# Meridian Launch Pack

This folder contains publish-ready launch assets for:

- X thread
- Hacker News (`Show HN`)
- Reddit (`r/LLMDevs`, `r/LocalLLaMA`)

Usage:

1. Verify live host state on `/proofs` and `/demo`.
2. Record or regenerate the 2-3 minute demo video artifact.
3. Post using the prepared copy in this folder.
4. Pin one canonical narrative link (`/why` or a pinned GitHub discussion).

These assets avoid provider-specific wording and keep the runtime/governance boundary explicit.

## Included assets

- `show_hn_short.md`
- `reddit_llmdevs.md`
- `reddit_localllama.md`
- `x_thread.md`
- `publish_checklist.md`
- `make_demo_video.py`
- `community_ops.py`
- `publish_live.py`
- `COMMUNITY_MOTION.md`

## Community ops lane

Dry-run weekly community update payload and artifact:

```bash
python3 company/launch/community_ops.py --dry-run
```

## Live publish lane

Run X + Reddit + HN + Discord publish orchestration with one command and audit
artifact output:

```bash
python3 company/launch/publish_live.py \
  --channels x,reddit,hn,discord \
  --site https://app.welliam.codes
```

Required credentials are resolved from environment variables:

- `MERIDIAN_X_API_TOKEN`
- `MERIDIAN_REDDIT_CLIENT_ID`
- `MERIDIAN_REDDIT_CLIENT_SECRET`
- `MERIDIAN_REDDIT_USERNAME`
- `MERIDIAN_REDDIT_PASSWORD`
- `MERIDIAN_HN_USERNAME`
- `MERIDIAN_HN_PASSWORD`
- `MERIDIAN_DISCORD_WEBHOOK_URL`

Acceptance lane (unit + mock-live):

```bash
./scripts/acceptance_publish_live_lane.sh
```

Real publish acceptance lane (requires live credentials; verifies all channels
report `status=posted`):

```bash
./scripts/acceptance_publish_live_real_lane.sh
```
