# Meridian

<p align="center">
  <img src="intelligence/company/www/assets/meridian_lockup.svg" alt="Meridian — Governed Agent Runtime" width="720">
</p>

<p align="center">
  <strong>Open research platform for governed local AI agents.</strong><br>
  Loom runs the local runtime. Kernel enforces governance. Intelligence exposes public proof/workflow surfaces.
</p>

<p align="center">
  <img src="https://img.shields.io/github/actions/workflow/status/mapleleaflatte03/meridian/ci.yml?branch=main&style=flat-square" alt="CI status">
  <img src="https://img.shields.io/badge/license-MIT-475569?style=flat-square" alt="MIT">
  <img src="https://img.shields.io/github/stars/mapleleaflatte03/meridian?style=flat-square" alt="GitHub stars">
  <img src="https://img.shields.io/badge/focus-open%20research-0f766e?style=flat-square" alt="Open research">
  <img src="https://img.shields.io/badge/runtime-local%20first-1f6feb?style=flat-square" alt="Local-first runtime">
</p>

<p align="center">
  <a href="https://app.welliam.codes">Website</a> ·
  <a href="https://app.welliam.codes/proofs">Proofs</a> ·
  <a href="https://app.welliam.codes/workflows">Workflows</a> ·
  <a href="CONTRIBUTING.md">Contributing</a> ·
  <a href="ROADMAP.md">Roadmap</a> ·
  <a href="docs/RESEARCH_HUB.md">Research Hub</a>
</p>

## What Meridian Is

Meridian is a governance-first stack for local AI agent systems:

- `loom/` — sovereign local runtime + PoGE execution layer (Rust)
- `kernel/` — constitutional governance core (Institution, Agent, Authority, Treasury, Court + 3-ledger economy)
- `intelligence/` — workflows, public surfaces, gateway, and operator tooling

License scope:
- monorepo root: MIT ([`LICENSE`](LICENSE))
- `kernel/`: Apache-2.0 ([`kernel/LICENSE`](kernel/LICENSE))
- `loom/` and `intelligence/`: MIT ([`loom/LICENSE`](loom/LICENSE), [`intelligence/LICENSE`](intelligence/LICENSE))

Canonical source is this monorepo.

Legacy repositories are archived mirrors:

- `meridian-loom` -> `meridian/loom`
- `meridian-kernel` -> `meridian/kernel`
- `meridian-intelligence` -> `meridian/intelligence`

Migration details: [`docs/REPO_MIGRATION_MAP.md`](docs/REPO_MIGRATION_MAP.md)
Mirror archive status: [`docs/MIRROR_ARCHIVE_STATUS.md`](docs/MIRROR_ARCHIVE_STATUS.md)
Mirror policy check: `./scripts/check_mirror_archive_policy.sh`

## Non-Goals (Locked)

- no paywall gate for core runtime/governance usage
- no mandatory commercial checkout path in onboarding
- no closed-source governance module hidden from community review

## Install Full Stack (One Command)

```bash
curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash
```

After install:

```bash
cd ~/meridian
./scripts/dev-up.sh
```

By default bootstrap initializes institution state, treasury baseline, and court rule set, then runs local smoke checks for:

- `/api/institution/template`
- `/api/treasury`
- `/api/status` + runtime proof readiness
- onboarding-ready contract verification (`MERIDIAN_VERIFY_ONBOARDING=1` by default)

Ready-to-run definition and gate:
- [`docs/ONBOARDING_CONTRACT.md`](docs/ONBOARDING_CONTRACT.md)
- `./scripts/acceptance_onboarding_ready_lane.sh`
- first agent helper: `./scripts/new-first-agent.sh "My Assistant"`

## Quick Visuals

Install flow:

![Install in 60 seconds](docs/assets/install_in_60_seconds.gif)

Live surfaces:

![Homepage](docs/assets/home-desktop.png)
![Proofs](docs/assets/proofs-desktop.png)
![Workflows](docs/assets/workflows-desktop.png)

## Local Dev Commands

```bash
# Start/stop local workspace + gateway
./scripts/dev-up.sh
./scripts/dev-down.sh

# Bootstrap only (without auto-start)
MERIDIAN_AUTO_START_STACK=0 ./scripts/bootstrap_full.sh

# Create first governed agent quickly
./scripts/new-first-agent.sh "My Assistant"

# Loom tests
cargo test --manifest-path loom/Cargo.toml --workspace

# Kernel tests
cd kernel
python3 -m unittest discover -s kernel/tests -p 'test_*.py'
python3 -m unittest discover -s economy/tests -p 'test_*.py'

# Intelligence tests
cd ../intelligence
python3 -m unittest -v test_gateway_brain_router.py

# Research capture artifacts
cd ..
./scripts/research_capture_baseline.sh
./scripts/research_capture_case_study.sh sanction_remediation_loop
```

## Open-Source Boundary

Meridian is open-source and contribution-first. Hosted credentials, external publishing identities, and managed operations remain explicit operational boundaries.

See:

- [`intelligence/company/www/OPEN_SOURCE_BOUNDARY.html`](intelligence/company/www/OPEN_SOURCE_BOUNDARY.html)
- [`docs/RESEARCH_HUB.md`](docs/RESEARCH_HUB.md)

## Contribute

- Contribution guide: [`CONTRIBUTING.md`](CONTRIBUTING.md)
- Issue templates: [`.github/ISSUE_TEMPLATE`](.github/ISSUE_TEMPLATE)
- Community map: [`docs/COMMUNITY_MAP.md`](docs/COMMUNITY_MAP.md)
- Roadmap: [`ROADMAP.md`](ROADMAP.md)
- Research artifacts: [`docs/research/README.md`](docs/research/README.md)

Optional support:

- GitHub Sponsors: https://github.com/sponsors/mapleleaflatte03
- Patreon: https://www.patreon.com/
- Sustainability policy: [`docs/SUSTAINABILITY.md`](docs/SUSTAINABILITY.md)
