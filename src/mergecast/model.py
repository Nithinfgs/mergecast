"""Plain data types shared by the analyzer and the renderers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class Severity(IntEnum):
    """Ordered so that ``max()`` picks the worst one."""

    CLEAN = 0
    OVERLAP = 1  # same file touched on both sides, regions far apart
    RISK = 2  # same file, edits close together, but git merges cleanly
    CONFLICT = 3  # git itself cannot merge these two

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass
class Node:
    """One thing that can be merged: a worktree snapshot."""

    path: str
    label: str
    head: str
    snapshot: str  # commit id including uncommitted work
    dirty_files: list[str] = field(default_factory=list)
    ahead: int | None = None
    behind: int | None = None
    vs_base: Severity | None = None
    vs_base_files: list[str] = field(default_factory=list)
    touched: list[str] = field(default_factory=list)  # files changed since the base


@dataclass
class FileFinding:
    path: str
    conflict: bool
    a_ranges: list[tuple[int, int]] = field(default_factory=list)
    b_ranges: list[tuple[int, int]] = field(default_factory=list)
    near: bool = False  # closest pair of edits is within the --near window


@dataclass
class PairResult:
    a: str  # node label
    b: str
    a_path: str
    b_path: str
    severity: Severity
    files: list[FileFinding] = field(default_factory=list)


@dataclass
class Report:
    repo: str
    base: str | None
    base_commit: str | None
    near: int
    nodes: list[Node]
    pairs: list[PairResult]

    @property
    def worst(self) -> Severity:
        sev = [p.severity for p in self.pairs]
        sev += [n.vs_base for n in self.nodes if n.vs_base is not None]
        return max(sev, default=Severity.CLEAN)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "base": self.base,
            "base_commit": self.base_commit,
            "near_lines": self.near,
            "worst": self.worst.label,
            "worktrees": [
                {
                    "path": n.path,
                    "branch": n.label,
                    "head": n.head,
                    "dirty_files": n.dirty_files,
                    "ahead": n.ahead,
                    "behind": n.behind,
                    "vs_base": n.vs_base.label if n.vs_base is not None else None,
                    "vs_base_conflicts": n.vs_base_files,
                    "touched": n.touched,
                }
                for n in self.nodes
            ],
            "pairs": [
                {
                    "a": p.a,
                    "b": p.b,
                    "a_path": p.a_path,
                    "b_path": p.b_path,
                    "severity": p.severity.label,
                    "files": [
                        {
                            "path": f.path,
                            "conflict": f.conflict,
                            "near": f.near,
                            "a_ranges": [list(r) for r in f.a_ranges],
                            "b_ranges": [list(r) for r in f.b_ranges],
                        }
                        for f in p.files
                    ],
                }
                for p in self.pairs
            ],
        }
