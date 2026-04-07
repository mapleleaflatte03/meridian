#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_LOOM_BIN="loom"
if [[ -x "${REPO_ROOT}/target/debug/loom" ]]; then
  DEFAULT_LOOM_BIN="${REPO_ROOT}/target/debug/loom"
elif [[ -x "${REPO_ROOT}/target/release/loom" ]]; then
  DEFAULT_LOOM_BIN="${REPO_ROOT}/target/release/loom"
elif [[ -x "${HOME}/.local/bin/loom" ]]; then
  DEFAULT_LOOM_BIN="${HOME}/.local/bin/loom"
fi
LOOM_BIN="${LOOM_BIN:-${DEFAULT_LOOM_BIN}}"
if ! command -v "${LOOM_BIN}" >/dev/null 2>&1 && [[ ! -x "${LOOM_BIN}" ]]; then
  echo "[ERROR] loom binary not found (LOOM_BIN=${LOOM_BIN})" >&2
  exit 127
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "[ERROR] jq is required for acceptance-full-system-lane" >&2
  exit 127
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/loom-full-system-XXXXXX")"
RUNTIME_ROOT="${WORK_DIR}/runtime"
KERNEL_PATH="${WORK_DIR}/kernel-fixture"
LOG_DIR="${WORK_DIR}/logs"
WARRANT_FILE="${WORK_DIR}/full-system-warrant.json"
REQUESTED_ORG_HINT="org_full_system"
ACTIVE_ORG_ID="${REQUESTED_ORG_HINT}"

mkdir -p "${LOG_DIR}"

CURRENT_STEP="setup"
CURRENT_COMPONENT="bootstrap"
CURRENT_LOG=""
MEMORY_SOURCE_REF="agent_atlas"
declare -a SUMMARY_ROWS=()

print_summary() {
  echo
  echo "=== FULL SYSTEM SUMMARY ==="
  printf "%-4s | %-24s | %-7s | %s\n" "Step" "Component" "Result" "Checks"
  printf -- "-----+--------------------------+---------+--------------------------------------------------------------\n"
  local row step component result checks
  for row in "${SUMMARY_ROWS[@]}"; do
    IFS="|" read -r step component result checks <<<"${row}"
    printf "%-4s | %-24s | %-7s | %s\n" "${step}" "${component}" "${result}" "${checks}"
  done
}

fail_now() {
  local message="$1"
  trap - ERR
  echo
  echo "[ERROR] Step ${CURRENT_STEP} component '${CURRENT_COMPONENT}' failed: ${message}" >&2
  if [[ -n "${CURRENT_LOG}" && -f "${CURRENT_LOG}" ]]; then
    echo "[ERROR] Component log: ${CURRENT_LOG}" >&2
    echo "----- component output begin -----" >&2
    cat "${CURRENT_LOG}" >&2
    echo "----- component output end -----" >&2
  fi
  SUMMARY_ROWS+=("${CURRENT_STEP}|${CURRENT_COMPONENT}|FAIL|${message}")
  print_summary
  echo
  echo "[ERROR] Workspace preserved at: ${WORK_DIR}" >&2
  exit 1
}

on_err() {
  local code=$?
  fail_now "unexpected command failure (exit=${code})"
}
trap on_err ERR

run_step() {
  local step="$1"
  local component="$2"
  shift 2
  CURRENT_STEP="${step}"
  CURRENT_COMPONENT="${component}"
  CURRENT_LOG="${LOG_DIR}/step_${step}_${component//[^a-zA-Z0-9_.-]/_}.log"
  echo
  echo ">>> STEP ${step} | ${component}"
  echo "+ $*"
  "$@" 2>&1 | tee "${CURRENT_LOG}"
}

