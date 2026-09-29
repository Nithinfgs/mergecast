"""Thin, read-mostly wrappers around the ``git`` CLI.

mergecast never touches a working tree, index, ref or config. The only thing it
writes are unreachable snapshot objects (see :func:`snapshot_commit`), which
``git gc`` prunes on its own schedule.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

MIN_GIT = (2, 38)  # first release with `git merge-tree --write-tree`


class GitError(RuntimeError):
    """A git command failed or git is unusable."""


def run_git(
    args: list[str],
    cwd: str | Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    full_env = {**os.environ, "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}
    if env:
        full_env.update(env)
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            env=full_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment specific
        raise GitError("git executable not found on PATH") from exc
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def git_version() -> tuple[int, int]:
    out = run_git(["--version"], ".").stdout
    m = re.search(r"(\d+)\.(\d+)", out)
    if not m:
        raise GitError(f"cannot parse git version from {out!r}")
    return int(m.group(1)), int(m.group(2))


def ensure_supported_git() -> None:
    if git_version() < MIN_GIT:
        raise GitError("mergecast needs git >= 2.38 (for `git merge-tree --write-tree`)")


@dataclass(frozen=True)
class Worktree:
    path: str
    head: str
    branch: str | None  # short branch name, None when detached
    detached: bool

    @property
    def label(self) -> str:
        return self.branch if self.branch else f"(detached {self.head[:7]})"


def repo_root(cwd: str | Path) -> str:
    proc = run_git(["rev-parse", "--show-toplevel"], cwd, check=False)
    if proc.returncode != 0:
        raise GitError(f"{Path(cwd).resolve()} is not inside a git repository")
    return proc.stdout.strip()


def list_worktrees(cwd: str | Path) -> list[Worktree]:
    """Return every checked-out worktree of the repository containing *cwd*."""
    out = run_git(["worktree", "list", "--porcelain", "-z"], cwd).stdout
    result: list[Worktree] = []
    record: dict[str, str] = {}

    def flush() -> None:
        if not record or "worktree" not in record:
            return
        if "bare" in record or "prunable" in record or "HEAD" not in record:
            return
        if not Path(record["worktree"]).is_dir():
            return
        branch = record.get("branch")
        if branch and branch.startswith("refs/heads/"):
            branch = branch[len("refs/heads/") :]
        result.append(
            Worktree(
                path=record["worktree"],
                head=record["HEAD"],
                branch=branch,
                detached="detached" in record,
            )
        )

    for field in out.split("\0"):
        if field == "":
            flush()
            record = {}
            continue
        key, _, value = field.partition(" ")
        record[key] = value
    flush()
    # An unborn branch reports an all-zero HEAD; nothing to compare there.
    return [w for w in result if set(w.head) != {"0"}]


def dirty_paths(wt_path: str) -> list[str]:
    out = run_git(["status", "--porcelain=v1", "-z", "--untracked-files=all"], wt_path).stdout
    fields = out.split("\0")
    paths: list[str] = []
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if entry[0] in "RC":  # renames/copies carry the source path as an extra field
            i += 1
    return paths


_IDENTITY = {
    "GIT_AUTHOR_NAME": "mergecast",
    "GIT_AUTHOR_EMAIL": "mergecast@localhost",
    "GIT_COMMITTER_NAME": "mergecast",
    "GIT_COMMITTER_EMAIL": "mergecast@localhost",
}


def snapshot_commit(wt_path: str, head: str) -> str:
    """Commit-ish object capturing HEAD + all uncommitted and untracked work.

    A private copy of the worktree's index is used, so the real index, the
    working tree and every ref stay untouched. ``.gitignore`` is respected.
    """
    with tempfile.TemporaryDirectory(prefix="mergecast-") as td:
        tmp_index = os.path.join(td, "index")
        real_index = run_git(["rev-parse", "--path-format=absolute", "--git-path", "index"], wt_path).stdout.strip()
        if os.path.exists(real_index):
            shutil.copyfile(real_index, tmp_index)
        env = {"GIT_INDEX_FILE": tmp_index}
        run_git(["add", "-A"], wt_path, env=env)
        tree = run_git(["write-tree"], wt_path, env=env).stdout.strip()
        return run_git(
            ["commit-tree", tree, "-p", head, "-m", "mergecast snapshot"],
            wt_path,
            env={**env, **_IDENTITY},
        ).stdout.strip()


def rev_parse(cwd: str, rev: str) -> str | None:
    proc = run_git(["rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"], cwd, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def detect_base(cwd: str) -> str | None:
    """Best-effort default branch: origin/HEAD, else main/master/trunk/develop."""
    proc = run_git(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], cwd, check=False)
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    for name in ("main", "master", "trunk", "develop"):
        if rev_parse(cwd, f"refs/heads/{name}"):
            return name
    return None


def merge_base(cwd: str, a: str, b: str) -> str | None:
    proc = run_git(["merge-base", a, b], cwd, check=False)
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None


def ahead_behind(cwd: str, tip: str, base: str) -> tuple[int, int]:
    out = run_git(["rev-list", "--left-right", "--count", f"{tip}...{base}"], cwd).stdout.split()
    return int(out[0]), int(out[1])


def changed_files(cwd: str, base: str, tip: str) -> list[str]:
    out = run_git(["diff", "--name-only", "-z", "--no-renames", base, tip], cwd).stdout
    return [p for p in out.split("\0") if p]


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


def hunk_ranges(cwd: str, base: str, tip: str, path: str) -> list[tuple[int, int]]:
    """Line ranges (in *base* coordinates) that *tip* modified in *path*.

    Using the merge-base side makes ranges from two different tips comparable.
    Pure insertions become a one-line range at the insertion point.
    """
    out = run_git(["diff", "-U0", "--no-color", "--no-ext-diff", "--no-renames", base, tip, "--", path], cwd).stdout
    ranges: list[tuple[int, int]] = []
    for line in out.splitlines():
        m = _HUNK.match(line)
        if not m:
            continue
        start = int(m.group(1))
        length = 1 if m.group(2) is None else int(m.group(2))
        ranges.append((start, start) if length == 0 else (start, start + length - 1))
    return ranges


def trial_merge(cwd: str, a: str, b: str) -> tuple[bool, list[str]]:
    """Simulate merging *b* into *a* in memory. Returns (clean, conflicted paths)."""
    proc = run_git(["merge-tree", "--write-tree", "--name-only", "--no-messages", "-z", a, b], cwd, check=False)
    if proc.returncode == 0:
        return True, []
    if proc.returncode != 1:
        raise GitError(f"git merge-tree failed: {proc.stderr.strip()}")
    parts = proc.stdout.split("\0")
    paths = []
    for p in parts[1:]:  # parts[0] is the result tree id
        if p == "":
            break
        paths.append(p)
    return False, sorted(set(paths))
