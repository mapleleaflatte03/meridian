Show HN: Meridian Loom — governed local agent runtime with verifiable receipts

Hi HN,

I built Meridian Loom: a local agent runtime where critical execution is tied to governance primitives and inspectable proof surfaces.

What is live right now:

- One-command install (`curl .../scripts/install.sh | bash`)
- Local agent loop (`loom new-agent`, `loom run-agent`)
- Connect adapters with operator lifecycle (`scaffold/validate/enable/test/health/scorecard`)
- Public runtime/proof dashboard on our host: https://app.welliam.codes/proofs

What is different:

- Runtime + governance are explicit:
  - Loom = runtime
  - Kernel = authority/treasury/court core
- Not just logs: we keep receipt/proof surfaces inspectable and tie failures into remediation paths.

Links:

- Runtime repo: https://github.com/mapleleaflatte03/meridian-loom
- Governance core: https://github.com/mapleleaflatte03/meridian-kernel
- Live demo: https://app.welliam.codes/demo

I would value hard feedback on:

1. Which adapter/lifecycle gaps still block production trust?
2. Which operator views are still missing for daily use?
