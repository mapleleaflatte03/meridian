# Payout Policy

Rules governing the payout proposal lifecycle, evidence requirements, and authority.

---

## 1. Payout Proposal Lifecycle

Every payout follows a six-state lifecycle:

```
draft -> submitted -> under_review -> approved -> dispute_window -> executed
                  \              \
                   -> cancelled    -> rejected
```

| State | Description | Who Acts |
|-------|-------------|----------|
| `draft` | Proposal created, not yet submitted | Proposer |
| `submitted` | Proposal submitted for review | System |
| `under_review` | Reviewer is evaluating evidence | Reviewer |
| `approved` | Reviewer and approver accept the proposal | Owner / delegated authority |
| `dispute_window` | 72-hour window for objections before execution | Anyone |
| `executed` | Payout sent to recipient wallet | System / owner |
| `rejected` | Proposal rejected at any review stage | Reviewer / owner |
| `cancelled` | Proposal withdrawn by proposer | Proposer |

Reference workspace surfaces:
- `GET /api/payouts`
- `GET /api/treasury/settlement-adapters`
- `POST /api/treasury/settlement-adapters/preflight`
- `POST /api/payouts/propose|submit|review|approve|open-dispute-window|reject|cancel|execute`

---

## 2. Evidence Requirements

Every proposal must include evidence appropriate to its contribution type:

| Contribution Type | Required Evidence |
|-------------------|-------------------|
| `code` | PR URL(s), commit hash(es), merged status |
| `documentation` | PR URL(s), specific files changed |
| `security_report` | Issue reference, severity assessment, fix verification |
| `bug_report` | Issue reference, reproduction steps, fix PR (if applicable) |
| `design` | Design artifacts, implementation PR (if applicable) |
| `vertical_example` | PR URL, working example verification |
| `test_coverage` | PR URL, coverage diff |
| `review` | Review comments, PR references |
| `community` | Specific activities with links |

Proposals without sufficient evidence are rejected at `under_review`.

---

## 3. Authority Requirements

| Action | Required Authority |
|--------|-------------------|
| Create proposal | Any registered contributor or maintainer |
| Review proposal | Any maintainer who is NOT the contributor |
| Approve proposal | Owner, or agent with delegated `treasury:approve` scope |
| Execute payout | Owner only (no delegation for execution in v1) |
| Cancel proposal | Original proposer, or owner |
| Reject proposal | Reviewer or owner |

Execution also requires an executable warrant with:
- `action_class = payout_execution`
- `boundary_name = payouts`

Execution additionally validates the chosen settlement adapter against the
institution-local `settlement_adapters.json` policy. The current reference
path only enables `internal_ledger` for payout execution. Other registered
adapters may appear in the policy surface, but they remain non-executable until
their proof contract is enabled. Non-ledger adapters must also declare a ready
verification path and present an accepted verifier attestation before
execution or received settlement notices can pass preflight.

Receiver-side federation execution closes the loop by reusing an already
persisted linked payout execution or settlement reference. The
`POST /api/federation/execution-jobs/execute` route does not accept caller
supplied `execution_refs`; it only emits a `settlement_notice` from the
actual stored proof path. When a host receives that `settlement_notice`, it
replays the same settlement-adapter preflight contract before recording any
local settlement ref; invalid notices open `invalid_settlement_notice` cases
and can automatically suspend the peer on the reference path.

Self-review is not allowed. The reviewer must be a different person than the contributor.

---

## 4. Dispute Window

After approval, every proposal enters a 72-hour dispute window before execution.

During this window:
- Any maintainer or contributor may raise an objection
- Objections must include specific grounds (evidence insufficiency, duplicate claim, etc.)
- An objection pauses execution and returns the proposal to `under_review`
- Owner may override and execute during dispute window if the objection is frivolous

---

## 5. Wallet Requirements

The recipient wallet must:
- Be registered in `treasury/wallets.json`
- Have verification Level 3 (`self_custody_verified`) or Level 4 (`multisig_controlled`)
- Be in `active` status

Payouts to Level 0, 1, or 2 wallets are blocked. This protects against sending funds to exchange addresses or unverified wallets.

---

## 6. Settlement Adapter Contract

The payout surface now carries a machine-readable settlement adapter registry.
Each adapter declares:

- whether payout execution is enabled
- the adapter's execution mode (`host_ledger`, `external_chain`, `manual_offchain`, or `external_reference`)
- the settlement path the execution follows
- which currencies are supported
- whether `tx_hash` is required
- whether structured `settlement_proof` is required
- the normalized `proof_type`
- the expected verification state
- the expected finality state
- the reversal or dispute capability
- the dispute model
- the finality model
- whether the current host can execute the adapter now
- the execution blockers when it cannot

On the current reference path:

| Adapter | Status | Payout Execution |
|---------|--------|------------------|
| `internal_ledger` | registered | enabled |
| `base_usdc_x402` | registered | disabled |
| `manual_bank_wire` | active | enabled |

`internal_ledger` normalizes proof as an institution transaction journal
reference and marks execution as `host_ledger_final`. `base_usdc_x402` remains
registered-only policy-disabled because it still depends on external chain
truth. `manual_bank_wire` is now executable on the internal/manual path when
its verifier attestation is present and the host advertises support, but the
wire itself remains manual/offchain.

On the reference host, `internal_ledger` is treated as the implicit local
settlement path even when host metadata does not explicitly enumerate a
settlement adapter list. That is a host-local ledger assumption, not a claim
that external adapters are executable.

Execution and preflight now surface a contract snapshot with:

- `execution_mode`
- `settlement_path`
- `requirements`
- `execution_blockers`
- `execution_blocker_messages`
- `finality_model`
- `dispute_model`
- `settlement_adapter_contract` on execution records and transaction rows

That makes the payout path honest about whether an adapter is merely known,
contractually described, or actually executable on this host.

---

## 7. Current Status

- Treasury balance: $0.00
- Payouts executed: 0
- Proposals created: 0
- Payout-eligible wallets: 0

This policy is live infrastructure awaiting its first use. No payouts can occur until:
1. Treasury has funds above reserve floor
2. At least one Level 3+ wallet is registered
3. A valid contribution exists with evidence
