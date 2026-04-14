# Meridian Capability Contract

Honest inventory of what Meridian supports today, what exists internally but isn't product-grade, and what's needed for replacement-grade parity with Claw-family agent systems.

## Tier 1 — Productized and Supported Now

Capabilities that are installed, tested, and available to end users through documented paths.

| Capability | Surface | Verification |
|-----------|---------|-------------|
| One-command install | `scripts/install-full.sh` | `acceptance_clean_slate_user_mode_lane.sh` |
| Guided first-run onboarding | `scripts/onboard.sh` | `acceptance_onboarding_ready_lane.sh` |
| Three install modes (user/demo/maintainer) | `bootstrap_full.sh` | Mode gate in bootstrap |
| Local agent provisioning | `loom new-agent` / `new-first-agent.sh` | CLI output + agent config |
| Kernel governance primitives | Institution, Authority, Treasury, Court | Kernel smoke check |
| PoGE proof receipts | `loom-poge` crate | `/api/runtime-proof`, `/api/kernel-proof-bundle` |
| Budget controls (reserve floor, spend limits) | Treasury module | `/api/treasury` |
| Court rules and sanctions | Court module | Court rule count check |
| Marketplace lifecycle | bid → assign → settle → dispute | `acceptance_onboarding_ready_lane.sh` |
| Provider-agnostic AI routing | `brain_router` | Config-driven, no hardcoded providers |
| Public web surfaces | Homepage, Pilot, Compare, Proofs, Workflows | Static HTML served by gateway |
| Local workspace API | `/api/status`, `/api/institution/template`, etc. | Gateway smoke check |

## Tier 2 — Present in Runtime/Internal State, Not Yet Product-Grade

Capabilities that exist in code or server state but lack documented install paths, user-facing docs, or acceptance verification.

| Capability | Location | Gap |
|-----------|----------|-----|
| Agent memory service | `loom-core/memory_service` | No user-facing memory management CLI/UI |
| Channel system | `loom-core/channels` | Channel config not part of onboarding |
| WASM sandbox execution | `loom-shadow/wasm_host` | No user docs for WASM agent extensions |
| Side hustle / autonomous work loops | `intelligence/.../side_hustle.py` | API exists but not in onboarding or public docs |
| Federation inbox | `kernel/economy/federation_inbox.json` | Multi-institution federation not user-documented |
| Revenue/subscription tracking | `kernel/economy/revenue.py`, `subscriptions.json` | Internal operator tooling only |
| Authority warrant queue | `kernel/economy/authority_queue.json` | Queue exists but no user-facing approval UI |
| Payout proposals | `kernel/economy/payout_proposals.json` | Contributor payout not user-documented |
| Agent profiles (aegis, atlas, forge, etc.) | `loom/agents/` | Pre-built agents not in onboarding path |
| Commonwealth research features | `intelligence/.../commonwealth.py` | Research module, not general-purpose |

## Tier 3 — Missing / Required for Replacement-Grade Parity

Capabilities needed for Meridian to serve as a full replacement for Claw-family local agent systems.

| Capability | Why Needed | Status |
|-----------|-----------|--------|
| Browser/action automation | Claw-family systems interact with browser; Loom doesn't yet | Not implemented |
| Persistent background scheduler | Cron-style recurring agent jobs without manual restart | Partial (supervisor exists, no scheduler) |
| Multi-agent orchestration UI | Visual/CLI orchestration of multiple agents | Not implemented (registry exists) |
| Plugin/extension marketplace | Discover and install community agent extensions | Not implemented |
| Research/retrieval pipelines | Web search, document retrieval, RAG-style workflows | Brain router exists, no pipeline orchestration |
| Interactive chat interface | Terminal or web chat with governed agent | Not implemented |
| Migration tooling from Claw | Import Claw configs/agents into Meridian | `migrate-from-claw.sh` exists, untested |
| Cross-device sync | Sync agent state across machines | Not implemented (local-first by design) |
| Hosted/cloud option | Optional remote execution for teams | Not implemented (local-first by design) |

## Governance Wrapping

Every Tier 1 and Tier 2 capability operates within Meridian's governance contract:

| Governance Layer | What It Covers |
|-----------------|----------------|
| Authority | High-risk actions require explicit warrants |
| Treasury | Budget checks before spend; reserve floor enforced |
| Court | Violations recorded; sanctions and appeals tracked |
| PoGE | Every governed execution emits verifiable proof receipt |
| Marketplace | Work assignment uses bid/assign/settle/dispute lifecycle |

Tier 3 capabilities, when implemented, MUST integrate with these governance primitives. This is Meridian's differentiator.

## What This Contract Prohibits

- Claiming Tier 2 or Tier 3 capabilities as "supported" in public-facing surfaces
- Describing runtime/internal state as product features
- Marketing replacement-grade parity before Tier 3 gaps are closed
- Implementing Tier 3 without governance wrapping
