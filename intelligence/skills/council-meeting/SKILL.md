---
name: council-meeting
description: "Use when Meridian needs a board-style council discussion about customer readiness, open-source intent, strategic clarity, or whether the current product is truly buyable."
metadata:
  created_by: meridian_system
  category: "strategy"
---

# Council Meeting

Use the shared council context pack at `company/COUNCIL_CUSTOMER_READINESS_CONTEXT.md`.

This skill is for the **internal Meridian council event**, not the external Codex `/subagent` council event.

- External Codex `/subagent` council: exploratory, off-system, research/debate first.
- Internal Meridian council: in-system, Leviathann-chaired, decision/action first.

Use this skill when the user asks for things like:
- council meeting
- board review
- why would a customer buy this
- is Meridian buyable right now
- what is the real intent of Meridian open source
- do we actually have strategic clarity
- họp hội đồng
- phản biện về khách hàng, opensource, định hướng

## Workflow

1. Convene the Meridian council with these preferred specialists: ATLAS, SENTINEL, QUILL, AEGIS, FORGE, PULSE.
2. Force every specialist to argue from the same verified context pack and live Meridian host facts.
3. Require disagreement, contradiction checks, and evidence-backed objections before consensus.
4. Separate:
   - what is currently sellable
   - what is strategically true but not yet sellable
   - what is still confusing or contradictory
5. End with one council resolution, a ranked blocker list, and the next execution moves.

## Role Expectations

- Atlas: analyze customer readiness, market realism, and buyer objections.
- Sentinel: attack contradictions, weak claims, strategic incoherence, and trust risks.
- Quill: write human-readable board minutes and the final resolution.
- Aegis: reject unsupported claims and mark verified vs inferential statements.
- Forge: turn the council resolution into concrete execution priorities.
- Pulse: compress disagreements, unresolved questions, and the final operator summary.

## Output Contract

Return a human-style council meeting with:
- agenda
- verified baseline
- arguments for
- objections / contradictions
- consensus
- unresolved questions
- immediate decisions
- next actions

## Guardrails

- Do not invent traction, customer love, or proof of value.
- Do not blur support, pilot revenue, customer revenue, and contributor payouts.
- Do not let open-source mythology replace the real sellable offer.
- If the product is not yet credible enough to earn money at scale, say exactly why.
