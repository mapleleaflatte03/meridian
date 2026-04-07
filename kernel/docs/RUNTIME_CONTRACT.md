# Meridian Constitutional Runtime Contract

A runtime is constitutionally governable by Meridian when it satisfies
seven requirements. This document defines those requirements, how to
implement each one, and how to verify compliance.

---

## What This Is

Meridian does not run agents. It governs them.

Any runtime — local subprocess, hosted API, MCP server, A2A agent, LangGraph
pipeline, or custom stack — can in principle have its agents governed by
Meridian's five primitives if it satisfies this contract and a real adapter
implements the required hooks.

This is the same pattern as Unix permissions: they work regardless of which
shell or application you use. The governance layer is separate from the
execution layer.

---

## The Seven Requirements

### 1. Agent Identity

**Requirement:** The runtime must provide a stable, unique agent ID that maps
to a Meridian agent record. Identity must persist across sessions.

**What Meridian does with it:** Maps runtime agent ID to `kernel/agent_registry.json`.
All governance checks are keyed on agent identity.

**Implementation options:**
- String ID shared at registration time (simplest, used by local_kernel)
- MCP client ID (available in any MCP-compliant runtime)
- A2A agent card ID (available in A2A-capable runtimes)
- JWT sub claim (for runtimes using standard auth)
- Enterprise: Microsoft Entra Agent ID

**Verification:** `python3 kernel/runtime_adapter.py check-contract --runtime_id <id>` — checks `contract_compliance.agent_identity`.

---

### 2. Action Envelope

**Requirement:** The runtime must wrap each governed action with a structured
envelope before calling Meridian checks. Minimum fields:

```python
envelope = {
    'agent_id': 'atlas',           # maps to Meridian agent record
    'action_type': 'research',     # the action being requested
    'resource': 'web_search',      # the resource being used
    'estimated_cost_usd': 0.05,    # pre-action cost estimate
}
```

**What Meridian does with it:** Input to `check_authority(agent_id, action_type)`
and `check_budget(agent_id, estimated_cost_usd)`.

**Implementation:** Wrap every tool call, API call, or subtask delegation in
this envelope before calling Meridian checks. Most runtimes can do this in a
middleware layer or a wrapper function.

---

### 3. Cost Attribution

**Requirement:** After each action completes, the runtime must report actual
cost so Meridian can update metering records.

**What Meridian does with it:** Records to `kernel/metering.jsonl` via
`metering.record()`. Input to treasury runway and spend reporting.

**Implementation:**

```python
from kernel.metering import record as meter_record

meter_record(
    org_id='my_org',
    agent_id='atlas',
    resource='web_search',
    quantity=1,
    unit='calls',
    cost_usd=actual_cost,
    details={'action': 'research', 'query': '...'}
)
```

**MCP path:** Post-tool-call hook. Record actual token count × model price.

**A2A path:** Post-task completion hook. Record agent execution cost.

---

### 4. Approval Hook

**Requirement:** For privileged actions, the runtime must call `check_authority()`
before execution and must block if the result is False.

**What Meridian does with it:** Checks agent risk state, kill switch status,
scope permissions, and active sanctions.

**Implementation:**

```python
from kernel.authority import check_authority

allowed, reason = check_authority(agent_id, action_type)
if not allowed:
    raise RuntimeError(f'Meridian authority check failed: {reason}')
```

**Which actions are privileged?** Any action that:
- Involves external services or APIs
- Spends budget
- Modifies persistent state
- Delegates to other agents

Low-risk read-only actions may skip this check by convention.

---

### 5. Audit Emission

**Requirement:** The runtime must emit structured audit events that Meridian
can ingest. Minimum fields: `timestamp`, `agent_id`, `action`, `outcome`.

**What Meridian does with it:** Appends to `kernel/audit_log.jsonl`.
Auditable trail for court proceedings, postmortems, and owner review.

**Implementation:**

```python
from kernel.audit import log_event

log_event(
    org_id='my_org',
    agent_id='atlas',
    action='research',
    resource='web_search',
    outcome='success',
    details={'query': '...', 'result_count': 5}
)
```

**Alternative:** If the runtime emits its own structured logs, a Meridian
adapter can translate them to `log_event()` calls asynchronously.

---

### 6. Sanction Controls

**Requirement:** Before each agent session begins, the runtime must query
`get_restrictions(agent_id)` and must disable or restrict agents that have
active sanctions.

**What Meridian does with it:** Returns list of active restrictions
(e.g., `['lead', 'assign', 'execute']`).

**Implementation:**

```python
from kernel.court import get_restrictions

restrictions = get_restrictions(agent_id)
if 'execute' in restrictions:
    raise RuntimeError(f'Agent {agent_id} is restricted from execute')
if 'lead' in restrictions:
    # Downgrade the session so the agent cannot take lead-only actions
    ...
```

**Minimum implementation:** Check for `execute` in the returned restriction set
and halt privileged work if present. Full implementation maps each returned
restriction to a runtime capability constraint.

---

### 7. Budget Gate

