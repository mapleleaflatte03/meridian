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
