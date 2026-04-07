# Capsule Specification

Formalization of the Meridian Capsule layer: the institution-scoped state
isolation boundary for the governance kernel.

Status labels used throughout:
- **PROVEN** -- implemented, tested, running in production code
- **DESIGN THESIS** -- formalized design direction, not yet implemented
- **NOT STARTED** -- future work, no code exists

---

## 1. What Capsule Is Today (PROVEN)

### 1.1 Definition

A capsule is an institution-scoped state directory. Every institution
registered with the kernel owns exactly one capsule. The capsule contains
all governance, economic, judicial, and federation state for that institution
as a collection of JSON files on disk.

Implementation: `kernel/capsule.py` (539 LOC).

### 1.2 Files Contained

Defined in `CAPSULE_FILES`, initialized by `init_capsule()`.
26 files per capsule (20 JSON, 2 JSONL, 4 lock files):

**Economy:** `ledger.json` (agents, treasury, bonus pool, epoch),
`revenue.json` (clients, orders, receivables), `owner_ledger.json`
(capital, expenses, reimbursements, draws), `wallets.json` (verification
levels 0-4), `treasury_accounts.json` (sub-accounts, transfer policy),
`funding_sources.json` (source types and records).

**Governance:** `authority_queue.json` (approvals, delegations, kill
switch), `court_records.json` (violations, appeals), `warrants.json`
(action/risk classes, court review states), `commitments.json`
(cross-institution lifecycle), `cases.json` (inter-institution disputes),
`policies.json`, `phase_state.json`.

**OSS:** `maintainers.json` (bdfl/core/maintainer roles),
`contributors.json` (contribution types, registration),
`payout_proposals.json` (proposal state machine and schema).

**Services:** `subscriptions.json` + `subscriptions.json.bak`,
`federation_inbox.json`, `federated_execution_jobs.json`.

**Append-only logs:** `metering.jsonl`, `transactions.jsonl`.

**Lock files:** `.federation_inbox.lock`, `.federated_execution_jobs.lock`,
`.subscriptions.lock`, `.accounting.lock`.

### 1.3 Capsule Isolation Model

One capsule per institution, scoped by `org_id`. `capsule_path()` resolves:
(1) `org_id is None` to `economy/` (legacy default),
(2) aliased `org_id` to the alias directory,
(3) all others to `capsules/<org_id>/`.

`register_capsule_alias()` lets the founding institution resolve to the
legacy `economy/` directory, preventing split-brain during multi-tenant
cutover. Auto-aliasing fires when exactly one org in `organizations.json`
lacks a dedicated capsule directory.

### 1.4 Workspace Binding

`kernel/workspace.py` binds to a capsule through `InstitutionContext`
(`kernel/institution_context.py`). Resolution order: (1)
`MERIDIAN_WORKSPACE_AUTH_ORG_ID` env var, (2) credential file `org_id`,
(3) fallback legacy institution. Once bound, all API endpoints operate
within that capsule. Cross-institution access is rejected by
`InstitutionContext.reject_cross_org()`.

### 1.5 Test Coverage

Six test files exercise the capsule layer:

- `kernel/tests/test_capsule.py` -- core operations: init, path resolution, aliasing, listing
- `kernel/tests/test_authority_capsule.py` -- authority queue scoped to capsule
- `kernel/tests/test_court_capsule.py` -- court records scoped to capsule
- `kernel/tests/test_treasury_capsule.py` -- treasury/ledger operations scoped to capsule
- `kernel/tests/test_workspace_context.py` -- workspace binding to institution-scoped capsule
- `economy/tests/test_capsule_scoping.py` -- cross-cutting capsule scoping validation

### 1.6 Current Guarantees

- No cross-institution state bleed within a single process
- Deterministic path resolution for any `(org_id, filename)` pair
- Initialization is atomic at the capsule level (`init_capsule()` fails
  if ledger already exists)
- Lock files exist for concurrent-write-sensitive subsystems
  (subscriptions, accounting, federation inbox, execution jobs)

---

## 2. What Capsule Does Not Do Today

Explicit boundaries of the current design (not bugs):

- **Not portable.** No bundle format; a capsule is a host-local directory.
- **No integrity verification.** No hash manifest, no signature, no Merkle root.
- **Not transmittable.** Federation sends HMAC-signed envelopes, not capsule state.
- **No versioning** beyond file timestamps. No sequence number or snapshot ID.
- **No provenance chain.** Cannot prove creator, modifier, kernel version, or origin host from capsule contents alone.
- **No growth management.** Append-only files (`metering.jsonl`, `transactions.jsonl`) grow without bound.

---

## 3. Design Thesis: Portable Governed Capsule (DESIGN THESIS)

A portable capsule is a signed, transmittable bundle containing all
governance state for one institution at a specific point in time.

### 3.1 Bundle Contents

| Component | Description |
|-----------|-------------|
| State snapshot | All 26 capsule files as they existed at snapshot time |
| Integrity manifest | SHA-256 hash of each file; Merkle root of all hashes |
| Provenance record | Creating institution `org_id`, host identity, timestamp, kernel version |
| Governance constraints | Active sanctions, authority state, budget limits at snapshot time |
| Commitment references | Linked commitments with their current lifecycle state |
| Warrant references | Active warrants at snapshot time |

