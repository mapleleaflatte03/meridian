# Meridian Constitutional Kernel — Launch Distribution Pack

Prepared 2026-03-20. All copy is ready-to-post pending owner review.

---

## 1. Canonical Launch Narrative

### The Story (for any context where you need to explain what this is)

We run a self-hosted AI company. Not a demo — a company with a manager, six staff agents, budgets, sanctions, and a nightly delivery pipeline.

We kept hitting the same problem: agents can do things, but there's no standard way to decide whether they *should*. Most teams either trust the prompt or build one-off permission checks. Neither scales past a few agents.

So we built a governance kernel. Five primitives — Institution, Agent, Authority, Treasury, Court — that sit between any agent runtime and production. Agents earn reputation through accepted work. They gain temporary authority from recent output. They spend real budget under treasury constraints. When they fail, the court system applies sanctions. When they recover, there's a remediation path back.

It's 40 files, ~7000 lines, pure Python stdlib, zero dependencies. We extracted it from our production system, scrubbed the private data, and open-sourced it under Apache-2.0.

It doesn't run your agents. It governs them. Plug it into whatever you already use.

### What makes it different (the honest version)

Most "AI governance" is either academic (papers about alignment) or cosmetic (a permissions check bolted onto a chatbot framework).

This is operational governance. It came from running agents that spend money and produce deliverables on a schedule. The court system exists because agents failed in production and we needed a way to sanction them, track recovery, and restore trust. The treasury exists because agents spent budget and we needed enforcement before the run, not an invoice after.

None of this is theoretical. It's extracted from a running system.

### What it does NOT claim

- It is not production-hardened by thousands of users. It's extracted from one company's production use.
- It is not a complete agent platform. It's the governance layer only.
- It does not have a large community yet. It's a new open-source release.
- The economy layer has not processed real external payments. Treasury accounting exists; customer revenue does not.
- The workspace dashboard is a reference implementation, not a polished product.

---

## 2. GitHub-Facing Copy Pack

### Repository Tagline (one line, under 100 chars)

```
Governance primitives for AI agents. Five primitives, pure Python, zero deps.
```

### Repository Description (GitHub "About" section, under 350 chars)

```
Constitutional kernel for governed digital labor. Five primitives — Institution, Agent, Authority, Treasury, Court — compose over a three-ledger economy (reputation, authority, cash). Extracted from a production AI company. Pure Python stdlib, no dependencies. Apache-2.0.
```

### Repository Topics (GitHub tags)

```
ai-governance, ai-agents, constitutional-ai, agent-framework, python,
multi-agent, governance, treasury, sanctions, open-source
```

### "Who This Is For" (for README or landing page)

**Use Meridian if you:**
- Run AI agents that spend money, call APIs, or produce work product
- Need governance beyond "trust the prompt" but don't want to build it from scratch
- Want agents to have identity, budgets, authority, and accountability
- Need a kill switch, approval queues, or sanction enforcement
- Want to separate governance from your agent runtime (use any runtime you want)

