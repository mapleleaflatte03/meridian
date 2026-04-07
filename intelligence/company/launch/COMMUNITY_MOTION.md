# Meridian Community Motion

This lane converts community growth into repeatable operator execution, not ad-hoc posting.

## What this adds

- A recurring weekly update payload pulled from live Meridian status/proof routes.
- Optional Discord publish via webhook (`MERIDIAN_DISCORD_WEBHOOK_URL`).
- Persistent run artifacts for audit/history in `company/launch/artifacts/`.

## Runbook

Dry-run (safe default):

```bash
python3 company/launch/community_ops.py --dry-run
```

Live publish to Discord:

```bash
export MERIDIAN_DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
python3 company/launch/community_ops.py
```

Output artifact:

- `company/launch/artifacts/community_ops_latest.json`

## Operator cadence

- Monday: publish weekly runtime/proof summary.
- Wednesday: publish incident/fix follow-up if any degraded status is detected.
- Friday: publish ship log + next-week priorities.

## Safety boundary

- This script never posts to X/Reddit/HN APIs directly.
- External social posting remains manual-owner action unless explicit credentials and automation policy are provided.
