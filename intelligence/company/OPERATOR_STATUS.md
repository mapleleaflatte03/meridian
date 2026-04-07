# Operator Status — Meridian

Last updated: 2026-03-25
Evidence base: direct commands and local file inspection (see Evidence column).

This document records the current operational truth of the Meridian system.
It is not promotional copy. Every claim is tagged verified, inferred, or unknown.

---

## System Status at a Glance

| Component | Status | Source |
|-----------|--------|--------|
| Agent runtime | HEALTHY — `loom doctor` OK and the Loom service-state probe verified healthy at closeout; this host remains a single-host Loom proof surface with bounded compatibility paths | `loom health --format json`, `loom service status --format json` |
| Live route ownership | VERIFIED — Meridian-facing MCP execution on this host is Loom-owned or fail-closed; non-Loom route requests are blocked instead of falling back silently | `readiness.py --json`, live route checks |
| Runtime proof receipt | VERIFIED — public `GET /api/runtime-proof` now turns the host's Loom health, canonical Loom service-state probe, runtime inventory, and governed-agent alignment into a structured proof receipt | localhost GET to `http://127.0.0.1:18901/api/runtime-proof` |
| Night-shift pipeline | BLOCKED — treasury $48 below reserve floor | `ci_vertical.py preflight` |
| Constitutional preflight | BLOCKED — treasury $48 below reserve floor | `treasury.py runway` |
| Channel delivery (@MeridianIntelligence) | NOT RUNNING — no new briefs (treasury-blocked) | preflight output |
| Premium delivery (@eggsama_bot) | NOT RUNNING — no new briefs (treasury-blocked) | preflight output |
| Workspace runtime-core surface | VERIFIED — `/api/context` and `/api/status` expose host identity, boundary registry, admission truth, the governed-agent runtime bindings (`agents` plus `agent_runtime_bindings`), and federation-gateway state for founding Meridian | authenticated probes to `http://127.0.0.1:18901/api/context`, `/api/status`, `/api/admission`, and `/api/federation` |
| Public host receipt | VERIFIED — unauthenticated `GET /api/federation/manifest` is the live Loom host proof surface; it returns the founding host's federation manifest and stays honest about `founding_locked` / federation-disabled live state | unauthenticated localhost GET to `http://127.0.0.1:18901/api/federation/manifest` |
| Admission mutation boundary | VERIFIED — live `POST /api/admission/admit` fails closed with `founding_locked` semantics | authenticated localhost POST to `http://127.0.0.1:18901/api/admission/admit` with a non-founding org |
| Settlement verifier gate | VERIFIED — `/api/treasury/settlement-adapters` and `/api/treasury/settlement-adapters/preflight` expose verifier mode, readiness, accepted attestation types, and fail-closed blockers for non-ledger adapters | authenticated localhost GET/POST to the treasury adapter endpoints |
| Trial reminders | Would run for 2 active IDs (owner test accounts) | subscriptions state via founding capsule alias |
| Revenue dashboard | Last OK 2026-03-20 (manually triggered) | `scheduler_truth.py --job revenue-dashboard` |
| External customers | ZERO — all subscription entries are owner test or synthetic residue | subscriptions state via founding capsule alias `_meta` |
| Customer revenue received | $0.00 | founding capsule ledger (`economy/ledger.json` via capsule alias) |
| Owner capital in treasury | $2.00 USDC | founding capsule ledger + transactions.jsonl |
| Reserve floor | $50.00 | founding capsule ledger |
| Runway | $-48.00 (below floor) | `python3 meridian_platform/treasury.py runway` |

---

## Treasury — Verified Facts

**Balance:** $2.00 (owner capital only, no customer revenue — originated as 2.00 USDC on Base L2, recorded as USD in ledger)
**Reserve floor:** $50.00
**Runway:** $-48.00 — treasury is $48 below the reserve floor

**Evidence for the $2.00:**
- founding capsule ledger `economy/ledger.json` (capsule alias for org_48b05c21): `"cash_usd": 2.0`, `"owner_capital_contributed_usd": 2.0`, `"total_revenue_usd": 0.0`
- `economy/transactions.jsonl` (line 35-36): 2.00 USDC received 2026-03-16, initially detected as `customer_payment`, reclassified to `owner_capital` per CLAUDE.md §12 (owner wallet)
- TX hash: `0xde03d0dc2602b815f2bebd3ee7aae005e8a4d3d44fa23c08ba918512c337db93`
- Note in ledger: "Clean treasury. $2 USDC owner capital deposit 2026-03-16 reclassified from customer_payment to owner_capital per CLAUDE.md §12."

