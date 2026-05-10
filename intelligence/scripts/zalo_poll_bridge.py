#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _post_json(url: str, payload: dict[str, Any], *, headers: dict[str, str] | None = None, timeout: float = 30.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", "replace")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"raw": raw}
    return parsed if isinstance(parsed, dict) else {"payload": parsed}


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "content", "message", "body"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
            if isinstance(candidate, dict):
                nested = _extract_text(candidate)
                if nested:
                    return nested
    return ""


def _normalize_update(item: dict[str, Any]) -> dict[str, Any] | None:
    message_id = str(item.get("message_id") or item.get("update_id") or item.get("id") or "").strip()
    sender = ""
    for key in ("fromuid", "from_id", "sender_id", "chat_id"):
        candidate = str(item.get(key) or "").strip()
        if candidate:
            sender = candidate
            break
    if not sender:
        sender = str(dict(item.get("sender") or {}).get("id") or "").strip()
    if not sender:
        sender = str(dict(item.get("from") or {}).get("id") or "").strip()
    text = _extract_text(item.get("text"))
    if not text:
        text = _extract_text(item.get("message"))
    if not text:
        text = _extract_text(item)
    if not sender or not text:
        return None
    return {
        "message_id": message_id or f"zalo-{int(time.time() * 1000)}",
        "fromuid": sender,
        "text": text,
        "raw": item,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    parser.add_argument("--gateway-url", required=True)
    parser.add_argument("--secret", required=True)
    parser.add_argument("--state-file", default="/tmp/zalo_poll_bridge_state.json")
    parser.add_argument("--timeout-seconds", type=int, default=5)
    parser.add_argument("--sleep-seconds", type=float, default=0.5)
    args = parser.parse_args()

    state_path = Path(args.state_file)
    last_message_id = ""
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            last_message_id = str((state if isinstance(state, dict) else {}).get("last_message_id") or "").strip()
        except Exception:
            last_message_id = ""

    updates_url = f"https://bot-api.zaloplatforms.com/bot{args.token}/getUpdates"
    while True:
        try:
            response = _post_json(updates_url, {"timeout": str(max(1, int(args.timeout_seconds)))}, timeout=max(5.0, float(args.timeout_seconds) + 5.0))
        except urllib.error.HTTPError as exc:
            sys.stderr.write(f"zalo getUpdates http error: {exc}\n")
            time.sleep(args.sleep_seconds)
            continue
        except urllib.error.URLError as exc:
            sys.stderr.write(f"zalo getUpdates url error: {exc}\n")
            time.sleep(args.sleep_seconds)
            continue
        except Exception as exc:
            sys.stderr.write(f"zalo getUpdates error: {exc}\n")
            time.sleep(args.sleep_seconds)
            continue

        items = response.get("result")
        if not isinstance(items, list) or not items:
            time.sleep(args.sleep_seconds)
            continue

        forwarded = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_update(item)
            if not normalized:
                continue
            current_id = str(normalized.get("message_id") or "").strip()
            if current_id and last_message_id and current_id <= last_message_id:
                continue
            try:
                _post_json(
                    args.gateway_url,
                    normalized,
                    headers={"X-Meridian-Channel-Secret": args.secret},
                    timeout=40.0,
                )
                last_message_id = current_id or last_message_id
                forwarded += 1
            except Exception as exc:
                sys.stderr.write(f"forward update failed: {exc}\n")
                continue

        if forwarded:
            state_path.write_text(json.dumps({"last_message_id": last_message_id}, ensure_ascii=False) + "\n", encoding="utf-8")
        time.sleep(args.sleep_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
