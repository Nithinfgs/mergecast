# Contributing

Thanks for helping! mergecast is small on purpose: stdlib only, read-only, one job.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest && ruff check . && ruff format --check . && mypy src
```

- Tests use real temporary git repos (`tests/conftest.py`); please avoid mocking git.
- Keep the tool **read-only**: nothing may modify a working tree, the real index, refs or config. `test_analysis_is_read_only` guards this.
- No runtime dependencies without a strong reason.
- Update the README when behaviour changes, and don't claim more than the code does.
- Regenerate the README image with `scripts/make_demo_svg.sh` if output format changes.

Open an issue first for larger changes (e.g. anything on the roadmap).
