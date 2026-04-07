# Open-Source Boundary

This document defines exactly what is open and what is not.

## What Is Open (This Repo)

### Kernel Primitives (`kernel/`)
The five constitutional primitives that govern digital labor:

| Primitive | File | Purpose |
|-----------|------|---------|
| Institution | `kernel/organizations.py` | Charter-governed container with lifecycle and policy defaults |
| Agent | `kernel/agent_registry.py` | Identity, scopes, budget, risk state, lifecycle management |
| Authority | `kernel/authority.py` | Approval queues, delegations, kill switch, action rights |
| Treasury | `kernel/treasury.py` | Balance, runway, reserve floor, budget enforcement |
| Court | `kernel/court.py` | Violations, sanctions, appeals, severity-based enforcement |

Supporting modules:
- `kernel/audit.py` — Structured JSONL audit logging
- `kernel/metering.py` — Usage metering per organization and agent
- `kernel/bootstrap.py` — Platform initialization and data backfill
- `kernel/federation_handoff_queue.py` — Remote routing handoff preview queue
- `kernel/payout_plan_preview_queue.py` — Payout dry-run preview queue and operator inspection state
- `kernel/workspace.py` — Owner-facing governed workspace (HTML dashboard + JSON API, including routing and preview snapshots)

### Economy Layer (`economy/`)
The lower layer that kernel primitives compose over:
- `economy/authority.py` — Authority scoring, sprint-lead eligibility, block matrix
- `economy/sanctions.py` — Sanction types, auto-apply/lift rules, restriction checks
- `economy/score.py` — REP/AUTH scoring, treasury deposits/withdrawals
- `economy/auto_score.py` — Automatic agent scoring after delivery cycles
- `economy/revenue.py` — Revenue, external settlement evidence, and support/customer payment recording (module code, not live data)
- `economy/ECONOMY_CONSTITUTION.md` — Three-ledger system rules
- `economy/tests/` — Economy layer tests

### Example Vertical (`examples/intelligence/`)
A concrete example workload running on the kernel:
- `examples/intelligence/ci_vertical.py` — Competitive intelligence pipeline mapped to five primitives
- `examples/intelligence/brief_quality.py` — Output quality gate
- `examples/intelligence/sample-data/` — Repo-local sample artifacts for status, post-mortem, and dry-run scoring
- `examples/intelligence/sample-brief.json` — Sample data

### Documentation and Community
- `README.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`
- `SECURITY.md`, `SUPPORT.md`, `GOVERNANCE.md`, `ROADMAP.md`
- `LICENSE` (Apache-2.0)
- `.github/` issue templates, PR template, funding config

## What Is NOT Open (Remains Private)

### Hosted Service Operations
- MCP server implementation (`mcp_server.py`)
- Telegram delivery pipeline (`channel_deliver.py`, `premium_deliver.py`)
- Subscription management (`subscriptions.py`)
- Payment monitoring (`payment_monitor.py`)
- Trial/email systems (`trial_reminder.py`, `send_email.py`)

### Commercial Business Logic
- Accounting and owner ledger (`accounting.py`)
- Revenue dashboard (`revenue_dashboard.py`)
- Research pipeline with proprietary sources (`research_pipeline.py`, `research_sources.json`)
- Battlecard generation (`battlecard.py`)
- Wallet management (`wallet.py`)

### Credentials and Live Data
- Private keys, wallet files, `.env` files
- Live ledger state (`ledger.json`, `revenue.json`)
- Customer data (`subscriptions.json`, `watchlists.json`)
- Audit logs with production data (`audit_log.jsonl`, `metering.jsonl`)
- Payment event logs

### Internal Company Documents
- Staff playbooks, identity docs, org charts
- Sales kits, pilot runbooks, revenue plans
- Telegram test plans and results
- Night-shift deliverable archives

## Boundary Principle

The kernel is the governance engine. It defines *how* digital labor is governed.
The hosted service is *one deployment* of that engine. It stays private.

A developer can take this kernel and build their own governed institution
without any dependency on the hosted Meridian service.
