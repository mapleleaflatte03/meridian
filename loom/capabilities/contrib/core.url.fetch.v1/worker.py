#!/usr/bin/env python3
"""
core.url.fetch.v1 — Meridian Core capability worker

Fetches a URL using urllib (no external dependencies) and extracts:
  - page title
  - first 500 characters of visible text
  - HTTP status

Payload JSON fields:
  url (required): the URL to fetch
  max_chars (optional, default 500): max chars of body text to extract

Output JSON fields:
  status: "completed" | "error"
  url: the URL that was fetched
  http_status: HTTP response code
  title: page title (empty string if none found)
  text: extracted visible text excerpt
  error: error message if status is "error"
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    """Minimal HTML parser that pulls visible text, skipping scripts/styles.

    title is read from <title> inside <head>.
    Body text is collected from visible elements.
    """

    # Tags whose entire subtree content is non-visible
    SKIP_TAGS = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self._skip = 0        # depth inside SKIP_TAGS
        self._in_head = False  # True while inside <head>
        self._in_title = False
        self.title: str = ""
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:  # noqa: ARG002
        tag = tag.lower()
        if tag == "head":
            self._in_head = True
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "head":
            self._in_head = False
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP_TAGS:
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if not stripped:
            return
        # Capture title from <title> tag
        if self._in_title and not self.title:
            self.title = stripped
            return
        # Collect body text — skip head (non-title) and skip-tagged subtrees
        if self._skip or self._in_head:
            return
        self.text_parts.append(stripped)


def fetch_url(url: str, max_chars: int = 500, timeout: int = 10) -> dict:
    """Fetch URL and return structured result dict."""
    headers = {
        "User-Agent": "Mozilla/5.0 (MeridianCore/0.1 +https://app.welliam.codes)",
        "Accept": "text/html,application/xhtml+xml,*/*",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            http_status = response.getcode()
            raw = response.read(65536)
            content_type = response.headers.get("Content-Type", "")
            match = re.search(r"charset=([^\s;]+)", content_type, re.I)
            encoding = match.group(1).strip().lower() if match else "utf-8"
            try:
                html = raw.decode(encoding, errors="replace")
            except (LookupError, ValueError):
                html = raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return {
            "status": "error",
            "url": url,
            "http_status": exc.code,
            "title": "",
            "text": "",
            "error": f"HTTP {exc.code}: {exc.reason}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "url": url,
            "http_status": 0,
            "title": "",
            "text": "",
            "error": str(exc),
        }

    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001
        pass

    full_text = re.sub(r"\s+", " ", " ".join(parser.text_parts)).strip()

    return {
        "status": "completed",
        "url": url,
        "http_status": http_status,
        "title": parser.title or "",
        "text": full_text[:max_chars],
        "error": "",
    }


def main() -> None:
    arg_parser = argparse.ArgumentParser(description="core.url.fetch.v1 worker")
    arg_parser.add_argument("--input", required=True)
    arg_parser.add_argument("--output", required=True)
    args = arg_parser.parse_args()

    with open(args.input, encoding="utf-8") as fh:
        payload_envelope = json.load(fh)

    capability = payload_envelope.get("capability", {})
    envelope = payload_envelope.get("envelope", {})
    # payload_json may be at root level or nested inside envelope
    raw_payload = (
        payload_envelope.get("payload_json", "")
        or envelope.get("payload_json", "")
    )

    parsed: dict = {}
    if raw_payload:
        try:
            parsed = json.loads(raw_payload)
        except json.JSONDecodeError:
            parsed = {}

    url = (parsed.get("url") or parsed.get("message") or "").strip()
    max_chars = int(parsed.get("max_chars", 500))

    if not url:
        fetch_result: dict = {
            "status": "error",
            "url": "",
            "http_status": 0,
            "title": "",
            "text": "",
            "error": "payload must include 'url' field",
        }
    else:
        fetch_result = fetch_url(url, max_chars=max_chars)

    result = {
        "status": fetch_result["status"],
        "worker_kind": capability.get("worker_kind", "python_capability_worker"),
        "capability_name": capability.get("name", "core.url.fetch.v1"),
        "completed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "agent_id": envelope.get("agent_id", ""),
        "org_id": envelope.get("org_id", ""),
        "action_type": envelope.get("action_type", "browse"),
        "resource": envelope.get("resource", ""),
        "url": fetch_result["url"],
        "http_status": fetch_result["http_status"],
        "title": fetch_result["title"],
        "text": fetch_result["text"],
        "error": fetch_result.get("error", ""),
        "summary": (
            f"[{fetch_result['http_status']}] {fetch_result['title']!r} — {fetch_result['text'][:120]}"
            if fetch_result["status"] == "completed"
            else f"Error: {fetch_result.get('error', 'unknown')}"
        ),
    }

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
