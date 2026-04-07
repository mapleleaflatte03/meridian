# Meridian Intelligence

Public portal, first-party apps, and launch operations for Meridian. Python.

## Build & Test

```bash
python -m pytest test_gateway_brain_router.py test_gateway_team_route.py -v
bash scripts/acceptance_publish_live_lane.sh      # dry-run publish
bash scripts/acceptance_competitor_snapshot_lane.sh
```

## Architecture

- `meridian_gateway.py` — HTTP gateway serving proof/workflow/community pages and API routes
- `company/meridian_platform/` — brain_router (provider-agnostic routing), team_topology, loom_runtime_proof
- `company/www/` — static web surfaces: proofs.html, workflows.html, community.html, compare.html
- `company/launch/` — launch materials, publish pipeline, social content, demo video
- `scripts/` — acceptance lanes for publish, competitor snapshot, proof chain, route decisions

## Live Surfaces

- `https://app.welliam.codes/proofs` — runtime proof posture dashboard
- `https://app.welliam.codes/workflows` — operator workflow showcase
- `https://app.welliam.codes/community` — community ops guide
- `https://app.welliam.codes/api/workflows/showcase` — JSON API (requires Origin header)

## Key Constraints

- Provider-agnostic: brain_router uses config-driven selection, no hardcoded providers
- M-wings branding in all web surfaces
- No prompt/meta jargon in public docs
- publish_live_real requires 8 external credential env vars (see acceptance lane output)
