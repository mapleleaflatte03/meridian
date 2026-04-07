Post 1:
Meridian Loom update: local governed agent runtime now has a public proof dashboard + realtime operator stream.

Runtime: https://github.com/mapleleaflatte03/meridian-loom
Proof view: https://app.welliam.codes/proofs

Post 2:
What shipped in this release:
- connect C2 hardening (rate-limit, malformed payload, reconnect-storm sanction path)
- desktop control transport lane
- event streaming into operator view (`/api/events/stream`)

Post 3:
Stack boundary stays explicit:
- Loom = runtime
- Kernel = authority/treasury/court core
- first-party workflows = workload proof, not category confusion

Kernel: https://github.com/mapleleaflatte03/meridian-kernel

Post 4:
Live pages:
- Demo: https://app.welliam.codes/demo
- Workflows: https://app.welliam.codes/workflows
- Compare: https://app.welliam.codes/compare

Post 5:
Looking for operator-grade feedback:
1) Which adapter/failure mode still blocks trust?
2) Which dashboard KPI would you require before production adoption?
