from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": __import__("os").environ["PATH"],
            "HOME": str(cwd),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
        },
    ).stdout


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def numbered(n: int, prefix: str = "line") -> str:
    return "".join(f"{prefix}{i}\n" for i in range(1, n + 1))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Main checkout with a 100-line shared.txt and a 100-line other.txt on `main`."""
    root = tmp_path / "main"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    write(root / "shared.txt", numbered(100))
    write(root / "other.txt", numbered(100, "o"))
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    return root


def add_worktree(repo: Path, name: str) -> Path:
    path = repo.parent / name
    git(repo, "worktree", "add", "-q", str(path), "-b", name)
    return path


def edit_line(path: Path, filename: str, lineno: int, text: str) -> None:
    f = path / filename
    lines = f.read_text().splitlines(keepends=True)
    lines[lineno - 1] = text + "\n"
    f.write_text("".join(lines))
