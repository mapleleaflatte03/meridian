# Publish Checklist

1. Verify live pages:
   - `/demo`
   - `/proofs`
   - `/workflows`
   - `/compare`
2. Verify launch assets:
   - `show_hn_short.md`
   - `reddit_llmdevs.md`
   - `reddit_localllama.md`
   - `x_thread.md`
3. Confirm demo video artifact exists:
   - `company/launch/assets/meridian_demo_2m20s.mp4`
4. Publish in order:
   - X thread
   - Reddit (`r/LLMDevs`, then `r/LocalLLaMA`)
   - Show HN
   - Discord community update
5. Execute automated lane:
   - `python3 company/launch/publish_live.py --channels x,reddit,hn,discord --site https://app.welliam.codes`
   - `./scripts/acceptance_publish_live_real_lane.sh`
6. Verify latest publish artifact:
   - `company/launch/artifacts/publish_live_latest.json`
   - every configured channel reports `status: posted`
7. After publish:
   - open one pinned discussion on Loom repo for feedback triage
   - log first 24h responses into `company/LEAD_TRACKER.md`
