<p align="center">
  <img src="../assets/meridian_lockup_flat.svg" alt="Meridian" width="720">
</p>

<p align="center">
  Current Loom commands, operating modes, and the honest “user only needs Loom” path.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/cli-official%20runtime%20surface-0c1117?style=flat-square" alt="CLI official runtime surface">
  <img src="https://img.shields.io/badge/modes-embedded%20shadow%20standalone-1f6feb?style=flat-square" alt="Embedded, shadow, standalone">
  <img src="https://img.shields.io/badge/operator-human%20grammar%20implemented-0f766e?style=flat-square" alt="Human grammar implemented">
</p>

<p align="center">
  <a href="../LOOM_SPEC.md">Loom Spec</a> ·
  <a href="PACKAGING_AND_INSTALL.md">Packaging</a> ·
  <a href="SHADOW_PREREQUISITES.md">Shadow Prerequisites</a> ·
  <a href="https://github.com/mapleleaflatte03/meridian-loom">Loom Repo</a>
</p>

# Meridian Loom // CLI and Operating Modes

**Status:** Design document plus official first-party runtime surface

## CLI Surface

The public `loom` binary already exists as Meridian's first-party runtime CLI.
It is still bounded in some hosted/runtime claims, but it does provide a real
command surface for setup, inspection, shadow rehearsal, fail-closed runtime
execution, runtime-side audit artifacts, and parity reporting.

### Current runtime commands

```
loom init              Create loom.toml and initialize local state
loom help              Show the grouped runtime command surface
loom doctor            Validate config, local state, kernel path, and registry access
loom health            Structured health check
loom status            Human-readable status summary
loom config show       Print resolved configuration
loom contract show     Show current registry-declared compliance state
loom agent resolve     Resolve governed agent identity against the kernel registry
loom envelope build    Construct a normalized action envelope
loom capsule inspect   Inspect the local capsule boundary
loom job list          Show persisted runtime-owned job state
loom job inspect       Inspect a specific job lifecycle snapshot
loom action enqueue    Materialize a queued governed action artifact
loom action execute    Rehearse fail-closed execution and write runtime/parity artifacts
loom service start     Start the local runtime service rehearsal shell
loom service status    Inspect the local runtime service state
loom service submit    Submit a governed action through the service boundary
loom service import-commitments Import sender-side execution_request delivery refs
loom service stop      Request a clean stop for the local runtime service shell
loom supervisor run    Process queued actions through the local queue supervisor
loom supervisor watch  Poll the local queue supervisor and write heartbeat/status artifacts
loom supervisor status Read the latest bounded supervisor state and heartbeat summary
loom supervisor daemon start  Spawn a local daemon rehearsal for the queue supervisor
loom supervisor daemon status Show the daemon rehearsal lifecycle state
loom supervisor daemon stop   Request a clean local daemon stop
loom shadow preflight  Capture 7-surface experimental preflight events
loom shadow decide     Materialize the current allow/deny gate outcome
loom shadow enforce    Return fail-closed exit codes from the same gate outcome
loom shadow compare    Diff reference-adapter events vs Loom shadow events
loom shadow report     Show the latest preflight/comparison report
loom parity report     Show the runtime-side parity stream and latest parity report
```

Current human-mode output uses the same `Meridian Loom // ...` header grammar
across init, doctor, health, status, config, contract, identity, envelope,
capsule, job, shadow, runtime, parity, and help surfaces so the operator shell
reads as one system instead of a pile of unrelated subcommands.
`loom supervisor watch` extends that grammar into a bounded loop surface with
heartbeat/status artifacts instead of introducing a separate ad hoc operator style.
`loom supervisor daemon start/status/stop` extend that same grammar into a local
daemon-lifecycle surface; this is still a rehearsal shell, not hosted runtime truth.
When stdout is a TTY, the CLI now adds a restrained ANSI shell layer for
headers and status cues. `NO_COLOR=1` disables it without changing the
underlying artifact grammar.

