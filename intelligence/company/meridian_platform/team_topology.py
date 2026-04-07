#!/usr/bin/env python3
"""Canonical Meridian team topology and live Loom provider sync."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PLATFORM_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = PLATFORM_DIR.parent.parent
MERIDIAN_HOME = WORKSPACE_DIR.parent
REGISTRY_PATH = PLATFORM_DIR / "agent_registry.json"
DEFAULT_ENV_FILES = (
    MERIDIAN_HOME / ".env",
    MERIDIAN_HOME / ".env.gateway",
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
DEFAULT_CODEX_AUTH_PATH = Path(
    os.environ.get(
        "MERIDIAN_CODEX_AUTH_PATH",
        str(DEFAULT_CODEX_HOME / ".codex" / "auth.json"),
    )
)


SPECIALIST_KEYS = ("ATLAS", "SENTINEL", "FORGE", "QUILL", "AEGIS", "PULSE")
SPECIALIST_PROFILE_NAMES = {
    "ATLAS": "atlas_specialist",
    "SENTINEL": "sentinel_specialist",
    "FORGE": "forge_specialist",
    "QUILL": "quill_specialist",
    "AEGIS": "aegis_specialist",
    "PULSE": "pulse_specialist",
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
        return "cli_session"
    if value in {"custom_endpoint", "custom-endpoint", "custom"}:
        return "http_json"
    if value in {"do-openai-compatible", "openai_compatible", "openai-compatible", "openai"}:
        return "http_json"
    if value in {"http_json", "http-json", "http"}:
        return "http_json"
    if value in {"local_ollama", "ollama"}:
        return "local_http_json"
    return "http_json"


def _make_agent(
    registry: dict[str, Any],
    *,
    env_key: str,
    name: str,
    profile_name: str,
    provider_kind: str,
    base_url: str,
    api_key_env_var: str,
    model: str,
    task_kind: str,
    manager_visible: bool,
) -> TeamAgent:
    registry_id, record = _registry_agent_with_fallback(
        registry,
        env_key=env_key,
        requested_name=name,
    )
    if not registry_id or not record:
        raise RuntimeError(f"team topology missing registry record for {name}")
    return TeamAgent(
        env_key=env_key,
        registry_id=registry_id,
        handle=str(record.get("economy_key") or _normalize_handle(name)).strip() or _normalize_handle(name),
        name=name,
        role=str(record.get("role") or "").strip(),
        purpose=str(record.get("purpose") or "").strip(),
        profile_name=profile_name,
        provider_kind=provider_kind,
        base_url=(base_url or "").strip(),
        api_key_env_var=api_key_env_var,
        model=(model or "").strip(),
        task_kind=task_kind,
        manager_visible=manager_visible,
    )


def load_team_topology(
    env: dict[str, str] | None = None,
    *,
    env_files: tuple[Path, ...] = DEFAULT_ENV_FILES,
) -> TeamTopology:
    runtime_env = load_runtime_env(env, env_files=env_files)
    registry = _load_registry()
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
        manager_transport = "http_json" if legacy_provider in {"xai", "grok", "xai_pool", "grok_pool"} else "cli_session"
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
        profile_name=manager_profile_name,
        provider_kind=manager_transport,
        base_url=manager_base_url,
        api_key_env_var=manager_api_key_env_var,
        model=manager_model,
        task_kind="manage",
        manager_visible=True,
    )
    specialists: list[TeamAgent] = []
    for key in SPECIALIST_KEYS:
        name = (runtime_env.get(f"MERIDIAN_AGENT_{key}_NAME") or key.title()).strip() or key.title()
        specialists.append(
            _make_agent(
                registry,
                env_key=key,
                name=name,
                profile_name=SPECIALIST_PROFILE_NAMES[key],
                provider_kind=_provider_kind_for_env(runtime_env.get(f"MERIDIAN_AGENT_{key}_PROVIDER", "")),
                base_url=runtime_env.get(f"MERIDIAN_AGENT_{key}_BASE_URL", ""),
                api_key_env_var=f"MERIDIAN_AGENT_{key}_API_KEY",
                model=runtime_env.get(f"MERIDIAN_AGENT_{key}_MODEL", ""),
                task_kind=SPECIALIST_TASK_DEFAULTS[key],
                manager_visible=False,
            )
        )
    return TeamTopology(org_id=org_id, manager=manager, specialists=tuple(specialists))


def default_imported_history_dir(loom_root: str | Path | None = None) -> Path:
    root = Path(loom_root) if loom_root else DEFAULT_LOOM_ROOT
    return root / "state" / "session-history" / "imported"


def _profile_json_for_agent(agent: TeamAgent) -> dict[str, Any]:
    base_url = (agent.base_url or "").strip()
    if agent.provider_kind in {"http_json", "openai_compatible", "custom_endpoint"}:
        if base_url.endswith("/api/v1") or base_url.endswith("/v1"):
            base_url = f"{base_url.rstrip('/')}/chat/completions"
    if agent.provider_kind in {"cli_session", "openai_codex"}:
        auth = {"mode": "codex_auth_json", "path": str(DEFAULT_CODEX_AUTH_PATH)}
        base_url = base_url or "cli://session"
    elif agent.provider_kind in {"local_http_json", "local_ollama"}:
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
        "kind": agent.provider_kind,
        "base_url": base_url,
        "model": agent.model,
        "auth": auth,
        "note": f"Meridian team route for {agent.name} ({agent.role})",
    }


def sync_loom_team_profiles(
    topology: TeamTopology,
    *,
    loom_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(loom_root) if loom_root else DEFAULT_LOOM_ROOT
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
        existing_profiles[team_agent.profile_name] = _profile_json_for_agent(team_agent)
        agent_route = {"profile": team_agent.profile_name, "default_model": team_agent.model}
        agent_routes[team_agent.registry_id] = dict(agent_route)
        agent_routes[team_agent.handle] = dict(agent_route)

    if "loom.llm.inference.v1" not in capability_routes:
        capability_routes["loom.llm.inference.v1"] = {
            "profile": "local_ollama",
            "default_model": "qwen2.5:7b",
        }

    payload["profiles"] = list(existing_profiles.values())
    profiles_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {
        "profiles_path": str(profiles_path),
        "profile_names": sorted(existing_profiles.keys()),
        "agent_routes": sorted(agent_routes.keys()),
    }