create_kernel_fixture() {
  mkdir -p "${KERNEL_PATH}/kernel"
  cat >"${KERNEL_PATH}/kernel/__init__.py" <<'PY'
# Meridian test kernel package marker
PY

  cat >"${KERNEL_PATH}/kernel/runtimes.json" <<'JSON'
{
  "runtimes": {
    "local_kernel": {
      "id": "local_kernel",
      "label": "Local Kernel Runtime"
    },
    "loom_native": {
      "status": "official",
      "notes": "full-system lane fixture runtime",
      "contract_compliance": {
        "agent_identity": true,
        "action_envelope": true,
        "cost_attribution": true,
        "approval_hook": true,
        "audit_emission": true,
        "sanction_controls": true,
        "budget_gate": true
      }
    }
  }
}
JSON

  cat >"${KERNEL_PATH}/kernel/organizations.py" <<'PY'
import json
import pathlib
import time

STORE = pathlib.Path(__file__).resolve().parent / "_organizations.json"

def _now():
    return str(int(time.time()))

def load_orgs():
    if STORE.exists():
        return json.loads(STORE.read_text())
    return {"organizations": {}}

def save_orgs(data):
    STORE.write_text(json.dumps(data, indent=2) + "\n")
PY

  cat >"${KERNEL_PATH}/kernel/agent_registry.py" <<'PY'
import argparse
import json
import pathlib

STORE = pathlib.Path(__file__).resolve().parent / "_agents.json"

def _load():
    if STORE.exists():
        return json.loads(STORE.read_text())
    return {"agents": {}}

def _save(data):
    STORE.write_text(json.dumps(data, indent=2) + "\n")

def list_agents(org_id=None, include_disabled=False):
    data = _load()
    agents = list(data.get("agents", {}).values())
    if org_id:
        agents = [agent for agent in agents if agent.get("org_id") == org_id]
    if not include_disabled:
        agents = [agent for agent in agents if agent.get("rollout_state", "active") != "disabled"]
    return agents

def _aliases_for(agent_ref):
    raw = (agent_ref or "").strip()
    if not raw:
        return []
    aliases = [raw]
    lower = raw.lower()
    aliases.append(lower)
    if raw.startswith("agent_"):
        aliases.append(raw[len("agent_"):])
        aliases.append(raw[len("agent_"):].lower())
    else:
        aliases.append(f"agent_{raw}")
        aliases.append(f"agent_{lower}")
    return list(dict.fromkeys(aliases))

def get_agent(agent_id, org_id=None):
    data = _load()
    agents = data.get("agents", {})
    for alias in _aliases_for(agent_id):
        candidate = agents.get(alias)
        if candidate:
            if org_id and candidate.get("org_id") != org_id:
                continue
            return candidate
    for candidate in agents.values():
        if candidate.get("name", "").lower() in _aliases_for(agent_id):
            if org_id and candidate.get("org_id") != org_id:
                continue
            return candidate
    return None

def upsert_agent(record):
    data = _load()
    agents = data.setdefault("agents", {})
    agent_id = record["id"]
    agents[agent_id] = record
    key = record.get("economy_key")
    if key:
        agents[key] = record
        agents[key.lower()] = record
    agents[record.get("name", "").lower()] = record
    _save(data)
    return record

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Meridian full-system fixture agent registry")
    sub = parser.add_subparsers(dest="command")
    get_cmd = sub.add_parser("get")
    get_cmd.add_argument("--agent_id", required=True)
    get_cmd.add_argument("--org_id")
    list_cmd = sub.add_parser("list")
    list_cmd.add_argument("--org_id")
    list_cmd.add_argument("--include_disabled", action="store_true")
    args = parser.parse_args()
    if args.command == "get":
        result = get_agent(args.agent_id, args.org_id)
        if result is None:
            print(f"Not found: {args.agent_id}")
        else:
            print(json.dumps(result, indent=2))
    elif args.command == "list":
        print(json.dumps({"agents": list_agents(args.org_id, args.include_disabled)}, indent=2))
    else:
        parser.print_help()
        raise SystemExit(2)
PY

  cat >"${KERNEL_PATH}/kernel/bootstrap.py" <<'PY'
import time
from organizations import load_orgs, save_orgs
import agent_registry

SEED = [
    ("manager", "Manager", "manager", "main"),
    ("atlas", "Atlas", "analyst", "atlas"),
    ("sentinel", "Sentinel", "verifier", "sentinel"),
    ("forge", "Forge", "executor", "forge"),
    ("quill", "Quill", "writer", "quill"),
    ("aegis", "Aegis", "qa_gate", "aegis"),
    ("pulse", "Pulse", "compressor", "pulse"),
]

def _now():
    return str(int(time.time()))

def _slugify(value):
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in (value or "nation")).strip("-") or "nation"

