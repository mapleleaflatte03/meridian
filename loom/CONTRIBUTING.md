# Contributing to Meridian Loom

Meridian Loom is a governed runtime. Contributions must preserve:

- Sovereign agent execution
- PoGE/verifiable receipts
- Warrant, court, authority, and treasury boundaries
- Provider-agnostic configuration surfaces

## Fast local path

```bash
make dev-first-proof
```

This lane runs the one-command first-proof surface and validates the local runtime boundary.

## Development flow

1. Create a focused branch.
2. Add tests first.
3. Implement the smallest scoped change.
4. Run the related acceptance lane(s).
5. Keep migration + rollback notes in README/doc updates.

## Required checks before PR

```bash
cargo test --workspace
cargo clippy -p meridian-loom --all-targets
make acceptance-security-auth-lane
make acceptance-observability-lane
make acceptance-oss-dx-lane
```

## Governance-safe change checklist

- No hardcoded provider-specific defaults in new config surfaces.
- No plaintext secret persistence in runtime artifacts.
- No bypass around authority/court/treasury checks.
- No claim in docs/UI that exceeds current live proof boundary.

## Good first governance tasks

- Improve operator remediation hints in `loom observe`.
- Add deterministic fixtures for degraded queue/proof scenarios.
- Expand acceptance lanes with idempotency and rollback checks.
