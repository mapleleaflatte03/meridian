# Meridian Proof Matrix

This file maps public claims to executable proof artifacts or live surfaces.

## Claim Maturity Levels

- **PROVEN** — claim backed by executable test or live surface with passing verification
- **DECLARED** — claim registered in code (e.g., runtimes.json) but no test exercises it
- **PLANNED** — claim appears in spec/roadmap only, no code artifact exists
- **FRONTIER** — claim is an acknowledged future goal, explicitly not claimed as current

## Reference Proofs

| Claim | Proof Artifact | Maturity | Notes |
| --- | --- | --- | --- |
| Runtime-core and agent-runtime truth exists | `GET /api/context`, `GET /api/status`, `GET /api/agents`, `GET /api/runtimes`, `GET /api/admission`, `GET /api/federation` | PROVEN | Process-bound reference workspace, with agent `runtime_binding` surfaced and kept coherent with registry truth; `/api/status` also surfaces `routing_planner` and `handoff_preview_queue` |
| Routing planner and handoff preview queue exist | [`kernel/tests/test_workspace_context.py`](../kernel/tests/test_workspace_context.py) and [`kernel/tests/test_federation_handoff_queue.py`](../kernel/tests/test_federation_handoff_queue.py) | PROVEN | Classifies local/remote/blocked requests and persists dispatch-ready remote handoff previews without claiming remote execution |
| Signed host-service federation exists | [`kernel/tests/test_federation.py`](../kernel/tests/test_federation.py) | PROVEN | Covers peer registry, replay protection, wrong-target rejection, settlement notice, case/court notice, witness archive |
| 3-host federation story exists | [`kernel/tests/test_three_host_federation_proof.py`](../kernel/tests/test_three_host_federation_proof.py) | PROVEN | Alpha/Beta/Gamma story with proposal, acceptance, execution review, court notice, breach notice, and witness archive |
| Legacy-compatible runtime seam exists | [`kernel/tests/test_legacy_v1_federation_proof.py`](../kernel/tests/test_legacy_v1_federation_proof.py) | PROVEN | Kernel-side reference adapter proof for legacy integration paths |
| Warrant-bound payouts exist | [`kernel/tests/test_treasury_capsule.py`](../kernel/tests/test_treasury_capsule.py) | PROVEN | Includes reserve-floor gate, phase gate, settlement adapter preflight, verifier-ready contract checks |
| Payout-plan dry-run preview queue exists | [`kernel/tests/test_payout_plan_preview_queue.py`](../kernel/tests/test_payout_plan_preview_queue.py) and [`kernel/tests/test_workspace_context.py`](../kernel/tests/test_workspace_context.py) | PROVEN | Inspectable dry-run queue with operator acknowledgment and read-only inspection; ack does not claim settlement |
| Settlement notice fail-closed behavior exists | [`kernel/tests/test_workspace_context.py`](../kernel/tests/test_workspace_context.py) and [`kernel/tests/test_federation.py`](../kernel/tests/test_federation.py) | PROVEN | Invalid notices open cases and can suspend peers |

## Live Proofs

