# Meridian Message Contract

Canonical positioning definitions. All repo copy, docs, and public surfaces must align with these sentences. If a surface drifts from this contract, this contract wins.

## Core Definitions

- **Meridian** is one product with one install and two modes.
- **Meridian Core** is the primary daily-use local agent runtime (browser tasks, research, memory, scheduling, loops) with verifiable proof.
- **Meridian Team** is Core plus governed execution depth (authority gates, treasury controls, court rules, audit surfaces).
- **Loom** is the runtime engine inside Meridian Core/Team.
- **Kernel** is the built-in governance engine (Institution, Authority, Treasury, Court).
- **Intelligence** is the interface layer (dashboards, proof surfaces, workflow galleries, operator tooling).

## User-Facing Sentences

- **What Meridian is:** One local-first agent product with two modes: Core for daily work, Team for governed execution.
- **How users start:** Run one install command, then choose mode in onboarding.
- **Why Meridian is different:** You get local execution plus built-in governance and verifiable receipts.

## Story Order (First 30 Seconds)

1. Meridian is one product with one install.
2. Meridian Core is the default path for daily local agent work.
3. Meridian Team adds governed execution depth on top of Core.
4. Onboarding selects mode (`core` or `team`) and persists that choice.
5. Loom/Kernel/Intelligence explain how Meridian is implemented, after the product story is clear.

## Positioning Hierarchy

```
Meridian (product)
├── Core mode (default daily-use local runtime)
│   └── Powered by Loom runtime capabilities
├── Team mode (Core + governed execution depth)
│   └── Powered by Kernel governance primitives
└── Intelligence surfaces (proof/workflow/operator visibility)
```

## What This Contract Prohibits

- Leading top-level copy with Loom-first framing as if it were a separate product line.
- Leading with governance-first or operator-first framing before Core/Team product truth.
- Presenting Team as a separate SKU, repo, or onboarding branch.
- Claiming capabilities not present in repo/runtime behavior.
- Hiding architecture truth; Loom/Kernel/Intelligence must remain accurate but subordinate to the product contract.

## Truth Anchors

- Install: `curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash`
- Onboarding: `./scripts/onboard.sh --mode core` or `./scripts/onboard.sh --mode team`
- Persisted mode: `runtime/onboard_state.json`
- Team governed execution depth: `/api/team/governed-execution` and related inspect/export routes
- Onboarding contract source of truth: [`docs/ONBOARDING_CONTRACT.md`](docs/ONBOARDING_CONTRACT.md)
