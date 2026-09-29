from __future__ import annotations

import pytest

from mergecast.analyze import analyze, who_touches
from mergecast.gitutil import GitError
from mergecast.model import Severity

from .conftest import add_worktree, edit_line, git


def pair(report, a, b):
    for p in report.pairs:
        if {p.a, p.b} == {a, b}:
            return p
    raise AssertionError(f"no pair {a}/{b}: {[(p.a, p.b) for p in report.pairs]}")


def test_same_lines_committed_is_conflict(repo):
    a, b = add_worktree(repo, "a"), add_worktree(repo, "b")
    edit_line(a, "shared.txt", 50, "from a")
    git(a, "commit", "-qam", "a")
    edit_line(b, "shared.txt", 50, "from b")
    git(b, "commit", "-qam", "b")
    p = pair(analyze(repo), "a", "b")
    assert p.severity == Severity.CONFLICT
    assert [f.path for f in p.files] == ["shared.txt"]
    assert p.files[0].conflict


def test_uncommitted_and_untracked_work_is_counted(repo):
    a, b = add_worktree(repo, "a"), add_worktree(repo, "b")
    edit_line(a, "shared.txt", 10, "dirty a")  # never committed
    edit_line(b, "shared.txt", 10, "dirty b")
    assert pair(analyze(repo), "a", "b").severity == Severity.CONFLICT
    # committed-only: both worktrees are identical to base, so nothing is forecast
    assert analyze(repo, include_uncommitted=False).pairs == []

    (a / "new.txt").write_text("x\n")
    (b / "new.txt").write_text("y\n")  # add/add conflict on untracked files
    files = {f.path: f for f in pair(analyze(repo), "a", "b").files}
    assert files["new.txt"].conflict


def test_close_edits_are_risk_far_edits_are_overlap(repo):
    a, b, c = (add_worktree(repo, n) for n in "abc")
    edit_line(a, "shared.txt", 10, "a")
    edit_line(b, "shared.txt", 15, "b")  # 5 lines away, git merges cleanly
    edit_line(c, "shared.txt", 90, "c")
    for w in (a, b, c):
        git(w, "commit", "-qam", "x")
    r = analyze(repo, near=20)
    assert pair(r, "a", "b").severity == Severity.RISK
    assert pair(r, "a", "c").severity == Severity.OVERLAP
    assert pair(analyze(repo, near=2), "a", "b").severity == Severity.OVERLAP


def test_disjoint_files_are_clean(repo):
    a, b = add_worktree(repo, "a"), add_worktree(repo, "b")
    edit_line(a, "shared.txt", 1, "a")
    edit_line(b, "other.txt", 1, "b")
    assert pair(analyze(repo), "a", "b").severity == Severity.CLEAN


def test_delete_vs_modify_is_conflict(repo):
    a, b = add_worktree(repo, "a"), add_worktree(repo, "b")
    git(a, "rm", "-q", "other.txt")
    git(a, "commit", "-qm", "rm")
    edit_line(b, "other.txt", 3, "changed")
    p = pair(analyze(repo), "a", "b")
    assert p.severity == Severity.CONFLICT
    assert p.files[0].path == "other.txt"


def test_vs_base_and_ahead_behind(repo):
    a = add_worktree(repo, "a")
    edit_line(a, "shared.txt", 5, "a")
    git(a, "commit", "-qam", "a")
    edit_line(repo, "shared.txt", 5, "main")
    git(repo, "commit", "-qam", "main moves")
    r = analyze(repo)
    node = next(n for n in r.nodes if n.label == "a")
    assert (node.ahead, node.behind) == (1, 1)
    assert node.vs_base == Severity.CONFLICT
    assert node.vs_base_files == ["shared.txt"]


def test_clean_base_checkout_is_not_a_peer(repo):
    a, b, c = (add_worktree(repo, n) for n in "abc")
    edit_line(a, "shared.txt", 1, "a")
    edit_line(b, "shared.txt", 2, "b")
    git(a, "commit", "-qam", "a")
    r = analyze(repo)  # main and the untouched worktree c never appear as peers
    assert {x for p in r.pairs for x in (p.a, p.b)} == {"a", "b"}
    assert len(r.pairs) == 1 and c.exists()


def test_analysis_is_read_only(repo):
    a, b = add_worktree(repo, "a"), add_worktree(repo, "b")
    edit_line(a, "shared.txt", 2, "dirty")
    (b / "untracked.txt").write_text("u\n")
    before = {w: (git(w, "status", "--porcelain=v2"), git(w, "rev-parse", "HEAD")) for w in (repo, a, b)}
    refs = git(repo, "for-each-ref")
    index = (a / ".git").read_text()  # linked worktree pointer file must be untouched
    analyze(repo)
    after = {w: (git(w, "status", "--porcelain=v2"), git(w, "rev-parse", "HEAD")) for w in (repo, a, b)}
    assert before == after
    assert refs == git(repo, "for-each-ref")
    assert index == (a / ".git").read_text()
    assert (b / "untracked.txt").read_text() == "u\n"
    # untracked file must not have been staged in the real index
    assert "?? untracked.txt" in git(b, "status", "--porcelain")


def test_who_touches(repo):
    a, b = add_worktree(repo, "a"), add_worktree(repo, "b")
    edit_line(a, "shared.txt", 1, "a")
    git(a, "commit", "-qam", "a")
    (b / "shared.new").write_text("n\n")
    r = analyze(repo)
    hits = who_touches(r, ["shared.*"])
    assert {n.label: f for n, f in hits} == {"a": ["shared.txt"], "b": ["shared.new"]}
    assert [n.label for n, _ in who_touches(r, ["shared.txt"], exclude_path=str(a))] == []


def test_single_worktree_and_bad_inputs(repo, tmp_path):
    r = analyze(repo)
    assert r.pairs == [] and len(r.nodes) == 1
    with pytest.raises(GitError):
        analyze(repo, base="does-not-exist")
    outside = tmp_path / "nowhere"
    outside.mkdir()
    with pytest.raises(GitError):
        analyze(outside)


def test_detached_head_worktree(repo):
    d = repo.parent / "det"
    git(repo, "worktree", "add", "-q", "--detach", str(d))
    edit_line(d, "shared.txt", 1, "d")
    r = analyze(repo)
    assert any(n.label.startswith("(detached ") for n in r.nodes)