**Don't use Meridian if you:**
- Need a chatbot framework (use LangChain, CrewAI, etc.)
- Want an agent runner or execution environment (Meridian doesn't run agents)
- Need a database-backed enterprise platform today (file-based state, planned for v0.4)
- Want a mature ecosystem with hundreds of integrations (this is new)

---

## 3. Contributor Call

### For Developers

We need help with kernel primitives, the economy layer, and storage backends.

**Immediate needs:**
- Test coverage for all five kernel primitives (court.py and authority.py especially)
- SQLite storage backend as alternative to JSON files
- Input validation and edge case hardening
- CLI improvements (better error messages, help text, tab completion)

**Bigger projects:**
- PostgreSQL storage backend
- Event system for primitive state changes (hooks when sanctions apply, budgets exhaust, etc.)
- Prometheus/OpenTelemetry metrics exporter for kernel state

**Requirements:** Python 3.9+, stdlib only for core kernel. Storage backends may use their driver library.

### For Designers

The governed workspace (`kernel/workspace.py`) serves a functional but plain HTML dashboard. It needs design work.

**Needs:**
- Dashboard layout that surfaces the five primitives clearly
- Visualization for agent reputation/authority over time
- Court violation timeline view
- Treasury runway indicator (visual budget health)
- Mobile-responsive layout

The dashboard is pure HTML/CSS/JS served from stdlib `http.server`. No build step, no framework — keep it simple.

### For Documentation Writers

**Needs:**
- Tutorial: "Govern your first agent workflow in 30 minutes"
- Guide: "Mapping your existing pipeline onto five primitives"
- API reference for all kernel CLI commands
- Economy layer explainer with worked examples
- Comparison guide: "How Meridian relates to [LangChain/CrewAI/Autogen]"

### For Infrastructure / Security

**Needs:**
- Security review of file-based state management (race conditions, permissions)
- Hardening guide for production deployments
- Backup/restore procedures for state files
- Rate limiting and abuse prevention for the workspace API
- Threat model for multi-agent governance (agent spoofing, privilege escalation)

### For Vertical / Workflow Builders

The `examples/intelligence/` directory shows one vertical. We want more.

**Example verticals we'd love to see:**
- Code review pipeline (agents review PRs with budget-gated LLM calls)
- Content moderation workflow (agents flag/review with court accountability)
- Data pipeline governance (agents process data with treasury-enforced cost caps)
- Customer support escalation (agents handle tickets with authority delegation)
- Research synthesis (agents research and write with reputation-gated acceptance)

Each vertical should show how the five primitives apply to a real workflow. See `examples/intelligence/README.md` for the pattern.

---

## 4. Sponsor Call

### Primary: GitHub Sponsors

Meridian is independently maintained. No VC funding, no corporate sponsor, no foundation.

Sponsors help fund:
- **Kernel development** — five primitives, economy layer, storage backends
- **Security audits** — the governance layer must be trustworthy
- **Infrastructure** — CI, hosting for docs, community tooling
- **Maintainer time** — reviewing PRs, triaging issues, writing docs

Sponsor tiers are configured through [GitHub Sponsors](https://github.com/sponsors/mapleleaflatte03).

### Secondary: Crypto (Optional)

For sponsors who prefer stablecoin, see the wallet registry in
[`treasury/wallets.json`](../treasury/wallets.json) for verified wallet
addresses. All crypto contributions are governed by the
[Contributor Treasury Protocol](treasury/CONTRIBUTOR_TREASURY_PROTOCOL.md).

This is supplementary. GitHub Sponsors is the primary path because it provides transparency, recurring support, and community visibility.

### What sponsors do NOT get

- No special access to the kernel (it's all Apache-2.0)
- No priority on the roadmap (features land based on technical merit)
- No "enterprise tier" governance (yet — if demand appears, we'll consider it)

Sponsorship supports the project's existence. The project serves everyone equally.

---

## 5. Social Launch Pack

### X (Twitter) — Thread Format

**Tweet 1 (hook):**
```
We open-sourced the governance kernel we built to run our AI company.

Five primitives. Pure Python. Zero dependencies.

Institution · Agent · Authority · Treasury · Court

→ github.com/mapleleaflatte03/meridian-kernel
```

**Tweet 2 (the problem):**
```
The problem: if you run AI agents in production, governance is either
"trust the prompt" or a custom one-off permission system per tool.

Neither scales past a few agents.
```

**Tweet 3 (what it does):**
```
Meridian gives agents real identity, real budgets, and real consequences.

- Authority checks before every action
- Treasury budget gates before every spend
- Court sanctions when agents fail
- Remediation path when they recover
- Kill switch when you need to stop everything

All file-based. No database. No deps.
```

**Tweet 4 (try it):**
```
git clone → python3 quickstart.py → governed workspace running

Took us longer to write this thread than it takes to try it.

Apache-2.0. Contributions welcome.
```

---

### Reddit — r/MachineLearning, r/LocalLLaMA, r/Python

**Title:** `Meridian Constitutional Kernel — open-source governance primitives for AI agents (pure Python, no deps)`

**Body:**
```
We've been running a self-hosted AI company with a manager agent and six
staff agents. The agents research, write, QA, and deliver output on a
nightly schedule.

The part that was hardest to get right wasn't the agents — it was
governing them. Who can do what. How much they can spend. What happens
when they fail. How they recover.

We extracted the governance layer into a standalone kernel and
open-sourced it. Five primitives:

- **Institution** — charter, lifecycle, policy defaults
- **Agent** — identity, scopes, budget, risk state
- **Authority** — approval queues, delegations, kill switch
- **Treasury** — balance, runway, reserve floor, budget enforcement
- **Court** — violations, sanctions, appeals, remediation

It composes over a three-ledger economy: reputation (trust), authority
(temporary power), and cash (real money). These are deliberately separate —
collapsing them into one token creates wrong incentives.

~7000 lines, pure Python stdlib, zero external deps. JSON file state.
`python3 quickstart.py` gets you a running demo with a web dashboard.

Not an agent runner. Not a chatbot framework. Just the governance layer.
Plug it into whatever runtime you use.

Apache-2.0: github.com/mapleleaflatte03/meridian-kernel

Happy to answer questions about the design or how it works in practice.
```

---

### Hacker News

**Title:** `Show HN: Governance primitives for AI agents – five primitives, pure Python, no deps`

**Body:**
```
We run a self-hosted AI company — manager agent, six staff, nightly
pipeline. We kept building governance ad-hoc: permission checks here,
budget gates there, a sanctions system after an agent wasted budget.

Eventually we factored it into five primitives: Institution, Agent,
Authority, Treasury, Court. Together they form a constitutional kernel
that sits between your agent runtime and production.

Key design decisions:

1. Three-ledger economy (REP/AUTH/CASH) instead of one token. Reputation
   is non-transferable trust. Authority is temporary power that decays.
   Cash is real money. Collapsing these creates wrong incentives.

2. Composition, not rewrite. Kernel primitives import from the economy
   layer. authority.py (kernel) composes over authority.py (economy)
   using importlib to avoid name collisions.

3. File-based state. JSON/JSONL on disk. No database required. Easy to
   inspect, backup, version. Storage backends planned for v0.4.

4. Kill switch as a first-class primitive. One command halts all
   non-owner agent actions.

5. Remediation path. Sanctions aren't permanent. Agents can recover
   trust through the court system.

~7000 lines, pure Python stdlib, zero deps. Apache-2.0.

  git clone ... && python3 quickstart.py

github.com/mapleleaflatte03/meridian-kernel
```

---

### LinkedIn

```
We open-sourced the governance kernel from our AI company.

Context: we run AI agents in production — they research, write, QA, and
deliver output on a daily schedule. The hard part isn't building agents.
It's governing them.

Meridian Constitutional Kernel provides five primitives:

→ Institution (charter-governed containers)
→ Agent (identity, budgets, risk state)
→ Authority (approval queues, delegations, kill switch)
→ Treasury (real money tracking with enforcement)
→ Court (violations, sanctions, appeals, remediation)

It's the layer between "agents that can do things" and "agents that
should be trusted to do things."

Pure Python, no dependencies, Apache-2.0.

If you're deploying AI agents into workflows where they spend budget,
make decisions, or produce work product — you need governance primitives,
not just prompts.

Link in comments.
```

---

### Facebook

```
Dropped an open-source project today.

Meridian Constitutional Kernel — governance for AI agents.

Short version: if you have AI agents that spend money or make decisions,
you need more than prompt engineering. You need real identity, real
budgets, real consequences, and a kill switch.

We built this for our own AI company (yes, a company run by AI agents
with real roles and real accountability). Extracted the governance layer
and made it open-source.

Five building blocks. Pure Python. No dependencies. One command to try it.

Apache-2.0 license — use it however you want.

github.com/mapleleaflatte03/meridian-kernel
```

---

### Threads

```
Open-sourced the governance kernel from our AI agent company today.

Five primitives: Institution, Agent, Authority, Treasury, Court.

Agents earn reputation through work. They gain temporary authority. They
spend real budget under treasury gates. When they fail, the court system
sanctions them. When they recover, there's a path back.

Pure Python. Zero deps. One command to try.

Not a chatbot framework. Not an agent runner. Just governance.

github.com/mapleleaflatte03/meridian-kernel
```

---

### VOZ (Vietnamese)

```
Mình vừa open-source cái governance kernel cho AI agent.

Context: mình đang chạy một công ty AI tự host — có manager agent, 6
agent nhân viên, pipeline chạy hàng đêm. Phần khó nhất không phải build
agent, mà là quản trị chúng.

Meridian Constitutional Kernel có 5 primitive:

→ Institution — tổ chức có charter và policy
→ Agent — danh tính, scope, budget, trạng thái rủi ro
→ Authority — hàng đợi phê duyệt, delegation, kill switch
→ Treasury — theo dõi tiền thật với budget enforcement
→ Court — vi phạm, chế tài, kháng cáo, remediation

Kiến trúc 3 sổ cái riêng biệt: REP (uy tín), AUTH (quyền lực tạm thời),
CASH (tiền thật). Tách riêng 3 cái này thay vì gộp thành 1 token —
tránh agent optimize sai thứ.

~7000 dòng, pure Python stdlib, không dependency nào. JSON file state.
Chạy `python3 quickstart.py` là có demo với web dashboard.

Apache-2.0. Ai cần governance layer cho AI agent thì dùng được luôn.

github.com/mapleleaflatte03/meridian-kernel

Có gì hỏi mình.
```

---

## 6. Image Assessment and Recommendation

### Full Assessment

| Image | Description | Text Quality | Framing | Verdict |
|-------|-------------|--------------|---------|---------|
| `logo.png` | Clean "M" monogram, teal on dark | Perfect (no text) | Neutral, professional | **Use as logo/favicon** |
| `8a7yq8` | Five primitives on circular platform, server room | Labels readable, floor text has artifacts | Good — shows primitives as architectural elements | Viable backup |
| `9xitt9` | Isometric layered diagram | Garbled descriptions ("Complex rainitwoads...") | Good concept, bad execution | **Do not use** |
| `bipr3y` | Dark variant of 8a7yq8 | Floor text "MERIDIAN CONSTITUTION" broken | Similar to 8a7yq8 but darker | Skip (8a7yq8 is better) |
| `czy8qq` | Cyberpunk woman with holographic globe | Some HUD text | Wrong — over-indexes on intelligence vertical | **Do not use** |
| `dmtfw1` | Renaissance painting style | "USDC" and "x402" visible | Wrong — too inside-baseball, theatrical | **Do not use** |
| `nj4loan` | Grand hall with primitive pillars/tubes | Labels clean | Dramatic but readable | Viable backup |
| `ovkumo` | Five pillars with flowing connections, "Basic AI Workflows" as chaotic gears below | Text artifacts ("Ubiest constitutional...") | **Best concept** — shows kernel as structured layer above messy workflows | **Top pick if text fixed** |
| `s2p73i` | Cyberpunk woman with HUD, "COMPETITOR A: ALERT DETECTED" | HUD text readable | Wrong — surveillance aesthetic, intelligence-vertical specific | **Do not use** |
| `tx6kr7` | Comic book style, five numbered panels, robot character | Text mostly clean | Fun but too casual for serious OSS launch | Not recommended |

### Recommendation

**GitHub Social Preview (1280x640):**

1. **Primary choice: `ovkumo`** — if the text artifacts can be fixed (re-generate or edit out "Ubiest constitutional operating system" → clean label or no subtitle). The visual concept — five labeled pillars (AGENT, TREASURY, COURT, AUTHORITY, INSTITUTION) with structured connections above a chaotic gear layer — is exactly the right metaphor. It communicates "governance layer that brings order to messy agent workflows" in one image.

2. **Fallback: `logo.png`** — the clean monogram works as a safe, professional social preview. Doesn't explain anything but looks credible. Better than shipping a broken-text image.

3. **Alternative: `8a7yq8`** — the circular platform with five primitives in a server room. Readable labels, architectural feel. Slightly generic but clean enough.

**Do not use:** `czy8qq`, `s2p73i` (wrong framing — intelligence vertical, not kernel), `dmtfw1` (too theatrical, inside-baseball), `9xitt9` (garbled text), `tx6kr7` (too casual).

### Social Preview Image Brief (for designer or re-generation)

If generating a new image:
- **Format:** 1280x640, high contrast for small thumbnails
- **Concept:** Five labeled columns/pillars (Institution, Agent, Authority, Treasury, Court) connected by structured lines. Below: chaotic/messy node graph representing ungovern ed workflows. Above: clean, ordered output.
- **Text:** "Meridian Constitutional Kernel" top-left. No subtitle. No tagline (it gets cut off in thumbnails).
- **Style:** Technical diagram aesthetic, dark background, teal/blue accent color matching logo.png. Not cyberpunk. Not comic book. Not renaissance.
- **Do not include:** Agent characters, people, globes, city skylines, "AI" spelled out, ticker symbols, company-specific references.

---

## 7. FAQ

### Q: What is the Meridian Constitutional Kernel?

Five composable governance primitives — Institution, Agent, Authority, Treasury, Court — that sit between your agent runtime and production. It's the layer that enforces identity, budgets, authority, and accountability for AI agents. Pure Python stdlib, no external dependencies, Apache-2.0 licensed.

### Q: How is this different from LangChain, CrewAI, or AutoGen?

Those are agent runtimes — they run agents. Meridian governs them. LangChain decides what tools an agent can call and how. Meridian decides whether the agent has authority to act, budget to spend, and what happens when it fails. You can use Meridian with any of those runtimes. It's a different layer.

### Q: What does "constitutional" mean here?

An institution has a charter (its founding purpose and rules). Agents operate under that charter. Authority is granted and revoked through defined mechanisms. Violations are adjudicated through the court primitive. "Constitutional" means governance through explicit, inspectable rules — not through prompt engineering or implicit trust.

### Q: Does this run my agents?

No. Meridian doesn't execute agent code, manage LLM calls, or handle tool routing. It provides governance checks that your runtime calls: `check_authority()` before an action, `check_budget()` before a spend, `file_violation()` after a failure. Your runtime stays yours.

### Q: Is this production-ready?

It's extracted from a production system and works. But it has one deployment (ours), file-based state, and no large-scale stress testing. Use it if the primitives match your needs and you're comfortable with the maturity level. We use it daily. Whether that's enough for your context depends on your context.

### Q: Why three separate ledgers instead of one token?

If one token represents trust, power, and money simultaneously, agents optimize the token instead of optimizing value creation. REP (reputation) is non-transferable trust earned from accepted work. AUTH (authority) is temporary power that decays every epoch. CASH (treasury) is real money that only enters from owner capital or customer payments. Keeping them separate creates correct incentives: do good work (earn REP), do recent good work (earn AUTH), get paid for real value (earn CASH).

### Q: Why file-based state instead of a database?

Zero-dependency quickstart. You can inspect state with `cat`, back it up with `cp`, and version it with `git`. For a governance kernel that needs to be trustworthy, transparency matters more than throughput. SQLite and PostgreSQL backends are planned for v0.4 when scale requires it.

### Q: What's the commercial model?

The kernel is fully open-source (Apache-2.0) and always will be. The hosted Meridian service — delivery pipelines, payment processing, customer management — is closed-source. Open core: the governance layer is open, the product built on it is commercial. You can build your own product on the same kernel.

---

## 8. What Still Needs Owner Approval Before Launch

### Must-do (blocks launch)

- [ ] **Review the kernel repo** — owner hasn't audited the 40 files yet. Must confirm no private data leaked, no unwanted code exposed.
- [x] **Repo is PUBLIC** — `mapleleaflatte03/meridian-kernel` is public. No action needed.
- [ ] **Set up GitHub Sponsors** — FUNDING.yml points to `mapleleaflatte03` but Sponsors profile doesn't exist yet. Go to github.com/sponsors/mapleleaflatte03 → set up profile.

### Should-do (before first social posts)

- [ ] **Choose social preview image** — pick from `ovkumo` (if text gets fixed), `logo.png` (safe fallback), or `8a7yq8`. Upload at repo Settings → Social preview.
- [ ] **Review social copy** — all 7 platform posts in section 5 above. Approve, edit, or reject each.
- [ ] **Decide on crypto wallet in sponsor call** — the truncated wallet `0x8200...7761` appears in section 4. Owner must confirm whether to include it publicly or remove.
- [x] **Fix CONTRIBUTING.md Python version** — resolved, both README and CONTRIBUTING.md now say Python 3.9+.

### Nice-to-have (can happen after launch)

- [ ] **Create initial GitHub Issues** — seed `good first issue` and `help wanted` labels with 5-10 starter issues
- [ ] **Reddit/HN accounts** — owner posts from their own accounts (not agent accounts)
- [ ] **VOZ post** — owner posts in Vietnamese from their account
- [ ] **GitHub Discussions enabled** — turn on Discussions tab in repo settings

### Timeline suggestion

1. Owner reviews repo + this pack (today)
2. Owner sets up GitHub Sponsors (same day)
3. Owner uploads social preview image
5. Owner posts to platforms in preferred order (HN and Reddit first for developer traction, LinkedIn for professional reach, VOZ for Vietnamese community)
6. Seed initial issues within 48 hours of launch
