# Meridian Outreach Pack

This pack exists to answer one simple question:

**What exactly should Sơn send, to whom, and on which channel?**

It is written for the current honest state of Meridian:
- runtime is healthy
- automation exists
- treasury-gated daily delivery is still blocked by policy
- the live offer is a **founder-led manual pilot**

Do not improvise beyond this unless the system state changes.

If you start getting confused about what Meridian is selling versus what it is building long-term, re-read:
- [Meridian Doctrine](MERIDIAN_DOCTRINE.md)

---

## The Core Rule

Do **not** send people:
- a vague founder story
- a giant product manifesto
- a public sales pitch in the wrong place

Do send them:
- one direct message
- one clear promise
- one demo link
- one small next step

The goal is not to “close a customer” in message 1.

The goal is:
1. get a reply
2. start a small pilot
3. learn whether the output is useful

---

## Where To Send What

### 1. Direct DM to one person

Best use:
- Telegram DM
- LinkedIn DM

Use this when:
- you know the person
- or the person matches the ICP closely

Do this first.

### 2. Email

Best use:
- when DM is unavailable
- when the buyer is more formal
- when you want a slightly calmer, more credible approach

Use after DM if needed, or instead of DM.

### 3. Public post

Best use:
- later
- as credibility support
- not as the first move

Do **not** rely on a public post to get the first real customer.

### 4. Telegram channel

Use the channel as:
- proof that Meridian exists
- a public surface
- social proof

Do **not** use the channel as your first outbound message to a serious lead.

The first outreach move should be direct and personal.

---

## Who To Send It To

Good first targets:
- product marketing manager
- competitive intelligence lead
- product manager tracking competitors
- founder/operator at a small AI tooling company

Bad first targets:
- enterprise procurement people
- generic “business” contacts
- people with no visible competitor-tracking problem
- anyone who clearly expects polished enterprise onboarding on day one

---

## Best First Move

Send **one direct DM** to **one person** with:
- one sentence about what Meridian does
- one real demo link
- one small ask

That is it.

---

## Lowest-Pressure Message

Use this when you feel afraid of overcommitting.

### Telegram / LinkedIn DM

> Hey [Name] — I built a small competitor-intelligence workflow for AI product teams.
>
> It tracks pricing changes, launches, API updates, and deprecations, then turns them into a cited brief.
>
> Here’s a real example: https://app.welliam.codes/demo.html
>
> I’m testing it through a small founder-led pilot right now. If this looks useful, I can run a 7-day pilot for your team.

Why this works:
- no fake scale claim
- no fake automation claim
- no pressure
- clear next step

---

## Slightly Stronger Message

Use this when the person clearly has the problem.

### Telegram / LinkedIn DM

> Hey [Name] — I built Meridian for teams who are tired of tracking competitors manually.
>
> It monitors pricing changes, launches, API updates, and deprecations across AI/ML companies, then turns that into a cited brief your team can actually read.
>
> Real example: https://app.welliam.codes/demo.html
>
> I’m running a small founder-led pilot now. If you want, I can scope a 7-day pilot around the competitors you care about.

---

## Email Version

Subject:
`A small competitor-intelligence pilot for AI product teams`

Body:

> Hi [Name],
>
> I built Meridian, a competitor-intelligence workflow for AI product teams.
>
> It tracks pricing changes, launches, API updates, and deprecations, then turns them into cited briefs. Here’s a real example:
> https://app.welliam.codes/demo.html
>
> I’m currently running a small founder-led pilot. If the output looks useful, I can scope a 7-day pilot around the competitors your team cares about.
>
> If that sounds relevant, reply here and I’ll send the simple setup questions.
>
> Sơn

---

## If They Reply “Interesting”

Send this:

> Great. I only need 3 things to scope it:
>
> 1. which competitors you care about
> 2. which topics matter most (pricing, launches, API changes, partnerships, etc.)
> 3. where you want the pilot output to land first
>
> I’ll keep the first pass small and practical.

---

## If They Ask “Is This Live?”

Say this:

> The workflow and outputs are real, and the current customer path is a founder-led manual pilot.
>
> I’m not pretending the full automated delivery loop is broadly live for customers yet. I’d rather let you judge the usefulness of the output first.

---

## If They Ask “How Much Work Is This For Me?”

Say this:

> Very little for the pilot. You give me the competitors and topics, and I set up the first pass.
>
> The goal of the pilot is to test usefulness, not create onboarding overhead.

---

## If They Ask “How Do I Pay?”

Say this:

> Only if the pilot is useful.
>
> Current continuation pricing is small and handled manually while the system is still early:
> - $2.99/week
> - $9.99/month

Do not lead with payment unless they ask or the pilot already proved useful.

---

## What Not To Say

Do not say:
- “fully automated”
- “production-ready at scale”
- “sign up and it all just works today”
- “daily delivery is already live for customers”
- “we already have traction”

Do not send:
- the OSS repo as the first link
- MCP endpoint as the first link
- a giant technical explanation

---

## Which Link To Send First

Default order:

1. `https://app.welliam.codes/demo.html`
2. `https://app.welliam.codes/pilot.html`
3. `https://app.welliam.codes/`

If they are highly technical, send the main page after the demo.

Do not start with the OSS repo unless they specifically care about the kernel.

---

## One-Command Reality Check Before Sending

Before you promise anything time-sensitive:

```bash
cd /root/.meridian/workspace
python3 company/meridian_platform/readiness.py
```

Interpret it like this:
- `OWNER_BLOCKED_TREASURY` → sell manual pilot only
- anything healthier → inspect before making stronger promises

---

## Recommended Next Step For Sơn

Do not send five messages yet.

Send **one** message to **one** person using the **Lowest-Pressure Message** above.

That is the safest correct move.
