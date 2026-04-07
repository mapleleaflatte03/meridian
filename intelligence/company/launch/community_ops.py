#!/usr/bin/env python3
"""Meridian community operations publisher.

This script turns launch templates into a repeatable operator lane:
- Pulls lightweight live status from app routes.
- Builds a concise community update payload.
- Optionally posts to Discord via webhook.
- Persists an audit artifact for every run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_SITE = "https://app.welliam.codes"
ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def _json_get(url: str, origin: str, timeout: float = 8.0) -> dict[str, Any]:
    req = Request(
        url,
        method="GET",
        headers={
            "Origin": origin,
            "Accept": "application/json",
            "User-Agent": "meridian-community-ops/1.0",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310
            payload = resp.read().decode("utf-8")
            loaded = json.loads(payload)
            if isinstance(loaded, dict):
                return loaded
            return {}
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return {}


def _build_message(site: str, status: dict[str, Any], proof: dict[str, Any]) -> str:
    slo = status.get("slo") if isinstance(status.get("slo"), dict) else {}
    objectives = slo.get("objectives")
    objective_count = len(objectives) if isinstance(objectives, list) else 0
    proof_state = str(proof.get("proof_type") or proof.get("status") or "unknown")
    evaluated = str(slo.get("evaluated_at") or status.get("evaluated_at") or "unknown")
    return (
        "Meridian weekly operator update\n"
        f"- runtime status evaluated: {evaluated}\n"
        f"- objective checks reported: {objective_count}\n"
        f"- runtime proof status: {proof_state}\n"
        f"- proofs: {site}/proofs\n"
        f"- workflows: {site}/workflows\n"
        f"- community: {site}/community"
    )


def _post_discord(webhook_url: str, message: str, timeout: float = 8.0) -> dict[str, Any]:
    payload = json.dumps({"content": message}).encode("utf-8")
    req = Request(
        webhook_url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return {"ok": True, "http_status": int(resp.status)}
    except HTTPError as exc:
        return {"ok": False, "http_status": int(exc.code), "error": str(exc)}
    except (URLError, TimeoutError) as exc:
        return {"ok": False, "error": str(exc)}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Publish Meridian community ops update")
    parser.add_argument("--site", default=DEFAULT_SITE, help="Public site base URL")
    parser.add_argument(
        "--discord-webhook",
        default=os.environ.get("MERIDIAN_DISCORD_WEBHOOK_URL", ""),
        help="Discord webhook URL (or set MERIDIAN_DISCORD_WEBHOOK_URL)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not send network posts")
    args = parser.parse_args(argv)

    site = str(args.site or DEFAULT_SITE).rstrip("/")
    status = _json_get(f"{site}/api/status", site)
    proof = _json_get(f"{site}/api/runtime-proof", site)
    message = _build_message(site, status, proof)

    publish_result: dict[str, Any] = {"ok": False, "skipped": True, "reason": "dry_run_or_missing_webhook"}
    if not args.dry_run and args.discord_webhook:
        publish_result = _post_discord(args.discord_webhook, message)
    artifact = {
        "schema_version": "community_ops_publish_v1",
        "published_at_unix_ms": int(time.time() * 1000),
        "site": site,
        "dry_run": bool(args.dry_run),
        "status_snapshot": {
            "evaluated_at": (status.get("slo") or {}).get("evaluated_at")
            if isinstance(status.get("slo"), dict)
            else status.get("evaluated_at"),
            "status": (status.get("slo") or {}).get("status")
            if isinstance(status.get("slo"), dict)
            else status.get("status"),
        },
        "proof_snapshot": {
            "status": proof.get("proof_type") or proof.get("status"),
        },
        "publish_result": publish_result,
        "message_preview": message,
    }
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    target = ARTIFACT_DIR / f"community_ops_{stamp}.json"
    target.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest = ARTIFACT_DIR / "community_ops_latest.json"
    latest.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"status": "ok", "artifact": str(target), "latest": str(latest)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
