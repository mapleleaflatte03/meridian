# Deployment Guide

This guide explains how to move from the local demo to a real Meridian
deployment without confusing the two.

Meridian Constitutional Kernel is a governance layer. It does not need to own
your runtime to govern it.

## 1. What Quickstart Gives You

`python3 quickstart.py` boots:

- a local demo institution
- a seeded agent registry
- a file-based economy ledger
- the reference workspace at `http://localhost:18901`

This is the fastest way to see all five primitives live. It is **not** the
same thing as a production control plane.

## 2. What A Real Deployment Looks Like

A real deployment has three parts:

1. **Your runtime**
   Runs agents, tool calls, prompts, and external integrations.

2. **Meridian kernel**
   Governs identity, authority, budget, accountability, and sanctions.

3. **Your control plane**
   Optional owner/operator UI or automation built on top of Meridian's JSON API.

```text
Your Runtime  ->  Meridian checks  ->  Your operator surface
             \->  metering/audit   \->  Your logs/backups
```

## 3. The Integration Boundary

Treat these as the deploy boundary:

- the [Constitutional Runtime Contract](RUNTIME_CONTRACT.md)
- the workspace JSON API exposed by `kernel/workspace.py`

If your runtime can satisfy the runtime contract, Meridian can govern it
without needing to become your runtime.

## 4. Minimal Deployment Checklist

### A. Initialize state

Use the repo bootstrap paths first:

```bash
python3 quickstart.py --init-only
```

This reconciles the repo's local demo JSON state for the institution, agents,
economy ledger, and workspace records so the example stays runnable even when
reference state is already checked into git.

### B. Start the reference workspace

```bash
python3 kernel/workspace.py --port 18901
```

Important:
- the built-in workspace is a reference surface
- if you expose it outside localhost, set `MERIDIAN_WORKSPACE_USER` and
  `MERIDIAN_WORKSPACE_PASS` (or point `MERIDIAN_WORKSPACE_CREDENTIALS_FILE`
  at a credentials file) so the workspace self-protects with HTTP Basic auth
- if you want auth and institution binding to agree explicitly, add
  `MERIDIAN_WORKSPACE_AUTH_ORG_ID=<org_id>` or an `org_id:` line in the
  credentials file; the process will refuse to start if that auth scope does
  not match the bound institution
- if you want mutation audit and role checks to bind to a real institution
  member, also add `MERIDIAN_WORKSPACE_USER_ID=<user_id>` or `user_id:` in the
  credentials file
- for programmatic access, issue a session token via `POST /api/session/issue`
  (authenticates with Basic, returns a Bearer token scoped to the institution);
  subsequent requests use `Authorization: Bearer <token>` instead of Basic
- set `MERIDIAN_SESSION_SECRET` to make session tokens survive process restarts;
  revocations are automatically persisted to a file alongside the workspace
- production teams should usually still front it with their own auth/reverse proxy
- many teams will build their own operator UI on top of the JSON API instead

### C. Register or model your runtime

Inspect the seeded runtime registry:

```bash
python3 kernel/runtime_adapter.py list
python3 kernel/runtime_adapter.py check-all
```

Register your own runtime if needed:

```bash
python3 kernel/runtime_adapter.py register \
  --id my_runtime \
  --label "My Runtime" \
  --type hosted \
  --protocols "MCP,custom" \
  --identity_mode api_key
```

Keep agent bindings and runtime registry entries coherent:
- set or review each agent's `runtime_binding` in `kernel/agent_registry.json`
- confirm the binding appears in `GET /api/agents` and `GET /api/status`
- confirm the corresponding runtime metadata appears in `GET /api/runtimes`

### D. Enforce governance checks in your runtime

Before privileged actions:
- call `check_authority(agent_id, action_type)`
- call `check_budget(agent_id, estimated_cost_usd)`

After actions:
- emit audit events
- emit metering / actual cost attribution

At session start:
- check sanctions / restrictions

These requirements are defined in detail in
[Constitutional Runtime Contract](RUNTIME_CONTRACT.md).

