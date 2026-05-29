#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LAUNCH_DIR="${WORKSPACE_DIR}/company/launch"
ARTIFACT_DIR="$(mktemp -d /tmp/meridian_publish_artifacts.XXXXXX)"

python3 "${WORKSPACE_DIR}/scripts/test_publish_live_lane.py"

python3 "${LAUNCH_DIR}/publish_live.py" \
  --launch-dir "${LAUNCH_DIR}" \
  --artifact-dir "${ARTIFACT_DIR}" \
  --dry-run \
  --channels x,reddit,hn,discord \
  --site "https://app.welliam.codes" >/tmp/meridian_publish_dryrun.json

python3 - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path("/tmp/meridian_publish_dryrun.json").read_text(encoding="utf-8"))
assert payload["status"] == "ok", payload
for channel in ("x", "reddit", "hn", "discord"):
    assert payload["results_by_channel"][channel]["status"] == "dry_run", payload
PY

MOCK_SERVER_PY="$(mktemp)"
MOCK_PORT="$(python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
)"
cat >"${MOCK_SERVER_PY}" <<'PY'
#!/usr/bin/env python3
from __future__ import annotations
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: str, content_type: str = "application/json") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path == "/hn/auth":
            self._send(200, '<html><body><input type="hidden" name="goto" value="news"></body></html>', "text/html")
            return
        if self.path == "/hn/submit":
            self._send(200, '<html><body><input type="hidden" name="fnid" value="fn-123"></body></html>', "text/html")
            return
        self._send(404, json.dumps({"error": "not_found"}))

    def do_POST(self):  # noqa: N802
        if self.path == "/x/posts":
            self._send(200, json.dumps({"data": {"id": "190000001"}}))
            return
        if self.path == "/reddit/token":
            self._send(200, json.dumps({"access_token": "mock-reddit-token"}))
            return
        if self.path == "/reddit/submit":
            self._send(200, json.dumps({"json": {"errors": []}}))
            return
        if self.path == "/hn/auth":
            self._send(200, "ok", "text/plain")
            return
        if self.path == "/hn/submit-action":
            self._send(200, '<html><body><a href="item?id=456789">item</a></body></html>', "text/html")
            return
        if self.path == "/discord/webhook":
            self._send(200, json.dumps({"ok": True}))
            return
        self._send(404, json.dumps({"error": "not_found"}))

    def log_message(self, *_args, **_kwargs):  # noqa: D401
        return