**Requirement:** Before any cost-bearing operation, the runtime must call
`check_budget()` and must block if the result is False.

**What Meridian does with it:** Checks agent budget limits and treasury
runway. Returns `(allowed, reason)`.

**Implementation:**

```python
from kernel.treasury import check_budget

allowed, reason = check_budget(agent_id, estimated_cost_usd)
if not allowed:
    raise RuntimeError(f'Meridian budget gate blocked: {reason}')
```

---

## Compliance Levels

| Score | Status | Meaning |
|-------|--------|---------|
| 7/7 native | **Compliant** | Runtime natively exposes all constitutional hooks. |
| 7/7 with tested kernel adapter | **Reference adapter** | A kernel-side adapter library covers the full contract, but a live deployment still needs to route runtime events through it. |
| 4-6/7 | **Partial** | Runtime can be partially governed. Adapter work needed for full coverage. |
| 1-3/7 | **Non-compliant** | Not governable without significant adapter work. |
| 0/7 (unknown) | **Unknown** | Contract compliance not yet assessed. Runtime API review required. |

Check compliance: `python3 kernel/runtime_adapter.py check-all`
Check adapter proof: `python3 kernel/runtime_adapter.py check-proof --runtime_id <id>`

Important: `check-all` and `check-contract` are registry-backed assessments.
They report what the runtime entry declares in `kernel/runtimes.json` plus any
tested kernel-side reference adapter hooks. They do not actively probe or
certify a live deployment unless that runtime is actually wired through the
adapter.

---

## Integration Example

A minimal integration showing how a third-party runtime wraps its agent
execution with Meridian governance:

```python
# my_runtime/meridian_adapter.py

import sys
sys.path.insert(0, '/path/to/meridian-kernel/kernel')

from authority import check_authority
from treasury import check_budget
from court import get_restrictions
from metering import record as meter_record
from audit import log_event

class MeridianAdapter:
    """Wraps a third-party runtime agent with Meridian constitutional governance."""

    def __init__(self, org_id, agent_id):
        self.org_id = org_id
        self.agent_id = agent_id

    def pre_session_check(self):
        """Call before each agent session starts."""
        from court import get_restrictions
        restrictions = get_restrictions(self.agent_id)
        if 'execute' in restrictions:
            raise RuntimeError(f'Agent {self.agent_id} is restricted from execute')
        return restrictions

    def pre_action_check(self, action_type, resource, estimated_cost_usd):
        """Call before each privileged action. Returns (allowed, reason)."""
        allowed, reason = check_authority(self.agent_id, action_type)
        if not allowed:
            return False, f'Authority check failed: {reason}'
        if estimated_cost_usd > 0:
            allowed, reason = check_budget(self.agent_id, estimated_cost_usd)
            if not allowed:
                return False, f'Budget gate blocked: {reason}'
        return True, 'ok'

    def post_action_record(self, action_type, resource, actual_cost_usd, outcome, details=None):
        """Call after each action completes to record cost and audit event."""
        meter_record(
            self.org_id, self.agent_id, resource,
            quantity=1, unit='calls', cost_usd=actual_cost_usd,
            details=details or {}
        )
        log_event(
            self.org_id, self.agent_id, action_type,
            resource=resource, outcome=outcome, details=details or {},
            session_id=self.session_id if hasattr(self, 'session_id') else None
        )


# Usage in your runtime:
adapter = MeridianAdapter(org_id='my_org', agent_id='atlas')

# Before session:
restrictions = adapter.pre_session_check()

# Before action:
allowed, reason = adapter.pre_action_check('research', 'web_search', 0.05)
if not allowed:
    raise RuntimeError(reason)

# Run action...
result = my_runtime.run_action('research', 'web_search')

# After action:
adapter.post_action_record('research', 'web_search',
                           actual_cost_usd=0.04,
                           outcome='success',
                           details={'query': '...', 'hits': 5})
```

This adapter pattern works for any runtime that can call Python functions.
For runtimes that cannot import Python directly (e.g., separate processes,
containerized runtimes, remote agents), you need a thin bridge or control
plane that exposes equivalent governance checks. The current demo workspace
JSON API is a reference surface; it does not yet expose dedicated remote
endpoints for every governance hook shown above.

---

## What Meridian Does Not Require

- Meridian does not require you to use a specific LLM provider
- Meridian does not require you to use a specific agent runner
- Meridian does not require you to change how agents are prompted
- Meridian does not require a database or external service
- Meridian does not require modifying the runtime's core execution logic

The contract is a set of hooks at the boundary between execution and governance.
The runtime keeps its architecture. Meridian governs the boundary.

---

## Runtime Registry

Current registered runtimes and their contract status:
`kernel/runtimes.json` — inspect with `python3 kernel/runtime_adapter.py check-all`

To register a new runtime:
```bash
python3 kernel/runtime_adapter.py register \
  --id my_runtime \
  --label "My Runtime" \
  --type hosted \
  --protocols "MCP,custom" \
  --identity_mode api_key
```