### E. Point example scoring/analysis tools at your artifacts

The OSS repo defaults to repo-local sample artifacts so it can run standalone.
Real deployments should point these tools at real runtime outputs:

```bash
export MERIDIAN_ARTIFACT_DIR=/path/to/artifacts
export MERIDIAN_RUN_STATE_FILE=/path/to/run-state.json
```

These are used by:
- `examples/intelligence/ci_vertical.py`
- `examples/intelligence/brief_quality.py`
- `economy/auto_score.py`

Legacy env vars such as `MERIDIAN_NS_DIR` and `MERIDIAN_CRON_JOBS` are still
accepted for backward compatibility, but new deployments should prefer:

- `MERIDIAN_ARTIFACT_DIR`
- `MERIDIAN_RUN_STATE_FILE`

## 5. JSON API Surface

The reference workspace exposes a local JSON API.

Read endpoints include:
- `/api/status`
- `/api/institution`
- `/api/agents`
- `/api/authority`
- `/api/treasury`
- `/api/court`
- `/api/runtimes`

Public truth surface:
- `/api/agents` shows each governed agent record, including its `runtime_binding`
- `/api/status` shows the same agent truth in the full workspace snapshot
- `/api/runtimes` shows the runtime registry truth used to interpret those bindings

Mutation endpoints include:
- `/api/authority/kill-switch`
- `/api/authority/request`
- `/api/authority/approve`
- `/api/court/file`
- `/api/court/resolve`
- `/api/treasury/contribute`
- `/api/treasury/reserve-floor`
- `/api/institution/charter`
- `/api/institution/lifecycle`

Session endpoints (available when auth is enabled):
- `POST /api/session/issue` — authenticate with Basic, receive a Bearer token
- `POST /api/session/revoke` — revoke a session token (admin+)
- `GET  /api/session/validate` — introspect a Bearer token (no auth required)

For production use, do not expose the workspace unauthenticated. The built-in
workspace can self-protect with HTTP Basic auth when credentials are configured,
and production teams should usually still put a reverse proxy / access layer in
front of it. The reference UI is meant to demonstrate the control surface, not
replace your deployment's full security model.

## 6. State And Persistence

Meridian uses JSON / JSONL files by default.

Important state includes:
- `kernel/organizations.json` — global institution index
- `kernel/agent_registry.json` — global agent index
- `kernel/audit_log.jsonl` — global append-only audit trail (org-tagged)
- `kernel/metering.jsonl` — global usage metering (org-tagged)
- `economy/capsules/<org_id>/ledger.json` — per-institution economy state (REP, AUTH, CASH per agent)
- `economy/capsules/<org_id>/transactions.jsonl` — per-institution transaction log
- `economy/capsules/<org_id>/revenue.json` — per-institution revenue state
- `economy/authority_queue.json` — per-institution approvals, delegations, kill switch
- `economy/court_records.json` — per-institution violations, sanctions, appeals

For serious use:
- back these up
- version policy/config changes
- rotate or archive append-only logs deliberately

Planned database backends are on the roadmap, but the file-based model is the
current contract.

The runtime registry in `kernel/runtimes.json` is also file-based metadata.
Only the built-in local kernel path is implemented today; other runtime entries
remain declared integration targets until adapter code exists.

## 7. What Meridian Does Not Give You

This repo does **not** include:
- your hosted delivery pipeline
- your customer data model
- your payment processor integration
- your reverse proxy/auth setup
- your production operator UI

Those belong to your deployment, not the kernel.

## 8. Recommended First Real Integration

The simplest serious integration path is:

1. run `quickstart.py --init-only`
2. keep the file-based state
3. run `kernel/workspace.py` locally or behind your reverse proxy
4. wrap one runtime with authority + budget checks
5. emit audit + metering after each action
6. point the example tools at your real artifacts with:
   - `MERIDIAN_ARTIFACT_DIR`
   - `MERIDIAN_RUN_STATE_FILE`

That gives you a governed deployment without rebuilding your runtime.
