# Meridian (Monorepo)

Meridian is an open-source, governance-first stack for local AI labor:

- `loom/` — sovereign local runtime and PoGE execution layer (Rust)
- `kernel/` — constitutional governance core (Institution, Agent, Authority, Treasury, Court + 3-ledger economy)
- `intelligence/` — operator workspace, workflows, public surfaces, and gateway

## Why Monorepo

Meridian moved from a multi-repo layout to this monorepo to simplify onboarding and OSS contribution:

- one clone for the full stack
- one bootstrap entrypoint
- clear module boundaries preserved under `loom/`, `kernel/`, `intelligence/`

## One-Command Install

```bash
curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash
```

This clones (or reuses) the monorepo, initializes kernel state, prepares shared environment variables, and builds the Loom CLI from source.

If you already cloned the repo:

```bash
./scripts/bootstrap_full.sh
```

## Module Commands

```bash
# Loom tests
cargo test --manifest-path loom/Cargo.toml --workspace

# Kernel tests
cd kernel
python3 -m unittest discover -s kernel/tests -p 'test_*.py'
python3 -m unittest discover -s economy/tests -p 'test_*.py'

# Intelligence gateway tests
cd ../intelligence
python3 -m unittest -v test_gateway_brain_router.py
cd company/meridian_platform
python3 -m unittest -v test_subscription_service.py
```

## Open Source Boundary

Meridian is open-source and contribution-first. Hosted services and external publishing credentials remain operational boundaries. See module docs for exact boundary definitions.
