# Meridian Roadmap (Public)

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
