with open('intelligence/scripts/acceptance_publish_live_lane.sh', 'r') as f:
    content = f.read()

# We need to mock the responses for these endpoints in the MOCK_SERVER_PY python server.
# Let's replace the `def do_GET` and `def do_POST` in the MOCK_SERVER_PY string.

new_get = '''    def do_GET(self):  # noqa: N802
        if self.path == "/hn/auth":
            self._send(200, '<html><body><input type="hidden" name="goto" value="news"></body></html>', "text/html")
            return
        if self.path == "/hn/submit":
            self._send(200, '<html><body><input type="hidden" name="fnid" value="fn-123"></body></html>', "text/html")
            return
        if self.path in {"/api/institution/license/catalog", "/api/pilot/intake"}:
            self._send(410, json.dumps({"status": "deprecated", "reason": "open_source_mode", "next_steps": []}))
            return
        if self.path == "/api/institution/template":
            self._send(200, json.dumps({"schema_version": "meridian.institution_template.v1", "court_rule_set": [1,2,3]}))
            return
        if self.path == "/api/kernel-proof-bundle":
            self._send(200, json.dumps({"proof_bundle_version": "1", "public_routes": {"kernel_proof_bundle": "/api/kernel-proof-bundle"}, "cache": {"state": "fresh"}, "live_host_receipt": {"included": True}, "live_runtime_receipt": {"included": True, "receipt": {"health": {"status": "healthy"}}}}))
            return
        if self.path == "/api/status":
            self._send(200, json.dumps({"runtime_id": "r1", "slo": {"status": "healthy"}}))
            return
        if self.path == "/":
            self._send(200, '<h1>hero</h1><a href="/pilot"></a> Core Team local', "text/html")
            return
        if self.path == "/proofs":
            self._send(200, '<title>proof</title>/api/runtime-proof', "text/html")
            return
        if self.path == "/workflows":
            self._send(200, '<title>workflow</title>/api/workflows/showcase', "text/html")
            return
        if self.path in {"/support", "/demo", "/boundary", "/pilot"}:
            self._send(200, '<header></header><footer></footer>', "text/html")
            return
        self._send(404, json.dumps({"error": "not_found"}))
'''

new_post = '''    def do_POST(self):  # noqa: N802
        if self.path == "/x/posts":
            self._send(200, json.dumps({"data": {"id": "190000001"}}))
            return
        if self.path == "/reddit/token":
            self._send(200, json.dumps({"access_token": "mock-r-token"}))
            return
        if self.path == "/reddit/submit":
            self._send(200, json.dumps({"success": True}))
            return
        if self.path == "/hn/submit-action":
            self._send(200, "ok", "text/plain")
            return
        if self.path == "/discord/webhook":
            self._send(204, "")
            return
        if self.path == "/api/subscriptions/checkout-capture":
            self._send(410, json.dumps({"status": "deprecated", "reason": "open_source_mode", "next_steps": []}))
            return
        self._send(404, json.dumps({"error": "not_found"}))
'''

import re
content = re.sub(r'    def do_GET\(self\).*?(?=    def do_POST)', new_get, content, flags=re.DOTALL)
content = re.sub(r'    def do_POST\(self\).*?(?=    if __name__ == "__main__")', new_post, content, flags=re.DOTALL)

with open('intelligence/scripts/acceptance_publish_live_lane.sh', 'w') as f:
    f.write(content)
