# Meridian Loom // First Governed Cell

This tutorial walks through creating your first governed execution cell: a
complete path from action envelope through queue, supervisor, and job inspection.

## Fast path

If you only want the operational path, run this:

```bash
./scripts/bootstrap_embedded.sh
./scripts/tests/rehearse_first_governed_cell.sh
```

That gets you from a clean checkout to a real governed action rehearsal with
artifacts on disk. The rest of this document explains what those artifacts are.

## Prerequisites

You have already run the bootstrap:

```bash
./scripts/bootstrap_embedded.sh
```

If not, run it now. It builds the binary, initializes a workspace, and verifies
the environment.

## What is a governed cell?

A governed cell is the smallest unit of governed execution in Loom:

1. **Envelope** -- a normalized action request with identity, cost, and resource
2. **Enqueue** -- the action enters the runtime queue as a pending job
3. **Supervisor** -- the supervisor picks up the job, evaluates governance gates, and executes
4. **Job record** -- the result is persisted in the runtime job ledger

Every step leaves an artifact. Every step is inspectable. That is the point.

## Artifact map

| Surface | What it tells you | Where it lands |
|---|---|---|
| Envelope | identity, resource, cost, action | `artifacts/shadow/decision.json` and runtime request artifacts |
| Queue | pending work and policy bucket | `state/runtime/queue/pending/<policy_class>/` |
| Job ledger | persisted job lifecycle | `state/runtime/jobs/<input_hash>/job.json` |
| Audit | kernel-owned runtime event trail | `kernel/runtime_audit/loom_runtime_events.jsonl` |
| Parity | reference vs runtime truth | `artifacts/parity/stream.jsonl` and `artifacts/parity/latest.json` |

## Setup

This tutorial uses a fixture-backed kernel so the governance gates have real
allow/deny behavior without needing the full Meridian Kernel deployment.

The rehearsal script at `scripts/tests/rehearse_first_governed_cell.sh` handles the
full setup automatically. The steps below show the exact sequence.

### Variables

```bash
LOOM="${LOOM:-./target/release/loom}"
ROOT_DIR="/tmp/loom-first-cell"
KERNEL_PATH="$(mktemp -d /tmp/loom-first-cell-kernel.XXXXXX)"
```

## Step 1: Create the fixture kernel

The fixture kernel provides the governance surfaces Loom calls during execution:
agent registry, court restrictions, authority checks, budget gates, and audit.

```bash
mkdir -p "${KERNEL_PATH}/kernel/adapters"
```

Create `runtimes.json` (the runtime registry Loom reads):

```bash
cat > "${KERNEL_PATH}/kernel/runtimes.json" <<'EOF'
{
  "runtimes": {
    "local_kernel": {"id": "local_kernel", "label": "Local Kernel Runtime"},
    "loom_native": {
      "status": "experimental",
      "notes": "first governed cell tutorial",
      "contract_compliance": {
        "agent_identity": null,
        "action_envelope": null,
        "cost_attribution": null,
        "approval_hook": null,
        "audit_emission": null,
        "sanction_controls": null,
        "budget_gate": null
      }
    }
  }
}
EOF
```

Create the agent registry, court, authority, treasury, metering, and adapter
fixtures. These are minimal Python scripts that Loom calls through the kernel
contract surface. The rehearsal script creates them for you; the snippets below
show the important shape only.

## Step 2: Initialize the workspace

```bash
${LOOM} init \
  --mode embedded \
  --kernel-path "${KERNEL_PATH}" \
  --root "${ROOT_DIR}" \
  --org-id org_tutorial
```

Expected output:

```
Meridian Loom // INIT
====================
root:        /tmp/loom-first-cell
config:      /tmp/loom-first-cell/loom.toml
mode:        embedded
org_id:      org_tutorial
state_dir:   state
run_dir:     run
log_dir:     logs
artifact_dir:artifacts
kernel_path: /tmp/loom-first-cell-kernel.XXXXXX
status:      initialized local-first runtime root
next_step:   loom doctor --root /tmp/loom-first-cell --format human
```

What happened: Loom created `loom.toml`, the `state` runtime ledger, the `run`
and `logs` service directories, the `artifacts` proof surfaces, worker
paths, and the capsule manifest for your org.

## Step 3: Build an action envelope

```bash
${LOOM} envelope build \
  --root "${ROOT_DIR}" \
  --agent-id agent_tutorial \
  --org-id org_tutorial \
  --action-type research \
  --resource web_search \
  --estimated-cost-usd 0.05 \
  --format human
```

Expected output:

```
Meridian Loom // ACTION ENVELOPE
=================================
agent_id:            agent_tutorial
agent_name:          Tutorial Agent
org_id:              org_tutorial
runtime_id:          local_kernel
runtime_label:       Local Kernel Runtime
action_type:         research
resource:            web_search
estimated_cost_usd:  0.0500
run_id:              (none)
session_id:          (none)
source:              loom_experimental_preflight
input_hash:          a1b2c3d4e5f67890
```

What happened: Loom resolved the agent identity from the kernel registry,
built a normalized envelope with the action parameters, and computed an input
hash. The governance checks that will happen later use this envelope.

## Step 4: Enqueue the action

```bash
${LOOM} action enqueue \
  --root "${ROOT_DIR}" \
  --agent-id agent_tutorial \
  --org-id org_tutorial \
  --action-type research \
  --resource web_search \
  --estimated-cost-usd 0.05 \
  --format human
```

Expected output:

