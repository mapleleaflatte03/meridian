#!/usr/bin/env bash
# acceptance_commonwealth_e2e_lane.sh
# End-to-end verification of all 5 Verifiable AI Commonwealth layers.
# Runs a 2-institution flow: federate → publish → acquire → settle →
#   dispute → court → refund → memory anchor → proof bundle.
# Exits non-zero on any failure.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${MERIDIAN_BASE_URL:-http://127.0.0.1:8266}"
FAIL=0

pass() { echo "[OK]   $1"; }
fail() { echo "[FAIL] $1"; FAIL=1; }
skip() { echo "[SKIP] $1"; }

require_json_field() {
    local label="$1"
    local json="$2"
    local field="$3"
    local expected="${4:-}"
    local val
    val="$(echo "$json" | python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
keys = '$field'.split('.')
v = d
for k in keys:
    if isinstance(v, dict): v = v.get(k)
    else: v = None
print(v if v is not None else '')
" 2>/dev/null)"
    if [[ -z "$val" ]]; then
        fail "$label: field '$field' missing or null in response"
        return 1
    fi
    if [[ -n "$expected" && "$val" != "$expected" ]]; then
        fail "$label: field '$field' expected='$expected' got='$val'"
        return 1
    fi
    pass "$label"
    return 0
}

api_get() {
    curl -fsS --max-time 10 "$BASE_URL$1" 2>/dev/null || echo "{}"
}

api_post() {
    local path="$1"
    local data="$2"
    curl -fsS --max-time 10 -X POST \
        -H "Content-Type: application/json" \
        -d "$data" \
        "$BASE_URL$path" 2>/dev/null || echo "{}"
}

# ─── Pre-flight ──────────────────────────────────────────────────────────────
echo ""
echo "=== Pre-flight: API reachability ==="
if ! curl -fsS --max-time 5 "$BASE_URL/api/status" >/dev/null 2>&1; then
    echo "[FAIL] API server not reachable at $BASE_URL"
    exit 1
fi
pass "API server reachable at $BASE_URL"

# ─── L1: Federation Layer on PoGE ────────────────────────────────────────────
echo ""
echo "=== L1: Federation Layer on PoGE ==="

FED_STATE="$(api_get "/api/commonwealth/federation")"
require_json_field "L1-GET /api/commonwealth/federation: protocol_version" \
    "$FED_STATE" "protocol_version" || true

LINK_RESP="$(api_post "/api/commonwealth/federation/link" \
    '{"peer_host_id":"host_org_b","peer_org_id":"org_b_test","transport":"http","endpoint_url":"http://127.0.0.1:18910","label":"Org B (E2E test)"}')"
if echo "$LINK_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert d.get('link_id') or d.get('status') == 'already_linked', f'no link_id: {d}'" 2>/dev/null; then
    pass "L1-POST /api/commonwealth/federation/link: peer linked"
    LINK_ID="$(echo "$LINK_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('link_id',''))")"
else
    fail "L1-POST /api/commonwealth/federation/link: $LINK_RESP"
    LINK_ID=""
fi

BUNDLE="$(api_get "/api/commonwealth/proof-bundle")"
require_json_field "L1-GET /api/commonwealth/proof-bundle: protocol" \
    "$BUNDLE" "protocol" || true
if echo "$BUNDLE" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert not d.get('error'), d.get('error','')" 2>/dev/null; then
    pass "L1: proof bundle has no error field"
else
    fail "L1: proof bundle contains error: $BUNDLE"
fi
if echo "$BUNDLE" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); agg=d.get('aggregate') or {}; assert int(agg.get('member_count',0)) >= 1, agg" 2>/dev/null; then
    pass "L1: proof bundle aggregate member_count >= 1"
else
    fail "L1: proof bundle aggregate member_count invalid: $BUNDLE"
fi

FED_STATE2="$(api_get "/api/commonwealth/federation")"
if echo "$FED_STATE2" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert d.get('peer_count', 0) >= 1 or d.get('peers'), 'no peers after link'" 2>/dev/null; then
    pass "L1: federation peer count >= 1 after link"
else
    fail "L1: federation peer_count not updated: $FED_STATE2"
fi

# ─── L4: Publish agent to commonwealth marketplace ───────────────────────────
echo ""
echo "=== L4: Verifiable Agent Exchange Protocol — Publish ==="

