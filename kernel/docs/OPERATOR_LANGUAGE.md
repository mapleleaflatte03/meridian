<p align="center">
  <img src="assets/meridian_lockup_flat.svg" alt="Meridian" width="720">
</p>

<p align="center">
  Terminal-first doctrine for kernel proof surfaces and the public Loom scaffold.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/surface-terminal--first-0c1117?style=flat-square" alt="Terminal first">
  <img src="https://img.shields.io/badge/kernel-thin%20CLI%20future-1f6feb?style=flat-square" alt="Kernel CLI future">
  <img src="https://img.shields.io/badge/loom-human%20grammar%20live-0f766e?style=flat-square" alt="Loom grammar live">
  <img src="https://img.shields.io/badge/proof-claims%20bound%20to%20evidence-475569?style=flat-square" alt="Claims bound to evidence">
</p>

<p align="center">
  <a href="../README.md">Kernel README</a> ·
  <a href="LOOM_SPEC.md">Loom Spec</a> ·
  <a href="loom/CLI_AND_MODES.md">Loom CLI</a> ·
  <a href="https://github.com/mapleleaflatte03/meridian-loom">Loom Repo</a>
</p>

<p align="center">
  <img src="assets/meridian_operator_panels.svg" alt="Meridian operator surface overview" width="960">
</p>

> Operator language is part of the product, not documentation garnish. The terminal has to carry the same truth boundary and same authority grammar as the web and proof surfaces.

# Meridian Operator Language

The grammar and vocabulary for all Meridian terminal surfaces.

Meridian is a governance kernel for digital labor. It sits above agent runtimes.
The kernel has 5 primitives (Institution, Agent, Authority, Treasury, Court),
7 contract hooks, and a 3-ledger economy (REP/AUTH/CASH). This document defines
how operators interact with Meridian through terminal commands, what they see in
response, and the canonical vocabulary for governance state.

No production Meridian CLI binary exists today. The kernel modules
(`court.py`, `treasury.py`, `runtime_adapter.py`, `agent_registry.py`,
`authority.py`) already expose argparse CLIs that serve as the existing
foundation. A separate experimental `loom` binary now exists in a local Loom
scaffold, but it only validates setup/operator shape for the planned runtime.
This document defines the target surface that a thin `meridian` entrypoint
would unify under.

---

## 1. Design Principles

**Terminal-first.** Every governance surface must be expressible in a terminal.
Dashboards, TUIs, and web surfaces are projections of the same data. The
terminal representation is the source of truth for output structure.

**Monospace for state, proportional for narrative.** Governance state, scores,
ledger values, and identifiers render in monospace (JetBrains Mono). Prose
descriptions and documentation render in proportional type (Inter or Space
Grotesk). Terminal output is monospace by definition.

**Information density over progressive disclosure.** A single `meridian check`
should surface institution, agents, economy, court, and runtime compliance in
one screen. Operators should not click through menus to find governance state.

**Governance vocabulary, not generic status words.** Agents are `SUSPENDED`, not
"inactive". Treasury is `BELOW_FLOOR`, not "low". Runtimes are `NON_COMPLIANT`,
not "disconnected". The vocabulary is specific to institutional governance.

**No emoji. No color-as-meaning-only.** Color enhances but never carries sole
meaning. Every severity and status is always paired with a text label. Screen
readers and monochrome terminals must remain fully functional.

---

## 2. Command Voice

Commands are verbs. Subcommands are nouns.

```
meridian <verb>                       # top-level action
meridian <noun> <verb>                # scoped action on a primitive
```

Examples:

```
meridian init                         # verb: initialize
meridian check                        # verb: report
meridian agent list                   # noun + verb
meridian treasury status              # noun + verb
meridian court violations             # noun + verb
```

**Flags are explicit.** No positional magic. Flags use `--kebab-case`.

```
--org-id <id>                         # institution scope
--runtime-id <id>                     # runtime scope
--agent-id <id>                       # agent scope
--format json|human                   # output format (default: json)
```

**All output is structured.** JSON is the default. Human-readable tables are
available with `--format human`. Pipe-friendly. Parse-friendly. Governance data
is never trapped inside prose paragraphs.

