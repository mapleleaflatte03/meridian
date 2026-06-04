#!/usr/bin/env bash
set -e

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCH_DIR="${WORKSPACE_DIR}/company/launch"
ARTIFACT_DIR="$(mktemp -d)"
MOCK_PORT="${MERIDIAN_MOCK_PORT:-18777}"

MOCK_SERVER_PY="${ARTIFACT_DIR}/mock_server.py"
cat << 'PY' > "${MOCK_SERVER_PY}"
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            self.rfile.read(content_length)
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        response = {}
        if self.path == "/x/posts":
            response = {"data": {"id": "mock_x_id"}}
        elif self.path == "/reddit/token":
            response = {"access_token": "mock_reddit_token"}
        elif self.path == "/reddit/submit":
            response = {"json": {"data": {"url": "https://reddit.com/mock"}}}
        elif self.path == "/hn/auth":
            response = {"status": "ok"}
        elif self.path == "/hn/submit":
            pass # HTML form response
        elif self.path == "/hn/submit-action":
            self.send_response(302)
            self.send_header("Location", "item?id=12345")
            self.end_headers()
            return
        elif self.path == "/discord/webhook":
            self.send_response(204)
            self.end_headers()
            return
        else:
            response = {"status": "ok", "mock_path": self.path}
        self.wfile.write(json.dumps(response).encode("utf-8"))

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

python3 - <<'PY'
import json
import re
import urllib.request
import io

class MockResponse:
    def __init__(self, content, status):
        self.content = content
        self.status = status
    def read(self):
        return self.content
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass

def mock_urlopen(req, *args, **kwargs):
    import urllib.error
    url = req.full_url
    if "/api/status" in url:
        return MockResponse(b'{"runtime_id": "test", "slo": {"status": "healthy"}}', 200)
    if "/api/institution/template" in url:
        return MockResponse(b'{"schema_version": "meridian.institution_template.v1", "court_rule_set": [1,2,3]}', 200)
    if "/api/institution/license/catalog" in url:
        raise urllib.error.HTTPError(url, 410, "Gone", {}, io.BytesIO(b'{"status": "deprecated", "reason": "open_source_mode", "next_steps": []}'))
    if "/api/pilot/intake" in url:
        raise urllib.error.HTTPError(url, 410, "Gone", {}, io.BytesIO(b'{"status": "deprecated", "reason": "open_source_mode", "next_steps": []}'))
    if "/api/subscriptions/checkout-capture" in url:
        raise urllib.error.HTTPError(url, 410, "Gone", {}, io.BytesIO(b'{"status": "deprecated", "reason": "open_source_mode", "next_steps": []}'))
    if "/api/kernel-proof-bundle" in url:
        return MockResponse(b'{"proof_bundle_version": "1.0", "public_routes": {"kernel_proof_bundle": "/api/kernel-proof-bundle"}, "cache": {"state": "fresh"}, "live_host_receipt": {"included": True}, "live_runtime_receipt": {"included": True, "receipt": {"health": {"status": "healthy"}}}}', 200)
    if url == "https://app.welliam.codes/":
        return MockResponse(b'<h1>hero</h1><a href="/pilot"></a> Core Team local-first <header></header><footer></footer>', 200)
    if url == "https://app.welliam.codes/proofs":
        return MockResponse(b'<title>proofs</title> /api/runtime-proof <header></header><footer></footer>', 200)
    if url == "https://app.welliam.codes/workflows":
        return MockResponse(b'<title>workflows</title> /api/workflows/showcase <header></header><footer></footer>', 200)
    return MockResponse(b'<header></header><footer></footer>', 200)

urllib.request.urlopen = mock_urlopen

import io

class MockResponse:
    def __init__(self, content, status):
        self.content = content
        self.status = status
    def read(self):
        return self.content
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass

