# Onboarding Contract (Ready-to-Run)

This contract defines what "one-command onboarding" means in Meridian.

## Definition

Running:

```bash
curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash
```

must produce a local state where a new user can immediately inspect governance/runtime surfaces without manual patching.

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
5. Court rule set initialized (>=3 rules in template path).
6. First agent can be provisioned through one helper command:
   - `./scripts/new-first-agent.sh "My Assistant"`
7. Supervisor auto-restart layer active for local stack reliability:
   - tracks `18901` (workspace), `19001` (peer workspace), `8266` (gateway)
   - status command: `./scripts/dev-supervisor.sh status`

## Verification Gate

Use:

```bash
./scripts/acceptance_onboarding_ready_lane.sh
```

This lane is the source of truth for onboarding readiness.
