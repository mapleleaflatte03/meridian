<p align="center">
  <img src="assets/meridian_lockup_flat.svg" alt="Meridian" width="720">
</p>

<p align="center">
  Public runtime thesis for Meridian-native execution, with strict separation between current Loom truth and future expansion claims.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/phase-official%20first--party%20runtime-0c1117?style=flat-square" alt="Official first-party runtime">
  <img src="https://img.shields.io/badge/proven-hooks-7%2F7-0f766e?style=flat-square" alt="7 of 7 proven hooks">
  <img src="https://img.shields.io/badge/runtime-Meridian%20Loom-1f6feb?style=flat-square" alt="Meridian Loom runtime">
  <img src="https://img.shields.io/badge/focus-product%20shape%20and%20operator%20shape-0f766e?style=flat-square" alt="Product and operator shape">
</p>

<p align="center">
  <a href="https://github.com/mapleleaflatte03/meridian-loom">Loom Repo</a> ·
  <a href="loom/CLI_AND_MODES.md">CLI and Modes</a> ·
  <a href="loom/PACKAGING_AND_INSTALL.md">Packaging</a> ·
  <a href="loom/SHADOW_PREREQUISITES.md">Shadow Prerequisites</a> ·
  <a href="https://github.com/mapleleaflatte03/meridian-loom/blob/main/docs/LOOM_100_IMPROVEMENTS.md">100 Improvements</a>
</p>

# Meridian Loom // Runtime Specification

**Status:** OFFICIAL FIRST-PARTY RUNTIME WITH BOUNDED LOCAL PROOF
**Core language:** Rust (supervisor / runtime core)
**Worker languages:** Python, TypeScript (where appropriate)
**Sandbox:** WASM for capability modules
**Registry ID:** `loom_native`

Meridian Loom is the Meridian-native execution runtime. It implements all 7
governance contract hooks natively — without adapter translation — and is the
primary runtime for the Meridian stack.

Loom is polyglot by design: a Rust supervisor manages lifecycle, isolation, and
governance bridging, while workers may be written in Python or TypeScript. WASM
sandboxing is used for capability modules where isolation matters.

