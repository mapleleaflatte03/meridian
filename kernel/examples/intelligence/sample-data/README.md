# Sample Data

This directory contains repo-local sample artifacts for the competitive
intelligence example.

It exists so the public OSS repo can demonstrate:
- `ci_vertical.py status`
- `ci_vertical.py post-mortem`
- `economy/auto_score.py --dry-run`
- `brief_quality.py`

without depending on a private runtime layout such as `~/.meridian/...`.

## Included Files

- `run-state.json` — minimal runtime state with a successful `deliver` job
- `brief-2026-03-20.md` — sample brief that passes the local quality gate
- `findings-2026-03-20.md` — sample findings with source and recency evidence
- `reports/run-2026-03-20.md` — sample pipeline report for post-mortem / dry-run scoring

The filenames are fixed reference artifacts, not promises about today's date.
The OSS example tooling resolves the latest sample artifacts by filename/mtime
so the public repo does not become invalid just because the calendar changes.

## Real Deployments

In a real deployment, point the example and scoring tools at your own artifact
directory with:

```bash
MERIDIAN_ARTIFACT_DIR=/path/to/artifacts
MERIDIAN_RUN_STATE_FILE=/path/to/run-state.json
```

The files in this directory are examples only. They are not production data.