**Error messages name the failing primitive and the enforcement rule.**

```json
{"error": "budget_gate_denied", "primitive": "treasury", "agent_id": "atlas",
 "requested_usd": 2.50, "remaining_usd": 0.00, "rule": "check_budget"}
```

---

## 3. Core Command Surface

### `meridian init`

Bootstrap a new institution with default agents, treasury, and court.

Wraps `quickstart.py --init-only` and `bootstrap.py`. Creates the founding
institution, provisions 7 agents from the reference ledger, initializes the
capsule (treasury, court records, authority queue), and writes the economy
ledger.

Expected output shape:

```
Institution created:  org_a1b2c3d4  "Demo Org"
Agents provisioned:   7
Treasury balance:     $0.00  (reserve floor $50.00)
Court:                0 violations, 0 appeals
Phase:                FOUNDING
```

### `meridian check`

Full governance snapshot. Reports all 5 primitives, economy state, and active
sanctions in a single output.

Expected output shape:

```
=== Meridian Governance Snapshot ===
Institution:   Demo Org (org_a1b2c3d4)  phase=ACTIVE
Agents:        7 total  7 nominal  0 elevated  0 suspended
Treasury:      $0.00  floor=$50.00  status=BELOW_FLOOR
Court:         0 open violations  0 pending appeals
Authority:     0 active delegations  0 queued
Runtimes:      1 registered  1 compliant

Agent Detail:
  Leviathann   manager     REP= 50  AUTH= 50  risk=NOMINAL
  Atlas        analyst     REP= 50  AUTH= 50  risk=NOMINAL
  Sentinel     verifier    REP= 50  AUTH= 50  risk=NOMINAL
  Forge        executor    REP= 50  AUTH= 50  risk=NOMINAL
  Quill        writer      REP= 50  AUTH= 50  risk=NOMINAL
  Aegis        qa_gate     REP= 50  AUTH= 50  risk=NOMINAL
  Pulse        compressor  REP= 50  AUTH= 50  risk=NOMINAL
```

### `meridian doctor`

Diagnostic command. Verifies state file integrity, checks runtime connectivity,
reports configuration drift between the agent registry and the economy ledger.

Checks performed:
- economy/ledger.json exists and parses
- agent_registry.json exists and parses
- capsule directory structure is intact
- REP/AUTH scores in registry match ledger (drift detection)
- court_records.json integrity
- runtime registry loads and at least one runtime is registered

Output: list of checks with `OK` / `WARN` / `CRITICAL` per check.

### `meridian health`

Lightweight liveness check. Suitable for cron monitoring or uptime scripts.

Checks:
- Kernel state files readable
- Treasury above reserve floor (yes/no)
- No unresolved critical violations

Output: single-line summary + exit code (0 = healthy, 1 = degraded).

```
[OK] kernel: healthy  treasury=$0.00  floor=$50.00  critical_violations=0
```

### `meridian agent list|show|status`

Agent roster. Wraps `agent_registry.py list`.

- `list` -- all agents with REP, AUTH, role, risk state
- `show --agent-id <id>` -- full agent record as JSON
- `status --agent-id <id>` -- current risk state, active sanctions, restrictions

### `meridian treasury status|check-budget`

Treasury surface. Wraps `treasury.py`.

- `status` -- balance, runway, reserve floor, metering summary, funding sources
- `check-budget --agent-id <id> --cost <usd>` -- pre-flight budget gate check

### `meridian court violations|sanctions|appeals`

Court surface. Wraps `court.py`.

- `violations [--agent-id <id>] [--status open]` -- violation records
- `sanctions --agent-id <id>` -- active sanctions and restrictions
- `appeals [--status pending]` -- appeal records

### `meridian authority delegations|queue|kill-switch`

Authority surface. Wraps `authority.py`.

- `delegations` -- active delegation rights
- `queue` -- pending authority requests
- `kill-switch --agent-id <id>` -- immediately zero an agent's AUTH score

### `meridian runtime list|check-contract|check-all`

Runtime registry and compliance. Wraps `runtime_adapter.py`.

- `list` -- all registered runtimes with contract scores
- `check-contract --runtime-id <id>` -- detailed contract compliance report
- `check-all` -- contract check for every registered runtime