**Why the pipeline is still blocked:** The reserve floor of $50 was set when the pipeline was being configured. With only $2 in treasury, the floor blocks all spending. The floor policy needs to be adjusted for pre-revenue operation OR the treasury needs $48+ recapitalization just to clear the reserve gate. That still would not make Meridian automation-ready by itself: automated delivery also waits for customer-backed phase progression and constitutional preflight.

---

## Resolved: Workspace Deactivated (was Blocker 1)

**Status:** RESOLVED 2026-03-20

The `deactivated_workspace` error was caused by upstream OpenAI Codex workspace state.
Owner re-ran `refreshed host Codex auth and reran Loom route verification` and the upstream
`deactivated_workspace` error disappeared. Host-level verification at closeout now
shows `loom doctor` returning OK and the Loom service-state probe succeeding at closeout.
Some embedded state inside `~/.meridian/cron/jobs.json` still carries old
`deactivated_workspace` strings. Treat `jobs.json` as schedule config plus an
embedded last-run cache. Use `company/meridian_platform/scheduler_truth.py` and
the per-job run logs under `~/.meridian/cron/runs/` for scheduler truth instead
of trusting jobs.json state blindly.

---

## Resolved: Runtime Health Re-verified

**Status:** RESOLVED 2026-03-20

Current direct checks pass on the host:
- `loom doctor` → OK
- `loom service status --format json`
  → running/healthy (verified at closeout)

This confirms the runtime is no longer blocked by workspace deactivation and is
healthy enough to remove the engineering runtime blocker from closeout.

---

## Blocker 1 (owner): Constitutional Preflight — Treasury Below Reserve Floor

**Status:** VERIFIED
**Command:** `python3 company/meridian_platform/ci_vertical.py preflight`
**Output (2026-03-20):**
```
BLOCKED: research — budget: Treasury below reserve floor (runway $-48.00)
BLOCKED: write   — budget: Treasury below reserve floor (runway $-48.00)
BLOCKED: qa_sentinel, qa_aegis, execute, compress, deliver, score
PREFLIGHT: BLOCKED — pipeline should not run
```

**Two paths to unblock preflight:**

Option A — Recapitalize treasury:
```bash
python3 company/meridian_platform/treasury.py contribute \
  --amount 50 --note "operator recapitalization" --by owner
```
This brings treasury to $52, which clears the $50 floor ($2 runway).

Option B — Lower the reserve floor to match actual operating level:
```bash
python3 company/meridian_platform/treasury.py set-reserve-floor \
  --amount 0 --note "pre-revenue operating mode" --by owner
```
This is a policy decision. It means the pipeline can run on any treasury balance.
Document the reason. Only the owner should make this call.

**Note:** These commands update the founding treasury state via the live capsule-backed ledger pointer. They are not on-chain.

---

## Blocker 2 (consequence): No Recent Brief Files

**Status:** VERIFIED (consequence of treasury block)

Because the night-shift pipeline has not run since the treasury fell below reserve floor,
there are no brief files at `night-shift/brief-YYYY-MM-DD.md` for recent dates.

Manual pilot delivery requires an existing brief. Without one, premium_deliver.py
and channel_deliver.py have nothing to send.

**Path to unblock:** Resolve the treasury blocker, then allow the pipeline to
run one full cycle.

---

## Sentinel State (Resolved)

**Status:** FIXED 2026-03-20

Sentinel was in `zero_authority` (AUTH=0) due to a bug in `sanctions.py lift()`:
when lifting `zero_authority`, the function cleared the flag but did not restore AUTH.
The `auth_zero` auto-rule then immediately re-sanctioned the agent on the next scoring run,
overwriting the owner's explicit remediation lift from 2026-03-19T14:38:46Z.

**Fix:** `lift_sanction()` now grants AUTH = `auth_decay_per_epoch + 1` when lifting
`zero_authority` if AUTH is 0. This prevents the auto-rule from immediately re-sanctioning.

Sentinel current state: REP=35, AUTH=6, zero_authority=False.
Sentinel can now participate in QA and earn AUTH through normal scoring.

