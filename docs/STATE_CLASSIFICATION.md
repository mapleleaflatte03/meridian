# Meridian State Classification

This document answers one question: **is this file source, runtime, demo, or migration residue?**

Use it before committing to verify you are not accidentally staging runtime-generated state.

---

## Categories

### 1. Source-Controlled Product Files

Code, scripts, templates, documentation, tests, and static web assets that **define product behavior**. Safe to commit. Required in every environment.

Examples:
- All `*.py`, `*.rs`, `*.ts`, `*.toml`, `*.yaml` source files
- `kernel/economy/*.py` (authority, score, sanctions, revenue logic)
- `kernel/economy/ECONOMY_CONSTITUTION.md`
- `docs/**`, `scripts/**`, `tests/**`
- Static frontend assets under `loom/templates/`, `loom/examples/`

---

### 2. Source-Controlled Seed / Baseline State

JSON files that contain **initial baseline values** required to bootstrap the system (e.g. treasury reserve floors, maintainer registry at install time). These are tracked intentionally but must **not accumulate runtime mutations**.

If one of these files changes between two commits, that change must be a deliberate, reviewed baseline update — not a side effect of running the system.

Tracked files in this category:

| File | Purpose |
|------|---------|
| `kernel/economy/ledger.json` | Treasury reserve floors and initial account balances for bootstrap |

**Policy**: If `git diff --cached` shows a change to any file in this category and it was not an intentional baseline update, unstage it.

---

### 3. Runtime-Generated State

Files **created or mutated by running the system** — marketplace bids, court votes and proposals, settlements, memory events, wallet balances, agent configs, subscription records, etc. These files reflect the live state of a running instance.

**These must NEVER be committed.** They are gitignored (see `.gitignore`).

Primary locations:
- `kernel/economy/` — economy runtime state (marketplace, courts, wallets, payments, etc.)
- `loom/agents/` — agent runtime configs and state
- `loom/context/` — runtime context snapshots
- `loom/providers/` — provider connection state
- `loom/state/` — general loom runtime state
- `runtime/` — top-level runtime artifacts
- `output/` — generated output artifacts

Full list of gitignored runtime files in `kernel/economy/`:

```
marketplace.json
court_rule_proposals.json
court_rules.json
court_votes.json
memory_graph.json
contributors.json
maintainers.json
payout_proposals.json
treasury_accounts.json
wallets.json
authority_queue.json
federation_inbox.json
funding_sources.json
payment_events.log
payment_monitor_state.json
payout_plan_preview_queue.json
revenue.json
runtime_budget_reservations.json
settlement_adapters.json
subscriptions.json
subscriptions.json.bak
transactions.jsonl
owner_ledger.json
```

---

### 4. Demo / Maintainer Seed State

Data imported when running with `MERIDIAN_INSTALL_MODE=demo` or `MERIDIAN_INSTALL_MODE=maintainer`. This data is **opt-in only** and is never part of the default user-mode install.

These files may be present locally after running a seeded install. They must not be committed unless they are static fixture files checked into a dedicated `seed/` or `fixtures/` directory that is clearly labeled as demo data.

---

### 5. Migration Artifacts

Legacy references from the OpenClaw era and archived mirror repositories. These exist for historical continuity and permalink stability only.

Documented in [`docs/REPO_MIGRATION_MAP.md`](./REPO_MIGRATION_MAP.md).

Archived mirrors (read-only):
- `https://github.com/mapleleaflatte03/meridian-loom`
- `https://github.com/mapleleaflatte03/meridian-kernel`
- `https://github.com/mapleleaflatte03/meridian-intelligence`

No new code or state should reference these repositories.

---

## Quick-Reference: File Path to Classification

| Path pattern | Classification |
|---|---|
| `kernel/economy/*.py` | Source — product logic |
| `kernel/economy/ECONOMY_CONSTITUTION.md` | Source — governance doc |
| `kernel/economy/tests/` | Source — tests |
| `kernel/economy/ledger.json` | Seed/baseline state — tracked intentionally |
| `kernel/economy/marketplace.json` | Runtime state — gitignored |
| `kernel/economy/court_*.json` | Runtime state — gitignored |
| `kernel/economy/wallets.json` | Runtime state — gitignored |
| `kernel/economy/treasury_accounts.json` | Runtime state — gitignored |
| `kernel/economy/contributors.json` | Runtime state — gitignored |
| `kernel/economy/maintainers.json` | Runtime state — gitignored |
| `kernel/economy/memory_graph.json` | Runtime state — gitignored |
| `kernel/economy/payout_proposals.json` | Runtime state — gitignored |
| `kernel/economy/subscriptions*.json` | Runtime state — gitignored |
| `kernel/economy/transactions.jsonl` | Runtime state — gitignored |
| `kernel/economy/revenue.json` | Runtime state — gitignored |
| `kernel/economy/payment_*.json` | Runtime state — gitignored |
| `kernel/economy/settlement_adapters.json` | Runtime state — gitignored |
| `kernel/economy/authority_queue.json` | Runtime state — gitignored |
| `kernel/economy/federation_inbox.json` | Runtime state — gitignored |
| `kernel/economy/funding_sources.json` | Runtime state — gitignored |
| `kernel/economy/owner_ledger.json` | Runtime state — gitignored |
| `kernel/economy/runtime_budget_reservations.json` | Runtime state — gitignored |
| `kernel/economy/*.db` | Runtime state — gitignored |
| `kernel/economy/*.tmp` | Runtime state — gitignored |
| `loom/agents/` | Runtime state — gitignored |
| `loom/context/` | Runtime state — gitignored |
| `loom/providers/` | Runtime state — gitignored |
| `loom/state/` | Runtime state — gitignored |
| `loom/templates/` | Source — static templates |
| `loom/examples/` | Source — example configs |
| `runtime/` | Runtime state — gitignored |
| `output/` | Runtime state — gitignored |
| `docs/**` | Source — documentation |
| `scripts/**` | Source — tooling scripts |

---

## Release Hygiene Checklist

Before every commit, run:

```bash
git diff --cached --name-only
```

Verify that **none** of the staged files are runtime-generated state. If any appear, unstage them:

```bash
git restore --staged kernel/economy/marketplace.json
# or for multiple files:
git restore --staged kernel/economy/
```

Checklist:

- [ ] No `kernel/economy/*.json` staged except `ledger.json` (and only if it was a deliberate baseline change)
- [ ] No `loom/agents/`, `loom/context/`, `loom/providers/`, `loom/state/` staged
- [ ] No `runtime/` or `output/` staged
- [ ] No `*.db`, `*.db-wal`, `*.db-shm` staged
- [ ] No `*.log` or `*.tmp` staged
- [ ] If `ledger.json` is staged, the change is an intentional bootstrap baseline update and has been reviewed
