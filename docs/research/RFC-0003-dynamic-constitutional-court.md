# RFC-0003: Dynamic Constitutional Court

Status: Draft (implementable)  
Owners: Kernel + Workspace maintainers  
Scope: court proposal lifecycle and `court.dynamic` status contract

## Problem

Static rule sets are not sufficient for long-running governed runtimes. Operators need auditable proposal/vote/tally/activate flow with explicit rule versions.

## Proposal

Promote Court to a dynamic constitutional surface.

Data model:

- `court_rules.json` (versioned active rules)
- `court_rule_proposals.json` (proposal lifecycle)
- `court_votes.json` (voter decisions with idempotent merge)

Pseudocode:

```text
propose_rule(patch, proposer) -> draft
cast_vote(proposal_id, voter, weight, decision) -> append/replace voter vote
tally(proposal_id) -> quorum + threshold
activate(proposal_id) -> ruleset_version + 1 + audit event
```

## API/Contract Impact

- `GET /api/court/rules`
- `POST /api/court/proposals`
- `POST /api/court/vote`
- `POST /api/court/proposals/activate`
- `/api/status` -> `court.dynamic.{ruleset_version,proposal_count,active_rules}`

## Acceptance Criteria

1. Activation blocked until quorum+threshold are met.
2. Vote idempotent on `(proposal_id, voter_id)`.
3. Every activated rule links to audit metadata (`rule_id`, `rule_version`, actor, timestamp).

## Rollback

Freeze activation endpoint and keep current active ruleset stable; retain read-only proposal history.

## References

- `kernel/kernel/court.py`
- `intelligence/company/meridian_platform/workspace.py`
