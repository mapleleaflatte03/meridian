<p align="center">
  <img src="assets/meridian_loom_lockup.svg" alt="Meridian Loom" width="720">
</p>

<p align="center">
  Publication rules for a repo that is public on purpose and still strict about its proof boundary.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/repo-public-0f766e?style=flat-square" alt="Repo public">
  <img src="https://img.shields.io/badge/runtime-official%20v0.1-0c1117?style=flat-square" alt="Official v0.1">
  <img src="https://img.shields.io/badge/checklist-honest%20or%20do%20not%20publish-0c1117?style=flat-square" alt="Honest checklist">
</p>

<p align="center">
  <a href="../README.md">Loom README</a> ·
  <a href="SETUP_REHEARSAL.md">Setup Rehearsal</a> ·
  <a href="ARCHITECTURE.md">Architecture</a> ·
  <a href="https://github.com/mapleleaflatte03/meridian-kernel/blob/main/docs/LOOM_SPEC.md">Loom Spec</a> ·
  <a href="https://github.com/mapleleaflatte03/meridian-kernel">Kernel Repo</a>
</p>

# Meridian Loom Publication Checklist

This checklist records the conditions required to keep Loom public as an
official local runtime without overclaiming what the runtime can already prove.

## Local repository truth

- [x] `README.md` positions Loom as the official governed local runtime
- [x] `LICENSE` is present
- [x] docs hero assets exist (`meridian_loom_lockup.svg`, `loom_runtime_panels.svg`)
- [x] GitHub Actions workflow exists for `cargo test` and `cargo build`
- [x] `loom.toml.example` exists
- [x] personal-agent templates exist
- [x] Setup rehearsal script exists
- [x] Runtime rehearsal surface exists (`loom action execute` + `loom parity report`)
- [x] Setup rehearsal documentation is current
- [x] Cargo workspace builds locally
- [x] Cargo workspace tests pass locally

## First public push status

- [x] GitHub API access works again
- [x] Public repository is created
- [x] Remote `origin` points at the public repository
- [x] First push succeeds

## First public release message

Every public Loom publication must preserve these truths:

- Loom is the active Meridian runtime surface today
- Loom is Meridian's official first-party runtime, not merely a future runner
- Loom contract truth should stay aligned with the kernel runtime registry and proof surfaces
- legacy compatibility remains bounded and secondary
- publication must not overclaim hosted or production-wide cutover

## Recommended local command

```bash
./scripts/check_publication_readiness.sh
```
