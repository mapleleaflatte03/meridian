# Meridian Ecosystem Residual Plan

This document records the next mandatory repo builds after the current probe, ACPX, onboarding, frontier transport, memory seam, Intelligence slimming, and kernel-admission update.

## Completed since last update (2026-03-29)

- **Safe cancellation surface**: Loom shadow service exposes `POST /cancel` and `cancel_job` request type. ACPX `sessions cancel` wired to real surface with `cancelled`/`not_found`/`not_cancelable` outcomes.
- **Transport ownership deepened**: Session provenance records now carry `transport_kind`, `auth_mode`, `execution_owner`. Provider probe reports consistent transport metadata.
- **Doctor memory check**: `loom doctor` inspects memory service (agents, entries, bytes) under "memory" category.
- **Doctor --fix**: `loom doctor --fix` re-runs workspace scaffolding for safe remediations.
- **Intelligence thinned**: `loom_runtime_proof.py` delegates binary/root discovery to shared `loom_runtime_discovery` module.

## `meridian-shell`
- Purpose: typed workflow shell for governed jobs, resumable steps, approvals, and budget-aware execution.
- Repo path: `/home/ubuntu/meridian-shell`
- First files:
  - `README.md`
  - `pyproject.toml`
  - `meridian_shell/cli.py`
  - `meridian_shell/workflows.py`
  - `meridian_shell/jobs.py`
  - `meridian_shell/approvals.py`
  - `tests/test_cli.py`
  - `tests/test_workflows.py`
- First commands:
  - `meridian-shell workflow init finance_ops`
  - `meridian-shell workflow run finance_ops --input sample.json`
  - `meridian-shell jobs list`
  - `meridian-shell approvals list`
- First tests:
  - workflow schema validation
  - approval state transitions
  - Loom service submission integration
- First proof expectation: one approval-gated workflow runs end-to-end and emits receipt + pipeline provenance.

## `meridian-hub`
- Purpose: versioned registry for skills, souls, workflow packs, and install/update/search flows.
- Repo path: `/home/ubuntu/meridian-hub`
- First files:
  - `README.md`
  - `pyproject.toml`
  - `meridian_hub/cli.py`
  - `meridian_hub/index.py`
  - `meridian_hub/registry.py`
  - `meridian_hub/install.py`
  - `tests/test_registry.py`
- First commands:
  - `meridian-hub index init`
  - `meridian-hub publish skill ./skills/browser`
  - `meridian-hub search browser`
  - `meridian-hub install skill browser`
- First tests:
  - index serialization
  - version conflict handling
  - skill install manifest verification
- First proof expectation: publish a local skill artifact, search it, install it into Loom, and confirm via `loom skill installs`.

## `meridian-node-go`
- Purpose: lightweight remote node runtime for Linux and edge hosts.
- Repo path: `/home/ubuntu/meridian-node-go`
- First files:
  - `README.md`
  - `go.mod`
  - `cmd/meridian-node/main.go`
  - `internal/handshake/handshake.go`
  - `internal/runtime/status.go`
  - `internal/runtime/dispatch.go`
  - `internal/runtime/proof.go`
- First commands:
  - `go test ./...`
  - `meridian-node register --host-id demo-node`
  - `meridian-node status --json`
- First tests:
  - host handshake
  - signed status snapshots
  - dispatch receipt parsing
- First proof expectation: node registers, reports health, and accepts one bounded dispatch with audit proof.

## `meridian-windows-node`
- Purpose: Windows companion/runtime surface with service mode and operator-safe permissions.
- Repo path: `/home/ubuntu/meridian-windows-node`
- First files:
  - `README.md`
  - `MeridianNode.sln`
  - `src/Meridian.Node/Program.cs`
  - `src/Meridian.Node/ServiceHost.cs`
  - `src/Meridian.Node/StatusReporter.cs`
  - `tests/Meridian.Node.Tests/StatusReporterTests.cs`
- First commands:
  - `dotnet test`
  - `Meridian.Node.exe status --json`
  - `Meridian.Node.exe register --host-id demo-win-node`
- First tests:
  - service registration
  - status JSON stability
  - dispatch auth boundary checks
- First proof expectation: Windows node reports status and can be seen by probe tooling.

## `meridian-home`
- Purpose: local device and home bridge for sensors, devices, and household workflows.
- Repo path: `/home/ubuntu/meridian-home`
- First files:
  - `README.md`
  - `pyproject.toml`
  - `meridian_home/cli.py`
  - `meridian_home/devices.py`
  - `meridian_home/events.py`
  - `meridian_home/bridge.py`
  - `tests/test_devices.py`
- First commands:
  - `meridian-home devices list`
  - `meridian-home bridge status`
  - `meridian-home emit event door.open`
- First tests:
  - device registry loading
  - event normalization
  - bridge receipt emission
- First proof expectation: one local device event enters Loom as a bounded channel ingress with provenance.

## `meridian-orchestrator`
- Purpose: autonomous coding and ops orchestration plane for long-running repo tasks.
- Repo path: `/home/ubuntu/meridian-orchestrator`
- First files:
  - `README.md`
  - `pyproject.toml`
  - `meridian_orchestrator/cli.py`
  - `meridian_orchestrator/runs.py`
  - `meridian_orchestrator/policies.py`
  - `meridian_orchestrator/worktrees.py`
  - `tests/test_runs.py`
- First commands:
  - `meridian-orchestrator run create --kind repo_fix`
  - `meridian-orchestrator run status --run-id ...`
  - `meridian-orchestrator run approve --run-id ...`
- First tests:
  - run lifecycle
  - policy gating
  - worktree isolation
- First proof expectation: one orchestrated repo task creates a run, pauses for approval, resumes, and emits receipts.

## Build order
1. `meridian-shell`
2. `meridian-hub`
3. `meridian-node-go`
4. `meridian-windows-node`
5. `meridian-home`
6. `meridian-orchestrator`

## Definition of done for each residual repo
- has a real CLI
- has unit tests
- has one live proof path
- has a stable JSON output for `meridian-probe` integration
- does not hide generic runtime truth in Intelligence
