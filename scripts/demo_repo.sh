#!/usr/bin/env bash
# Builds a throwaway repo with four "agent" worktrees that collide in different ways.
# Usage: scripts/demo_repo.sh [target-dir]   (default: /tmp/mergecast-demo)
set -euo pipefail
ROOT="${1:-/tmp/mergecast-demo}"
rm -rf "$ROOT"; mkdir -p "$ROOT/shop"; cd "$ROOT/shop"
git init -q -b main
git config user.name demo; git config user.email demo@example.com

mkdir -p src tests
python3 - <<'PY'
lines = ["# session handling", "import time", ""]
for i in range(1, 61):
    lines.append(f"def step_{i}():\n    return {i}\n")
open("src/session.py", "w").write("\n".join(lines))
open("src/billing.py", "w").write("\n".join(f"line_{i} = {i}" for i in range(1, 80)) + "\n")
open("src/api.py", "w").write("\n".join(f"route_{i} = {i}" for i in range(1, 80)) + "\n")
open("README.md", "w").write("# shop\n")
PY
git add -A && git commit -qm "initial"

git worktree add -q ../agent-auth    -b agent/auth
git worktree add -q ../agent-billing -b agent/billing
git worktree add -q ../agent-api     -b agent/api
git worktree add -q ../agent-docs    -b agent/docs

# agent/auth and agent/billing edit the SAME lines of session.py (hard conflict)
( cd ../agent-auth
  sed -i.bak 's/^    return 12$/    return 12  # auth: expire tokens/' src/session.py && rm src/session.py.bak
  git commit -qam "auth: token expiry" )
( cd ../agent-billing
  sed -i.bak 's/^    return 12$/    return 12  # billing: per-seat/' src/session.py && rm src/session.py.bak
  echo "# billing uses sessions" >> src/session.py   # uncommitted work, still counted
  sed -i.bak 's/^line_40 = 40$/line_40 = 4000/' src/billing.py && rm src/billing.py.bak )

# agent/api edits billing.py a few lines away from billing's change (git merges, but risky)
( cd ../agent-api
  sed -i.bak 's/^line_45 = 45$/line_45 = "api"/' src/billing.py && rm src/billing.py.bak
  sed -i.bak 's/^route_3 = 3$/route_3 = "v2"/' src/api.py && rm src/api.py.bak
  git commit -qam "api: v2 route" )

# agent/docs only touches a far-away file in api.py's territory and README
( cd ../agent-docs
  sed -i.bak 's/^route_70 = 70$/route_70 = "docs"/' src/api.py && rm src/api.py.bak
  echo "docs" >> README.md
  git commit -qam "docs" )

# main moves on, so branches are behind it
echo "release = '1.1'" >> src/billing.py; git commit -qam "main: release marker"
echo "$ROOT/shop"
