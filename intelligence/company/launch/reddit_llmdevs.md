Title: Meridian Loom: provider-agnostic local agent runtime with governed connect lifecycle + proof dashboard

I just shipped a new Meridian Loom release and want technical feedback from people running real agent systems.

Core claim:

- Loom is a local runtime for governed agent execution.
- Kernel provides authority / treasury / court constraints.
- First-party workflows prove the runtime under load.

What is new in this release:

- `connect` hardening (rate-limit, malformed payload handling, reconnect-storm sanction path)
- new desktop control transport lane in `loom connect`
- realtime operator event stream (`/api/events/stream`) surfaced on public `/proofs`
- public workflow + USDC operating surfaces (`/workflows`)

Links:

- Loom: https://github.com/mapleleaflatte03/meridian-loom
- Kernel: https://github.com/mapleleaflatte03/meridian-kernel
- Live proof dashboard: https://app.welliam.codes/proofs
- Live demo: https://app.welliam.codes/demo

What I need from this sub:

1. Which connect transport or failure mode is still under-specified?
2. Which operator KPI would you require before trusting this in production?