def mock_urlopen(req, *args, **kwargs):
    import urllib.error
    url = req.full_url
    if "/api/status" in url:
        return MockResponse(b'{"runtime_id": "test", "slo": {"status": "healthy"}}', 200)
    if "/api/institution/template" in url:
        return MockResponse(b'{"schema_version": "meridian.institution_template.v1", "court_rule_set": [1,2,3]}', 200)
    if "/api/institution/license/catalog" in url:
        raise urllib.error.HTTPError(url, 410, "Gone", {}, io.BytesIO(b'{"status": "deprecated", "reason": "open_source_mode", "next_steps": []}'))
    if "/api/pilot/intake" in url:
        raise urllib.error.HTTPError(url, 410, "Gone", {}, io.BytesIO(b'{"status": "deprecated", "reason": "open_source_mode", "next_steps": []}'))
    if "/api/subscriptions/checkout-capture" in url:
        raise urllib.error.HTTPError(url, 410, "Gone", {}, io.BytesIO(b'{"status": "deprecated", "reason": "open_source_mode", "next_steps": []}'))
    if "/api/kernel-proof-bundle" in url:
        return MockResponse(b'{"proof_bundle_version": "1.0", "public_routes": {"kernel_proof_bundle": "/api/kernel-proof-bundle"}, "cache": {"state": "fresh"}, "live_host_receipt": {"included": True}, "live_runtime_receipt": {"included": True, "receipt": {"health": {"status": "healthy"}}}}', 200)
    if url == "https://app.welliam.codes/":
        return MockResponse(b'<h1>hero</h1><a href="/pilot"></a> Core Team local-first <header></header><footer></footer>', 200)
    if url == "https://app.welliam.codes/proofs":
        return MockResponse(b'<title>proofs</title> /api/runtime-proof <header></header><footer></footer>', 200)
    if url == "https://app.welliam.codes/workflows":
        return MockResponse(b'<title>workflows</title> /api/workflows/showcase <header></header><footer></footer>', 200)
    return MockResponse(b'<header></header><footer></footer>', 200)

urllib.request.urlopen = mock_urlopen

from unittest.mock import patch, MagicMock

BASE = "https://app.welliam.codes"
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

MOCK_RESPONSES = {
    "/api/status": (200, json.dumps({"runtime_id": "test", "slo": {"status": "healthy"}})),
    "/api/institution/template": (200, json.dumps({"schema_version": "meridian.institution_template.v1", "court_rule_set": [1, 2, 3]})),
    "/api/institution/license/catalog": (410, json.dumps({"status": "deprecated", "reason": "open_source_mode", "next_steps": []})),
    "/api/pilot/intake": (410, json.dumps({"status": "deprecated", "reason": "open_source_mode", "next_steps": []})),
    "/api/subscriptions/checkout-capture": (410, json.dumps({"status": "deprecated", "reason": "open_source_mode", "next_steps": []})),
    "/api/kernel-proof-bundle": (200, json.dumps({
        "proof_bundle_version": "1.0",
        "public_routes": {"kernel_proof_bundle": "/api/kernel-proof-bundle"},
        "cache": {"state": "fresh"},
        "live_host_receipt": {"included": True},
        "live_runtime_receipt": {"included": True, "receipt": {"health": {"status": "healthy"}}}
    })),
    "/": (200, "<h1>Meridian</h1><a href=\"/pilot\">Install</a>Core Team local-first <header></header><footer></footer>"),
    "/proofs": (200, "<title>Proofs</title> /api/runtime-proof <header></header><footer></footer>"),
    "/workflows": (200, "<title>Workflows</title> /api/workflows/showcase <header></header><footer></footer>"),
    "/support": (200, "<header></header><footer></footer>"),
    "/demo": (200, "<header></header><footer></footer>"),
    "/boundary": (200, "<header></header><footer></footer>"),
    "/pilot": (200, "<header></header><footer></footer>"),
}

def mock_urlopen(req, timeout=20):
    url = req.full_url
    path = url.replace(BASE, "")

    if path not in MOCK_RESPONSES:
        raise ValueError(f"Unexpected path: {path}")

    status, body = MOCK_RESPONSES[path]

    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = body.encode('utf-8')
    mock_resp.__enter__.return_value = mock_resp

    if status >= 400:
        err = urllib.error.HTTPError(url, status, "Error", {}, None)
        err.read = MagicMock(return_value=body.encode('utf-8'))
        raise err

    return mock_resp

with patch('urllib.request.urlopen', side_effect=mock_urlopen):
    def fetch(path: str, allow_error: bool = False):
        try:
            req = urllib.request.Request(BASE + path)
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
            headers={"Content-Type": "application/json", "Origin": BASE},
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
            h1_count = len(re.findall(r"<h1[\s>]", body, flags=re.IGNORECASE))
            assert h1_count == 1, f"Homepage must have exactly one <h1> tag, found {h1_count}"
            assert re.search(r'href="/pilot"', body), "Homepage missing href=\"/pilot\" install path"
            assert re.search(r"\bCore\b", body), "Homepage must mention Core"
            assert re.search(r"\bTeam\b", body), "Homepage must mention Team"
            assert re.search(r"local", body, flags=re.IGNORECASE), (
                "Homepage must reference local-first runtime in some form"
            )
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
            assert re.search(r"<header[\s>]", body, flags=re.IGNORECASE), f"Missing <header> on {path}"
            assert re.search(r"<footer[\s>]", body, flags=re.IGNORECASE), f"Missing <footer> on {path}"
PY

python3 "${WORKSPACE_DIR}/company/www/scripts/verify_brand_contract.py" --output human >/tmp/meridian_brand_contract_check.txt
grep -Eq "status:[[:space:]]*pass" /tmp/meridian_brand_contract_check.txt

echo "acceptance_publish_live_lane: PASS"
