# CASE-STUDY-0003: Dynamic Court Rule Activation

## Scenario

An operator proposes a constitutional patch, receives votes, tallies, and activates the rule while preserving auditable lineage.

## Steps

1. Submit proposal:

```bash
curl -fsS -X POST http://127.0.0.1:8266/api/court/proposals \
  -H 'Content-Type: application/json' \
  -d '{"title":"Runtime cap update","rule_text":"max_runtime_jobs=8"}' | jq .
```

2. Vote and tally (example):

```bash
curl -fsS -X POST http://127.0.0.1:8266/api/court/vote \
  -H 'Content-Type: application/json' \
  -d '{"proposal_id":"<proposal_id>","vote":"approve"}' | jq .
curl -fsS -X POST http://127.0.0.1:8266/api/court/tally \
  -H 'Content-Type: application/json' \
  -d '{"proposal_id":"<proposal_id>","quorum":1}' | jq .
```

3. Activate:

```bash
curl -fsS -X POST http://127.0.0.1:8266/api/court/proposals/activate \
  -H 'Content-Type: application/json' \
  -d '{"proposal_id":"<proposal_id>"}' | jq .
```

## Expected Result

- activation route returns `rule_id`
- `/api/status` reflects updated dynamic court metadata
- proposal record remains queryable for audit
