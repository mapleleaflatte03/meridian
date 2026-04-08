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

# Capture baseline
curl -fsS http://127.0.0.1:8266/api/status > /tmp/status.before.json
curl -fsS http://127.0.0.1:8266/api/kernel-proof-bundle > /tmp/proof.before.json

# (module-specific sanction trigger/review commands go here)

# Capture after remediation
curl -fsS http://127.0.0.1:8266/api/status > /tmp/status.after.json
curl -fsS http://127.0.0.1:8266/api/kernel-proof-bundle > /tmp/proof.after.json
```

## Acceptance

1. Violation/sanction counters move in expected direction.
2. Proof surfaces remain reachable and coherent before/after remediation.
3. No silent state mutation without observable route evidence.

## Boundary

- This case-study is a local governance trace example.
- It does not claim universal production coverage across all institutions.
