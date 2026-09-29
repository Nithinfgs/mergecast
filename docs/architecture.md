# Architecture

```
src/mergecast/
  gitutil.py   subprocess wrappers around git (worktrees, snapshots, merge-tree, diffs)
  model.py     dataclasses: Node, FileFinding, PairResult, Report, Severity
  analyze.py   orchestration: build nodes -> compare pairs (thread pool) -> Report
  render.py    text / markdown / json renderers (no I/O besides returning strings)
  cli.py       argparse front-end: scan, watch, who
```

## Data flow

1. `list_worktrees` parses `git worktree list --porcelain -z`. Bare, prunable, missing and unborn worktrees are skipped.
2. For each worktree, `dirty_paths` runs `git status`. If dirty, `snapshot_commit` copies the worktree's index to a
   temp file, points `GIT_INDEX_FILE` at it, runs `git add -A`, `write-tree`, `commit-tree -p HEAD`. The result is a
   commit that represents "HEAD + everything on disk" without touching the real index.
3. Every pair `(a, b)` of peers goes through `compare_pair`:
   - `git merge-base a b`
   - `git merge-tree --write-tree --name-only --no-messages -z a b`: exit 0 clean, 1 conflicted (file list on stdout)
   - `git diff --name-only mb a|b` gives touched files; the intersection plus conflicted paths are "shared"
   - `git diff -U0 mb a|b -- path` gives hunk ranges **in merge-base coordinates**, so ranges from both sides are comparable
   - severity: conflict > risk (ranges within `--near` lines) > overlap > clean
4. Each node is also compared to the base ref (ahead/behind, would-it-conflict-on-merge).
5. Renderers turn the `Report` into text, Markdown or JSON.

## Decisions

- **Shell out to git rather than use a library.** `merge-tree --write-tree` is the same engine that will perform the
  real merge, so the forecast matches reality for textual conflicts. It also keeps the dependency count at zero.
- **Snapshots via temp index.** Alternatives (`git stash create`, copying the worktree) either miss untracked files or
  are slow. The cost is a few unreachable loose objects.
- **Clean base checkouts are not peers.** A worktree identical to base can't collide, and listing it only adds noise.
- **Severity has a heuristic middle tier.** "Risk" (nearby edits) is deliberately separate from "conflict" so that
  `--fail-on conflict` remains a hard guarantee.

## Testing

`tests/` builds real repositories and worktrees in temp dirs (no mocks of git). Cases: same-line conflicts,
uncommitted/untracked work, add/add, delete-vs-modify, proximity tiers, behind-base conflicts, detached HEAD,
single worktree, invalid input, CLI exit codes and formats, and a read-only guarantee (status, HEAD, refs unchanged).
