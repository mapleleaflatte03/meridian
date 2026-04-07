#!/usr/bin/env python3
"""Telegram export import helpers for Meridian session continuity."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from team_topology import default_imported_history_dir


@dataclass(frozen=True)
class ImportedMessage:
    message_id: str
    started_at: int
    timestamp: str
    author: str
    speaker: str
    text: str

    def to_history_item(self, session_key: str) -> dict[str, Any]:
        return {
            "history_type": "imported_message",
            "job_id": self.message_id,
            "pipeline_id": self.message_id,
            "status": "historical",
            "session_key": session_key,
            "speaker": self.speaker,
            "author": self.author,
            "text": self.text,
            "started_at": self.started_at,
            "imported": True,
            "source_label": "imported_history",
        }


def _now() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _session_path(session_key: str, *, loom_root: str | Path | None = None) -> Path:
    token = hashlib.sha1(session_key.encode("utf-8")).hexdigest()[:16]
    return default_imported_history_dir(loom_root) / f"{token}.json"


def _flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        chunks: list[str] = []
        for item in value:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks)
    return ""


def _speaker_for(author: str, manager_names: set[str]) -> str:
    normalized = (author or "").strip().lower()
    if normalized in manager_names:
        return "manager"
    return "user"


def _parse_dt(value: str) -> tuple[str, int]:
    raw = (value or "").strip()
    if not raw:
        return "", 0
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw, 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    unix_ms = int(parsed.timestamp() * 1000)
    return parsed.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), unix_ms


def _extract_messages_from_json(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("messages"), list):
        return list(payload["messages"])
    chats = payload.get("chats")
    if isinstance(chats, dict):
        chat_list = chats.get("list")
        if isinstance(chat_list, list):
            for item in chat_list:
                if isinstance(item, dict) and isinstance(item.get("messages"), list):
                    return list(item["messages"])
    return []


def _normalize_json_messages(messages: list[dict[str, Any]], manager_names: set[str]) -> list[ImportedMessage]:
    items: list[ImportedMessage] = []
    for raw in messages:
        if not isinstance(raw, dict):
            continue
        text = _flatten_text(raw.get("text")).strip()
        if not text:
            continue
        timestamp, started_at = _parse_dt(str(raw.get("date") or ""))
        author = str(raw.get("from") or raw.get("actor") or raw.get("author") or "").strip()
        message_id = str(raw.get("id") or f"imported-{len(items)+1}")
        items.append(
            ImportedMessage(
                message_id=message_id,
                started_at=started_at,
                timestamp=timestamp,
                author=author or "unknown",
                speaker=_speaker_for(author, manager_names),
                text=text,
            )
        )
    return items


class _TelegramHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._capture: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key: value or "" for key, value in attrs}
        classes = attrs_map.get("class", "")
        if tag == "div" and "message" in classes and "default" in classes:
            self._current = {}
        if self._current is None:
            return
        if tag == "div" and "from_name" in classes:
            self._capture = "author"
            self._buffer = []
        elif tag == "div" and "text" in classes:
            self._capture = "text"
            self._buffer = []
        elif tag == "div" and "date" in classes:
            title = attrs_map.get("title", "").strip()
            if title:
                self._current["date"] = title
        elif tag == "br" and self._capture == "text":
            self._buffer.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return
        if tag == "div" and self._capture in {"author", "text"}:
            value = unescape("".join(self._buffer)).strip()
            if value:
                self._current[self._capture] = value
            self._capture = None
            self._buffer = []
        elif tag == "div" and self._capture is None and self._current.get("text"):
            self.messages.append(self._current)
            self._current = None

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)


def _normalize_html_messages(html_text: str, manager_names: set[str]) -> list[ImportedMessage]:
    parser = _TelegramHtmlParser()
    parser.feed(html_text)
    items: list[ImportedMessage] = []
    for index, raw in enumerate(parser.messages, start=1):
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        author = str(raw.get("author") or "").strip()
        timestamp, started_at = _parse_dt(str(raw.get("date") or ""))
        items.append(
            ImportedMessage(
                message_id=f"html-{index}",
                started_at=started_at,
                timestamp=timestamp,
                author=author or "unknown",
                speaker=_speaker_for(author, manager_names),
                text=text,
            )
        )
    return items


def import_telegram_history(
    export_path: str | Path,
    session_key: str,
    *,
    manager_name: str = "Leviathann",
    loom_root: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(export_path)
    if not path.exists():
        raise FileNotFoundError(f"export file not found: {path}")
    manager_names = {
        (manager_name or "Leviathann").strip().lower(),
        "leviathann",
        "leviathan",
    }
    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = _normalize_json_messages(_extract_messages_from_json(payload), manager_names)
    elif suffix in {".html", ".htm"}:
        items = _normalize_html_messages(path.read_text(encoding="utf-8"), manager_names)
    else:
        raise ValueError("telegram export import supports .json and .html files only")

    storage_path = _session_path(session_key, loom_root=loom_root)
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "session_key": session_key,
        "source": "telegram_export_import",
        "imported": True,
        "historical": True,
        "manager_name": manager_name,
        "imported_at": _now(),
        "message_count": len(items),
        "messages": [item.__dict__ for item in items],
    }
    storage_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "session_key": session_key,
        "storage_path": str(storage_path),
        "message_count": len(items),
    }


def load_imported_history(session_key: str, *, loom_root: str | Path | None = None) -> dict[str, Any]:
    storage_path = _session_path(session_key, loom_root=loom_root)
    if not storage_path.exists():
        return {}
    return json.loads(storage_path.read_text(encoding="utf-8"))


def imported_history_items(session_key: str, *, loom_root: str | Path | None = None) -> list[dict[str, Any]]:
    payload = load_imported_history(session_key, loom_root=loom_root)
    items: list[dict[str, Any]] = []
    for raw in payload.get("messages", []):
        if not isinstance(raw, dict):
            continue
        item = ImportedMessage(
            message_id=str(raw.get("message_id") or ""),
            started_at=int(raw.get("started_at") or 0),
            timestamp=str(raw.get("timestamp") or ""),
            author=str(raw.get("author") or "unknown"),
            speaker=str(raw.get("speaker") or "user"),
            text=str(raw.get("text") or ""),
        )
        items.append(item.to_history_item(session_key))
    return items


def imported_history_context(session_key: str, *, loom_root: str | Path | None = None, limit: int = 24) -> str:
    items = imported_history_items(session_key, loom_root=loom_root)
    if not items:
        return ""
    lines: list[str] = []
    for item in items[-limit:]:
        speaker = str(item.get("speaker") or "user").strip()
        author = str(item.get("author") or "").strip()
        text = str(item.get("text") or "").strip()
        label = author or speaker
        lines.append(f"{label}: {text}")
    return "\n".join(lines).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Telegram history into Meridian session continuity")
    parser.add_argument("--export-path", required=True)
    parser.add_argument("--session-key", required=True)
    parser.add_argument("--manager-name", default="Leviathann")
    parser.add_argument("--loom-root", default="")
    args = parser.parse_args()
    result = import_telegram_history(
        args.export_path,
        args.session_key,
        manager_name=args.manager_name,
        loom_root=args.loom_root or None,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