### 3.2 Receiver Capabilities

A receiver of a portable capsule should be able to:

1. **Verify integrity** -- recompute hashes, rebuild Merkle tree, confirm root matches.
2. **Verify provenance** -- validate signature against known peer key.
3. **Inspect governance constraints** -- examine sanctions, authority, budget before accepting.
4. **Reject untrusted peers** -- peers in `suspended`/`revoked` trust state are rejected.
5. **Mount** -- unpack into a local institution-scoped capsule directory.

### 3.3 Bundle Format

A `.capsule` file is a tar archive containing:

```
manifest.json          -- integrity hashes, provenance, governance snapshot
manifest.json.sig      -- detached HMAC-SHA256 signature of manifest.json
state/                 -- directory of all capsule JSON/JSONL files
```

The manifest is the root of trust. The state directory is the payload.
The signature binds the manifest to a known host identity.

---

## 4. Composition with Existing Primitives

No new cryptographic or networking primitives. Capsule design extends
existing proven patterns:

- **Federation HMAC signatures.** `kernel/federation.py` signs envelopes
  with HMAC-SHA256 per peer. Capsule signing applies the same algorithm
  to a manifest instead of an envelope.
- **Witness archive hashing.** `kernel/witness_archive.py` archives
  receipts with SHA-256 content hashes. Capsule manifests use the same
  approach over capsule files.
- **Commitment lifecycle.** `commitments.json` tracks cross-institution
  states. Portable capsules formalize the state commitments reference.
- **Court cases.** `cases.json` tracks disputes (`non_delivery`,
  `fraudulent_proof`, `breach_of_commitment`). Capsule provenance
  provides the evidence chain court proceedings require.
- **Peer trust states.** `TRUST_STATES = ('trusted', 'suspended',
  'revoked')` already gates envelope acceptance; the same model gates
  capsule acceptance.

---

## 5. Integrity Verification Design (DESIGN THESIS)

### 5.1 CLI Commands

| Command | Purpose | Status |
|---------|---------|--------|
| `meridian capsule integrity --org-id <id>` | Hash all files, compare against stored manifest | DESIGN THESIS |
| `meridian capsule sign --org-id <id>` | Sign current capsule state, produce manifest + signature | DESIGN THESIS |
| `meridian capsule verify --file <path>` | Verify a received `.capsule` bundle | DESIGN THESIS |

### 5.2 Hash Algorithm

SHA-256, consistent with `kernel/federation.py` payload hashing
(`_payload_hash()`) and `kernel/witness_archive.py` content hashing.

### 5.3 Signature

HMAC-SHA256 using the institution's host key, consistent with the
federation envelope signing scheme. No new key material required.

### 5.4 Merkle Tree Construction

- Leaves: SHA-256 hash of each capsule file's contents.
- Leaf ordering: sorted by filename (lexicographic, ascending) for
  deterministic root computation.
- Internal nodes: SHA-256 of concatenated child hashes.
- Root: stored in `manifest.json` as `merkle_root`.

Lock files (`.federation_inbox.lock`, `.federated_execution_jobs.lock`,
`.subscriptions.lock`, `.accounting.lock`) are excluded from the Merkle
tree. They are synchronization artifacts, not state.

---

## 6. Phased Implementation

| Phase | Scope | Status | Dependency |
|-------|-------|--------|------------|
| 0 | Institution-scoped directory isolation | **PROVEN** -- `kernel/capsule.py` | None |
| 1 | Integrity manifest: hash each file, write `manifest.json` into capsule | **NOT STARTED** | None (next reasonable step) |
| 2 | Capsule signing: HMAC-SHA256 manifest signature using host key | **NOT STARTED** | Phase 1 |
| 3 | Portable capsule format: `.capsule` tar bundle with manifest + signature + state | **NOT STARTED** | Phase 2 |
| 4 | Capsule transmission via federation gateway | **NOT STARTED** | Phase 3 + network federation peers |
| 5 | Cross-host capsule verification and mounting | **NOT STARTED** | Phase 4 |

Phase 0 is the only phase with production code and test coverage.
Phases 1-5 are design targets with no committed timeline.

---

## 7. What This Document Is Not

- Not a claim that portable capsules exist today (only Phase 0 is implemented).
- Not an implementation plan with timelines.
- Not a wire-format specification (that belongs in Phase 3).
- Not a replacement for federation (capsule transmission uses the gateway).

This document formalizes the capsule concept from "background code that
happens to scope state" to "named architectural lane with a defined
evolution path."

---

## References

- `kernel/capsule.py` (539 LOC) -- capsule implementation
- `kernel/federation.py` (1,045 LOC) -- federation gateway
- `kernel/witness_archive.py` -- witness archival store
- `kernel/institution_context.py` -- institution binding
- `kernel/workspace.py` -- workspace surface
- `kernel/tests/test_capsule.py`, `test_authority_capsule.py`,
  `test_court_capsule.py`, `test_treasury_capsule.py`,
  `test_workspace_context.py` -- kernel capsule tests
- `economy/tests/test_capsule_scoping.py` -- cross-cutting scoping tests