This document began as a pure spec. Loom now ships as Meridian's first-party
runtime repo and local operator surface. The broader speculative and near-term
runtime agenda now lives in the separate
research docket at
[`meridian-loom/docs/LOOM_100_IMPROVEMENTS.md`](https://github.com/mapleleaflatte03/meridian-loom/blob/main/docs/LOOM_100_IMPROVEMENTS.md),
so this spec can stay focused on truth boundary, contract shape, and migration.
The runtime now includes bounded local surfaces for all seven contract areas.
Several important gaps have moved forward, but not to broad hosted runtime proof:
- `audit_emission` now writes runtime-side artifacts through the kernel-owned
  `audit.py log-runtime` CLI path into `kernel/runtime_audit/loom_runtime_events.jsonl`
  when a kernel is present, with a local fallback otherwise. This is still not
  the hosted kernel's global audit trail
- `sanction_controls`, `approval_hook`, and `budget_gate` are still sourced
  from read-only kernel reference gates, but `loom action execute` now enforces
  the current effective allow/deny outcome fail-closed instead of stopping at a
  shell-only preflight path
- when that effective decision is `allow`, `loom action execute` now dispatches
  an experimental local worker through a governed supervisor path and writes
  request/result/log artifacts under `.loom/runtime/jobs/<input_hash>/`
- `loom action enqueue` and `loom supervisor run` now materialize and process
  queued actions under `.loom/runtime/queue/`, exercising the same decision and
  worker dispatch path through a local queue supervisor
- `loom job list` / `loom job inspect` now surface persisted runtime-owned job
  state from `.loom/runtime/jobs/<input_hash>/job.json`, so the operator can
  inspect queue, decision, execution, parity, and audit paths without manual
  file spelunking
- `loom supervisor watch` now runs that same local queue supervisor in a bounded
  polling loop and writes `.loom/runtime/supervisor/status.json` plus
  `.loom/runtime/supervisor/heartbeat.jsonl`. This makes local supervisor state
  inspectable, but it is still not a daemonized or hosted scheduler
- `loom supervisor daemon start/status/stop` now wrap that same queue supervisor
  in a real local daemon-lifecycle shell with `runtime_state.json`, background
  logging, and stop-request handling. This is still a bounded local rehearsal,
  not a hosted supervisor service
- `loom service start/status/submit/stop` now wrap that same local runtime path
  in a service shell with runtime state, service events, ingress receipts, and
  truthful transport reporting. When the local Unix socket boundary is
  unavailable, the service falls back to file-backed ingress under
  `.loom/runtime/ingress/`
- `loom service start --http-address ... --service-token ...` can now expose a
  tokenized local HTTP control plane with `GET /status`, `POST /submit`, and
  `POST /stop` when the host permits local binding
- `loom service import-commitments` can now import sender-side
  `execution_request` delivery refs from a commitments snapshot into the local
  Loom queue, writing import markers under
  `.loom/runtime/imports/commitment_execution/`. This is a real local ingress
  seam from kernel truth, not hosted cross-host replacement
- the parity surface now emits `.loom/parity/stream.jsonl` and
  `.loom/parity/latest.json`, and can capture per-action live legacy runtime probe
  artifacts under `.loom/parity/legacy/<input_hash>.json` plus
  `.loom/parity/legacy_live_stream.jsonl`
- that same parity surface now persists a stable-ID action comparison receipt
  under `.loom/parity/comparisons/<input_hash>.json` plus
  `.loom/parity/comparison_stream.jsonl`, so Loom runtime events, reference
  decisions, and audit IDs can be inspected together. This is stronger than the
  old file-only compare, but it is still not hosted per-action runtime parity
- `loom shadow decide` / `loom shadow enforce` now union that read-only gate
  result with a local sanction preview derived from the resolved identity
  snapshot. If the snapshot contains `execute` or `remediation_only`, the
  decision fails closed locally even if the reference gate would otherwise allow
- `loom shadow decide` now writes a standalone decision artifact using the same
  effective decision surface, but that is still an experimental preflight
  surface, not governed runtime enforcement
- `loom shadow enforce` now returns fail-closed exit codes from that same
  decision surface, but it is still an experimental operator aid, not runtime
  enforcement
- `loom action execute` now materializes a runtime execution receipt, runtime
  audit artifact, and parity stream for the same effective decision surface, but
  it is still an experimental rehearsal command, not a governed worker runtime
- the local Wasm lane is now executable via `loom wasm run`, which proves
  Wasmtime store limits and pooling profiles through a local guest path without
  claiming a hosted capability runtime already exists

It does provide governed local execution and native contract coverage on the
current local/runtime path. What remains bounded is broader hosted proof,
transport breadth, and every future deployment mode.

---

## 1. Separation of Concerns

**Meridian Kernel** owns governance:
- Institution, Agent, Authority, Treasury, Court
- 7 contract hooks (identity, envelope, cost, approval, audit, sanctions, budget)

**Meridian Loom** owns execution:
- Process lifecycle (start, stop, health, restart)
- LLM call routing and model selection
- Tool execution and sandboxing
- Channel/transport adapters (Telegram, MCP, A2A, HTTP)
- Session management and context windows
- Container/WASM isolation
- Cron/scheduling primitives

**The boundary:** Loom calls UP into the Kernel via the 7 hooks.
The Kernel never calls down into Loom.

---

## 2. Contract Requirements

Every runtime in the Meridian ecosystem must satisfy 7 contract hooks
(defined in `kernel/runtimes.json` under `contract_requirements`).

| # | Hook | What Loom Must Do |
|---|------|-------------------|
| 1 | `agent_identity` | Provide stable unique agent ID mapping to kernel agent records |
| 2 | `action_envelope` | Wrap each governed action: agent_id, action_type, resource, estimated_cost_usd |
| 3 | `cost_attribution` | Report actual cost post-action via kernel `metering.record()` |
| 4 | `approval_hook` | Call `check_authority(agent_id, action)` before privileged actions; block on `False` |
| 5 | `audit_emission` | Emit structured events to kernel audit_log (timestamp, agent_id, action, outcome) |
| 6 | `sanction_controls` | Query `get_restrictions(agent_id)` per session; enforce restrictions |
| 7 | `budget_gate` | Call `check_budget(agent_id, cost)` before cost-bearing ops; block on `False` |

Current compliance: **7/7 native** on the active `loom_native` runtime entry.

---

## 3. Target Performance

These are **directional goals**, not official public benchmarks. Loom is now a
governed execution runtime, but this section is still not claiming rigorously
published benchmark numbers.
Competitor observations are labeled with confidence based on source quality and
recency.

| Metric | Directional Target | Rationale | Confidence |
|--------|--------------------|-----------|------------|
| Memory | <50 MB | Comparable Rust runtimes (ZeroClaw, SkyClaw) report <15 MB in their docs; legacy runtime's JS runtime is observed at ~100 MB in local testing. Loom targets well below legacy runtime but does not claim parity with minimal embedded runtimes. | DIRECTIONAL — no Loom measurement exists |
| Cold start | <500 ms | ZeroClaw docs claim 10ms; legacy runtime observed at ~30s locally. Loom's target is conservative relative to reported Rust runtimes but aspirational relative to current state (no code). | DIRECTIONAL — no Loom measurement exists |
| Isolation | WASM + container | OpenFang demonstrates dual-metered WASM isolation. Loom plans the same architecture class. | DESIGN GOAL |
| Contract compliance | 7/7 native | The kernel defines 7 hooks. Loom implements them natively without adapter translation. | CURRENT RUNTIME ENTRY: 7/7 |

**What these numbers are not:**
- Not official Meridian benchmark publications yet
- Not guaranteed post-implementation figures
- Not claims about competitor runtimes beyond what their public docs state

Actual Loom performance numbers will be published when Phase 1 (shadow mode)
produces measurable runtime data.

---

## 4. Module Layout

```
meridian-loom/
  loom.toml                       # Runtime config
  Cargo.toml                      # Rust supervisor manifest

  # ── Rust core (supervisor, lifecycle, governance bridge) ──
  src/
    main.rs                       # Entry point
    runtime/
      mod.rs
      lifecycle.rs                # Start, stop, health, restart
      session.rs                  # Session management
      scheduler.rs                # Cron + night-shift scheduling
    execution/
      mod.rs
      sandbox.rs                  # Container/WASM isolation boundary
      worker_spawn.rs             # Spawn Python/TS/Rust workers
      llm_router.rs               # Model selection + call routing
    transport/
      mod.rs
      telegram.rs                 # Telegram channel adapter
      mcp.rs                      # MCP server/client
      a2a.rs                      # A2A protocol adapter
      http.rs                     # HTTP API surface
    governance/
      mod.rs
      contract_bridge.rs          # 7-hook bridge to Meridian Kernel
      envelope.rs                 # Action envelope construction
      metering_emitter.rs         # Cost attribution emission

  # ── Workers (polyglot — language chosen per task) ──
  workers/
    python/                       # Python workers (research, analysis)
    typescript/                   # TypeScript workers (channel adapters)
    wasm/                         # WASM capability modules (sandboxed tools)

  tests/
    contract_compliance_test.rs   # Proves 7/7 compliance
    shadow_mode_test.rs           # Shadow vs. primary comparison
```

The Rust core handles lifecycle, isolation, and governance bridging. Workers are
spawned as separate processes (Python, TypeScript) or loaded as WASM modules.
The supervisor never assumes all execution logic is Rust.

---

## 5. Phased Migration

### Phase 0 — Spec + Runtime Foundation (complete)
- This document
- Registry entry with native 7/7 compliance, status `"active"`
- Public Loom runtime repo for CLI/setup plus 7-surface local/runtime coverage
- Experimental decision artifact (`loom shadow decide`) for operator review of the
  current effective gate outcome
- Experimental fail-closed command (`loom shadow enforce`) for shell automation
- Experimental fail-closed runtime rehearsal command (`loom action execute`)
- Experimental governed local worker supervisor on allow-path
- Runtime-side canonical artifact under `kernel/runtime_audit/loom_runtime_events.jsonl`
- Bounded `loom supervisor watch` loop with heartbeat/status artifacts
- Local daemon lifecycle rehearsal with runtime state and stop-request handling
- Local runtime service rehearsal with service state, ingress receipts, and
  truthful file-backed ingress fallback
- Sender-side commitment outbox import into the local Loom queue
- Parity stream and latest parity report under `.loom/parity/`
- Optional per-action founder-host legacy runtime live probe artifact captured into the parity surface
- Read-only reference-adapter gate evaluation for sanction/approval/budget surfaces
- Local sanction preview derived from resolved identity restrictions, still
  rehearsal-only and not native runtime enforcement
- No governed execution runtime

### Phase 1 — Shadow Mode
- Loom runs alongside legacy runtime, receiving same inputs, outputs discarded
- Governance hooks call the real kernel
- Target: 2/7 compliance (agent_identity + action_envelope)
- Verification: zero governance-check divergence over 3+ night-shift runs

### Phase 2 — Governed Worker Cells
- Loom executes real agent tasks in isolated cells
- Cost attribution and budget gate implemented
- Target: 5+/7 compliance
- Verification: single governed agent completes end-to-end in Loom

### Phase 3 — Capability ABI
- Stable binary interface for capabilities (tools, transports, sandboxes)
- Loadable without recompilation
- Target: 7/7 compliance maintained

### Phase 4 — Checkpoint/Sanction Native Layer
- Native checkpoint emission and sanction enforcement
- No adapter translation for restrictions
- Target: 7/7 compliance, sanctioned agent blocked natively

### Phase 5 — Native Ingress
- Telegram bot adapter, MCP server, scheduler
- Full legacy runtime replacement
- Justification gate: Phase 4 stable AND owner confirms retirement
- Verification: 7 consecutive clean night-shift runs before legacy runtime retirement

---

## 6. Verification

At each phase, the runtime adapter tooling assesses registry-declared
compliance. The tooling reads the `contract_compliance` fields in
`runtimes.json` and reports their current state — it does not independently
verify a live runtime:

```bash
# Show registry-declared state
python3 kernel/runtime_adapter.py show --runtime_id loom_native

# Report contract compliance from registry
python3 kernel/runtime_adapter.py check-contract --runtime_id loom_native
```

`null` = unproven (no test exists), `true` = proven by a passing test,
`false` = tested and non-compliant.
No field is set to `true` until a test proves it. The registry is the
source of truth; the tooling reports what it says.
