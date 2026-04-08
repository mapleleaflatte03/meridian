# CASE-STUDY-0002: Hypercube Inclusion Verification

## Scenario

Operator receives one aggregate bundle and needs to validate whether a receipt hash belongs to the bundle.

## Steps

1. Build bundle:

```bash
cd /home/ubuntu/meridian/kernel
python3 examples/generate_public_proof_bundle.py --output /tmp/kernel_bundle_case2.json
```

2. Inspect first inclusion proof:

```bash
jq '.aggregate.inclusion_proofs[0]' /tmp/kernel_bundle_case2.json
```

3. Confirm aggregate flags:

```bash
jq '.aggregate | {aggregate_root,inclusion_verified,member_count}' /tmp/kernel_bundle_case2.json
```

## Expected Result

- inclusion path exists for sampled member
- aggregate root present
- `inclusion_verified == true`

## Notes

This case does not assert business semantics; it asserts cryptographic membership consistency in the aggregate payload.
