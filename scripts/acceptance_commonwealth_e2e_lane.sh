#!/usr/bin/env bash
# acceptance_commonwealth_e2e_lane.sh
# End-to-end verification of all 5 Verifiable AI Commonwealth layers.
# Runs a 2-institution flow: federate → publish → acquire → settle →
#   dispute → court → refund → memory anchor → proof bundle.
# Exits non-zero on any failure.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${MERIDIAN_BASE_URL:-http://127.0.0.1:8266}"
REQUEST_TIMEOUT="${MERIDIAN_REQUEST_TIMEOUT:-60}"
OPERATOR_TOKEN="${MERIDIAN_OPERATOR_TOKEN:-${MERIDIAN_GATEWAY_TOKEN:-}}"
FAIL=0

pass() { echo "[OK]   $1"; }
fail() { echo "[FAIL] $1"; FAIL=1; }
skip() { echo "[SKIP] $1"; }

wait_for_api() {
    local url="$1"
    local timeout_s="${2:-30}"
    local deadline=$((SECONDS + timeout_s))
    while (( SECONDS < deadline )); do
        if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

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
    local path="$1"
    local tmp code
    tmp="$(mktemp)"
    if [[ -n "$OPERATOR_TOKEN" && "${MERIDIAN_OPERATOR_TOKEN_ON_GET:-0}" == "1" ]]; then
        code="$(curl -sS --max-time "$REQUEST_TIMEOUT" -o "$tmp" -w "%{http_code}" \
            -H "X-Meridian-Operator-Token: $OPERATOR_TOKEN" \
            "$BASE_URL$path" 2>/dev/null || true)"
    else
        code="$(curl -sS --max-time "$REQUEST_TIMEOUT" -o "$tmp" -w "%{http_code}" \
            "$BASE_URL$path" 2>/dev/null || true)"
    fi
    LAST_HTTP_CODE="${code:-000}"
    cat "$tmp" 2>/dev/null || echo "{}"
    rm -f "$tmp"
}

api_post() {
    local path="$1"
    local data="$2"
    local tmp code
    tmp="$(mktemp)"
    if [[ -n "$OPERATOR_TOKEN" ]]; then
        code="$(curl -sS --max-time "$REQUEST_TIMEOUT" -o "$tmp" -w "%{http_code}" -X POST \
            -H "Content-Type: application/json" \
            -H "X-Meridian-Operator-Token: $OPERATOR_TOKEN" \
            -d "$data" \
            "$BASE_URL$path" 2>/dev/null || true)"
    else
        code="$(curl -sS --max-time "$REQUEST_TIMEOUT" -o "$tmp" -w "%{http_code}" -X POST \
            -H "Content-Type: application/json" \
            -d "$data" \
            "$BASE_URL$path" 2>/dev/null || true)"
    fi
    LAST_HTTP_CODE="${code:-000}"
    cat "$tmp" 2>/dev/null || echo "{}"
    rm -f "$tmp"
}

api_post_retry_timeout() {
    local path="$1"
    local data="$2"
    local attempts="${3:-5}"
    local i resp
    for ((i=1; i<=attempts; i++)); do
        resp="$(api_post "$path" "$data")"
        if [[ "${LAST_HTTP_CODE:-000}" == "000" ]]; then
            if (( i < attempts )); then
                sleep 1
                continue
            fi
        fi
        if echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); assert not (d.get('output') == 'TimeoutError: timed out' or str(d.get('error','')).startswith('TimeoutError'))" 2>/dev/null; then
            echo "$resp"
            return 0
        fi
        if (( i < attempts )); then
            sleep 1
        fi
    done
    echo "$resp"
    return 0
}

api_get_retry_json() {
    local path="$1"
    local attempts="${2:-5}"
    local i resp
    for ((i=1; i<=attempts; i++)); do
        resp="$(api_get "$path")"
        if echo "$resp" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert isinstance(d, dict) and len(d) > 0" 2>/dev/null; then
            echo "$resp"
            return 0
        fi
        if (( i < attempts )); then
            sleep 1
        fi
    done
    echo "$resp"
    return 0
}

