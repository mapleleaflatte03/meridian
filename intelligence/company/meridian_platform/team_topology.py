#!/usr/bin/env python3
"""Canonical Meridian team topology and live Loom provider sync."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PLATFORM_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = PLATFORM_DIR.parent.parent
MERIDIAN_HOME = WORKSPACE_DIR.parent
REGISTRY_PATH = PLATFORM_DIR / "agent_registry.json"
TEAM_PRESETS_PATH = PLATFORM_DIR / "config" / "team_presets.json"
LOCAL_RUNTIME_ENV_FILE = Path.home() / ".meridian" / ".env"
LOCAL_RUNTIME_GATEWAY_ENV_FILE = Path.home() / ".meridian" / ".env.gateway"
LOCAL_TEAM_CONFIG_FILE = Path.home() / ".meridian" / "team.json"
DEFAULT_ENV_FILES = (
    MERIDIAN_HOME / ".env",
    MERIDIAN_HOME / ".env.gateway",
    LOCAL_RUNTIME_ENV_FILE,
    LOCAL_RUNTIME_GATEWAY_ENV_FILE,
)
DEFAULT_LOOM_ROOT = Path(
    os.environ.get(
        "MERIDIAN_LOOM_ROOT",
        "/home/ubuntu/.local/share/meridian-loom/runtime/default",
    )
)
DEFAULT_CODEX_HOME = Path(
    os.environ.get(
        "MERIDIAN_CODEX_HOME",
        str(MERIDIAN_HOME / "auth" / "codex" / "login-home"),
    )
)
DEFAULT_LOOM_CODEX_AUTH_PATH = Path(".meridian/auth/codex/login-home/.codex/auth.json")
DEFAULT_SHARED_CODEX_AUTH_PATH = Path(".codex/auth.json")
DEFAULT_CODEX_BASE_URL = "https://chatgpt.com/backend-api"
DEFAULT_TEAM_PRESET = "dev_team"


def _candidate_codex_auth_paths(runtime_env: dict[str, str] | None = None) -> tuple[Path, ...]:
    env = runtime_env or {}
    explicit_auth = str(env.get("MERIDIAN_CODEX_AUTH_PATH") or os.environ.get("MERIDIAN_CODEX_AUTH_PATH") or "").strip()
    explicit_home = str(env.get("MERIDIAN_CODEX_HOME") or os.environ.get("MERIDIAN_CODEX_HOME") or "").strip()
    home_dir = Path.home()
    candidates: list[Path] = []
    if explicit_auth:
        candidates.append(Path(explicit_auth))
    if explicit_home:
        candidates.append(Path(explicit_home) / ".codex" / "auth.json")
    candidates.extend(
        [
            home_dir / ".meridian" / "auth" / "codex" / "login-home" / ".codex" / "auth.json",
            MERIDIAN_HOME / "auth" / "codex" / "login-home" / ".codex" / "auth.json",
            home_dir / ".codex" / "auth.json",
            DEFAULT_CODEX_HOME / ".codex" / "auth.json",
        ]
    )
    ordered: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        rendered = str(candidate)
        if rendered in seen:
            continue
        seen.add(rendered)
        ordered.append(candidate)
    return tuple(ordered)


def _codex_auth_path_rank(path: Path) -> int:
    rendered = str(path)
    try:
        normalized = path.expanduser().resolve(strict=False)
    except Exception:
        normalized = path
    normalized_text = str(normalized)
    markers = (
        (str(DEFAULT_LOOM_CODEX_AUTH_PATH), 0),
        (str(DEFAULT_SHARED_CODEX_AUTH_PATH), 1),
        (str(MERIDIAN_HOME / "auth" / "codex" / "login-home" / ".codex" / "auth.json"), 0),
        (str(Path.home() / ".meridian" / "auth" / "codex" / "login-home" / ".codex" / "auth.json"), 0),
        (str(Path.home() / ".codex" / "auth.json"), 1),
        (str(DEFAULT_CODEX_HOME / ".codex" / "auth.json"), 1),
    )
    for marker, rank in markers:
        if rendered.endswith(marker) or normalized_text.endswith(marker):
            return rank
    return 2


def _looks_like_valid_codex_auth(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        return False
    access_token = str(tokens.get("access_token") or "").strip()
    return bool(access_token)


def _resolve_codex_auth_path(runtime_env: dict[str, str] | None = None) -> Path:
    candidates = _candidate_codex_auth_paths(runtime_env)
    valid_existing = [
        candidate for candidate in candidates if candidate.exists() and _looks_like_valid_codex_auth(candidate)
    ]
    if valid_existing:
        return max(
            valid_existing,
            key=lambda candidate: (
                -_codex_auth_path_rank(candidate),
                candidate.stat().st_mtime,
            ),
        )
    existing = [candidate for candidate in candidates if candidate.exists()]
    if existing:
        return max(existing, key=lambda candidate: candidate.stat().st_mtime)
    return candidates[0]


SPECIALIST_KEYS = ("ATLAS", "SENTINEL", "FORGE", "QUILL", "AEGIS", "PULSE")
SPECIALIST_PROFILE_NAMES = {
    "ATLAS": "research_frontier",
    "SENTINEL": "verifier_frontier",
    "FORGE": "executor_tooling",
    "QUILL": "writer_general",
    "AEGIS": "qa_frontier",
    "PULSE": "local_ollama",
}
SPECIALIST_TASK_DEFAULTS = {
    "ATLAS": "research",
    "SENTINEL": "verify",
    "FORGE": "execute",
    "QUILL": "write",
    "AEGIS": "qa_gate",
    "PULSE": "compress",
}


@dataclass(frozen=True)
class TeamAgent:
    env_key: str
    registry_id: str
    handle: str
    name: str
    role: str
    purpose: str
    profile_name: str
    provider_kind: str
    base_url: str
    api_key_env_var: str
    model: str
    task_kind: str
    kernel_role: str
    scopes: tuple[str, ...]
    budget: dict[str, float]
    aliases: tuple[str, ...]
    dispatchable: bool = True
    manager_visible: bool = False


@dataclass(frozen=True)
class TeamTopology:
    org_id: str
    manager: TeamAgent
    specialists: tuple[TeamAgent, ...]

    def specialist_by_id(self, agent_id: str) -> TeamAgent | None:
        target = (agent_id or "").strip().lower()
        for agent in self.specialists:
            if target in {agent.registry_id.lower(), agent.handle.lower(), agent.name.lower()}:
                return agent
        return None


def _load_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {"agents": {}}
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _load_team_presets() -> dict[str, Any]:
    if not TEAM_PRESETS_PATH.exists():
        return {"schema_version": 1, "default_preset": DEFAULT_TEAM_PRESET, "presets": {}}
    try:
        payload = json.loads(TEAM_PRESETS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": 1, "default_preset": DEFAULT_TEAM_PRESET, "presets": {}}
    if not isinstance(payload, dict):
        return {"schema_version": 1, "default_preset": DEFAULT_TEAM_PRESET, "presets": {}}
    return payload


def _load_local_team_config(runtime_env: dict[str, str]) -> dict[str, Any]:
    explicit_path = str(runtime_env.get("MERIDIAN_TEAM_CONFIG_PATH") or "").strip()
    path = Path(explicit_path) if explicit_path else LOCAL_TEAM_CONFIG_FILE
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _string_map(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def _coerce_aliases(values: Any) -> tuple[str, ...]:
    aliases: list[str] = []
    for raw in values or []:
        value = str(raw or "").strip()
        if value and value not in aliases:
            aliases.append(value)
    return tuple(aliases)


def _coerce_scopes(values: Any) -> tuple[str, ...]:
    scopes: list[str] = []
    for raw in values or []:
        value = str(raw or "").strip()
        if value and value not in scopes:
            scopes.append(value)
    return tuple(scopes)


def _coerce_budget(values: Any) -> dict[str, float]:
    payload = _string_map(values)
    normalized: dict[str, float] = {}
    for key in ("max_per_run_usd", "max_per_day_usd", "max_per_month_usd"):
        try:
            normalized[key] = float(payload.get(key))
        except (TypeError, ValueError):
            continue
    return normalized


def _team_role_payload(
    preset_payload: dict[str, Any],
    override_payload: dict[str, Any],
    *,
    env_key: str,
    manager_visible: bool,
) -> dict[str, Any]:
    merged = dict(_string_map(preset_payload))
    merged.update(_string_map(override_payload))
    aliases = list(_coerce_aliases(preset_payload.get("aliases")))
    for item in _coerce_aliases(override_payload.get("aliases")):
        if item not in aliases:
            aliases.append(item)
    merged["aliases"] = tuple(aliases)
    merged["scopes"] = _coerce_scopes(merged.get("scopes"))
    merged["budget"] = _coerce_budget(merged.get("budget"))
    merged["dispatchable"] = bool(merged.get("dispatchable", not manager_visible))
    merged["manager_visible"] = manager_visible
    merged["env_key"] = env_key
    return merged


def _resolve_team_semantics(runtime_env: dict[str, str]) -> dict[str, Any]:
    catalog = _load_team_presets()
    presets = _string_map(catalog.get("presets"))
    local_config = _load_local_team_config(runtime_env)
    preset_name = (
        str(runtime_env.get("MERIDIAN_TEAM_PRESET") or "").strip()
        or str(local_config.get("preset") or "").strip()
        or str(catalog.get("default_preset") or DEFAULT_TEAM_PRESET).strip()
        or DEFAULT_TEAM_PRESET
    )
    preset = _string_map(presets.get(preset_name))
    if not preset:
        preset_name = str(catalog.get("default_preset") or DEFAULT_TEAM_PRESET).strip() or DEFAULT_TEAM_PRESET
        preset = _string_map(presets.get(preset_name))
    fallback = _string_map(presets.get("generic_team"))
    manager_defaults = _team_role_payload(
        _string_map(_string_map(fallback).get("manager")),
        _string_map(_string_map(preset).get("manager")),
        env_key="MANAGER",
        manager_visible=True,
    )
    manager_overrides = _team_role_payload(
        manager_defaults,
        _string_map(local_config.get("manager")),
        env_key="MANAGER",
        manager_visible=True,
    )
    specialist_defaults = _string_map(_string_map(fallback).get("specialists"))
    preset_specialists = _string_map(_string_map(preset).get("specialists"))
    local_specialists = _string_map(local_config.get("specialists"))
    specialists: dict[str, dict[str, Any]] = {}
    for key in SPECIALIST_KEYS:
        specialist_base = _team_role_payload(
            _string_map(specialist_defaults.get(key)),
            _string_map(preset_specialists.get(key)),
            env_key=key,
            manager_visible=False,
        )
        specialists[key] = _team_role_payload(
            specialist_base,
            _string_map(local_specialists.get(key)),
            env_key=key,
            manager_visible=False,
        )
    return {
        "preset": preset_name,
        "manager": manager_overrides,
        "specialists": specialists,
        "config_path": str(
            Path(str(runtime_env.get("MERIDIAN_TEAM_CONFIG_PATH") or "").strip())
            if str(runtime_env.get("MERIDIAN_TEAM_CONFIG_PATH") or "").strip()
            else LOCAL_TEAM_CONFIG_FILE
        ),
    }


def _parse_env_file(path: Path) -> dict[str, str]:
    payload: dict[str, str] = {}
    if not path.exists():
        return payload
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        payload[key] = value
    return payload


def load_runtime_env(
    env: dict[str, str] | None = None,
    *,
    env_files: tuple[Path, ...] = DEFAULT_ENV_FILES,
) -> dict[str, str]:
    runtime_env: dict[str, str] = {}
    for path in env_files:
        runtime_env.update(_parse_env_file(path))
    runtime_env.update(os.environ)
    if env:
        runtime_env.update(env)
    return runtime_env


def _normalize_handle(value: str) -> str:
    return (value or "").strip().lower().replace(" ", "_")


def _registry_agent_by_name(registry: dict[str, Any], name: str) -> tuple[str, dict[str, Any]] | tuple[str, None]:
    target = (name or "").strip().lower()
    for agent_id, record in (registry.get("agents") or {}).items():
        if (str(record.get("name") or "").strip().lower()) == target:
            return agent_id, dict(record)
    return "", None


def _registry_agent_entries(registry: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    entries: list[tuple[str, dict[str, Any]]] = []
    for agent_id, raw in (registry.get("agents") or {}).items():
        if isinstance(raw, dict):
            entries.append((str(agent_id), dict(raw)))
    return entries


def _registry_agent_with_fallback(
    registry: dict[str, Any],
    *,
    env_key: str,
    requested_name: str,
) -> tuple[str, dict[str, Any]] | tuple[str, None]:
    direct_id, direct_record = _registry_agent_by_name(registry, requested_name)
    if direct_id and direct_record:
        return direct_id, direct_record

    requested_token = _normalize_handle(requested_name)
    for agent_id, record in _registry_agent_entries(registry):
        record_name = _normalize_handle(str(record.get("name") or ""))
        record_id = _normalize_handle(agent_id.replace("agent_", ""))
        economy_key = _normalize_handle(str(record.get("economy_key") or ""))
        if requested_token and requested_token in {record_name, record_id, economy_key}:
            return agent_id, record

    if env_key == "MANAGER":
        for preferred_id in ("agent_manager", "manager"):
            for agent_id, record in _registry_agent_entries(registry):
                if agent_id == preferred_id:
                    return agent_id, record
        for agent_id, record in _registry_agent_entries(registry):
            role = str(record.get("role") or "").strip().lower()
            if role in {"manager", "orchestrator"}:
                return agent_id, record

    if env_key in SPECIALIST_KEYS:
        expected_id = f"agent_{env_key.lower()}"
        for agent_id, record in _registry_agent_entries(registry):
            if agent_id == expected_id:
                return agent_id, record
        expected_handle = env_key.lower()
        for agent_id, record in _registry_agent_entries(registry):
            economy_key = _normalize_handle(str(record.get("economy_key") or ""))
            if economy_key == expected_handle:
                return agent_id, record

    return "", None


def _provider_kind_for_env(raw: str) -> str:
    value = (raw or "").strip().lower()
    if value in {"cli_session", "openai_codex", "openai-codex", "codex"}:
        return "openai_codex"
    if value in {"custom_endpoint", "custom-endpoint", "custom"}:
        return "custom_endpoint"
    if value in {"do-openai-compatible", "openai_compatible", "openai-compatible", "openai"}:
        return "openai_compatible"
    if value in {"http_json", "http-json", "http"}:
        return "openai_compatible"
    if value in {"local_ollama", "ollama"}:
        return "local_ollama"
    return ""


def _default_provider_kind_for_profile(profile_name: str) -> str:
    value = (profile_name or "").strip()
    if value in {
        "manager_frontier",
        "research_frontier",
        "writer_general",
        "qa_frontier",
        "verifier_frontier",
        "executor_tooling",
    }:
        return "openai_codex"
    if value == "local_ollama":
        return "local_ollama"
    return "openai_compatible"


def _make_agent(
    registry: dict[str, Any],
    *,
    env_key: str,
    name: str,
    role: str,
    purpose: str,
    profile_name: str,
    provider_kind: str,
    base_url: str,
    api_key_env_var: str,
    model: str,
    task_kind: str,
    kernel_role: str,
    scopes: tuple[str, ...],
    budget: dict[str, float],
    aliases: tuple[str, ...],
    dispatchable: bool,
    manager_visible: bool,
) -> TeamAgent:
    registry_id, record = _registry_agent_with_fallback(
        registry,
        env_key=env_key,
        requested_name=name,
    )
    if not registry_id or not record:
        registry_id = f"agent_{_normalize_handle(name)}"
        record = {
            "name": name,
            "role": role,
            "purpose": purpose or f"{name} ({env_key})",
            "economy_key": _normalize_handle(name),
        }
    return TeamAgent(
        env_key=env_key,
        registry_id=registry_id,
        handle=str(record.get("economy_key") or _normalize_handle(name)).strip() or _normalize_handle(name),
        name=name,
        role=role.strip(),
        purpose=purpose.strip(),
        profile_name=profile_name,
        provider_kind=provider_kind,
        base_url=(base_url or "").strip(),
        api_key_env_var=api_key_env_var,
        model=(model or "").strip(),
        task_kind=task_kind,
        kernel_role=kernel_role.strip(),
        scopes=scopes,
        budget=budget,
        aliases=aliases,
        dispatchable=dispatchable,
        manager_visible=manager_visible,
    )


def load_team_topology(
    env: dict[str, str] | None = None,
    *,
    env_files: tuple[Path, ...] = DEFAULT_ENV_FILES,
) -> TeamTopology:
    runtime_env = load_runtime_env(env, env_files=env_files)
    registry = _load_registry()
    semantics = _resolve_team_semantics(runtime_env)
    manager_name = (runtime_env.get("MERIDIAN_MANAGER_AGENT_NAME") or "Leviathann").strip() or "Leviathann"
    org_id = (runtime_env.get("MERIDIAN_LOOM_ORG_ID") or runtime_env.get("MERIDIAN_WORKSPACE_ORG_ID") or "org_48b05c21").strip()
    manager_profile_name = (
        (runtime_env.get("MERIDIAN_BRAIN_MANAGER_PROFILE_NAME") or "").strip()
        or "manager_primary"
    )
    manager_transport = (
        (runtime_env.get("MERIDIAN_BRAIN_MANAGER_TRANSPORT") or "").strip().lower()
    )
    if not manager_transport:
        legacy_provider = (runtime_env.get("MERIDIAN_MANAGER_PROVIDER") or "").strip().lower()
        manager_transport = "openai_compatible" if legacy_provider in {"xai", "grok", "xai_pool", "grok_pool"} else "openai_codex"
    manager_base_url = (
        (runtime_env.get("MERIDIAN_BRAIN_MANAGER_ENDPOINT") or "").strip()
        or (runtime_env.get("MERIDIAN_MANAGER_XAI_BASE_URL") or "").strip()
    )
    manager_model = (
        (runtime_env.get("MERIDIAN_BRAIN_MANAGER_MODEL") or "").strip()
        or (runtime_env.get("MERIDIAN_MANAGER_MODEL") or "").strip()
    )
    manager_api_key_env_var = (runtime_env.get("MERIDIAN_BRAIN_MANAGER_AUTH_ENV") or "").strip()
    manager = _make_agent(
        registry,
        env_key="MANAGER",
        name=manager_name,
        role=str(semantics["manager"].get("role") or "manager"),
        purpose=str(semantics["manager"].get("purpose") or "Manager and orchestrator."),
        profile_name=manager_profile_name,
        provider_kind=manager_transport,
        base_url=manager_base_url,
        api_key_env_var=manager_api_key_env_var,
        model=manager_model,
        task_kind=str(semantics["manager"].get("task_kind") or "manage"),
        kernel_role=str(semantics["manager"].get("kernel_role") or "manager"),
        scopes=tuple(semantics["manager"].get("scopes") or ()),
        budget=dict(semantics["manager"].get("budget") or {}),
        aliases=tuple(semantics["manager"].get("aliases") or ()),
        dispatchable=bool(semantics["manager"].get("dispatchable", False)),
        manager_visible=bool(semantics["manager"].get("manager_visible", True)),
    )
    specialists: list[TeamAgent] = []
    for key in SPECIALIST_KEYS:
        name = (runtime_env.get(f"MERIDIAN_AGENT_{key}_NAME") or key.title()).strip() or key.title()
        profile_name = (
            (runtime_env.get(f"MERIDIAN_AGENT_{key}_PROFILE_NAME") or "").strip()
            or SPECIALIST_PROFILE_NAMES[key]
        )
        provider_kind = _provider_kind_for_env(runtime_env.get(f"MERIDIAN_AGENT_{key}_PROVIDER", ""))
        if not provider_kind:
            provider_kind = _default_provider_kind_for_profile(profile_name)
        agent_semantics = dict((semantics.get("specialists") or {}).get(key) or {})
        specialists.append(
            _make_agent(
                registry,
                env_key=key,
                name=name,
                role=str(agent_semantics.get("role") or key.lower()),
                purpose=str(agent_semantics.get("purpose") or f"{name} specialist."),
                profile_name=profile_name,
                provider_kind=provider_kind,
                base_url=runtime_env.get(f"MERIDIAN_AGENT_{key}_BASE_URL", ""),
                api_key_env_var=f"MERIDIAN_AGENT_{key}_API_KEY",
                model=runtime_env.get(f"MERIDIAN_AGENT_{key}_MODEL", ""),
                task_kind=str(agent_semantics.get("task_kind") or SPECIALIST_TASK_DEFAULTS[key]),
                kernel_role=str(agent_semantics.get("kernel_role") or ""),
                scopes=tuple(agent_semantics.get("scopes") or ()),
                budget=dict(agent_semantics.get("budget") or {}),
                aliases=tuple(agent_semantics.get("aliases") or ()),
                dispatchable=bool(agent_semantics.get("dispatchable", True)),
                manager_visible=bool(agent_semantics.get("manager_visible", False)),
            )
        )
    return TeamTopology(org_id=org_id, manager=manager, specialists=tuple(specialists))


def default_imported_history_dir(loom_root: str | Path | None = None) -> Path:
    root = Path(loom_root) if loom_root else DEFAULT_LOOM_ROOT
    return root / "state" / "session-history" / "imported"


def _profile_json_for_agent(
    agent: TeamAgent,
    existing_profile: dict[str, Any] | None = None,
    *,
    runtime_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    existing = dict(existing_profile or {})
    provider_kind = (
        (agent.provider_kind or "").strip()
        or str(existing.get("kind") or "").strip()
        or _default_provider_kind_for_profile(agent.profile_name)
    )
    base_url = (agent.base_url or "").strip() or str(existing.get("base_url") or "").strip()
    model = (agent.model or "").strip() or str(existing.get("model") or "").strip()
    if provider_kind in {"openai_compatible", "custom_endpoint"}:
        if base_url.endswith("/api/v1") or base_url.endswith("/v1"):
            base_url = f"{base_url.rstrip('/')}/chat/completions"
    if provider_kind == "openai_codex":
        auth = {"mode": "codex_auth_json", "path": str(_resolve_codex_auth_path(runtime_env))}
        base_url = base_url or DEFAULT_CODEX_BASE_URL
    elif provider_kind == "local_ollama":
        auth = {"mode": "none"}
        base_url = base_url or "http://127.0.0.1:11434/v1/chat/completions"
    else:
        if agent.api_key_env_var:
            auth = {"mode": "bearer_env", "env_var": agent.api_key_env_var}
        else:
            auth = {"mode": "none"}
        base_url = base_url
    return {
        "name": agent.profile_name,
        "kind": provider_kind,
        "base_url": base_url,
        "model": model,
        "auth": auth,
        "note": f"Meridian team route for {agent.name} ({agent.role})",
    }


def _role_for_kernel_registry(agent: TeamAgent) -> str:
    explicit = (agent.kernel_role or "").strip().lower()
    if explicit:
        return explicit
    value = (agent.role or agent.task_kind or "").strip().lower()
    mapping = {
        "manage": "manager",
        "manager": "manager",
        "manager_tech_lead": "manager",
        "research": "analyst",
        "analyst": "analyst",
        "architect": "analyst",
        "verify": "verifier",
        "verifier": "verifier",
        "security_reviewer": "verifier",
        "execute": "executor",
        "executor": "executor",
        "backend_engineer": "executor",
        "frontend_engineer": "executor",
        "platform_engineer": "executor",
        "write": "writer",
        "writer": "writer",
        "qa_gate": "qa_gate",
        "qa_reliability_engineer": "qa_gate",
        "compress": "compressor",
        "compressor": "compressor",
    }
    return mapping.get(value, "analyst")


def _default_scopes_for_agent(agent: TeamAgent) -> list[str]:
    if agent.scopes:
        return list(agent.scopes)
    role = _role_for_kernel_registry(agent)
    if role == "manager":
        return ["manage", "read", "delegate"]
    if role == "analyst":
        return ["research", "read", "analyze"]
    if role == "verifier":
        return ["verify", "read", "audit"]
    if role == "executor":
        return ["execute", "write", "deploy"]
    if role == "writer":
        return ["write", "read", "draft"]
    if role == "qa_gate":
        return ["verify", "read", "qa"]
    if role == "compressor":
        return ["compress", "read", "summarize"]
    return ["read"]


def _default_budget_for_agent(agent: TeamAgent) -> dict[str, float]:
    if agent.budget:
        return dict(agent.budget)
    role = _role_for_kernel_registry(agent)
    if role == "manager":
        return {"max_per_run_usd": 1.0, "max_per_day_usd": 10.0, "max_per_month_usd": 200.0}
    if role == "verifier":
        return {"max_per_run_usd": 0.3, "max_per_day_usd": 3.0, "max_per_month_usd": 50.0}
    return {"max_per_run_usd": 0.5, "max_per_day_usd": 5.0, "max_per_month_usd": 100.0}


def _kernel_registry_path(loom_root: Path, runtime_env: dict[str, str]) -> Path:
    explicit = (runtime_env.get("MERIDIAN_KERNEL_AGENT_REGISTRY_PATH") or "").strip()
    if explicit:
        return Path(explicit)

    kernel_root = (runtime_env.get("MERIDIAN_KERNEL_ROOT") or "").strip()
    if not kernel_root:
        loom_toml = loom_root / "loom.toml"
        if loom_toml.exists():
            for raw_line in loom_toml.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line.startswith("kernel_path"):
                    continue
                _, value = line.split("=", 1)
                kernel_root = value.strip().strip('"').strip("'")
                if kernel_root:
                    break
    if not kernel_root:
        kernel_root = "/opt/meridian-kernel"

    kernel_root_path = Path(kernel_root)
    if kernel_root_path.name == "kernel":
        nested_kernel_dir = kernel_root_path / "kernel"
        if (nested_kernel_dir / "agent_registry.py").exists() or nested_kernel_dir.exists():
            return nested_kernel_dir / "agent_registry.json"
        return kernel_root_path / "agent_registry.json"
    return kernel_root_path / "kernel" / "agent_registry.json"


def _runtime_kernel_root(loom_root: Path, runtime_env: dict[str, str]) -> str:
    explicit = (runtime_env.get("MERIDIAN_KERNEL_ROOT") or "").strip()
    if explicit:
        return explicit
    loom_toml = loom_root / "loom.toml"
    if loom_toml.exists():
        for raw_line in loom_toml.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line.startswith("kernel_path"):
                continue
            _, value = line.split("=", 1)
            kernel_root = value.strip().strip('"').strip("'")
            if kernel_root:
                return kernel_root
    bundled_kernel_root = MERIDIAN_HOME / "kernel"
    if (bundled_kernel_root / "kernel" / "agent_registry.py").exists():
        return str(bundled_kernel_root)
    return "/opt/meridian-kernel"


def _sync_kernel_org_state(
    *,
    loom_root: Path,
    runtime_env: dict[str, str],
    org_id: str,
) -> dict[str, Any]:
    kernel_root = Path(_runtime_kernel_root(loom_root, runtime_env))
    kernel_platform_dir = kernel_root / "kernel"
    kernel_orgs_path = kernel_platform_dir / "organizations.json"
    platform_orgs_path = PLATFORM_DIR / "organizations.json"
    result = {
        "kernel_orgs_path": str(kernel_orgs_path),
        "kernel_org_status": "missing_platform_orgs",
        "kernel_capsule_path": str(kernel_root / "capsules" / org_id),
        "kernel_capsule_status": "skipped",
    }

    if not platform_orgs_path.exists():
        return result

    try:
        platform_payload = json.loads(platform_orgs_path.read_text(encoding="utf-8"))
    except Exception:
        result["kernel_org_status"] = "invalid_platform_orgs"
        return result

    platform_org = dict((platform_payload.get("organizations") or {}).get(org_id) or {})
    if not platform_org:
        result["kernel_org_status"] = "org_missing_from_platform"
        return result

    if kernel_orgs_path.exists():
        try:
            kernel_payload = json.loads(kernel_orgs_path.read_text(encoding="utf-8"))
        except Exception:
            kernel_payload = {"organizations": {}, "updatedAt": ""}
    else:
        kernel_payload = {"organizations": {}, "updatedAt": ""}

    kernel_orgs = kernel_payload.get("organizations")
    if not isinstance(kernel_orgs, dict):
        kernel_orgs = {}
    kernel_orgs[org_id] = platform_org
    kernel_payload["organizations"] = kernel_orgs
    kernel_payload["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    kernel_orgs_path.parent.mkdir(parents=True, exist_ok=True)
    kernel_orgs_path.write_text(json.dumps(kernel_payload, indent=2) + "\n", encoding="utf-8")
    result["kernel_org_status"] = "updated"

    capsule_dir = kernel_root / "capsules" / org_id
    ledger_path = capsule_dir / "ledger.json"
    if ledger_path.exists():
        result["kernel_capsule_status"] = "unchanged"
        return result

    capsule_dir.mkdir(parents=True, exist_ok=True)
    template_ledger_path = kernel_root / "economy" / "ledger.json"
    if template_ledger_path.exists():
        ledger_template = json.loads(template_ledger_path.read_text(encoding="utf-8"))
    else:
        ledger_template = {
            "version": 1,
            "schema": "meridian-kernel-economy-v1",
            "updatedAt": "",
            "agents": {},
            "treasury": {
                "cash_usd": 0.0,
                "reserve_floor_usd": 50.0,
                "total_revenue_usd": 0.0,
                "support_received_usd": 0.0,
                "owner_capital_contributed_usd": 0.0,
                "expenses_recorded_usd": 0.0,
                "owner_draws_usd": 0.0,
            },
            "bonus_pool": {"available_usd": 0.0},
            "epoch": {"number": 0, "started_at": "", "auth_decay_per_epoch": 5},
            "transactions": [],
        }

    bootstrap_script = (
        "import json, pathlib, sys\n"
        "kernel_dir = pathlib.Path(sys.argv[1])\n"
        "org_id = sys.argv[2]\n"
        "template = json.loads(sys.argv[3])\n"
        "sys.path.insert(0, str(kernel_dir))\n"
        "import capsule\n"
        "try:\n"
        "    capsule.init_capsule(org_id, ledger_template=template)\n"
        "    print('initialized')\n"
        "except FileExistsError:\n"
        "    print('exists')\n"
    )
    import subprocess

    completed = subprocess.run(
        [
            "python3",
            "-c",
            bootstrap_script,
            str(kernel_platform_dir),
            org_id,
            json.dumps(ledger_template),
        ],
        capture_output=True,
        text=True,
        cwd=str(kernel_root),
    )
    if completed.returncode == 0:
        result["kernel_capsule_status"] = (completed.stdout or "initialized").strip() or "initialized"
    else:
        result["kernel_capsule_status"] = f"init_failed:{(completed.stderr or completed.stdout).strip()[:120]}"
    return result


def _sync_runtime_loom_config(
    *,
    loom_root: Path,
    runtime_env: dict[str, str],
    org_id: str,
) -> dict[str, Any]:
    loom_toml = loom_root / "loom.toml"
    if not loom_toml.exists():
        return {
            "loom_toml_path": str(loom_toml),
            "loom_toml_status": "missing",
        }

    payload: list[str] = []
    updated_org = False
    updated_kernel = False
    kernel_root = _runtime_kernel_root(loom_root, runtime_env)
    for raw_line in loom_toml.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("org_id"):
            payload.append(f'org_id = "{org_id}"')
            updated_org = True
            continue
        if line.startswith("kernel_path"):
            payload.append(f'kernel_path = "{kernel_root}"')
            updated_kernel = True
            continue
        payload.append(raw_line)

    if not updated_org:
        payload.append(f'org_id = "{org_id}"')
    if not updated_kernel:
        payload.append(f'kernel_path = "{kernel_root}"')

    rendered = "\n".join(payload).rstrip() + "\n"
    status = "unchanged"
    if loom_toml.read_text(encoding="utf-8") != rendered:
        loom_toml.write_text(rendered, encoding="utf-8")
        status = "updated"
    return {
        "loom_toml_path": str(loom_toml),
        "loom_toml_status": status,
        "loom_kernel_path": kernel_root,
        "loom_org_id": org_id,
    }


def _sync_kernel_agent_registry(
    topology: TeamTopology,
    *,
    loom_root: Path,
    runtime_env: dict[str, str],
    org_id: str,
) -> dict[str, Any]:
    registry_path = _kernel_registry_path(loom_root, runtime_env)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    if registry_path.exists():
        try:
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {"agents": {}, "updatedAt": ""}
    else:
        payload = {"agents": {}, "updatedAt": ""}
    original_payload = json.loads(json.dumps(payload))
    agents = payload.get("agents")
    if not isinstance(agents, dict):
        agents = {}

    synced_ids: list[str] = []
    for team_agent in (topology.manager, *topology.specialists):
        existing = dict(agents.get(team_agent.registry_id) or {})
        role = _role_for_kernel_registry(team_agent)
        existing["id"] = team_agent.registry_id
        existing["org_id"] = org_id
        existing["name"] = team_agent.name
        existing["role"] = role
        existing["purpose"] = team_agent.purpose or f"{team_agent.name} ({team_agent.env_key})"
        existing["model_policy"] = existing.get("model_policy") or {
            "allowed_models": [],
            "max_context_tokens": 200000,
            "max_output_tokens": 16000,
        }
        existing["scopes"] = _default_scopes_for_agent(team_agent)
        existing["budget"] = _default_budget_for_agent(team_agent)
        existing["approval_required"] = bool(existing.get("approval_required", False))
        existing["rollout_state"] = str(existing.get("rollout_state") or "active")
        existing["runtime_binding"] = {
            "runtime_id": "loom_native",
            "runtime_label": "Meridian Loom Runtime",
            "runtime_registered": True,
            "registration_status": "registered",
            "bound_org_id": org_id,
            "context_source": "agent_registry",
            "boundary_name": "workspace",
            "identity_model": "session",
            "boundary_scope": "institution_bound",
        }
        existing["sla"] = existing.get("sla") or {
            "max_latency_seconds": 120,
            "availability_target": 0.95,
        }
        existing["reputation_units"] = int(existing.get("reputation_units") or 50)
        existing["authority_units"] = int(existing.get("authority_units") or 50)
        existing["status"] = str(existing.get("status") or "active")
        existing["created_at"] = str(existing.get("created_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        existing["last_active_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        existing["sponsor_id"] = existing.get("sponsor_id")
        existing["risk_state"] = str(existing.get("risk_state") or "nominal")
        existing["lifecycle_state"] = str(existing.get("lifecycle_state") or "active")
        existing["economy_key"] = team_agent.handle
        existing["incident_count"] = int(existing.get("incident_count") or 0)
        existing["escalation_path"] = list(existing.get("escalation_path") or [])
        agents[team_agent.registry_id] = existing
        synced_ids.append(team_agent.registry_id)

    payload["agents"] = agents
    payload["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    comparable_original = dict(original_payload)
    comparable_payload = dict(payload)
    comparable_original["updatedAt"] = ""
    comparable_payload["updatedAt"] = ""
    changed = comparable_original != comparable_payload
    write_status = "unchanged"
    if changed:
        try:
            registry_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            write_status = "updated"
        except OSError as exc:
            write_status = f"write_failed:{exc.errno}"
    return {
        "kernel_registry_path": str(registry_path),
        "kernel_registry_synced_agents": synced_ids,
        "kernel_registry_status": write_status,
    }


def sync_loom_team_profiles(
    topology: TeamTopology,
    *,
    loom_root: str | Path | None = None,
    org_id: str | None = None,
    runtime_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = Path(loom_root) if loom_root else DEFAULT_LOOM_ROOT
    resolved_runtime_env = dict(runtime_env or load_runtime_env())
    resolved_org_id = (org_id or topology.org_id or "org_48b05c21").strip() or "org_48b05c21"
    profiles_path = root / "providers" / "profiles.json"
    profiles_path.parent.mkdir(parents=True, exist_ok=True)
    if profiles_path.exists():
        payload = json.loads(profiles_path.read_text(encoding="utf-8"))
    else:
        payload = {"default_profile": "local_ollama", "profiles": [], "routing": {"agents": {}, "capabilities": {}}}

    existing_profiles = {
        str(item.get("name") or "").strip(): dict(item)
        for item in payload.get("profiles", [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    routing = payload.setdefault("routing", {})
    agent_routes = routing.setdefault("agents", {})
    capability_routes = routing.setdefault("capabilities", {})

    keep_profile_names = {"local_ollama", topology.manager.profile_name}
    keep_profile_names.update(agent.profile_name for agent in topology.specialists)

    # Preserve existing non-team profiles, but overwrite team-owned profiles.
    for team_agent in (topology.manager, *topology.specialists):
        existing_profiles[team_agent.profile_name] = _profile_json_for_agent(
            team_agent,
            existing_profiles.get(team_agent.profile_name),
            runtime_env=runtime_env,
        )
        route_model = (
            team_agent.model
            or str(existing_profiles[team_agent.profile_name].get("model") or "").strip()
        )
        agent_route = {"profile": team_agent.profile_name, "default_model": route_model}
        agent_routes[team_agent.registry_id] = dict(agent_route)
        agent_routes[team_agent.handle] = dict(agent_route)

    if "loom.llm.inference.v1" not in capability_routes:
        capability_routes["loom.llm.inference.v1"] = {
            "profile": "local_ollama",
            "default_model": "qwen2.5:7b",
        }

    payload["profiles"] = list(existing_profiles.values())
    profiles_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    runtime_config_sync = _sync_runtime_loom_config(
        loom_root=root,
        runtime_env=resolved_runtime_env,
        org_id=resolved_org_id,
    )
    kernel_org_sync = _sync_kernel_org_state(
        loom_root=root,
        runtime_env=resolved_runtime_env,
        org_id=resolved_org_id,
    )
    kernel_sync = _sync_kernel_agent_registry(
        topology,
        loom_root=root,
        runtime_env=resolved_runtime_env,
        org_id=resolved_org_id,
    )
    return {
        "profiles_path": str(profiles_path),
        "profile_names": sorted(existing_profiles.keys()),
        "agent_routes": sorted(agent_routes.keys()),
        **runtime_config_sync,
        **kernel_org_sync,
        **kernel_sync,
    }
