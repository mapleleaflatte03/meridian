# BENCHMARK-0002: Hypercube Aggregation Latency and Integrity

## Objective

Measure bundle build latency and verify inclusion correctness for hypercube aggregation.

## Reproduction

```bash
cd /home/ubuntu/meridian/kernel
python3 examples/generate_public_proof_bundle.py --output /tmp/kernel_bundle_bench.json
jq '.aggregate | {bundle_id,dimension,member_count,inclusion_verified}' /tmp/kernel_bundle_bench.json
```

## Metrics

- `member_count`
- `dimension`
- `inclusion_verified` (must be `true`)
- generation wall time (shell timing)

## Pass Criteria

1. `inclusion_verified == true`
2. `member_count >= 1`
3. aggregate payload includes `member_receipts` and `inclusion_proofs`

## Regression Signal

- inclusion path missing
- `inclusion_verified == false`
- aggregate route returns metadata-only block