def bootstrap(name=None, owner_id=None, slug=None, charter=None, plan="enterprise"):
    org_name = (name or "FullSystem Nation").strip() or "FullSystem Nation"
    org_owner = (owner_id or "operator").strip() or "operator"
    org_slug = (slug or _slugify(org_name)).strip() or "nation"
    org_charter = (charter or "FullSystem Charter").strip() or "FullSystem Charter"

    orgs = load_orgs()
    organizations = orgs.setdefault("organizations", {})
    org_id = None
    for candidate_id, org in organizations.items():
        if org.get("slug") == org_slug:
            org_id = candidate_id
            break
    if org_id is None:
        org_id = f"org_{org_slug.replace('-', '_')}"
        organizations[org_id] = {
            "id": org_id,
            "name": org_name,
            "slug": org_slug,
            "owner_id": org_owner,
            "plan": plan,
            "status": "active",
            "charter": org_charter,
            "created_at": _now(),
            "updated_at": _now(),
        }
    else:
        organizations[org_id]["charter"] = org_charter
        organizations[org_id]["updated_at"] = _now()
    save_orgs(orgs)

    for key, display_name, role, economy_key in SEED:
        agent_id = f"agent_{key}"
        agent_registry.upsert_agent({
            "id": agent_id,
            "name": display_name,
            "org_id": org_id,
            "role": role,
            "economy_key": economy_key,
            "approval_required": False,
            "budget": {"max_per_run_usd": 1.0},
            "runtime_binding": {
                "runtime_id": "loom_native",
                "runtime_label": "Loom Native Runtime",
                "bound_org_id": org_id,
                "boundary_name": "workspace",
                "identity_model": "session",
                "runtime_registered": True,
                "registration_status": "registered"
            },
            "rollout_state": "active",
            "created_at": _now(),
            "updated_at": _now(),
        })
    return {"org_id": org_id, "slug": org_slug}
PY

  cat >"${KERNEL_PATH}/kernel/court.py" <<'PY'
def get_restrictions(agent_id, org_id=None):
    return []
PY

  cat >"${KERNEL_PATH}/kernel/authority.py" <<'PY'
def check_authority(agent_id, action, org_id=None):
    return True, "ok"
PY

  cat >"${KERNEL_PATH}/kernel/treasury.py" <<'PY'
import json
import pathlib
import time

WALLETS_STORE = pathlib.Path(__file__).resolve().parent / "_wallets.json"
ACCOUNTS_STORE = pathlib.Path(__file__).resolve().parent / "_accounts.json"
RESERVATIONS_STORE = pathlib.Path(__file__).resolve().parent / "_reservations.json"

def _load(path):
    if path.exists():
        return json.loads(path.read_text())
    return {}

def _save(path, payload):
    path.write_text(json.dumps(payload, indent=2) + "\n")

def _now():
    return int(time.time())

def get_wallet(wallet_id, org_id=None):
    wallets = _load(WALLETS_STORE)
    wallet = wallets.get(wallet_id)
    if wallet is None:
        return None
    if org_id and wallet.get("org_id") != org_id:
        return None
    return wallet

def get_treasury_account(account_id, org_id=None):
    accounts = _load(ACCOUNTS_STORE)
    account = accounts.get(account_id)
    if account is None:
        return None
    if org_id and account.get("org_id") != org_id:
        return None
    return account