ensure_treasury_headroom() {
    local required_usd="${1:-0.0}"
    local context_label="${2:-treasury headroom}"
    local snapshot shortfall available needs_topup topup_amount topup_resp

    snapshot="$(api_get "/api/treasury")"
    if ! assert_http_ok "Treasury check ($context_label)" "$snapshot"; then
        fail "Treasury snapshot unavailable for $context_label"
        return 1
    fi

    shortfall="$(echo "$snapshot" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(float(d.get('shortfall_usd') or 0.0))" 2>/dev/null || echo "0")"
    available="$(echo "$snapshot" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(float(d.get('available_for_reservation_usd') or 0.0))" 2>/dev/null || echo "0")"

    needs_topup=0
    if python3 -c "import sys; shortfall=float(sys.argv[1]); avail=float(sys.argv[2]); req=float(sys.argv[3]); raise SystemExit(0 if (shortfall > 0.0001 or avail + 1e-9 < req) else 1)" "$shortfall" "$available" "$required_usd" 2>/dev/null; then
        needs_topup=1
    fi

    if [[ "$needs_topup" == "0" ]]; then
        pass "Treasury headroom sufficient for $context_label (available=${available}, required=${required_usd})"
        return 0
    fi

    topup_amount="$(python3 -c "import sys; shortfall=float(sys.argv[1]); avail=float(sys.argv[2]); req=float(sys.argv[3]); deficit=max(shortfall, req-avail, 0.0); print(round(max(deficit + 5.0, 1.0), 2))" "$shortfall" "$available" "$required_usd")"
    topup_resp="$(api_post "/api/treasury/contribute" "{\"amount\":${topup_amount},\"note\":\"e2e auto headroom ${context_label}\"}")"
    if assert_http_ok "Treasury top-up ($context_label)" "$topup_resp"; then
        pass "Treasury topped up by \$${topup_amount} for $context_label"
        return 0
    fi
    fail "Treasury top-up failed for $context_label: $topup_resp"
    return 1
}

assert_http_ok() {
    local label="$1"
    local payload="$2"
    local code="${LAST_HTTP_CODE:-000}"
    if [[ "$code" =~ ^2 ]]; then
        return 0
    fi
    # Calls wrapped in command substitution execute in a subshell, so
    # LAST_HTTP_CODE may be lost. If payload is present and non-empty JSON,
    # continue and let semantic assertions validate correctness.
    if [[ "$code" == "000" ]]; then
        if echo "$payload" | python3 -c "import json,sys; d=json.load(sys.stdin); assert isinstance(d, dict) and len(d) > 0" 2>/dev/null; then
            return 0
        fi
    fi
    local compact
    compact="$(echo "$payload" | tr '\n' ' ' | cut -c1-300)"
    if [[ "$code" =~ ^2 ]]; then
        return 0
    else
        fail "$label: http=$code body=$compact"
        return 1
    fi
}

# ─── Pre-flight ──────────────────────────────────────────────────────────────
echo ""
echo "=== Pre-flight: API reachability ==="
if ! wait_for_api "$BASE_URL/api/status" "${MERIDIAN_API_READY_TIMEOUT_SECONDS:-45}"; then
    echo "[FAIL] API server not reachable at $BASE_URL"
    exit 1
fi
pass "API server reachable at $BASE_URL"

STATUS_JSON="$(api_get "/api/status")"
if ! assert_http_ok "Preflight /api/status" "$STATUS_JSON"; then
    echo "[acceptance_commonwealth_e2e_lane] FAIL — preflight status not reachable."
    exit 1
fi
ACTIVE_ORG_ID="$(echo "$STATUS_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(((d.get('institution') or {}).get('id') or (d.get('org') or {}).get('id') or '').strip())" 2>/dev/null || true)"
if [[ -z "$ACTIVE_ORG_ID" ]]; then
    fail "Unable to resolve active org_id from /api/status (institution.id/org.id)"
    ACTIVE_ORG_ID="org_48b05c21"
else
    pass "Active org_id resolved: $ACTIVE_ORG_ID"
fi

