# Onboarding Contract (Ready-to-Run)

This contract defines what "one-command onboarding" means in Meridian's one-product, two-mode contract.

## Definition

Running:

```bash
curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash
```

must produce a local state where a new user can immediately inspect governance/runtime surfaces without manual patching. The first dashboard view must remain honest on clean state: if no agents, channels, delivery targets, or audit history exist yet, Meridian must show those surfaces as empty or unavailable instead of fabricating activity.

## Guided Onboarding Path

The authoritative first-run onboarding script:

```bash
./scripts/onboard.sh                   # interactive guided mode
./scripts/onboard.sh --non-interactive # use defaults / env vars
```

This is the recommended path for all new users. It creates the user's own institution and first agent without importing maintainer or demo data.

Alternative shortcut (skips guided setup):

```bash
./scripts/new-first-agent.sh "My Assistant"
```

## User-Customized Fields

Fields collected during guided onboarding. Each can be overridden by setting the corresponding environment variable before running `onboard.sh --non-interactive`.

| Field | Env var | Default | Description |
| --- | --- | --- | --- |
| Institution name | `MERIDIAN_INST_NAME` | `"My Workspace"` | Display name for the institution |
| Owner user ID | `MERIDIAN_OWNER_ID` | auto-generated UUID | Identifier for the owning user |
| Plan tier | `MERIDIAN_INST_PLAN` | `core` or `team` from selected mode | Core mode persists `core`; Team mode persists `team` by default, with `enterprise` available as an explicit Team override |
| First agent name | `MERIDIAN_AGENT_NAME` | `"Assistant"` | Display name of the first provisioned agent |
| First agent role | `MERIDIAN_AGENT_ROLE` | `manager` | One of: `manager`, `analyst`, `executor`, `writer` |
| Import demo pack | `MERIDIAN_IMPORT_DEMO_PACK` | `no` | Set to `yes` to seed pre-built demo data |
| Enable governance | `MERIDIAN_ENABLE_GOVERNANCE` | `yes` | Set to `no` to disable governance gates |
| Brain route type | `MERIDIAN_BRAIN_ROUTE_TYPE` | `http_json` | Core defaults to the Meridian-owned manager route |
| Brain provider profile | `MERIDIAN_BRAIN_PROVIDER_PROFILE` | `manager_primary` | Provider profile restored from `~/.meridian/.env` / `.env.gateway` when available |
| Brain model | `MERIDIAN_BRAIN_MODEL` | `grok-4-1-fast-reasoning` | Default manager model for Core onboarding |
| Brain endpoint | `MERIDIAN_BRAIN_ENDPOINT` | from `MERIDIAN_BRAIN_MANAGER_ENDPOINT` or `MERIDIAN_MANAGER_XAI_BASE_URL` | Required for `http_json` execution |

## Onboarding Modes (Product Contract)

| Mode | Description |
| --- | --- |
| **Core** (recommended) | Daily-use local runtime setup. Creates institution + first agent with minimal operator overhead. |
| **Team** | Core plus governed execution depth (authority/treasury/court/audit surfaces). |

## Bootstrap Profiles (Advanced / Internal)

The installer/bootstrap layer can still run with internal profiles (`user`, `demo`, `maintainer`) for packaging and ops workflows. These are implementation profiles, not separate product lines.

- `user`: clean-slate bootstrap path
- `demo`: bootstrap plus demo data import path
- `maintainer`: operator-level bootstrap path

Public onboarding contract remains Core/Team mode selection via `./scripts/onboard.sh`.

## Data Roots

| What is created | Location |
| --- | --- |
| Onboarding state (`onboard_state.json`) | `$MERIDIAN_ROOT/runtime/` |
| Kernel governance state (org, capsule, treasury) | `$MERIDIAN_ROOT/kernel/` |
| Loom CLI configuration | `~/.config/meridian-loom/` |
| Agent configs | `~/.config/meridian-loom/agents/` |

## Supported User Config Surface

After onboarding, the supported user-edited runtime config lives outside the repo in:

