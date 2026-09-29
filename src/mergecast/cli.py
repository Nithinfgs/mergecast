"""Command line interface."""

from __future__ import annotations

import argparse
import sys
import time

from . import __version__
from .analyze import DEFAULT_NEAR, analyze, who_touches
from .gitutil import GitError, repo_root
from .model import Severity
from .render import (
    Style,
    clear_screen,
    render_json,
    render_markdown,
    render_text,
    render_who,
    use_color,
)

EXIT_OK, EXIT_FOUND, EXIT_ERROR = 0, 1, 2
_FAIL_ON = {"never": None, "overlap": Severity.OVERLAP, "risk": Severity.RISK, "conflict": Severity.CONFLICT}


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("-C", dest="path", default=".", metavar="DIR", help="run as if started in DIR (default: .)")
    p.add_argument("--base", metavar="REF", help="base branch to compare against (default: origin/HEAD, main, master…)")
    p.add_argument("--committed-only", action="store_true", help="ignore uncommitted and untracked changes")
    p.add_argument(
        "--near",
        type=int,
        default=DEFAULT_NEAR,
        metavar="N",
        help=f"lines apart at which two edits in one file count as 'risk' (default: {DEFAULT_NEAR})",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mergecast",
        description="Forecast merge conflicts between parallel git worktrees — including uncommitted work — "
        "before they happen. Read-only: never touches your working trees, index or branches.",
    )
    p.add_argument("--version", action="version", version=f"mergecast {__version__}")
    sub = p.add_subparsers(dest="command")

    scan = sub.add_parser("scan", help="one-shot forecast (default command)")
    _add_common(scan)
    scan.add_argument("--format", choices=["text", "json", "md"], default="text")
    scan.add_argument(
        "--fail-on",
        choices=list(_FAIL_ON),
        default="never",
        help="exit 1 if a pair reaches this severity (for CI/hooks)",
    )
    scan.add_argument("-v", "--verbose", action="store_true", help="list every affected file")
    scan.add_argument("--no-color", action="store_true")

    watch = sub.add_parser("watch", help="re-run the forecast continuously")
    _add_common(watch)
    watch.add_argument("-i", "--interval", type=float, default=3.0, help="seconds between refreshes (default: 3)")
    watch.add_argument("--no-color", action="store_true")

    who = sub.add_parser("who", help="which worktrees are changing these files?")
    _add_common(who)
    who.add_argument("patterns", nargs="+", metavar="PATH", help="file path or glob, relative to the repo root")
    who.add_argument("--include-self", action="store_true", help="also list the current worktree")
    who.add_argument("--check", action="store_true", help="exit 1 if another worktree touches a match")
    who.add_argument("--format", choices=["text", "json"], default="text")
    who.add_argument("--no-color", action="store_true")
    return p


def _style(args: argparse.Namespace) -> Style:
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    return Style(color=use_color() and not args.no_color, unicode="utf" in enc)


def _run_scan(args: argparse.Namespace) -> int:
    report = analyze(args.path, args.base, not args.committed_only, args.near)
    if args.format == "json":
        sys.stdout.write(render_json(report))
    elif args.format == "md":
        sys.stdout.write(render_markdown(report))
    else:
        sys.stdout.write(render_text(report, _style(args), args.verbose))
    threshold = _FAIL_ON[args.fail_on]
    pair_worst = max((p.severity for p in report.pairs), default=Severity.CLEAN)
    return EXIT_FOUND if threshold is not None and pair_worst >= threshold else EXIT_OK


def _run_watch(args: argparse.Namespace) -> int:
    style = _style(args)
    try:
        while True:
            report = analyze(args.path, args.base, not args.committed_only, args.near)
            frame = render_text(report, style)
            stamp = time.strftime("%H:%M:%S")
            sys.stdout.write(
                clear_screen()
                + frame
                + style.paint(f"\nupdated {stamp} · every {args.interval:g}s · Ctrl-C to quit\n", "dim")
            )
            sys.stdout.flush()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        return EXIT_OK


def _run_who(args: argparse.Namespace) -> int:
    report = analyze(args.path, args.base, not args.committed_only, args.near)
    me = None if args.include_self else repo_root(args.path)
    hits = who_touches(report, args.patterns, exclude_path=me)
    if args.format == "json":
        import json

        sys.stdout.write(
            json.dumps([{"branch": n.label, "path": n.path, "files": files} for n, files in hits], indent=2) + "\n"
        )
    else:
        sys.stdout.write(render_who(hits, _style(args)))
    return EXIT_FOUND if args.check and hits else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "scan")  # bare `mergecast` and `mergecast --format json` mean `scan`
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {"scan": _run_scan, "watch": _run_watch, "who": _run_who}
    try:
        return handlers[args.command](args)
    except GitError as exc:
        print(f"mergecast: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except BrokenPipeError:  # e.g. `mergecast | head`
        return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
