#!/usr/bin/env python3
"""Render ANSI-coloured terminal output (stdin) as a dark-theme SVG (stdout).

Used to produce docs/assets/demo.svg from real mergecast output:
    scripts/make_demo_svg.sh
"""
import re
import sys
from xml.sax.saxutils import escape

COLORS = {"31": "#ff6b6b", "32": "#69db7c", "33": "#ffd43b", "34": "#74c0fc", "36": "#66d9e8"}
FG, DIM = "#d8dee9", "#7b8496"
CW, LH, PAD = 8.4, 20, 22


def main() -> None:
    text = sys.stdin.read().rstrip("\n")
    lines = text.split("\n")
    width = int(max(len(re.sub(r"\x1b\[[0-9;]*m", "", ln)) for ln in lines) * CW + PAD * 2)
    height = LH * len(lines) + PAD * 2 + 30
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" rx="10" fill="#14171f"/>',
        '<circle cx="20" cy="18" r="6" fill="#ff5f56"/><circle cx="40" cy="18" r="6" fill="#ffbd2e"/>'
        '<circle cx="60" cy="18" r="6" fill="#27c93f"/>',
        '<g font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="14" xml:space="preserve">',
    ]
    for row, line in enumerate(lines):
        y = PAD + 30 + row * LH
        spans, color, bold, col = [], FG, False, 0
        for part in re.split(r"(\x1b\[[0-9;]*m)", line):
            if part.startswith("\x1b["):
                for code in part[2:-1].split(";"):
                    if code in ("0", ""):
                        color, bold = FG, False
                    elif code == "1":
                        bold = True
                    elif code == "2":
                        color = DIM
                    elif code in COLORS:
                        color = COLORS[code]
            elif part:
                x = PAD + col * CW
                w = ' font-weight="700"' if bold else ""
                spans.append(f'<text x="{x:.1f}" y="{y}" fill="{color}"{w}>{escape(part).replace(' ', chr(160))}</text>')
                col += len(part)
        out.extend(spans)
    out.append("</g></svg>")
    print("\n".join(out))


main()
