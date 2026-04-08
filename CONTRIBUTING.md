# Contributing to Meridian

Meridian is an open research platform for governed local AI agents. This repository is canonical; archived mirrors are read-only.

## Fast Path (First PR)

1. Bootstrap full stack:

```bash
./scripts/bootstrap_full.sh
```

2. Verify local routes:

```bash
curl -fsS http://127.0.0.1:8266/api/status | python3 -m json.tool
curl -fsS http://127.0.0.1:8266/api/institution/template | python3 -m json.tool
curl -fsS http://127.0.0.1:8266/api/treasury | python3 -m json.tool
```

3. Pick an issue:
- `good first issue` for onboarding/docs/tests
- `research` for protocol/RFC/benchmark work
- `governance` for court/authority/treasury paths

## Module Test Gates

Run the gate for the module you changed:

```bash
# Loom
cargo test --manifest-path loom/Cargo.toml --workspace

# Kernel
cd kernel
python3 -m unittest discover -s kernel/tests -p 'test_*.py'
python3 -m unittest discover -s economy/tests -p 'test_*.py'

# Intelligence / web surfaces
cd ../intelligence
python3 -m unittest -v test_gateway_brain_router.py
./scripts/acceptance_publish_live_lane.sh
```

## PR Requirements

1. One problem per PR.
2. Tests first for behavior changes.
3. Include command evidence (tests/routes/screenshots when relevant).
4. Keep governance semantics intact: Institution, Agent, Authority, Treasury, Court, PoGE.
5. No over-claiming in docs/web copy.
6. Include rollback note for non-trivial behavior changes.

## Research Contribution Rules

- Use `Research RFC` issue template for protocol/runtime proposals.
- State hypothesis, trust boundary impact, and measurable acceptance criteria.
- Link benchmark traces or proof payloads in the PR description.

## Community & Routing

- Issues: https://github.com/mapleleaflatte03/meridian/issues/new/choose
- Discussions: https://github.com/mapleleaflatte03/meridian/discussions
- Roadmap: [`ROADMAP.md`](ROADMAP.md)
- Research hub: [`docs/RESEARCH_HUB.md`](docs/RESEARCH_HUB.md)
- Community map: [`docs/COMMUNITY_MAP.md`](docs/COMMUNITY_MAP.md)
- Project governance: [`docs/PROJECT_GOVERNANCE.md`](docs/PROJECT_GOVERNANCE.md)
- Security policy: [`SECURITY.md`](SECURITY.md)
- Sponsors: https://github.com/sponsors/mapleleaflatte03
