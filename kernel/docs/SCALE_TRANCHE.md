# Kernel Scale Tranche (Current)

This tranche isolates two scale-level tracks without weakening the existing Python governance core.

## 1) Rust-Kernel Exploration Track

- Keep the current Python Kernel as canonical runtime.
- Mirror core contracts in Rust prototypes (read-only first).
- Current implemented lane:
  - `kernel-rs-explore/` crate with deterministic governance gate checks.
  - `evaluate_action` contract models:
    - warrant gate
    - authority gate
    - court gate
    - treasury reserve-floor gate
  - proof envelope schema:
    - `meridian.kernel.rs.explore.proof.v1`
- Verification command:
  - `examples/run_rust_kernel_exploration.sh`
- Success criteria:
  - contract parity fixtures pass against Python outputs
  - no mutation path moved until parity is stable

## 2) Treasury Deep Stabilization Track

- Extend treasury runtime-budget tests with mixed lifecycle flow:
  - reserve -> commit
  - reserve -> release
  - reserve -> expire
- Track invariants:
  - active reservations return to `0`
  - committed/released/expired totals remain internally consistent
  - available-for-reservation never drops below `0` for valid paths
- Current lane:
  - `kernel/tests/test_treasury_stabilization_lane.py`

## Rollback

- No migration or storage model change in this tranche.
- If any stability lane regresses, remove the new lane and keep existing treasury behavior unchanged.
