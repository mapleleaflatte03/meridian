# Migration Guide: Claw-Family Stacks to Meridian

This guide helps users of OpenClaw (Claude Code), OpenFang (Codex), ZeroClaw (Aider), and adjacent agent runtimes evaluate and switch to Meridian Core or Team.

## What Meridian Is

Meridian is one product with two modes:

- **Meridian Core** — daily-use local agent runtime (browser tasks, research, memory, scheduling, loops)
- **Meridian Team** — Core plus governed execution depth (authority, treasury, court, audit)

One install. One onboarding. Mode selected at first run.

## Concept Mapping

### Maps Cleanly to Meridian Core

| Claw-family concept | Meridian Core equivalent | Notes |
| --- | --- | --- |
| CLI agent session | `./scripts/core.sh` task runner | Browse, research, memory, scheduling, inspect |
| Agent config / profile | `runtime/onboard_state.json` + agent registry | Created during onboarding |
| Memory / context | `core.sh remember` / `core.sh recall` | Key-value memory with receipts |
| Browser automation | `core.sh browse URL` | Bounded browser navigation |
| Terminal task execution | `core.sh research "command"` | Bounded terminal execution with proof |
| Scheduled / recurring tasks | `core.sh schedule NAME INTERVAL` | Cron-style scheduling |
| Agent status / inspect | `core.sh inspect` / `core.sh status` | Runtime state + last execution |

### Requires Meridian Team

| Claw-family concept | Meridian Team feature | Why Team |
| --- | --- | --- |
| Budget / spend tracking | Treasury with reserve floors | Real policy enforcement, not just logging |
| Approval workflows | Authority gates + warrants | Governed approval paths with audit trail |
| Violation / sanction tracking | Court rules + sanctions | Constitutional enforcement model |
| Audit export | `/api/team/governed-execution/audit-export` | Structured JSON audit artifacts |
| Multi-agent governance | Team governed execution surface | Policy-gated execution across agent teams |

### Does Not Map Cleanly Yet

| Claw-family feature | Gap | Status |
| --- | --- | --- |
| IDE integration (VS Code, JetBrains) | Meridian is CLI/API-first | Not planned for Phase 6 |
| Hosted / cloud execution | Meridian is local-first | By design; no cloud dependency |
| MCP server ecosystem | Loom capabilities exist but ecosystem is smaller | Growing; see `loom/capabilities/` |
| Conversation / chat UX | No interactive chat mode | Core uses task-oriented commands instead |
| Git integration (auto-commit, PR) | No built-in git automation | Use standard git tooling alongside Meridian |
| Plugin / extension marketplace | Loom capabilities are the extension unit | Smaller ecosystem than Claw-family |

## First-Run Path for Switchers

```bash
# 1. Install Meridian
curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash

# 2. Choose your mode
cd ~/meridian
./scripts/onboard.sh --mode core    # most switchers start here
# or
./scripts/onboard.sh --mode team    # if you need governed execution depth

# 3. Try the things you already do in Claw-family tools
./scripts/core.sh browse https://example.com
./scripts/core.sh research "echo hello world"
./scripts/core.sh remember my_note "something useful"
./scripts/core.sh recall my_note
./scripts/core.sh inspect

# 4. (Team only) Try governed execution
#    Team routes are Basic-auth-protected. `dev-up.sh` writes credentials to
#    runtime/workspace_credentials. Or use the ready-made example:
#      bash examples/team-governed-execution.sh
WORKSPACE_USER="$(awk -F': *' '/^user:/ {print $2; exit}' runtime/workspace_credentials)"
WORKSPACE_PASS="$(awk -F': *' '/^pass:/ {print $2; exit}' runtime/workspace_credentials)"
curl -s -u "${WORKSPACE_USER}:${WORKSPACE_PASS}" \
  -X POST http://127.0.0.1:18901/api/team/governed-execution \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"agent_1","task_description":"Test governed task","amount_usd":5.0,"proof_receipt":"proof_test","assigned_by":"me","settled_by":"me","estimated_cost_usd":0.10}'
```

## What to Try First After Migration

1. **Core daily loop**: `core.sh browse` + `core.sh research` + `core.sh remember/recall`
2. **Inspect proof**: `core.sh inspect` shows execution receipt and agent state
3. **Run benchmark**: `./scripts/benchmark_meridian.sh --with-comparisons` to see cold-start and RSS differences
4. **Team depth** (if Team mode): governed execution + audit export via the Team API surface

## Honest Assessment

### Where Meridian is stronger

- **Governance depth**: Treasury, Court, Authority are built in, not bolted on
- **Proof receipts**: Every action produces a PoGE receipt
- **Cold start / resource footprint**: Loom CLI starts in ~19ms / ~0.2 MiB vs 300ms+ / 250+ MiB for Claw-family
- **Local-first by design**: No cloud dependency, no opaque remote execution

### Where Claw-family stacks are stronger

- **IDE integration**: VS Code, JetBrains, web IDE support
- **Conversation UX**: Interactive chat is the default mode
- **Ecosystem breadth**: MCP servers, plugins, extension marketplace
- **Community size**: Larger user base and contributor pool
- **Git automation**: Built-in commit, PR, branch management

### Migration script

A code-level migration script exists at `scripts/migrate-from-claw.sh` for importing agent configs and governance state from Claw-ecosystem projects. Run with `--dry-run` first.

## Further Reading

- [README.md](../README.md) — product overview
- [docs/ONBOARDING_CONTRACT.md](ONBOARDING_CONTRACT.md) — onboarding contract
- [docs/MESSAGE_CONTRACT.md](MESSAGE_CONTRACT.md) — positioning contract
- [CONTRIBUTING.md](../CONTRIBUTING.md) — contributor path
