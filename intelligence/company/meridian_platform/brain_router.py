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

import institution_brain_policy


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
POLICY_OVERRIDE_ENV_NAMES = (
    "MERIDIAN_BRAIN_MANAGER_PROFILE_NAME",
    "MERIDIAN_BRAIN_MANAGER_TRANSPORT",
    "MERIDIAN_BRAIN_MANAGER_ENDPOINT",
    "MERIDIAN_BRAIN_MANAGER_MODEL",
    "MERIDIAN_BRAIN_MANAGER_CLI_BIN",
    "MERIDIAN_BRAIN_MANAGER_CLI_HOME",
    "MERIDIAN_BRAIN_MANAGER_KEY_POOL",
    "MERIDIAN_BRAIN_MANAGER_KEY_ENV_POOL",
    "MERIDIAN_BRAIN_MANAGER_AUTH_ENV",
    "MERIDIAN_BRAIN_MANAGER_FAILOVER_STATUS_CODES",
)


class RoutePolicyError(RuntimeError):
    def __init__(self, code: str, message: str, *, metadata: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.metadata = dict(metadata or {})

    def as_result(self) -> dict[str, Any]:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": self.message,
            "output_text": "",
            "error_code": self.code,
            "error_metadata": dict(self.metadata),
            "model": "",
            "provider_profile": DEFAULT_MANAGER_PROFILE,
            "transport_kind": DEFAULT_MANAGER_TRANSPORT,
            "auth_mode": "none",
            "failover_trace": [],
        }


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


def _has_policy_override(env: dict[str, str]) -> bool:
    return any(bool(str(env.get(name) or "").strip()) for name in POLICY_OVERRIDE_ENV_NAMES)


def _route_allowed(route: dict[str, Any]) -> tuple[bool, str]:
    if not route.get("approved_by_authority", True):
        return False, "route exists but is not authority-approved"
    if not route.get("allowed_by_treasury", True):
        return False, "route exists but violates treasury policy"
    if route.get("disabled"):
        return False, str(route.get("disable_reason") or "all routes disabled by billing/auth/cooldown").strip()
    cooldown = str(route.get("cooldown_until") or "").strip()
    if cooldown:
        import datetime as _dt
        try:
            deadline = _dt.datetime.fromisoformat(cooldown.replace("Z", "+00:00"))
            if _dt.datetime.now(_dt.timezone.utc) < deadline:
                return False, f"route in cooldown until {cooldown}"
        except (ValueError, TypeError):
            pass
    if str(route.get("last_health") or "").strip() == "blocked":
        reason = str(route.get("last_health_reason") or "route health is blocked").strip()
        return False, reason
    return True, ""


