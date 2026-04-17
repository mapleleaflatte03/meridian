# Meridian

<p align="center">
  <img src="intelligence/company/www/assets/logo.png" alt="Meridian — Core and Team local-first product" width="220">
</p>

<p align="center">
  <strong>Meridian — one product, one install, two modes.</strong><br>
  Meridian Core is the daily-use local agent runtime. Meridian Team adds governed execution depth. Run guided onboarding, choose your mode, and start locally with verifiable proof.
</p>

<p align="center">
  <img src="https://img.shields.io/github/actions/workflow/status/mapleleaflatte03/meridian/ci.yml?branch=main&style=flat-square" alt="CI status">
  <img src="https://img.shields.io/badge/license-MIT-475569?style=flat-square" alt="MIT">
  <img src="https://img.shields.io/github/stars/mapleleaflatte03/meridian?style=flat-square" alt="GitHub stars">
  <img src="https://img.shields.io/badge/mode-Core%20%2B%20Team-0f766e?style=flat-square" alt="Core and Team modes">
  <img src="https://img.shields.io/badge/runtime-local%20first-1f6feb?style=flat-square" alt="Local-first runtime">
  <img src="https://img.shields.io/badge/governance-Team%20depth-111827?style=flat-square" alt="Team governance depth">
</p>

<p align="center">
  <a href="https://app.welliam.codes">Website</a> ·
  <a href="https://app.welliam.codes/pilot">Get Started</a> ·
  <a href="https://app.welliam.codes/loom">Runtime Details</a> ·
  <a href="https://app.welliam.codes/compare">Compare</a> ·
  <a href="CONTRIBUTING.md">Contributing</a> ·
  <a href="ROADMAP.md">Roadmap</a>
</p>

## What You Get

One product. One install. Two modes.

**Meridian Core** — daily-use local agent runtime: browser tasks, research, memory, scheduled automation, and agent loops. No governance expertise required to start.

**Meridian Team** — Core plus governance depth: institution treasury, court rules, warrants, authority gates, and full audit surfaces.

Install in one command:

```bash
curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash
```

Then choose your mode in onboarding:

```bash
cd ~/meridian

# Core mode (recommended for most users):
./scripts/onboard.sh --mode core

# Team mode (Core + governance depth):
./scripts/onboard.sh --mode team

# Or run interactively and choose at the prompt:
./scripts/onboard.sh
```

The selected mode is persisted in `runtime/onboard_state.json`.

After Core setup, run daily tasks:

```bash
./scripts/core.sh browse https://example.com
./scripts/core.sh research "echo hello world"
./scripts/core.sh remember my_note "something useful"
./scripts/core.sh recall my_note
./scripts/core.sh inspect
```

After Team setup, Core tasks work the same — plus governed Team execution surfaces via `dev-up.sh`.

Team governed execution (Team mode only):

Team routes are auth-protected. `dev-up.sh` writes a Basic-auth credentials file to `runtime/workspace_credentials` (default user `owner`, default password `meridian_local_operator`). Override either via the `MERIDIAN_WORKSPACE_USER` / `MERIDIAN_WORKSPACE_PASS` env vars, or via `MERIDIAN_WORKSPACE_PASSWORD` before running `dev-up.sh`. The runnable `examples/team-governed-execution.sh` already resolves these automatically.

```bash
# Resolve Basic-auth credentials written by dev-up.sh.
WORKSPACE_USER="$(awk -F': *' '/^user:/ {print $2; exit}' runtime/workspace_credentials)"
WORKSPACE_PASS="$(awk -F': *' '/^pass:/ {print $2; exit}' runtime/workspace_credentials)"

# Run one governed execution slice (court + budget + authority/treasury/court/audit context)
curl -s -u "${WORKSPACE_USER}:${WORKSPACE_PASS}" \
  -X POST http://127.0.0.1:18901/api/team/governed-execution \
  -H 'Content-Type: application/json' \
  -d '{
    "agent_id":"agent_123",
    "task_description":"Prepare governed execution memo",
    "amount_usd":15.0,
    "proof_receipt":"proof_team_demo",
    "assigned_by":"ops_lead",
    "settled_by":"ops_lead",
    "estimated_cost_usd":0.25
  }'

# Inspect Team governance state for an agent
curl -s -u "${WORKSPACE_USER}:${WORKSPACE_PASS}" \
  "http://127.0.0.1:18901/api/team/governed-execution/inspect?agent_id=agent_123"

# Export Team audit artifact (JSON)
curl -s -u "${WORKSPACE_USER}:${WORKSPACE_PASS}" \
  "http://127.0.0.1:18901/api/team/governed-execution/audit-export?agent_id=agent_123"
```