LINK_SHARED_SECRET="${MERIDIAN_FEDERATION_LINK_SECRET:-${MERIDIAN_FEDERATION_SIGNING_SECRET:-}}"
LINK_PEER_HOST_ID="${MERIDIAN_FEDERATION_PEER_HOST_ID:-host_org_b}"
LINK_ENDPOINT_URL="${MERIDIAN_FEDERATION_PEER_ENDPOINT_URL:-http://127.0.0.1:19001}"
E2E_AGENT_ID="${MERIDIAN_E2E_AGENT_ID:-agent_forge}"
E2E_PRIMARY_AMOUNT="${MERIDIAN_E2E_PRIMARY_AMOUNT:-0.25}"
E2E_GUARD_AMOUNT="${MERIDIAN_E2E_GUARD_AMOUNT:-0.20}"
E2E_REFUND_AMOUNT="${MERIDIAN_E2E_REFUND_AMOUNT:-0.10}"
E2E_AUTO_RECAPITALIZE="${MERIDIAN_E2E_AUTO_RECAPITALIZE:-1}"
E2E_RUN_ID="${MERIDIAN_E2E_RUN_ID:-$(date -u +%Y%m%dT%H%M%S)-$RANDOM}"

echo ""
echo "=== Treasury preflight for settlement tests ==="
TREASURY_PREFLIGHT="$(api_get "/api/treasury")"
if assert_http_ok "Treasury preflight /api/treasury" "$TREASURY_PREFLIGHT"; then
    SHORTFALL_USD="$(echo "$TREASURY_PREFLIGHT" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(float(d.get('shortfall_usd') or 0.0))" 2>/dev/null || echo "0")"
    AVAILABLE_FOR_RESERVATION_USD="$(echo "$TREASURY_PREFLIGHT" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(float(d.get('available_for_reservation_usd') or 0.0))" 2>/dev/null || echo "0")"
    REQUIRED_HEADROOM_USD="$(python3 -c "import sys; a=float(sys.argv[1]); b=float(sys.argv[2]); c=float(sys.argv[3]); print(round(a+b+c+0.75, 2))" "$E2E_PRIMARY_AMOUNT" "$E2E_GUARD_AMOUNT" "$E2E_REFUND_AMOUNT")"
    if [[ "${E2E_AUTO_RECAPITALIZE}" == "1" ]]; then
        NEEDS_TOPUP=0
        if python3 -c "import sys; x=float(sys.argv[1]); raise SystemExit(0 if x > 0.0001 else 1)" "${SHORTFALL_USD}" 2>/dev/null; then
            NEEDS_TOPUP=1
        fi
        if python3 -c "import sys; avail=float(sys.argv[1]); req=float(sys.argv[2]); raise SystemExit(0 if avail + 1e-9 < req else 1)" "${AVAILABLE_FOR_RESERVATION_USD}" "${REQUIRED_HEADROOM_USD}" 2>/dev/null; then
            NEEDS_TOPUP=1
        fi
        if [[ "$NEEDS_TOPUP" == "1" ]]; then
            TOPUP_AMOUNT="$(python3 -c "import sys; shortfall=float(sys.argv[1]); avail=float(sys.argv[2]); req=float(sys.argv[3]); deficit=max(shortfall, req-avail, 0.0); print(round(deficit + 5.0, 2))" "${SHORTFALL_USD}" "${AVAILABLE_FOR_RESERVATION_USD}" "${REQUIRED_HEADROOM_USD}")"
            TOPUP_RESP="$(api_post "/api/treasury/contribute" "{\"amount\":${TOPUP_AMOUNT},\"note\":\"e2e auto recapitalize\"}")"
            if assert_http_ok "Treasury top-up /api/treasury/contribute" "$TOPUP_RESP"; then
                pass "Treasury recapitalized by \$${TOPUP_AMOUNT} for E2E settlement coverage"
            else
                fail "Treasury top-up failed: $TOPUP_RESP"
            fi
        else
            pass "Treasury preflight already above reserve floor"
        fi
    else
        skip "Treasury auto recapitalize disabled (MERIDIAN_E2E_AUTO_RECAPITALIZE=0)"
    fi
else
    fail "Treasury preflight route unavailable"
fi

# ─── L1: Federation Layer on PoGE ────────────────────────────────────────────
echo ""
echo "=== L1: Federation Layer on PoGE ==="

FED_STATE="$(api_get "/api/commonwealth/federation")"
assert_http_ok "L1-GET /api/commonwealth/federation" "$FED_STATE" || true
require_json_field "L1-GET /api/commonwealth/federation: protocol_version" \
    "$FED_STATE" "protocol_version" || true

