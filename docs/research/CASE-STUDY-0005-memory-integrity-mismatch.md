# CASE-STUDY-0005: Memory Integrity Mismatch Rejection

## Scenario

Memory chain is tampered and temporal query must reject with explicit mismatch.

## Steps (test harness)

Run the unit test that simulates tampering:

```bash
cd /home/ubuntu/meridian/intelligence
python3 -m unittest -v company.meridian_platform.test_memory_graph_temporal.MemoryGraphTemporalTests.test_temporal_query_rejects_integrity_mismatch
```

## Expected Result

- test passes only when `temporal_query_with_proof` raises `memory_integrity_mismatch:*`
- API layer converts mismatch into HTTP 409 with structured error payload
