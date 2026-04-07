# Treasury Policy

Rules governing treasury accounts, inflows, reserve floors, and reconciliation.

---

## 1. Treasury Account Separation

The treasury is divided into three accounts:

| Account | Purpose | Funding Source |
|---------|---------|---------------|
| **Company Treasury** | Main pool for all inflows | Direct -- all money enters here first |
| **Maintainer Support** | Allocated for maintainer payouts | Transfer from Company Treasury (owner approval) |
| **Contributor Payout Pool** | Allocated for contributor bounties | Transfer from Company Treasury (owner approval) |

Money always enters the Company Treasury first. Sub-accounts are funded by explicit transfer.

---

## 2. Inflow Classification

Every inflow must be classified by source type:

| Source Type | Description | Verification |
|-------------|-------------|-------------|
| `owner_capital` | Direct founder contribution | Owner attestation + on-chain tx |
| `github_sponsors` | GitHub Sponsors payment | GitHub payment confirmation |
| `direct_crypto` | Stablecoin transfer from identified sponsor | On-chain tx + sender identification |
| `customer_payment` | Payment for product/service | Invoice + payment confirmation |
| `grant` | Foundation or organizational grant | Grant agreement + payment confirmation |
| `reimbursement` | Reimbursement of out-of-pocket expenses | Expense record + receipt |

Unclassified inflows are held in Company Treasury with status `unverified` until classified.

---

## 3. Reserve Floor Rules

The Company Treasury maintains a reserve floor. No payouts or transfers may reduce the balance below this floor.

**Current reserve floor:** $50.00

Rules:
- Reserve floor can only be changed by the owner via `set-reserve-floor` command
- Every change is logged with a note explaining the reason
- Sub-accounts may have their own reserve floors (default $0)
- The `can_payout()` function enforces: `balance >= reserve_floor + payout_amount`

---

## 4. Account Transfer Rules

Transfers between treasury accounts require:

1. **Owner approval** -- no automated transfers
2. **Reserve maintenance** -- source account must remain above its reserve floor after transfer
3. **Audit record** -- transfer logged with amount, source, destination, reason, and approver
4. **No circular transfers** -- transfers must have a stated purpose

---

## 5. Reconciliation

The authoritative treasury balance is the institution's capsule `ledger.json` field `treasury.cash_usd` (resolved via `capsule_path(org_id, 'ledger.json')`).

Reconciliation rules:
- `treasury_accounts.json` balances are policy/allocation records, not authoritative
- If `treasury_accounts.json` total differs from `ledger.json`, the ledger is correct
- Reconciliation should be checked on every `treasury_snapshot()` call
- Discrepancies must be investigated and resolved, not silently corrected

---

## 6. Spending Authority

- Only the owner can approve payouts and transfers
- Delegated authority (via the Authority primitive) may be granted for bounded amounts
- All delegations expire and are revocable
- Kill switch engagement freezes all treasury operations except balance reads