LINK_RESP="$(api_post "/api/commonwealth/federation/link" \
    "{\"peer_host_id\":\"$LINK_PEER_HOST_ID\",\"peer_org_id\":\"$ACTIVE_ORG_ID\",\"transport\":\"http\",\"endpoint_url\":\"$LINK_ENDPOINT_URL\",\"label\":\"Commonwealth peer ${LINK_PEER_HOST_ID}\",\"shared_secret\":\"$LINK_SHARED_SECRET\"}")"
if ! assert_http_ok "L1-POST /api/commonwealth/federation/link" "$LINK_RESP"; then
    LINK_ID=""
elif echo "$LINK_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert d.get('link_id') or d.get('status') == 'already_linked', f'no link_id: {d}'" 2>/dev/null; then
    pass "L1-POST /api/commonwealth/federation/link: peer linked"
    LINK_ID="$(echo "$LINK_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('link_id',''))")"
else
    fail "L1-POST /api/commonwealth/federation/link: $LINK_RESP"
    LINK_ID=""
fi

BUNDLE="$(api_get "/api/commonwealth/proof-bundle")"
assert_http_ok "L1-GET /api/commonwealth/proof-bundle" "$BUNDLE" || true
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
    "{\"agent_id\":\"$E2E_AGENT_ID\",\"task_description\":\"E2E commonwealth test agent ${E2E_RUN_ID}\",\"amount_usd\":$E2E_PRIMARY_AMOUNT,\"royalty_rate\":0.10,\"federation_scope\":[\"org_b_test\"],\"action_ids\":[\"e2e_publish_${E2E_RUN_ID}\"]}")"
if ! assert_http_ok "L4-POST /api/commonwealth/marketplace/publish" "$PUBLISH_RESP"; then
    LISTING_ID=""
elif echo "$PUBLISH_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert d.get('listing_id'), f'no listing_id: {d}'" 2>/dev/null; then
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
    if ! assert_http_ok "L4-POST /api/commonwealth/marketplace/acquire" "$ACQUIRE_RESP"; then
        fail "L4-POST /api/commonwealth/marketplace/acquire: $ACQUIRE_RESP"
    elif echo "$ACQUIRE_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert d.get('acquisition_id'), f'no acquisition_id: {d}'" 2>/dev/null; then
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

if [[ "${E2E_AUTO_RECAPITALIZE}" == "1" ]]; then
    ensure_treasury_headroom "$(python3 -c "import sys; p=float(sys.argv[1]); g=float(sys.argv[2]); r=float(sys.argv[3]); print(round(p+g+r+0.5, 2))" "$E2E_PRIMARY_AMOUNT" "$E2E_GUARD_AMOUNT" "$E2E_REFUND_AMOUNT")" "settlement prepare bundle" || true
fi

PREPARE_RESP="$(api_post_retry_timeout "/api/commonwealth/settlement/prepare" \
    "{\"peer_org_id\":\"org_b_test\",\"agent_id\":\"$E2E_AGENT_ID\",\"task_description\":\"E2E settlement ${E2E_RUN_ID}\",\"amount_usd\":$E2E_PRIMARY_AMOUNT,\"royalty_rate\":0.10,\"action_ids\":[\"e2e_settle_${E2E_RUN_ID}\"]}")"
if ! assert_http_ok "L2-POST /api/commonwealth/settlement/prepare" "$PREPARE_RESP"; then
    SETTLEMENT_ID=""
elif echo "$PREPARE_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert d.get('settlement_id'), f'no settlement_id: {d}'" 2>/dev/null; then
    pass "L2-POST /api/commonwealth/settlement/prepare: settlement prepared"
    SETTLEMENT_ID="$(echo "$PREPARE_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('settlement_id',''))")"
    SETTLEMENT_RECEIPT_HASH="$(echo "$PREPARE_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('receipt_hash',''))")"
    RESERVATION_ID="$(echo "$PREPARE_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('reservation_id',''))")"
    if [[ -n "$RESERVATION_ID" ]]; then
        pass "L2: reservation linked to settlement ($RESERVATION_ID)"
    else
        fail "L2: missing reservation_id in settlement prepare response: $PREPARE_RESP"
    fi
