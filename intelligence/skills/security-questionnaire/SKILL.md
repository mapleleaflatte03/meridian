---
name: security-questionnaire
description: "Use when the user needs governed questionnaire answers, customer assurance drafts, or evidence-backed responses for security, privacy, retention, subprocessors, or AI governance."
metadata:
  created_by: meridian_product
  session_key: "web_api:trust-ops"
  category: "assurance"
---

# Security Questionnaire

Use this skill when the user asks for:
- security questionnaire help
- customer assurance drafts
- trust center or due diligence responses
- AI governance answer packs

## Workflow

1. Separate approved evidence from draft answers and open gaps.
2. Route the work through these preferred specialists: ATLAS, QUILL, AEGIS.
3. Reuse governed trust evidence first, then gather missing support.
4. Draft only the answers that can be supported truthfully in the current execution context.
5. Escalate missing proof instead of inventing it.

## Reachable Capability Hints

- Atlas should retrieve the strongest available evidence and missing-proof signals.
- Quill should draft buyer-facing answers that stay bounded to the evidence.
- Aegis should reject unsupported certifications, retention promises, privacy promises, or subprocessor claims.

## Guardrails

- Do not claim SOC 2, ISO 27001, retention timelines, subprocessors, privacy guarantees, or AI governance controls without proof.
- Do not hide open gaps; unresolved questions must stay visible.
- Do not present a draft answer pack as fully approved unless the evidence is actually approved.