`loom init` accepts `--mode shadow|standalone|embedded` and `--kernel-path <path>`.
The current rehearsal path uses `embedded` plus a kernel path so Loom can
read the runtime registry and agent registry honestly. `loom init` writes a
`loom.toml` in the target directory and refuses to overwrite an existing config.

### Future commands (not implemented yet)

These remain planned runtime surfaces, not current CLI truth:

```
loom start             Start the Loom runtime supervisor
loom stop              Graceful shutdown of the runtime supervisor
loom worker list       List live worker processes
loom worker spawn <id> Spawn a worker (debug/dev)
loom worker stop <id>  Stop a live worker
loom schedule list     Show scheduled jobs
loom schedule run <id> Trigger a job immediately
```

## Operating Modes

Loom has three modes. The mode is set in `loom.toml` under `[runtime].mode`.

### 1. Shadow mode (`mode = "shadow"`)

**Purpose:** Eventually run alongside the primary runtime (legacy runtime) without
affecting production. Loom will receive the same inputs and run the same
governance hooks while its outputs are discarded.

**When to use:** Phase 1 — proving that Loom's governance checks produce
identical results to the primary runtime.

**Current runtime truth:**
- `loom shadow preflight` captures experimental events for all 7 contract surfaces
- `loom shadow decide` writes a standalone decision artifact (`decision.json`)
- that decision surface unions a local sanction preview from the resolved
  identity snapshot with the read-only reference gate result
- `loom shadow enforce` uses the same effective decision surface but returns `0`
  for allow and `2` for deny so shell automation can fail closed
- `loom action execute` uses that same effective decision surface to materialize
  a runtime execution receipt, a runtime-side audit artifact, a parity
  stream, and a governed local worker dispatch when the decision is `allow`
- `loom job list` and `loom job inspect` now surface persisted runtime-owned
  job state from `.loom/runtime/jobs/<input_hash>/job.json`
- `loom action enqueue` and `loom supervisor run` now exercise the same allow/
  deny boundary through a local queue supervisor, moving queued artifacts from
  `.loom/runtime/queue/pending/` into `.loom/runtime/queue/processed/`
- `loom service start/status/submit/stop` now expose a local runtime-service
  shell with runtime state, service events, ingress receipts, and truthful
  transport reporting
- when the Unix socket boundary is unavailable, that same service shell falls
  back to file-backed ingress under `.loom/runtime/ingress/`
- `loom service start --http-address ... --service-token ...` can now expose a
  tokenized local HTTP control plane, and the same service shell can accept
  `GET /status`, `POST /submit`, and `POST /stop` over that local boundary
- `loom service import-commitments` can now import sender-side
  `execution_request` delivery refs from a commitments snapshot into the local
  Loom queue and write import markers under
  `.loom/runtime/imports/commitment_execution/`
- `loom supervisor watch` now runs that same local queue supervisor in a bounded
  polling loop and writes `.loom/runtime/supervisor/status.json` plus
  `.loom/runtime/supervisor/heartbeat.jsonl`
- `loom supervisor daemon start/status/stop` now wrap that same local queue
  supervisor in a real local daemon-lifecycle shell with `runtime_state.json`,
  background logging, and stop-request handling
- `loom shadow compare` compares Loom's captured events against a
  kernel-reference event log, not a live legacy runtime runtime stream
- `loom shadow report` surfaces the latest comparison or preflight report
- `loom parity report` surfaces the runtime-side parity report and, when
  available, a per-action legacy runtime probe artifact and probe stream captured
  from the founder host

**What it does not do yet:**
- It does not subscribe to live production traffic
- It does not shadow the real legacy runtime runtime process
- It does not prove per-action live runtime parity
- It does not prove a hosted runtime service or durable ingress transport
- It does not prove live sender-host commitment import cutover
- It does not prove a hosted daemon supervisor or scheduler

**What Phase 1 will eventually prove:** Governance-check parity without production risk.

### 2. Standalone mode (`mode = "standalone"`)

**Purpose:** Loom is the only runtime. It owns lifecycle, execution,
governance bridging, and transport.

