<p align="center">
  <img src="../assets/meridian_lockup_flat.svg" alt="Meridian" width="720">
</p>

<p align="center">
  The gates Loom must satisfy before shadow mode can claim more than rehearsal and report files.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/shadow-currently%20rehearsal-0c1117?style=flat-square" alt="Currently rehearsal">
  <img src="https://img.shields.io/badge/parity-not%20replacement%20proof-8b0000?style=flat-square" alt="Not replacement proof">
  <img src="https://img.shields.io/badge/operator-surface%20real-0f766e?style=flat-square" alt="Operator surface real">
</p>

<p align="center">
  <a href="../LOOM_SPEC.md">Loom Spec</a> ·
  <a href="CLI_AND_MODES.md">CLI and Modes</a> ·
  <a href="PACKAGING_AND_INSTALL.md">Packaging</a> ·
  <a href="https://github.com/mapleleaflatte03/meridian-loom">Loom Repo</a>
</p>

# Meridian Loom // Shadow Mode Prerequisites

## Purpose

This document lists the prerequisites for Loom Phase 1 (shadow mode).
It is a checklist, not a timeline. Some repository-level prerequisites now
exist, but the runtime and verification gates for true Phase 1 shadow mode are
still not met.

Shadow mode means: Loom receives the same input stream as the primary
runtime (legacy runtime), runs its own governance hooks, and discards output.
The only observable effect is a divergence report comparing Loom decisions
against the primary runtime's actual decisions. Zero production impact.

This gate exists so that shadow mode is never attempted on a foundation
that cannot support it. Every box must be checked before the first shadow
run.

---

## Repository Prerequisites

- [x] `meridian-loom` runtime repository created publicly
  - https://github.com/mapleleaflatte03/meridian-loom
- [x] `Cargo.toml` with workspace structure
  - workspace root with `loom-core`, `loom-cli`, `loom-shadow` crates
- [x] CI workflow defined for `cargo build` and `cargo test`
  - GitHub Actions file exists in the public runtime repository
- [x] README with honest status as an official first-party runtime with bounded claims
  - No aspirational feature lists; only what exists and what does not
- [x] Experimental preflight path exists for all 7 governance surfaces
  - `agent_identity`, `action_envelope`, `cost_attribution`, `approval_hook`, `audit_emission`, `sanction_controls`, `budget_gate`
  - shadow-mode proof is still narrower than the active runtime registry entry
- [x] Read-only reference gate surface exists for sanction/approval/budget
  - Loom can compare shadow events against kernel reference-adapter decisions
  - Loom can now also materialize a runtime-side parity stream and latest report
  - per-action live legacy runtime parity still does not exist
- [x] Experimental decision artifact exists
  - `loom shadow decide` writes the current allow/deny outcome to `.loom/shadow/decision.json`
  - still adapter-backed preflight only, not native runtime enforcement
- [x] Experimental fail-closed shell surface exists
  - `loom shadow enforce` returns `0` allow / `2` deny from the same gate result
  - still adapter-backed preflight only, not native runtime enforcement
- [x] Experimental fail-closed runtime rehearsal surface exists
  - `loom action execute` returns the same fail-closed decision and writes
    `.loom/runtime/last_execution.json`
  - runtime-side audit artifacts now land in `kernel/runtime_audit/loom_runtime_events.jsonl` when a kernel audit path is present
  - parity artifacts now land in `.loom/parity/`
  - still rehearsal-only, not a governed worker runtime
- [x] Experimental local runtime service and commitment-import seams exist
  - `loom service start/status/submit/stop` now expose a local runtime service shell
  - the service prefers Unix socket ingress but truthfully falls back to file-backed ingress under `.loom/runtime/ingress/`
  - `loom service import-commitments` can import sender-side `execution_request` delivery refs from commitment snapshots
  - these are local rehearsal seams, not proof that Loom receives the same live input stream as legacy runtime
- [x] Experimental local sanction preview exists
  - derived from the resolved identity snapshot, not a live Loom runtime
  - `execute` / `remediation_only` can deny locally even if the read-only reference gate allows
  - still preflight-only, not native runtime enforcement

---

## Kernel-Side Prerequisites

- [ ] Stable `agent_identity` hook interface documented
  - exists in `RUNTIME_CONTRACT.md`
  - input: agent ID, runtime binding, registry snapshot
  - output: accept / reject / suspend with reason
- [ ] Stable `action_envelope` hook interface documented
  - exists in `RUNTIME_CONTRACT.md`
  - input: action payload, agent context, policy snapshot
  - output: signed envelope with governance metadata
- [x] `kernel/runtimes.json` entry for `loom_native`
  - EXISTS today -- primary Meridian runtime with native 7/7 contract compliance
- [ ] Shadow mode event format defined
  - envelope schema for shadowed actions
  - must include: timestamp, hook name, primary decision, shadow decision
  - must include: input hash for reproducibility
- [ ] Shadow divergence comparison against a primary runtime
  - current runtime can compare Loom shadow events against kernel reference-adapter events
  - current runtime can capture a live legacy runtime proof snapshot into the parity surface
  - future Phase 1 still requires pairing Loom decisions with real per-action legacy runtime runtime decisions

---

## Runtime Prerequisites

- [ ] Rust toolchain installed on build host
  - stable channel, minimum edition 2021
- [ ] `contract_bridge.rs`
  - reads `kernel/agent_registry.json`
  - maps agent IDs to Loom internal representation
  - validates registry schema before accepting
- [ ] `envelope.rs`
  - constructs action envelopes matching kernel format
  - serializes to JSON matching `action_envelope` hook output spec
- [ ] `lifecycle.rs`
  - start command: initialize runtime, load config, bind to event stream
  - health command: return structured status
  - stop command: graceful shutdown, flush pending shadow events
- [ ] Shadow mode receiver
  - accepts same input stream as legacy runtime
  - runs hooks (`agent_identity`, `action_envelope`)
  - discards governance output (does not affect production)
  - writes shadow event log to local file

---

## Verification Prerequisites

- [ ] `loom health` returns structured JSON
  - fields: `version`, `uptime_seconds`, `mode` ("shadow"), `hooks_active`
  - nonzero uptime confirms process is running
- [ ] `loom contract` reads `runtimes.json` and reports satisfaction
  - expected initial output: 2/7 (`agent_identity` + `action_envelope`)
  - remaining 5 hooks listed as null/unsatisfied
- [ ] `loom shadow report` compares governance events
  - reads shadow event log and primary runtime log
  - reports: total events, matches, divergences, divergence percentage
- [x] `loom parity report` surfaces runtime-side parity artifacts
  - reads `.loom/parity/latest.json` and `.loom/parity/stream.jsonl`
  - includes live legacy runtime proof snapshot when available on the founder host
- [ ] 3+ consecutive shadow runs with zero governance divergence
  - each run processes at least 10 governance events
  - zero divergence across all three runs
  - logs retained as evidence artifacts

---

## What This Document Is Not

- Not a timeline or sprint plan.
  There are no dates here because dates without prerequisites are fiction.
- Not a claim that shadow mode is near.
  Even with a public runtime repo, the hook implementation and divergence engine do
  not exist yet.
- Not a Rust tutorial.
  The runtime prerequisites assume familiarity with Rust and Cargo.
- Not an architecture document.
  Architecture decisions belong in the Loom repo once it exists.

This is the gate checklist for Loom Phase 1 entry.
No box, no entry.