def _policy_route_to_plan(route: dict[str, Any], policy: dict[str, Any], *, model_hint: str = "") -> dict[str, Any]:
    auth_profiles = dict(policy.get("auth_profiles") or {})
    auth_profile_name = ""
    auth_profile: dict[str, Any] = {}
    for item in list(route.get("auth_profile_order") or []):
        candidate = str(item or "").strip()
        if not candidate:
            continue
        auth_profile_name = candidate
        auth_profile = dict(auth_profiles.get(candidate) or {})
        if auth_profile:
            break
    transport_kind = str(route.get("route_type") or "").strip().lower()
    if transport_kind not in {"cli_session", "http_json"}:
        raise RoutePolicyError("no_active_execution_route_configured", "no active execution route configured")

    model = str(model_hint or route.get("model") or "").strip()
    failover_classes = list(
        route.get("failover_error_classes")
        or policy.get("failover_policy", {}).get("error_classes")
        or institution_brain_policy.DEFAULT_FAILOVER_ERROR_CLASSES
    )
    failover_status_codes = (
        DEFAULT_FAILOVER_STATUS_CODES
        if any(item in {"billing", "auth", "rate_limit", "provider_unavailable", "transport"} for item in failover_classes)
        else set(DEFAULT_FAILOVER_STATUS_CODES)
    )

    endpoint = str(route.get("endpoint") or auth_profile.get("endpoint") or "").strip()
    key_env_pool = list(route.get("key_env_pool") or auth_profile.get("key_env_pool") or [])
    key_pool = _dedupe([
        str(os.environ.get(name) or "").strip()
        for name in key_env_pool
        if str(os.environ.get(name) or "").strip()
    ])
    auth_env = str(route.get("auth_env") or auth_profile.get("auth_env") or "").strip()
    if auth_env and not key_pool:
        token = str(os.environ.get(auth_env) or "").strip()
        if token:
            key_pool.append(token)

    provider_ref = str(route.get("provider_ref") or route.get("provider_profile") or auth_profile_name or "").strip() or DEFAULT_MANAGER_PROFILE
    model_ref = str(route.get("model_ref") or "").strip()
    provider_registry = dict(policy.get("provider_registry") or {})
    model_registry = dict(policy.get("model_registry") or {})

    return {
        "profile_name": provider_ref,
        "transport_kind": transport_kind,
        "endpoint": endpoint,
        "model": model,
        "key_pool": key_pool,
        "failover_status_codes": failover_status_codes,
        "max_tokens": int(policy.get("max_tokens") or DEFAULT_MAX_TOKENS),
        "cli_bin": str(route.get("cli_bin") or auth_profile.get("cli_bin") or "").strip(),
        "cli_home": str(route.get("cli_home") or auth_profile.get("cli_home") or "").strip(),
        "auth_mode": str(auth_profile.get("auth_mode") or ("session_home" if transport_kind == "cli_session" else "bearer_pool")).strip(),
        "migration_note": "",
        "policy_route_id": str(route.get("route_id") or "").strip(),
        "policy_source": "institution_policy",
        "policy_auth_profile": auth_profile_name,
        "policy_provider_ref": provider_ref,
        "policy_model_ref": model_ref,
        "policy_provider_entry": dict(provider_registry.get(provider_ref) or {}),
        "policy_model_entry": dict(model_registry.get(model_ref) or {}),
        "policy_fallback_route_ids": list(route.get("fallback_route_ids") or []),
        "policy_disable_reason": str(route.get("disable_reason") or "").strip(),
        "policy_budget_band": str(route.get("budget_band") or "").strip(),
        "policy_org_id": str(policy.get("institution_id") or "").strip(),
    }


def _resolve_policy_plan(env: dict[str, str], model_hint: str = "") -> dict[str, Any] | None:
    if _has_policy_override(env):
        return None
    org_id = str(env.get("MERIDIAN_WORKSPACE_ORG_ID") or env.get("MERIDIAN_ORG_ID") or "").strip()
    if not org_id:
        return None
    policy = institution_brain_policy.load_policy(org_id)
    route = institution_brain_policy.active_route(policy)
    if not route:
        raise RoutePolicyError(
            "no_active_execution_route_configured",
            "no active execution route configured",
            metadata={"org_id": org_id},
        )
    allowed, reason = _route_allowed(route)
    if not allowed:
        if "authority-approved" in reason:
            raise RoutePolicyError("route_not_authority_approved", reason, metadata={"org_id": org_id, "route_id": route.get("route_id", "")})
        if "treasury policy" in reason:
            raise RoutePolicyError("route_not_treasury_allowed", reason, metadata={"org_id": org_id, "route_id": route.get("route_id", "")})
        raise RoutePolicyError("all_routes_disabled_by_billing_or_cooldown", reason, metadata={"org_id": org_id, "route_id": route.get("route_id", "")})
    return _policy_route_to_plan(route, policy, model_hint=model_hint)


def _update_policy_success(plan: dict[str, Any], *, failover_trace: list[dict[str, Any]] | None = None) -> None:
    if str(plan.get("policy_source") or "") != "institution_policy":
        return
    org_id = str(plan.get("policy_org_id") or os.environ.get("MERIDIAN_WORKSPACE_ORG_ID") or os.environ.get("MERIDIAN_ORG_ID") or "").strip()
    route_id = str(plan.get("policy_route_id") or "").strip()
    if not org_id or not route_id:
        return
    institution_brain_policy.update_route_health(
        org_id,
        route_id=route_id,
        health="healthy",
        reason="",
        failover=(failover_trace or [])[-1] if failover_trace else {},
        updated_by="brain_router",
    )


