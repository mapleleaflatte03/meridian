# Meridian Recovery Runbook

**Date:** 2026-03-20 (updated)
**Status:** Operationally blocked — owner treasury action remaining

---

## What Is Broken

Two blockers currently matter:

1. ~~**OpenAI Codex workspace deactivated**~~ — **RESOLVED** 2026-03-20. Owner refreshed host Codex auth and re-ran Loom route verification. Agent health and the Loom service-state probe now verify cleanly.
2. ~~**Runtime instability**~~ — **RESOLVED AT CLOSEOUT**. Host-level verification now shows `loom health --format json` healthy and `loom service status --format json` reporting a running service probe.
3. **Treasury below reserve floor** — $2.00 cash vs $50.00 reserve floor = $-48.00 runway, blocking all budget-gated pipeline phases

One-command status check:
```bash
cd /home/ubuntu/.meridian/workspace
python3 company/meridian_platform/readiness.py
```

## What Was Repaired (Engineering-Owned)

| Fix | Detail |
|-----|--------|
| Workspace auth hardened | All POST endpoints now enforce `by='owner'` server-side |
| Caddy basicauth | Mutating `/api/*` routes require HTTP Basic Auth |
| Treasury route fixed | `/api/treasury/*` now routes to workspace server (was falling to MCP → 404) |
| MCP paid-tool integrity | All 5 tools have `agent_id`; x402 fails closed; settlement recording now happens post-settlement with durable retry journal |
| Revenue accounting unified | Customer revenue surfaces use `total_revenue_usd`; legacy `revenue_received_usd` removed from the live ledger snapshot |
| Payment email attribution | Empty wallet no longer matches any payment |
| Premium delivery dedup | `brief_date` field for reliable dedup; `record_delivery()` returns success/failure |
| Tests rewritten | `unittest.TestCase` coverage now includes economy integrity plus company money-integrity checks |
| Pipeline bootstrap files | Created `night-shift/BACKLOG.md` and `night-shift/LAST_HANDOFF.md` |
| Caddy credentials | Stored at `/etc/caddy/.workspace_credentials` (mode 0600, `org_id` and `user_id` pinned to founding Meridian owner context) |
| Systemd org binding | `meridian-workspace.service` and `meridian-mcp.service` now have drop-ins under `/etc/systemd/system/*.service.d/org-bind.conf` pinning `org_48b05c21` explicitly |
| Sentinel authority drift | `lift_sanction()` now restores minimum AUTH when lifting `zero_authority`; Sentinel reconciled to AUTH=6 |

## What Still Requires Engineering Work

No active engineering blocker is verified at closeout. The runtime check that was previously
failing now passes on the host:

- `loom health --format json` → healthy
- `loom service status --format json` → running/healthy

The remaining operational blocker is owner-side treasury policy, not engineering breakage.

## What Still Requires Owner Action

### ~~Action 1: Reactivate OpenAI Codex Workspace~~ — DONE

Resolved 2026-03-20. Owner re-ran `refreshed host Codex auth and reran Loom route verification`.
This removed the upstream `deactivated_workspace` blocker and the runtime is now verified
healthy at closeout time.

### Action 2 (sole remaining blocker): Unblock Treasury Gating

**What:** The reserve floor is $50 but treasury only has $2 of owner capital and $0 revenue. Pipeline is correctly blocked.

**Choose one:**

**Option A — Recapitalize (add real money):**
```bash
cd /home/ubuntu/.meridian/workspace
python3 company/meridian_platform/treasury.py contribute \
  --amount 50 --note "operator recapitalization for pipeline restart" --by owner
```
This brings treasury to $52, clearing the $50 floor ($2 runway).

**Option B — Lower reserve floor for pre-revenue mode:**
```bash
cd /home/ubuntu/.meridian/workspace
python3 company/meridian_platform/treasury.py set-reserve-floor \
  --amount 0 --note "pre-revenue operating mode — no external customers yet" --by owner
```
This is a policy decision. It allows the pipeline to run on any treasury balance. Only choose this if you accept that the reserve floor was premature for a pre-revenue system.

