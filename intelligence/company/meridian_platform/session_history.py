#!/usr/bin/env python3
"""Structured Meridian session history events for manager/worker flows."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import secrets
from pathlib import Path
from typing import Any


DEFAULT_LOOM_ROOT = Path("/home/ubuntu/.local/share/meridian-loom/runtime/default")


def _history_root(loom_root: str | Path | None = None) -> Path:
    root = Path(loom_root) if loom_root else DEFAULT_LOOM_ROOT
    return root / "state" / "session-history" / "events"


def _session_path(session_key: str, *, loom_root: str | Path | None = None) -> Path:
    token = hashlib.sha1(session_key.encode("utf-8")).hexdigest()[:16]
    return _history_root(loom_root) / f"{token}.json"


def _now_iso() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_ms() -> int:
    return int(dt.datetime.utcnow().timestamp() * 1000)


def load_session_events(session_key: str, *, loom_root: str | Path | None = None) -> dict[str, Any]:
    path = _session_path(session_key, loom_root=loom_root)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def append_session_event(
    session_key: str,
    event: dict[str, Any],
    *,
    loom_root: str | Path | None = None,
) -> dict[str, Any]:
    path = _session_path(session_key, loom_root=loom_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = load_session_events(session_key, loom_root=loom_root) or {
        "session_key": session_key,
        "source": "meridian_session_events",
        "live": True,
        "updated_at": _now_iso(),
        "events": [],
    }
    payload = dict(event)
    payload.setdefault("event_id", f"evt-{_now_ms()}-{secrets.token_hex(4)}")
    payload.setdefault("session_key", session_key)
    payload.setdefault("started_at", _now_ms())
    payload.setdefault("recorded_at", _now_iso())
    payload.setdefault("source_label", "live_session_event")
    document.setdefault("events", []).append(payload)
    document["updated_at"] = _now_iso()
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return payload


def update_session_event(
    session_key: str,
    event_id: str,
    updates: dict[str, Any],
    *,
    loom_root: str | Path | None = None,
) -> dict[str, Any] | None:
    path = _session_path(session_key, loom_root=loom_root)
    if not path.exists():
        return None
    document = load_session_events(session_key, loom_root=loom_root)
    for item in document.get("events", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("event_id") or "") != str(event_id or ""):
            continue
        item.update(dict(updates))
        item["updated_at"] = _now_iso()
        document["updated_at"] = _now_iso()
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        return dict(item)
    return None


def session_event_history_items(session_key: str, *, loom_root: str | Path | None = None) -> list[dict[str, Any]]:
    payload = load_session_events(session_key, loom_root=loom_root)
    items: list[dict[str, Any]] = []
    for raw in payload.get("events", []):
        if not isinstance(raw, dict):
            continue
        items.append(dict(raw))
    return items
