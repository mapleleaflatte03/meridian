# Meridian Constitutional Kernel — Launch Post

*Superseded by [LAUNCH_PACK.md](LAUNCH_PACK.md) which has platform-specific
copy for X, Reddit, HN, LinkedIn, Facebook, Threads, and VOZ.*

*For posting on HN, Reddit, dev communities. Adjust tone per platform.*

---

**Meridian Constitutional Kernel: Governance primitives for AI agents**

We're open-sourcing the constitutional kernel we built to govern our own
AI agent company.

**The problem:** AI agents are getting deployed into production — spending
money, making decisions, producing work product. Most governance is either
"trust the prompt" or custom one-off permission systems.

**What this is:** Five composable primitives that sit between your agent
runtime and production:

- **Institution** — charter-governed container with lifecycle
- **Agent** — first-class identity with scopes, budget, risk state
- **Authority** — approval queues, delegations, kill switch
- **Treasury** — real money tracking with runway and budget enforcement
- **Court** — violations, sanctions, appeals, remediation

Agents earn reputation through accepted work, gain temporary authority,
and spend real budget under treasury constraints. When they fail, the
court system applies sanctions. When they recover, there's a remediation
path back.

**What it's not:** This is not a chatbot framework, not an agent runner,
not a marketplace. It's the governance layer. Plug it into whatever
agent runtime you use.

**Try it:**
```
git clone ... && python3 quickstart.py
```
Pure Python stdlib, no dependencies, under 10 minutes to a running demo.

Apache-2.0 licensed.

---

## Short description (for repo/social)

Open-source kernel for governed digital labor. Five primitives:
Institution, Agent, Authority, Treasury, Court. Pure Python, no deps.

## Hero line

Governance primitives for AI agents that spend money, make decisions,
and produce real work.

## Contributor call

We're looking for contributors interested in:
- Building new example verticals (your workflow on our kernel)
- Improving the governed workspace UI
- Adding storage backends (SQLite, PostgreSQL)
- Writing tests for kernel primitives
- Security review and hardening

No CLA. Apache-2.0 inbound = outbound. Good first issues labeled
in the issue tracker.

## Sponsor call

Meridian is independently maintained. Sponsors help fund kernel
development, security audits, and community infrastructure.
GitHub Sponsors is the primary path.