### `meridian capsule list|inspect|integrity`

Institution-scoped capsule state.

- `list` -- capsules and their owning institutions
- `inspect --org-id <id>` -- files present in capsule, sizes, timestamps
- `integrity --org-id <id>` -- verify capsule files parse, detect missing files

### `meridian federation peers|inbox|manifest`

Federation surface.

- `peers` -- registered federation peers with trust states
- `inbox` -- pending inbound federation notices
- `manifest` -- this host's public federation manifest

---

## 4. Status Vocabulary

Canonical governance terms. These are the only valid values in structured output.

### Agent risk state

| State | Meaning |
|-------|---------|
| `NOMINAL` | Operating within expected parameters |
| `ELEVATED` | Incident count above threshold; under watch |
| `CRITICAL` | Multiple incidents or active severe sanctions |
| `SUSPENDED` | Removed from task eligibility pending review |
| `QUARANTINED` | Isolated; no execution rights, read-only |
| `DECOMMISSIONED` | Permanently removed from active roster |

### Sanction state

| State | Meaning |
|-------|---------|
| `ACTIVE` | Sanction currently enforced |
| `PROBATION` | Restricted from lead/assign/execute actions |
| `LEAD_BAN` | Cannot lead sprints or direct other agents |
| `ZERO_AUTHORITY` | AUTH score zeroed; minimal action rights |
| `REMEDIATION_ONLY` | May only perform remediation tasks |

### Federation peer state

| State | Meaning |
|-------|---------|
| `TRUSTED` | Peer accepted; envelopes processed |
| `SUSPENDED` | Peer temporarily blocked; envelopes rejected |
| `REVOKED` | Peer permanently removed from federation |

### Runtime compliance

| State | Meaning |
|-------|---------|
| `COMPLIANT` | 7/7 contract hooks satisfied |
| `PARTIAL` | 1-6/7 contract hooks satisfied |
| `NON_COMPLIANT` | 0/7 contract hooks satisfied |
| `PLANNED` | Runtime registered but no compliance data |

### Treasury state

| State | Meaning |
|-------|---------|
| `FUNDED` | Balance above reserve floor |
| `BELOW_FLOOR` | Balance below reserve floor; payouts blocked |
| `BLOCKED` | Treasury operations suspended (phase gate or policy) |

### Institution phase

| State | Meaning |
|-------|---------|
| `FOUNDING` | Initial bootstrap; not yet fully operational |
| `ACTIVE` | Normal operation |
| `SUSPENDED` | Operations paused by owner or policy |
| `DISSOLVED` | Institution terminated |

### Capsule integrity

| State | Meaning |
|-------|---------|
| `INTACT` | All expected files present and parseable |
| `DRIFT_DETECTED` | Registry/ledger mismatch or unexpected file state |
| `CORRUPT` | Files missing, unparseable, or structurally invalid |

---

## 5. Output Severity Levels

How the terminal communicates urgency. Every output line that reports state
uses this format:

```
[SEVERITY] primitive: message
```

| Level | Meaning | Operator action |
|-------|---------|-----------------|
| `OK` | Nominal, no action needed | None |
| `NOTICE` | Informational, operator should be aware | Read and acknowledge |
| `WARN` | Degraded, action recommended | Investigate and plan remediation |
| `CRITICAL` | Enforcement active or imminent | Immediate attention required |
| `BLOCKED` | Operation cannot proceed | Must resolve before continuing |

Examples:

```
[OK] treasury: balance $150.00 above reserve floor $50.00
[NOTICE] court: 1 appeal pending review
[WARN] treasury: balance $0.00 below reserve floor $50.00
[WARN] agent: atlas incident_count=4 risk=ELEVATED
[CRITICAL] court: agent forge under REMEDIATION_ONLY sanction
[BLOCKED] budget_gate: agent atlas cost $2.50 exceeds remaining budget $0.00
[BLOCKED] treasury: payout denied, balance below reserve floor
```

---

## 6. Proof Surface Commands

How operators verify claims about the kernel.

### `meridian proof-bundle`