---

## Subscription State

**Status:** VERIFIED via subscriptions state and `_meta` block behind the founding capsule alias

**Active (trial):**
- `6114408283` — owner-controlled internal test account, expires 2026-03-23
- `1053016694` — owner-controlled internal test account, expires 2026-03-23

**Cancelled test residue:**
- test123, verify-test, 999888777, 999000111, 999999999 — all synthetic test entries from 2026-03-16 integration testing

**External customers:** ZERO
**Customer revenue:** $0.00

**Trial reminders (upcoming, for owner test IDs):**
- 2026-03-21: 2-day reminder (inferred — trial_reminder.py will reach these IDs)
- 2026-03-22: 1-day reminder
- 2026-03-23: Expiry-day reminder
These reminders go to owner-controlled accounts. Not funnel activity.

---

## What Can Be Done Without Owner Action

- Run `python3 company/meridian_platform/readiness.py` for a one-command readiness verdict
- Run `python3 company/meridian_platform/ci_vertical.py status` for the current constitutional status map
- Read and inspect all state files
- Run `--dry-run` on any delivery script to see what would be sent
- Improve product surfaces (docs, site copy, architecture docs)
- File court records, review economy ledger
- Run `python3 company/meridian_platform/ci_vertical.py preflight` to get current gate status before a pipeline run

---

## Required Owner Actions (Priority Order)

1. **Resolve the treasury blocker** — choose one:
   - Contribute $48+ to clear the reserve floor, OR
   - Lower the reserve floor for pre-revenue operating mode.
   See command examples in the treasury blocker section above.

2. **Acquire first external customer** — zero external traction exists.
   Manual pilot path is available via email or Telegram DM (see pilot.html).

No tracked public-repo engineering blocker remains at closeout. The remaining
live runtime modules are intentionally founding-service-only, and the system is
currently owner-blocked by treasury policy and, as a consequence, by the
absence of a fresh brief. The latest founding-only service-state update also
made subscriptions and owner-ledger accounting state capsule-canonical, with
company-file compatibility paths kept only as symlink aliases back to the
founding capsule, while payment-monitor state continues to resolve through the
founding capsule boundary instead of hidden singleton file paths.

---

## What Is Healthy (Verified)

- Codebase intact, no corruption
- Agent runtime healthy: `loom doctor` OK and the Loom service-state probe verified healthy at closeout
- Constitutional primitives (institution, agents, authority, court) initialized and enforced
- Website accessible: app.welliam.codes (index.html, pilot.html, demo.html)
- Public Telegram channel @MeridianIntelligence exists
- Bot @eggsama_bot exists and can accept /start commands
- GitHub repo mapleleaflatte03/meridian-intelligence is public
- OSS kernel mapleleaflatte03/meridian-kernel is public (Apache-2.0)
- x402 payment infrastructure is code-complete (unproven against real external customer)
- $2.00 USDC owner capital on record in treasury

---

## Delivery Architecture

See `DELIVERY_ARCHITECTURE.md` in this directory for the full Telegram channel/bot/premium model.

Subscription state is now capsule-canonical for the founding org. The
`company/subscriptions.json`, `subscriptions.json.bak`, and
`.subscriptions.lock` paths are compatibility symlinks back to the founding
capsule files rather than the other way around.

---

## STATUS DOC RULES — Anti-Regression Guardrail

These rules apply to this document and any future operator status docs:

1. **Every financial claim must cite a source file or command.**
   Wrong: "Treasury is $0."
   Right: "Treasury cash_usd=2.0 per founding capsule ledger (`economy/ledger.json` via capsule alias), total_revenue_usd=0.0."

2. **Every command example must be tested before publication.**
   Wrong: `treasury.py deposit --amount 50` (command does not exist)
   Right: `treasury.py contribute --amount 50 --note "..." --by owner` (verified via --help)

3. **Repo visibility claims must be confirmed by direct check, not assumed.**
   Check `gh repo view <repo> --json isPrivate` or inspect the repo directly.

4. **Every unverified claim must be labeled `[inferred]` or `[unknown]`.**
   Do not write confident prose for things you have not directly checked.

5. **Status docs are not promotional copy.**
   If something is broken, say it is broken and state the exact reason.
   Softening operational failures misleads operators and creates rework.