PUBLISH_RESP="$(api_post "/api/commonwealth/marketplace/publish" \
    '{"agent_id":"agent_e2e_001","task_description":"E2E commonwealth test agent","amount_usd":1.00,"royalty_rate":0.10,"federation_scope":["org_b_test"],"action_ids":[]}')"
if echo "$PUBLISH_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert d.get('listing_id'), f'no listing_id: {d}'" 2>/dev/null; then
    pass "L4-POST /api/commonwealth/marketplace/publish: agent published"
    LISTING_ID="$(echo "$PUBLISH_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('listing_id',''))")"
else
    fail "L4-POST /api/commonwealth/marketplace/publish: $PUBLISH_RESP"
    LISTING_ID=""
fi

# ─── L4: Acquire agent from commonwealth marketplace ─────────────────────────
echo ""
echo "=== L4: Verifiable Agent Exchange Protocol — Acquire ==="

if [[ -n "$LISTING_ID" ]]; then
    ACQUIRE_RESP="$(api_post "/api/commonwealth/marketplace/acquire" \
        "{\"listing_id\":\"$LISTING_ID\",\"acquirer_org_id\":\"org_b_test\",\"reservation_note\":\"E2E acquire test\"}")"
    if echo "$ACQUIRE_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert d.get('acquisition_id'), f'no acquisition_id: {d}'" 2>/dev/null; then
        pass "L4-POST /api/commonwealth/marketplace/acquire: acquired listing $LISTING_ID"
    else
        fail "L4-POST /api/commonwealth/marketplace/acquire: $ACQUIRE_RESP"
    fi
else
    skip "L4-acquire: no listing_id from publish step"
fi

# ─── L2: Settlement — Prepare ────────────────────────────────────────────────
echo ""
echo "=== L2: Inter-Institution Settlement Protocol ==="

PREPARE_RESP="$(api_post "/api/commonwealth/settlement/prepare" \
    '{"peer_org_id":"org_b_test","agent_id":"agent_e2e_001","task_description":"E2E settlement","amount_usd":1.00,"royalty_rate":0.10,"action_ids":[]}')"
if echo "$PREPARE_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert d.get('settlement_id'), f'no settlement_id: {d}'" 2>/dev/null; then
    pass "L2-POST /api/commonwealth/settlement/prepare: settlement prepared"
    SETTLEMENT_ID="$(echo "$PREPARE_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('settlement_id',''))")"
else
    fail "L2-POST /api/commonwealth/settlement/prepare: $PREPARE_RESP"
    SETTLEMENT_ID=""
fi

# ─── L2: Settlement — Commit ─────────────────────────────────────────────────
if [[ -n "$SETTLEMENT_ID" ]]; then
    COMMIT_RESP="$(api_post "/api/commonwealth/settlement/commit" \
        "{\"settlement_id\":\"$SETTLEMENT_ID\",\"proof_receipt\":\"e2e_proof_receipt_$(date +%s)\",\"warrant_ref\":\"e2e_warrant_ref\"}")"
    if echo "$COMMIT_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert d.get('status') == 'committed', f'not committed: {d}'" 2>/dev/null; then
        pass "L2-POST /api/commonwealth/settlement/commit: settlement committed"
    else
        fail "L2-POST /api/commonwealth/settlement/commit: $COMMIT_RESP"
    fi
else
    skip "L2-commit: no settlement_id from prepare step"
fi

# ─── L2: Settlement — Refund (new settlement for dispute path) ────────────────
PREPARE_REFUND_RESP="$(api_post "/api/commonwealth/settlement/prepare" \
    '{"peer_org_id":"org_b_test","agent_id":"agent_e2e_002","task_description":"E2E dispute/refund test","amount_usd":0.50,"royalty_rate":0.10,"action_ids":[]}')"
REFUND_SETTLEMENT_ID="$(echo "$PREPARE_REFUND_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('settlement_id',''))" 2>/dev/null)"

