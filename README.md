# Meridian

<p align="center">
  <img src="intelligence/company/www/assets/logo.png" alt="Meridian — Core and Team local-first product" width="180">
</p>

<p align="center">
  <strong>One product. One install. Two modes.</strong><br>
  Meridian Core is your daily local agent runtime. Meridian Team adds governed execution depth.
</p>

<p align="center">
  <img src="https://img.shields.io/github/actions/workflow/status/mapleleaflatte03/meridian/ci.yml?branch=main&style=flat-square" alt="CI">
  <img src="https://img.shields.io/badge/license-MIT-475569?style=flat-square" alt="MIT">
  <img src="https://img.shields.io/github/stars/mapleleaflatte03/meridian?style=flat-square" alt="Stars">
</p>

<p align="center">
  <a href="https://app.welliam.codes">Website</a> ·
  <a href="https://app.welliam.codes/pilot">Get Started</a> ·
  <a href="CONTRIBUTING.md">Contributing</a> ·
  <a href="ROADMAP.md">Roadmap</a>
</p>

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash
```

Then run onboarding:

```bash
cd ~/meridian
./scripts/onboard.sh          # interactive — choose Core or Team
```

Non-interactive:

```bash
MERIDIAN_INST_NAME="My Org" MERIDIAN_AGENT_NAME="Assistant" \
  ./scripts/onboard.sh --non-interactive --mode core
```

## Core Daily Use

```bash
./scripts/core.sh browse https://example.com
./scripts/core.sh research "summarize this week"
./scripts/core.sh remember my_note "something useful"
./scripts/core.sh recall my_note
./scripts/core.sh inspect
```

## Team Governed Execution

Team routes are Basic-auth-gated and require `--mode team` in onboarding. See [`examples/team-governed-execution.sh`](examples/team-governed-execution.sh) for a runnable flow.

After `./scripts/dev-up.sh`:

```bash
# Resolve Basic-auth credentials written by dev-up.sh
WORKSPACE_USER="$(awk -F': *' '/^user:/ {print $2; exit}' runtime/workspace_credentials)"
WORKSPACE_PASS="$(awk -F': *' '/^pass:/ {print $2; exit}' runtime/workspace_credentials)"

# Run governed execution slice (auth-gated, team mode required)
curl -s -u "${WORKSPACE_USER}:${WORKSPACE_PASS}" \
  -X POST http://127.0.0.1:18901/api/team/governed-execution \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"atlas","task_description":"governed memo","amount_usd":0.01}'
```

## Architecture

```
Meridian (platform)
├── loom/        — Local agent runtime: sessions, channels, memory, skills, proof (Rust)
├── kernel/      — Governance engine: Institution, Authority, Treasury, Court (Python)
└── intelligence/ — Interface layer: dashboards, proofs, workflows, operator tooling (Python)
```

## Developer Commands

```bash
# Start/stop local workspace + gateway
./scripts/dev-up.sh && ./scripts/dev-down.sh

# Supervisor (auto-restart 18901/19001/8266)
./scripts/dev-supervisor.sh status

# Run tests
cargo test --manifest-path loom/Cargo.toml --workspace
cd kernel && python3 -m unittest discover -s kernel/tests -p 'test_*.py'
cd intelligence && python3 -m unittest -v test_gateway_brain_router.py
```

## Governance, Benchmark, and Migration

- [Why Meridian](https://app.welliam.codes/why) — architecture rationale and governance model
- [Proofs](https://app.welliam.codes/proofs) — live proof posture dashboard
- [Benchmark lane](scripts/benchmark_meridian.sh) — cold-start and RSS comparison
- [Migration guide](docs/MIGRATION_FROM_CLAW.md) — concept mapping from Claw-family CLIs
- [Onboarding contract](docs/ONBOARDING_CONTRACT.md) — ready-to-run gate

## Licenses

- Root: MIT ([`LICENSE`](LICENSE))
- `kernel/`: Apache-2.0 ([`kernel/LICENSE`](kernel/LICENSE))
- `loom/` and `intelligence/`: MIT

Open source. No paywall for runtime usage. No closed governance module. See [`docs/MESSAGE_CONTRACT.md`](docs/MESSAGE_CONTRACT.md).

## Contribute

[`CONTRIBUTING.md`](CONTRIBUTING.md) · [Issues](https://github.com/mapleleaflatte03/meridian/issues) · [Roadmap](ROADMAP.md) · [Sponsors](https://github.com/sponsors/mapleleaflatte03)
