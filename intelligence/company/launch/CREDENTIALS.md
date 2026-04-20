# Publish-Live-Real Credentials

Eight environment variables gate `acceptance_publish_live_real_lane.sh`. The
lane fails loudly with the missing-key list when any is unset — it never
simulates or mocks a real publish. This file is the operator handbook for
obtaining and setting them.

Use `.env.publish.example` (in this folder) as a fill-in template. Copy it,
rename it `.env.publish`, set values, then `source .env.publish` before
running the real lane.

## Credentials

| Env var | Provider | Where to obtain | Scope / notes |
|---|---|---|---|
| `MERIDIAN_X_API_TOKEN` | X (Twitter) | developer.x.com → create app → generate Bearer token | Requires posting permission on the account used. |
| `MERIDIAN_REDDIT_CLIENT_ID` | Reddit | reddit.com/prefs/apps → create "script" app → top-left ID string | Distinct from the username. |
| `MERIDIAN_REDDIT_CLIENT_SECRET` | Reddit | Same app page as CLIENT_ID → "secret" field | Rotate if leaked. |
| `MERIDIAN_REDDIT_USERNAME` | Reddit | Posting account username | Must own the script app. |
| `MERIDIAN_REDDIT_PASSWORD` | Reddit | Posting account password | App-specific password if 2FA is on. |
| `MERIDIAN_HN_USERNAME` | Hacker News | news.ycombinator.com posting account | Account must be old enough to post without rate-limit penalties. |
| `MERIDIAN_HN_PASSWORD` | Hacker News | Same account password | No API token — the publisher uses form auth. |
| `MERIDIAN_DISCORD_WEBHOOK_URL` | Discord | Server settings → Integrations → Webhooks → New Webhook → Copy URL | Channel-scoped. Regenerate the webhook rather than editing it if rotated. |

## Pre-flight

Before the first real publish:

1. Dry run: `./scripts/acceptance_publish_live_lane.sh`
   — must pass without any credentials. Proves the orchestration shape.
2. Fill the 8 values into `.env.publish` (copy of `.env.publish.example`).
3. `source intelligence/company/launch/.env.publish`
4. Real run: `./scripts/acceptance_publish_live_real_lane.sh`
   — must print `status: posted` on every configured channel.
5. Artifact check: `intelligence/company/launch/artifacts/publish_live_latest.json`.

## Never do

- Do not commit `.env.publish` or any populated `.env*` file. The example
  template in this folder is the only file with these key names that belongs
  in the repo.
- Do not add `MERIDIAN_ALLOW_API_SKIP=1` to paper over a missing credential.
  A skipped channel is not a posted channel.
- Do not mock the real lane — `acceptance_publish_live_real_lane.sh` must
  only run against real provider endpoints. Any mock should stay in
  `acceptance_publish_live_lane.sh`.