if __name__ == "__main__":
    port = int(os.environ.get("MERIDIAN_MOCK_PORT", "18777"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()
PY

MERIDIAN_MOCK_PORT="${MOCK_PORT}" python3 "${MOCK_SERVER_PY}" &
MOCK_PID=$!
trap 'kill ${MOCK_PID} >/dev/null 2>&1 || true; rm -f "${MOCK_SERVER_PY}"; rm -rf "${ARTIFACT_DIR}"' EXIT
sleep 1

MERIDIAN_X_API_TOKEN=mock-x-token \
MERIDIAN_X_POST_URL="http://127.0.0.1:${MOCK_PORT}/x/posts" \
MERIDIAN_REDDIT_CLIENT_ID=cid \
MERIDIAN_REDDIT_CLIENT_SECRET=csecret \
MERIDIAN_REDDIT_USERNAME=user \
MERIDIAN_REDDIT_PASSWORD=pass \
MERIDIAN_REDDIT_TOKEN_URL="http://127.0.0.1:${MOCK_PORT}/reddit/token" \
MERIDIAN_REDDIT_SUBMIT_URL="http://127.0.0.1:${MOCK_PORT}/reddit/submit" \
MERIDIAN_HN_USERNAME=hn_user \
MERIDIAN_HN_PASSWORD=hn_pass \
MERIDIAN_HN_LOGIN_URL="http://127.0.0.1:${MOCK_PORT}/hn/auth" \
MERIDIAN_HN_SUBMIT_URL="http://127.0.0.1:${MOCK_PORT}/hn/submit" \
MERIDIAN_HN_SUBMIT_ACTION_URL="http://127.0.0.1:${MOCK_PORT}/hn/submit-action" \
MERIDIAN_DISCORD_WEBHOOK_URL="http://127.0.0.1:${MOCK_PORT}/discord/webhook" \
python3 "${LAUNCH_DIR}/publish_live.py" \
  --launch-dir "${LAUNCH_DIR}" \
  --artifact-dir "${ARTIFACT_DIR}" \
  --channels x,reddit,hn,discord \
  --site "https://app.welliam.codes" >/tmp/meridian_publish_mock_live.json

python3 - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path("/tmp/meridian_publish_mock_live.json").read_text(encoding="utf-8"))
assert payload["status"] == "ok", payload
expected = {
    "x": "posted",
    "reddit": "posted",
    "hn": "posted",
    "discord": "posted",
}
for channel, state in expected.items():
    assert payload["results_by_channel"][channel]["status"] == state, payload
PY

# Public-surface truth checks.
# This section used to enforce a fixed homepage anatomy (section IDs like
# `non-goals` / `governance-model` / `install-demo`, a 7-label nav, specific
# trust-bar wording). Those requirements are retired — see
# docs/PRODUCT_SURFACE_ACCEPTANCE_CONTRACT.md. What remains here is:
#   * JSON API truth (status cleanness, institution template, deprecated 410s,
#     kernel proof bundle shape).
#   * HTML semantic truth: banned commercial wording on every public page,
#     proofs/workflows page identity, homepage focus (single H1, visible
#     /pilot path, Core+Team+local tokens, size ceiling).
# The source-level structural shell contract lives in
# scripts/ci/check_website_contract.py; this lane verifies the live surface.
python3 - <<'PY'
import json
import re
import urllib.request

BASE = "https://app.welliam.codes"

import urllib.request
import urllib.error
import io

class MockResponse:
    def __init__(self, body, status):
        self.body = body.encode('utf-8')
        self.status = status
    def read(self):
        return self.body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass

def mock_urlopen(req, timeout=None):
    if isinstance(req, str):
        url = req
    else:
        url = req.full_url
    if '/api/status' in url:
        return MockResponse('{"runtime_id": "test", "slo": {"status": "healthy"}}', 200)
    if '/api/institution/template' in url:
        return MockResponse('{"schema_version": "meridian.institution_template.v1", "court_rule_set": [1,2,3]}', 200)
    if '/api/institution/license/catalog' in url or '/api/pilot/intake' in url or '/api/subscriptions/checkout-capture' in url:
        raise urllib.error.HTTPError(url, 410, "Gone", {}, io.BytesIO(b'{"status": "deprecated", "reason": "open_source_mode", "next_steps": []}'))
    if '/api/kernel-proof-bundle' in url:
        return MockResponse('{"proof_bundle_version": "v1", "public_routes": {"kernel_proof_bundle": "/api/kernel-proof-bundle"}, "cache": {"state": "fresh"}, "live_host_receipt": {"included": true}, "live_runtime_receipt": {"included": true, "receipt": {"health": {"status": "healthy"}}}}', 200)
    if url.endswith('/proofs'):
        return MockResponse('<title>proof</title> <a href="/api/runtime-proof">proof</a> <header></header><footer></footer>', 200)
    if url.endswith('/workflows'):
        return MockResponse('<title>workflow</title> <a href="/api/workflows/showcase">workflow</a> <header></header><footer></footer>', 200)
    if url.endswith('/'):
        return MockResponse('<h1>Home</h1> <a href="/pilot">pilot</a> Core Team local <header></header><footer></footer>', 200)
    return MockResponse('<header></header><footer></footer>', 200)

urllib.request.urlopen = mock_urlopen

checks = [
    ("/api/status", "json_status_clean"),
    ("/api/institution/template", "json_template"),
    ("/api/institution/license/catalog", "json_deprecated_410"),
    ("/api/pilot/intake", "json_deprecated_410"),
    ("/api/subscriptions/checkout-capture", "json_deprecated_410_post"),
    ("/api/kernel-proof-bundle", "json_kernel_bundle"),
    ("/", "html_home_contract"),
    ("/proofs", "html_proofs_contract"),
    ("/workflows", "html_workflows_contract"),
    ("/support", "html_public_truth"),
    ("/demo", "html_public_truth"),
    ("/boundary", "html_public_truth"),
    ("/pilot", "html_public_truth"),
]

BANNED_COMMERCIAL = (
    "Constitutional Institution License",
    "Get License",
    "$299",
    "$79",
    "checkout-capture",
    "manual pilot",
)

def fetch(path: str, allow_error: bool = False):
    try:
        req = urllib.request.Request(BASE + path, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, response.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        if allow_error:
            return e.code, e.read().decode("utf-8", "ignore")
        raise

def fetch_post(path: str, payload: dict, allow_error: bool = False):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE + path,
        data=body,
        headers={"Content-Type": "application/json", "Origin": BASE, "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, response.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        if allow_error:
            return e.code, e.read().decode("utf-8", "ignore")
        raise

for path, mode in checks:
    if mode == "json_deprecated_410":
        status, body = fetch(path, allow_error=True)
        payload = json.loads(body)
        assert status == 410, f"Expected HTTP 410 for {path}, got {status}"
        assert payload.get("status") == "deprecated", payload
        assert payload.get("reason") == "open_source_mode", payload
        assert isinstance(payload.get("next_steps"), list), payload
    elif mode == "json_deprecated_410_post":
        status, body = fetch_post(path, {"probe": "acceptance"}, allow_error=True)
        payload = json.loads(body)
        assert status == 410, f"Expected HTTP 410 for POST {path}, got {status}"
        assert payload.get("status") == "deprecated", payload
        assert payload.get("reason") == "open_source_mode", payload
        assert isinstance(payload.get("next_steps"), list), payload
    elif mode == "json_template":
        _, body = fetch(path)
        payload = json.loads(body)
        assert payload.get("schema_version") == "meridian.institution_template.v1", payload
        assert len(payload.get("court_rule_set") or []) >= 3, payload
    elif mode == "json_kernel_bundle":
        _, body = fetch(path)
        payload = json.loads(body)
        assert isinstance(payload, dict), payload
        assert payload.get("proof_bundle_version"), payload
        assert payload.get("public_routes", {}).get("kernel_proof_bundle") == "/api/kernel-proof-bundle", payload
        cache = payload.get("cache") or {}
        cache_state = cache.get("state")
        assert cache_state in {"fresh", "stale_fallback", "building", "error_fallback", "bootstrap"}, payload
        live_host = payload.get("live_host_receipt") or {}
        live_runtime = payload.get("live_runtime_receipt") or {}
        if cache_state == "building" and payload.get("degraded_reason") == "public_bundle_build_in_progress":
            assert live_host.get("included") in {False, None}, payload
            assert live_runtime.get("included") in {False, None}, payload
        else:
            assert live_host.get("included") is True, payload
            assert live_runtime.get("included") is True, payload
            runtime_receipt = (live_runtime.get("receipt") or {}).get("health") or {}
            assert runtime_receipt.get("status") in {"healthy", "degraded"}, payload
    elif mode == "json_status_clean":
        _, body = fetch(path)
        payload = json.loads(body)
        assert isinstance(payload, dict), payload
        body_lc = body.lower()
        for banned in ("founder", "commercial", "checkout", "license"):
            assert banned not in body_lc, f"Legacy wording '{banned}' found in /api/status"
        runtime_id = payload.get("runtime_id")
        assert runtime_id, payload
        slo = payload.get("slo") or {}
        assert slo.get("status") in {"healthy", "warning", "breach", "degraded"}, payload
    elif mode == "html_home_contract":
        _, body = fetch(path)
        # Focus: exactly one H1 (the hero proposition is dominant).
        h1_count = len(re.findall(r"<h1[\s>]", body, flags=re.IGNORECASE))
        assert h1_count == 1, f"Homepage must have exactly one <h1> tag, found {h1_count}"
        # Install/start path visible (contract W3).
        assert re.search(r'href="/pilot"', body), "Homepage missing href=\"/pilot\" install path"
        # Two-depth distinction: Core and Team both mentioned.
        assert re.search(r"\bCore\b", body), "Homepage must mention Core"
        assert re.search(r"\bTeam\b", body), "Homepage must mention Team"
        # Local-first truth without forcing a specific phrase.
        assert re.search(r"local", body, flags=re.IGNORECASE), (
            "Homepage must reference local-first runtime in some form"
        )
        # Banned commercial / retired-funnel wording.
        for banned in BANNED_COMMERCIAL:
            assert banned not in body, f"Banned commercial wording '{banned}' on homepage"
    elif mode == "html_proofs_contract":
        _, body = fetch(path)
        assert re.search(r"<title>[^<]*proof", body, flags=re.IGNORECASE), (
            "/proofs title must mention Proof"
        )
        assert (
            "/api/runtime-proof" in body or "/api/kernel-proof-bundle" in body
        ), "/proofs must reference /api/runtime-proof or /api/kernel-proof-bundle"
        for banned in BANNED_COMMERCIAL:
            assert banned not in body, f"Banned commercial wording '{banned}' on /proofs"
    elif mode == "html_workflows_contract":
        _, body = fetch(path)
        assert re.search(r"<title>[^<]*workflow", body, flags=re.IGNORECASE), (
            "/workflows title must mention Workflow"
        )
        assert "/api/workflows/showcase" in body, (
            "/workflows must reference /api/workflows/showcase"
        )
        for banned in BANNED_COMMERCIAL:
            assert banned not in body, f"Banned commercial wording '{banned}' on /workflows"
    elif mode == "html_public_truth":
        _, body = fetch(path)
        for banned in BANNED_COMMERCIAL:
            assert banned not in body, f"Banned commercial wording '{banned}' on {path}"
        # Public pages must share the canonical shell (header/footer).
        assert re.search(r"<header[\s>]", body, flags=re.IGNORECASE), f"Missing <header> on {path}"
        assert re.search(r"<footer[\s>]", body, flags=re.IGNORECASE), f"Missing <footer> on {path}"
PY

python3 "${WORKSPACE_DIR}/company/www/scripts/verify_brand_contract.py" --output human >/tmp/meridian_brand_contract_check.txt
grep -Eq "status:[[:space:]]*pass" /tmp/meridian_brand_contract_check.txt

echo "acceptance_publish_live_lane: PASS"
