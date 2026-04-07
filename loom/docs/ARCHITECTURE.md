# Meridian Loom Architecture

Meridian Loom is the operator-facing local runtime boundary for Meridian. The repo is intentionally local-first: it proves a real service, queue, audit, parity, and operator surface on one host without claiming hosted replacement or live transport cutover.

## Stable surfaces

- Local service lifecycle: foreground and background modes, status, stop, logs, and restart.
- Queue seam: inspect, consume, ack, run-once, run-until-empty, and status over local records.
- Runtime artifacts: job ledger, audit trail, parity stream, parity report, and shadow decisions.
- Install paths: source build, tarball, and container-oriented packaging.
- Operator docs: install, run, config, service, operations, and release guidance.

## Runtime layout

A runtime root is expected to hold:

- `loom.toml`
- `state/`
- `run/service/`
- `run/ingress/`
- `logs/`
- `capabilities/`
- `artifacts/audit/`
- `artifacts/parity/`
- `artifacts/runtime/`
- `artifacts/shadow/`

## Compatibility notes

Legacy compatibility identifiers remain only where they still serve backward compatibility for parsing, import, or migration surfaces. They do not define the current active runtime path.

## Script layout

- `scripts/tests/` contains operational rehearsals that exercise the current Loom surface.
- `scripts/migration_tools/` contains import and back-compat rehearsals that preserve older compatibility paths without presenting them as the primary runtime.

See [README.md](../README.md) for the concise repo truth and operator links.