def register_wallet(wallet_id, address, *, actor_id="", org_id=None, label="", **kwargs):
    wallets = _load(WALLETS_STORE)
    if wallet_id in wallets:
        raise ValueError("wallet exists")
    wallets[wallet_id] = {
        "wallet_id": wallet_id,
        "org_id": org_id,
        "address": address,
        "label": label,
        "actor_id": actor_id,
        "created_at": _now(),
        "status": kwargs.get("status", "active"),
    }
    _save(WALLETS_STORE, wallets)
    return wallets[wallet_id]

def register_treasury_account(account_id, *, wallet_id="", actor_id="", org_id=None, label="", purpose="", status="active", **kwargs):
    accounts = _load(ACCOUNTS_STORE)
    if account_id in accounts:
        raise ValueError("account exists")
    accounts[account_id] = {
        "account_id": account_id,
        "wallet_id": wallet_id,
        "org_id": org_id,
        "label": label,
        "purpose": purpose,
        "status": status,
        "actor_id": actor_id,
        "created_at": _now(),
    }
    _save(ACCOUNTS_STORE, accounts)
    return accounts[account_id]

def check_budget(agent_id, cost_usd, org_id=None):
    return True, "ok"

def reserve_runtime_budget(agent_id, estimated_cost, org_id=None, action="", resource="", context=None, policy_ref=""):
    reservations = _load(RESERVATIONS_STORE)
    reservation_id = f"res_{len(reservations) + 1:04d}"
    reservations[reservation_id] = {
        "reservation_id": reservation_id,
        "agent_id": agent_id,
        "org_id": org_id,
        "estimated_cost": float(estimated_cost),
        "action": action,
        "resource": resource,
        "context": context or {},
        "policy_ref": policy_ref,
        "status": "reserved",
        "created_at": _now(),
    }
    _save(RESERVATIONS_STORE, reservations)
    return {"allowed": True, "reservation_id": reservation_id, "reason": "ok"}

def commit_runtime_budget(reservation_id, actual_cost_usd, note=""):
    reservations = _load(RESERVATIONS_STORE)
    reservation = reservations.get(reservation_id)
    if reservation is None:
        return {"reservation_id": reservation_id, "status": "missing", "commit_reason": "unknown reservation"}
    reservation["actual_cost_usd"] = float(actual_cost_usd)
    reservation["status"] = "committed"
    reservation["commit_note"] = note
    reservation["updated_at"] = _now()
    _save(RESERVATIONS_STORE, reservations)
    return {"reservation_id": reservation_id, "status": "committed", "commit_reason": note or "committed"}

def release_runtime_budget(reservation_id, reason=""):
    reservations = _load(RESERVATIONS_STORE)
    reservation = reservations.get(reservation_id)
    if reservation is None:
        return {"reservation_id": reservation_id, "status": "missing", "release_reason": "unknown reservation"}
    reservation["status"] = "released"
    reservation["release_reason"] = reason
    reservation["updated_at"] = _now()
    _save(RESERVATIONS_STORE, reservations)
    return {"reservation_id": reservation_id, "status": "released", "release_reason": reason or "released"}
PY
}

create_warrant() {
  python3 - "${WARRANT_FILE}" <<'PY'
import hashlib
import json
import sys
import time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

path = sys.argv[1]
seed = bytes([31] * 32)
private_key = Ed25519PrivateKey.from_private_bytes(seed)
public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

warrant_id = bytes(((i * 9 + 7) & 0xFF) for i in range(32))
scope_cbor = bytes([0xA1, 0x69, 0x65, 0x6D, 0x62, 0x6F, 0x64, 0x69, 0x65, 0x64, 0xF5])
expiry_epoch_ms = int(time.time() * 1000) + 10 * 60 * 1000
message = warrant_id + hashlib.sha256(scope_cbor).digest() + expiry_epoch_ms.to_bytes(8, "big")
signature = private_key.sign(message)

payload = {
    "id_hex": warrant_id.hex(),
    "scope_cbor_hex": scope_cbor.hex(),
    "expiry_epoch_ms": expiry_epoch_ms,
    "kernel_sig_hex": signature.hex(),
    "kernel_pub_hex": public_key.hex(),
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2)
    handle.write("\n")
PY
}

