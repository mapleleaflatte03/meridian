# Meridian Loom Community Map

## Project shape

- `crates/loom-cli`: operator-facing command surface
- `crates/loom-core`: runtime config, routing, context, memory primitives
- `crates/loom-shadow`: governed execution capture, parity/proof, queue/service runtime
- `scripts/`: acceptance lanes and reproducible operator workflows

## Where to start

1. Run `make dev-first-proof`.
2. Read `docs/ARCHITECTURE.md`.
3. Pick a scoped lane:
   - Security/Auth: `make acceptance-security-auth-lane`
   - Observability: `make acceptance-observability-lane`
   - OSS DX: `make acceptance-oss-dx-lane`

## Change lanes and owners (logical)

- Runtime control plane: `loom-cli` + `loom-shadow`
- Provider/auth routing: `loom-core/provider_router.rs`, `loom-core/provider_auth_store.rs`
- Governance receipts: `loom-shadow` report/capture surfaces
- Docs + acceptance: `README.md`, `scripts/`, `.github` templates

## Contribution boundaries

- Keep provider configuration agnostic.
- Preserve warrant/court/authority/treasury semantics.
- Prefer additive migration layers over breaking defaults.
- Ensure each operator-facing feature has:
  - Tests
  - Acceptance lane
  - Rollback note
