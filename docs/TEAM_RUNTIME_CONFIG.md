# Team Runtime Config

This document defines the supported configuration path for Meridian Core and Team runtime behavior.

## Source Of Truth

For an end user, the supported configuration sources are:

| Purpose | Source of truth | Owner |
| --- | --- | --- |
| Product mode (`core` / `team`) and first-run bootstrap state | `runtime/onboard_state.json` | onboarding scripts |
| User-local runtime and provider config | `~/.meridian/.env` | end user |
| User-local gateway/runtime overrides | `~/.meridian/.env.gateway` | end user |
| Brain-router / manager policy config when explicitly used | `intelligence/company/meridian_platform/config/*.json` plus referenced env vars | source + end user |
| Team topology seed metadata | `intelligence/company/meridian_platform/agent_registry.json` | source-controlled product code |

The user-edited files are `~/.meridian/.env` and `~/.meridian/.env.gateway`.

## Config Precedence

`team_topology.load_runtime_env()` resolves environment files in this order:

1. repo `.env`
2. repo `.env.gateway`
3. `~/.meridian/.env`
4. `~/.meridian/.env.gateway`

Later files override earlier ones. The supported rule is:

- repo env files provide product defaults
- `~/.meridian/*` provides the user's local runtime truth

## Generated Runtime State

The following are generated or synchronized artifacts. Users should not hand-edit them as their primary config surface:

| File | Status | Purpose |
| --- | --- | --- |
| `runtime/default/providers/profiles.json` | generated | provider profiles materialized from team topology + local env |
| `runtime/default/loom.toml` | generated/synced | runtime org/kernel binding |
| `kernel/agent_registry.json` or bundled kernel registry path | generated/synced | runtime-registered team agents |
| `runtime/default/state/**` | generated | runtime jobs, receipts, queues, session history |
| `state/**` | generated | local caches and temporary proof artifacts |

If a user wants to change provider, model, endpoint, agent name, or runtime root, they should update `~/.meridian/.env` or `~/.meridian/.env.gateway` and let runtime sync regenerate the derived files.

## Supported User Customization

The supported local env surface includes:

- `MERIDIAN_MANAGER_AGENT_NAME`
- `MERIDIAN_BRAIN_MANAGER_PROFILE_NAME`
- `MERIDIAN_BRAIN_MANAGER_TRANSPORT`
- `MERIDIAN_BRAIN_MANAGER_ENDPOINT`
- `MERIDIAN_BRAIN_MANAGER_MODEL`
- `MERIDIAN_BRAIN_MANAGER_AUTH_ENV`
- `MERIDIAN_AGENT_<NAME>_NAME`
- `MERIDIAN_AGENT_<NAME>_PROFILE_NAME`
- `MERIDIAN_AGENT_<NAME>_PROVIDER`
- `MERIDIAN_AGENT_<NAME>_BASE_URL`
- `MERIDIAN_AGENT_<NAME>_MODEL`
- `MERIDIAN_AGENT_<NAME>_API_KEY`
- `MERIDIAN_LOOM_BIN`
- `MERIDIAN_LOOM_ROOT`
- `MERIDIAN_LOOM_ORG_ID`
- `MERIDIAN_LOOM_AGENT_ID`
- `MERIDIAN_LOOM_SERVICE_TOKEN`

This is the supported path for:

1. naming agents
2. choosing provider transport
3. supplying model + endpoint
4. pointing Meridian at a different Loom binary or runtime root

## Runtime Sync Contract

`sync_loom_team_profiles()` is the canonical bridge between user config and runtime state. It is allowed to:

- render provider profiles
- sync `loom.toml`
- sync runtime-facing agent registry data
- sync kernel org/capsule metadata needed for execution

It is not the user configuration surface. The env files remain the user truth.

## Routing And Execution In The Supported Path

These behaviors are product behavior, not local hacks:

- route planning may intentionally return `skills=[]`
- specialist execution must respect `plan.skills=[]`
- explicit specialist requests use compact prompts instead of loading unrelated skill/memory context
- explicit specialist requests may prefer direct-provider-first for specialist lanes where Loom adds avoidable latency
- reasoning-leak cleanup happens inside gateway execution before manager synthesis

These behaviors should work without manual edits to runtime-state files.

## Officially Supported vs Debug-Only

Officially supported:

- onboarding via `./scripts/onboard.sh`
- local config via `~/.meridian/.env` and `~/.meridian/.env.gateway`
- runtime start via `./scripts/dev-up.sh` or the documented Core/Team commands
- provider hookup through documented env vars
- runtime sync regenerating `profiles.json`, `loom.toml`, and runtime registry state

Only tolerated for local debugging:

- hand-editing `runtime/default/providers/profiles.json`
- hand-editing runtime job or queue files under `runtime/default/state/`
- hand-editing `kernel/agent_registry.json`
- temporary probes, staged receipts, screenshots, and ad hoc cache files under `state/`
