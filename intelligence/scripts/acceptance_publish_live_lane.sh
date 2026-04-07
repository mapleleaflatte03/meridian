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
MOCK_PORT=18777
cat >"${MOCK_SERVER_PY}" <<'PY'
#!/usr/bin/env python3
from __future__ import annotations
import json
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
    server = ThreadingHTTPServer(("127.0.0.1", 18777), Handler)
    server.serve_forever()
PY

python3 "${MOCK_SERVER_PY}" &
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
import urllib.request

BASE = "https://app.welliam.codes"
checks = [
    ("/api/institution/template", "json_template"),
    ("/api/institution/license/catalog", "json_deprecated_410"),
    ("/api/kernel-proof-bundle", "json_kernel_bundle"),
    ("/", "html"),
    ("/proofs", "html_secondary"),
    ("/workflows", "html_secondary"),
]

def fetch(path: str, allow_error: bool = False):
    try:
        req = urllib.request.Request(BASE + path)
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
        assert cache.get("state") in {"fresh", "stale_fallback", "building", "error_fallback", "bootstrap"}, payload
    elif mode == "html":
        _, body = fetch(path)
        # Open-source positioning present
        assert "open-source" in body.lower() or "open source" in body.lower(), "Missing open-source positioning on homepage"
        assert "Get Started" in body, "Missing 'Get Started' CTA on homepage"
        assert "trust-bar" in body or "Local-first" in body, "Missing trust bar section"
        assert "premium-footer" in body or "footer-nav-group" in body, "Missing premium footer"
        assert "Contribute" in body, "Missing contribution link on homepage"
        assert "/support" in body, "Missing support link on homepage"
        # Legacy commercial strings must be absent
        assert "Constitutional Institution License" not in body, "Legacy 'Constitutional Institution License' found on homepage"
        assert "Get License" not in body, "Legacy 'Get License' found on homepage"
        assert "$299" not in body, "Legacy '$299' pricing found on homepage"
        assert "$79" not in body, "Legacy '$79' pricing found on homepage"
        assert "checkout-capture" not in body, "Legacy checkout-capture reference found on homepage"
        # Consistent nav
        for nav_label in ("Product", "Governance", "Proofs", "Workflows", "Community", "Support", "Docs"):
            assert nav_label in body, f"Missing nav label '{nav_label}' on homepage"
    elif mode == "html_secondary":
        _, body = fetch(path)
        assert "site-nav" in body, f"Missing site nav on {path}"
        assert "Docs" in body, f"Missing Docs nav item on {path}"
        assert "nav-cta" in body, f"Missing nav CTA on {path}"
        assert "Get Started" in body, f"Missing 'Get Started' CTA on {path}"
        assert "premium-footer" in body or "footer-nav-group" in body, f"Missing premium footer on {path}"
        assert "Get License" not in body, f"Legacy 'Get License' found on {path}"
        for nav_label in ("Product", "Governance", "Community", "Support"):
            assert nav_label in body, f"Missing nav label '{nav_label}' on {path}"
PY

echo "acceptance_publish_live_lane: PASS"
