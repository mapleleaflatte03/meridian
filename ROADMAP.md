# Meridian Roadmap (Public)

> For a detailed capability inventory (productized / internal-only / missing), see [`docs/CAPABILITY_CONTRACT.md`](docs/CAPABILITY_CONTRACT.md).

## Phase A — Foundation Lock

- Monorepo as canonical source; archived mirrors stay read-only.
- Redirect policy enforced for issue/PR/discussion routing.
- Public wording locked to open-source + Loom-first product boundary.

## Phase B — Onboarding Contract

- `install-full.sh` + `bootstrap_full.sh` produce ready-to-run local state.
- Required routes after bootstrap:
  - `/api/status`
  - `/api/institution/template`
  - `/api/treasury`
  - `/api/runtime-proof`
  - `/api/kernel-proof-bundle`
- Gate: `scripts/acceptance_onboarding_ready_lane.sh`

## Phase C — Contributor Experience

- Contribution guide, project governance doc, security policy, and templates stay in sync.
- Acceptance evidence required for merge on governance/runtime/public-surface changes.
- Community routing remains GitHub-first with explicit escalation paths.

## Phase D — Research Moat

- Publish reproducible RFC/benchmark/case-study artifacts under `docs/research/`.
- Keep PoGE and governance claims grounded in command evidence and payload traces.
- Prioritize benchmarked hardening of:
  - proof settle latency,
  - fallback success rate,
  - sanction/remediation observability.

## Phase E — Advanced Research (RFC-Driven)

- Recursive PoGE aggregation experiments.
- Runtime/memory optimization for long-lived local agents.
- Institutional/federation extensions only via open RFC path.

## Phase F — Living Institution Surfaces

- Institution status bar on public surfaces sourced from `/api/status`.
- Court voting chamber wired to dynamic court APIs.
- Proof explorer wired to recursive + aggregate payloads.
- Marketplace panel wired to live bid/assign/settle/dispute state.

## Phase G — Replacement-Path Parity

Meridian's long-term goal is not to remain "governance plus wrapper." Loom must grow into a standalone replacement for Claw-family local agent systems, with governance as the differentiator rather than the only value.

Capabilities already productized (see `docs/CAPABILITY_CONTRACT.md` for full inventory):
- One-command install with guided onboarding
- Local agent provisioning and runtime
- Kernel governance (Institution, Authority, Treasury, Court)
- PoGE proof receipts
- Marketplace lifecycle (bid/assign/settle/dispute)
- Provider-agnostic AI routing

Next milestones for replacement-grade parity:
- **Agent memory management CLI/UI** — user-facing tools for inspecting and managing agent memory.
- **Channel configuration in onboarding** — integrate channel setup into first-run flow.
- **Persistent background scheduler** — cron-style recurring agent jobs without manual restart.
- **Browser/action automation** — Loom agents can interact with web pages and local applications.
- **Interactive agent chat** — terminal or web interface for governed conversation with agents.
- **Multi-agent orchestration** — visual or CLI coordination of multiple agents with governance.
- **Plugin/extension discovery** — community extensions installable through Loom CLI.
- **Migration tooling validation** — test and document `migrate-from-claw.sh` as a real path.

Governance contract for all new capabilities:
- Every new surface MUST integrate with Authority, Treasury, Court, and PoGE.
- No capability ships without governance wrapping.
- Replacement-grade does not mean governance-optional.

## Open vs Patent-Candidate Boundaries

- Open by default:
  - protocol specs
  - reference code
  - tests and reproducible benchmark artifacts
- Patent-candidate topics (investigation only, no lock-in in current repo):
  - hypercube pairing optimization strategy
  - adaptive constitutional sanction scoring
  - royalty-proof binding design

Roadmap updates happen in issues/discussions before implementation.
