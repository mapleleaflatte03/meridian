# Meridian Loom

Governed local agent runtime written in Rust. Four crates: `loom-cli`, `loom-core`, `loom-poge`, `loom-shadow`.

## Build & Test

```bash
cargo build                    # build all crates
cargo test                     # run all unit + integration tests
make acceptance-full-system    # 10-step end-to-end lane
```

## Architecture

- **loom-cli**: CLI entry point. Commands: `init-nation`, `breed`, `connect`, `memory`, `observe`, `deploy`, `auth`, `extension`, `quickstart`, `runtime`.
- **loom-core**: Core services — `memory_service`, `channels`, `provider_router`, `wasm_host`, `capabilities`.
- **loom-poge**: Proof of Governed Execution — Merkle roots, witnesses, settlement.
- **loom-shadow**: Shadow execution layer — WASM sandbox, gRPC physical backend, embodied lifecycle.

## Governance Primitives

Every action passes through: **Authority** (permission) -> **Court** (dispute) -> **Treasury** (cost/settlement) -> **Warrant** (cryptographic receipt).

Never bypass governance gates. Never hardcode providers.

## Connect Ecosystem

Adapters live in `templates/connect/`. Each adapter has a manifest, health history, fallback path, and scorecard KPIs. Acceptance lanes per adapter in `scripts/acceptance_connect_*_lane.sh`.

## Key Constraints

- Provider-agnostic: route via config, never hardcode model providers
- PoGE: every governed execution emits a Merkle root + witness digest
- 3-ledger economy: Treasury accounts, payout proposals, contributor ledger
- M-wings branding in all UI/web surfaces
- No prompt/meta jargon in README or public docs
