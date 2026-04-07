# Meridian Council Context

Use this file to keep council-style discussions anchored in verified Meridian truth.

## Boundary

This is the context pack for the **internal Meridian council event**.

It is not the same as an external Codex `/subagent` council:

- External Codex `/subagent` council:
  - off-system
  - exploratory
  - adversarial research and debate
  - can challenge Meridian from outside its own runtime assumptions
- Internal Meridian council:
  - in-system
  - manager-first
  - uses Meridian's own agent team
  - turns an already-serious question into an institutional decision, dissent log, and action register

Do not blur these two events together.

## Questions the council must answer

1. Is Meridian currently simple and credible enough for a real outside customer to buy?
2. What is the real purpose of Meridian's public open-source layer?
3. Where does the public story create trust, and where does it create buying friction?
4. What must change before asking for broader customer payments?

## Verified current commercial truth

- The current live public offer is a bounded paid founder pilot.
- The public offer is `founder-pilot-week` at `$49` for `7` days.
- The live public buy path is:
  - `POST /api/pilot/intake`
  - then `POST /api/subscriptions/checkout-capture`
- Payment rail: exact-amount USDC on Base with tx-hash capture.
- Card checkout is not live.
- Email is the safe default delivery target; Telegram is used when a real target is available.
- Broader customer automation remains bounded by phase progression, preflight, and constitutional gates.

## Verified open-source intent

- The kernel is intentionally public and reusable as the governance boundary.
- Meridian Intelligence is the first commercial wedge, not the whole platform identity.
- Loom is the execution/runtime layer and installable local runtime.
- The hosted Meridian service is not fully open.
- Not-open scope includes:
  - delivery pipelines
  - payment processing
  - customer data
  - proprietary research sources

## Truth boundaries that matter to a buyer

- Support is not customer revenue.
- Demo alerts, briefs, and battlecards are qualified reference examples.
- MCP pricing can be shown publicly, but external-customer settlement proof is still pending.
- The doctrine rule is to prefer the narrower claim that can be honored today.

## Strategic tension

Meridian is strongest when read as:
- an open governance kernel
- a live runtime
- and one narrow paid founder pilot

It becomes harder to buy when a customer has to understand all three layers before they can understand the single thing they are paying for.

## Primary evidence paths

- `company/MERIDIAN_DOCTRINE.md`
- `README.md`
- `company/www/index.html`
- `company/www/demo.html`
- `company/www/pilot.html`
- `company/www/support.html`
- `company/www/OPEN_SOURCE_BOUNDARY.html`
- `/opt/meridian-kernel/README.md`
- `/home/ubuntu/meridian-loom/README.md`