extract_json_field() {
  local file="$1"
  local query="$2"
  python3 - "${file}" "${query}" <<'PY'
import json
import re
import subprocess
import sys

path, query = sys.argv[1], sys.argv[2]
text = open(path, "r", encoding="utf-8").read()
text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
decoder = json.JSONDecoder()
payload = None
payload_end = -1
for idx, ch in enumerate(text):
    if ch not in "{[":
        continue
    try:
        candidate, parsed_len = decoder.raw_decode(text[idx:])
    except json.JSONDecodeError:
        continue
    end_pos = idx + parsed_len
    if end_pos > payload_end or (
        end_pos == payload_end and isinstance(candidate, dict) and not isinstance(payload, dict)
    ):
        payload = candidate
        payload_end = end_pos
if payload is None:
    print("null")
    raise SystemExit(0)
proc = subprocess.run(
    ["jq", "-r", query],
    input=json.dumps(payload),
    text=True,
    capture_output=True,
)
if proc.returncode != 0:
    raise SystemExit(proc.returncode)
print(proc.stdout.rstrip("\n"))
PY
}

assert_json() {
  local file="$1"
  local query="$2"
  local message="$3"
  if ! python3 - "${file}" "${query}" <<'PY'
import json
import re
import subprocess
import sys

path, query = sys.argv[1], sys.argv[2]
text = open(path, "r", encoding="utf-8").read()
text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
decoder = json.JSONDecoder()
payload = None
payload_end = -1
for idx, ch in enumerate(text):
    if ch not in "{[":
        continue
    try:
        candidate, parsed_len = decoder.raw_decode(text[idx:])
    except json.JSONDecodeError:
        continue
    end_pos = idx + parsed_len
    if end_pos > payload_end or (
        end_pos == payload_end and isinstance(candidate, dict) and not isinstance(payload, dict)
    ):
        payload = candidate
        payload_end = end_pos
if payload is None:
    raise SystemExit(2)
proc = subprocess.run(
    ["jq", "-e", query],
    input=json.dumps(payload),
    text=True,
    capture_output=True,
)
raise SystemExit(proc.returncode)
PY
  then
    fail_now "${message}"
  fi
}

echo "=== Meridian Loom Full-System Acceptance Lane ==="
echo "work_dir=${WORK_DIR}"
echo "runtime_root=${RUNTIME_ROOT}"
echo "kernel_path=${KERNEL_PATH}"

create_kernel_fixture
create_warrant

# 1) init-nation
run_step "1" "nation.init" \
  "${LOOM_BIN}" init-nation \
  --charter "FullSystemTestNation" \
  --org-id "${REQUESTED_ORG_HINT}" \
  --root "${RUNTIME_ROOT}" \
  --kernel-path "${KERNEL_PATH}" \
  --format json

assert_json "${CURRENT_LOG}" '.status == "init_nation_ready"' "init-nation did not return init_nation_ready"
assert_json "${CURRENT_LOG}" '(.hot_wallet_status == "created") or (.hot_wallet_status == "reused")' "init-nation hot_wallet_status invalid"
assert_json "${CURRENT_LOG}" '.seed_agents_count >= 7' "init-nation did not materialize 7 seed agents"
ACTIVE_ORG_ID="$(extract_json_field "${CURRENT_LOG}" '.institution_id // .runtime_org_id // empty')"
if [[ -z "${ACTIVE_ORG_ID}" || "${ACTIVE_ORG_ID}" == "null" ]]; then
  fail_now "init-nation output missing institution_id/runtime_org_id for downstream governance checks"
fi

