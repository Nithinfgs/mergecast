"""Terminal, Markdown and JSON output."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import TextIO

from .model import FileFinding, Node, PairResult, Report, Severity

_CODES = {"red": "31", "yellow": "33", "blue": "34", "green": "32", "dim": "2", "bold": "1", "cyan": "36"}
_COLOR_OF = {
    Severity.CONFLICT: "red",
    Severity.RISK: "yellow",
    Severity.OVERLAP: "blue",
    Severity.CLEAN: "green",
}
_ICON = {Severity.CONFLICT: "✖", Severity.RISK: "▲", Severity.OVERLAP: "◆", Severity.CLEAN: "✔"}
_ASCII_ICON = {Severity.CONFLICT: "x", Severity.RISK: "!", Severity.OVERLAP: "~", Severity.CLEAN: "ok"}


def use_color(stream: TextIO | None = None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


class Style:
    def __init__(self, color: bool, unicode: bool = True):
        self.color = color
        self.unicode = unicode

    def paint(self, text: str, *names: str) -> str:
        if not self.color or not names:
            return text
        return f"\x1b[{';'.join(_CODES[n] for n in names)}m{text}\x1b[0m"

    def sev(self, s: Severity, text: str | None = None, bold: bool = False) -> str:
        text = text if text is not None else s.label
        return self.paint(text, _COLOR_OF[s], *(("bold",) if bold else ()))

    def icon(self, s: Severity) -> str:
        return self.sev(s, (_ICON if self.unicode else _ASCII_ICON)[s])


def _fmt_ranges(ranges: list[tuple[int, int]], limit: int = 3) -> str:
    if not ranges:
        return "—"
    parts = [f"{a}" if a == b else f"{a}-{b}" for a, b in ranges[:limit]]
    if len(ranges) > limit:
        parts.append(f"+{len(ranges) - limit}")
    return ",".join(parts)


def _short_path(path: str, repo: str) -> str:
    home = str(Path.home())
    try:
        rel = os.path.relpath(path, Path(repo).parent)
        if not rel.startswith(".."):
            return rel
    except ValueError:
        pass
    return "~" + path[len(home) :] if path.startswith(home) else path


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - len(text))


def render_text(report: Report, style: Style, verbose: bool = False) -> str:
    out: list[str] = []
    p = style.paint
    base = f"{report.base} ({report.base_commit[:7]})" if report.base and report.base_commit else "none detected"
    out.append(p("mergecast", "bold") + p(f" · {len(report.nodes)} worktrees · base {base}", "dim"))
    out.append("")

    if len(report.nodes) < 2:
        out.append("Only one worktree found — nothing to compare against.")
        out.append(p("Create more with `git worktree add ../feature -b feature`.", "dim"))
        if report.nodes:
            out.append("")
            out.extend(_node_table(report, style))
        return "\n".join(out) + "\n"

    out.extend(_node_table(report, style))
    out.append("")

    bad = [pr for pr in report.pairs if pr.severity > Severity.CLEAN]
    if not bad:
        out.append(style.icon(Severity.CLEAN) + " " + p("No collisions forecast between worktrees.", "green"))
    for pr in bad:
        out.extend(_pair_block(pr, style, report.near, verbose))

    base_bad = [n for n in report.nodes if n.vs_base == Severity.CONFLICT]
    if base_bad and report.base:
        out.append("")
        out.append(p(f"Would conflict with {report.base}:", "bold"))
        for n in base_bad:
            files = ", ".join(n.vs_base_files[:4]) + (" …" if len(n.vs_base_files) > 4 else "")
            out.append(f"  {style.icon(Severity.CONFLICT)} {n.label}  {p(files, 'dim')}")

    counts = {s: sum(1 for pr in report.pairs if pr.severity == s) for s in Severity}
    out.append("")
    out.append(
        "  ".join(
            style.sev(s, f"{counts[s]} {s.label}")
            for s in (Severity.CONFLICT, Severity.RISK, Severity.OVERLAP, Severity.CLEAN)
        )
        + p(f"  of {len(report.pairs)} pairs", "dim")
    )
    return "\n".join(out) + "\n"


def _node_table(report: Report, style: Style) -> list[str]:
    p = style.paint
    rows = []
    for n in report.nodes:
        div = "—"
        if n.ahead is not None and n.behind is not None:
            div = f"+{n.ahead} -{n.behind}"
        rows.append(
            (
                n.label,
                _short_path(n.path, report.repo),
                div,
                str(len(n.dirty_files)) if n.dirty_files else "·",
                n,
            )
        )
    w_branch = max(8, *(len(r[0]) for r in rows))
    w_path = max(4, *(len(r[1]) for r in rows))
    w_div = max(6, *(len(r[2]) for r in rows))
    head = f"  {_pad('BRANCH', w_branch)}  {_pad('PATH', w_path)}  {_pad('Δ BASE', w_div)}  DIRTY  BASE MERGE"
    lines = [p(head, "dim")]
    for branch, path, div, dirty, n in rows:
        if n.vs_base is None:
            status = p("—", "dim")
        elif n.vs_base == Severity.CONFLICT:
            status = style.sev(Severity.CONFLICT, f"{_ICON[Severity.CONFLICT] if style.unicode else 'x'} conflicts")
        elif n.behind == 0:
            status = style.sev(Severity.CLEAN, "up to date")
        else:
            status = style.sev(Severity.CLEAN, "clean")
        lines.append(
            f"  {p(_pad(branch, w_branch), 'bold')}  {_pad(path, w_path)}  {_pad(div, w_div)}  {_pad(dirty, 5)}  {status}"
        )
    return lines


def _pair_block(pr: PairResult, style: Style, near: int, verbose: bool) -> list[str]:
    p = style.paint
    arrow = "↔" if style.unicode else "<->"
    lines = [
        f"{style.icon(pr.severity)} {style.sev(pr.severity, pr.severity.label.upper(), bold=True)}  "
        f"{p(pr.a, 'bold')} {arrow} {p(pr.b, 'bold')}"
    ]
    shown = pr.files if verbose else pr.files[:6]
    w = max((len(f.path) for f in shown), default=0)
    for f in shown:
        tag = _file_tag(f, near)
        lines.append(
            f"    {_pad(f.path, w)}  {p('lines', 'dim')} {_fmt_ranges(f.a_ranges)} {p('vs', 'dim')} {_fmt_ranges(f.b_ranges)}  {tag}"
            if (f.a_ranges or f.b_ranges)
            else f"    {_pad(f.path, w)}  {tag}"
        )
    if len(pr.files) > len(shown):
        lines.append(p(f"    … {len(pr.files) - len(shown)} more (use --verbose)", "dim"))
    lines.append("")
    return lines


def _file_tag(f: FileFinding, near: int) -> str:
    if f.conflict:
        return "conflict"
    if f.near:
        return f"close (≤{near} lines)"
    return "same file, far apart"


def render_who(hits: list[tuple[Node, list[str]]], style: Style) -> str:
    if not hits:
        return style.paint("No other worktree is touching those paths.", "green") + "\n"
    lines = []
    for n, files in hits:
        lines.append(style.paint(n.label, "bold") + style.paint(f"  {n.path}", "dim"))
        for f in files[:10]:
            lines.append(f"  {f}")
        if len(files) > 10:
            lines.append(style.paint(f"  … {len(files) - 10} more", "dim"))
    return "\n".join(lines) + "\n"


def render_markdown(report: Report) -> str:
    lines = [f"### mergecast forecast — {len(report.nodes)} worktrees, base `{report.base or 'n/a'}`", ""]
    bad = [pr for pr in report.pairs if pr.severity > Severity.CLEAN]
    if not bad:
        lines.append("✅ No collisions forecast.")
    else:
        lines += ["| | Pair | Files |", "|---|---|---|"]
        icon = {Severity.CONFLICT: "🔴", Severity.RISK: "🟠", Severity.OVERLAP: "🔵"}
        for pr in bad:
            files = "<br>".join(f"`{f.path}`" + (" (conflict)" if f.conflict else "") for f in pr.files[:8])
            lines.append(f"| {icon[pr.severity]} {pr.severity.label} | `{pr.a}` ↔ `{pr.b}` | {files} |")
    return "\n".join(lines) + "\n"


def render_json(report: Report) -> str:
    return json.dumps(report.to_dict(), indent=2) + "\n"


def clear_screen() -> str:
    return "\x1b[2J\x1b[H" if shutil.get_terminal_size().columns else ""