**Verify it worked:**
```bash
python3 company/meridian_platform/ci_vertical.py preflight
```
Expected: `PREFLIGHT: OK` with Loom health and service-state probes still healthy

---

## After Treasury Action — Controlled Verification Ladder

Run these in order to confirm the system is fully operational:

```bash
# Step 1: Workspace health
loom service status --format json

# Step 2: Preflight check
cd /home/ubuntu/.meridian/workspace
python3 company/meridian_platform/ci_vertical.py preflight

# Step 3: Dry-run delivery wiring check
python3 company/premium_deliver.py --dry-run --skip-preflight
python3 company/channel_deliver.py --dry-run --skip-preflight

# Current expected result before a fresh brief exists:
# - premium_deliver.py: "No brief available for delivery."
# - channel_deliver.py: "No brief available for channel delivery."
# Treat this as "no brief generated yet", not as proof that delivery is healthy.
# After one successful pipeline cycle creates a fresh brief, rerun these commands.

# Step 4: Trigger one controlled pipeline cycle
loom schedule run-due "7274a600-3588-430d-807c-4286bff20f5a" --timeout 60000

# Step 5: Wait for pipeline to complete (jobs run on schedule)
# Or manually trigger each stage:
loom schedule run-due "50390799-0f7d-4a62-9c88-52e8290d2604" --timeout 120000  # research
loom schedule run-due "c48e2244-e47d-47e7-9bc4-ad053ba4f8c1" --timeout 120000  # write
loom schedule run-due "2581a129-4735-4c3e-a0ec-924689dcda39" --timeout 120000  # qa
loom schedule run-due "25911223-5a4a-44ae-a089-c1d8527e4e58" --timeout 120000  # deliver
```

---

## What "Green" Looks Like

| Check | Expected |
|-------|----------|
| `loom service status --format json` | Agent responds cleanly (no gateway 1006, no embedded timeout) |
| `python3 company/meridian_platform/ci_vertical.py preflight` | `PREFLIGHT: OK` |
| `python3 company/meridian_platform/treasury.py runway` | `Runway: $X.XX` (positive number) |
| `ls night-shift/brief-YYYY-MM-DD.md` | File exists after one pipeline cycle |
| `python3 premium_deliver.py --dry-run --skip-preflight` | Before a fresh brief exists: reports `No brief available for delivery.` After a fresh brief exists: should show dry-run delivery output instead of the no-brief message. |
| `python3 channel_deliver.py --dry-run --skip-preflight` | Before a fresh brief exists: reports `No brief available for channel delivery.` After a fresh brief exists: should show channel dry-run output instead of the no-brief message. |
| Telegram @eggsama_bot `/start` | Bot responds |
| `https://app.welliam.codes/workspace` | Browser prompts for owner auth, then workspace dashboard loads |
| `https://app.welliam.codes/sse` | Returns SSE endpoint event, and the follow-up session POST path under `/messages/` stays reachable on the same origin |

---

## What Is Healthy (Verified 2026-03-20)

- All local services running: caddy, meridian-workspace, meridian-mcp, Loom local control plane
- Website serving at https://app.welliam.codes (200 OK)
- Public MCP boundary serving at https://app.welliam.codes/sse with same-origin `/messages/` session routing
- Workspace dashboard + API: responding after owner auth
- Workspace API endpoints: 401 without owner credentials
- Treasury route: /api/treasury/* correctly proxied to workspace server
- Telegram bot @eggsama_bot: connected and healthy
- Trial reminders: working (2 owner test accounts, expiring 2026-03-23)
- Economy tests: 5/5 passing
- Git repos: clean and pushed after final packaging
- Pipeline bootstrap files: created
- Cron scheduler: enabled, 12 jobs configured
