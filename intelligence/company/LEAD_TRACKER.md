# Meridian Lead Tracker

Minimal founder sales cockpit for zero-spend outreach.

State lives in:
- `company/leads.json` — local, ignored, safe for real lead data
- `company/leads.json.sample` — tracked schema example

CLI:
```bash
cd /root/.meridian/workspace

python3 company/lead_tracker.py init
python3 company/lead_tracker.py summary
python3 company/lead_tracker.py add \
  --name "Jane Doe" \
  --company "Acme AI" \
  --role "PMM" \
  --source "LinkedIn" \
  --contact-channel "telegram" \
  --contact-handle "@jane" \
  --priority 5 \
  --fit-score 4 \
  --next-action "Send demo link"
python3 company/lead_tracker.py list --active-only
python3 company/lead_tracker.py next
python3 company/lead_tracker.py set-stage --lead lead_xxxxxxxx --stage contacted --next-action "Wait 3 days, then follow up"
python3 company/lead_tracker.py note --lead lead_xxxxxxxx --text "Asked whether Telegram is required" --next-action "Send pilot page"
```

## Stage meanings

- `new` — not contacted yet
- `contacted` — first message sent
- `replied` — prospect responded
- `scoping` — discussing competitors, topics, or fit
- `pilot_active` — founder-led pilot running
- `waiting_feedback` — pilot delivered, waiting for verdict
- `negotiating` — discussing paid continuation
- `won` — paid continuation started
- `lost` — explicitly closed or not worth chasing

## Rules

- Keep real lead data in `company/leads.json`, not in git.
- Do not mark `pilot_active` until the pilot actually starts.
- Do not mark `won` until real payment is received or a real paid commitment is confirmed.
- Before promising automated daily delivery, run:

```bash
python3 company/meridian_platform/readiness.py
```

If verdict is `OWNER_BLOCKED_TREASURY`, keep the lead in manual-pilot mode.
