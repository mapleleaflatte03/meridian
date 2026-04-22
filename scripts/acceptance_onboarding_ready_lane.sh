#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

SUPERVISOR_SERVICE_NAME="meridian-runtime-supervisor.service"
SUPERVISOR_SERVICE_WAS_ACTIVE=0
SUPERVISOR_SERVICE_SEEN=0
SUPERVISOR_PROCESS_WAS_ACTIVE=0

cleanup_on_exit() {
  ./scripts/dev-down.sh >/dev/null 2>&1 || true
  if [[ "${SUPERVISOR_SERVICE_SEEN}" -eq 1 && "${SUPERVISOR_SERVICE_WAS_ACTIVE}" -eq 1 ]]; then
    systemctl --user start "${SUPERVISOR_SERVICE_NAME}" >/dev/null 2>&1 || true
  fi
  if [[ "${SUPERVISOR_PROCESS_WAS_ACTIVE}" -eq 1 && "${SUPERVISOR_SERVICE_WAS_ACTIVE}" -eq 0 ]]; then
    MERIDIAN_SUPERVISOR_ENABLE=1 ./scripts/dev-up.sh --no-summary >/dev/null 2>&1 || true
  fi
}
trap cleanup_on_exit EXIT

if command -v systemctl >/dev/null 2>&1; then
  if systemctl --user list-unit-files 2>/dev/null | grep -q "^${SUPERVISOR_SERVICE_NAME}"; then
    SUPERVISOR_SERVICE_SEEN=1
    if [[ "$(systemctl --user is-active "${SUPERVISOR_SERVICE_NAME}" 2>/dev/null || true)" == "active" ]]; then
      SUPERVISOR_SERVICE_WAS_ACTIVE=1
      echo "[onboarding-lane] stopping ${SUPERVISOR_SERVICE_NAME} for isolated bootstrap gate"
      systemctl --user stop "${SUPERVISOR_SERVICE_NAME}" >/dev/null 2>&1 || true
      sleep 1
    fi
  fi
fi

if pgrep -f "scripts/dev-supervisor.sh run" >/dev/null 2>&1; then
  SUPERVISOR_PROCESS_WAS_ACTIVE=1
  echo "[onboarding-lane] stopping standalone dev-supervisor loop for isolated bootstrap gate"
  pkill -f "scripts/dev-supervisor.sh run" >/dev/null 2>&1 || true
  sleep 1
fi

./scripts/dev-supervisor.sh stop >/dev/null 2>&1 || true
./scripts/dev-down.sh >/dev/null 2>&1 || true
sleep 1

if pgrep -f "/home/ubuntu/meridian/intelligence/company/meridian_platform/workspace.py" >/dev/null 2>&1; then
  echo "[onboarding-lane] stopping orphan workspace.py processes for isolated bootstrap gate"
  pkill -f "/home/ubuntu/meridian/intelligence/company/meridian_platform/workspace.py" >/dev/null 2>&1 || true
  sleep 1
fi
if pgrep -f "/home/ubuntu/meridian/intelligence/meridian_gateway.py" >/dev/null 2>&1; then
  echo "[onboarding-lane] stopping orphan meridian_gateway.py processes for isolated bootstrap gate"
  pkill -f "/home/ubuntu/meridian/intelligence/meridian_gateway.py" >/dev/null 2>&1 || true
  sleep 1
fi

if pgrep -f "scripts/dev-supervisor.sh run" >/dev/null 2>&1; then
  echo "[onboarding-lane] unable to isolate runtime: dev-supervisor loop still running" >&2
  exit 1
fi
if pgrep -f "/home/ubuntu/meridian/intelligence/company/meridian_platform/workspace.py" >/dev/null 2>&1; then
  echo "[onboarding-lane] unable to isolate runtime: orphan workspace.py process still running" >&2
  exit 1
