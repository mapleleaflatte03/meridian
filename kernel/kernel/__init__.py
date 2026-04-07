"""
Meridian Kernel -- Governed multi-agent runtime primitives.

Provides the five constitutional primitives for running a governed
multi-agent organization:

  * organizations  -- Institution / Tenant model
  * agent_registry -- Agent identity, budget, scopes, lifecycle
  * authority      -- Approval queues, delegations, kill switch
  * treasury       -- Financial read facade over economy layer
  * court          -- Violations, sanctions, appeals
  * audit          -- Append-only audit log
  * metering       -- Usage metering and budget checks
  * bootstrap      -- Initialize platform state from economy ledger
  * workspace      -- HTTP dashboard + JSON API
"""
