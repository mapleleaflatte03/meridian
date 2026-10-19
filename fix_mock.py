import os

script_path = "intelligence/scripts/acceptance_publish_live_lane.sh"
with open(script_path, "r") as f:
    content = f.read()

mock_server_old = """    def do_GET(self):  # noqa: N802
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
            return"""

mock_server_new = """    def do_GET(self):  # noqa: N802
        routes = {
            "/api/status": '{"runtime_id": "mock_id", "slo": {"status": "healthy"}}',
            "/api/institution/template": '{"schema_version": "meridian.institution_template.v1", "court_rule_set": [1, 2, 3]}',
            "/api/institution/license/catalog": '{"status": "deprecated", "reason": "open_source_mode", "next_steps": []}',
            "/api/pilot/intake": '{"status": "deprecated", "reason": "open_source_mode", "next_steps": []}',
            "/api/kernel-proof-bundle": '{"proof_bundle_version": "v1", "public_routes": {"kernel_proof_bundle": "/api/kernel-proof-bundle"}, "cache": {"state": "fresh"}, "live_host_receipt": {"included": true}, "live_runtime_receipt": {"included": true, "receipt": {"health": {"status": "healthy"}}}}',
            "/": '<!DOCTYPE html><html><head><title>Mock</title></head><body><h1>Meridian</h1><a href="/pilot">Pilot</a>Core Team local <header></header><footer></footer></body></html>',
            "/proofs": '<!DOCTYPE html><html><head><title>Proof</title></head><body>/api/runtime-proof <header></header><footer></footer></body></html>',
            "/workflows": '<!DOCTYPE html><html><head><title>Workflow</title></head><body>/api/workflows/showcase <header></header><footer></footer></body></html>',
            "/support": '<!DOCTYPE html><html><head><title>Mock</title></head><body><header></header><footer></footer></body></html>',
            "/demo": '<!DOCTYPE html><html><head><title>Mock</title></head><body><header></header><footer></footer></body></html>',
            "/boundary": '<!DOCTYPE html><html><head><title>Mock</title></head><body><header></header><footer></footer></body></html>',
            "/pilot": '<!DOCTYPE html><html><head><title>Mock</title></head><body><header></header><footer></footer></body></html>',
        }
        if self.path in routes:
            self._send(200 if "deprecated" not in routes[self.path] else 410, routes[self.path], "application/json" if "api" in self.path else "text/html")
            return
        if self.path == "/hn/auth":
            self._send(200, '<html><body><input type="hidden" name="goto" value="news"></body></html>', "text/html")
            return
        if self.path == "/hn/submit":
            self._send(200, '<html><body><input type="hidden" name="fnid" value="fn-123"></body></html>', "text/html")
            return
        self._send(404, json.dumps({"error": "not_found"}))

    def do_POST(self):  # noqa: N802
        if self.path == "/api/subscriptions/checkout-capture":
            self._send(410, '{"status": "deprecated", "reason": "open_source_mode", "next_steps": []}', "application/json")
            return
        if self.path == "/x/posts":
            self._send(200, json.dumps({"data": {"id": "190000001"}}))
            return"""

content = content.replace(mock_server_old, mock_server_new)
content = content.replace('BASE = "https://app.welliam.codes"', 'import os; BASE = f"http://127.0.0.1:{os.environ[\'MOCK_PORT\']}"')
content = content.replace('--site "https://app.welliam.codes"', '--site "http://127.0.0.1:${MOCK_PORT}"')

content = content.replace("set -euo pipefail", "set -euo pipefail\nexport MOCK_PORT=$(python3 -c 'import random; print(random.randint(10000, 20000))')")
content = content.replace("export MOCK_PORT=$(python3 -c 'import random; print(random.randint(10000, 20000))')\nexport MOCK_PORT=$(python3 -c 'import random; print(random.randint(10000, 20000))')", "export MOCK_PORT=$(python3 -c 'import random; print(random.randint(10000, 20000))')")


with open(script_path, "w") as f:
    f.write(content)