- `~/.meridian/.env`
- `~/.meridian/.env.gateway`
- `~/.meridian/team.json`

These files are the supported place to set provider choice, model, endpoint, runtime root, preset selection, and team role/purpose overrides for local use. Runtime-generated files such as `runtime/default/providers/profiles.json`, `runtime/default/loom.toml`, and runtime registry/state files are derived artifacts, not the primary user config surface.

See [`TEAM_RUNTIME_CONFIG.md`](./TEAM_RUNTIME_CONFIG.md) for precedence and sync rules.

## What Is NOT Created

- No remote accounts or cloud registrations
- No data on `app.welliam.codes` or any hosted service
- No demo or maintainer state (unless explicitly opted in via `MERIDIAN_IMPORT_DEMO_PACK=yes`)

## Required Outcomes

1. Kernel state initialized (institution exists).
2. Institution template route available:
   - `/api/institution/template`
3. Treasury route available with reserve baseline:
   - `/api/treasury`
4. Runtime status/proof routes reachable:
   - `/api/status`
   - `/api/runtime-proof`
   - `/api/kernel-proof-bundle`
5. Team governed execution surface available (Team mode only, Basic-auth-protected):
   - `POST /api/team/governed-execution`
   - `GET /api/team/governed-execution/inspect?agent_id=<id>`
   - `GET /api/team/governed-execution/audit-export?agent_id=<id>`
   - Credentials are written to `runtime/workspace_credentials` by `./scripts/dev-up.sh`;
     override via `MERIDIAN_WORKSPACE_USER` / `MERIDIAN_WORKSPACE_PASS` or
     `MERIDIAN_WORKSPACE_PASSWORD`. See `examples/team-governed-execution.sh` for a runnable flow.
6. Court rule set initialized (>=3 rules in template path).
7. First agent can be provisioned through one helper command:
   - `./scripts/new-first-agent.sh "My Assistant"`
8. Supervisor auto-restart layer active for local stack reliability:
   - tracks `18901` (workspace), `19001` (peer workspace), `8266` (gateway)
   - status command: `./scripts/dev-supervisor.sh status`
   - optional persistent user service:
     - install: `./scripts/install-supervisor-service.sh`
     - status: `systemctl --user status meridian-runtime-supervisor.service --no-pager`

## Verification Gate

Use:

```bash
./scripts/acceptance_onboarding_ready_lane.sh
```

This lane is the source of truth for onboarding readiness.

## Claim-to-Evidence Lock (Batch 1)

| Contract outcome | Executable check | Evidence artifact |
| --- | --- | --- |
| Kernel state initialized and template/treasury/runtime routes reachable | `./scripts/acceptance_onboarding_ready_lane.sh` (bootstrap smoke + local API readiness probes) | `runtime/bootstrap_gateway_smoke.json` produced by bootstrap and validated by the lane |
| Court baseline initialized (`>=3` rules) | `./scripts/acceptance_onboarding_ready_lane.sh` (`court_rule_count` assertion + dynamic court lifecycle smoke) | Lane output (`[onboarding-lane] court ...`) and validated bootstrap smoke payload |
| First governed agent helper exists and onboarding path is executable | `./scripts/acceptance_onboarding_ready_lane.sh` (`./scripts/new-first-agent.sh` executable assertion) | Lane output (`[onboarding-lane] ...`) |
| Supervisor reliability path is available and status-checkable | `./scripts/acceptance_onboarding_ready_lane.sh` (`./scripts/dev-supervisor.sh` executable assertion + conditional status snapshot) | Lane output (`[onboarding-lane] supervisor status snapshot`) when supervisor is enabled |
| One-command installer keeps onboarding verification toggle wired | `./scripts/acceptance_onboarding_ready_lane.sh` (`MERIDIAN_VERIFY_ONBOARDING` presence assertion in installer) | Verified against `scripts/install-full.sh` by the lane |

## Evidence Requirements for Release Claims

A claim that onboarding is "ready-to-run" is valid only when the acceptance lane passes in a clean local environment and the generated smoke artifact matches this contract.
