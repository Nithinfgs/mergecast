#!/usr/bin/env bash
# Claude Code PreToolUse hook: before an agent edits a file, tell it if a sibling
# worktree is already changing that file. Exit code 2 feeds stderr back to the agent.
# Register under hooks -> PreToolUse, matcher "Edit|Write|MultiEdit" in .claude/settings.json.
set -euo pipefail
input="$(cat)"
file="$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))')"
[ -z "$file" ] && exit 0
root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
rel="${file#"$root"/}"
if out="$(mergecast who "$rel" --check --format text --no-color 2>&1)"; then
  exit 0
fi
{
  echo "mergecast: another worktree is already changing $rel:"
  echo "$out"
  echo "Consider coordinating, or pick a different file, to avoid a merge conflict."
} >&2
exit 2