Generate the public proof bundle. Calls `examples/generate_public_proof_bundle.py`.
Outputs a JSON artifact containing federation summaries, adapter proofs, and
an explicit `not_live_proven` list. Add `--format human` when the operator
needs a terminal summary instead of the machine artifact. The bundle is the
canonical artifact for external verification.

```
meridian proof-bundle [--format human|json] [--live-manifest-url <url>]
```

### `meridian proof-matrix`

Print the claim-to-evidence map from `docs/PROOF_MATRIX.md`. Each row maps a
public claim to its proof artifact (test file, live endpoint, or runner output).

```
meridian proof-matrix [--format human|json]
```

### `meridian verify-runtime --runtime-id <id>`

Run contract compliance check against the runtime registry. Wraps
`runtime_adapter.py check-contract`. Reports satisfied hooks, gaps, unknown
hooks, and the overall compliance verdict.

```
meridian verify-runtime --runtime-id loom_native
```

```
=== Contract Check: loom_native ===
Status:    ACTIVE
Score:     7/7
Native:    agent_identity, action_envelope, cost_attribution, approval_hook, ...
Verdict:   Runtime 'loom_native' satisfies all 7 constitutional requirements
           natively through governed capability dispatch.
```

### `meridian verify-attestation` (future)

Check Sigstore signature on a release artifact. Not implemented. Listed here to
reserve the command surface for supply-chain verification.

---

## 7. First-Run Experience

What an operator sees when they run `meridian init` followed by `meridian check`
for the first time. This is the target "governance is visible and real in 60
seconds" experience.

```
$ meridian init

  Meridian Constitutional Kernel -- Quickstart

  -> Checking Python version... OK
  -> Creating economy ledger
  -> Running kernel bootstrap
  Created founding org: org_a1b2c3d4
    Registered: agent_manager (Manager)
    Registered: agent_atlas (Atlas)
    Registered: agent_sentinel (Sentinel)
    Registered: agent_forge (Forge)
    Registered: agent_quill (Quill)
    Registered: agent_aegis (Aegis)
    Registered: agent_pulse (Pulse)
    Initialized capsule authority queue
    Initialized capsule court records

  Initialization complete.

$ meridian check

  === Meridian Governance Snapshot ===
  Institution:   Demo Org (org_a1b2c3d4)  phase=ACTIVE
  Agents:        7 total  7 nominal  0 elevated  0 suspended
  Treasury:      $0.00  floor=$50.00  status=BELOW_FLOOR
  Court:         0 open violations  0 pending appeals
  Authority:     0 active delegations  0 queued
  Runtimes:      1 registered  1 compliant

  Agent Detail:
    Leviathann   manager     REP= 50  AUTH= 50  risk=NOMINAL
    Atlas        analyst     REP= 50  AUTH= 50  risk=NOMINAL
    Sentinel     verifier    REP= 50  AUTH= 50  risk=NOMINAL
    Forge        executor    REP= 50  AUTH= 50  risk=NOMINAL
    Quill        writer      REP= 50  AUTH= 50  risk=NOMINAL
    Aegis        qa_gate     REP= 50  AUTH= 50  risk=NOMINAL
    Pulse        compressor  REP= 50  AUTH= 50  risk=NOMINAL

  [WARN] treasury: balance $0.00 below reserve floor $50.00

$
```

Five primitives reporting. All agents visible. Treasury state explicit. Court
empty. One warning surfaced because treasury is below floor. Governance is real
and auditable from the first command.

---

## 8. Terminal Color Mapping

CSS palette mapped to ANSI 256-color codes for terminal rendering. These values
correspond to the brand palette defined in `docs/BRAND_ASSETS.md`.

| Semantic name | CSS value | ANSI 256 | Usage |
|---------------|-----------|----------|-------|
| `--accent` | `#4fc3f7` | 117 (light cyan) | Primary interactive elements, command names |
| `--glow` | `#00e5ff` | 87 (bright cyan) | Highlights, active selections |
| `--green` | `#4caf50` | 71 (green) | `OK` severity, `COMPLIANT` status |
| `--gold` | `#ffd54f` | 221 (gold) | `NOTICE` severity, score values |
| `--warn` | `#ffa726` | 214 (orange) | `WARN` severity, `BELOW_FLOOR` status |
| `--critical` | `#ef5350` | 203 (red) | `CRITICAL` / `BLOCKED` severity |
| `--dim` | `#666666` | 242 (gray) | Decorators, separators, timestamps |
| `--fg` | `#e0e0e0` | 253 (light gray) | Default foreground text |

