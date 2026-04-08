# BENCHMARK-0004: Marketplace Settlement and Dispute Path

## Objective

Validate that marketplace lifecycle reflects reserve/settle/dispute transitions and stays observable via API.

## Reproduction

```bash
cd /home/ubuntu/meridian
curl -fsS http://127.0.0.1:8266/api/marketplace | jq .
curl -fsS http://127.0.0.1:8266/api/treasury | jq .
curl -fsS http://127.0.0.1:8266/api/status | jq '.marketplace'
```

## Metrics

- open bids
- active assignments
- settled count
- open disputes

## Pass Criteria

1. `/api/marketplace` payload includes bids/assignments/settlements/disputes.
2. status marketplace block mirrors lifecycle counters.
3. treasury endpoint remains healthy while lifecycle operations execute.
