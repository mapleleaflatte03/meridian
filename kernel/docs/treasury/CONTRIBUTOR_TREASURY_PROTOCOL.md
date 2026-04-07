# Contributor Treasury Protocol v1

A credible, auditable contributor treasury protocol for the Meridian Constitutional Kernel.

This is not a token launch or DeFi protocol. It is a governance and payout layer for an open-source project, built on the same five primitives that govern the kernel itself.

---

## Purpose

Meridian is open-source (Apache-2.0). Contributors who improve the kernel deserve a credible path to compensation. This protocol defines:

1. How funds enter the treasury
2. How wallets are verified
3. How contributions are tracked
4. How payouts are proposed, reviewed, and executed
5. How fraud is detected and disputed

## Current Status

| Item | Status |
|------|--------|
| Treasury balance | $0.00 |
| Owner capital received | $2.00 USDC (recorded, not yet in ledger) |
| External revenue | $0.00 |
| Contributors paid | 0 |
| Payout proposals | 0 |
| GitHub Sponsors | Not yet configured |
| Safe multisig | Planned, not deployed |
| SIWE verification | Planned, not implemented |

This protocol is live infrastructure with zero throughput. It defines the rules for when money arrives.

---

## Five-Primitive Mapping

The treasury protocol maps onto the kernel's five primitives:

| Primitive | Role in Treasury Protocol |
|-----------|--------------------------|
| **Institution** | Project context -- charter defines the project's purpose and treasury governance authority |
| **Agent** | Future automation -- agents that process payout proposals or verify contributions |
| **Authority** | Payout approval -- who can propose, review, and approve payouts. Maps to approval queue and delegation system |
| **Treasury** | Inflow/outflow -- balance tracking, reserve enforcement, budget gates, account separation |
| **Court** | Fraud/disputes -- false contribution claims, self-dealing, dispute resolution |

---

## Fund Flow

```
Inflow Sources                    Treasury Accounts              Outflows

GitHub Sponsors ──┐               ┌──────────────────┐
Owner Capital ────┼──────────────>│ Company Treasury  │
Direct Crypto ────┤               │ (main pool)       │
Customer Payment ─┤               │ reserve: $50 min  │
Grant ────────────┤               └────────┬─────────┘
Reimbursement ────┘                        │
                              owner approval required
                                           │
                          ┌────────────────┼────────────────┐
                          v                v                v
                   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
                   │ Maintainer  │  │ Contributor  │  │   Other     │
                   │ Support     │  │ Payout Pool  │  │  (future)   │
                   └──────┬──────┘  └──────┬──────┘  └─────────────┘
                          │                │
                   payout proposal    payout proposal
                   + dispute window   + dispute window
                          │                │
                          v                v
                   Level 3+ wallet    Level 3+ wallet
```

All inflows enter the company treasury first. Sub-account funding requires owner approval. Payouts require a proposal, review, approval, and a 72-hour dispute window.

---

## Funding Hierarchy

1. **GitHub Sponsors** (PRIMARY) -- transparent, recurring, community-visible
2. **Direct crypto** (SECONDARY) -- stablecoin transfers for sponsors who prefer on-chain
3. **Customer payments** -- revenue from products/services built on Meridian
4. **Grants** -- foundation or organizational grants
5. **Owner capital** -- founder deposits to bootstrap operations

GitHub Sponsors is primary because it provides transparency, recurring support, and community trust signals. Crypto is supplementary.

---

## Registry Files

All protocol state is stored in machine-readable JSON files under `treasury/`:

| File | Contents |
|------|----------|
| [`wallets.json`](../../treasury/wallets.json) | Wallet registry with 5 verification levels |
| [`treasury_accounts.json`](../../treasury/treasury_accounts.json) | Treasury sub-accounts (company, maintainer, contributor) |
| [`maintainers.json`](../../treasury/maintainers.json) | Maintainer registry with roles |
| [`contributors.json`](../../treasury/contributors.json) | Contributor registry (currently empty) |
| [`payout_proposals.json`](../../treasury/payout_proposals.json) | Payout proposal state machine |
| [`funding_sources.json`](../../treasury/funding_sources.json) | Classified inflow records |

---

## Related Policy Documents

- [Treasury Policy](TREASURY_POLICY.md) -- reserve rules, account separation, reconciliation
- [Payout Policy](PAYOUT_POLICY.md) -- proposal lifecycle, evidence requirements, authority
- [Wallet Verification](WALLET_VERIFICATION.md) -- verification levels, SIWE, multisig
- [Fraud and Dispute Policy](FRAUD_AND_DISPUTE_POLICY.md) -- anti-fraud rules, court integration

---

## Anti-Fraud Summary

Seven requirements for any payout:

1. **Contribution proof** -- PR links, commit hashes, or issue references
2. **Wallet classification** -- recipient must have Level 3+ (self-custody verified) wallet
3. **Reviewer identity** -- a named reviewer who is not the contributor
4. **Approval record** -- owner or delegated authority approval
5. **Dispute path** -- 72-hour window between approval and execution
6. **Audit trail** -- all state changes logged to audit_log.jsonl
7. **Court integration** -- fraud maps to existing violation types (false_confidence, critical_failure)

See [Fraud and Dispute Policy](FRAUD_AND_DISPUTE_POLICY.md) for details.
