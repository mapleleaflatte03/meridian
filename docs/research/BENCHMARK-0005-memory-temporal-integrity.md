# BENCHMARK-0005: Memory Temporal Integrity Query

## Objective

Verify that memory queries return timeline evidence with integrity metadata.

## Reproduction

```bash
cd /home/ubuntu/meridian
curl -fsS -X POST http://127.0.0.1:8266/api/memory/query \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"agent_atlas","start_ts":"2026-04-01T00:00:00Z","end_ts":"2026-04-09T00:00:00Z"}' | jq .
```

## Pass Criteria

1. response includes `nodes[]` and `proof`
2. proof includes `head_hash` and `selected_count`
3. integrity mismatch returns explicit 409 payload