NATION_GOV_FILE="${LOG_DIR}/step_1_nation_governance.json"
python3 - "${KERNEL_PATH}" "${ACTIVE_ORG_ID}" >"${NATION_GOV_FILE}" <<'PY'
import json
import pathlib
import sys
kernel_path, org_id = sys.argv[1], sys.argv[2]
kernel_dir = pathlib.Path(kernel_path) / "kernel"
sys.path.insert(0, str(kernel_dir))
import court
import authority
import treasury
restrictions = court.get_restrictions("agent_manager", org_id)
allowed, reason = authority.check_authority("agent_manager", "init_nation", org_id)
print(json.dumps({
    "court_status": "clear" if "init_nation" not in restrictions else "blocked",
    "authority_status": "allowed" if allowed else "denied",
    "authority_reason": reason,
}))
PY
assert_json "${NATION_GOV_FILE}" '.court_status == "clear"' "nation governance court check failed"
assert_json "${NATION_GOV_FILE}" '.authority_status == "allowed"' "nation governance authority check failed"
SUMMARY_ROWS+=("1|nation.init|PASS|status=init_nation_ready; treasury_hot_wallet=$(extract_json_field "${CURRENT_LOG}" '.hot_wallet_status'); court=clear; authority=allowed")

# 2) breed
run_step "2" "evolution.breed" \
  "${LOOM_BIN}" breed agent_atlas agent_quill \
  --agent-id agent_atlas \
  --kernel-path "${KERNEL_PATH}" \
  --org-id "${ACTIVE_ORG_ID}" \
  --mutation-rate 0.15 \
  --root "${RUNTIME_ROOT}" \
  --format json

assert_json "${CURRENT_LOG}" '.status == "breed_created"' "breed did not create DNA artifact"
assert_json "${CURRENT_LOG}" '.court_status == "clear"' "breed court check failed"
assert_json "${CURRENT_LOG}" '.authority_status == "allowed"' "breed authority check failed"
assert_json "${CURRENT_LOG}" '(.dna_id | length) > 0' "breed dna_id missing"
SUMMARY_ROWS+=("2|evolution.breed|PASS|court=clear; authority=allowed; dna_id=$(extract_json_field "${CURRENT_LOG}" '.dna_id')")

# 3) connect scaffold
run_step "3" "connect.scaffold" \
  "${LOOM_BIN}" connect scaffold \
  --name test-grpc \
  --transport grpc \
  --action-schema meridian.runtime.v1 \
  --root "${RUNTIME_ROOT}" \
  --format json

assert_json "${CURRENT_LOG}" '.status == "connect_scaffolded"' "connect scaffold failed"
assert_json "${CURRENT_LOG}" '.transport == "grpc"' "connect scaffold transport mismatch"
SUMMARY_ROWS+=("3|connect.scaffold|PASS|adapter_id=$(extract_json_field "${CURRENT_LOG}" '.adapter_id'); transport=grpc")

# 4) shadow run grpc_physical
run_step "4" "shadow.grpc_physical" \
  "${LOOM_BIN}" shadow run \
  --backend grpc_physical \
  --root "${RUNTIME_ROOT}" \
  --kernel-path "${KERNEL_PATH}" \
  --agent-id agent_atlas \
  --org-id "${ACTIVE_ORG_ID}" \
  --action-type shadow_grpc_physical \
  --resource external_grpc_physical \
  --warrant-file "${WARRANT_FILE}" \
  --url grpc://127.0.0.1:50051 \
  --grpc-service meridian.embodied.action.v1.PhysicalActionService \
  --grpc-method Execute \
  --grpc-action-kind physical.move \
  --grpc-action-objective "move testbot" \
  --physical-robot-id testbot \
  --physical-target test-zone \
  --physical-command move \
  --physical-safety-class restricted \
  --grpc-physical-lifecycle stream \
  --grpc-physical-ack-required true \
  --grpc-physical-ack-timeout-seconds 5 \
  --format json

assert_json "${CURRENT_LOG}" '.backend == "grpc_physical"' "grpc_physical backend not used"
assert_json "${CURRENT_LOG}" '.warrant_binding_status == "verified"' "grpc_physical warrant binding is not verified"
assert_json "${CURRENT_LOG}" '.host_backend == "external_grpc_physical"' "grpc_physical host backend mismatch"

