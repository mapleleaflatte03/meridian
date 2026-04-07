# Meridian First Customer Playbook

This is the zero-spend path to the first real customer.

Do not pretend the nightly automated pipeline is currently delivering. It is treasury-gated by policy. Sell the value of the output first, then reactivate automation when the economics are real.

If you need the plain-language model behind Meridian before selling anything, read:
- [Meridian Doctrine](MERIDIAN_DOCTRINE.md)

---

## Goal

Get one real team to say:

1. "This is useful enough to try."
2. "This is useful enough to pay for."

That is enough to prove the workflow deserves capital and resumed automated delivery.

---

## Ideal First Customer

Best initial buyer:
- product marketing manager
- competitive intelligence lead
- product manager who owns market tracking

Best company profile:
- B2B software
- AI-native tooling
- 3 to 10 meaningful competitors
- founder or operator team already overwhelmed by release/pricing churn

Avoid first:
- large procurement-heavy enterprises
- teams that require Slack/email integrations on day one
- buyers who need card checkout immediately

---

## Offer

Sell this:

**"A founder-led 7-day pilot for cited competitor intelligence."**

Do not sell this:
- "fully automated production system" as the current customer experience
- "daily bot delivery" as if it is already active for customers today
- "self-serve signup" as the main path

What the pilot includes:
- competitor watchlist setup
- cited alerts
- battlecard on request
- iteration on topics that matter

What the pilot proves:
- the output is worth reading
- the output is worth paying for
- the workflow should be funded back into full automation

---

## Surfaces To Use

Send people here, in this order:

1. Demo:
   `https://app.welliam.codes/demo.html`
2. Pilot page:
   `https://app.welliam.codes/pilot.html`
3. Main page:
   `https://app.welliam.codes/`

Primary contact:
- Telegram: `https://t.me/Enhanhsj`
- Email: `mailto:nguyensimon186@gmail.com`

Do not lead with:
- MCP endpoint
- OSS kernel repo
- payment rails

Those are credibility layers, not the first hook.

---

## Message Sequence

### Message 1

Short DM or short email:

> I built a competitor-intelligence workflow for AI product teams. It tracks pricing changes, launches, API updates, and deprecations, then turns them into cited briefs. Here's a real example: https://app.welliam.codes/demo.html
>
> I'm running a small founder-led pilot right now. Want to try it for 7 days?

### Message 2

If they reply:

> Great. I need 3 things:
> 1. the competitors you care about
> 2. the topics that matter most
> 3. your preferred Telegram account for delivery
>
> I'll scope a 7-day pilot and send the first output manually.

### Message 3

If pilot is useful:

> If this is useful enough to keep, I can move you into paid continuation and formalize the delivery path. Current pricing is $2.99/week or $9.99/month while the system is still early.

---

## Qualification Checklist

Green flags:
- already tracking competitors manually
- complains about newsletters being noisy
- cares about pricing/API changes
- willing to try Telegram delivery
- can decide quickly

Red flags:
- wants full procurement/security review first
- wants custom integrations first
- needs card checkout before any trial
- no clear competitor set

---

## Operator Workflow

1. Confirm prospect fit.
2. Send demo.
3. Get competitor list + topics.
4. Configure watchlist.
5. Run pilot manually.
6. Ask for usefulness verdict before asking for payment.
7. If positive, convert into paid continuation.

Track every real prospect in:

```bash
cd /root/.meridian/workspace
python3 company/lead_tracker.py summary
```

For exact message wording and channel guidance, use:

```bash
less company/OUTREACH_PACK.md
```

---

## Truth Guardrails

Always say:
- manual pilot
- founder-led
- cited output
- automated pipeline exists but is treasury-gated right now

Never say:
- fully self-serve
- automated daily customer delivery is live today
- card checkout is ready
- external traction already exists

---

## One-Command Reality Check

Before promising anything time-sensitive:

```bash
cd /root/.meridian/workspace
python3 company/meridian_platform/readiness.py
```

Interpretation:
- `OWNER_BLOCKED_TREASURY` → keep selling manual pilot, do not promise automated daily delivery
- anything else → inspect the output before making a stronger claim