Color is never the sole indicator. Every colored element is paired with a text
label (`[OK]`, `[WARN]`, `COMPLIANT`, `BLOCKED`, etc.). A monochrome terminal
must convey the same information as a color terminal.

---

## 9. Loom-Specific Commands

Meridian Loom is Meridian's official first-party execution runtime (see
`docs/LOOM_SPEC.md`). Current status: public runtime with bounded local proof
and still-bounded hosted/runtime claims. The runtime already exposes `loom
doctor`, `loom status`, `loom contract show`, `loom job list`, `loom job inspect`,
`loom shadow decide`, `loom shadow enforce`, `loom action execute`, and
`loom parity report` as real operator surfaces. This section defines the target
command surface and the operator language those shipping surfaces should keep
growing into.

All Loom commands are prefixed `loom`, not `meridian`. Loom is the runtime.
Meridian is the governance kernel. The namespaces are separate.

Current human-mode rehearsal output already uses the canonical header grammar:

```text
Meridian Loom // INIT
Meridian Loom // DOCTOR
Meridian Loom // HEALTH
Meridian Loom // STATUS
Meridian Loom // CONFIG
Meridian Loom // CONTRACT
Meridian Loom // AGENT IDENTITY
Meridian Loom // ACTION ENVELOPE
Meridian Loom // CAPSULE INSPECT
Meridian Loom // JOB LIST
Meridian Loom // JOB INSPECT
Meridian Loom // SUPERVISOR STATUS
Meridian Loom // SUPERVISOR DAEMON
Meridian Loom // SHADOW PREFLIGHT
Meridian Loom // SHADOW DECISION
Meridian Loom // RUNTIME EXECUTE
Meridian Loom // SHADOW REPORT
Meridian Loom // PARITY REPORT
Meridian Loom // HELP
```

### Lifecycle

```
loom start [--config loom.toml]       # start the Loom runtime
loom stop                             # graceful shutdown
loom restart                          # stop + start
```

### Health

```
loom health                           # structured health report
```

Expected output shape:

```json
{"status": "healthy", "uptime_seconds": 3600, "workers": 4,
 "contract_compliance": "7/7", "governance_bridge": "connected"}
```

### Shadow Mode

Shadow mode runs Loom alongside the legacy runtime, receiving the same inputs, discarding
outputs. Used during Phase 1 migration to verify governance hook compliance
without risk.

```
loom shadow start                     # enter shadow mode
loom shadow stop                      # exit shadow mode
loom shadow report                    # divergence report vs. primary runtime
```

### Contract Compliance

```
loom contract                         # report hook compliance from registry
```

### Worker Management

```
loom worker list                      # active workers with language and state
loom worker spawn --type python       # spawn a new worker process
loom worker kill --worker-id <id>     # terminate a worker
```

### Capsule Lifecycle

```
loom capsule mount --org-id <id>      # mount institution capsule into runtime
loom capsule unmount --org-id <id>    # unmount capsule
```

---

## 10. What This Document Is Not

**Not a CLI implementation spec.** This document does not define argument
parsing, exit codes, shell completion, or binary packaging. Those belong in an
implementation-level spec when a `meridian` entrypoint is built.

**Not a TUI wireframe.** Terminal UI layout, scrolling, panels, and interactive
elements are a separate concern. This document defines the data and vocabulary
that a TUI would render.

**Not a promise that all commands exist today.** The kernel modules
(`runtime_adapter.py`, `court.py`, `treasury.py`, `agent_registry.py`,
`authority.py`) already expose argparse-based CLIs that cover most of the
`meridian *` surface. A unified entrypoint would compose these modules. The
`loom *` commands are entirely future.

**This is the operator language.** The grammar and vocabulary that all Meridian
terminal surfaces share -- CLI, TUI, log output, monitoring alerts, and
federation diagnostics. Any surface that talks to an operator uses these terms,
these severity levels, and this output structure.
