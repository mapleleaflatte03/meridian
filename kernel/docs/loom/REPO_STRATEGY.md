# Meridian Loom — Repository Strategy

**Status:** Decision document plus official first-party runtime repo

A separate `meridian-loom` runtime repo now exists publicly at
`https://github.com/mapleleaflatte03/meridian-loom` to validate the repo
shape, Rust workspace layout, CI workflow, and the runtime/product path.

## Decision: Separate Repository

Meridian Loom will live in a **separate repository** from the Meridian Kernel.

### Why separate

1. **Different release cadence.** The kernel is a stable governance API. Loom
   is an execution runtime with faster iteration, more dependencies, and a
   build toolchain (Cargo/Rust) that the kernel (pure Python, stdlib-only) does
   not need.

2. **Different dependency graphs.** The kernel has zero external dependencies
   by design. Loom depends on Rust crates, WASM tooling, and transport-layer
   libraries. Mixing them would pollute the kernel's clean dependency boundary.

3. **Independent adoption.** A team might use the kernel with a different
   runtime (Loom, OpenFang, etc.). A team might also evaluate Loom before
   committing to the full kernel governance model. Separate repos make both
   paths natural.

4. **CI isolation.** Kernel CI runs Python tests with no build step. Loom CI
   runs `cargo build`, WASM compilation, and integration tests against a kernel
   instance. These should not block each other.

### What stays in the kernel repo

- The governance primitives (Institution, Agent, Authority, Treasury, Court)
- The 7-hook contract spec (`kernel/runtimes.json`, `RUNTIME_CONTRACT.md`)
- The runtime adapter tooling (`runtime_adapter.py`)
- The Loom spec document (`docs/LOOM_SPEC.md`) — this is a kernel-side spec
  of what Loom must satisfy, not Loom's own implementation docs
- Brand assets and proof documents

### What goes in the Loom repo

- All Rust source (`src/`)
- Worker scaffolds (`workers/python/`, `workers/typescript/`, `workers/wasm/`)
- `loom.toml` configuration
- `Cargo.toml` and `Cargo.lock`
- Loom's own integration tests
- Loom's own documentation (install, CLI, modes)

### Repository name

`meridian-loom` under the same GitHub organization.

### Cross-repo contract

The kernel repo publishes the 7-hook contract spec. Loom's CI pulls that spec
and runs compliance checks against it. This is a one-directional dependency:
Loom depends on the kernel spec; the kernel never depends on Loom.

```
meridian-kernel/kernel/runtimes.json   →  source of truth for contract
meridian-loom/tests/contract_test.rs   →  pulls spec, proves compliance
```

### When this decision could change

If Loom stabilizes and the kernel adds Loom-specific admission primitives
(e.g., WASM capability declarations in agent registration), a monorepo with
workspace-level separation (`kernel/` and `loom/` directories) could make
sense. But that decision is deferred until Phase 2 or later — premature
coupling is worse than the overhead of two repos.