**When to use:** Phase 5 — after Loom has proven 7/7 compliance and passed
the legacy runtime retirement gate.

**What it does:**
- Full lifecycle management (start, stop, health, restart)
- Worker spawning and isolation
- Transport adapters (Telegram, MCP, HTTP)
- Governance hooks called for every action
- Scheduler/cron execution

**Requirement:** The Meridian Kernel must be accessible — either as a local
path or (future) a remote API.

### 3. Embedded mode (`mode = "embedded"`)

**Purpose:** Loom bundles a compiled subset of the kernel's governance checks
so that a user can run Loom without separately installing or configuring the
full kernel.

**When to use:** When a user wants to try Loom with minimal setup. The
embedded kernel subset provides governance checks but does not include the
full kernel administration surface (institution management, court operations,
etc.).

**What it does:**
- Includes a vendored, compiled governance library derived from the kernel
- Provides the 7-hook contract interface without a separate kernel process
- Uses a local SQLite store for audit log, budget tracking, and agent state
- Does NOT provide the full kernel administration CLI or multi-institution
  routing

**Trade-offs:**

| Aspect | Embedded | Standalone (with separate kernel) |
|--------|----------|-----------------------------------|
| Setup complexity | Lower — single binary | Higher — two components |
| Governance surface | 7 hooks only | Full kernel (court, institution mgmt, etc.) |
| Multi-institution | No | Yes (kernel supports it) |
| Audit trail | Local SQLite | Kernel's canonical audit log |
| Upgrades | Coupled to Loom releases | Independent kernel/Loom upgrades |

**When embedded mode is NOT enough:**
- You need multi-institution governance
- You need the court/sanctions administrative surface
- You need the kernel's canonical audit log format for compliance
- You want to run multiple runtimes against one kernel

In those cases, use standalone mode with a separately installed kernel.

## How "user only needs Loom" works

For a user who wants to evaluate Loom without understanding the full Meridian
ecosystem:

```bash
# 1. Build Loom from source
cargo build

# 2. Initialize with embedded governance + kernel path
./target/debug/loom init --mode embedded --kernel-path /path/to/meridian-kernel

# 3. Inspect the scaffold honestly
./target/debug/loom doctor --format human
./target/debug/loom contract show
./target/debug/loom action execute --agent-id <id> --action-type research --resource web_search --estimated-cost-usd 0.05 --format human

# 4. Inspect parity
./target/debug/loom parity report
```

This creates a `loom.toml` with `mode = "embedded"` and initializes the local
state boundary. In the current scaffold, the user gets:
- local config and capsule state
- doctor/health/status surfaces
- registry-backed contract inspection
- agent identity resolution against the kernel registry
- action envelope construction
- a runtime-owned job ledger with `loom job list` / `loom job inspect`
- experimental shadow preflight, decision capture, comparison, fail-closed
  runtime rehearsal, queue-backed supervisor rehearsal, local runtime service
  rehearsal, sender-side commitment import, runtime-side audit artifacts, and
  parity reporting

They do **not** get:
- a running runtime supervisor
- a hosted runtime service
- a long-running worker supervisor
- a hosted daemon supervisor or scheduler
- a hosted long-running scheduler or worker pool
- multi-institution support
- native sanction enforcement in a hosted worker runtime
- the hosted kernel's canonical audit log
- per-action live legacy runtime parity against a real legacy runtime action execution stream

Those remain future Loom expansion work, not current runtime truth.

## CLI design principles

1. **No implicit behavior.** Every action requires an explicit command or
   config entry. Loom does not auto-discover or auto-configure.
2. **Structured output.** `loom health`, `loom contract show`, and the shadow
   surfaces return JSON or human-readable output. Comparison results now include
   hook-level divergence details instead of only aggregate counts.
3. **No destructive defaults.** `loom init` refuses overwrite. Future runtime
   lifecycle commands should also fail closed when config or kernel bindings are missing.
4. **Config is the truth.** The CLI modifies `loom.toml`; `loom.toml` drives
   behavior. There is no hidden state beyond what the config file declares.