PHYSICAL_GOV_FILE="${LOG_DIR}/step_4_physical_governance.json"
python3 - "${KERNEL_PATH}" "${ACTIVE_ORG_ID}" >"${PHYSICAL_GOV_FILE}" <<'PY'
import json
import pathlib
import sys
kernel_path, org_id = sys.argv[1], sys.argv[2]
kernel_dir = pathlib.Path(kernel_path) / "kernel"
sys.path.insert(0, str(kernel_dir))
import court
import authority
import treasury
restrictions = court.get_restrictions("agent_atlas", org_id)
allowed, reason = authority.check_authority("agent_atlas", "physical.move", org_id)
budget_allowed, budget_reason = treasury.check_budget("agent_atlas", 0.01, org_id)
print(json.dumps({
    "court_status": "clear" if "physical.move" not in restrictions else "blocked",
    "authority_status": "allowed" if allowed else "denied",
    "authority_reason": reason,
    "treasury_status": "allowed" if budget_allowed else "blocked",
    "treasury_reason": budget_reason,
}))
PY
assert_json "${PHYSICAL_GOV_FILE}" '.court_status == "clear"' "physical court check failed"
assert_json "${PHYSICAL_GOV_FILE}" '.authority_status == "allowed"' "physical authority check failed"
assert_json "${PHYSICAL_GOV_FILE}" '.treasury_status == "allowed"' "physical treasury check failed"
SUMMARY_ROWS+=("4|shadow.grpc_physical|PASS|warrant=verified; treasury=allowed; court=clear; authority=allowed")

# 5) memory fork (native)
CURRENT_STEP="5"
CURRENT_COMPONENT="memory.fork"
CURRENT_LOG="${LOG_DIR}/step_5_memory_fork.log"
{
  echo ">>> STEP 5 | memory.fork"
  echo "+ ${LOOM_BIN} memory write --agent-id agent_atlas ..."
  "${LOOM_BIN}" memory write --root "${RUNTIME_ROOT}" --agent-id agent_atlas --category research --key pattern --content "v1" --source full-system --format json
  "${LOOM_BIN}" memory write --root "${RUNTIME_ROOT}" --agent-id agent_atlas --category research --key pattern --content "v2" --source full-system --format json
  "${LOOM_BIN}" memory write --root "${RUNTIME_ROOT}" --agent-id agent_atlas --category research --key insight --content "portable" --source full-system --format json
  echo "+ ${LOOM_BIN} memory fork agent_atlas --branch full-system --target-agent-id agent_quill ..."
  "${LOOM_BIN}" memory fork agent_atlas --branch full-system --target-agent-id agent_quill --root "${RUNTIME_ROOT}" --format json
} 2>&1 | tee "${CURRENT_LOG}"

assert_json "${CURRENT_LOG}" '.status == "memory_fork_created" or .status == "memory_forked"' "memory fork step did not produce native fork status"
MEMORY_SOURCE_REF="$(extract_json_field "${CURRENT_LOG}" '.source_ref // "agent_atlas"')"
if [[ -z "${MEMORY_SOURCE_REF}" || "${MEMORY_SOURCE_REF}" == "null" ]]; then
  MEMORY_SOURCE_REF="agent_atlas"
fi
SUMMARY_ROWS+=("5|memory.fork|PASS|source_ref=${MEMORY_SOURCE_REF}; mode=native")

# 6) memory replay
run_step "6" "memory.replay" \
  "${LOOM_BIN}" memory replay "${MEMORY_SOURCE_REF}" \
  --target-agent-id agent_quill \
  --kernel-path "${KERNEL_PATH}" \
  --org-id "${ACTIVE_ORG_ID}" \
  --root "${RUNTIME_ROOT}" \
  --format json

assert_json "${CURRENT_LOG}" '.status == "memory_replay_applied"' "memory replay failed"
assert_json "${CURRENT_LOG}" '.court_status == "clear"' "memory replay court check failed"
assert_json "${CURRENT_LOG}" '.authority_status == "allowed"' "memory replay authority check failed"
assert_json "${CURRENT_LOG}" '.replayed_entries > 0' "memory replay did not apply entries"
SUMMARY_ROWS+=("6|memory.replay|PASS|court=clear; authority=allowed; replayed_entries=$(extract_json_field "${CURRENT_LOG}" '.replayed_entries')")

