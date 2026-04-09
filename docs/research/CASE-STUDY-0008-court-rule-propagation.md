# CASE-STUDY-0008: Dynamic Court Rule Propagation Across Federation

**RFC:** RFC-0007 (Dynamic Constitutional Federation)  
**Date:** 2026-04-08  

## Scenario

Institution A discovers that unauthorized agent execution is occurring across
federation boundaries. A's court creates a new rule and propagates it to
federation peer B.

## Steps

1. **A creates rule:** "No unauthorized agent execution across federation boundaries"
2. **Propagate:** `POST /api/commonwealth/court/propagate` to peer host_org_b
3. **Envelope:** HMAC-SHA256 signed envelope issued (or queued locally if unavailable)
4. **Record:** Propagation recorded with delivery status and propagation_id
5. **B receives:** B's federation inbox processes the rule (advisory by default)

## Observed Behavior

- Propagation creates a signed envelope when federation module is available
- Falls back to local queue when HMAC signing is unavailable
- Propagation record stored with `delivery_status` for audit trail
- Rule text and version preserved exactly as issued

## Key Finding

Court rule propagation preserves institutional sovereignty. The receiving institution
decides whether to adopt the rule — propagation is advisory unless bilateral
constitutional agreements specify otherwise. This design prevents governance capture
while enabling cooperative rule alignment.
