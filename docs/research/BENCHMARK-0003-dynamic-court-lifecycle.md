# BENCHMARK-0003: Dynamic Court Proposal Lifecycle

## Objective

Benchmark dynamic court lifecycle endpoints and verify rule-version progression.

## Reproduction

```bash
cd /home/ubuntu/meridian
curl -fsS http://127.0.0.1:8266/api/court/rules | jq .
curl -fsS http://127.0.0.1:8266/api/court/proposals | jq .
curl -fsS http://127.0.0.1:8266/api/status | jq '.court.dynamic'
```

## Metrics

- proposal count
- active rule count
- ruleset version
- API availability (HTTP 200)

## Pass Criteria

1. court dynamic block present in `/api/status`
2. proposal/rules routes return JSON payloads
3. ruleset version is stable and monotonic across activation events
