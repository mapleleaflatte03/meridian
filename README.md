<p align="center">
  <img src="company/www/assets/meridian_lockup.svg" alt="Meridian live host" width="720">
</p>

<p align="center">
  <strong>Meridian — Loom-first governed agent runtime portal</strong><br>
  Loom is the flagship local runtime product, Kernel is the runtime-neutral governance core, and the Meridian apps are first-party proof workloads.<br>
  The live host keeps that hierarchy explicit instead of collapsing it into one vague category claim.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/release-live%20host-0c1117?style=flat-square" alt="live host">
  <img src="https://img.shields.io/badge/surface-public%20intelligence-0f766e?style=flat-square" alt="Public intelligence surface">
  <img src="https://img.shields.io/badge/runtime-truthfully%20bounded-1f6feb?style=flat-square" alt="Truthfully bounded runtime">
  <img src="https://img.shields.io/badge/install-1--command-111827?style=flat-square" alt="1-command install">
</p>

<p align="center">
  <a href="https://app.welliam.codes/">Home</a> ·
  <a href="https://app.welliam.codes/loom">Loom</a> ·
  <a href="https://app.welliam.codes/why">Why</a> ·
  <a href="https://app.welliam.codes/compare">Compare</a> ·
  <a href="https://app.welliam.codes/demo">Demo</a> ·
  <a href="https://app.welliam.codes/proofs">Proofs</a> ·
  <a href="https://app.welliam.codes/workflows">Workflows</a> ·
  <a href="https://app.welliam.codes/community">Community</a> ·
  <a href="https://app.welliam.codes/support">Support</a> ·
  <a href="https://app.welliam.codes/boundary">Boundary</a> ·
  <a href="https://github.com/mapleleaflatte03/meridian">Docs</a> ·
  <a href="https://github.com/mapleleaflatte03/meridian/blob/main/CONTRIBUTING.md">Contribute</a>
</p>

# Meridian Intelligence

This repo is the public Meridian portal plus the first-party Meridian apps that run on Loom + Kernel. It is not the governance kernel, and it is not the runtime itself. The product front door is now Loom.

## Launch Positioning

Meridian currently presents a Loom-first hierarchy around four ideas:

- Meridian Loom as the flagship local runtime product.
- Meridian Kernel as the runtime-neutral governance core.
- Meridian Intelligence plus bounded Trust Ops as first-party workloads that prove the runtime under real pressure.
- A truthful host boundary that separates verified live routes from future deployment claims.

Operational positioning shorthand:

- Claw-family stacks: broad personal-assistant autonomy surfaces.
- Meridian Loom: governed runtime execution for organizations that need
  receipts, warrants, court/authority policy, and treasury-gated labor.

## 1-Command Install

If the operator question is "what do I install?", use the monorepo one-command setup:

```bash
curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash
```

This keeps onboarding in one place while preserving clear module boundaries.

## Product Hierarchy

The current Meridian story across the stack is:

- **Loom runtime:** the product front door and official first-party runtime.
- **Kernel boundary:** five runtime-neutral governance primitives — Institution, Agent, Authority, Treasury, Court.
- **First-party Meridian apps:** Intelligence and bounded Trust Ops workloads that prove what Loom + Kernel can carry.

Loom carries execution, sessions, channels, skills, personal agents, and memory/context. Kernel carries authority, treasury, court, warrants, sanctions, and the runtime contract. Commitment remains a Meridian platform primitive composed above Kernel, but it is not the category center or the runtime front door.

## Competitive Snapshot Tooling

To keep Meridian-vs-Claw comparisons reproducible, this repo ships a repeatable
snapshot lane:

```bash
./scripts/acceptance_competitor_snapshot_lane.sh
```

It writes:

- `output/competitor_snapshot/latest.json`
- `output/competitor_snapshot/latest.md`

Both artifacts contain the same fixed repo set (Meridian stack + Claw-family
repos) with stars/forks and recent commit velocity windows (`24h`, `72h`,
`7d`).

## Brain Router Migration (Provider-Agnostic)

Manager routing now uses an agnostic brain router surface instead of provider-named defaults.

- New optional env surface:
  - `MERIDIAN_BRAIN_ROUTER_CONFIG_PATH`
  - `MERIDIAN_BRAIN_MANAGER_PROFILE_NAME`
  - `MERIDIAN_BRAIN_MANAGER_TRANSPORT` (`cli_session` or `http_json`)
  - `MERIDIAN_BRAIN_MANAGER_ENDPOINT`
  - `MERIDIAN_BRAIN_MANAGER_MODEL`
  - `MERIDIAN_BRAIN_MANAGER_KEY_POOL` / `MERIDIAN_BRAIN_MANAGER_KEY_ENV_POOL`
  - `MERIDIAN_BRAIN_MANAGER_FAILOVER_STATUS_CODES`
