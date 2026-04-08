# CASE-STUDY-0001: Sanction -> Remediation Loop

## Objective

Show a minimal governed loop where runtime behavior triggers governance controls and remediation tracking.

## Scenario

1. A governed action violates policy boundary.
2. Court records violation and opens sanction path.
3. Operator remediation closes violation with evidence.

## Evidence Routes

- `/api/status` (court counters + slo status)
- `/api/runtime-proof` (runtime boundary evidence)
- `/api/kernel-proof-bundle` (kernel proof bundle coherence)
- `/api/treasury` (budget/reserve posture)

## Reproduction Skeleton

```bash
cd /path/to/meridian
./scripts/dev-up.sh

# Capture before/after snapshots and a normalized summary artifact
./scripts/research_capture_case_study.sh sanction_remediation_loop

# (module-specific sanction trigger/review commands go here)
```

## Acceptance

1. Violation/sanction counters move in expected direction.
2. Proof surfaces remain reachable and coherent before/after remediation.
3. No silent state mutation without observable route evidence.
4. Case summary file exists with stable invariants:
   - `runtime_id_stable`
   - `proof_mode_stable`
   - `kernel_bundle_route_present`

## Boundary

- This case-study is a local governance trace example.
- It does not claim universal production coverage across all institutions.