def _update_policy_failure(plan: dict[str, Any], *, detail: str, failover_trace: list[dict[str, Any]] | None = None) -> None:
    if str(plan.get("policy_source") or "") != "institution_policy":
        return
    org_id = str(plan.get("policy_org_id") or os.environ.get("MERIDIAN_WORKSPACE_ORG_ID") or os.environ.get("MERIDIAN_ORG_ID") or "").strip()
    route_id = str(plan.get("policy_route_id") or "").strip()
    if not org_id or not route_id:
        return
    reason_class = institution_brain_policy.classify_reason(detail)
    institution_brain_policy.update_route_health(
        org_id,
        route_id=route_id,
        health="blocked" if reason_class in {"billing", "auth"} else "degraded",
        reason=detail,
        failover=(failover_trace or [])[-1] if failover_trace else {},
        updated_by="brain_router",
    )


def _route_chain_from_policy(plan: dict[str, Any], *, _cached_policy: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if str(plan.get("policy_source") or "") != "institution_policy":
        return [plan]
    org_id = str(plan.get("policy_org_id") or os.environ.get("MERIDIAN_WORKSPACE_ORG_ID") or os.environ.get("MERIDIAN_ORG_ID") or "").strip()
    if not org_id:
        return [plan]
    policy = _cached_policy or institution_brain_policy.load_policy(org_id)
    chain: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for route in institution_brain_policy.resolve_route_chain(policy):
        allowed, reason = _route_allowed(route)
        if not allowed:
            skipped.append({"route_id": str(route.get("route_id") or ""), "reason": reason})
            continue
        converted = _policy_route_to_plan(route, policy, model_hint=str(plan.get("model") or "").strip())
        converted["_skipped_routes"] = skipped
        chain.append(converted)
    return chain or [plan]


def _structured_route_error(
    code: str,
    message: str,
    *,
    plan: dict[str, Any] | None = None,
    failover_trace: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "ok": False,
        "returncode": -1,
        "stdout": "",
        "stderr": message,
        "output_text": "",
        "error_code": code,
        "error_metadata": dict(metadata or {}),
        "failover_trace": list(failover_trace or []),
    }
    if isinstance(plan, dict):
        payload.update(
            {
                "model": str(plan.get("model") or "").strip(),
                "provider_profile": str(plan.get("profile_name") or DEFAULT_MANAGER_PROFILE).strip() or DEFAULT_MANAGER_PROFILE,
                "transport_kind": str(plan.get("transport_kind") or DEFAULT_MANAGER_TRANSPORT).strip() or DEFAULT_MANAGER_TRANSPORT,
                "auth_mode": str(plan.get("auth_mode") or "none").strip() or "none",
                "policy_source": str(plan.get("policy_source") or ""),
                "policy_route_id": str(plan.get("policy_route_id") or ""),
                "policy_auth_profile": str(plan.get("policy_auth_profile") or ""),
            }
        )
    return payload


def _resolve_manager_plan_with_source(*, runtime_env: dict[str, str] | None = None, model_hint: str = "") -> dict[str, Any]:
    env = dict(os.environ)
    if runtime_env:
        env.update(runtime_env)

    policy_plan = _resolve_policy_plan(env, model_hint=model_hint)
    if policy_plan is not None:
        return policy_plan

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
    )
    cli_home = (
        str(env.get("MERIDIAN_BRAIN_MANAGER_CLI_HOME") or "").strip()
        or str(manager_doc.get("cli_home") or "").strip()
        or str(env.get("MERIDIAN_CODEX_HOME") or "").strip()
    )
    if not cli_home:
        cli_home = str(env.get("HOME") or "").strip() or "/tmp"
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
        elif cli_bin:
            transport_kind = "cli_session"
        elif endpoint:
            transport_kind = "http_json"
        else:
            raise RoutePolicyError(
                "no_active_execution_route_configured",
                "no active execution route configured",
            )
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

    if transport_kind == "cli_session" and not cli_bin:
        raise RoutePolicyError(
            "no_active_execution_route_configured",
            "no active execution route configured",
        )
    if transport_kind == "http_json" and not endpoint:
        raise RoutePolicyError(
            "no_active_execution_route_configured",
            "no active execution route configured",
        )

    provider_ref = str(manager_doc.get("provider_ref") or profile_name).strip() or DEFAULT_MANAGER_PROFILE
    model_ref = str(manager_doc.get("model_ref") or "").strip()
    provider_entry = dict(manager_doc.get("provider_entry") or {})
    if provider_ref and not provider_entry:
        provider_entry = {
            "provider_id": provider_ref,
            "display_name": provider_ref,
            "default_route_type": transport_kind,
            "capabilities": [transport_kind],
            "metadata": {},
        }
    model_entry = dict(manager_doc.get("model_entry") or {})
    if model_ref and not model_entry:
        model_entry = {
            "model_id": model_ref,
            "provider_id": provider_ref,
            "model_name": model,
            "metadata": {},
        }

    auth_mode = "session_home" if transport_kind == "cli_session" else "bearer_pool"
    return {
        "profile_name": provider_ref,
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
        "policy_source": "override",
        "policy_route_id": "",
        "policy_auth_profile": "",
        "policy_provider_ref": provider_ref,
        "policy_model_ref": model_ref,
        "policy_provider_entry": provider_entry,
        "policy_model_entry": model_entry,
        "policy_fallback_route_ids": [],
        "policy_disable_reason": "",
        "policy_budget_band": "",
    }


