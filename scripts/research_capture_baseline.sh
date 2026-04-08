#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${MERIDIAN_BASE_URL:-http://127.0.0.1:8266}"
OUT_DIR="${MERIDIAN_RESEARCH_OUT_DIR:-$ROOT_DIR/runtime/research}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="$OUT_DIR/baseline_${STAMP}.json"

mkdir -p "$OUT_DIR"

python3 - "$BASE_URL" "$OUT_FILE" <<'PY'
import json
import sys
import urllib.request
from datetime import datetime, timezone

base = sys.argv[1].rstrip("/")
out_file = sys.argv[2]

def fetch(path: str):
    with urllib.request.urlopen(base + path, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))

status = fetch("/api/status")
runtime_proof = fetch("/api/runtime-proof")
kernel_bundle = fetch("/api/kernel-proof-bundle")
treasury = fetch("/api/treasury")

payload = {
    "captured_at": datetime.now(timezone.utc).isoformat(),
    "base_url": base,
    "status": {
        "runtime_id": status.get("runtime_id"),
        "slo_status": (status.get("slo") or {}).get("status"),
        "queue_count": status.get("queue_count"),
        "pending_delivery_count": status.get("pending_delivery_count"),
        "delivered_count": status.get("delivered_count"),
        "proof_mode": status.get("proof_mode"),
    },
    "contract_blocks": {
        "proof_recursive": (status.get("proof") or {}).get("recursive"),
        "proof_aggregate": (status.get("proof") or {}).get("aggregate"),
        "court_dynamic": (status.get("court") or {}).get("dynamic"),
        "marketplace": status.get("marketplace"),
        "memory_temporal_integrity": (status.get("memory") or {}).get("temporal_integrity"),
    },
    "runtime_proof": {
        "runtime_id": runtime_proof.get("runtime_id"),
        "proof_mode": runtime_proof.get("proof_mode"),
        "runtime_proof_status": runtime_proof.get("runtime_proof_status"),
        "kernel_bundle_route": runtime_proof.get("kernel_bundle_route"),
    },
    "kernel_proof_bundle": {
        "proof_bundle_version": kernel_bundle.get("proof_bundle_version"),
        "status": kernel_bundle.get("status"),
        "cache_state": (kernel_bundle.get("cache") or {}).get("state"),
        "source": kernel_bundle.get("source"),
    },
    "treasury": {
        "balance_usd": treasury.get("balance_usd"),
        "reserve_floor_usd": treasury.get("reserve_floor_usd"),
        "runway_usd": treasury.get("runway_usd"),
    },
}

with open(out_file, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2)

print(out_file)
PY

echo "[research-baseline] captured -> $OUT_FILE"