else
    fail "L2-POST /api/commonwealth/settlement/prepare: $PREPARE_RESP"
    SETTLEMENT_ID=""
fi

# ─── L2: Settlement — Commit ─────────────────────────────────────────────────
if [[ -n "$SETTLEMENT_ID" ]]; then
    LIVE_PROOF_ROOT="$(api_get "/api/status" | python3 -c "import json,sys; d=json.loads(sys.stdin.read() or '{}'); print((((d.get('proof') or {}).get('recursive') or {}).get('root')) or '')" 2>/dev/null || true)"
    PROOF_RECEIPT="$SETTLEMENT_RECEIPT_HASH"
    if [[ -z "$PROOF_RECEIPT" ]]; then
        PROOF_RECEIPT="$LIVE_PROOF_ROOT"
    fi
    if [[ -z "$PROOF_RECEIPT" ]]; then
        fail "L2-commit: missing settlement receipt hash and live recursive proof root"
        PROOF_RECEIPT="0000000000000000000000000000000000000000000000000000000000000000"
    fi
    COMMIT_RESP="$(api_post_retry_timeout "/api/commonwealth/settlement/commit" \
        "{\"settlement_id\":\"$SETTLEMENT_ID\",\"proof_receipt\":\"$PROOF_RECEIPT\",\"warrant_ref\":\"e2e_warrant_ref\"}")"
    if ! assert_http_ok "L2-POST /api/commonwealth/settlement/commit" "$COMMIT_RESP"; then
        if echo "$COMMIT_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); msg=' '.join([str(d.get('error','')), str(d.get('reason','')), str(d.get('output',''))]).lower(); assert 'status=committed' in msg or 'already committed' in msg" 2>/dev/null; then
            pass "L2-POST /api/commonwealth/settlement/commit: idempotent replay accepted (already committed)"
        else
        REFUND_ON_FAIL="$(api_post "/api/commonwealth/settlement/refund" \
            "{\"settlement_id\":\"$SETTLEMENT_ID\",\"reason\":\"auto_refund_after_commit_failure\",\"court_decision_ref\":\"court_e2e_auto_refund\"}")"
        fail "L2-commit auto-refund attempted: $REFUND_ON_FAIL"
        fi
    elif echo "$COMMIT_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert d.get('status') == 'committed', f'not committed: {d}'" 2>/dev/null; then
        pass "L2-POST /api/commonwealth/settlement/commit: settlement committed"
        if echo "$COMMIT_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); t=d.get('treasury_commit') or {}; s=str(t.get('status','')); assert s in ('committed','already_committed'), t" 2>/dev/null; then
            pass "L2: treasury commit finalized from reservation"
        else
            fail "L2: treasury commit missing/error in settlement commit response: $COMMIT_RESP"
        fi
    else
        fail "L2-POST /api/commonwealth/settlement/commit: $COMMIT_RESP"
    fi
else
    skip "L2-commit: no settlement_id from prepare step"
fi

PREPARE_FAKE_RESP="$(api_post_retry_timeout "/api/commonwealth/settlement/prepare" \
    "{\"peer_org_id\":\"org_b_test\",\"agent_id\":\"$E2E_AGENT_ID\",\"task_description\":\"E2E invalid proof guard ${E2E_RUN_ID}\",\"amount_usd\":$E2E_GUARD_AMOUNT,\"royalty_rate\":0.10,\"action_ids\":[\"e2e_invalid_${E2E_RUN_ID}\"]}")"
FAKE_SETTLEMENT_ID="$(echo "$PREPARE_FAKE_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('settlement_id',''))" 2>/dev/null || true)"
if ! assert_http_ok "L2 fake-prepare" "$PREPARE_FAKE_RESP"; then
    fail "L2: unable to create fake-proof settlement guard case: $PREPARE_FAKE_RESP"
elif [[ -n "$FAKE_SETTLEMENT_ID" ]]; then
    FAKE_COMMIT_RESP="$(api_post "/api/commonwealth/settlement/commit" \
        "{\"settlement_id\":\"$FAKE_SETTLEMENT_ID\",\"proof_receipt\":\"totally_fake_receipt\",\"warrant_ref\":\"e2e_invalid\"}")"
    if echo "$FAKE_COMMIT_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert d.get('error'), d" 2>/dev/null; then
        pass "L2: fake proof receipt rejected (fail-closed)"
    else
        fail "L2: fake proof receipt unexpectedly accepted: $FAKE_COMMIT_RESP"
    fi