This Team flow adds a real policy consequence over Core: the routes themselves are Basic-auth-gated, it is blocked unless onboarding mode is `team`, and it returns an inspectable governance + audit artifact tied to runtime evidence.

## Why Meridian

Other local agent runtimes give you autonomy. Meridian gives you autonomy plus Core daily-use flow, Team governed depth, and runtime proof in one install:

- **Verifiable receipts** — every agent action produces a PoGE proof receipt you can inspect.
- **Budget controls** — Treasury enforces reserve floors, spend limits, and payout boundaries.
- **Authority gates** — high-risk actions require explicit warrants and approval paths.
- **Court rules** — violations, sanctions, appeals, and remediation are tracked with auditable history.
- **Local-first** — execution and state stay on your machine. No cloud dependency.

## Architecture

```
Meridian (platform)
├── loom/        — Local agent runtime: sessions, channels, memory, skills, proof (Rust)
├── kernel/      — Governance engine: Institution, Authority, Treasury, Court (Python)
└── intelligence/ — Interface layer: dashboards, proofs, workflows, operator tooling (Python)
```

- `loom/` is what runs your agents.
- `kernel/` is what keeps them accountable.
- `intelligence/` is what makes governance visible.

## Quick Start

After install, run the guided onboarding:

```bash
# Create your institution and first agent (interactive)
./scripts/onboard.sh
```

For non-interactive / CI usage:

```bash
MERIDIAN_INST_NAME="My Org" MERIDIAN_AGENT_NAME="Assistant" ./scripts/onboard.sh --non-interactive
```

After onboarding completes, explore the public proof surfaces:

- [Proofs](https://app.welliam.codes/proofs) — runtime proof posture dashboard
- [Workflows](https://app.welliam.codes/workflows) — operator workflow gallery
- [Demo](https://app.welliam.codes/demo) — full walkthrough

Ready-to-run gate: [`docs/ONBOARDING_CONTRACT.md`](docs/ONBOARDING_CONTRACT.md)

## Quick Visuals

Install flow:

![Install in 60 seconds](docs/assets/install_in_60_seconds.gif)

Live surfaces:

![Homepage](docs/assets/home-desktop.png)
![Proofs](docs/assets/proofs-desktop.png)
![Workflows](docs/assets/workflows-desktop.png)

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

## Governance and Trust

Loom's built-in governance is what makes it different from other agent runtimes. Under the hood:

- **Kernel** provides five governance primitives (Institution, Agent, Authority, Treasury, Court) and a 3-ledger economy (REP, AUTH, CASH).
- **PoGE receipts** give you verifiable proof of every execution boundary.
- **Runtime proof routes** expose governance state through inspectable APIs.

For deep governance documentation:
- [Why Meridian](https://app.welliam.codes/why) — architecture rationale
- [Proofs](https://app.welliam.codes/proofs) — live proof posture dashboard
- [Workflows](https://app.welliam.codes/workflows) — operator workflow gallery
- [Research Hub](docs/RESEARCH_HUB.md) — RFCs, benchmarks, case studies

## Benchmark, Migrate, Evaluate

- **Benchmark lane**: `./scripts/benchmark_meridian.sh --with-comparisons` — reproducible cold-start and RSS comparison against detected Claw-family CLIs
- **Migration guide**: [`docs/MIGRATION_FROM_CLAW.md`](docs/MIGRATION_FROM_CLAW.md) — concept mapping from OpenClaw / OpenFang / ZeroClaw
- **Example packs**: [`examples/`](examples/) — Core daily loop, scheduled check, Team governed execution, benchmark comparison
- **Release cadence**: [`docs/RELEASE_CADENCE.md`](docs/RELEASE_CADENCE.md) — tag-driven release model and verification

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
