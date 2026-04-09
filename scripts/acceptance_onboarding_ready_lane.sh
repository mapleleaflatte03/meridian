#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

find_free_port() {
  python3 - <<'PY'
import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

ONBOARDING_WORKSPACE_PORT="${MERIDIAN_TEST_WORKSPACE_PORT:-$(find_free_port)}"
ONBOARDING_GATEWAY_PORT="${MERIDIAN_TEST_GATEWAY_PORT:-$(find_free_port)}"
if [[ "${ONBOARDING_WORKSPACE_PORT}" == "${ONBOARDING_GATEWAY_PORT}" ]]; then
  ONBOARDING_GATEWAY_PORT="$(find_free_port)"
fi
export ONBOARDING_GATEWAY_PORT

if [ ! -x "./scripts/new-first-agent.sh" ]; then
  echo "[onboarding-lane] missing executable helper: ./scripts/new-first-agent.sh" >&2
  exit 1
fi
if [ ! -x "./scripts/dev-supervisor.sh" ]; then
  echo "[onboarding-lane] missing executable helper: ./scripts/dev-supervisor.sh" >&2
  exit 1
fi

echo "[onboarding-lane] bootstrap full stack (skip loom build for fast/portable gate)"
bootstrap_ok=0
for bootstrap_attempt in 1 2 3; do
  if [[ "${bootstrap_attempt}" -gt 1 ]]; then
    ONBOARDING_WORKSPACE_PORT="$(find_free_port)"
    ONBOARDING_GATEWAY_PORT="$(find_free_port)"
    if [[ "${ONBOARDING_WORKSPACE_PORT}" == "${ONBOARDING_GATEWAY_PORT}" ]]; then
      ONBOARDING_GATEWAY_PORT="$(find_free_port)"
    fi
    export ONBOARDING_GATEWAY_PORT
    ./scripts/dev-down.sh >/dev/null 2>&1 || true
    sleep 1
  fi
  echo "[onboarding-lane] bootstrap attempt ${bootstrap_attempt}/3"
  echo "[onboarding-lane] ports workspace=${ONBOARDING_WORKSPACE_PORT} gateway=${ONBOARDING_GATEWAY_PORT}"
  if MERIDIAN_SKIP_LOOM_BUILD=1 \
    MERIDIAN_AUTO_START_STACK=1 \
    MERIDIAN_WORKSPACE_PORT="${ONBOARDING_WORKSPACE_PORT}" \
    MERIDIAN_GATEWAY_PORT="${ONBOARDING_GATEWAY_PORT}" \
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

def get_json(path: str, *, required: bool = True):
    last_error = None
    for attempt in range(60):
        try:
            with urllib.request.urlopen(BASE + path, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {502, 503, 504}:
                raise
        except urllib.error.URLError as exc:
            last_error = exc
        time.sleep(min(1.0, 0.2 + (0.05 * attempt)))
    if required:
        raise RuntimeError(f"API probe failed for {path}: {last_error}")
    return None

def post_json(path: str, payload: dict, *, allow_forbidden: bool = False):
    body = json.dumps(payload).encode("utf-8")
    last_error = None
    for attempt in range(40):
        request = urllib.request.Request(
            BASE + path,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
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
            if exc.code not in {502, 503, 504}:
                raise last_error
        except urllib.error.URLError as exc:
            last_error = exc
        time.sleep(min(1.0, 0.2 + (0.05 * attempt)))
    raise RuntimeError(f"POST probe failed for {path}: {last_error}")

status = get_json("/api/status")
template = get_json("/api/institution/template")
treasury = get_json("/api/treasury")
runtime_proof = get_json("/api/runtime-proof", required=False)
runtime_proof_contract = get_json("/api/runtime-proof-contract", required=False)
kernel_bundle = get_json("/api/kernel-proof-bundle", required=False)
agents_payload = get_json("/api/agents")

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
    proof_block = dict(status.get("proof") or {})
    recursive = dict(proof_block.get("recursive") or {})
    aggregate = dict(proof_block.get("aggregate") or {})
    assert recursive.get("root") or aggregate.get("bundle_id"), status

if isinstance(kernel_bundle, dict):
    assert kernel_bundle.get("proof_bundle_version"), kernel_bundle
else:
    aggregate = dict((status.get("proof") or {}).get("aggregate") or {})
    assert aggregate.get("bundle_id"), status

agents = []
if isinstance(agents_payload, dict):
    if isinstance(agents_payload.get("output"), list):
        agents = agents_payload["output"]
    elif isinstance(agents_payload.get("agents"), list):
        agents = agents_payload["agents"]
assert agents, agents_payload
agent_id = str(agents[0].get("id") or "").strip()
assert agent_id, agents[0]

# Marketplace full-stack smoke: bid -> assign -> settle -> dispute(stay/refund)
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

    assignment = post_json("/api/marketplace/assign", {"bid_id": bid_id})
    reservation_id = str(assignment.get("reservation_id") or "").strip()
    assert reservation_id, assignment

    settlement = post_json(
        "/api/marketplace/settle",
        {
            "bid_id": bid_id,
            "proof_receipt": f"proof_onboarding_{stamp}",
            "reservation_id": reservation_id,
        },
    )
    split = settlement.get("split") or {}
    total = float(split.get("total_usd") or 0.0)
    worker = float(split.get("worker_usd") or 0.0)
    royalty = float(split.get("royalty_usd") or 0.0)
    assert round(worker + royalty, 4) == round(total, 4), settlement

    opened_dispute = post_json(
        "/api/marketplace/dispute",
        {
            "bid_id": bid_id,
            "reason": "acceptance_dispute_lifecycle",
            "action_ids": ["acceptance_onboarding_marketplace_dispute"],
        },
    )
    dispute_id = str(opened_dispute.get("dispute_id") or "").strip()
    assert dispute_id, opened_dispute

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

    refunded_dispute = post_json(
        "/api/marketplace/dispute",
        {
            "dispute_id": dispute_id,
            "decision": "refund",
            "reservation_id": reservation_id,
            "court_decision_ref": f"court_acceptance_refund_{stamp}",
        },
    )
    release_status = ((refunded_dispute.get("treasury_release") or {}).get("status") or "").strip().lower()
    assert release_status in {"released", "refunded"}, refunded_dispute

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
    vote = post_json(
        "/api/court/vote",
        {
            "proposal_id": proposal_id,
            "vote": "for",
            "justification": "acceptance lane requires activation lifecycle smoke",
        },
    )
    assert (vote.get("vote") or {}).get("vote") == "for", vote
    tally = post_json("/api/court/tally", {"proposal_id": proposal_id})
    assert bool((tally.get("tally") or {}).get("approved")), tally
    activation = post_json("/api/court/proposals/activate", {"proposal_id": proposal_id})
    rule_id = str(activation.get("rule_id") or "").strip()
    assert rule_id, activation
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

if [ "${MERIDIAN_SUPERVISOR_ENABLE:-1}" = "1" ]; then
  if [ ! -f "runtime/pids/supervisor.pid" ]; then
    echo "[onboarding-lane] missing runtime/pids/supervisor.pid while supervisor is enabled" >&2
    exit 1
  fi
  echo "[onboarding-lane] supervisor status snapshot"
  ./scripts/dev-supervisor.sh status
fi

echo "[onboarding-lane] PASS"
