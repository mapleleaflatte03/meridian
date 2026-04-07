#!/usr/bin/env python3
"""Provider-agnostic brain routing for manager/specialist execution."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


DEFAULT_FAILOVER_STATUS_CODES = {401, 402, 403, 408, 409, 429, 500, 502, 503, 504}
DEFAULT_FAILOVER_MARKERS = (
    "quota",
    "insufficient",
    "rate limit",
    "credit",
    "billing",
    "invalid api key",
    "incorrect api key",
    "unauthorized",
    "deactivated",
    "overloaded",
    "temporarily unavailable",
    "timeout",
)
DEFAULT_MANAGER_PROFILE = "manager_primary"
DEFAULT_MANAGER_TRANSPORT = "cli_session"
DEFAULT_MAX_TOKENS = 650
DEFAULT_ROUTER_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "brain_router.sample.json"


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        token = str(value or "").strip()
        if token and token not in out:
            out.append(token)
    return out


def _parse_status_codes(raw: Any, fallback: set[int] | None = None) -> set[int]:
    if isinstance(raw, list):
        values: set[int] = set()
        for item in raw:
            try:
                values.add(int(item))
            except (TypeError, ValueError):
                continue
        return values or set(fallback or set())
    text = str(raw or "").strip()
    if not text:
        return set(fallback or set())
    values = set()
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            values.add(int(token))
        except ValueError:
            continue
    return values or set(fallback or set())


def _parse_csv_values(raw: Any) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    return [item.strip() for item in re.split(r"[\s,;]+", text) if item.strip()]


def _extract_chat_output(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = str(item.get("text") or "").strip()
                if text:
                    parts.append(text)
        if parts:
            return "\n".join(parts).strip()
    return str(message.get("reasoning_content") or "").strip()


def _should_failover(status_code: int | None, detail: str, failover_status_codes: set[int]) -> bool:
    if status_code is not None and status_code in failover_status_codes:
        return True
    lowered = str(detail or "").strip().lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in DEFAULT_FAILOVER_MARKERS)


def _load_router_document(runtime_env: dict[str, str]) -> dict[str, Any]:
    path_value = str(runtime_env.get("MERIDIAN_BRAIN_ROUTER_CONFIG_PATH") or "").strip()
    if not path_value:
        return {}
    path = Path(path_value)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _legacy_manager_key_pool(runtime_env: dict[str, str]) -> list[str]:
    keys = _parse_csv_values(runtime_env.get("MERIDIAN_MANAGER_XAI_API_KEYS"))
    for index in range(1, 10):
        token = str(runtime_env.get(f"MERIDIAN_MANAGER_XAI_API_KEY_{index}") or "").strip()
        if token:
            keys.append(token)
    fallback = str(runtime_env.get("MERIDIAN_MANAGER_XAI_API_KEY") or "").strip()
    if fallback:
        keys.append(fallback)
    return _dedupe(keys)


def _legacy_remote_manager_enabled(runtime_env: dict[str, str]) -> bool:
    value = str(runtime_env.get("MERIDIAN_MANAGER_PROVIDER") or "").strip().lower()
    return value in {"xai", "grok", "xai_pool", "grok_pool"}


def resolve_manager_plan(*, runtime_env: dict[str, str] | None = None, model_hint: str = "") -> dict[str, Any]:
    env = dict(os.environ)
    if runtime_env:
        env.update(runtime_env)
    document = _load_router_document(env)
    manager_doc = document.get("manager") if isinstance(document.get("manager"), dict) else {}

    profile_name = (
        str(env.get("MERIDIAN_BRAIN_MANAGER_PROFILE_NAME") or "").strip()
        or str(manager_doc.get("profile_name") or "").strip()
        or DEFAULT_MANAGER_PROFILE
    )
    transport_kind = (
        str(env.get("MERIDIAN_BRAIN_MANAGER_TRANSPORT") or "").strip().lower()
        or str(manager_doc.get("transport_kind") or "").strip().lower()
    )
    endpoint = (
        str(env.get("MERIDIAN_BRAIN_MANAGER_ENDPOINT") or "").strip()
        or str(manager_doc.get("endpoint") or "").strip()
    )
    model = (
        str(model_hint or "").strip()
        or str(env.get("MERIDIAN_BRAIN_MANAGER_MODEL") or "").strip()
        or str(manager_doc.get("model") or "").strip()
        or str(env.get("MERIDIAN_MANAGER_MODEL") or "").strip()
    )
    cli_bin = (
        str(env.get("MERIDIAN_BRAIN_MANAGER_CLI_BIN") or "").strip()
        or str(manager_doc.get("cli_bin") or "").strip()
        or str(env.get("MERIDIAN_CODEX_BIN") or "").strip()
        or "codex"
    )
    cli_home = (
        str(env.get("MERIDIAN_BRAIN_MANAGER_CLI_HOME") or "").strip()
        or str(manager_doc.get("cli_home") or "").strip()
        or str(env.get("MERIDIAN_CODEX_HOME") or "").strip()
        or "/home/ubuntu/.meridian/auth/codex/login-home"
    )
    max_tokens = int(
        str(
            env.get("MERIDIAN_BRAIN_MANAGER_MAX_TOKENS")
            or manager_doc.get("max_tokens")
            or DEFAULT_MAX_TOKENS
        ).strip()
    )

    key_pool = _parse_csv_values(env.get("MERIDIAN_BRAIN_MANAGER_KEY_POOL"))
    if not key_pool and isinstance(manager_doc.get("key_pool"), list):
        key_pool = [str(item).strip() for item in manager_doc.get("key_pool", []) if str(item).strip()]
    key_env_pool = _parse_csv_values(env.get("MERIDIAN_BRAIN_MANAGER_KEY_ENV_POOL"))
    for env_var in key_env_pool:
        token = str(env.get(env_var) or "").strip()
        if token:
            key_pool.append(token)
    auth_env = str(env.get("MERIDIAN_BRAIN_MANAGER_AUTH_ENV") or "").strip()
    if auth_env and not key_pool:
        token = str(env.get(auth_env) or "").strip()
        if token:
            key_pool.append(token)
    key_pool = _dedupe(key_pool)

    failover_status_codes = _parse_status_codes(
        env.get("MERIDIAN_BRAIN_MANAGER_FAILOVER_STATUS_CODES")
        or manager_doc.get("failover_status_codes"),
        fallback=DEFAULT_FAILOVER_STATUS_CODES,
    )

    migration_note = ""
    if not transport_kind:
        if _legacy_remote_manager_enabled(env):
            transport_kind = "http_json"
            migration_note = "legacy manager provider env mapped to agnostic http_json transport"
        else:
            transport_kind = DEFAULT_MANAGER_TRANSPORT
    if transport_kind == "http_json":
        if not endpoint and _legacy_remote_manager_enabled(env):
            endpoint = str(env.get("MERIDIAN_MANAGER_XAI_BASE_URL") or "").strip()
        if not key_pool and _legacy_remote_manager_enabled(env):
            key_pool = _legacy_manager_key_pool(env)
        if _legacy_remote_manager_enabled(env):
            failover_status_codes = _parse_status_codes(
                env.get("MERIDIAN_MANAGER_XAI_FAILOVER_STATUS_CODES"),
                fallback=failover_status_codes or DEFAULT_FAILOVER_STATUS_CODES,
            )
            if migration_note:
                migration_note += "; "
            migration_note += "legacy API key pool env mapped to agnostic key pool"
    auth_mode = "session_home" if transport_kind == "cli_session" else "bearer_pool"
    return {
        "profile_name": profile_name,
        "transport_kind": transport_kind,
        "endpoint": endpoint,
        "model": model,
        "key_pool": key_pool,
        "failover_status_codes": failover_status_codes,
        "max_tokens": max_tokens,
        "cli_bin": cli_bin,
        "cli_home": cli_home,
        "auth_mode": auth_mode,
        "migration_note": migration_note,
    }


def _run_cli_default(*, command: list[str], env_vars: dict[str, str], timeout: int) -> dict[str, Any]:
    output_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="meridian-brain-cli-", suffix=".txt", delete=False) as handle:
            output_path = handle.name
        command.extend(["-o", output_path])
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env_vars,
        )
        output_text = ""
        if output_path:
            candidate = Path(output_path)
            if candidate.exists():
                output_text = candidate.read_text(encoding="utf-8").strip()
        return {
            "returncode": completed.returncode,
            "stdout": (completed.stdout or "").strip(),
            "stderr": (completed.stderr or "").strip(),
            "output_text": output_text,
        }
    finally:
        if output_path:
            try:
                Path(output_path).unlink(missing_ok=True)
            except Exception:
                pass


def _http_post_default(*, endpoint: str, headers: dict[str, str], payload: dict[str, Any], timeout: int) -> str:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def execute_manager(
    *,
    runtime_env: dict[str, str] | None = None,
    system_prompt: str,
    user_prompt: str,
    model: str,
    timeout: int,
    run_cli: Callable[..., dict[str, Any]] | None = None,
    http_post: Callable[..., str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ)
    if runtime_env:
        env.update(runtime_env)
    plan = resolve_manager_plan(runtime_env=env, model_hint=model)
    model_name = str(plan.get("model") or model or "").strip()
    profile_name = str(plan.get("profile_name") or DEFAULT_MANAGER_PROFILE).strip() or DEFAULT_MANAGER_PROFILE
    transport_kind = str(plan.get("transport_kind") or DEFAULT_MANAGER_TRANSPORT).strip()
    auth_mode = str(plan.get("auth_mode") or "none").strip()
    warnings: list[str] = []
    failover_trace: list[dict[str, Any]] = []

    if transport_kind == "cli_session":
        prompt = (
            f"System instructions:\n{system_prompt.strip()}\n\n"
            f"User request:\n{user_prompt.strip()}\n\n"
            "Return only the final answer for the user."
        )
        command = [
            str(plan.get("cli_bin") or "codex"),
            "exec",
            "-m",
            model_name,
            "--skip-git-repo-check",
            "--ephemeral",
            "--color",
            "never",
            "-C",
            "/home/ubuntu",
            prompt,
        ]
        env_vars = dict(env)
        env_vars["HOME"] = str(plan.get("cli_home") or env_vars.get("HOME") or "").strip()
        cli_runner = run_cli or _run_cli_default
        try:
            cli_result = cli_runner(command=command, env_vars=env_vars, timeout=timeout)
        except Exception as exc:
            return {
                "ok": False,
                "returncode": -1,
                "stdout": "",
                "stderr": f"{exc.__class__.__name__}: {exc}",
                "output_text": "",
                "model": model_name,
                "provider_profile": profile_name,
                "transport_kind": "cli_session",
                "auth_mode": "session_home",
                "failover_trace": failover_trace,
            }
        output_text = str(cli_result.get("output_text") or "").strip()
        returncode = int(cli_result.get("returncode") or 0)
        stderr = str(cli_result.get("stderr") or "").strip()
        stdout = str(cli_result.get("stdout") or "").strip()
        ok = returncode == 0 and bool(output_text)
        if returncode == 0 and not output_text:
            ok = False
            stderr = stderr or "CLI manager route returned empty output"
        return {
            "ok": ok,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "output_text": output_text,
            "model": model_name,
            "provider_profile": profile_name,
            "transport_kind": "cli_session",
            "auth_mode": "session_home",
            "failover_trace": failover_trace,
        }

    endpoint = str(plan.get("endpoint") or "").strip()
    key_pool = list(plan.get("key_pool") or [])
    failover_status_codes = set(plan.get("failover_status_codes") or set())
    if not endpoint:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "manager route missing MERIDIAN_BRAIN_MANAGER_ENDPOINT",
            "output_text": "",
            "model": model_name,
            "provider_profile": profile_name,
            "transport_kind": "http_json",
            "auth_mode": auth_mode,
            "warnings": warnings,
            "failover_trace": failover_trace,
        }
    if not key_pool:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "manager route missing key pool",
            "output_text": "",
            "model": model_name,
            "provider_profile": profile_name,
            "transport_kind": "http_json",
            "auth_mode": auth_mode,
            "warnings": warnings,
            "failover_trace": failover_trace,
        }
    post = http_post or _http_post_default
    max_tokens = int(plan.get("max_tokens") or DEFAULT_MAX_TOKENS)

    for index, api_key in enumerate(key_pool, start=1):
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
        }
        try:
            raw_body = post(endpoint=endpoint, headers=headers, payload=payload, timeout=timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            detail = body or str(exc)
            should_failover = index < len(key_pool) and _should_failover(exc.code, detail, failover_status_codes)
            failover_trace.append(
                {
                    "key_slot": index,
                    "outcome": "http_error",
                    "status_code": exc.code,
                    "detail": detail[:200],
                    "failover_to_next": should_failover,
                }
            )
            if should_failover:
                warnings.append(f"key slot {index} failed with HTTP {exc.code}; switched to next key")
                continue
            return {
                "ok": False,
                "returncode": exc.code or -1,
                "stdout": "",
                "stderr": f"HTTP {exc.code}: {detail[:300]}",
                "output_text": "",
                "model": model_name,
                "provider_profile": profile_name,
                "transport_kind": "http_json",
                "auth_mode": auth_mode,
                "key_slot": index,
                "warnings": warnings,
                "failover_trace": failover_trace,
            }
        except Exception as exc:
            detail = f"{exc.__class__.__name__}: {exc}"
            should_failover = index < len(key_pool) and _should_failover(None, detail, failover_status_codes)
            failover_trace.append(
                {
                    "key_slot": index,
                    "outcome": "transport_error",
                    "status_code": None,
                    "detail": detail[:200],
                    "failover_to_next": should_failover,
                }
            )
            if should_failover:
                warnings.append(f"key slot {index} failed ({detail}); switched to next key")
                continue
            return {
                "ok": False,
                "returncode": -1,
                "stdout": "",
                "stderr": detail[:300],
                "output_text": "",
                "model": model_name,
                "provider_profile": profile_name,
                "transport_kind": "http_json",
                "auth_mode": auth_mode,
                "key_slot": index,
                "warnings": warnings,
                "failover_trace": failover_trace,
            }

        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError:
            parsed = {}
        output_text = _extract_chat_output(parsed)
        if output_text:
            failover_trace.append(
                {
                    "key_slot": index,
                    "outcome": "success",
                    "status_code": 200,
                    "detail": "",
                    "failover_to_next": False,
                }
            )
            return {
                "ok": True,
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "output_text": output_text,
                "model": str(parsed.get("model") or model_name),
                "provider_profile": profile_name,
                "transport_kind": "http_json",
                "auth_mode": auth_mode,
                "key_slot": index,
                "warnings": warnings,
                "failover_trace": failover_trace,
            }
        detail = str(parsed.get("error") or parsed or "empty output").strip()
        should_failover = index < len(key_pool) and _should_failover(None, detail, failover_status_codes)
        failover_trace.append(
            {
                "key_slot": index,
                "outcome": "empty_payload",
                "status_code": None,
                "detail": detail[:200],
                "failover_to_next": should_failover,
            }
        )
        if should_failover:
            warnings.append(f"key slot {index} returned empty/invalid payload; switched to next key")
            continue
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"empty output: {detail[:300]}",
            "output_text": "",
            "model": model_name,
            "provider_profile": profile_name,
            "transport_kind": "http_json",
            "auth_mode": auth_mode,
            "key_slot": index,
            "warnings": warnings,
            "failover_trace": failover_trace,
        }
    return {
        "ok": False,
        "returncode": -1,
        "stdout": "",
        "stderr": "key pool exhausted without successful response",
        "output_text": "",
        "model": model_name,
        "provider_profile": profile_name,
        "transport_kind": "http_json",
        "auth_mode": auth_mode,
        "warnings": warnings,
        "failover_trace": failover_trace,
    }


def manager_exec_metadata(*, runtime_env: dict[str, str] | None = None, model_hint: str = "") -> dict[str, str]:
    plan = resolve_manager_plan(runtime_env=runtime_env, model_hint=model_hint)
    return {
        "provider_profile": str(plan.get("profile_name") or DEFAULT_MANAGER_PROFILE).strip() or DEFAULT_MANAGER_PROFILE,
        "model": str(plan.get("model") or model_hint or "").strip(),
        "transport_kind": str(plan.get("transport_kind") or DEFAULT_MANAGER_TRANSPORT).strip() or DEFAULT_MANAGER_TRANSPORT,
        "auth_mode": str(plan.get("auth_mode") or "none").strip() or "none",
    }


def execute_specialist_http(
    *,
    profile_name: str,
    endpoint: str,
    model: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    timeout: int,
    http_post: Callable[..., str] | None = None,
) -> dict[str, Any]:
    if not endpoint:
        return {"ok": False, "error": "missing specialist endpoint"}
    if not api_key:
        return {"ok": False, "error": "missing specialist API key"}
    post = http_post or _http_post_default
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        raw_body = post(endpoint=endpoint, headers=headers, payload=payload, timeout=timeout)
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "error": f"direct provider fallback HTTP {exc.code}",
            "status_code": exc.code,
            "body": exc.read().decode("utf-8", errors="replace"),
            "provider_profile": profile_name,
            "transport_kind": "http_json",
            "auth_mode": "bearer_env",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"direct provider fallback failed: {exc}",
            "provider_profile": profile_name,
            "transport_kind": "http_json",
            "auth_mode": "bearer_env",
        }
    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError:
        parsed = {}
    output_text = _extract_chat_output(parsed)
    return {
        "ok": bool(output_text),
        "output_text": output_text,
        "raw_output": raw_body,
        "model": str(parsed.get("model") or model),
        "response": parsed,
        "provider_profile": profile_name,
        "transport_kind": "http_json",
        "auth_mode": "bearer_env",
    }
