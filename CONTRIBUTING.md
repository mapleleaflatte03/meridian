# Contributing to Meridian

Meridian is an open research platform for governed local AI agents. Contributions are welcome across runtime, governance, and documentation.

## Before You Start

1. Read [`README.md`](README.md) and [`docs/REPO_MIGRATION_MAP.md`](docs/REPO_MIGRATION_MAP.md).
2. Confirm work targets this monorepo (archived mirrors are read-only).
3. Open an issue first for larger changes.

## Local Setup

```bash
./scripts/bootstrap_full.sh
```

Run module tests before submitting a PR:

```bash
# Loom
cargo test --manifest-path loom/Cargo.toml --workspace

# Kernel
cd kernel
python3 -m unittest discover -s kernel/tests -p 'test_*.py'
python3 -m unittest discover -s economy/tests -p 'test_*.py'

# Intelligence
cd ../intelligence
python3 -m unittest -v test_gateway_brain_router.py
```

## PR Expectations

1. Keep changes scoped to one problem.
2. Add or update tests for behavior changes.
3. Include before/after evidence for API/UI changes.
4. Preserve governance-first semantics (Institution, Agent, Authority, Treasury, Court, PoGE).

## Community

- Discussions: https://github.com/mapleleaflatte03/meridian/discussions
- Issues: https://github.com/mapleleaflatte03/meridian/issues/new/choose
- Sponsors: https://github.com/sponsors/mapleleaflatte03
