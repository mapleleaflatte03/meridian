# Meridian

<p align="center">
  <img src="intelligence/company/www/assets/logo.png" alt="Meridian — local-first Core and Team product" width="220">
</p>

<p align="center">
  <strong>One local agent product with two depths.</strong><br>
  Meridian Core is the daily cockpit. Meridian Team is the governed depth for approvals, budget, court, and audit.
</p>

<p align="center">
  <img src="https://img.shields.io/github/actions/workflow/status/mapleleaflatte03/meridian/ci.yml?branch=main&style=flat-square" alt="CI status">
  <img src="https://img.shields.io/badge/license-MIT-475569?style=flat-square" alt="MIT">
  <img src="https://img.shields.io/github/stars/mapleleaflatte03/meridian?style=flat-square" alt="GitHub stars">
</p>

<p align="center">
  <a href="https://app.welliam.codes">Website</a> ·
  <a href="https://app.welliam.codes/pilot">Install</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash
```

## Onboarding

```bash
cd ~/meridian
./scripts/onboard.sh
```

Choose your mode in onboarding:

- **Core** — daily local work
- **Team** — governed execution depth

The selected mode is persisted in `runtime/onboard_state.json`.

After onboarding, supported user-local provider and runtime overrides live in:

- `~/.meridian/.env`
- `~/.meridian/.env.gateway`

See [`docs/TEAM_RUNTIME_CONFIG.md`](docs/TEAM_RUNTIME_CONFIG.md) for the source-of-truth config model, precedence rules, and generated runtime files.

## First commands

```bash
./scripts/core.sh browse https://example.com
./scripts/core.sh research "summarize this week"
./scripts/core.sh remember my_note "something useful"
./scripts/core.sh recall my_note
./scripts/core.sh inspect
```

## Team mode

Team mode keeps Core behavior and adds governed execution routes in the local dashboard. These routes are Basic-auth-gated and require onboarding with `--mode team`.

Runnable example: [`examples/team-governed-execution.sh`](examples/team-governed-execution.sh)

## Architecture

Meridian is split into three layers:

- `loom/` — local agent runtime
- `kernel/` — governance engine
- `intelligence/` — website, dashboard, proofs, workflows, operator surfaces

## Why Meridian

- **Core first** — daily local work without governance overload
- **Team when needed** — approvals, treasury, court, and audit remain available as deeper control
- **Proof visible** — inspect runtime and policy posture through live routes
- **Local-first** — execution and state stay on your machine

## Developer commands

```bash
./scripts/dev-up.sh
./scripts/dev-down.sh

cargo test --manifest-path loom/Cargo.toml --workspace
cd kernel && python3 -m unittest discover -s kernel/tests -p 'test_*.py'
cd intelligence && python3 -m unittest -v test_gateway_brain_router.py
```

## Governance, benchmark, and migration

- [Why Meridian](https://app.welliam.codes/why)
- [Proofs](https://app.welliam.codes/proofs)
- [Benchmark lane](scripts/benchmark_meridian.sh)
- [Migration guide](docs/MIGRATION_FROM_CLAW.md)
- [Onboarding contract](docs/ONBOARDING_CONTRACT.md)
- [Team runtime config](docs/TEAM_RUNTIME_CONFIG.md)

## Dev and Maintenance Commands

These are developer/maintenance commands. **First-time users: start with `./scripts/onboard.sh` above, not these.**

```bash
# Start/stop local workspace + gateway (run after onboarding)
./scripts/dev-up.sh
./scripts/dev-down.sh

# Supervisor (auto-restart 18901/19001/8266)
./scripts/dev-supervisor.sh status

# Install only (without auto-start stack)
MERIDIAN_AUTO_START_STACK=0 ./scripts/bootstrap_full.sh

# Loom tests
cargo test --manifest-path loom/Cargo.toml --workspace

# Kernel tests
cd kernel && python3 -m unittest discover -s kernel/tests -p 'test_*.py'

# Intelligence tests
cd intelligence && python3 -m unittest -v test_gateway_brain_router.py
```

## Non-Goals (Locked)

- No paywall gate for core runtime/governance usage
- No mandatory commercial checkout path in onboarding
- No closed-source governance module hidden from community review

## Licenses

- Monorepo root: MIT ([`LICENSE`](LICENSE))
- `kernel/`: Apache-2.0 ([`kernel/LICENSE`](kernel/LICENSE))
- `loom/` and `intelligence/`: MIT

Canonical source is this monorepo. Legacy repos (`meridian-loom`, `meridian-kernel`, `meridian-intelligence`) are archived mirrors. See [`docs/REPO_MIGRATION_MAP.md`](docs/REPO_MIGRATION_MAP.md).

## Contribute

- [`CONTRIBUTING.md`](CONTRIBUTING.md)
- [Issue templates](.github/ISSUE_TEMPLATE)
- [Roadmap](ROADMAP.md)
- [Community map](docs/COMMUNITY_MAP.md)

Optional support: [GitHub Sponsors](https://github.com/sponsors/mapleleaflatte03) · [Sustainability policy](docs/SUSTAINABILITY.md)

---

*Meridian positioning contract: [`docs/MESSAGE_CONTRACT.md`](docs/MESSAGE_CONTRACT.md)*