```
Meridian Loom // ACTION ENVELOPE
=================================
agent_id:            agent_tutorial
...
input_hash:          a1b2c3d4e5f67890


Meridian Loom // ACTION ENQUEUED
=================================
queue_path:           /tmp/loom-first-cell/state/runtime/queue/pending/standard/TIMESTAMP-agent_tutorial-a1b2c3d4.json
job_path:             /tmp/loom-first-cell/state/runtime/jobs/a1b2c3d4e5f67890/job.json
input_hash:           a1b2c3d4e5f67890
agent_id:             agent_tutorial
org_id:               org_tutorial
action_type:          research
resource:             web_search
estimated_cost_usd:   0.050000
kernel_path:          /tmp/loom-first-cell-kernel.XXXXXX
next_step:            loom job inspect --job-id a1b2c3d4e5f67890 --root <path>
then:                 loom supervisor run --root <path> --max-jobs 1
```

What happened: Loom wrote a pending queue file under
`state/runtime/queue/pending/<policy_class>/` and created a job record under
`state/runtime/jobs/<input_hash>/`. The job status is now `queued`.

Governance at this step: the envelope was built and validated. The agent
identity was resolved through the kernel registry. No execution happened yet.

## Step 5: Inspect the queued job

```bash
${LOOM} job list --root "${ROOT_DIR}" --format human
```

Expected output:

```
Meridian Loom // JOB LIST
==========================
phase:       experimental runtime-owned job ledger
boundary:    local job state is real; hosted scheduler remains future work

Current state
=============
root:                /tmp/loom-first-cell
status_filter:       (none)
jobs_found:          1

Entries
-------
  a1b2c3d4e5f67890 | status=queued | stage=queue_pending | bucket=pending | agent=agent_tutorial | action=research::web_search | updated_at=TIMESTAMP
```

The job is queued and waiting for the supervisor.

## Step 6: Run the supervisor

```bash
${LOOM} supervisor run \
  --root "${ROOT_DIR}" \
  --kernel-path "${KERNEL_PATH}" \
  --max-jobs 1 \
  --format human
```

Expected output:

```
Meridian Loom // SUPERVISOR RUN
================================
root:            /tmp/loom-first-cell
max_jobs:        1
queue_path:      /tmp/loom-first-cell/state/runtime/queue
...

Processing: a1b2c3d4e5f67890
  decision:    allow
  worker:      python
  exit_code:   0
  result:      success

Completed: 1 job(s) processed
```

What happened: the supervisor:

1. Scanned `state/runtime/queue/pending/<policy_class>/` for queued actions
2. For each action, evaluated the governance decision surface:
   - **Sanction controls** -- checked court restrictions (none for this agent)
   - **Authority check** -- verified the agent has authority for this action type
   - **Budget gate** -- verified the estimated cost is within the agent's budget
3. With an `allow` decision, dispatched the action to a local Python worker
4. Wrote the execution result to the job ledger
5. Emitted a runtime audit entry through the kernel audit path
6. Updated the parity stream

## Step 7: Inspect the completed job

```bash
${LOOM} job inspect \
  --root "${ROOT_DIR}" \
  --job-id a1b2c3d4e5f67890 \
  --format human
```

Expected output:

```
Meridian Loom // JOB INSPECT
=============================
job_id:          a1b2c3d4e5f67890
status:          completed
stage:           runtime_executed
agent_id:        agent_tutorial
org_id:          org_tutorial
action_type:     research
resource:        web_search
estimated_cost:  0.0500
decision:        allow
worker_exit:     0
queue_path:      state/runtime/queue/pending/standard/TIMESTAMP-agent_tutorial-a1b2c3d4.json
runtime_path:    state/runtime/jobs/a1b2c3d4e5f67890/
audit_path:      kernel/runtime_audit/loom_runtime_events.jsonl
parity_path:     artifacts/parity/stream.jsonl
```

## Step 8: Verify the audit and parity trails

```bash
${LOOM} parity report --root "${ROOT_DIR}"
${LOOM} shadow report --root "${ROOT_DIR}"
```

These commands surface the runtime parity stream and shadow report, showing
the governance decision, execution result, and audit evidence for every action
that passed through the supervisor.

## What you just proved

By completing this tutorial, you proved that:

1. **Governed identity resolution works.** The agent identity was resolved
   through the kernel registry, not hardcoded.

2. **The action envelope is normalized.** Every action carries agent identity,
   cost, resource, and action type in a standard format.

3. **The queue boundary is real.** Actions enter a persistent queue before
   execution. The supervisor processes them, not the caller.

4. **Governance gates fire on every action.** Sanction controls, authority
   checks, and budget gates all evaluated before the worker ran.

5. **Execution leaves auditable artifacts.** The job ledger, runtime audit
   trail, and parity stream all recorded what happened, who did it, what
   the governance decision was, and whether the worker succeeded.

6. **Fail-closed is the default.** If any governance gate had denied the
   action, the supervisor would have rejected it with exit code 2. No
   execution would have occurred.

This is one governed cell. A real runtime is many governed cells, scheduled,
isolated, and audited at scale. That is the path Loom is building toward.

## If you want to continue

```bash
./scripts/tests/rehearse_local_sanction_preview.sh
./scripts/tests/rehearse_supervisor_queue.sh
./scripts/tests/rehearse_supervisor_watch.sh
./scripts/tests/rehearse_supervisor_daemon.sh
```

If you are choosing an everyday operating mode, start with `profiles/solo.toml`
and move up only when you need more ceremony, approvals, or isolation.

Read `docs/ARCHITECTURE.md` for the compact architecture and truth boundary.
