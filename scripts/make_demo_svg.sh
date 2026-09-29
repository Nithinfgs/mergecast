#!/usr/bin/env bash
# Regenerates docs/assets/*.svg from real mergecast output on the demo repo.
set -euo pipefail
cd "$(dirname "$0")/.."
DEMO="$(scripts/demo_repo.sh)"
( cd "$DEMO" && FORCE_COLOR=1 python3 -m mergecast ) | PYTHONPATH=src python3 scripts/ansi2svg.py > docs/assets/demo.svg
echo "wrote docs/assets/demo.svg"