def resolve_manager_plan(*, runtime_env: dict[str, str] | None = None, model_hint: str = "") -> dict[str, Any]:
    return _resolve_manager_plan_with_source(runtime_env=runtime_env, model_hint=model_hint)


def _run_claude_cli_default(*, command: list[str], env_vars: dict[str, str], timeout: int) -> dict[str, Any]:
    """Run claude CLI which outputs to stdout (no -o file flag)."""
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env_vars,
    )
    output_text = (completed.stdout or "").strip()
    return {
        "returncode": completed.returncode,
        "stdout": output_text,
        "stderr": (completed.stderr or "").strip(),
        "output_text": output_text,
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


def _execute_single_plan(
    *,
    plan: dict[str, Any],
    env: dict[str, str],
    system_prompt: str,
    user_prompt: str,
    timeout: int,
    run_cli: Callable[..., dict[str, Any]] | None,
    http_post: Callable[..., str] | None,
) -> dict[str, Any]:
    model_name = str(plan.get("model") or "").strip()
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
        cli_bin = str(plan.get("cli_bin") or "").strip()
        if not cli_bin:
            result = _structured_route_error("no_active_execution_route_configured", "no active execution route configured", plan=plan, failover_trace=failover_trace)
            _update_policy_failure(plan, detail=result["stderr"], failover_trace=failover_trace)
            return result
        is_claude_cli = os.path.basename(cli_bin) == "claude"
        if is_claude_cli:
            command = [cli_bin, "-p", prompt, "--output-format", "text"]
            if model_name:
                command.extend(["--model", model_name])
        else:
            command = [
                cli_bin,
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
        if not is_claude_cli:
            env_vars["HOME"] = str(plan.get("cli_home") or env_vars.get("HOME") or "").strip()
        cli_runner = run_cli or (_run_claude_cli_default if is_claude_cli else _run_cli_default)
        try:
            cli_result = cli_runner(command=command, env_vars=env_vars, timeout=timeout)
        except Exception as exc:
            detail = f"{exc.__class__.__name__}: {exc}"
            result = _structured_route_error("provider_transport_failed", detail, plan=plan, failover_trace=failover_trace)
            _update_policy_failure(plan, detail=detail, failover_trace=failover_trace)
            return result

        output_text = str(cli_result.get("output_text") or "").strip()
        returncode = int(cli_result.get("returncode") or 0)
        stderr = str(cli_result.get("stderr") or "").strip()
        stdout = str(cli_result.get("stdout") or "").strip()
        ok = returncode == 0 and bool(output_text)
        if returncode == 0 and not output_text:
            ok = False
            stderr = stderr or "CLI manager route returned empty output"

        result = {
            "ok": ok,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "output_text": output_text,
            "model": model_name,
            "provider_profile": profile_name,
            "transport_kind": "cli_session",
            "auth_mode": auth_mode,
            "failover_trace": failover_trace,
            "policy_source": str(plan.get("policy_source") or ""),
            "policy_route_id": str(plan.get("policy_route_id") or ""),
            "policy_auth_profile": str(plan.get("policy_auth_profile") or ""),
        }
        if ok:
            _update_policy_success(plan, failover_trace=failover_trace)
        else:
            _update_policy_failure(plan, detail=stderr or "brain router execution failed", failover_trace=failover_trace)
        return result

    endpoint = str(plan.get("endpoint") or "").strip()
    key_pool = list(plan.get("key_pool") or [])
    failover_status_codes = set(plan.get("failover_status_codes") or set())
    if not endpoint:
        result = _structured_route_error("no_active_execution_route_configured", "no active execution route configured", plan=plan, failover_trace=failover_trace)
        _update_policy_failure(plan, detail=result["stderr"], failover_trace=failover_trace)
        return result
    if not key_pool:
        result = _structured_route_error("all_routes_disabled_by_billing_or_cooldown", "all routes disabled by billing/auth/cooldown", plan=plan, failover_trace=failover_trace)
        _update_policy_failure(plan, detail=result["stderr"], failover_trace=failover_trace)
        return result

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
            result = _structured_route_error("provider_http_error", f"HTTP {exc.code}: {detail[:300]}", plan=plan, failover_trace=failover_trace)
            result.update({"key_slot": index, "warnings": warnings})
            _update_policy_failure(plan, detail=result["stderr"], failover_trace=failover_trace)
            return result
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
            result = _structured_route_error("provider_transport_failed", detail[:300], plan=plan, failover_trace=failover_trace)
            result.update({"key_slot": index, "warnings": warnings})
            _update_policy_failure(plan, detail=result["stderr"], failover_trace=failover_trace)
            return result

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
            result = {
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
                "policy_source": str(plan.get("policy_source") or ""),
                "policy_route_id": str(plan.get("policy_route_id") or ""),
                "policy_auth_profile": str(plan.get("policy_auth_profile") or ""),
            }
            _update_policy_success(plan, failover_trace=failover_trace)
            return result

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

        result = _structured_route_error("provider_empty_payload", f"empty output: {detail[:300]}", plan=plan, failover_trace=failover_trace)
        result.update({"key_slot": index, "warnings": warnings})
        _update_policy_failure(plan, detail=result["stderr"], failover_trace=failover_trace)
        return result

    result = _structured_route_error("all_routes_disabled_by_billing_or_cooldown", "all routes disabled by billing/auth/cooldown", plan=plan, failover_trace=failover_trace)
    result.update({"warnings": warnings})
    _update_policy_failure(plan, detail=result["stderr"], failover_trace=failover_trace)
    return result


def _append_route_failover_trace(
    route_trace: list[dict[str, Any]],
    *,
    from_plan: dict[str, Any],
    to_plan: dict[str, Any],
    reason: str,
) -> None:
    route_trace.append(
        {
            "route_failover": True,
            "from_route_id": str(from_plan.get("policy_route_id") or ""),
            "to_route_id": str(to_plan.get("policy_route_id") or ""),
            "from_provider_profile": str(from_plan.get("profile_name") or ""),
            "to_provider_profile": str(to_plan.get("profile_name") or ""),
            "reason_class": institution_brain_policy.classify_reason(reason),
            "reason_detail": str(reason or "")[:200],
        }
    )


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

    try:
        initial_plan = _resolve_manager_plan_with_source(runtime_env=env, model_hint=model)
    except RoutePolicyError as exc:
        return exc.as_result()

    cached_policy = None
    if str(initial_plan.get("policy_source") or "") == "institution_policy":
        org_id = str(initial_plan.get("policy_org_id") or env.get("MERIDIAN_WORKSPACE_ORG_ID") or env.get("MERIDIAN_ORG_ID") or "").strip()
        if org_id:
            cached_policy = institution_brain_policy.load_policy(org_id)
    route_chain = _route_chain_from_policy(initial_plan, _cached_policy=cached_policy)
    route_failover_trace: list[dict[str, Any]] = []
    for index, plan in enumerate(route_chain):
        result = _execute_single_plan(
            plan=plan,
            env=env,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout=timeout,
            run_cli=run_cli,
            http_post=http_post,
        )
        result["failover_trace"] = list(route_failover_trace) + list(result.get("failover_trace") or [])
        if result.get("ok"):
            result["route_decision"] = {
                "selected_index": index,
                "chain_length": len(route_chain),
                "skipped_routes": list(plan.get("_skipped_routes") or []),
                "route_id": str(plan.get("policy_route_id") or ""),
                "provider_profile": str(plan.get("profile_name") or ""),
            }
            return result

        if str(plan.get("policy_source") or "") == "institution_policy" and index + 1 < len(route_chain):
            reason = str(result.get("stderr") or result.get("error_code") or "execution failed")
            _append_route_failover_trace(
                route_failover_trace,
                from_plan=plan,
                to_plan=route_chain[index + 1],
                reason=reason,
            )
            continue
        return result

    return _structured_route_error(
        "all_routes_disabled_by_billing_or_cooldown",
        "all routes disabled by billing/auth/cooldown",
        plan=initial_plan,
        failover_trace=route_failover_trace,
    )


def manager_exec_metadata(*, runtime_env: dict[str, str] | None = None, model_hint: str = "") -> dict[str, str]:
    plan = _resolve_manager_plan_with_source(runtime_env=runtime_env, model_hint=model_hint)
    return {
        "provider_profile": str(plan.get("profile_name") or DEFAULT_MANAGER_PROFILE).strip() or DEFAULT_MANAGER_PROFILE,
        "model": str(plan.get("model") or model_hint or "").strip(),
        "transport_kind": str(plan.get("transport_kind") or DEFAULT_MANAGER_TRANSPORT).strip() or DEFAULT_MANAGER_TRANSPORT,
        "auth_mode": str(plan.get("auth_mode") or "none").strip() or "none",
        "source": str(plan.get("policy_source") or ""),
        "route_id": str(plan.get("policy_route_id") or ""),
        "auth_profile": str(plan.get("policy_auth_profile") or ""),
    }


def manager_policy_status(*, runtime_env: dict[str, str] | None = None, model_hint: str = "") -> dict[str, Any]:
    env = dict(os.environ)
    if runtime_env:
        env.update(runtime_env)
    org_id = str(env.get("MERIDIAN_WORKSPACE_ORG_ID") or env.get("MERIDIAN_ORG_ID") or "").strip()
    base = (
        institution_brain_policy.policy_status(org_id, runtime_env=env)
        if org_id
        else {
            "configured": False,
            "source": "override",
            "status": "blocked",
            "reason": "no_active_execution_route_configured",
            "active_route": None,
            "fallback_chain": [],
            "auth_profiles": {},
            "failover_policy": {},
        }
    )
    try:
        plan = _resolve_manager_plan_with_source(runtime_env=env, model_hint=model_hint)
    except RoutePolicyError as exc:
        base["status"] = "blocked"
        base["reason"] = exc.code
        base["detail"] = exc.message
        return base

    base["selected_plan"] = {
        "provider_profile": str(plan.get("profile_name") or DEFAULT_MANAGER_PROFILE).strip() or DEFAULT_MANAGER_PROFILE,
        "provider_ref": str(plan.get("policy_provider_ref") or "").strip(),
        "provider_entry": dict(plan.get("policy_provider_entry") or {}),
        "model": str(plan.get("model") or model_hint or "").strip(),
        "model_ref": str(plan.get("policy_model_ref") or "").strip(),
        "model_entry": dict(plan.get("policy_model_entry") or {}),
        "transport_kind": str(plan.get("transport_kind") or DEFAULT_MANAGER_TRANSPORT).strip() or DEFAULT_MANAGER_TRANSPORT,
        "auth_mode": str(plan.get("auth_mode") or "none").strip() or "none",
        "source": str(plan.get("policy_source") or base.get("source") or ""),
        "route_id": str(plan.get("policy_route_id") or ""),
        "auth_profile": str(plan.get("policy_auth_profile") or ""),
        "budget_band": str(plan.get("policy_budget_band") or ""),
    }
    return base


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
