Title: Meridian Loom update: local governed runtime, desktop lane, and public proof viewer

Built and shipped a new Loom release for local-first operators who want more than a chat wrapper.

What it does:

- Local runtime + agent loop
- Adapter lifecycle (`connect scaffold/list/validate/enable/test/health/scorecard`)
- Browser + shell + desktop control lanes
- Public proof/receipt view: https://app.welliam.codes/proofs

Why it might interest this sub:

- Provider-agnostic routing/config (no provider lock-in in config schema)
- Governance layer is explicit (authority/treasury/court)
- Reconnect/fallback/sanction paths are test lanes, not hidden behavior

Project links:

- Loom: https://github.com/mapleleaflatte03/meridian-loom
- Kernel: https://github.com/mapleleaflatte03/meridian-kernel
- Demo: https://app.welliam.codes/demo

Would appreciate direct technical criticism on:

1. Desktop control boundaries (what is still unsafe or missing?)
2. Which local-operator features matter most after browser/shell/desktop?