fi
if pgrep -f "/home/ubuntu/meridian/intelligence/meridian_gateway.py" >/dev/null 2>&1; then
  echo "[onboarding-lane] unable to isolate runtime: orphan meridian_gateway.py process still running" >&2
  exit 1
fi

find_free_port() {
  python3 - <<'PY'
import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

ONBOARDING_WORKSPACE_PORT="${MERIDIAN_TEST_WORKSPACE_PORT:-$(find_free_port)}"
ONBOARDING_WORKSPACE_PEER_PORT="${MERIDIAN_TEST_WORKSPACE_PEER_PORT:-$(find_free_port)}"
ONBOARDING_GATEWAY_PORT="${MERIDIAN_TEST_GATEWAY_PORT:-$(find_free_port)}"
if [[ "${ONBOARDING_WORKSPACE_PORT}" == "${ONBOARDING_GATEWAY_PORT}" ]]; then
  ONBOARDING_GATEWAY_PORT="$(find_free_port)"
fi
if [[ "${ONBOARDING_WORKSPACE_PORT}" == "${ONBOARDING_WORKSPACE_PEER_PORT}" ]]; then
  ONBOARDING_WORKSPACE_PEER_PORT="$(find_free_port)"
fi
if [[ "${ONBOARDING_GATEWAY_PORT}" == "${ONBOARDING_WORKSPACE_PEER_PORT}" ]]; then
  ONBOARDING_WORKSPACE_PEER_PORT="$(find_free_port)"
fi
export ONBOARDING_GATEWAY_PORT
export ONBOARDING_WORKSPACE_PORT

if [ ! -x "./scripts/new-first-agent.sh" ]; then
  echo "[onboarding-lane] missing executable helper: ./scripts/new-first-agent.sh" >&2
  exit 1
fi
if [ ! -x "./scripts/dev-supervisor.sh" ]; then
  echo "[onboarding-lane] missing executable helper: ./scripts/dev-supervisor.sh" >&2
  exit 1
fi
if [ ! -x "./scripts/onboard.sh" ]; then
  echo "[onboarding-lane] missing executable helper: ./scripts/onboard.sh" >&2
  exit 1
fi

echo "[onboarding-lane] bootstrap full stack (skip loom build for fast/portable gate)"
bootstrap_ok=0
for bootstrap_attempt in 1 2 3; do
  if [[ "${bootstrap_attempt}" -gt 1 ]]; then
    ONBOARDING_WORKSPACE_PORT="$(find_free_port)"
    ONBOARDING_WORKSPACE_PEER_PORT="$(find_free_port)"
    ONBOARDING_GATEWAY_PORT="$(find_free_port)"
    if [[ "${ONBOARDING_WORKSPACE_PORT}" == "${ONBOARDING_GATEWAY_PORT}" ]]; then
      ONBOARDING_GATEWAY_PORT="$(find_free_port)"
    fi
    if [[ "${ONBOARDING_WORKSPACE_PORT}" == "${ONBOARDING_WORKSPACE_PEER_PORT}" ]]; then
      ONBOARDING_WORKSPACE_PEER_PORT="$(find_free_port)"
    fi
    if [[ "${ONBOARDING_GATEWAY_PORT}" == "${ONBOARDING_WORKSPACE_PEER_PORT}" ]]; then
      ONBOARDING_WORKSPACE_PEER_PORT="$(find_free_port)"
    fi
    export ONBOARDING_GATEWAY_PORT
    export ONBOARDING_WORKSPACE_PORT
    ./scripts/dev-down.sh >/dev/null 2>&1 || true
    sleep 1
  fi
  echo "[onboarding-lane] bootstrap attempt ${bootstrap_attempt}/3"
  echo "[onboarding-lane] ports workspace=${ONBOARDING_WORKSPACE_PORT} peer=${ONBOARDING_WORKSPACE_PEER_PORT} gateway=${ONBOARDING_GATEWAY_PORT}"
  if MERIDIAN_INSTALL_MODE=demo \
    MERIDIAN_SKIP_LOOM_BUILD=1 \
    MERIDIAN_AUTO_START_STACK=1 \
    MERIDIAN_WORKSPACE_PORT="${ONBOARDING_WORKSPACE_PORT}" \
    MERIDIAN_WORKSPACE_PEER_PORT="${ONBOARDING_WORKSPACE_PEER_PORT}" \
    MERIDIAN_GATEWAY_PORT="${ONBOARDING_GATEWAY_PORT}" \
    MERIDIAN_PEER_WORKSPACE_ENABLED=0 \
    MERIDIAN_SUPERVISOR_ENABLE=0 \
    ./scripts/bootstrap_full.sh >/tmp/meridian_onboarding_bootstrap.log 2>&1; then
    bootstrap_ok=1
    break
  fi
  echo "[onboarding-lane] bootstrap attempt ${bootstrap_attempt} failed" >&2
done

if [[ "${bootstrap_ok}" -ne 1 ]]; then
  echo "[onboarding-lane] bootstrap failed after 3 attempts; dumping /tmp/meridian_onboarding_bootstrap.log" >&2
  cat /tmp/meridian_onboarding_bootstrap.log >&2 || true
  exit 1
fi

echo "[onboarding-lane] validate bootstrap smoke report"
python3 - <<'PY'
import json
from pathlib import Path

report_path = Path("runtime/bootstrap_gateway_smoke.json")
assert report_path.exists(), "missing runtime/bootstrap_gateway_smoke.json"
payload = json.loads(report_path.read_text(encoding="utf-8"))

assert payload.get("status") == "ok", payload
assert payload.get("institution_template_schema") == "meridian.institution_template.v1", payload
assert int(payload.get("court_rule_count") or 0) >= 3, payload
assert payload.get("treasury_balance_usd") is not None, payload
assert payload.get("treasury_reserve_floor_usd") is not None, payload
assert payload.get("runtime_id"), payload
PY

echo "[onboarding-lane] verify local API readiness contract"
python3 - <<'PY'
import json
import os
import time
import datetime
from pathlib import Path
import urllib.request
import urllib.error

BASE = f"http://127.0.0.1:{os.environ['ONBOARDING_GATEWAY_PORT']}"
HTTP_TIMEOUT_SECONDS = float(os.environ.get("MERIDIAN_ACCEPTANCE_HTTP_TIMEOUT", "20"))

def step(label: str):
    print(f"[onboarding-lane] {label}", flush=True)

def get_json(path: str, *, required: bool = True):
    last_error = None
    for attempt in range(20):
        try:
            with urllib.request.urlopen(BASE + path, timeout=HTTP_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {502, 503, 504}:
                raise
        except (urllib.error.URLError, TimeoutError, Exception) as exc:
            last_error = exc
        time.sleep(min(1.0, 0.2 + (0.05 * attempt)))
    if required:
        raise RuntimeError(f"API probe failed for {path}: {last_error}")
    return None

def post_json(path: str, payload: dict, *, allow_forbidden: bool = False, accept_statuses=None):
    accepted = set(accept_statuses or [])
    body = json.dumps(payload).encode("utf-8")
    last_error = None
    for attempt in range(12):
        request = urllib.request.Request(
            BASE + path,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"{exc.code} {path}: {raw}")
            if allow_forbidden and exc.code in {401, 403}:
                return {
                    "_forbidden": True,
                    "status_code": exc.code,
                    "raw": raw,
                }
            if exc.code in accepted:
                parsed = None
                try:
                    parsed = json.loads(raw)
                except Exception:
                    parsed = None
                return {
                    "_http_error": True,
                    "status_code": exc.code,
                    "raw": raw,
                    "payload": parsed,
                }
            if exc.code not in {502, 503, 504}:
                raise last_error
        except (urllib.error.URLError, TimeoutError, Exception) as exc:
            last_error = exc
        time.sleep(min(1.0, 0.2 + (0.05 * attempt)))
    raise RuntimeError(f"POST probe failed for {path}: {last_error}")

def ensure_treasury_headroom(required_usd: float, *, note: str):
    def metric(payload: dict, key: str, default: float = 0.0) -> float:
        value = payload.get(key)
        if value is None:
            value = (payload.get("runtime_budget") or {}).get(key)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    snapshot = get_json("/api/treasury")
    shortfall = metric(snapshot, "shortfall_usd", 0.0)
    available = metric(snapshot, "available_for_reservation_usd", 0.0)
    if shortfall <= 1e-6 and available + 1e-9 >= required_usd:
        return snapshot
    topup = round(max(shortfall, required_usd - available, 0.0) + 5.0, 2)
    contribute = post_json(
        "/api/treasury/contribute",
        {
            "amount": topup,
            "note": note,
        },
    )
    refreshed = contribute.get("snapshot") if isinstance(contribute, dict) else None
    if not isinstance(refreshed, dict):
        refreshed = get_json("/api/treasury")
    refreshed_available = metric(refreshed, "available_for_reservation_usd", 0.0)
    refreshed_shortfall = metric(refreshed, "shortfall_usd", 0.0)
    assert refreshed_shortfall <= 1e-6, refreshed
    assert refreshed_available + 1e-9 >= required_usd, refreshed
    return refreshed

status = get_json("/api/status")
step("status probe complete")
template = get_json("/api/institution/template")
treasury = get_json("/api/treasury")
runtime_proof = get_json("/api/runtime-proof", required=False)
runtime_proof_contract = get_json("/api/runtime-proof-contract", required=False)
kernel_bundle = get_json("/api/kernel-proof-bundle", required=False)
agents_payload = get_json("/api/agents")
step("institution/template/treasury/proof probes complete")

assert status.get("runtime_id"), status
slo = status.get("slo") or {}
assert slo.get("status") in {"healthy", "warning", "breach"}, status

status_blob = json.dumps(status).lower()
for banned in ("founder", "founding", "commercial", "checkout", "license"):
    assert banned not in status_blob, f"legacy wording '{banned}' found in /api/status"

assert template.get("schema_version") == "meridian.institution_template.v1", template
assert len(template.get("court_rule_set") or []) >= 3, template
assert isinstance(template.get("policy_defaults"), dict), template

assert treasury.get("balance_usd") is not None, treasury
assert treasury.get("reserve_floor_usd") is not None, treasury

if isinstance(runtime_proof_contract, dict):
    contract_block = runtime_proof_contract.get("runtime_proof_contract") or {}
    assert contract_block.get("proof_chain_status") in {"complete", "partial", "degraded"}, runtime_proof_contract
    assert contract_block.get("runtime_proof_status") in {"proven", "degraded"}, runtime_proof_contract

if isinstance(runtime_proof, dict):
    assert runtime_proof.get("runtime_id"), runtime_proof
else:
    runtime_proof_meta = dict(status.get("runtime_proof") or {})
    assert runtime_proof_meta.get("route") == "/api/runtime-proof", status
    assert runtime_proof_meta.get("contract_route") == "/api/runtime-proof-contract", status

if isinstance(kernel_bundle, dict):
    assert kernel_bundle.get("proof_bundle_version"), kernel_bundle
else:
    runtime_proof_meta = dict(status.get("runtime_proof") or {})
    assert runtime_proof_meta.get("kernel_bundle_route") == "/api/kernel-proof-bundle", status

agents = []
if isinstance(agents_payload, dict):
    if isinstance(agents_payload.get("output"), list):
        agents = agents_payload["output"]
    elif isinstance(agents_payload.get("agents"), list):
        agents = agents_payload["agents"]
assert agents, agents_payload
bound_org_id = str(
    ((status.get("context") or {}).get("bound_org_id"))
    or ((status.get("institution") or {}).get("id"))
    or ""
).strip()

def agent_matches_bound_org(agent: dict) -> bool:
    runtime_binding = agent.get("runtime_binding") or {}
    return str(
        runtime_binding.get("bound_org_id")
        or agent.get("org_id")
        or ""
    ).strip() == bound_org_id

selected_agent = next((agent for agent in agents if agent_matches_bound_org(agent)), agents[0])
agent_id = str(selected_agent.get("id") or "").strip()
assert agent_id, selected_agent

onboard_script = Path("scripts/onboard.sh").read_text(encoding="utf-8")
assert "Config root:" in onboard_script, "onboard.sh missing config-root summary"
assert "LOOM_CONFIG_ROOT" in onboard_script, "onboard.sh should print computed Loom config root"
assert "What is local (your machine only):" in onboard_script, "onboard.sh missing local/private/public boundary copy"
assert "https://app.welliam.codes is a public showcase." in onboard_script, "onboard.sh missing public showcase boundary line"
assert "MERIDIAN_ORG_ID=" in onboard_script and "MERIDIAN_WORKSPACE_ORG_ID=" in onboard_script, "onboard.sh missing explicit org-bound dev-up instruction"
new_first_agent_script = Path("scripts/new-first-agent.sh").read_text(encoding="utf-8")
assert "MERIDIAN_ORG_ID is required" in new_first_agent_script, "new-first-agent helper lost explicit org requirement"

# Marketplace full-stack smoke: bid -> assign -> settle -> dispute(stay/refund)
ensure_treasury_headroom(
    required_usd=0.25,
    note="acceptance_onboarding_marketplace_headroom",
)
step("treasury headroom validated for marketplace lifecycle")
stamp = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
bid = post_json(
    "/api/marketplace/bids",
    {
        "agent_id": agent_id,
        "task_description": f"onboarding-ready-{stamp}",
        "amount_usd": 0.05,
        "action_ids": ["acceptance_onboarding_marketplace"],
    },
    allow_forbidden=True,
)
if bid.get("_forbidden"):
    marketplace_snapshot = get_json("/api/marketplace")
    assert isinstance(marketplace_snapshot.get("status"), dict), marketplace_snapshot
else:
    bid_id = str(bid.get("bid_id") or "").strip()
    assert bid_id, bid

    step(f"marketplace bid posted ({bid_id})")
    assignment = post_json(
        "/api/marketplace/assign",
        {"bid_id": bid_id},
        allow_forbidden=True,
        accept_statuses={400, 409},
    )
    reservation_id = ""
    if assignment.get("_forbidden"):
        marketplace_snapshot = get_json("/api/marketplace")
        assert isinstance(marketplace_snapshot.get("status"), dict), marketplace_snapshot
    elif assignment.get("_http_error"):
        raw = str(assignment.get("raw") or "").lower()
        if "treasury_reserve_denied" in raw:
            marketplace_snapshot = get_json("/api/marketplace")
            assert isinstance(marketplace_snapshot.get("status"), dict), marketplace_snapshot
            reservation_id = ""
        if "status=assigned" in raw or "not open" in raw:
            marketplace_snapshot = get_json("/api/marketplace")
            assignments = list(marketplace_snapshot.get("assignments") or [])
            matches = [
                row for row in assignments
                if str(row.get("bid_id") or "").strip() == bid_id
            ]
            if matches:
                reservation_id = str(matches[-1].get("reservation_id") or "").strip()
            else:
                raise AssertionError(f"unexpected marketplace assign error: {assignment}")
        elif "treasury_reserve_denied" not in raw:
            raise AssertionError(f"unexpected marketplace assign error: {assignment}")
    else:
        reservation_id = str(assignment.get("reservation_id") or "").strip()

    if not reservation_id:
        marketplace_snapshot = get_json("/api/marketplace")
        assignments = list(marketplace_snapshot.get("assignments") or [])
        matches = [
            row for row in assignments
            if str(row.get("bid_id") or "").strip() == bid_id
        ]
        if matches:
            reservation_id = str(matches[-1].get("reservation_id") or "").strip()
    if not reservation_id:
        marketplace_snapshot = get_json("/api/marketplace")
        assert isinstance(marketplace_snapshot.get("status"), dict), marketplace_snapshot
        reservation_id = ""
    else:
        step(f"marketplace bid assigned ({bid_id}, reservation={reservation_id})")

    if reservation_id:
        settlement = post_json(
            "/api/marketplace/settle",
            {
                "bid_id": bid_id,
                "proof_receipt": f"proof_onboarding_{stamp}",
                "reservation_id": reservation_id,
            },
            accept_statuses={400},
        )
        if settlement.get("_http_error"):
            raw = str(settlement.get("raw") or "").lower()
            if "status=settled" in raw:
                marketplace_snapshot = get_json("/api/marketplace")
                settlements = list(marketplace_snapshot.get("settlements") or [])
                matches = [row for row in settlements if row.get("bid_id") == bid_id]
                assert matches, marketplace_snapshot
                settlement = matches[-1]
            else:
                raise AssertionError(f"unexpected marketplace settle error: {settlement}")
        split = settlement.get("split") or {}
        total = float(split.get("total_usd") or 0.0)
        worker = float(split.get("worker_usd") or 0.0)
        royalty = float(split.get("royalty_usd") or 0.0)
        assert round(worker + royalty, 4) == round(total, 4), settlement
        step(f"marketplace bid settled ({bid_id})")

        opened_dispute = post_json(
            "/api/marketplace/dispute",
            {
                "bid_id": bid_id,
                "reason": "acceptance_dispute_lifecycle",
                "action_ids": ["acceptance_onboarding_marketplace_dispute"],
            },
            accept_statuses={400},
        )
        if opened_dispute.get("_http_error"):
            raw = str(opened_dispute.get("raw") or "").lower()
            if "cannot be disputed (status=disputed)" in raw:
                marketplace_snapshot = get_json("/api/marketplace")
                bids = list(marketplace_snapshot.get("bids") or [])
                disputes = list(marketplace_snapshot.get("disputes") or [])
                active_bid = next((row for row in bids if row.get("id") == bid_id), {})
                existing_dispute_id = str(active_bid.get("dispute_id") or "").strip()
                if existing_dispute_id:
                    opened_dispute = next(
                        (row for row in disputes if row.get("id") == existing_dispute_id),
                        {"dispute_id": existing_dispute_id},
                    )
            else:
                raise AssertionError(f"unexpected marketplace dispute-open error: {opened_dispute}")
        dispute_id = str(opened_dispute.get("dispute_id") or opened_dispute.get("id") or "").strip()
        assert dispute_id, opened_dispute
        step(f"marketplace dispute opened ({dispute_id})")

    stayed_dispute = post_json(
        "/api/marketplace/dispute",
        {
            "dispute_id": dispute_id,
            "decision": "stay",
            "reservation_id": reservation_id,
            "court_decision_ref": f"court_acceptance_stay_{stamp}",
        },
    )
    assert (stayed_dispute.get("dispute") or {}).get("decision") == "stay", stayed_dispute
    step(f"marketplace dispute stayed ({dispute_id})")

    refunded_dispute = post_json(
        "/api/marketplace/dispute",
        {
            "dispute_id": dispute_id,
            "decision": "refund",
            "reservation_id": reservation_id,
            "court_decision_ref": f"court_acceptance_refund_{stamp}",
        },
        accept_statuses={400},
    )
    treasury_release = refunded_dispute.get("treasury_release") or {}
    release_status = (treasury_release.get("status") or "").strip().lower()
    if refunded_dispute.get("_http_error"):
        raw = str(refunded_dispute.get("raw") or "").lower()
        if "already resolved" in raw:
            marketplace_snapshot = get_json("/api/marketplace")
            disputes = list(marketplace_snapshot.get("disputes") or [])
            resolved = next((row for row in disputes if row.get("id") == dispute_id), None)
            assert resolved and (resolved.get("status") or "").lower() == "resolved", marketplace_snapshot
            decision = (resolved.get("decision") or "").strip().lower()
            assert decision in {"refund", "release"}, resolved
            release_status = "refunded" if decision == "refund" else "released"
        else:
            raise AssertionError(f"unexpected marketplace dispute-refund error: {refunded_dispute}")
    if release_status == "error":
        dispute_obj = refunded_dispute.get("dispute") or {}
        if (dispute_obj.get("decision") or "").strip().lower() == "refund":
            release_status = "refunded"
        elif (dispute_obj.get("decision") or "").strip().lower() in {"stay", "release"}:
            release_status = "released"
    assert release_status in {"released", "refunded"}, refunded_dispute
    step(f"marketplace dispute refunded ({dispute_id})")

    marketplace_snapshot = get_json("/api/marketplace")
    settlements = list(marketplace_snapshot.get("settlements") or [])
    matching_settlements = [row for row in settlements if row.get("bid_id") == bid_id]
    assert matching_settlements, marketplace_snapshot
    assert matching_settlements[-1].get("proof_receipt"), matching_settlements[-1]
    assert matching_settlements[-1].get("reservation_id") == reservation_id, matching_settlements[-1]

# Dynamic court lifecycle smoke: proposal -> vote -> tally -> activate
proposal = post_json(
    "/api/court/proposals",
    {
        "title": f"onboarding-court-{stamp}",
        "rule_text": "onboarding_ready_lane=true",
    },
    allow_forbidden=True,
)
if proposal.get("_forbidden"):
    rules = get_json("/api/court/rules")
    assert isinstance(rules.get("rules"), list), rules
else:
    proposal_id = str(proposal.get("proposal_id") or "").strip()
    assert proposal_id, proposal
    step(f"court proposal created ({proposal_id})")
    vote = post_json(
        "/api/court/vote",
        {
            "proposal_id": proposal_id,
            "vote": "for",
            "justification": "acceptance lane requires activation lifecycle smoke",
        },
    )
    assert (vote.get("vote") or {}).get("vote") == "for", vote
    step(f"court vote submitted ({proposal_id})")
    tally = post_json("/api/court/tally", {"proposal_id": proposal_id})
    assert bool((tally.get("tally") or {}).get("approved")), tally
    step(f"court tally approved ({proposal_id})")
    activation = post_json("/api/court/proposals/activate", {"proposal_id": proposal_id})
    rule_id = str(activation.get("rule_id") or "").strip()
    assert rule_id, activation
    step(f"court rule activated ({rule_id})")
    rules = get_json("/api/court/rules")
    active_rules = list(rules.get("rules") or [])
    assert any((row.get("id") or "") == rule_id for row in active_rules), rules

status_after = get_json("/api/status")
dynamic = ((status_after.get("court") or {}).get("dynamic") or {})
assert dynamic.get("ruleset_version") is not None, status_after
active_rules = dynamic.get("active_rules")
assert active_rules is not None, status_after
try:
    active_rules_count = int(active_rules)
except (TypeError, ValueError) as exc:
    raise AssertionError(f"invalid court.dynamic.active_rules: {active_rules!r}") from exc
assert active_rules_count >= 0, status_after

install_script = (Path("scripts/install-full.sh")).read_text(encoding="utf-8")
assert "MERIDIAN_VERIFY_ONBOARDING" in install_script, "install-full.sh missing onboarding verification toggle"
PY

if [ "${MERIDIAN_SUPERVISOR_ENABLE:-0}" = "1" ]; then
  if [ ! -f "runtime/pids/supervisor.pid" ]; then
    echo "[onboarding-lane] missing runtime/pids/supervisor.pid while supervisor is enabled" >&2
    exit 1
  fi
  echo "[onboarding-lane] supervisor status snapshot"
  ./scripts/dev-supervisor.sh status
fi

echo "[onboarding-lane] PASS"
