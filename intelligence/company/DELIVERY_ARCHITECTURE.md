# Meridian Delivery Architecture

Last updated: 2026-03-20

---

## Current Delivery Model

The Meridian Telegram system has four distinct surfaces.
They are not interchangeable, and only one of them is the current customer path.

### 1. Founder-led manual pilot

**Role:** Current customer delivery path.

- New teams are onboarded through a founder-led manual pilot.
- Delivery happens directly from the founder to the pilot team, usually over Telegram.
- This is the only honest customer path while treasury-gated automation remains paused.
- It uses the same category of governed output, but does not pretend the automated loop ran when it did not.

### 2. @MeridianIntelligence (channel)

**Role:** Public preview surface.

- Broadcast only. No subscriber interaction.
- Used for public previews when there is a fresh brief worth posting.
- Managed by `channel_deliver.py`.
- Explicit operator action today, not a daily or weekly delivery promise.

**Who sees it:** Public. Discovery and proof-of-output surface.

### 3. @eggsama_bot (subscriber bot)

**Role:** Internal test surface now; future subscriber lifecycle surface later.

- The bot remains a valid technical surface, but it is not the current public onboarding promise.
- The two active bot subscriptions today are owner-controlled internal tests.
- `premium_deliver.py` and `trial_reminder.py` still exercise this path for internal verification only.
- Once treasury policy allows honest automated delivery again, this bot can resume lifecycle and direct-delivery duties.
- Subscription state is still founding-service-only, but now resolves through the founding institution's capsule alias rather than a free-floating singleton path.

**Who uses it today:** Owner-controlled internal test accounts only.

### 4. Owner Telegram (5322393870)

**Role:** Operator control surface. Morning brief delivery. System alerts.

- `night-shift-deliver` sends the full morning brief to the owner when the pipeline is clear.
- `revenue-dashboard` reports weekly to the owner.
- This is a private operator channel, not a customer surface.

---

## Delivery Flow (Current Truth)

```
Night-shift pipeline
│
├── If constitutional preflight is BLOCKED
│     → no automated customer delivery should happen
│     → no brief should be pretended into existence
│
├── If a fresh brief exists and the founder is running a manual pilot
│     → founder sends the output manually to pilot participants
│
├── If a fresh brief exists and the public preview is intentionally posted
│     → channel_deliver.py can post an abbreviated preview to @MeridianIntelligence
│     → this is not currently guaranteed by cron
│
├── If treasury policy and preflight later allow automated delivery again
│     → premium_deliver.py can resume bot/private DM delivery
│     → @eggsama_bot becomes the active subscriber lifecycle surface again
│
└── trial_reminder.py
      → currently an internal lifecycle-check path for test accounts
      → not the primary public customer path
```

---

## Constitutional Preflight in Delivery

Both `channel_deliver.py` and `premium_deliver.py` call `ci_vertical.py preflight`
before any automated delivery attempt. If preflight returns non-zero, automated
delivery is blocked.

Preflight blocks when:
- Treasury balance below reserve floor (currently $48.00 below floor)
- Kill switch engaged
- Agent authority blocked

This is by design. Uncontrolled spend requires treasury funding. Manual founder
delivery does not claim that the automated loop ran; `--skip-preflight` is only
for explicit operator recovery/testing, not for pretending automated customer
delivery succeeded.

---

## Surface Summary

| Surface | Current role | Audience | Interaction | Current truth |
|---------|--------------|----------|-------------|---------------|
| Founder manual pilot | Real customer delivery path | Pilot teams | Direct | Active when the founder chooses to run a pilot |
| @MeridianIntelligence | Public preview | Public | None (broadcast) | Optional / manual posting; not a standing delivery promise |
| @eggsama_bot | Internal test + future subscriber lifecycle | Owner test accounts today | Yes — commands | Not the active public onboarding promise |
| Owner DM (5322393870) | Operator brief + alerts | Owner only | None | Active when pipeline clears |

---

## Current Operational Truth (2026-03-20, updated)

See `OPERATOR_STATUS.md` for the full breakdown of what is blocked and why.

Short version:
- `deactivated_workspace` is resolved and current host-level runtime checks are healthy.
- Constitutional preflight is blocked by treasury shortfall ($-48 vs reserve floor).
- No recent brief files exist because the pipeline has not run since the treasury block.
- The two "active" bot subscriptions are owner-controlled internal tests, not customers.
- No external customers exist. No external automated deliveries have occurred.
- `channel_deliver.py` is not on a deterministic cron schedule and should be treated as an explicit preview-post action.
- The honest customer path right now is founder-led manual pilot delivery, not bot trial automation.

**Brief source of truth:** `night-shift/brief-YYYY-MM-DD.md` files. Both
`channel_deliver.py` and `premium_deliver.py` use `get_today_brief()` which checks
today's date first, then falls back to the most recent brief file.