| Claim | Live Surface | Maturity | Current Truth |
| --- | --- | --- | --- |
| Live workspace exposes runtime-core and agent-runtime truth | `GET /api/context`, `GET /api/status`, `GET /api/agents`, `GET /api/runtime-proof` | PROVEN | Founding-only, single-org, honest boundary classification; bindings are surfaced consistently and `/api/status` includes routing planner and handoff preview truth |
| Live routing preview surfaces are exposed | `GET /api/federation`, `GET /api/federation/handoff-preview-queue` | PROVEN | Local/remote/blocked decisions are preview-only; remote candidates are persisted for inspection, not executed by this surface |
| Live treasury exposes settlement adapter contract | `GET /api/treasury/settlement-adapters` | PROVEN | `internal_ledger` ready; external adapters registered but not executable |
| Live treasury exposes settlement readiness snapshot | `GET /api/treasury/settlement-adapters/readiness` | PROVEN | Host support and verifier blockers are reported truthfully before execution is attempted |
| Live preflight exposes settlement verifier blockers | `POST /api/treasury/settlement-adapters/preflight` | PROVEN | External adapters fail closed until verifier is ready and host support exists |
| Live treasury exposes payout-plan preview queue inspection | `GET /api/treasury/payout-plan-preview-queue`, `GET /api/treasury/payout-plan-preview-queue/inspect` | PROVEN | Dry-run preview records are inspectable; operator acknowledgment is recorded without claiming settlement |
| Live service boundaries are explicitly classified | `GET /api/subscriptions`, `GET /api/accounting`, `GET /api/federation/manifest` | PROVEN | Canonical service module + compatibility role surfaced, no fake multi-host routing |
| Live readiness stays truthful | [`company/meridian_platform/readiness.py`](../../company/meridian_platform/readiness.py) | PROVEN | Founder-backed phase 0, treasury-blocked, customer revenue 0 |

## Declared But Unproven

| Claim | Registry/Code Location | Maturity | What Would Prove It |
| --- | --- | --- | --- |
| MCP adapter satisfies 2/7 hooks | `runtimes.json` -> `mcp_generic` | DECLARED | Adapter code + passing test |
| A2A adapter satisfies 1/7 hooks | `runtimes.json` -> `a2a_generic` | DECLARED | Adapter code + passing test |
| Meridian Loom satisfies 7/7 hooks | `runtimes.json` -> `loom_native` | ACTIVE | 11 runtime planes live, native contract compliance |

## Public Proof Runner

Generate the high-signal public proof bundle:

```bash
python3 examples/generate_public_proof_bundle.py
```

For a human-readable operator view instead of JSON:

```bash
python3 examples/generate_public_proof_bundle.py --format human
```

To embed a truthful live host receipt as well, pass the public live manifest:

```bash
python3 examples/generate_public_proof_bundle.py \
  --live-manifest-url http://127.0.0.1:18901/api/federation/manifest
```

This emits a JSON artifact containing:

1. a three-host federation summary
2. a legacy reference-adapter federation summary
3. an optional live host receipt from `GET /api/federation/manifest`
4. an optional live runtime receipt from `GET /api/runtime-proof`
5. an explicit `not_live_proven` list

A checked-in human-format example lives at
[`examples/public-proof-bundle-human.txt`](../examples/public-proof-bundle-human.txt).

In restricted environments the bundle may mark a proof `skipped` instead of
failing, for example when localhost socket binding is unavailable. That is
expected and truthful.

The broader federation regression matrix remains in
[`kernel/tests/test_federation.py`](../kernel/tests/test_federation.py) and is
still part of the full test suite, but it is not part of the minimal public
proof runner because some localhost transport cases depend on the execution
environment allowing socket binding.

## Frontier, Not Yet Claimed As Live

- live multi-host federation between independent deployed Meridian hosts
- live end-to-end hosted deployment wiring
- live MCP identity propagation beyond current founding-only boundaries
- non-`internal_ledger` settlement execution on a live host

## Future Proof Surface

Target shape for cryptographic proof (none of this exists today):

- **GitHub Actions CI** running the full test suite on every push to `main` and on every PR. Test results recorded as CI artifacts.
- **Sigstore/cosign attestation** signing test results per commit. Each passing suite produces a signed attestation blob tied to the commit SHA.
- **SLSA Level 1 provenance** on tagged releases. Build provenance generated automatically, linking source commit to release artifact.
- **Matrix linkage**: each row in the Reference Proofs and Live Proofs tables above links to a verifiable signed artifact, not just a test file path.

This section describes the target, not the current state. Today, proofs are verified by running tests locally or on a host. The goal is to make every claim independently verifiable by a third party without trusting the host operator.
