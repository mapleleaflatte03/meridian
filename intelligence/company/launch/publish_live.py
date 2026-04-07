#!/usr/bin/env python3
"""Publish Meridian launch updates to live community channels with audit artifacts."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_SITE = "https://app.welliam.codes"
DEFAULT_CHANNELS = ("x", "reddit", "hn", "discord")
NETWORK_TIMEOUT_SECONDS = 20.0


class PublishError(RuntimeError):
    """Raised when a channel publish call fails."""


@dataclass
class ChannelResult:
    channel: str
    status: str
    reason: str = ""
    details: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "channel": self.channel,
            "status": self.status,
            "reason": self.reason,
        }
        if self.details:
            payload["details"] = self.details
        return payload


def _now_ms() -> int:
    return int(time.time() * 1000)


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def _safe_read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _normalize_channels(raw: list[str] | str | None) -> list[str]:
    if raw is None:
        return list(DEFAULT_CHANNELS)
    if isinstance(raw, str):
        chunks = [raw]
    else:
        chunks = raw
    result: list[str] = []
    for chunk in chunks:
        for token in str(chunk).split(","):
            normalized = token.strip().lower()
            if not normalized:
                continue
            if normalized not in DEFAULT_CHANNELS:
                raise PublishError(f"unsupported channel '{normalized}'")
            if normalized not in result:
                result.append(normalized)
    if not result:
        return list(DEFAULT_CHANNELS)
    return result


def _request_text(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: float = NETWORK_TIMEOUT_SECONDS,
) -> tuple[int, str, str]:
    req = Request(url, method=method, headers=headers or {}, data=data)
    try:
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read().decode("utf-8", errors="replace")
            return int(resp.status), body, str(resp.url)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise PublishError(f"http_{exc.code}: {body[:400]}") from exc
    except URLError as exc:
        raise PublishError(f"network_error: {exc}") from exc
    except TimeoutError as exc:
        raise PublishError("network_timeout") from exc


def _request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    form: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any], str]:
    data: bytes | None = None
    req_headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    elif form is not None:
        data = urlencode(form).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    status, body, final_url = _request_text(
        url,
        method=method,
        headers=req_headers,
        data=data,
    )
    try:
        parsed = json.loads(body) if body else {}
        if isinstance(parsed, dict):
            return status, parsed, final_url
    except json.JSONDecodeError:
        pass
    return status, {"raw": body}, final_url


def _require_env(env: dict[str, str], key: str) -> str:
    value = str(env.get(key, "")).strip()
    if not value:
        raise PublishError(f"missing_credential:{key}")
    return value


def _line_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:220]
    return fallback


def _x_compose_text(x_thread_text: str, site: str) -> str:
    first = _line_title(
        x_thread_text,
        "Meridian Loom: governed runtime with proof receipts.",
    )
    if len(first) <= 240:
        return f"{first}\n\n{site}/loom\n{site}/proofs"
    return f"{first[:220]}...\n\n{site}/loom\n{site}/proofs"


def _publish_x(*, launch_dir: Path, site: str, env: dict[str, str]) -> ChannelResult:
    token = _require_env(env, "MERIDIAN_X_API_TOKEN")
    post_url = env.get("MERIDIAN_X_POST_URL", "https://api.x.com/2/tweets").strip()
    thread_text = _safe_read_text(launch_dir / "x_thread.md")
    composed = _x_compose_text(thread_text, site)
    status, payload, _ = _request_json(
        post_url,
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
        payload={"text": composed},
    )
    post_id = str((payload.get("data") or {}).get("id") or "").strip()
    post_url_public = f"https://x.com/i/web/status/{post_id}" if post_id else ""
    return ChannelResult(
        channel="x",
        status="posted" if post_id else "posted_unverified",
        details={
            "http_status": status,
            "post_id": post_id,
            "post_url": post_url_public,
        },
    )


def _reddit_token(*, env: dict[str, str]) -> str:
    client_id = _require_env(env, "MERIDIAN_REDDIT_CLIENT_ID")
    client_secret = _require_env(env, "MERIDIAN_REDDIT_CLIENT_SECRET")
    username = _require_env(env, "MERIDIAN_REDDIT_USERNAME")
    password = _require_env(env, "MERIDIAN_REDDIT_PASSWORD")
    user_agent = env.get("MERIDIAN_REDDIT_USER_AGENT", "meridian-launch-bot/1.0").strip()
    token_url = env.get("MERIDIAN_REDDIT_TOKEN_URL", "https://www.reddit.com/api/v1/access_token").strip()
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("utf-8")
    status, payload, _ = _request_json(
        token_url,
        method="POST",
        headers={
            "Authorization": f"Basic {auth}",
            "User-Agent": user_agent,
        },
        form={
            "grant_type": "password",
            "username": username,
            "password": password,
        },
    )
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise PublishError(f"reddit_token_failed:http_{status}")
    return token


def _publish_reddit(*, launch_dir: Path, site: str, env: dict[str, str]) -> ChannelResult:
    token = _reddit_token(env=env)
    submit_url = env.get("MERIDIAN_REDDIT_SUBMIT_URL", "https://oauth.reddit.com/api/submit").strip()
    user_agent = env.get("MERIDIAN_REDDIT_USER_AGENT", "meridian-launch-bot/1.0").strip()
    subreddit_map = {
        "LLMDevs": launch_dir / "reddit_llmdevs.md",
        "LocalLLaMA": launch_dir / "reddit_localllama.md",
    }
    override = env.get("MERIDIAN_REDDIT_SUBREDDITS", "").strip()
    if override:
        selected = [item.strip() for item in override.split(",") if item.strip()]
    else:
        selected = ["LLMDevs", "LocalLLaMA"]
    posts: list[dict[str, Any]] = []
    for subreddit in selected:
        source = subreddit_map.get(subreddit, launch_dir / "reddit_llmdevs.md")
        body = _safe_read_text(source)
        title = _line_title(body, f"Showcase: Meridian Loom on {site}/loom")
        status, payload, _ = _request_json(
            submit_url,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": user_agent,
            },
            form={
                "api_type": "json",
                "kind": "self",
                "sr": subreddit,
                "title": title,
                "text": body,
            },
        )
        errors = (
            payload.get("json", {})
            .get("errors", [])
            if isinstance(payload.get("json"), dict)
            else []
        )
        if errors:
            raise PublishError(f"reddit_submit_failed:{subreddit}:{errors}")
        posts.append(
            {
                "subreddit": subreddit,
                "http_status": status,
                "title": title,
            }
        )
    return ChannelResult(channel="reddit", status="posted", details={"posts": posts})


def _extract_input_value(html: str, name: str) -> str:
    pattern = rf'name="{re.escape(name)}"[^>]*value="([^"]+)"'
    match = re.search(pattern, html)
    if not match:
        return ""
    return match.group(1).strip()


def _publish_hn(*, launch_dir: Path, site: str, env: dict[str, str]) -> ChannelResult:
    username = _require_env(env, "MERIDIAN_HN_USERNAME")
    password = _require_env(env, "MERIDIAN_HN_PASSWORD")
    login_url = env.get("MERIDIAN_HN_LOGIN_URL", "https://news.ycombinator.com/login").strip()
    submit_url = env.get("MERIDIAN_HN_SUBMIT_URL", "https://news.ycombinator.com/submit").strip()
    submit_action_url = env.get("MERIDIAN_HN_SUBMIT_ACTION_URL", "https://news.ycombinator.com/r").strip()
    show_hn_url = env.get("MERIDIAN_HN_TARGET_URL", f"{site}/loom").strip()
    note = _safe_read_text(launch_dir / "show_hn_short.md")
    title = env.get(
        "MERIDIAN_HN_TITLE",
        "Show HN: Meridian Loom - Governed local runtime with proof receipts",
    ).strip()

    # login step
    _, login_page, _ = _request_text(login_url, method="GET")
    goto = _extract_input_value(login_page, "goto") or "news"
    _, _, after_login = _request_text(
        login_url,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=urlencode({"acct": username, "pw": password, "goto": goto}).encode("utf-8"),
    )
    if "login" in after_login:
        raise PublishError("hn_login_failed")

    # submit step
    _, submit_page, _ = _request_text(submit_url, method="GET")
    fnid = _extract_input_value(submit_page, "fnid")
    if not fnid:
        raise PublishError("hn_submit_fnid_missing")
    _, submit_response, _ = _request_text(
        submit_action_url,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=urlencode(
            {"fnid": fnid, "fnop": "submit-page", "title": title, "url": show_hn_url, "text": note}
        ).encode("utf-8"),
    )
    item_match = re.search(r"item\?id=(\d+)", submit_response)
    if not item_match:
        raise PublishError("hn_submit_unverified")
    item_id = item_match.group(1)
    return ChannelResult(
        channel="hn",
        status="posted",
        details={
            "item_id": item_id,
            "item_url": f"https://news.ycombinator.com/item?id={item_id}",
        },
    )


def _publish_discord(*, launch_dir: Path, site: str, env: dict[str, str]) -> ChannelResult:
    webhook = _require_env(env, "MERIDIAN_DISCORD_WEBHOOK_URL")
    text = _safe_read_text(launch_dir / "COMMUNITY_MOTION.md")
    message = f"{text[:1700]}\n\nProofs: {site}/proofs\nWorkflows: {site}/workflows"
    status, payload, _ = _request_json(
        webhook,
        method="POST",
        payload={"content": message},
    )
    return ChannelResult(
        channel="discord",
        status="posted",
        details={"http_status": status, "response": payload},
    )


def _write_artifact(artifact_dir: Path, payload: dict[str, Any]) -> dict[str, str]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stamped = artifact_dir / f"publish_live_{_timestamp()}.json"
    latest = artifact_dir / "publish_live_latest.json"
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    stamped.write_text(serialized, encoding="utf-8")
    latest.write_text(serialized, encoding="utf-8")
    return {"artifact": str(stamped), "latest": str(latest)}


def run_publish_lane(
    *,
    launch_dir: Path,
    artifact_dir: Path,
    dry_run: bool,
    channels: list[str] | str | None,
    site: str,
    fail_on_missing_creds: bool,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env_map = dict(os.environ if env is None else env)
    resolved_channels = _normalize_channels(channels)
    results: list[ChannelResult] = []
    failures: list[dict[str, Any]] = []

    handlers = {
        "x": _publish_x,
        "reddit": _publish_reddit,
        "hn": _publish_hn,
        "discord": _publish_discord,
    }

    for channel in resolved_channels:
        if dry_run:
            results.append(
                ChannelResult(
                    channel=channel,
                    status="dry_run",
                    reason="dry_run_enabled",
                )
            )
            continue
        handler = handlers[channel]
        try:
            result = handler(launch_dir=launch_dir, site=site, env=env_map)
            results.append(result)
        except PublishError as error:
            reason = str(error)
            status = "missing_credentials" if reason.startswith("missing_credential:") else "error"
            failed = ChannelResult(channel=channel, status=status, reason=reason)
            results.append(failed)
            if status == "missing_credentials" and not fail_on_missing_creds:
                continue
            failures.append(failed.as_dict())
        except Exception as error:  # pragma: no cover - defensive path
            failed = ChannelResult(channel=channel, status="error", reason=f"unexpected:{error}")
            results.append(failed)
            failures.append(failed.as_dict())

    payload = {
        "schema_version": "meridian.launch.publish_live.v1",
        "generated_at_unix_ms": _now_ms(),
        "site": site.rstrip("/"),
        "dry_run": bool(dry_run),
        "channels": resolved_channels,
        "status": "ok" if not failures else "failed",
        "results": [result.as_dict() for result in results],
        "results_by_channel": {result.channel: result.as_dict() for result in results},
        "failures": failures,
    }
    paths = _write_artifact(artifact_dir, payload)
    payload["artifact_path"] = paths["artifact"]
    payload["latest_artifact_path"] = paths["latest"]
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish Meridian launch posts to live channels")
    parser.add_argument(
        "--launch-dir",
        default=str(Path(__file__).resolve().parent),
        help="Directory containing launch markdown assets",
    )
    parser.add_argument(
        "--artifact-dir",
        default=str(Path(__file__).resolve().parent / "artifacts"),
        help="Directory for publish artifacts",
    )
    parser.add_argument(
        "--channels",
        default="x,reddit,hn,discord",
        help="Comma-separated channels: x,reddit,hn,discord",
    )
    parser.add_argument("--site", default=DEFAULT_SITE, help="Public Meridian site base URL")
    parser.add_argument("--dry-run", action="store_true", help="Build artifacts without external posting")
    parser.add_argument(
        "--allow-missing-creds",
        action="store_true",
        help="Do not fail if a channel is missing credentials",
    )
    args = parser.parse_args(argv)

    payload = run_publish_lane(
        launch_dir=Path(args.launch_dir).resolve(),
        artifact_dir=Path(args.artifact_dir).resolve(),
        dry_run=bool(args.dry_run),
        channels=args.channels,
        site=str(args.site).strip() or DEFAULT_SITE,
        fail_on_missing_creds=not bool(args.allow_missing_creds),
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
