with open('intelligence/scripts/acceptance_publish_live_lane.sh', 'r') as f:
    content = f.read()

new_post = '''    def do_POST(self):  # noqa: N802
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
        if self.path == "/api/subscriptions/checkout-capture":
            self._send(410, json.dumps({"status": "deprecated", "reason": "open_source_mode", "next_steps": []}))
            return
        self._send(404, json.dumps({"error": "not_found"}))
'''

import re
content = re.sub(r'    def do_POST\(self\).*?(?=\n\nif __name__ == "__main__")', new_post, content, flags=re.DOTALL)

with open('intelligence/scripts/acceptance_publish_live_lane.sh', 'w') as f:
    f.write(content)
