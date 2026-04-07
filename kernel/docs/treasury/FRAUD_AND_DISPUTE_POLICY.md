# Fraud and Dispute Policy

Anti-fraud requirements, fraud patterns, court integration, and dispute process for the Meridian treasury protocol.

---

## 1. Anti-Fraud Requirements

Every payout must satisfy all seven requirements:

1. **Contribution proof** -- verifiable evidence linking the contributor to accepted work (PR URLs, commit hashes, issue references)
2. **Wallet classification** -- recipient wallet must be Level 3+ (self-custody verified or multisig controlled)
3. **Reviewer identity** -- a named reviewer who is NOT the contributor must evaluate the proposal
4. **Approval record** -- explicit approval by owner or agent with delegated `treasury:approve` authority
5. **Dispute path** -- 72-hour window between approval and execution for objections
6. **Audit trail** -- all proposal state changes logged to `kernel/audit_log.jsonl`
7. **Court integration** -- fraud violations filed via the Court primitive with sanctions applied

Failure to meet any requirement blocks the payout.

---

## 2. Fraud Patterns

The protocol defends against these specific patterns:

### 2a. Fake Contribution Claims
**Pattern:** Claiming credit for work not done, PRs not merged, or contributions that don't exist.
**Defense:** Evidence requirement -- PR URLs must resolve, commits must exist in the repo, issues must be referenced.

### 2b. Self-Dealing
**Pattern:** Proposing, reviewing, and approving your own payout.
**Defense:** Self-review prohibition. Reviewer must be a different person than the contributor. Approval requires owner or delegated authority.

### 2c. Wallet Substitution
**Pattern:** Registering someone else's wallet to intercept their payout.
**Defense:** SIWE verification (Level 3) proves key control. Only the person who controls the private key can register the wallet.

### 2d. Duplicate Claims
**Pattern:** Claiming the same contribution across multiple proposals.
**Defense:** Evidence cross-reference during review. Reviewers must check for prior proposals referencing the same PRs/commits.

### 2e. Inflated Valuation
**Pattern:** Claiming a trivial fix deserves a large payout.
**Defense:** Reviewer assessment of contribution scope. Owner final approval on amount.

### 2f. Ghost Contributors
**Pattern:** Creating fake GitHub accounts to claim bounties.
**Defense:** GitHub account age and activity checks during review. Contributor must have verifiable history.

---

## 3. Court Integration

Fraud violations map to existing Court primitive violation types defined in `kernel/court.py`:

| Fraud Pattern | Violation Type | Severity |
|---------------|---------------|----------|
| Fake contribution claim | `false_confidence` | 4-5 |
| Self-dealing | `critical_failure` | 5 |
| Wallet substitution | `critical_failure` | 5 |
| Duplicate claim | `false_confidence` | 3 |
| Inflated valuation | `weak_output` | 2-3 |
| Ghost contributor | `false_confidence` | 4 |

Sanctions follow the existing Court severity scale:
- Severity 1-2: Warning, no payout for this proposal
- Severity 3: Authority freeze, payout eligibility suspended
- Severity 4: Reputation penalty, extended payout suspension
- Severity 5: Full suspension, all active proposals cancelled, remediation required

---

## 4. Dispute Process

Disputes use the existing Court primitive functions:

### 4a. Filing a Dispute

Any maintainer or contributor may file a dispute during the 72-hour dispute window:

```python
from court import file_violation

file_violation(
    agent_id=contributor_id,
    org_id=org_id,
    violation_type='false_confidence',  # or appropriate type
    severity=3,
    evidence='Payout proposal XYZ references PR #123 which was not authored by the claimant',
    policy_ref='docs/treasury/FRAUD_AND_DISPUTE_POLICY.md'
)
```

### 4b. Appeal

If a contributor's proposal is rejected or sanctioned, they may appeal:

```python
from court import file_appeal

file_appeal(
    violation_id=violation_id,
    agent_id=contributor_id,
    grounds='PR #123 was a collaborative effort; contributor authored the key changes in commits abc123 and def456'
)
```

### 4c. Resolution

Appeals are decided by the owner or delegated authority:

```python
from court import decide_appeal

decide_appeal(
    appeal_id=appeal_id,
    decision='upheld',  # or 'denied'
    by='owner'
)
```

### 4d. Remediation

After sanctions expire or issues are resolved, restrictions can be lifted:

```python
from court import remediate

remediate(
    agent_id=contributor_id,
    by='owner',
    note='Dispute resolved, contribution verified'
)
```

---

## 5. Audit Requirements

All treasury protocol actions must be logged:

- Proposal creation, submission, review, approval, rejection, cancellation
- Wallet registration and verification level changes
- Funding source classification
- Account transfers
- Payout execution
- Dispute filing and resolution

The audit trail is the authoritative record. If a dispute arises about what happened, the audit log is the source of truth.