- Config schema + sample:
  - `company/meridian_platform/config/brain_router.schema.json`
  - `company/meridian_platform/config/brain_router.sample.json`
- Backward compatibility:
  - legacy manager env keys are still read through a migration layer.
  - no provider-named defaults are required for new installs.

Rollback plan (safe + quick):
1. Set `MERIDIAN_BRAIN_MANAGER_TRANSPORT=cli_session` and `MERIDIAN_BRAIN_MANAGER_CLI_BIN=codex`.
2. Unset `MERIDIAN_BRAIN_MANAGER_ENDPOINT` and key-pool envs.
3. Restart `meridian-gateway.service`.
4. Verify via `GET /api/status` and a short manager route request.

## Monorepo Architecture

- [meridian/loom](https://github.com/mapleleaflatte03/meridian/tree/main/loom): first-party local runtime, CLI, personal agents, channels, memory, and proof receipts.
- [meridian/kernel](https://github.com/mapleleaflatte03/meridian/tree/main/kernel): governance truth, institution, authority, treasury, court, and the runtime contract Loom consumes.
- [meridian/intelligence](https://github.com/mapleleaflatte03/meridian/tree/main/intelligence): portal, live host surface, first-party workflows, and contribution-first research routes.

## What Is Live Today

- Loom as both the live execution runtime on this host and the installable local runtime.
- The public web portal, Loom landing page, compare page, demo page, and boundary note.
- A public proof dashboard with realtime event stream (`/proofs`).
- A workflow gallery with live treasury/payout snapshot (`/workflows`).
- A community operating page (`/community`) tied to governance-first contribution lanes.
- Competitor intelligence as the first Loom-backed first-party workflow.
- Bounded Trust Ops primitives as additional first-party workloads on the same host.
- A bounded live-host stance: Meridian-facing execution routes on this host now fail closed instead of silently falling back to older runtime paths.
- Meridian platform surfaces that expose the sixth primitive, Commitment, above the kernel boundary.
- A public runtime comparison page that explains where Loom is sharper than OpenClaw, OpenFang, IronClaw, TEMM1E, Goose, OpenHands, CrewAI, and LangGraph and where it still has to earn the right to win: https://app.welliam.codes/compare

## What Is Not Claimed

- Full hosted runtime replacement.
- Every possible deployment route running live on this host.
- Universal live automation without treasury, policy, and boundary proof.

## Intelligence Workflow (Current Vertical)

Competitive intelligence is the first managed first-party workflow vertical. What exists today is the workflow, the runtime, and the product surface. What is intentionally still narrow is the delivery promise. The public demo and battlecard pages include qualified reference examples; they are not meant to imply that every illustrated output is a currently live customer artifact on the public host.

- **Cited competitor alerts** — findings on pricing changes, launches, API updates, and deprecations
- **Curated intelligence briefs** — top competitive moves with action items
- **Battlecards on demand** — structured competitor snapshots for sales enablement
- **Competitor watchlists** — track specific companies through the governed workflow

### Current Entry Path (Open Source)

Start with these public surfaces:
- Loom: https://app.welliam.codes/loom
- Demo: https://app.welliam.codes/demo
- Proofs: https://app.welliam.codes/proofs
- Workflows: https://app.welliam.codes/workflows
- Community: https://app.welliam.codes/community
- Support: https://app.welliam.codes/support
- Contact: Telegram [@Enhanhsj](https://t.me/Enhanhsj) or email `nguyensimon186@gmail.com`

Meridian is now positioned as an open research and contribution stack. Public surfaces are for proof visibility, reproducible workflows, and governance experimentation. They are not a hard-paywalled sales funnel.

### 5-Step Open Contribution Path (Current Live Boundary)

If your goal is "agent work -> verifiable governance -> community contribution", use this sequence:

1. Install Loom and run first proof (`loom quickstart`) on your own host.
2. Verify runtime and governance receipts in `/proofs` (`/api/events/stream`).
3. Inspect live workflow state in `/workflows` (`/api/workflows/showcase`).
4. Validate treasury and payout policy state from `/api/treasury` and `/api/payouts`.
5. Contribute patches/tests/docs with claims bounded to what receipts and treasury state can currently prove on-host.

If you are unsure about operational boundaries, read:
- [Meridian Doctrine](company/MERIDIAN_DOCTRINE.md)

---

## MCP Tools

Connect via SSE: `https://app.welliam.codes/sse`

```json
{
  "mcpServers": {
    "meridian": {
      "url": "https://app.welliam.codes/sse"
    }
  }
}
```

| Tool | Access | Description |
|------|--------|-------------|
| `intelligence_latest_brief` | Public research surface | Brief output for the host-bound Meridian institution in current OSS boundary |
| `intelligence_on_demand_research` | Public research surface | Sourced research findings on the current public MCP surface |
| `intelligence_competitor_snapshot` | Public research surface | Competitor snapshot surface; public battlecard layouts remain reference examples |
| `intelligence_qa_verify` | Public research surface | QA verification of claims or text |
| `intelligence_weekly_digest` | Public research surface | Weekly digest surface; public layout remains a reference example |
| `company_info` | Public | Meridian capabilities and runtime boundary |

On the live host today, every MCP tool call is audited and metered for the
host-bound Meridian institution path. The shared runtime-core taxonomy classifies
that path as `mcp_service` with identity model `x402_payment` and scope
`host_bound_service_only`. Multi-institution MCP routing is not live.
The live agent registry also surfaces `runtime_binding` on each governed agent
record, and that same field is visible through `GET /api/agents` and the
`agents` array plus the top-level `agent_runtime_bindings` summary block inside
`/api/status`. That makes the agent-bound runtime truth public instead of
implicit.

---

## Support and Sustainability

- **MCP tool transport:** [x402](https://x402.org) over USDC on Base L2 (when enabled by host policy)
- **Support / sponsorship:** use the support page for voluntary backing of build, infra, and open kernel work
- **Research grants / consulting:** optional sustainability channels; not required for core OSS usage
- **Chain:** Base L2 (Chain ID 8453)
- **Token:** USDC (`0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`)
- **Wallet:** `0x82009D0fa435d490A12e0cBfBE47bf3358e47761`

---

## Managed Agent Team

Every agent is a registered entity with identity, scopes, budget, and reputation.

| Agent | Role | Purpose |
|-------|------|---------|
| **Leviathann** | Manager | Orchestrates pipeline, routes work, closes loops |
| **Atlas** | Analyst | Research, sourced findings, competitive analysis |
| **Quill** | Writer | Structured briefs, release-ready deliverables |
| **Aegis** | QA Gate | PASS/FAIL acceptance with evidence |
| **Sentinel** | Verifier | Contradiction detection, risk review |
| **Forge** | Executor | Implementation, operational steps |
| **Pulse** | Compressor | Context compression, triage |

Agents earn REP (reputation) and AUTH (authority) from accepted output. Sanctions apply for failures, fake progress, or wasted resources.

---

## Reference CI Pipeline

The CI workflow is structured as a nightly sequence. The logic is real and contribution-facing; claims remain bounded to what the current public host can verify.

1. **Research** — Fetch tracked sources. Watchlist competitors get priority.
2. **Extract** — Sourced findings with relevance scoring and deduplication
3. **Write** — Cited intelligence alert in structured format
4. **QA** — Multi-agent verification: source freshness, citation accuracy, quality bar
5. **Deliver** — Approved alert through the current bounded runtime path on the public host
6. **Score** — Economy auto-scores agents (REP/AUTH deltas). Registry syncs.
7. **Audit** — Every step logged. Usage metered.

---

## Economy

Constitutional 3-ledger internal economy:

- **REP (Reputation)** — earned from accepted output, non-transferable
- **AUTH (Authority)** — temporary right to lead work, decays without output
- **CASH (Treasury)** — real money only (owner capital, sponsorship, grants, and approved program revenue)

---

## Tech Stack

- **Runtime:** [Meridian Loom](https://github.com/mapleleaflatte03/meridian/tree/main/loom) — primary execution surface for agent execution, capability dispatch, sessions
- **Platform:** Python 3.10, JSON state files, JSONL audit/metering logs
- **Proxy:** Caddy (auto-TLS)
- **Payments:** [x402](https://x402.org) + USDC on Base L2
- **Infrastructure:** VPS (Vultr), Docker sandboxing, systemd

---

*Meridian platform for governed digital labor. Built on the Meridian Constitutional Kernel and the Meridian Loom runtime. Running since 2026-03-15.*
