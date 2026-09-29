from __future__ import annotations

import json

from mergecast.cli import main

from .conftest import add_worktree, edit_line, git


def collide(repo):
    a, b = add_worktree(repo, "a"), add_worktree(repo, "b")
    edit_line(a, "shared.txt", 7, "a")
    edit_line(b, "shared.txt", 7, "b")
    return a, b


def test_default_scan_text(repo, capsys, monkeypatch):
    collide(repo)
    monkeypatch.setenv("NO_COLOR", "1")
    assert main(["-C", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "CONFLICT" in out and "shared.txt" in out and "\x1b[" not in out


def test_fail_on_thresholds(repo):
    collide(repo)
    assert main(["scan", "-C", str(repo), "--fail-on", "conflict", "--format", "json"]) == 1
    assert main(["scan", "-C", str(repo), "--fail-on", "never", "--format", "json"]) == 0


def test_json_output_is_valid(repo, capsys):
    collide(repo)
    main(["scan", "-C", str(repo), "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert data["worst"] == "conflict"
    assert data["pairs"][0]["files"][0]["path"] == "shared.txt"


def test_markdown_output(repo, capsys):
    collide(repo)
    main(["scan", "-C", str(repo), "--format", "md"])
    assert "| 🔴 conflict |" in capsys.readouterr().out


def test_who_check(repo, capsys):
    a, b = collide(repo)
    assert main(["who", "shared.txt", "-C", str(a), "--check"]) == 1  # b touches it
    assert main(["who", "other.txt", "-C", str(a), "--check"]) == 0
    capsys.readouterr()
    main(["who", "shared.txt", "-C", str(a), "--format", "json"])
    assert [h["branch"] for h in json.loads(capsys.readouterr().out)] == ["b"]


def test_not_a_repo_exits_2(tmp_path, capsys):
    assert main(["-C", str(tmp_path)]) == 2
    assert "not inside a git repository" in capsys.readouterr().err


def test_single_worktree_message(repo, capsys):
    assert main(["-C", str(repo)]) == 0
    assert "nothing to compare" in capsys.readouterr().out


def test_committed_only_flag(repo):
    collide(repo)
    assert main(["-C", str(repo), "--committed-only", "--fail-on", "overlap", "--format", "json"]) == 0
    git(repo, "status")  # repo still healthy
