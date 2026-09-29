"""Forecast merge trouble between worktrees.

For every pair of worktrees we (1) ask git to simulate the merge in memory and
(2) look at which files and line ranges each side changed relative to their
merge-base. (1) yields hard conflicts; (2) surfaces the softer risk of two
agents editing the same file or the same neighbourhood even when git would
happily merge the text.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path

from . import gitutil as g
from .model import FileFinding, Node, PairResult, Report, Severity

DEFAULT_NEAR = 20


def _ranges_near(a: list[tuple[int, int]], b: list[tuple[int, int]], window: int) -> bool:
    for a0, a1 in a:
        for b0, b1 in b:
            gap = max(a0, b0) - min(a1, b1)
            if gap <= window:
                return True
    return False


def build_nodes(repo: str, include_uncommitted: bool = True) -> list[Node]:
    nodes: list[Node] = []
    for wt in g.list_worktrees(repo):
        dirty = g.dirty_paths(wt.path)
        snap = g.snapshot_commit(wt.path, wt.head) if (dirty and include_uncommitted) else wt.head
        nodes.append(
            Node(
                path=wt.path,
                label=wt.label,
                head=wt.head,
                snapshot=snap,
                dirty_files=dirty if include_uncommitted else [],
            )
        )
    return nodes


def compare_pair(repo: str, a: Node, b: Node, near: int) -> PairResult:
    result = PairResult(a=a.label, b=b.label, a_path=a.path, b_path=b.path, severity=Severity.CLEAN)
    if a.snapshot == b.snapshot:
        return result
    mb = g.merge_base(repo, a.snapshot, b.snapshot)
    if mb is None:  # unrelated histories
        return result
    clean, conflicted = g.trial_merge(repo, a.snapshot, b.snapshot)
    a_files = set(g.changed_files(repo, mb, a.snapshot))
    b_files = set(g.changed_files(repo, mb, b.snapshot))
    shared = sorted((a_files & b_files) | set(conflicted))
    worst = Severity.CLEAN if clean else Severity.CONFLICT
    for path in shared:
        a_r = g.hunk_ranges(repo, mb, a.snapshot, path)
        b_r = g.hunk_ranges(repo, mb, b.snapshot, path)
        is_conflict = path in conflicted
        is_near = is_conflict or _ranges_near(a_r, b_r, near)
        result.files.append(FileFinding(path, is_conflict, a_r, b_r, is_near))
        if not is_conflict:
            worst = max(worst, Severity.RISK if is_near else Severity.OVERLAP)
    result.severity = worst
    return result


def analyze(
    start: str | Path = ".",
    base: str | None = None,
    include_uncommitted: bool = True,
    near: int = DEFAULT_NEAR,
) -> Report:
    g.ensure_supported_git()
    repo = g.repo_root(start)
    base_ref = base or g.detect_base(repo)
    base_commit = g.rev_parse(repo, base_ref) if base_ref else None
    if base and base_commit is None:
        raise g.GitError(f"base ref {base!r} not found")

    nodes = build_nodes(repo, include_uncommitted)

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(nodes)))) as pool:
        # A clean checkout of the base branch has nothing to collide; skip it as a peer.
        peers = [n for n in nodes if n.snapshot != base_commit]
        pair_futures = [pool.submit(compare_pair, repo, a, b, near) for a, b in combinations(peers, 2)]
        if base_commit:
            base_futures = [pool.submit(_vs_base, repo, n, base_commit) for n in nodes]
            for fut in base_futures:
                fut.result()
        pairs = [f.result() for f in pair_futures]

    pairs.sort(key=lambda p: (-p.severity, p.a, p.b))
    return Report(repo=repo, base=base_ref, base_commit=base_commit, near=near, nodes=nodes, pairs=pairs)


def _vs_base(repo: str, node: Node, base_commit: str) -> None:
    node.ahead, node.behind = g.ahead_behind(repo, node.snapshot, base_commit)
    mb = g.merge_base(repo, node.snapshot, base_commit)
    if mb is None:
        return
    node.touched = g.changed_files(repo, mb, node.snapshot)
    if node.snapshot == base_commit or node.behind == 0:
        node.vs_base = Severity.CLEAN  # fast-forwardable
        return
    clean, conflicted = g.trial_merge(repo, node.snapshot, base_commit)
    node.vs_base = Severity.CLEAN if clean else Severity.CONFLICT
    node.vs_base_files = conflicted


def who_touches(report: Report, patterns: list[str], exclude_path: str | None = None) -> list[tuple[Node, list[str]]]:
    """Which worktrees have changed files matching any glob in *patterns*?"""
    from fnmatch import fnmatch

    hits: list[tuple[Node, list[str]]] = []
    for n in report.nodes:
        if exclude_path and Path(n.path).resolve() == Path(exclude_path).resolve():
            continue
        files = sorted(set(n.touched) | set(n.dirty_files))
        matched = [f for f in files if any(fnmatch(f, p) or f == p for p in patterns)]
        if matched:
            hits.append((n, matched))
    return hits