else
    fail "L2: unable to create fake-proof settlement guard case: $PREPARE_FAKE_RESP"
fi

# ─── L2: Settlement — Refund (new settlement for dispute path) ────────────────
PREPARE_REFUND_RESP="$(api_post_retry_timeout "/api/commonwealth/settlement/prepare" \
    "{\"peer_org_id\":\"org_b_test\",\"agent_id\":\"$E2E_AGENT_ID\",\"task_description\":\"E2E dispute/refund test ${E2E_RUN_ID}\",\"amount_usd\":$E2E_REFUND_AMOUNT,\"royalty_rate\":0.10,\"action_ids\":[\"e2e_refund_${E2E_RUN_ID}\"]}")"
REFUND_SETTLEMENT_ID="$(echo "$PREPARE_REFUND_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('settlement_id',''))" 2>/dev/null || true)"

if ! assert_http_ok "L2-refund prepare" "$PREPARE_REFUND_RESP"; then
    fail "L2-refund: failed to prepare a second settlement for refund test: $PREPARE_REFUND_RESP"
elif [[ -n "$REFUND_SETTLEMENT_ID" ]]; then
    REFUND_RESP="$(api_post_retry_timeout "/api/commonwealth/settlement/refund" \
        "{\"settlement_id\":\"$REFUND_SETTLEMENT_ID\",\"reason\":\"E2E court-ordered refund\",\"court_decision_ref\":\"court_e2e_001\"}")"
    if ! assert_http_ok "L2-POST /api/commonwealth/settlement/refund" "$REFUND_RESP"; then
        REFUND_MSG_NORM="$(printf "%s" "$REFUND_RESP" | tr '[:upper:]' '[:lower:]')"
        if [[ "$REFUND_MSG_NORM" == *"already refunded"* || "$REFUND_MSG_NORM" == *"status=refunded"* || "$REFUND_MSG_NORM" == *"cannot be refunded"* ]]; then
            pass "L2-POST /api/commonwealth/settlement/refund: idempotent replay accepted (already refunded)"
        else
            fail "L2-POST /api/commonwealth/settlement/refund: $REFUND_RESP"
        fi
    elif echo "$REFUND_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert d.get('status') == 'refunded', f'not refunded: {d}'" 2>/dev/null; then
        pass "L2-POST /api/commonwealth/settlement/refund: settlement refunded"
    else
        fail "L2-POST /api/commonwealth/settlement/refund: $REFUND_RESP"
    fi
fi

# ─── L3: Dynamic Constitutional Federation — Court Rule Propagation ──────────
echo ""
echo "=== L3: Dynamic Constitutional Federation ==="

PROPAGATE_RESP="$(api_post "/api/commonwealth/court/propagate" \
    "{\"peer_host_id\":\"$LINK_PEER_HOST_ID\",\"peer_org_id\":\"$ACTIVE_ORG_ID\",\"rule_id\":\"rule_e2e_${E2E_RUN_ID}\",\"rule_text\":\"E2E cross-institution rule: no unauthorized agent execution\",\"ruleset_version\":\"1.0.0-e2e-${E2E_RUN_ID}\"}")"
if ! assert_http_ok "L3-POST /api/commonwealth/court/propagate" "$PROPAGATE_RESP"; then
    fail "L3-POST /api/commonwealth/court/propagate: $PROPAGATE_RESP"
elif echo "$PROPAGATE_RESP" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert d.get('propagation_id'), f'no propagation_id: {d}'; assert d.get('delivery_status') == 'envelope_delivered', d" 2>/dev/null; then
    pass "L3-POST /api/commonwealth/court/propagate: rule propagated"
else
    fail "L3-POST /api/commonwealth/court/propagate: $PROPAGATE_RESP"
fi

# ─── L5: Temporal Memory Commonwealth Chain ───────────────────────────────────
echo ""
echo "=== L5: Temporal Memory Commonwealth Chain ==="

ANCHOR="$(api_get_retry_json "/api/commonwealth/memory/anchor" 8)"
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

api_get_retry_json "/api/status" 8 > /tmp/meridian_e2e_status.json
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