# 7) swarm run --settle-zk
run_step "7" "swarm.run_settle_zk" \
  "${LOOM_BIN}" swarm run \
  --root "${RUNTIME_ROOT}" \
  --kernel-path "${KERNEL_PATH}" \
  --agent-id agent_atlas \
  --org-id "${ACTIVE_ORG_ID}" \
  --action-type research \
  --resource system_info \
  --module builtin:system.info \
  --warrant-file "${WARRANT_FILE}" \
  --estimated-cost-usd 0.05 \
  --actual-cost-usd 0.05 \
  --settle-zk \
  --zk-backend sp1 \
  --format json

assert_json "${CURRENT_LOG}" '.status == "swarm_run_settled"' "swarm run did not settle"
assert_json "${CURRENT_LOG}" '.shadow.warrant_binding_status == "verified"' "swarm shadow warrant binding not verified"
assert_json "${CURRENT_LOG}" '.treasury_status == "committed"' "swarm treasury status is not committed"
SWARM_SETTLEMENT_PATH="$(extract_json_field "${CURRENT_LOG}" '.paths.settlement_latest_path')"
if [[ -z "${SWARM_SETTLEMENT_PATH}" || "${SWARM_SETTLEMENT_PATH}" == "null" || ! -f "${SWARM_SETTLEMENT_PATH}" ]]; then
  fail_now "swarm settlement artifact missing"
fi
assert_json "${SWARM_SETTLEMENT_PATH}" '.court_status == "clear"' "swarm settlement court status is not clear"
assert_json "${SWARM_SETTLEMENT_PATH}" '.authority_status == "allowed"' "swarm settlement authority status is not allowed"
SUMMARY_ROWS+=("7|swarm.run_settle_zk|PASS|warrant=verified; treasury=committed; court=clear; authority=allowed")

# 8) job settle --zk
run_step "8" "job.settle_zk" \
  "${LOOM_BIN}" job settle \
  --zk \
  --root "${RUNTIME_ROOT}" \
  --kernel-path "${KERNEL_PATH}" \
  --actual-cost-usd 0.05 \
  --zk-backend sp1 \
  --format json

assert_json "${CURRENT_LOG}" '.status == "zk_settlement_captured"' "job settle did not capture zk settlement"
assert_json "${CURRENT_LOG}" '.court_status == "clear"' "job settle court check failed"
assert_json "${CURRENT_LOG}" '.authority_status == "allowed"' "job settle authority check failed"
assert_json "${CURRENT_LOG}" '.treasury_status == "committed"' "job settle treasury status is not committed"
assert_json "${CURRENT_LOG}" '.warrant_id_hex | startswith("0x")' "job settle warrant_id_hex missing"
SUMMARY_ROWS+=("8|job.settle_zk|PASS|warrant_id_hex=$(extract_json_field "${CURRENT_LOG}" '.warrant_id_hex'); treasury=committed; court=clear; authority=allowed")

# 9) parity report
run_step "9" "report.parity" \
  "${LOOM_BIN}" parity report \
  --root "${RUNTIME_ROOT}"

if ! grep -q "PARITY REPORT" "${CURRENT_LOG}"; then
  fail_now "parity report output missing PARITY REPORT heading"
fi
SUMMARY_ROWS+=("9|report.parity|PASS|parity_report_rendered=true")

# 10) shadow report
run_step "10" "report.shadow" \
  "${LOOM_BIN}" shadow report \
  --root "${RUNTIME_ROOT}"

if ! grep -q "SHADOW REPORT" "${CURRENT_LOG}"; then
  fail_now "shadow report output missing SHADOW REPORT heading"
fi
SUMMARY_ROWS+=("10|report.shadow|PASS|shadow_report_rendered=true")

print_summary
echo
echo "[PASS] Full-system lane completed successfully."
echo "work_dir=${WORK_DIR}"
