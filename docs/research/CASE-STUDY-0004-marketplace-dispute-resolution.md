# CASE-STUDY-0004: Marketplace Dispute Resolution

## Scenario

A bid is assigned, settlement is disputed, and court decision chooses refund or release.

## Steps

1. Create bid:

```bash
curl -fsS -X POST http://127.0.0.1:8266/api/marketplace/bids \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"agent_atlas","task_description":"policy brief","amount_usd":5.0}' | jq .
```

2. Assign and settle (example payloads):

```bash
curl -fsS -X POST http://127.0.0.1:8266/api/marketplace/assign \
  -H 'Content-Type: application/json' \
  -d '{"bid_id":"<bid_id>"}' | jq .
curl -fsS -X POST http://127.0.0.1:8266/api/marketplace/settle \
  -H 'Content-Type: application/json' \
  -d '{"bid_id":"<bid_id>","proof_receipt":"proof_hash"}' | jq .
```

3. Open and resolve dispute:

```bash
curl -fsS -X POST http://127.0.0.1:8266/api/marketplace/dispute \
  -H 'Content-Type: application/json' \
  -d '{"bid_id":"<bid_id>","reason":"proof mismatch"}' | jq .
curl -fsS -X POST http://127.0.0.1:8266/api/marketplace/dispute \
  -H 'Content-Type: application/json' \
  -d '{"dispute_id":"<dispute_id>","decision":"refund","reservation_id":"<reservation_id>"}' | jq .
```

## Expected Result

- dispute lifecycle is visible in `/api/marketplace`
- settlement status updates based on decision
- treasury reservation release/refund path is visible in response payload