if [[ -n "$REFUND_SETTLEMENT_ID" ]]; then
    REFUND_RESP="$(api_post "/api/commonwealth/settlement/refund" \
        "{\"settlement_id\":\"$REFUND_SETTLEMENT_ID\",\"reason\":\"E2E court-ordered refund\",\"court_decision_ref\":\"court_e2e_001\"}")"
    if echo "$REFUND_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert d.get('status') == 'refunded', f'not refunded: {d}'" 2>/dev/null; then
        pass "L2-POST /api/commonwealth/settlement/refund: settlement refunded"
    else
        fail "L2-POST /api/commonwealth/settlement/refund: $REFUND_RESP"
    fi
else
    fail "L2-refund: failed to prepare a second settlement for refund test: $PREPARE_REFUND_RESP"
fi

# ─── L3: Dynamic Constitutional Federation — Court Rule Propagation ──────────
echo ""
echo "=== L3: Dynamic Constitutional Federation ==="

PROPAGATE_RESP="$(api_post "/api/commonwealth/court/propagate" \
    '{"peer_host_id":"host_org_b","rule_id":"rule_e2e_001","rule_text":"E2E cross-institution rule: no unauthorized agent execution","ruleset_version":"1.0.0-e2e"}')"
if echo "$PROPAGATE_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert d.get('propagation_id'), f'no propagation_id: {d}'" 2>/dev/null; then
    pass "L3-POST /api/commonwealth/court/propagate: rule propagated"
else
    fail "L3-POST /api/commonwealth/court/propagate: $PROPAGATE_RESP"
fi

# ─── L5: Temporal Memory Commonwealth Chain ───────────────────────────────────
echo ""
echo "=== L5: Temporal Memory Commonwealth Chain ==="

ANCHOR="$(api_get "/api/commonwealth/memory/anchor")"
if echo "$ANCHOR" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert d.get('anchor_status') == 'verified', f'anchor not verified: {d}'" 2>/dev/null; then
    pass "L5-GET /api/commonwealth/memory/anchor: chain verified"
    ANCHOR_HASH="$(echo "$ANCHOR" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('head_hash',''))")"
    pass "L5: head_hash=$ANCHOR_HASH"
else
    fail "L5-GET /api/commonwealth/memory/anchor: $ANCHOR"
fi

# ─── Verify /api/status V5 contract blocks ───────────────────────────────────
echo ""
echo "=== /api/status V5 contract blocks ==="

curl -fsS --max-time 10 "$BASE_URL/api/status" 2>/dev/null > /tmp/meridian_e2e_status.json
python3 - /tmp/meridian_e2e_status.json <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
checks = [
    ('proof.recursive', lambda d: (d.get('proof') or {}).get('recursive')),
    ('proof.aggregate', lambda d: (d.get('proof') or {}).get('aggregate')),
    ('court.dynamic', lambda d: (d.get('court') or {}).get('dynamic')),
    ('marketplace.mode', lambda d: (d.get('marketplace') or {}).get('mode')),
    ('memory.temporal_integrity', lambda d: (d.get('memory') or {}).get('temporal_integrity')),
    ('commonwealth.federation', lambda d: (d.get('commonwealth') or {}).get('federation')),
    ('commonwealth.settlement', lambda d: (d.get('commonwealth') or {}).get('settlement')),
]
fail = False
for name, fn in checks:
    val = fn(d)
    if val is not None:
        print(f'[OK]   /api/status block: {name}')
    else:
        print(f'[FAIL] /api/status block missing: {name}')
        fail = True
sys.exit(1 if fail else 0)
PY
if [[ $? -ne 0 ]]; then FAIL=1; fi

# Ensure status reflects linked federation/settlement activity from this run
if python3 - <<'PY'
import json
with open('/tmp/meridian_e2e_status.json') as f:
    d=json.load(f)
cw=(d.get('commonwealth') or {})
fed=(cw.get('federation') or {})
sett=(cw.get('settlement') or {})
assert int(fed.get('peer_count',0)) >= 1, fed
assert bool(sett.get('inter_institution_enabled')) is True, sett
print('[OK]   /api/status commonwealth reflects active federation/settlement state')
PY
then
    :
else
    fail "/api/status commonwealth did not reflect active federation/settlement state"
fi

# ─── Summary ──────────────────────────────────────────────────────────────────
echo ""
if [[ $FAIL -eq 0 ]]; then
    echo "[acceptance_commonwealth_e2e_lane] PASS — all 5 commonwealth layers verified."
else
    echo "[acceptance_commonwealth_e2e_lane] FAIL — see failures above."
    exit 1
fi
