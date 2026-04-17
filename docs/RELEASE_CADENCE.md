# Release Cadence

## Current Model

Meridian ships on a **tag-driven** release model for the Loom runtime package:

- **Tags**: A push to `v0.x.y` triggers the checked-in Loom release workflow at `loom/.github/workflows/release.yml`.
- **Artifacts**: Four platform binaries (linux x86_64/aarch64, darwin x86_64/aarch64) plus SHA-256 checksums.
- **Cadence**: No fixed calendar. Releases happen when a meaningful milestone (feature, fix, or benchmark improvement) lands on `main`.

## What a Release Includes

Each release contains:

1. **Loom CLI binary** — the runtime engine for Core and Team
2. **Kernel governance state** — institution, treasury, court, authority primitives
3. **Intelligence surfaces** — gateway, proof routes, workflow gallery
4. **Scripts** — onboarding, core task runner, dev-up/down, benchmark lane, migration tool

## How to Cut a Release

```bash
# 1. Ensure main is clean and tests pass
git status
cargo test --manifest-path loom/Cargo.toml --workspace
python3 -m unittest discover -s intelligence/company/meridian_platform -p 'test_*.py'

# 2. Tag and push (the checked-in release workflow lives under loom/)
git tag v0.1.17
git push origin v0.1.17

# 3. GitHub Actions builds and publishes Loom release assets
```

## Release Verification

```bash
# After download, verify the release artifact
./scripts/benchmark_meridian.sh --iterations 5
./scripts/acceptance_onboarding_ready_lane.sh
```

## Version History

| Version | Date | Highlights |
| --- | --- | --- |
| v0.1.17 | 2026-04 | Current: release hardening — Rust supervision race fix, Team example Basic-auth path, docs/example truth |
| v0.1.16 | 2026-04 | Core/Team modes, governed execution, benchmark lane |

## Release Notes Convention

Each GitHub release includes:
- Summary of changes (features, fixes, improvements)
- Benchmark artifact comparison with previous release where applicable
- Migration notes if behavior changed
- Link to relevant docs

## Further Reading

- [loom/docs/RELEASE.md](../loom/docs/RELEASE.md) — Loom-specific release packaging details
- [CONTRIBUTING.md](../CONTRIBUTING.md) — contributor path
- [ROADMAP.md](../ROADMAP.md) — planned work
