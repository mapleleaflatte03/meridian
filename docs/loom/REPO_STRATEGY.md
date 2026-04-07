# Meridian Loom — Repository Strategy

**Status:** Adopted monorepo execution model for OSS onboarding, with explicit module boundaries preserved.

## Decision: Monorepo Adopted

Meridian now runs with a canonical monorepo layout for day-to-day OSS execution:

```text
meridian/
├── loom/
├── kernel/
└── intelligence/
```

The previous split-repo model (`meridian-loom`, `meridian-kernel`, `meridian-intelligence`) remains useful as historical mirrors and public module entry points, but contributor onboarding and integrated development now target the unified `meridian/` workspace.

## Why we were separate before

The stack started as separate repositories because:

1. **Different release cadence** across runtime (Rust) and kernel (Python stdlib).
2. **Different dependency graphs** and toolchains.
3. **Runtime-neutral governance goals** required clean separation of concerns.
4. **CI isolation** simplified early stabilization.

Those reasons were valid for early bootstrapping and proof hardening.

## Why monorepo now

Monorepo is now preferred for OSS growth and reproducibility:

1. **One-command onboarding** for full stack setup.
2. **Single clone for contributors** instead of cross-repo path wiring.
3. **Integrated acceptance lanes** for runtime + governance + portal surfaces.
4. **Path-filtered CI** keeps per-module test isolation while preserving one workspace.

## Boundary invariants (still enforced)

Monorepo does **not** collapse architectural boundaries:

- `kernel/` remains governance source of truth (Institution, Agent, Authority, Treasury, Court).
- `loom/` remains execution/runtime surface consuming kernel contracts.
- `intelligence/` remains operator/workflow and public surface layer.

Governance semantics and contract boundaries are unchanged; only repository ergonomics changed.

## Contract ownership in monorepo

```text
kernel/kernel/runtimes.json      → source of truth for runtime contract
loom/tests/*contract*            → compliance proof against kernel contract
intelligence/meridian_gateway.py → bounded public/control-plane integration
```

This keeps kernel authority explicit while making end-to-end verification easier for contributors.
