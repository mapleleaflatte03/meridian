#!/usr/bin/env python3
"""Unified Meridian gateway with Markdown memory, proactive heartbeat, and dynamic skills."""

from __future__ import annotations

import base64
import ast
import concurrent.futures
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse
from abc import ABC, abstractmethod
from html import unescape
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from meridian_config import load_config

HOST = "127.0.0.1"
PORT = 8266
WORKSPACE_DIR = Path(__file__).resolve().parent
COMPANY_DIR = WORKSPACE_DIR / "company"
PLATFORM_DIR = COMPANY_DIR / "meridian_platform"
for _path in (WORKSPACE_DIR, COMPANY_DIR, PLATFORM_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from company import mcp_server
from accounting import append_tx as accounting_append_tx, load_ledger as accounting_load_ledger, save_ledger as accounting_save_ledger
from audit import log_event
from capsule import ensure_treasury_aliases, ledger_path as capsule_ledger_path
from court import file_violation as court_file_violation, get_restrictions as court_get_restrictions
from warrants import (
    issue_warrant as warrants_issue_warrant,
    mark_warrant_executed as warrants_mark_warrant_executed,
    review_warrant as warrants_review_warrant,
    validate_warrant_for_execution as warrants_validate_warrant_for_execution,
)
from loom_runtime_client import estimate_capability_cost_usd, format_estimated_cost_usd
from loom_runtime_discovery import preferred_loom_bin, preferred_loom_root, runtime_value
from session_history import append_session_event, load_session_events
from team_topology import SPECIALIST_KEYS, load_team_topology, sync_loom_team_profiles
from telegram_history import imported_history_context
import brain_router

KERNEL_DIR = Path("/opt/meridian-kernel/kernel")
_KERNEL_IMPORT_CONFLICTS = (
    "agent_registry",
    "capsule",
    "organizations",
    "runtime_adapter",
)


def _call_isolated_kernel_treasury(method_name: str, *args: Any, **kwargs: Any) -> Any:
    kernel_dir = str(KERNEL_DIR)
    original_sys_path = list(sys.path)
    saved_modules: dict[str, Any] = {}
    try:
        conflict_paths = {str(WORKSPACE_DIR), str(COMPANY_DIR), str(PLATFORM_DIR)}
        sys.path[:] = [kernel_dir] + [
            entry for entry in original_sys_path
            if entry != kernel_dir and entry not in conflict_paths
        ]
        for module_name in _KERNEL_IMPORT_CONFLICTS:
            if module_name in sys.modules:
                saved_modules[module_name] = sys.modules.pop(module_name)
        spec = importlib.util.spec_from_file_location(
            f"meridian_kernel_treasury_gateway_{method_name}",
            KERNEL_DIR / "treasury.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return getattr(module, method_name)(*args, **kwargs)
    finally:
        for module_name in _KERNEL_IMPORT_CONFLICTS:
            sys.modules.pop(module_name, None)
        for module_name, module in saved_modules.items():
            sys.modules[module_name] = module
        sys.path[:] = original_sys_path


def treasury_reserve_runtime_budget(*args: Any, **kwargs: Any) -> Any:
    return _call_isolated_kernel_treasury("reserve_runtime_budget", *args, **kwargs)


def treasury_commit_runtime_budget(*args: Any, **kwargs: Any) -> Any:
    return _call_isolated_kernel_treasury("commit_runtime_budget", *args, **kwargs)


def treasury_release_runtime_budget(*args: Any, **kwargs: Any) -> Any:
    return _call_isolated_kernel_treasury("release_runtime_budget", *args, **kwargs)

SOUL_PATH = WORKSPACE_DIR / "SOUL.md"
MEMORY_PATH = WORKSPACE_DIR / "MEMORY.md"
SKILLS_DIR = WORKSPACE_DIR / "skills"
COUNCIL_CONTEXT_PATH = COMPANY_DIR / "COUNCIL_CUSTOMER_READINESS_CONTEXT.md"
LOOM_MEMORY_PATH = "workspace/MEMORY.md"
LOOM_BIN = runtime_value('binary_path', preferred_loom_bin())
LOOM_ROOT = runtime_value('runtime_root', preferred_loom_root())
SKILL_QUALITY_STATE_PATH = Path(LOOM_ROOT) / "state" / "skill-quality" / "quality.json"
USER_SESSION_SCORE_STATE_PATH = Path(os.path.realpath(capsule_ledger_path())).with_name("user_session_scores.json")
TELEGRAM_DEDUP_STATE_PATH = Path(LOOM_ROOT) / "state" / "gateway" / "telegram_dedup.json"
MEMORY_RECALL_STATE_PATH = Path(LOOM_ROOT) / "state" / "gateway" / "memory_recall.json"
TRUST_EVIDENCE_STATE_PATH = Path(LOOM_ROOT) / "state" / "gateway" / "trust_evidence.json"
TRUST_ASSURANCE_STATE_PATH = Path(LOOM_ROOT) / "state" / "gateway" / "trust_assurance.json"
ROUTE_DECISION_TRACE_PATH = Path(LOOM_ROOT) / "state" / "gateway" / "route_decision_trace.jsonl"
TELEGRAM_INBOUND_DEDUP_WINDOW_SECONDS = int(os.environ.get("MERIDIAN_TELEGRAM_INBOUND_DEDUP_WINDOW_SECONDS", "120"))
TELEGRAM_OUTBOUND_DEDUP_WINDOW_SECONDS = int(os.environ.get("MERIDIAN_TELEGRAM_OUTBOUND_DEDUP_WINDOW_SECONDS", "900"))
SKILL_AUTONOMY_LOCK = threading.RLock()
ROUTE_LOAD_CACHE_LOCK = threading.RLock()
ROUTE_LOAD_CACHE: dict[str, Any] = {"fetched_at_unix_ms": 0, "snapshot": {}}
WORKSPACE_STATUS_CACHE_LOCK = threading.RLock()
WORKSPACE_STATUS_CACHE: dict[str, Any] = {"fetched_at_unix_ms": 0, "snapshot": None}
WORKFLOW_SHOWCASE_CACHE_LOCK = threading.RLock()
WORKFLOW_SHOWCASE_CACHE: dict[str, Any] = {"fetched_at_unix_ms": 0, "snapshot": None}
WORKSPACE_STATUS_REFRESH_LOCK = threading.RLock()
WORKSPACE_STATUS_REFRESH_IN_FLIGHT = False
WORKFLOW_SHOWCASE_REFRESH_LOCK = threading.RLock()
WORKFLOW_SHOWCASE_REFRESH_IN_FLIGHT = False
LOOM_ORG_ID = (
    os.environ.get("MERIDIAN_LOOM_ORG_ID")
    or os.environ.get("MERIDIAN_WORKSPACE_ORG_ID")
    or runtime_value('org_id', '')
    or "org_48b05c21"
)
LOOM_AGENT_ID = os.environ.get("MERIDIAN_LOOM_AGENT_ID", "agent_leviathann")
MERIDIAN_CODEX_HOME = os.environ.get(
    "MERIDIAN_CODEX_HOME",
    "/home/ubuntu/.meridian/auth/codex/login-home",
)
MERIDIAN_CODEX_BIN = os.environ.get(
    "MERIDIAN_CODEX_BIN",
    "/home/ubuntu/.npm-global/bin/codex",
)
MAX_STEPS = int(os.environ.get("MERIDIAN_GATEWAY_MAX_STEPS", "6"))
REQUEST_TIMEOUT_SECONDS = int(os.environ.get("MERIDIAN_GATEWAY_TIMEOUT_SECONDS", "90"))
HEARTBEAT_INTERVAL_SECONDS = 60
ROUTE_SCORE_TEAM_MARGIN_SHORT = int(os.environ.get("MERIDIAN_ROUTE_TEAM_MARGIN_SHORT", "9"))
ROUTE_SCORE_TEAM_MARGIN_DEFAULT = int(os.environ.get("MERIDIAN_ROUTE_TEAM_MARGIN_DEFAULT", "4"))
ROUTE_SCORE_DIRECT_GUARD_CONFIDENCE = int(os.environ.get("MERIDIAN_ROUTE_DIRECT_GUARD_CONFIDENCE", "55"))
ROUTE_LOAD_CACHE_TTL_SECONDS = int(os.environ.get("MERIDIAN_ROUTE_LOAD_CACHE_TTL_SECONDS", "5"))
WORKSPACE_STATUS_CACHE_TTL_SECONDS = int(os.environ.get("MERIDIAN_WORKSPACE_STATUS_CACHE_TTL_SECONDS", "5"))
WORKFLOW_SHOWCASE_CACHE_TTL_SECONDS = int(os.environ.get("MERIDIAN_WORKFLOW_SHOWCASE_CACHE_TTL_SECONDS", "10"))
WORKSPACE_STATUS_UPSTREAM_TIMEOUT_SECONDS = float(
    os.environ.get("MERIDIAN_WORKSPACE_STATUS_UPSTREAM_TIMEOUT_SECONDS", "6")
)
WORKSPACE_API_BASE = os.environ.get("MERIDIAN_WORKSPACE_API_BASE", "http://127.0.0.1:18901").rstrip("/")
WORKSPACE_CREDENTIALS_FILE = Path(
    os.environ.get("MERIDIAN_WORKSPACE_CREDENTIALS_FILE", "/home/ubuntu/.meridian/.workspace_credentials")
)

ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_CYAN = "\033[36m"
ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_RED = "\033[31m"

LLM_BASE_URL = ""
LLM_MODEL = ""
LLM_API_KEY = ""
TEAM_TOPOLOGY = load_team_topology()
sync_loom_team_profiles(TEAM_TOPOLOGY, loom_root=LOOM_ROOT)
TEAM_MANAGER_AGENT_ID = TEAM_TOPOLOGY.manager.registry_id
MEMORY_RECALL_AGENT_ID = os.environ.get("MERIDIAN_MEMORY_AGENT_ID", TEAM_MANAGER_AGENT_ID)
SKILL_VALIDATOR = Path("/home/ubuntu/.codex/skills/.system/skill-creator/scripts/quick_validate.py")
GOVERNED_SKILL_SYNTHESIS_POLICY_REF = "governed_dynamic_skill_synthesis_v1"
GOVERNED_SKILL_BOUNDARY_NAME = "skill_autonomy"
GOVERNED_MEMORY_POLICY_REF = "governed_memory_retrieval_v1"
SKILL_SYNTHESIS_CREATE_COST_USD = 0.03
SKILL_SYNTHESIS_REFINE_COST_USD = 0.015
MEMORY_RECALL_LIMIT = int(os.environ.get("MERIDIAN_MEMORY_RECALL_LIMIT", "4"))
MEMORY_RECALL_SOURCE = "gateway_markdown_memory_sync"
MEMORY_FACT_SOURCE = "gateway_user_fact_extract"
MEMORY_DELIVERY_SOURCE = "gateway_session_artifact_memory"
MEMORY_HISTORY_SCAN_LIMIT = int(os.environ.get("MERIDIAN_MEMORY_HISTORY_SCAN_LIMIT", "160"))
MEMORY_SUCCESSFUL_OUTPUT_LIMIT = int(os.environ.get("MERIDIAN_MEMORY_SUCCESSFUL_OUTPUT_LIMIT", "96"))
MEMORY_USER_FACT_LIMIT = int(os.environ.get("MERIDIAN_MEMORY_USER_FACT_LIMIT", "24"))
MEMORY_DELIVERY_CONTENT_LIMIT = int(os.environ.get("MERIDIAN_MEMORY_DELIVERY_CONTENT_LIMIT", "1200"))
MEMORY_FACT_CONTENT_LIMIT = int(os.environ.get("MERIDIAN_MEMORY_FACT_CONTENT_LIMIT", "240"))
MEMORY_COMPRESSED_OUTPUT_LIMIT = int(os.environ.get("MERIDIAN_MEMORY_COMPRESSED_OUTPUT_LIMIT", "420"))
TRUST_EVIDENCE_LIMIT = int(os.environ.get("MERIDIAN_TRUST_EVIDENCE_LIMIT", "4"))
TRUST_EVIDENCE_COMPRESSED_LIMIT = int(os.environ.get("MERIDIAN_TRUST_EVIDENCE_COMPRESSED_LIMIT", "520"))
TRUST_EVIDENCE_WATCH_FRESHNESS_DAYS = int(os.environ.get("MERIDIAN_TRUST_EVIDENCE_WATCH_FRESHNESS_DAYS", "14"))
TRUST_EVIDENCE_QUESTIONNAIRE_FRESHNESS_DAYS = int(os.environ.get("MERIDIAN_TRUST_EVIDENCE_QUESTIONNAIRE_FRESHNESS_DAYS", "30"))
TRUST_QUESTIONNAIRE_MAX_QUESTIONS = int(os.environ.get("MERIDIAN_TRUST_QUESTIONNAIRE_MAX_QUESTIONS", "8"))
TRUST_QUESTIONNAIRE_APPROVED_FIT = int(os.environ.get("MERIDIAN_TRUST_QUESTIONNAIRE_APPROVED_FIT", "22"))
TRUST_QUESTIONNAIRE_DRAFT_FIT = int(os.environ.get("MERIDIAN_TRUST_QUESTIONNAIRE_DRAFT_FIT", "12"))
MEMORY_SUCCESSFUL_OUTPUT_DECAY_AFTER_DAYS = int(os.environ.get("MERIDIAN_MEMORY_SUCCESSFUL_OUTPUT_DECAY_AFTER_DAYS", "3"))
MEMORY_USER_FACT_DECAY_AFTER_DAYS = int(os.environ.get("MERIDIAN_MEMORY_USER_FACT_DECAY_AFTER_DAYS", "21"))
MEMORY_SUCCESSFUL_OUTPUT_EVICT_AFTER_DAYS = int(os.environ.get("MERIDIAN_MEMORY_SUCCESSFUL_OUTPUT_EVICT_AFTER_DAYS", "21"))
MEMORY_USER_FACT_EVICT_AFTER_DAYS = int(os.environ.get("MERIDIAN_MEMORY_USER_FACT_EVICT_AFTER_DAYS", "120"))
MEMORY_LOW_VALUE_EVICT_THRESHOLD = int(os.environ.get("MERIDIAN_MEMORY_LOW_VALUE_EVICT_THRESHOLD", "-2"))
MEMORY_RECALL_ARTIFACT_VERSION = "compressed_recall_v1"
SKILL_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "cho",
    "cua",
    "for",
    "from",
    "how",
    "i",
    "in",
    "into",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "please",
    "show",
    "that",
    "the",
    "this",
    "toi",
    "to",
    "today",
    "we",
    "with",
    "you",
}
SKILL_WORKER_HINTS = {
    "ai-intelligence": ["ATLAS", "QUILL", "AEGIS"],
    "ai-stack-watch": ["ATLAS", "AEGIS"],
    "council-meeting": ["ATLAS", "SENTINEL", "QUILL", "AEGIS", "FORGE", "PULSE"],
    "download-quarantine": ["FORGE", "SENTINEL"],
    "founder-update": ["QUILL", "AEGIS"],
    "malware-triage": ["FORGE", "SENTINEL"],
    "mvp-sprint-scope": ["ATLAS", "QUILL", "FORGE"],
    "night-shift-ops": ["FORGE", "PULSE", "QUILL"],
    "ops-snapshot": ["FORGE", "PULSE"],
    "safe-web-research": ["ATLAS", "QUILL", "AEGIS"],
    "security-questionnaire": ["ATLAS", "QUILL", "AEGIS"],
    "skill-lab": ["FORGE", "QUILL"],
    "staff-training-loop": ["SENTINEL", "FORGE", "PULSE"],
    "subscribe": ["FORGE", "QUILL", "AEGIS"],
}
GENERIC_AUTONOMY_SKILLS = {"ai-intelligence", "safe-web-research"}
SKILL_ALIAS_HINTS = {
    "ai-intelligence": {"brief", "digest", "competitor", "intelligence", "latest", "research", "snapshot", "weekly"},
    "ai-stack-watch": {
        "ai stack",
        "api change",
        "deprecation",
        "model watch",
        "policy change",
        "pricing change",
        "provider watch",
        "regulation",
        "regulatory",
        "trust risk",
        "vendor watch",
        "watch",
    },
    "council-meeting": {
        "board",
        "buyable",
        "buyer",
        "council",
        "customer",
        "direction",
        "gtm",
        "meeting",
        "open",
        "opensource",
        "product",
        "source",
        "strategy",
        "why",
        "khach",
        "khách",
        "mua",
        "huong",
        "hướng",
        "dinh",
        "định",
        "hoi",
        "hội",
        "dong",
        "đồng",
        "phan",
        "phản",
        "bien",
        "biện",
    },
    "download-quarantine": {"artifact", "download", "file", "hash", "quarantine", "remote"},
    "malware-triage": {"artifact", "indicator", "malware", "risk", "sample", "triage"},
    "mvp-sprint-scope": {"build", "day", "days", "fast", "mvp", "prototype", "scope", "ship", "sprint"},
    "night-shift-ops": {"backlog", "handoff", "night", "overnight", "report", "shift"},
    "ops-snapshot": {"health", "host", "incident", "ops", "snapshot", "status"},
    "safe-web-research": {
        "competitor",
        "domain",
        "latest",
        "link",
        "page",
        "research",
        "scan",
        "search",
        "source",
        "url",
        "web",
        "website",
        "nguon",
        "nguồn",
        "trang",
    },
    "security-questionnaire": {
        "ai governance",
        "answer library",
        "customer assurance",
        "data retention",
        "due diligence",
        "evidence pack",
        "questionnaire",
        "security review",
        "soc2",
        "subprocessor",
        "trust center",
        "vendor risk",
    },
    "skill-lab": {"automate", "playbook", "repeat", "reusable", "skill", "workflow"},
    "staff-training-loop": {"coach", "failure", "improve", "lesson", "prompt", "training", "worker"},
    "subscribe": {"buy", "customer", "pay", "payment", "plan", "pricing", "subscribe", "subscription", "trial"},
}


def _operator_access_token() -> str:
    return str(os.environ.get("MERIDIAN_GATEWAY_TOKEN") or "").strip()


def _extract_operator_token(headers: Any) -> str:
    header_get = getattr(headers, "get", None)
    if not callable(header_get):
        return ""
    authorization = str(header_get("Authorization", "") or "").strip()
    if authorization:
        lowered = authorization.lower()
        if lowered.startswith("bearer "):
            return authorization[7:].strip()
        if lowered.startswith("token "):
            return authorization[6:].strip()
        if lowered.startswith("basic "):
            try:
                decoded = base64.b64decode(authorization[6:].strip()).decode("utf-8")
            except Exception:
                decoded = ""
            if ":" in decoded:
                return decoded.split(":", 1)[1].strip()
    return str(header_get("X-Meridian-Operator-Token", "") or "").strip()


def _operator_token_valid(headers: Any) -> bool:
    expected = _operator_access_token()
    provided = _extract_operator_token(headers)
    if not expected or not provided:
        return False
    return secrets.compare_digest(provided, expected)
AUTONOMY_ACTION_TERMS = {
    "analyze",
    "audit",
    "book",
    "brief",
    "build",
    "buy",
    "call",
    "check",
    "compare",
    "create",
    "debug",
    "deliver",
    "draft",
    "email",
    "fix",
    "gui",
    "gửi",
    "generate",
    "investigate",
    "mail",
    "message",
    "notify",
    "plan",
    "post",
    "prepare",
    "price",
    "quote",
    "register",
    "repair",
    "report",
    "research",
    "review",
    "scan",
    "schedule",
    "search",
    "send",
    "ship",
    "soan",
    "snapshot",
    "status",
    "summarize",
    "support",
    "subscribe",
    "follow",
    "followup",
    "translate",
    "triage",
    "update",
    "verify",
    "viet",
    "viết",
    "write",
}
AUTONOMY_CATEGORY_KEYWORDS = {
    "assurance": {
        "assurance",
        "audit",
        "customer assurance",
        "data retention",
        "diligence",
        "evidence",
        "governance",
        "iso27001",
        "questionnaire",
        "review",
        "risk",
        "soc2",
        "subprocessor",
        "trust",
    },
    "communication": {"email", "mail", "message", "notify", "send", "gửi", "gui", "follow", "followup"},
    "writing": {"announce", "brief", "copy", "demo", "draft", "soan", "summarize", "update", "viet", "viết", "write"},
    "operations": {"debug", "fix", "health", "incident", "ops", "repair", "snapshot", "status", "triage"},
    "research": {"analyze", "compare", "competitor", "customer", "find", "icp", "jtbd", "khach", "khách", "latest", "persona", "research", "scan", "search"},
    "verification": {"audit", "check", "qa", "review", "validate", "verify"},
    "subscription": {"bao gia", "buy", "checkout", "customer", "pay", "payment", "price", "pricing", "proposal", "quote", "subscribe", "trial"},
    "planning": {"book", "build", "demo", "plan", "playbook", "prepare", "protocol", "schedule", "ship", "scope", "sprint"},
}
AUTONOMY_WORKER_PROFILES = {
    "assurance": ["ATLAS", "QUILL", "AEGIS"],
    "communication": ["QUILL", "AEGIS"],
    "writing": ["QUILL", "AEGIS"],
    "operations": ["FORGE", "PULSE", "AEGIS"],
    "research": ["ATLAS", "AEGIS"],
    "verification": ["SENTINEL", "AEGIS"],
    "subscription": ["FORGE", "QUILL", "AEGIS"],
    "planning": ["QUILL", "FORGE", "AEGIS"],
    "general": ["FORGE", "QUILL", "AEGIS"],
}
AUTONOMY_CAPABILITY_HINTS = {
    "assurance": [
        "Atlas should retrieve the strongest relevant evidence and trust signals.",
        "Quill should draft buyer-facing answers and evidence packs without overstating proof.",
        "Aegis should reject unsupported claims, stale evidence, and missing approval state.",
    ],
    "communication": [
        "Quill can draft a send-ready message or email.",
        "Aegis must reject any claim that an external mail transport succeeded without proof.",
    ],
    "writing": [
        "Quill should produce the user-facing artifact.",
        "Aegis should remove unsupported claims and tighten the final copy.",
    ],
    "operations": [
        "Forge should inspect live host/runtime state.",
        "Pulse should compress noisy operational context into an operator-usable summary.",
        "Aegis should gate high-risk claims.",
    ],
    "research": [
        "Atlas should gather findings and options.",
        "Aegis should separate verified facts from unsupported inference.",
    ],
    "verification": [
        "Sentinel should attack contradictions and hidden risk when available.",
        "Aegis should provide the final QA verdict.",
    ],
    "subscription": [
        "Forge should inspect payment or subscription execution paths.",
        "Quill should prepare the customer-facing explanation or offer.",
        "Aegis should block unsupported commercial claims.",
    ],
    "planning": [
        "Quill should turn the result into a usable plan.",
        "Forge should convert the plan into immediate execution steps.",
        "Aegis should reject missing scheduling details or unsupported assumptions before anything is presented as booked.",
    ],
    "general": [
        "Forge should find the closest executable path.",
        "Quill should package the result for the user.",
        "Aegis should reject unsupported claims.",
    ],
}


def _record_gateway_audit(
    action: str,
    *,
    session_key: str,
    channel: str,
    text: str = "",
    outcome: str = "success",
    ingress_request_id: str = "",
    delivery_id: str = "",
    extra_details: dict[str, Any] | None = None,
) -> None:
    details: dict[str, Any] = {
        "channel": str(channel or "").strip(),
    }
    preview = " ".join(str(text or "").split()).strip()
    if preview:
        details["text_preview"] = preview[:280]
    if ingress_request_id:
        details["ingress_request_id"] = str(ingress_request_id).strip()
    if delivery_id:
        details["delivery_id"] = str(delivery_id).strip()
    if isinstance(extra_details, dict):
        for key, value in extra_details.items():
            details[str(key)] = value
    try:
        log_event(
            LOOM_ORG_ID,
            TEAM_MANAGER_AGENT_ID,
            action,
            resource=session_key,
            outcome=outcome,
            details=details,
            session_id=session_key,
        )
    except Exception as exc:
        _log(f"gateway audit warning: {exc}", color=ANSI_YELLOW)


def _profile_transport_kind(provider_kind: str) -> str:
    value = (provider_kind or "").strip().lower()
    if value in {"cli_session", "openai_codex"}:
        return "cli_session"
    if value in {"http_json", "openai_compatible", "custom_endpoint"}:
        return "http_json"
    if value in {"local_http_json", "local_ollama"}:
        return "local_http_json"
    return "unknown"


def _profile_auth_mode(provider_kind: str) -> str:
    value = (provider_kind or "").strip().lower()
    if value in {"cli_session", "openai_codex"}:
        return "session_home"
    if value in {"local_http_json", "local_ollama"}:
        return "none"
    return "bearer_env_pool"


def _team_route_fallback(agent_id: str) -> dict[str, Any]:
    target = (agent_id or "").strip().lower()
    if target in {TEAM_TOPOLOGY.manager.registry_id.lower(), TEAM_TOPOLOGY.manager.handle.lower(), TEAM_TOPOLOGY.manager.name.lower()}:
        manager = TEAM_TOPOLOGY.manager
        return {
            "profile": manager.profile_name,
            "model": manager.model,
            "transport_kind": _profile_transport_kind(manager.provider_kind),
            "auth_mode": _profile_auth_mode(manager.provider_kind),
            "execution_owner": "meridian",
        }
    specialist = TEAM_TOPOLOGY.specialist_by_id(agent_id)
    if specialist is None:
        return {}
    return {
        "profile": specialist.profile_name,
        "model": specialist.model,
        "transport_kind": _profile_transport_kind(specialist.provider_kind),
        "auth_mode": _profile_auth_mode(specialist.provider_kind),
        "execution_owner": "meridian",
    }


def _loom_manager_defaults() -> dict[str, str]:
    manager_meta = brain_router.manager_exec_metadata(runtime_env=os.environ, model_hint="")
    provider_profile = str(manager_meta.get("provider_profile") or "manager_primary").strip() or "manager_primary"
    model = str(manager_meta.get("model") or "").strip()
    manifest_path = Path(LOOM_ROOT) / "state" / "onboard.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        brain = payload.get("brain") or {}
        configured_model = str(brain.get("managerModel") or "").strip()
        configured_profile = str(brain.get("managerProfile") or "").strip()
        if configured_profile:
            provider_profile = configured_profile
        if configured_model and not model:
            model = configured_model
    except Exception:
        pass
    return {"provider_profile": provider_profile, "model": model}


def _run_loom_json(command: list[str], *, timeout: int = REQUEST_TIMEOUT_SECONDS) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            _loom_cli_prefix() + command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    payload = _extract_json_value(stdout)
    if payload is None:
        payload = {}
    result = {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "payload": payload,
    }
    if completed.returncode != 0 and not stderr and not payload:
        result["error"] = stdout[:500]
    elif completed.returncode != 0:
        result["error"] = stderr[:500] or stdout[:500]
    return result


def _load_runtime_job_result(job_id: str) -> dict[str, Any]:
    if not job_id:
        return {}
    path = Path(LOOM_ROOT) / "state" / "runtime" / "jobs" / job_id / "result.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _loom_channel_ingest(channel_id: str, peer_id: str, text: str, *, thread_id: str = "") -> dict[str, Any]:
    command = [
        LOOM_BIN,
        "channel",
        "ingest",
        "--root",
        LOOM_ROOT,
        "--channel",
        channel_id,
        "--peer",
        str(peer_id),
        "--text",
        text,
        "--format",
        "json",
    ]
    if thread_id:
        command.extend(["--thread", str(thread_id)])
    result = _run_loom_json(command)
    if not result.get("ok"):
        _log(f"loom channel ingest failed for {channel_id}:{peer_id}: {result.get('error') or result.get('stderr') or result.get('stdout')}", color=ANSI_YELLOW)
    return result


def _normalize_web_session_id(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    normalized = re.sub(r"[^a-z0-9._-]+", "-", raw).strip("-._")
    return normalized[:64]


def _create_web_session_id(goal: str, client_hint: str = "") -> str:
    seed = f"{time.time_ns()}:{os.getpid()}:{threading.get_ident()}:{client_hint}:{goal[:80]}"
    return f"ws-{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:16]}"


def _resolve_web_request_session(
    payload: dict[str, Any] | None,
    headers: Any,
    goal: str,
) -> dict[str, str | bool]:
    data = payload if isinstance(payload, dict) else {}
    header_get = getattr(headers, "get", None)
    header_session_id = ""
    if callable(header_get):
        header_session_id = str(header_get("X-Meridian-Session-Id", "") or "").strip()
    session_candidates = [
        data.get("session_id"),
        data.get("conversation_id"),
        data.get("thread_id"),
        header_session_id,
    ]
    session_id = ""
    for candidate in session_candidates:
        session_id = _normalize_web_session_id(candidate)
        if session_id:
            break
    generated = False
    if not session_id:
        client_hint = ""
        if callable(header_get):
            client_hint = str(header_get("User-Agent", "") or "").strip()
        session_id = _create_web_session_id(goal, client_hint=client_hint)
        generated = True
    return {
        "session_id": session_id,
        "session_key": f"web_api:{session_id}",
        "generated": generated,
    }


def _effective_web_session_key(session_id: str, ingress_payload: dict[str, Any] | None) -> str:
    fallback_session_key = f"web_api:{session_id}"
    ingress_data = ingress_payload if isinstance(ingress_payload, dict) else {}
    ingress_session_key = str(ingress_data.get("session_key") or "").strip()
    if ingress_session_key and ingress_session_key != f"web_api:{LOOM_ORG_ID}":
        return ingress_session_key
    return fallback_session_key


def _loom_channel_send(channel_id: str, recipient: str, text: str) -> dict[str, Any]:
    command = [
        LOOM_BIN,
        "channel",
        "send",
        "--root",
        LOOM_ROOT,
        "--channel",
        channel_id,
        "--recipient",
        str(recipient),
        "--text",
        text,
        "--format",
        "json",
    ]
    result = _run_loom_json(command)
    if not result.get("ok"):
        _log(f"loom channel send failed for {channel_id}:{recipient}: {result.get('error') or result.get('stderr') or result.get('stdout')}", color=ANSI_YELLOW)
    return result


def _normalize_telegram_dedup_text(text: Any) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value[:8000]


def _telegram_long_window_text(text: Any) -> bool:
    normalized = _normalize_telegram_dedup_text(text)
    return normalized.startswith("🌅 [") and "morning brief:" in normalized


def _load_telegram_dedup_state() -> dict[str, Any]:
    path = TELEGRAM_DEDUP_STATE_PATH
    if not path.exists():
        return {"recent_ingress": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"recent_ingress": {}}
    if not isinstance(payload, dict):
        return {"recent_ingress": {}}
    payload.setdefault("recent_ingress", {})
    if not isinstance(payload.get("recent_ingress"), dict):
        payload["recent_ingress"] = {}
    return payload


def _save_telegram_dedup_state(state: dict[str, Any]) -> None:
    TELEGRAM_DEDUP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TELEGRAM_DEDUP_STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _prune_telegram_dedup_state(state: dict[str, Any], *, now_unix_ms: int | None = None) -> None:
    now_ms = int(now_unix_ms or time.time() * 1000)
    cutoff_ms = now_ms - max(TELEGRAM_OUTBOUND_DEDUP_WINDOW_SECONDS, TELEGRAM_INBOUND_DEDUP_WINDOW_SECONDS) * 1000 * 2
    recent_ingress = state.get("recent_ingress", {})
    if isinstance(recent_ingress, dict):
        for fingerprint, item in list(recent_ingress.items()):
            if not isinstance(item, dict):
                recent_ingress.pop(fingerprint, None)
                continue
            seen_at = int(item.get("seen_at_unix_ms") or 0)
            if seen_at and seen_at < cutoff_ms:
                recent_ingress.pop(fingerprint, None)


def _telegram_ingress_fingerprint(chat_id: Any, message_id: Any, text: Any) -> str:
    normalized = {
        "chat_id": str(chat_id or "").strip(),
        "message_id": str(message_id or "").strip(),
        "text": _normalize_telegram_dedup_text(text),
    }
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    return f"ting_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:20]}"


def _telegram_inbound_seen_recently(chat_id: Any, message_id: Any, text: Any) -> bool:
    fingerprint = _telegram_ingress_fingerprint(chat_id, message_id, text)
    state = _load_telegram_dedup_state()
    _prune_telegram_dedup_state(state)
    recent = state.get("recent_ingress", {})
    if not isinstance(recent, dict):
        recent = {}
        state["recent_ingress"] = recent
    now_ms = int(time.time() * 1000)
    existing = recent.get(fingerprint)
    if isinstance(existing, dict):
        seen_at = int(existing.get("seen_at_unix_ms") or 0)
        if seen_at and now_ms - seen_at <= TELEGRAM_INBOUND_DEDUP_WINDOW_SECONDS * 1000:
            existing["seen_at_unix_ms"] = now_ms
            _save_telegram_dedup_state(state)
            return True
    recent[fingerprint] = {
        "chat_id": str(chat_id or "").strip(),
        "message_id": str(message_id or "").strip(),
        "text_preview": str(text or "").strip()[:200],
        "seen_at_unix_ms": now_ms,
    }
    _save_telegram_dedup_state(state)
    return False


def _recent_telegram_delivery_duplicate(recipient: str, text: str) -> dict[str, Any] | None:
    normalized_text = _normalize_telegram_dedup_text(text)
    if not normalized_text:
        return None
    now_ms = int(time.time() * 1000)
    if _telegram_long_window_text(text):
        cutoff_ms = 0
    else:
        cutoff_ms = now_ms - TELEGRAM_OUTBOUND_DEDUP_WINDOW_SECONDS * 1000
    delivery_dir = Path(LOOM_ROOT) / "state" / "channels" / "delivery"
    matches: list[dict[str, Any]] = []
    for path in sorted(delivery_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(payload.get("channel_id") or "").strip() != "telegram":
            continue
        if str(payload.get("recipient") or "").strip() != str(recipient or "").strip():
            continue
        submitted_at = int(payload.get("submitted_at_unix_ms") or 0)
        if submitted_at and submitted_at < cutoff_ms:
            continue
        status = str(payload.get("status") or "").strip().lower()
        if status not in {"queued", "pending", "delivered"}:
            continue
        candidate_text = _normalize_telegram_dedup_text(payload.get("display_text") or "")
        if candidate_text != normalized_text:
            continue
        matches.append(payload)
    return matches[0] if matches else None


def _loom_channel_deliveries(limit: int = 50) -> list[dict[str, Any]]:
    command = [
        LOOM_BIN,
        "channel",
        "deliveries",
        "--root",
        LOOM_ROOT,
        "--limit",
        str(limit),
        "--format",
        "json",
    ]
    result = _run_loom_json(command)
    payload = result.get("payload") if isinstance(result, dict) else None
    if not result.get("ok") or not isinstance(payload, list):
        if not result.get("ok"):
            _log(
                f"loom channel deliveries failed: {result.get('error') or result.get('stderr') or result.get('stdout')}",
                color=ANSI_YELLOW,
            )
        return []
    return [item for item in payload if isinstance(item, dict)]


def _median_int(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(int(item) for item in values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return int((ordered[mid - 1] + ordered[mid]) / 2)


def _routing_runtime_load_snapshot(*, force_refresh: bool = False) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    ttl_ms = max(1, ROUTE_LOAD_CACHE_TTL_SECONDS) * 1000
    with ROUTE_LOAD_CACHE_LOCK:
        cached_at = int(ROUTE_LOAD_CACHE.get("fetched_at_unix_ms") or 0)
        cached_snapshot = ROUTE_LOAD_CACHE.get("snapshot")
        if (
            not force_refresh
            and isinstance(cached_snapshot, dict)
            and cached_snapshot
            and cached_at
            and now_ms - cached_at <= ttl_ms
        ):
            return dict(cached_snapshot)

    deliveries = _loom_channel_deliveries(limit=24)
    normalized = [item for item in deliveries if isinstance(item, dict)]
    pending_count = 0
    completed_count = 0
    failed_count = 0
    latency_samples: list[int] = []
    latest_status = ""
    for item in normalized:
        status = str(item.get("status") or "").strip().lower()
        if not latest_status and status:
            latest_status = status
        if status in {"queued", "pending"}:
            pending_count += 1
        if status in {"delivered", "failed"}:
            completed_count += 1
            if status == "failed":
                failed_count += 1
            submitted_at = int(item.get("submitted_at_unix_ms") or 0)
            updated_at = int(item.get("updated_at_unix_ms") or 0)
            if submitted_at > 0 and updated_at >= submitted_at:
                latency_ms = updated_at - submitted_at
                if 0 <= latency_ms <= 600_000:
                    latency_samples.append(latency_ms)
    fail_rate = (failed_count / completed_count) if completed_count else 0.0
    latency_p50_ms = _median_int(latency_samples)
    latency_p90_ms = 0
    if latency_samples:
        ordered = sorted(latency_samples)
        idx = int(round((len(ordered) - 1) * 0.9))
        latency_p90_ms = ordered[max(0, min(idx, len(ordered) - 1))]
    backlog_pressure = pending_count
    if latency_p50_ms >= 12_000:
        backlog_pressure += 1
    if fail_rate >= 0.30:
        backlog_pressure += 1
    snapshot = {
        "fetched_at_unix_ms": now_ms,
        "sample_window_count": len(normalized),
        "pending_count": pending_count,
        "completed_count": completed_count,
        "failed_count": failed_count,
        "fail_rate": round(fail_rate, 4),
        "latency_p50_ms": latency_p50_ms,
        "latency_p90_ms": latency_p90_ms,
        "latest_status": latest_status or "unknown",
        "backlog_pressure": backlog_pressure,
    }
    with ROUTE_LOAD_CACHE_LOCK:
        ROUTE_LOAD_CACHE["fetched_at_unix_ms"] = now_ms
        ROUTE_LOAD_CACHE["snapshot"] = dict(snapshot)
    return snapshot


def _adaptive_route_thresholds(load_snapshot: dict[str, Any]) -> dict[str, Any]:
    team_margin_short = ROUTE_SCORE_TEAM_MARGIN_SHORT
    team_margin_default = ROUTE_SCORE_TEAM_MARGIN_DEFAULT
    direct_guard_confidence = ROUTE_SCORE_DIRECT_GUARD_CONFIDENCE
    pending_count = int(load_snapshot.get("pending_count") or 0)
    latency_p50_ms = int(load_snapshot.get("latency_p50_ms") or 0)
    fail_rate = float(load_snapshot.get("fail_rate") or 0.0)
    notes: list[str] = []

    if pending_count >= 4:
        team_margin_short += 5
        team_margin_default += 4
        direct_guard_confidence -= 6
        notes.append("queue_high")
    elif pending_count >= 2:
        team_margin_short += 3
        team_margin_default += 2
        direct_guard_confidence -= 3
        notes.append("queue_elevated")

    if latency_p50_ms >= 12_000:
        team_margin_short += 4
        team_margin_default += 3
        direct_guard_confidence -= 4
        notes.append("latency_high")
    elif latency_p50_ms >= 7_000:
        team_margin_short += 2
        team_margin_default += 1
        direct_guard_confidence -= 2
        notes.append("latency_elevated")

    if fail_rate >= 0.35:
        team_margin_short += 4
        team_margin_default += 3
        direct_guard_confidence -= 5
        notes.append("delivery_fail_rate_high")
    elif fail_rate >= 0.20:
        team_margin_short += 2
        team_margin_default += 1
        direct_guard_confidence -= 2
        notes.append("delivery_fail_rate_elevated")

    if pending_count == 0 and latency_p50_ms and latency_p50_ms <= 2_500 and fail_rate <= 0.10:
        team_margin_short -= 1
        team_margin_default -= 1
        direct_guard_confidence += 1
        notes.append("load_low")

    team_margin_short = max(3, min(team_margin_short, 26))
    team_margin_default = max(2, min(team_margin_default, 20))
    direct_guard_confidence = max(35, min(direct_guard_confidence, 85))

    load_tier = "normal"
    if pending_count >= 4 or latency_p50_ms >= 12_000 or fail_rate >= 0.35:
        load_tier = "high"
    elif pending_count >= 2 or latency_p50_ms >= 7_000 or fail_rate >= 0.20:
        load_tier = "elevated"
    elif pending_count == 0 and latency_p50_ms and latency_p50_ms <= 2_500 and fail_rate <= 0.10:
        load_tier = "low"

    return {
        "team_margin_short": team_margin_short,
        "team_margin_default": team_margin_default,
        "direct_guard_confidence": direct_guard_confidence,
        "load_tier": load_tier,
        "notes": notes,
    }


def _loom_channel_update(
    delivery_id: str,
    status: str,
    *,
    external_ref: str = "",
    detail: str | None = None,
) -> dict[str, Any]:
    delivery_id = str(delivery_id or "").strip()
    status = str(status or "").strip()
    if not delivery_id or not status:
        return {}
    command = [
        LOOM_BIN,
        "channel",
        "update",
        "--root",
        LOOM_ROOT,
        "--delivery-id",
        delivery_id,
        "--status",
        status,
        "--format",
        "json",
    ]
    if external_ref:
        command.extend(["--external-ref", external_ref])
    if detail is not None:
        command.extend(["--detail", detail])
    result = _run_loom_json(command)
    if not result.get("ok"):
        _log(
            f"loom channel update failed for {delivery_id}: {result.get('error') or result.get('stderr') or result.get('stdout')}",
            color=ANSI_YELLOW,
        )
    return result


def _loom_manager_route(*, agent_id: str = "", org_id: str = "") -> dict[str, Any]:
    command = [
        LOOM_BIN,
        "provider",
        "route",
        "--root",
        LOOM_ROOT,
        "--capability",
        "loom.llm.inference.v1",
        "--format",
        "json",
    ]
    if agent_id:
        command.extend(["--agent-id", agent_id])
    if org_id:
        command.extend(["--org-id", org_id])
    result = _run_loom_json(command)
    if result.get("ok") and isinstance(result.get("payload"), dict):
        return result.get("payload")
    return _team_route_fallback(agent_id)


def _loom_session_route(
    session_key: str,
    *,
    agent_id: str = "",
    org_id: str = "",
    ingress_request_id: str = "",
    delivery_id: str = "",
    job_id: str = "",
) -> dict[str, Any]:
    channel_id, _, peer_id = session_key.partition(":")
    binding_id = f"binding-{channel_id}" if channel_id else ""
    route = _loom_manager_route(agent_id=agent_id, org_id=org_id)
    provider_profile = str(route.get("profile") or "").strip()
    model = str(route.get("model") or "").strip()
    transport_kind = str(route.get("transport_kind") or "").strip()
    auth_mode = str(route.get("auth_mode") or "").strip()
    execution_owner = str(route.get("execution_owner") or "").strip()
    command = [
        LOOM_BIN,
        "session",
        "route",
        "--root",
        LOOM_ROOT,
        "--session-key",
        session_key,
        "--channel-id",
        channel_id,
        "--peer-id",
        peer_id,
        "--binding-id",
        binding_id,
        "--agent-id",
        agent_id,
        "--override-source",
        "default",
        "--format",
        "json",
    ]
    if org_id:
        command.extend(["--org-id", org_id])
    if provider_profile:
        command.extend(["--provider-profile", provider_profile])
    if model:
        command.extend(["--model", model])
    if transport_kind:
        command.extend(["--transport-kind", transport_kind])
    if auth_mode:
        command.extend(["--auth-mode", auth_mode])
    if execution_owner:
        command.extend(["--execution-owner", execution_owner])
    if ingress_request_id:
        command.extend(["--ingress-request-id", ingress_request_id])
    if delivery_id:
        command.extend(["--delivery-id", delivery_id])
    if job_id:
        command.extend(["--job-id", job_id])
    result = _run_loom_json(command)
    if not result.get("ok"):
        _log(
            f"loom session route failed for {session_key}: {result.get('error') or result.get('stderr') or result.get('stdout')}",
            color=ANSI_YELLOW,
        )
    return result


_MERIDIAN_INTERNAL_STATUS_TERMS = (
    "meridian",
    "loom",
    "gateway",
    "telegram",
    "delivery queue",
    "bot",
    "kernel",
    "treasury",
    "authority",
    "court",
    "commitment",
    "governance",
    "runtime proof",
    "runtime-proof",
    "preflight",
    "admission",
    "federation",
    "constitutional",
)
_MERIDIAN_INTERNAL_QUESTION_TERMS = (
    "current",
    "now",
    "status",
    "trạng thái",
    "trang thai",
    "state",
    "posture",
    "health",
    "hiện tại",
    "hien tai",
    "runtime",
    "proof",
    "balance",
    "pending",
    "open",
    "match",
    "aligned",
)

_MERIDIAN_TEAM_REQUEST_TERMS = (
    "workflow",
    "workflows",
    "plan",
    "remediation",
    "remediate",
    "step-by-step",
    "steps",
    "write",
    "draft",
    "compare",
    "operator crisis",
    "use whichever specialists",
    "founder-facing",
    "messaging",
)

_MERIDIAN_COMPLEX_OPERATOR_TERMS = (
    "workflow",
    "remediation",
    "operator crisis",
    "founder update",
    "contributor payouts",
    "actual phase gate",
    "host evidence",
    "next update should promise",
    "payout execution",
    "sanction-restricted",
    "telegram delivery",
    "worker verification",
    "do not invent evidence",
    "three things at once",
)


def _looks_like_meridian_operator_workflow_query(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    mentions_complex_ops = any(term in lowered for term in _MERIDIAN_COMPLEX_OPERATOR_TERMS)
    mentions_meridian = any(term in lowered for term in _MERIDIAN_INTERNAL_STATUS_TERMS)
    mentions_governed_runtime = any(
        term in lowered for term in ("contributor payouts", "phase gate", "telegram delivery", "host evidence")
    )
    return mentions_complex_ops and (mentions_meridian or mentions_governed_runtime)

_MERIDIAN_POSITIONING_TERMS = (
    "leviathann",
    "direct specialists",
    "specialists directly",
    "talk to leviathann",
    "why users should talk",
    "founder answer",
    "brand voice",
    "homepage version",
)

_MERIDIAN_COUNCIL_TERMS = (
    "council",
    "board",
    "meeting",
    "hội đồng",
    "hoi dong",
    "phản biện",
    "phan bien",
    "tranh luận",
    "tranh luan",
    "đối chiếu",
    "doi chieu",
    "thống nhất",
    "thong nhat",
)

_MERIDIAN_COUNCIL_EXPLICIT_TRIGGERS = (
    "/council",
    "board review for meridian",
    "internal council for meridian",
    "meridian board review",
    "meridian council",
    "meridian council meeting",
    "meridian internal council",
    "meridian strategy council",
    "họp hội đồng meridian",
    "hoi dong meridian",
)

_MERIDIAN_CUSTOMER_STRATEGY_TERMS = (
    "customer",
    "buyer",
    "buyable",
    "buy",
    "product",
    "money",
    "pay",
    "pricing",
    "open source",
    "opensource",
    "direction",
    "strategy",
    "wedge",
    "khách",
    "khach",
    "mua",
    "sản phẩm",
    "san pham",
    "kiếm tiền",
    "kiem tien",
    "opensouce",
    "định hướng",
    "dinh huong",
)


def _looks_like_meridian_internal_query(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    if _request_is_security_questionnaire(text) or _request_is_ai_stack_watch(text):
        return False
    if _looks_like_meridian_council_query(text):
        return False
    mentions_meridian = any(term in lowered for term in _MERIDIAN_INTERNAL_STATUS_TERMS)
    asks_for_state = any(term in lowered for term in _MERIDIAN_INTERNAL_QUESTION_TERMS)
    asks_for_team_work = any(term in lowered for term in _MERIDIAN_TEAM_REQUEST_TERMS)
    asks_for_explicit_action = any(
        term in lowered
        for term in (
            "gửi mail",
            "gui mail",
            "send mail",
            "email to",
            "book meeting",
            "đặt lịch",
            "dat lich",
            "soạn",
            "soan",
        )
    )
    return mentions_meridian and asks_for_state and not asks_for_team_work and not asks_for_explicit_action


def _looks_like_meridian_positioning_query(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    mentions_positioning = any(term in lowered for term in _MERIDIAN_POSITIONING_TERMS)
    mentions_complex_ops = any(term in lowered for term in _MERIDIAN_COMPLEX_OPERATOR_TERMS)
    return mentions_positioning and not mentions_complex_ops


def _looks_like_meridian_council_query(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    explicit_trigger = any(trigger in lowered for trigger in _MERIDIAN_COUNCIL_EXPLICIT_TRIGGERS)
    if not explicit_trigger:
        return False
    mentions_council = any(term in lowered for term in _MERIDIAN_COUNCIL_TERMS)
    mentions_strategy = any(term in lowered for term in _MERIDIAN_CUSTOMER_STRATEGY_TERMS)
    mentions_meridian = "meridian" in lowered or "leviathann" in lowered or "loom" in lowered or "kernel" in lowered
    strategy_hits = sum(1 for term in _MERIDIAN_CUSTOMER_STRATEGY_TERMS if term in lowered)
    return (
        (mentions_council and (mentions_strategy or mentions_meridian))
        or (mentions_meridian and strategy_hits >= 2)
        or (strategy_hits >= 3 and any(term in lowered for term in ("open source", "opensource", "định hướng", "dinh huong", "mua", "buy", "customer", "khách")))
    )


def _worker_is_restricted(agent_key: str) -> bool:
    specialist = next((agent for agent in TEAM_TOPOLOGY.specialists if agent.env_key == agent_key), None)
    if specialist is None:
        return False
    try:
        restrictions = court_get_restrictions(specialist.economy_key, org_id=LOOM_ORG_ID) or []
    except Exception:
        return False
    values = {str(item or "").strip().lower() for item in restrictions}
    return bool(values & {"execute", "assign", "lead"})


def _normalize_worker_selection(workers: list[str], text: str) -> list[str]:
    ordered: list[str] = []
    for worker in workers:
        value = str(worker or "").strip().upper()
        if value not in SPECIALIST_KEYS or value in ordered:
            continue
        if _worker_is_restricted(value):
            if value == "SENTINEL" and "AEGIS" not in ordered and not _worker_is_restricted("AEGIS"):
                ordered.append("AEGIS")
            continue
        ordered.append(value)
    if _looks_like_meridian_positioning_query(text):
        preferred = [worker for worker in ordered if worker in {"QUILL", "AEGIS", "PULSE"}]
        if "QUILL" not in preferred and not _worker_is_restricted("QUILL"):
            preferred.append("QUILL")
        if "AEGIS" not in preferred and not _worker_is_restricted("AEGIS"):
            preferred.append("AEGIS")
        ordered = preferred
    return ordered


def _request_prefers_compact_status_response(goal: str) -> tuple[bool, int]:
    lowered = str(goal or "").strip().lower()
    if not lowered:
        return False, 0
    compact_markers = (
        "trả lời ngắn",
        "tra loi ngan",
        "ngắn gọn",
        "ngan gon",
        "one line",
        "1 line",
        "một câu",
        "mot cau",
        "bullet",
        "gạch đầu dòng",
        "gach dau dong",
    )
    wants_compact = any(marker in lowered for marker in compact_markers)
    wants_two = any(marker in lowered for marker in ("2 gạch đầu dòng", "2 bullet", "two bullet", "2 dòng", "2 dong"))
    return wants_compact, (2 if wants_two else 0)


def _render_meridian_internal_answer(_goal: str) -> str:
    status = _workspace_api_get_json("/api/status")
    proof = _workspace_api_get_json("/api/runtime-proof")
    if not status.get("ok"):
        payload = status.get("payload") or {}
        detail = str(payload.get("output") or payload.get("error") or "workspace status unavailable").strip()
        return f"Meridian live status is currently unavailable: {detail}"
    status_payload = dict(status.get("payload") or {})
    proof_payload = dict(proof.get("payload") or {})
    context = dict(status_payload.get("context") or {})
    treasury = dict(status_payload.get("treasury") or {})
    authority = dict(status_payload.get("authority") or {})
    cases = dict(status_payload.get("cases") or {})
    observability = dict(status_payload.get("observability") or {})
    slo = dict(status_payload.get("slo") or observability.get("slo") or {})
    alert_queue = dict(status_payload.get("alert_queue") or {})
    surfaces = dict(proof_payload.get("runtime_surfaces") or {})
    session_surface = dict(surfaces.get("session_provenance") or {})
    channel_surface = dict(surfaces.get("channel_runtime") or {})
    pending_approvals = authority.get("pending_approvals") or []
    org_id = str(context.get("bound_org_id") or status_payload.get("org_id") or LOOM_ORG_ID).strip() or LOOM_ORG_ID
    runtime_id = str(status_payload.get("runtime_id") or proof_payload.get("runtime_id") or "unknown").strip() or "unknown"
    preflight = str(status_payload.get("preflight") or status_payload.get("ci_vertical", {}).get("preflight") or "unknown").strip() or "unknown"
    slo_status = str(slo.get("status") or "unknown").strip() or "unknown"
    alert_count = int(alert_queue.get("queue_count") or 0)
    balance = float(treasury.get("balance_usd") or 0.0)
    reserve_floor = float(treasury.get("reserve_floor_usd") or 0.0)
    open_cases = int(cases.get("open") or 0)
    active_sessions = int(session_surface.get("active_count") or 0)
    active_deliveries = int(channel_surface.get("active_delivery_count") or 0)
    telegram = _recent_telegram_delivery_summary(limit=5)
    telegram_checked = int(telegram.get("checked_count") or 0)
    telegram_delivered = int(telegram.get("delivered_count") or 0)
    telegram_failed = int(telegram.get("failed_count") or 0)
    telegram_latest = str(telegram.get("latest_status") or "unknown").strip() or "unknown"
    wants_compact, bullet_count = _request_prefers_compact_status_response(_goal)
    if wants_compact and bullet_count == 2:
        return (
            f"- Gateway runtime: `{runtime_id}` for `{org_id}`; preflight `{preflight}`; SLO `{slo_status}`.\n"
            f"- Telegram delivery: latest `{telegram_latest}`, delivered `{telegram_delivered}/{telegram_checked}`, failed `{telegram_failed}`."
        )
    if wants_compact:
        return (
            f"Meridian runtime `{runtime_id}` is live (preflight `{preflight}`, SLO `{slo_status}`); "
            f"Telegram latest `{telegram_latest}` with `{telegram_delivered}/{telegram_checked}` delivered and `{telegram_failed}` failed."
        )
    return (
        f"Meridian is operating on {runtime_id} for {org_id} with preflight {preflight}, "
        f"SLO {slo_status}, {alert_count} queued alerts, treasury ${balance:.2f} against a ${reserve_floor:.2f} reserve floor, "
        f"{len(pending_approvals)} pending approvals, {open_cases} open cases, "
        f"{active_sessions} active sessions, {active_deliveries} active channel deliveries, "
        f"and Telegram latest {telegram_latest} with {telegram_delivered}/{telegram_checked} delivered and {telegram_failed} failed."
    )


def _recent_telegram_delivery_summary(limit: int = 5) -> dict[str, Any]:
    delivery_dir = Path(LOOM_ROOT) / "state" / "channels" / "delivery"
    records: list[dict[str, Any]] = []
    try:
        candidates = sorted(delivery_dir.glob("*.json"), reverse=True)
    except Exception:
        candidates = []
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("channel_id") or "").strip() != "telegram":
            continue
        records.append(payload)
        if len(records) >= limit:
            break
    return {
        "checked_count": len(records),
        "delivered_count": sum(1 for item in records if str(item.get("status") or "").strip() == "delivered"),
        "failed_count": sum(1 for item in records if str(item.get("status") or "").strip() == "failed"),
        "pending_count": sum(1 for item in records if str(item.get("status") or "").strip() not in {"delivered", "failed"}),
        "latest_status": str(records[0].get("status") or "").strip() if records else "",
        "latest_delivery_id": str(records[0].get("delivery_id") or "").strip() if records else "",
    }


def _build_meridian_operator_truth_packet() -> dict[str, Any]:
    status = _workspace_api_get_json("/api/status")
    proof = _workspace_api_get_json("/api/runtime-proof")
    payouts = _workspace_api_get_json("/api/payouts")
    status_payload = dict(status.get("payload") or {}) if status.get("ok") else {}
    proof_payload = dict(proof.get("payload") or {}) if proof.get("ok") else {}
    payouts_payload = dict(payouts.get("payload") or {}) if payouts.get("ok") else {}
    context = dict(status_payload.get("context") or {})
    treasury = dict(status_payload.get("treasury") or {})
    observability = dict(status_payload.get("observability") or {})
    slo = dict(status_payload.get("slo") or observability.get("slo") or {})
    alert_queue = dict(status_payload.get("alert_queue") or {})
    authority = dict(status_payload.get("authority") or {})
    cases = dict(status_payload.get("cases") or {})
    execution_gate = dict(payouts_payload.get("execution_gate") or {})
    phase_machine = dict(payouts_payload.get("phase_machine") or {})
    return {
        "runtime_id": str(status_payload.get("runtime_id") or proof_payload.get("runtime_id") or "").strip(),
        "org_id": str(context.get("bound_org_id") or LOOM_ORG_ID).strip(),
        "preflight": str(status_payload.get("preflight") or status_payload.get("ci_vertical", {}).get("preflight") or "").strip(),
        "slo_status": str(slo.get("status") or "").strip(),
        "queued_alerts": int(alert_queue.get("queue_count") or 0),
        "treasury_balance_usd": float(treasury.get("balance_usd") or 0.0),
        "treasury_reserve_floor_usd": float(treasury.get("reserve_floor_usd") or 0.0),
        "pending_approvals": len(authority.get("pending_approvals") or []),
        "open_cases": int(cases.get("open") or 0),
        "payout_phase_number": phase_machine.get("number"),
        "payout_phase_name": phase_machine.get("name"),
        "payout_execution_gate_ok": bool(execution_gate.get("phase_ok")),
        "payout_execution_gate_reason": str(execution_gate.get("reason") or "").strip(),
        "sentinel_restricted": _worker_is_restricted("SENTINEL"),
        "telegram_delivery": _recent_telegram_delivery_summary(),
    }


def _build_meridian_council_truth_packet() -> dict[str, Any]:
    operator_truth = _build_meridian_operator_truth_packet()
    status = _workspace_api_get_json("/api/status")
    readiness = _workspace_api_get_json("/api/treasury/settlement-adapters/readiness")
    status_payload = dict(status.get("payload") or {}) if status.get("ok") else {}
    service_state = dict(status_payload.get("service_state") or {})
    readiness_payload = dict(readiness.get("payload") or {}) if readiness.get("ok") else {}
    readiness_summary = dict(readiness_payload.get("summary") or {})
    return {
        "operator_truth": operator_truth,
        "open_source_posture": {
            "mode": "full_open_source",
            "public_checkout_live": False,
            "support_model": "voluntary_support_and_research_collaboration",
            "setup_path": "/pilot",
            "legacy_route_status": {
                "path": "/api/institution/license/catalog",
                "status": "deprecated_410",
                "reason": "open_source_mode",
            },
        },
        "delivery_truth": {
            "email_bounded_delivery_live": True,
            "telegram_bounded_delivery_live": True,
            "broad_customer_automation_live": False,
            "nightly_pipeline_state": "treasury_gated_and_preflight_gated",
            "open_enrollment_offer_live": False,
        },
        "payment_truth": {
            "card_gateway_live": False,
            "paypal_gateway_live": False,
            "manual_bank_wire_primary": False,
            "x402_external_customer_proof": False,
            "base_usdc_public_gateway_live": False,
        },
        "service_state_truth": {
            "pilot_intake_mode": "deprecated_public_route",
            "subscription_preview_public_path": "",
            "public_support_paths": {},
        },
        "subscription_truth": {
            "status": "internal_subscription_state_preserved_for_ledger_continuity",
            "public_support_intake_enabled": False,
        },
        "settlement_truth": {
            "ready_adapter_ids": list(readiness_payload.get("ready_adapter_ids") or []),
            "blocked_adapter_ids": list(readiness_payload.get("blocked_adapter_ids") or []),
            "host_supported_adapters": list(readiness_summary.get("host_supported_adapters") or []),
            "default_payout_adapter": readiness_payload.get("default_payout_adapter"),
        },
        "open_source_truth": {
            "kernel_open_source": True,
            "kernel_role": "runtime_neutral_governance_layer",
            "intelligence_role": "first_open_research_vertical",
            "loom_role": "live_execution_runtime_on_this_host_and_installable_local_runtime",
            "hosted_service_fully_open": False,
            "not_open_scope": [
                "delivery_pipelines",
                "payment_processing",
                "customer_data",
                "proprietary_research_sources",
            ],
            "doctrine_rule": "prefer_the_narrower_claim_that_can_be_honored_today",
        },
        "council_paths": {
            "doctrine": "company/MERIDIAN_DOCTRINE.md",
            "context_pack": str(COUNCIL_CONTEXT_PATH.relative_to(WORKSPACE_DIR)),
            "homepage": "company/www/index.html",
            "demo": "company/www/demo.html",
            "get_started": "company/www/pilot.html",
            "boundary": "company/www/OPEN_SOURCE_BOUNDARY.html",
            "kernel_readme": "/opt/meridian-kernel/README.md",
            "public_readme": "README.md",
        },
    }


def _build_workflow_showcase_snapshot() -> dict[str, Any]:
    status = _workspace_status_snapshot_cached()
    aux_routes = ["/api/runtime-proof", "/api/payouts", "/api/treasury"]
    aux_payloads: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(aux_routes)) as pool:
        futures = {
            pool.submit(_workspace_api_get_json_with_timeout, route, 8.0): route
            for route in aux_routes
        }
        for future in concurrent.futures.as_completed(futures):
            route = futures[future]
            try:
                result = future.result()
            except Exception:
                result = {"ok": False, "payload": {}}
            aux_payloads[route] = result if isinstance(result, dict) else {"ok": False, "payload": {}}

    status_payload = dict(status.get("payload") or {}) if status.get("ok") else {}
    proof_result = dict(aux_payloads.get("/api/runtime-proof") or {})
    payouts_result = dict(aux_payloads.get("/api/payouts") or {})
    treasury_result = dict(aux_payloads.get("/api/treasury") or {})
    proof_payload = dict(proof_result.get("payload") or {}) if proof_result.get("ok") else {}
    payouts_payload = dict(payouts_result.get("payload") or {}) if payouts_result.get("ok") else {}
    treasury_payload = dict(treasury_result.get("payload") or {}) if treasury_result.get("ok") else {}

    authority = dict(status_payload.get("authority") or {})
    cases = dict(status_payload.get("cases") or {})
    alert_queue = dict(status_payload.get("alert_queue") or {})
    status_treasury = dict(status_payload.get("treasury") or {})
    execution_gate = dict(payouts_payload.get("execution_gate") or {})
    phase_machine = dict(payouts_payload.get("phase_machine") or {})
    proposals = list(payouts_payload.get("proposals") or [])
    telegram = _recent_telegram_delivery_summary(limit=10)

    treasury_balance = float(
        treasury_payload.get("balance_usd")
        or status_treasury.get("balance_usd")
        or 0.0
    )
    reserve_floor = float(
        treasury_payload.get("reserve_floor_usd")
        or status_treasury.get("reserve_floor_usd")
        or 0.0
    )
    paid_orders = int(treasury_payload.get("paid_orders") or status_treasury.get("paid_orders") or 0)
    proof_type = str(
        proof_payload.get("proof_type")
        or proof_payload.get("status")
        or status_payload.get("proof_mode")
        or "unknown"
    ).strip() or "unknown"
    runtime_id = str(
        status_payload.get("runtime_id")
        or proof_payload.get("runtime_id")
        or "unknown"
    ).strip() or "unknown"

    workflows = [
        {
            "workflow_id": "ai_stack_watch",
            "title": "AI Stack Watch",
            "status": "live",
            "pricing_hint_usd": 0.50,
            "proof_hooks": ["cited_findings", "route_decision_trace", "delivery_receipts"],
            "operator_signal": "queued_alerts",
            "operator_value": int(alert_queue.get("queue_count") or 0),
        },
        {
            "workflow_id": "security_questionnaire_assist",
            "title": "Security Questionnaire Assist",
            "status": "live_with_review_queue",
            "pricing_hint_usd": 1.50,
            "proof_hooks": ["evidence_lifecycle", "approval_queue", "review_audit"],
            "operator_signal": "pending_approvals",
            "operator_value": len(authority.get("pending_approvals") or []),
        },
        {
            "workflow_id": "trust_ops_delivery",
            "title": "Trust Ops Delivery",
            "status": "live_with_fallback",
            "pricing_hint_usd": 3.00,
            "proof_hooks": ["channel_health", "fallback_path", "sanction_path"],
            "operator_signal": "open_cases",
            "operator_value": int(cases.get("open") or 0),
        },
    ]

    return {
        "schema_version": "meridian.workflow_showcase.v1",
        "generated_at_unix_ms": int(time.time() * 1000),
        "runtime_id": runtime_id,
        "proof_type": proof_type,
        "treasury_balance_usd": treasury_balance,
        "treasury_reserve_floor_usd": reserve_floor,
        "paid_orders": paid_orders,
        "payout_proposals": len(proposals),
        "payout_phase": {
            "number": phase_machine.get("number"),
            "name": phase_machine.get("name"),
            "execution_gate_ok": bool(execution_gate.get("phase_ok")),
            "execution_gate_reason": str(execution_gate.get("reason") or "").strip(),
        },
        "telegram_delivery": telegram,
        "workflows": workflows,
    }


def _load_council_context() -> str:
    try:
        return COUNCIL_CONTEXT_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _atlas_should_use_internal_analysis(plan: dict[str, Any], request: str) -> bool:
    reason = str(plan.get("reason") or "").strip().lower()
    lowered = str(request or "").strip().lower()
    skill_names = {
        str(item.get("name") or "").strip().lower()
        for item in list(plan.get("skills") or [])
        if isinstance(item, dict)
    }
    if reason in {
        "meridian_council_meeting",
        "meridian_positioning",
        "meridian_operator_workflow",
    }:
        return True
    if "council-meeting" in skill_names:
        return True
    return any(token in lowered for token in ("meridian", "leviathann", "loom", "kernel", "open source", "opensource"))


def _verified_fact_mode_enabled(request: str, skills_used: list[str], verified_facts: dict[str, Any] | None) -> bool:
    if not isinstance(verified_facts, dict) or not verified_facts:
        return False
    names = {str(item or "").strip().lower() for item in skills_used if str(item or "").strip()}
    if "council-meeting" in names or _looks_like_meridian_council_query(request):
        return False
    if names & {"ops-snapshot", "founder-update"}:
        return True
    return (
        _looks_like_meridian_internal_query(request)
        or _looks_like_meridian_operator_workflow_query(request)
        or _looks_like_meridian_positioning_query(request)
    )


def _format_usd(value: Any) -> str:
    try:
        return f"${float(value or 0.0):.2f}"
    except Exception:
        return "$0.00"


def _verified_fact_citations(verified_facts: dict[str, Any]) -> list[str]:
    telegram = dict(verified_facts.get("telegram_delivery") or {})
    return [
        f"runtime_id: {verified_facts.get('runtime_id')}",
        f"preflight: {verified_facts.get('preflight')}",
        f"slo_status: {verified_facts.get('slo_status')}",
        f"queued_alerts: {verified_facts.get('queued_alerts')}",
        f"treasury_balance_usd: {verified_facts.get('treasury_balance_usd')}",
        f"treasury_reserve_floor_usd: {verified_facts.get('treasury_reserve_floor_usd')}",
        f"pending_approvals: {verified_facts.get('pending_approvals')}",
        f"open_cases: {verified_facts.get('open_cases')}",
        f"payout_phase: {verified_facts.get('payout_phase_number')} / {verified_facts.get('payout_phase_name')}",
        f"payout_execution_gate_ok: {verified_facts.get('payout_execution_gate_ok')}",
        f"telegram_delivery_checked: {telegram.get('checked_count')}",
        f"telegram_delivery_latest_status: {telegram.get('latest_status')}",
    ]


def _verified_fact_warnings(verified_facts: dict[str, Any], *, include_unknowns: bool = True) -> list[str]:
    warnings: list[str] = []
    if not bool(verified_facts.get("payout_execution_gate_ok")):
        reason = str(verified_facts.get("payout_execution_gate_reason") or "").strip()
        if reason:
            warnings.append(f"payout_execution_gate: {reason}")
    if bool(verified_facts.get("sentinel_restricted")):
        warnings.append("sentinel lane is currently restricted by live host controls")
    if include_unknowns:
        warnings.append("disk pressure and scheduled-job status were not independently verified in this snapshot")
    return warnings


def _specialist_role_label(specialist: Any) -> str:
    role = str(getattr(specialist, "role", "") or "").strip()
    if role:
        return role
    task_kind = str(getattr(specialist, "task_kind", "") or "").strip().lower()
    fallback_by_task = {
        "research": "research specialist",
        "verify": "verification specialist",
        "qa_gate": "quality gate specialist",
        "execute": "execution specialist",
        "write": "writing specialist",
        "compress": "compression specialist",
        "manage": "manager",
    }
    if task_kind:
        return fallback_by_task.get(task_kind, task_kind.replace("_", " "))
    return "specialist"


def _specialist_purpose_label(specialist: Any) -> str:
    purpose = str(getattr(specialist, "purpose", "") or "").strip()
    if purpose:
        return purpose
    task_kind = str(getattr(specialist, "task_kind", "") or "").strip().replace("_", " ")
    if task_kind:
        return f"Deliver governed {task_kind} output with verifiable traceability."
    return "Deliver governed output with verifiable traceability."


def _verified_fact_worker_receipt(
    specialist: TeamSpecialist,
    request: str,
    session_key: str,
    verified_facts: dict[str, Any],
    skills_used: list[str],
) -> dict[str, Any]:
    telegram = dict(verified_facts.get("telegram_delivery") or {})
    runtime_id = str(verified_facts.get("runtime_id") or "unknown").strip() or "unknown"
    org_id = str(verified_facts.get("org_id") or LOOM_ORG_ID).strip() or LOOM_ORG_ID
    preflight = str(verified_facts.get("preflight") or "unknown").strip() or "unknown"
    slo_status = str(verified_facts.get("slo_status") or "unknown").strip() or "unknown"
    queued_alerts = int(verified_facts.get("queued_alerts") or 0)
    pending_approvals = int(verified_facts.get("pending_approvals") or 0)
    open_cases = int(verified_facts.get("open_cases") or 0)
    treasury_balance = _format_usd(verified_facts.get("treasury_balance_usd"))
    reserve_floor = _format_usd(verified_facts.get("treasury_reserve_floor_usd"))
    phase_number = verified_facts.get("payout_phase_number")
    phase_name = str(verified_facts.get("payout_phase_name") or "").strip()
    payout_reason = str(verified_facts.get("payout_execution_gate_reason") or "").strip()
    checked = int(telegram.get("checked_count") or 0)
    delivered = int(telegram.get("delivered_count") or 0)
    failed = int(telegram.get("failed_count") or 0)
    pending = int(telegram.get("pending_count") or 0)
    latest_status = str(telegram.get("latest_status") or "").strip() or "unknown"
    warnings = _verified_fact_warnings(verified_facts)
    citations = _verified_fact_citations(verified_facts)
    names = {str(item or "").strip().lower() for item in skills_used if str(item or "").strip()}

    if specialist.env_key == "FORGE":
        if "ops-snapshot" in names:
            result = (
                f"Operational Meridian snapshot: runtime `{runtime_id}` for `{org_id}` is up, preflight is `{preflight}`, "
                f"SLO is `{slo_status}`, queued alerts `{queued_alerts}`, pending approvals `{pending_approvals}`, and open cases `{open_cases}`. "
                f"Treasury is {treasury_balance} against a reserve floor of {reserve_floor}. "
                f"Payout execution is {'enabled' if bool(verified_facts.get('payout_execution_gate_ok')) else 'blocked'} in phase `{phase_number}` (`{phase_name}`)."
            )
        else:
            result = (
                f"Execution lane should stay constrained to verified Meridian facts. Current live posture is runtime `{runtime_id}`, "
                f"preflight `{preflight}`, SLO `{slo_status}`, treasury {treasury_balance} vs reserve floor {reserve_floor}, "
                f"and payout execution {'enabled' if bool(verified_facts.get('payout_execution_gate_ok')) else 'blocked'}."
            )
    elif specialist.env_key == "PULSE":
        result = (
            f"Compressed Meridian snapshot: `{runtime_id}` on `{org_id}`, preflight `{preflight}`, SLO `{slo_status}`, "
            f"alerts `{queued_alerts}`, approvals `{pending_approvals}`, cases `{open_cases}`, treasury {treasury_balance} vs floor {reserve_floor}, "
            f"Telegram `{delivered}/{checked}` delivered with `{failed}` failed and `{pending}` pending, latest status `{latest_status}`."
        )
    elif specialist.env_key == "QUILL":
        result = (
            "Founder update:\n\n"
            f"Meridian is operating on `{runtime_id}` for `{org_id}` with preflight `{preflight}` and SLO `{slo_status}`. "
            f"There are `{queued_alerts}` queued alerts, `{pending_approvals}` pending approvals, and `{open_cases}` open cases.\n\n"
            f"Treasury is {treasury_balance} against a reserve floor of {reserve_floor}. "
            f"Payouts are {'currently executable' if bool(verified_facts.get('payout_execution_gate_ok')) else 'not executable right now'} "
            f"because the system is in Phase `{phase_number}` (`{phase_name}`)."
        )
        if payout_reason:
            result += f" Execution gate reason: {payout_reason}."
        result += (
            f"\n\nTelegram delivery is currently `{latest_status}` based on the last `{checked}` checked deliveries: "
            f"`{delivered}` delivered, `{failed}` failed, `{pending}` pending."
        )
    elif specialist.env_key == "AEGIS":
        result = (
            "PASS: the bounded Meridian response can be grounded entirely in verified host facts. "
            "Do not claim payout availability beyond the current execution gate. "
            "Do not claim disk pressure, scheduled-job status, or non-Telegram delivery health unless separately verified."
        )
    elif specialist.env_key == "SENTINEL":
        result = (
            f"Risk review: Meridian runtime `{runtime_id}` is live, but treasury headroom is thin at {treasury_balance} against floor {reserve_floor}. "
            f"Payout execution is {'enabled' if bool(verified_facts.get('payout_execution_gate_ok')) else 'blocked'} in phase `{phase_number}` (`{phase_name}`). "
            f"Telegram evidence currently shows `{delivered}/{checked}` delivered."
        )
    else:
        result = (
            f"Verified Meridian facts: runtime `{runtime_id}`, preflight `{preflight}`, SLO `{slo_status}`, "
            f"treasury {treasury_balance} vs floor {reserve_floor}."
        )

    return {
        "agent_id": specialist.registry_id,
        "role": _specialist_role_label(specialist),
        "task_kind": specialist.task_kind,
        "request_id": f"verified-facts::{specialist.registry_id}::{int(time.time())}",
        "session_key": session_key,
        "provider_profile": specialist.profile_name,
        "model": specialist.model,
        "transport_kind": "meridian_verified_fact_playbook",
        "result": result,
        "confidence": "high",
        "citations": citations,
        "warnings": warnings,
        "status": "ok",
        "skills_used": skills_used,
        "raw": {
            "verified_facts": verified_facts,
            "mode": "meridian_verified_fact_playbook",
            "request": request,
        },
    }


def _request_needs_writer(text: str) -> bool:
    lowered = (text or "").strip().lower()
    writer_phrases = (
        "write ",
        "draft ",
        "founder answer",
        "founder note",
        "short answer",
        "short statement",
        "paragraph",
        "message",
    )
    return any(phrase in lowered for phrase in writer_phrases)


def _council_role_instruction(agent_key: str) -> str:
    if agent_key == "ATLAS":
        return (
            "Assess what a real buyer can purchase now, what makes the offer credible, and the top blockers to customer acquisition."
        )
    if agent_key == "SENTINEL":
        return (
            "Attack assumptions, contradictions, and self-deception. Prefer disconfirming evidence over optimism."
        )
    if agent_key == "QUILL":
        return (
            "Write board-style minutes and a resolution that sounds like serious internal human work, not marketing copy."
        )
    if agent_key == "AEGIS":
        return (
            "Separate verified statements from inference, reject unsupported claims, and mark where evidence is too weak."
        )
    if agent_key == "FORGE":
        return (
            "Turn the council decision into a 7-day execution register with proofs of done, not vague advice."
        )
    if agent_key == "PULSE":
        return (
            "Compress consensus, dissent, unresolved questions, and the shortest truthful conclusion."
        )
    return ""


def _run_codex_exec(*, system_prompt: str, user_prompt: str, model: str, timeout: int = REQUEST_TIMEOUT_SECONDS) -> dict[str, Any]:
    return brain_router.execute_manager(
        runtime_env=os.environ,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        timeout=timeout,
    )


def _manager_exec_metadata(model: str = "") -> dict[str, str]:
    return brain_router.manager_exec_metadata(runtime_env=os.environ, model_hint=model)


def _telegram_help_text() -> str:
    return (
        "Telegram conversation surface:\n"
        "/help -> show this help.\n"
        "Any other message goes to Leviathann.\n"
        "Leviathann decides which internal specialists to call and returns the final answer."
    )


def _parse_telegram_command(text: str) -> dict[str, str]:
    stripped = text.strip()
    if not stripped:
        return {"mode": "empty", "arg": ""}
    if stripped == "/help" or stripped.startswith("/help "):
        return {"mode": "help", "arg": stripped[5:].strip()}
    if stripped.startswith("/"):
        parts = stripped.split(None, 1)
        return {"mode": "team", "arg": parts[1].strip() if len(parts) > 1 else stripped}
    return {"mode": "team", "arg": stripped}


def _team_specialist_catalog() -> str:
    lines = []
    for agent in TEAM_TOPOLOGY.specialists:
        lines.append(
            f"- {agent.env_key}: {agent.name} ({agent.role}) -> {agent.purpose}"
        )
    return "\n".join(lines)


def _fallback_team_workers(text: str) -> list[str]:
    workers = ["ATLAS", "AEGIS"]
    if _request_needs_writer(text) and "QUILL" not in workers:
        workers.append("QUILL")
    return _normalize_worker_selection(workers, text)


def _request_has_meeting_execution_details(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    has_contact = "@" in lowered
    has_precise_time = bool(re.search(r"\b([01]?\d|2[0-3])[:h][0-5]\d\b", lowered) or re.search(r"\b([1-9]|1[0-2])\s?(am|pm)\b", lowered))
    has_platform = any(token in lowered for token in ("zoom", "meet", "teams", "calendar", "lịch", "lich"))
    return has_contact and has_precise_time and has_platform


def _request_wants_research_writer(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    writer_cues = (
        "brief",
        "report",
        "memo",
        "battlecard",
        "deck",
        "slide",
        "presentation",
        "document",
        "tài liệu",
        "tai lieu",
        "soạn",
        "viet",
        "write ",
        "draft ",
    )
    return any(cue in lowered for cue in writer_cues)


def _refine_skill_routed_workers(request: str, matched_skills: list[dict[str, Any]], workers: list[str]) -> list[str]:
    lowered_skills = {str(item.get("name") or "").strip().lower() for item in matched_skills}
    selected = _normalize_worker_selection(workers, request)
    if _request_wants_protocol_artifact(request) or any("protocol" in name for name in lowered_skills):
        return _normalize_worker_selection(["QUILL", "AEGIS"], request)
    if "security-questionnaire" in lowered_skills or _request_is_security_questionnaire(request, list(lowered_skills)):
        return _normalize_worker_selection(["ATLAS", "QUILL", "AEGIS"], request)
    if "ai-stack-watch" in lowered_skills or _request_is_ai_stack_watch(request, list(lowered_skills)):
        if not _request_wants_research_writer(request):
            return _normalize_worker_selection(["ATLAS", "AEGIS"], request)
        return _normalize_worker_selection(["ATLAS", "QUILL", "AEGIS"], request)
    if "book-meeting" in lowered_skills and not _request_has_meeting_execution_details(request):
        return _normalize_worker_selection(["QUILL", "AEGIS"], request)
    if "safe-web-research" in lowered_skills or _request_prefers_safe_web_research(request):
        if not _request_wants_research_writer(request):
            return _normalize_worker_selection(["ATLAS", "AEGIS"], request)
        return _normalize_worker_selection(["ATLAS", "QUILL", "AEGIS"], request)
    if "scan-doi-thu" in lowered_skills and not _request_wants_research_writer(request):
        return _normalize_worker_selection(["ATLAS", "AEGIS"], request)
    if _request_is_customer_research(request, list(lowered_skills)):
        if not _request_wants_research_writer(request):
            return _normalize_worker_selection(["ATLAS"], request)
        return _normalize_worker_selection(["ATLAS", "QUILL", "AEGIS"], request)
    return selected


def _specialist_timeout_for_request(agent_key: str, request: str, skills_used: list[str]) -> int:
    lowered_skills = {str(item or "").strip().lower() for item in skills_used}
    if agent_key == "ATLAS" and _request_is_ai_stack_watch(request, skills_used):
        return 28
    if agent_key == "ATLAS" and _request_is_security_questionnaire(request, skills_used):
        return 22
    if agent_key == "ATLAS" and "scan-doi-thu" in lowered_skills:
        return 25
    if agent_key == "ATLAS" and _request_is_customer_research(request, skills_used):
        return 30
    if agent_key == "SENTINEL":
        return 10
    if agent_key == "QUILL" and (
        _request_wants_protocol_artifact(request)
        or any("protocol" in name for name in lowered_skills)
    ):
        return 22
    if agent_key == "AEGIS" and (
        _request_wants_protocol_artifact(request)
        or any("protocol" in name for name in lowered_skills)
    ):
        return 18
    if agent_key == "QUILL" and (
        lowered_skills.intersection({"mail-gui", "book-meeting"})
        or any("follow" in name for name in lowered_skills)
        or _request_is_security_questionnaire(request, skills_used)
        or _request_is_customer_research(request, skills_used)
    ):
        return 30
    if agent_key == "AEGIS" and (
        lowered_skills.intersection({"mail-gui", "book-meeting"})
        or any("follow" in name for name in lowered_skills)
        or _request_is_security_questionnaire(request, skills_used)
        or _request_is_ai_stack_watch(request, skills_used)
        or _request_is_customer_research(request, skills_used)
    ):
        return 25
    if agent_key == "AEGIS" and "scan-doi-thu" in lowered_skills:
        return 20
    if agent_key in {"ATLAS", "QUILL", "PULSE"}:
        return 45
    return 120


def _prefer_direct_provider_first(agent_key: str, request: str, skills_used: list[str]) -> bool:
    lowered_skills = {str(item or "").strip().lower() for item in skills_used}
    fast_lane_skills = {"mail-gui", "book-meeting", "safe-web-research", "security-questionnaire"}
    protocol_lane = _request_wants_protocol_artifact(request) or any("protocol" in name for name in lowered_skills)
    customer_research_lane = any(
        "research" in name and any(token in name for token in ("khach", "customer", "persona", "jtbd", "icp"))
        for name in lowered_skills
    )
    assurance_lane = _request_is_security_questionnaire(request, skills_used)
    return agent_key in {"QUILL", "AEGIS"} and (
        bool(lowered_skills.intersection(fast_lane_skills))
        or any("follow" in name for name in lowered_skills)
        or customer_research_lane
        or assurance_lane
        or protocol_lane
    )


def _direct_provider_timeout_for_request(
    agent_key: str,
    request: str,
    skills_used: list[str],
    specialist_timeout: int,
) -> int:
    if not _prefer_direct_provider_first(agent_key, request, skills_used):
        return max(6, min(specialist_timeout, 15))
    lowered_skills = {str(item or "").strip().lower() for item in skills_used}
    if _request_wants_protocol_artifact(request) or any("protocol" in name for name in lowered_skills):
        return min(12 if agent_key == "QUILL" else 10, max(8, specialist_timeout // 2))
    if (
        lowered_skills.intersection({"mail-gui", "book-meeting"})
        or any("follow" in name for name in lowered_skills)
    ):
        return min(12, max(8, specialist_timeout // 2))
    if _request_is_security_questionnaire(request, skills_used):
        return min(13, max(9, specialist_timeout // 2))
    if "safe-web-research" in lowered_skills or _request_is_customer_research(request, skills_used):
        return min(14, max(10, specialist_timeout // 2))
    return min(15, max(8, specialist_timeout // 2))


def _route_requires_team_execution(request: str, skill_names: list[str]) -> bool:
    lowered_skills = {str(item or "").strip().lower() for item in skill_names if str(item or "").strip()}
    if not request.strip():
        return False
    if _request_wants_protocol_artifact(request):
        return True
    if _request_is_security_questionnaire(request, list(lowered_skills)):
        return True
    if _request_is_ai_stack_watch(request, list(lowered_skills)):
        return True
    if _request_is_customer_research(request, list(lowered_skills)):
        return True
    if _request_prefers_safe_web_research(request):
        return True
    if lowered_skills.intersection(
        {
            "mail-gui",
            "book-meeting",
            "follow-demo-soan",
            "scan-doi-thu",
            "protocol-deal-hoi",
            "mvp-sprint-scope",
            "security-questionnaire",
            "ai-stack-watch",
            "research-khach-hang",
            "ops-snapshot",
            "founder-update",
        }
    ):
        return True
    return False


def _decision_grade_route_score(request: str, skill_bundle: dict[str, Any]) -> dict[str, Any]:
    stripped = str(request or "").strip()
    tokens = _request_tokens(stripped)
    token_count = len(tokens)
    short_prompt = token_count <= 6 and len(stripped.split()) <= 10
    actionable = _request_is_actionable(stripped)
    matched_skills = [dict(item) for item in list(skill_bundle.get("matches") or []) if isinstance(item, dict)]
    skill_names = [str(item.get("name") or "").strip() for item in matched_skills if str(item.get("name") or "").strip()]
    sorted_scores = sorted((int(item.get("score") or 0) for item in matched_skills), reverse=True)
    top_skill_score = sorted_scores[0] if sorted_scores else 0
    second_skill_score = sorted_scores[1] if len(sorted_scores) > 1 else 0
    score_gap = max(0, top_skill_score - second_skill_score)
    top_skill_name = str(matched_skills[0].get("name") or "").strip().lower() if matched_skills else ""
    has_autogenerated_top = bool(matched_skills and matched_skills[0].get("autogenerated"))
    workers_seed = list(skill_bundle.get("workers") or []) or _fallback_team_workers(stripped)
    candidate_workers = _refine_skill_routed_workers(stripped, matched_skills, workers_seed)
    if not candidate_workers:
        candidate_workers = _fallback_team_workers(stripped)
    requires_team_execution = _route_requires_team_execution(stripped, skill_names)
    load_snapshot = _routing_runtime_load_snapshot()
    adaptive_thresholds = _adaptive_route_thresholds(load_snapshot)
    direct_latency_seconds = 6 if short_prompt else 9
    team_worker_latency = sum(
        min(_specialist_timeout_for_request(worker, stripped, skill_names), 35)
        for worker in candidate_workers
    )
    team_latency_seconds = team_worker_latency + 8
    direct_cost_usd = round(0.0006 + (0.00002 * max(token_count, 1)), 6)
    team_cost_usd = round(
        0.0012 * max(len(candidate_workers), 1)
        + (0.00007 * team_latency_seconds)
        + (0.00003 * max(token_count, 1)),
        6,
    )
    direct_score = 50
    team_score = 46
    if requires_team_execution:
        team_score += 24
    if actionable:
        team_score += 6
    else:
        direct_score += 4
    if short_prompt and not actionable:
        direct_score += 16
        team_score -= 6
    if top_skill_score >= 20:
        team_score += 16
    elif top_skill_score >= 12:
        team_score += 10
    elif top_skill_score >= 8:
        team_score += 6
    else:
        direct_score += 12
        team_score -= 4
    if score_gap <= 2:
        direct_score += 8
    elif score_gap >= 6:
        team_score += 4
    if has_autogenerated_top and top_skill_name in {"tra-loi-duy", "ai-intelligence"}:
        direct_score += 8
        team_score -= 6
    if _request_needs_writer(stripped):
        team_score += 4
    latency_delta = max(0, team_latency_seconds - direct_latency_seconds)
    cost_delta = max(0.0, team_cost_usd - direct_cost_usd)
    team_score -= min(24, int(latency_delta / 4))
    team_score -= min(16, int(cost_delta * 1000))
    margin_required = int(
        adaptive_thresholds.get("team_margin_short")
        if short_prompt
        else adaptive_thresholds.get("team_margin_default")
    )
    direct_guard_confidence = int(adaptive_thresholds.get("direct_guard_confidence") or ROUTE_SCORE_DIRECT_GUARD_CONFIDENCE)
    raw_margin = team_score - direct_score
    decision = "team" if raw_margin >= margin_required else "direct"
    confidence = min(99, max(40, int((abs(raw_margin) * 2) + (top_skill_score * 1.5) + (score_gap * 1.5))))
    reason = "balanced"
    if decision == "direct":
        if short_prompt and top_skill_score <= 8:
            reason = "short_ambiguous_low_confidence"
        elif latency_delta >= 20 or cost_delta >= 0.004:
            reason = "latency_cost_guardrail"
        else:
            reason = "direct_is_sufficient"
    elif requires_team_execution:
        reason = "requires_structured_execution"
    return {
        "decision": decision,
        "reason": reason,
        "confidence": confidence,
        "short_prompt": short_prompt,
        "actionable": actionable,
        "requires_team_execution": requires_team_execution,
        "token_count": token_count,
        "top_skill_score": top_skill_score,
        "second_skill_score": second_skill_score,
        "score_gap": score_gap,
        "top_skill_name": top_skill_name,
        "candidate_workers": list(candidate_workers),
        "estimated_direct_latency_seconds": direct_latency_seconds,
        "estimated_team_latency_seconds": team_latency_seconds,
        "estimated_direct_cost_usd": direct_cost_usd,
        "estimated_team_cost_usd": team_cost_usd,
        "direct_score": direct_score,
        "team_score": team_score,
        "margin_required": margin_required,
        "raw_margin": raw_margin,
        "direct_guard_confidence": direct_guard_confidence,
        "load_snapshot": load_snapshot,
        "adaptive_thresholds": adaptive_thresholds,
    }


def _route_decision_trace_payload(
    *,
    session_key: str,
    request: str,
    plan: dict[str, Any],
    routing_score: dict[str, Any],
    skill_names: list[str],
) -> dict[str, Any]:
    adaptive_thresholds = dict(routing_score.get("adaptive_thresholds") or {})
    load_snapshot = dict(routing_score.get("load_snapshot") or {})
    workers = [
        str(item or "").strip().upper()
        for item in list(plan.get("workers") or [])
        if str(item or "").strip()
    ]
    return {
        "schema_version": "route_decision_trace_v1",
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_key": str(session_key or "").strip(),
        "request_text": str(request or "").strip(),
        "skills_used": [str(name or "").strip() for name in skill_names if str(name or "").strip()],
        "route": {
            "mode": str(plan.get("mode") or "").strip(),
            "reason": str(plan.get("reason") or "").strip(),
            "decision": str(routing_score.get("decision") or "").strip(),
            "decision_reason": str(routing_score.get("reason") or "").strip(),
            "confidence": int(routing_score.get("confidence") or 0),
            "direct_score": int(routing_score.get("direct_score") or 0),
            "team_score": int(routing_score.get("team_score") or 0),
            "margin_required": int(routing_score.get("margin_required") or 0),
            "raw_margin": int(routing_score.get("raw_margin") or 0),
            "direct_guard_confidence": int(routing_score.get("direct_guard_confidence") or 0),
            "workers": workers,
            "criteria": str(plan.get("criteria") or "").strip(),
            "depth": str(plan.get("depth") or "").strip(),
            "adaptive_thresholds": {
                "team_margin_short": int(adaptive_thresholds.get("team_margin_short") or 0),
                "team_margin_default": int(adaptive_thresholds.get("team_margin_default") or 0),
                "direct_guard_confidence": int(adaptive_thresholds.get("direct_guard_confidence") or 0),
                "load_tier": str(adaptive_thresholds.get("load_tier") or "").strip(),
                "notes": [str(note or "").strip() for note in list(adaptive_thresholds.get("notes") or []) if str(note or "").strip()],
            },
            "load_snapshot": {
                "pending_count": int(load_snapshot.get("pending_count") or 0),
                "latency_p50_ms": int(load_snapshot.get("latency_p50_ms") or 0),
                "latency_p90_ms": int(load_snapshot.get("latency_p90_ms") or 0),
                "fail_rate": float(load_snapshot.get("fail_rate") or 0.0),
                "latest_status": str(load_snapshot.get("latest_status") or "").strip(),
                "backlog_pressure": int(load_snapshot.get("backlog_pressure") or 0),
            },
            "estimated_direct_latency_seconds": int(routing_score.get("estimated_direct_latency_seconds") or 0),
            "estimated_team_latency_seconds": int(routing_score.get("estimated_team_latency_seconds") or 0),
            "estimated_direct_cost_usd": float(routing_score.get("estimated_direct_cost_usd") or 0.0),
            "estimated_team_cost_usd": float(routing_score.get("estimated_team_cost_usd") or 0.0),
        },
    }


def _record_route_decision_trace(
    *,
    session_key: str,
    request: str,
    plan: dict[str, Any],
    routing_score: dict[str, Any],
    skill_names: list[str],
) -> dict[str, Any]:
    payload = _route_decision_trace_payload(
        session_key=session_key,
        request=request,
        plan=plan,
        routing_score=routing_score,
        skill_names=skill_names,
    )
    trace_id = f"rtrace_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
    payload["trace_id"] = trace_id
    payload["artifact_path"] = str(ROUTE_DECISION_TRACE_PATH)
    try:
        ROUTE_DECISION_TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with ROUTE_DECISION_TRACE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception as exc:
        _log(f"route decision trace append failed: {exc}", color=ANSI_YELLOW)
        return {}
    return {
        "trace_id": trace_id,
        "artifact_path": str(ROUTE_DECISION_TRACE_PATH),
        "schema_version": "route_decision_trace_v1",
    }


def _team_route_plan(text: str, session_key: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {"mode": "direct", "reason": "empty"}
    if stripped.lower() in {"hi", "hello", "hey", "yo", "ping"}:
        return {"mode": "direct", "reason": "greeting"}
    skill_bundle = _skill_bundle_for_request(
        stripped,
        session_key,
        manager_brief=stripped,
        allow_create=True,
    )
    routing_score = _decision_grade_route_score(stripped, skill_bundle)
    route_direct_guard = int(
        routing_score.get("direct_guard_confidence") or ROUTE_SCORE_DIRECT_GUARD_CONFIDENCE
    )
    if _looks_like_meridian_council_query(stripped):
        workers = _normalize_worker_selection(["ATLAS", "SENTINEL", "QUILL", "AEGIS", "FORGE", "PULSE"], stripped)
        return {
            "mode": "team",
            "topic": stripped,
            "depth": "deep",
            "criteria": "readiness",
            "workers": workers,
            "manager_brief": (
                "Run a Meridian council meeting, not a generic answer. "
                "Atlas should assess buyer readiness, product credibility, and why a real outside customer would or would not pay now. "
                "Sentinel should attack contradictions, weak strategic claims, trust gaps, and open-source confusion. "
                "Quill should write human-readable board minutes and a final council resolution. "
                "Aegis should separate verified statements from inference and reject unsupported claims. "
                "Forge should convert the council's consensus into immediate execution priorities and revenue-facing next moves. "
                "Pulse should compress disagreements, unresolved questions, and the final operator summary. "
                "The meeting must include arguments for, objections, consensus, unresolved questions, and immediate decisions."
            ),
            "verified_facts": _build_meridian_council_truth_packet(),
            "reason": "meridian_council_meeting",
            "skills": skill_bundle["matches"],
        }
    if _looks_like_meridian_internal_query(stripped):
        return {
            "mode": "internal_status",
            "topic": stripped,
            "depth": "quick",
            "criteria": "consistency",
            "reason": "meridian_internal_status",
            "skills": skill_bundle["matches"],
        }
    if _looks_like_meridian_operator_workflow_query(stripped):
        workers = _normalize_worker_selection(["FORGE", "QUILL", "AEGIS"], stripped)
        return {
            "mode": "team",
            "topic": stripped,
            "depth": "deep",
            "criteria": "consistency",
            "workers": workers,
            "manager_brief": (
                "Use live Meridian host truth for governance posture. "
                "Forge should draft the operational remediation sequence. "
                "Quill should turn the result into a clear operator/founder-facing brief. "
                "Aegis should reject unsupported claims and flag blocked lanes."
            ),
            "verified_facts": _build_meridian_operator_truth_packet(),
            "reason": "meridian_operator_workflow",
            "skills": skill_bundle["matches"],
        }
    if _looks_like_meridian_positioning_query(stripped):
        workers = _normalize_worker_selection(["QUILL", "AEGIS"], stripped)
        return {
            "mode": "team",
            "topic": stripped,
            "depth": "standard",
            "criteria": "consistency",
            "workers": workers,
            "manager_brief": (
                "Quill should draft a founder-style Meridian positioning answer grounded in the actual Meridian operating model. "
                "Aegis should remove unsupported claims and keep the answer aligned with live Meridian truth."
            ),
            "reason": "meridian_positioning",
            "skills": skill_bundle["matches"],
        }
    if _skill_route_should_activate(stripped, skill_bundle):
        workers = _refine_skill_routed_workers(
            stripped,
            skill_bundle["matches"],
            skill_bundle["workers"] or _fallback_team_workers(stripped),
        )
        top_skill = skill_bundle["matches"][0]
        verified_facts = _skill_route_verified_facts(stripped, skill_bundle["matches"])
        if (
            routing_score.get("decision") == "direct"
            and not bool(routing_score.get("requires_team_execution"))
            and not bool(routing_score.get("actionable"))
            and int(routing_score.get("confidence") or 0) >= route_direct_guard
        ):
            return {
                "mode": "direct",
                "topic": stripped,
                "depth": "quick",
                "criteria": "consistency",
                "workers": [],
                "manager_brief": stripped,
                "reason": "decision_grade_direct_short_ambiguous",
                "skills": skill_bundle["matches"],
                "verified_facts": verified_facts,
                "routing_score": routing_score,
            }
        return {
            "mode": "team",
            "topic": stripped,
            "depth": "standard",
            "criteria": "factual",
            "workers": workers,
            "manager_brief": (
                f"Use the internal skill {top_skill['name']} as guidance, but prioritize the user-facing artifact the request is asking for right now. "
                "Do not drift into product design, system design, or roadmap planning unless the user explicitly asks for that. "
                "If the exact external action is unavailable, still complete the closest executable draft/template/message/plan the user can use immediately, "
                "and state plainly what missing details or access would be required to finish the action for real."
            ),
            "reason": "skill_routed_request",
            "skills": skill_bundle["matches"],
            "verified_facts": verified_facts,
            "routing_score": routing_score,
        }
    if (
        routing_score.get("decision") == "direct"
        and bool(routing_score.get("short_prompt"))
        and not bool(routing_score.get("requires_team_execution"))
        and not bool(routing_score.get("actionable"))
        and int(routing_score.get("confidence") or 0) >= route_direct_guard
    ):
        return {
            "mode": "direct",
            "topic": stripped,
            "depth": "quick",
            "criteria": "consistency",
            "workers": [],
            "manager_brief": stripped,
            "reason": "decision_grade_direct_short_ambiguous",
            "skills": skill_bundle["matches"],
            "routing_score": routing_score,
        }
    history_context = imported_history_context(session_key, loom_root=LOOM_ROOT, limit=24)
    manager = _loom_manager_defaults()
    plan = _run_codex_exec(
        system_prompt=(
            "You are Leviathann, Meridian's manager and orchestrator. "
            "Decide whether to answer directly or delegate to internal specialists. "
            "Return strict JSON only with keys: mode, workers, topic, depth, criteria, manager_brief, reason. "
            "mode must be direct or team. "
            "workers must be an array containing zero or more of: ATLAS, SENTINEL, FORGE, QUILL, AEGIS, PULSE. "
            "depth must be quick, standard, or deep. criteria must be factual, readiness, or consistency. "
            "manager_brief must be a concise execution brief for specialists.\n\n"
            "Specialists:\n"
            f"{_team_specialist_catalog()}\n\n"
            "Available reusable skills:\n"
            f"{TEAM_SKILLS.prompt_block()}"
        ),
        user_prompt=(
            f"Imported conversation continuity for this session:\n{history_context or '(none)'}\n\n"
            f"Matching internal skills for this request:\n{skill_bundle['guidance'] or '(none)'}\n\n"
            f"User request:\n{stripped}"
        ),
        model=manager["model"],
        timeout=min(REQUEST_TIMEOUT_SECONDS, 45),
    )
    payload = _extract_json(plan.get("output_text", "")) if plan.get("ok") else None
    if not isinstance(payload, dict):
        fallback_mode = "team" if str(routing_score.get("decision") or "").strip() == "team" else ("team" if len(stripped.split()) >= 4 else "direct")
        return {
            "mode": fallback_mode,
            "topic": stripped,
            "depth": "standard",
            "criteria": "factual",
            "workers": _fallback_team_workers(stripped) if fallback_mode == "team" else [],
            "manager_brief": stripped,
            "reason": f"planner_fallback_{str(routing_score.get('decision') or '').strip() or 'heuristic'}",
            "skills": skill_bundle["matches"],
            "routing_score": routing_score,
        }
    mode = str(payload.get("mode") or "team").strip().lower()
    if mode not in {"direct", "team"}:
        mode = "team"
    depth = str(payload.get("depth") or "standard").strip().lower()
    if depth not in {"quick", "standard", "deep"}:
        depth = "standard"
    criteria = str(payload.get("criteria") or "factual").strip().lower()
    if criteria not in {"factual", "readiness", "consistency"}:
        criteria = "factual"
    topic = str(payload.get("topic") or stripped).strip() or stripped
    requested_workers = payload.get("workers")
    workers: list[str] = []
    if isinstance(requested_workers, list):
        for item in requested_workers:
            value = str(item or "").strip().upper()
            if value in SPECIALIST_KEYS and value not in workers:
                workers.append(value)
    workers = _normalize_worker_selection(workers, stripped)
    if mode == "team" and not workers:
        workers = _fallback_team_workers(stripped)
    if mode == "team" and _request_needs_writer(stripped) and "QUILL" not in workers:
        workers.append("QUILL")
    planner_reason = str(payload.get("reason") or "").strip()
    if (
        mode == "team"
        and str(routing_score.get("decision") or "").strip() == "direct"
        and bool(routing_score.get("short_prompt"))
        and not bool(routing_score.get("requires_team_execution"))
        and not bool(routing_score.get("actionable"))
        and int(routing_score.get("confidence") or 0) >= route_direct_guard
    ):
        mode = "direct"
        workers = []
        planner_reason = "decision_grade_override_to_direct"
    return {
        "mode": mode,
        "topic": topic,
        "depth": depth,
        "criteria": criteria,
        "workers": workers,
        "manager_brief": str(payload.get("manager_brief") or topic).strip() or topic,
        "reason": planner_reason,
        "skills": skill_bundle["matches"],
        "routing_score": routing_score,
    }


def _manager_direct_response(goal: str, session_key: str, plan: dict[str, Any] | None = None) -> str:
    manager_defaults = _loom_manager_defaults()
    manager_meta = _manager_exec_metadata(manager_defaults.get("model", ""))
    if _looks_like_meridian_internal_query(goal):
        answer = _render_meridian_internal_answer(goal)
        append_session_event(session_key, {
            "history_type": "manager_response",
            "status": "completed",
            "agent_id": TEAM_MANAGER_AGENT_ID,
            "speaker": "manager",
            "text": answer,
            "provider_profile": manager_meta["provider_profile"],
            "model": manager_meta["model"],
            "transport_kind": manager_meta["transport_kind"],
            "auth_mode": manager_meta["auth_mode"],
            "execution_owner": "meridian",
        }, loom_root=LOOM_ROOT)
        return answer
    history_context = imported_history_context(session_key, loom_root=LOOM_ROOT, limit=24)
    memory_context = _memory_context_block(dict(plan or {}).get("memory_packet"))
    trust_evidence_context = _trust_evidence_context_block(dict(plan or {}).get("trust_evidence_packet"))
    result = _run_codex_exec(
        system_prompt=(
            "You are Leviathann, Meridian's manager. "
            "Answer the user directly. Use conversation continuity when relevant. "
            "Do not mention internal specialist routing unless asked. "
            "Use governed memory recall only as bounded context, never as a substitute for verified live facts."
        ),
        user_prompt=(
            f"Governed memory recall:\n{memory_context or '(none)'}\n\n"
            f"Governed trust evidence:\n{trust_evidence_context or '(none)'}\n\n"
            f"Imported conversation continuity:\n{history_context or '(none)'}\n\n"
            f"User request:\n{goal.strip()}"
        ),
        model=manager_defaults["model"],
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if result.get("ok") and str(result.get("output_text") or "").strip():
        answer = str(result.get("output_text") or "").strip()
        result_meta = _manager_exec_metadata(str(result.get("model") or manager_defaults.get("model") or ""))
        append_session_event(session_key, {
            "history_type": "manager_response",
            "status": "completed",
            "agent_id": TEAM_MANAGER_AGENT_ID,
            "speaker": "manager",
            "text": answer,
            "provider_profile": str(result.get("provider_profile") or result_meta["provider_profile"]),
            "model": str(result.get("model") or result_meta["model"]),
            "transport_kind": str(result.get("transport_kind") or result_meta["transport_kind"]),
            "auth_mode": str(result.get("auth_mode") or result_meta["auth_mode"]),
            "execution_owner": "meridian",
        }, loom_root=LOOM_ROOT)
        return answer
    answer = "Unable to complete the request right now."
    append_session_event(session_key, {
        "history_type": "manager_response",
        "status": "failed",
        "agent_id": TEAM_MANAGER_AGENT_ID,
        "speaker": "manager",
        "text": answer,
        "provider_profile": str(result.get("provider_profile") or manager_meta["provider_profile"]),
        "model": str(result.get("model") or manager_meta["model"]),
        "transport_kind": str(result.get("transport_kind") or manager_meta["transport_kind"]),
        "auth_mode": str(result.get("auth_mode") or manager_meta["auth_mode"]),
        "execution_owner": "meridian",
        "warnings": [str(result.get("stderr") or "codex exec failed").strip()],
    }, loom_root=LOOM_ROOT)
    return answer


def _run_specialist_step(agent_key: str, request: str, session_key: str, plan: dict[str, Any]) -> dict[str, Any]:
    specialist = next(agent for agent in TEAM_TOPOLOGY.specialists if agent.env_key == agent_key)
    specialist_role = _specialist_role_label(specialist)
    specialist_purpose = _specialist_purpose_label(specialist)
    def _safe_runtime_context() -> Any:
        try:
            return mcp_server._loom_runtime_context()  # type: ignore[attr-defined]
        except Exception:
            return {}
    context_block = _specialist_history_context(request, session_key, plan)
    verified_facts = plan.get("verified_facts")
    verified_facts_block = json.dumps(verified_facts, indent=2, ensure_ascii=False) if isinstance(verified_facts, dict) else "(none)"
    plan_skills = plan.get("skills") if isinstance(plan.get("skills"), list) else []
    matched_skills = [dict(item) for item in plan_skills if isinstance(item, dict)] or TEAM_SKILLS.search(request, limit=2)
    skill_guidance_block = TEAM_SKILLS.guidance_block(matched_skills)
    skill_execution_addendum = _skill_specific_execution_addendum(request, matched_skills)
    skills_used = [str(item.get("name") or "").strip() for item in matched_skills if str(item.get("name") or "").strip()]
    memory_context_block = _memory_context_block(dict(plan or {}).get("memory_packet"))
    trust_evidence_context_block = _trust_evidence_context_block(dict(plan or {}).get("trust_evidence_packet"))
    council_context_block = _load_council_context() if str(plan.get("reason") or "").strip() == "meridian_council_meeting" else ""
    council_role_block = _council_role_instruction(agent_key) if council_context_block else ""
    if _verified_fact_mode_enabled(request, skills_used, verified_facts) and agent_key != "ATLAS":
        receipt = _verified_fact_worker_receipt(
            specialist,
            request,
            session_key,
            dict(verified_facts or {}),
            skills_used,
        )
        append_session_event(session_key, {
            "history_type": "worker_receipt",
            "status": receipt["status"],
            "agent_id": specialist.registry_id,
            "speaker": "worker",
            "role": specialist_role,
            "task_kind": specialist.task_kind,
            "request_id": receipt["request_id"],
            "provider_profile": specialist.profile_name,
            "model": specialist.model,
            "transport_kind": receipt["transport_kind"],
            "text": receipt["result"],
            "confidence": receipt["confidence"],
            "citations": receipt["citations"],
            "warnings": receipt["warnings"],
            "skills_used": skills_used,
        }, loom_root=LOOM_ROOT)
        return receipt

    if agent_key == "ATLAS" and not _atlas_should_use_internal_analysis(plan, request):
        atlas_timeout = _specialist_timeout_for_request(agent_key, request, skills_used)
        lowered_skill_names = {item.lower() for item in skills_used}
        atlas_memory_block = _atlas_memory_research_block(dict(plan or {}).get("memory_packet"), request, skills_used)
        if "safe-web-research" in lowered_skill_names and _request_prefers_safe_web_research(request):
            safe_url = _extract_request_url(request)
            if not safe_url:
                domain_match = re.search(r"\b[a-z0-9.-]+\.(com|org|net|io|ai|dev|app|co|xyz|vn)(/[^\s]*)?\b", str(request or "").strip(), flags=re.IGNORECASE)
                if domain_match:
                    safe_url = domain_match.group(0)
                    if not safe_url.startswith(("http://", "https://")):
                        safe_url = f"https://{safe_url}"
            safe_fetch = _run_safe_web_fetch(safe_url) if safe_url else {"ok": False, "error": "No public URL was provided."}
            atlas_result = _safe_web_research_artifact(request, safe_fetch)
            atlas_warnings: list[str] = []
            if safe_fetch.get("ok"):
                atlas_warnings.append("safe_text_fetch_completed")
            else:
                atlas_warnings.append(str(safe_fetch.get("error") or "safe_web_fetch_failed").strip())
            receipt = {
                "agent_id": specialist.registry_id,
                "role": specialist_role,
                "task_kind": specialist.task_kind,
                "request_id": "",
                "session_key": session_key,
                "provider_profile": specialist.profile_name,
                "model": specialist.model,
                "transport_kind": "safe_web_fetch",
                "result": atlas_result,
                "confidence": "",
                "citations": [safe_url] if safe_fetch.get("ok") and safe_url else [],
                "warnings": [item for item in atlas_warnings if item],
                "status": "ok" if atlas_result else "error",
                "raw": safe_fetch,
                "skills_used": skills_used,
            }
            append_session_event(session_key, {
                "history_type": "worker_receipt",
                "status": receipt["status"],
                "agent_id": specialist.registry_id,
                "speaker": "worker",
                "role": specialist_role,
                "task_kind": specialist.task_kind,
                "request_id": receipt["request_id"],
                "provider_profile": specialist.profile_name,
                "model": specialist.model,
                "transport_kind": receipt["transport_kind"],
                "text": receipt["result"],
                "confidence": receipt["confidence"],
                "citations": receipt["citations"],
                "warnings": receipt["warnings"],
                "skills_used": skills_used,
            }, loom_root=LOOM_ROOT)
            return receipt
        atlas_research_brief = str(plan.get("topic") or request)
        research_sections = [atlas_research_brief]
        if atlas_memory_block:
            research_sections.append(atlas_memory_block)
        if trust_evidence_context_block and trust_evidence_context_block != "(none)":
            research_sections.append(
                "Governed trust evidence shortlist:\n"
                "Use this only as approved/draft context for trust-facing answers. "
                "Do not invent approvals beyond what is shown.\n"
                f"{trust_evidence_context_block}"
            )
        if skill_guidance_block:
            research_sections.append(skill_guidance_block)
        result = mcp_server.do_on_demand_research_route(
            "\n\n".join(section for section in research_sections if str(section or "").strip()),
            (
                "quick"
                if (
                    "scan-doi-thu" in lowered_skill_names
                    or (
                        _request_is_customer_research(request, skills_used)
                        and not _request_wants_research_writer(request)
                    )
                )
                else str(plan.get("depth") or "standard")
            ),
            agent_id=specialist.registry_id,
            session_id=session_key,
            timeout=atlas_timeout,
        )
        atlas_result = str(result.get("research") or result.get("error") or "").strip()
        atlas_warnings = [str(result.get("error") or "").strip()] if result.get("error") else []
        result_citations = list(result.get("citations") or []) if isinstance(result.get("citations"), list) else []
        if _atlas_result_uses_placeholder_sources(atlas_result):
            atlas_result = ""
            atlas_warnings = [*atlas_warnings, "placeholder_citations_detected_in_research_output"]
        if "scan-doi-thu" in lowered_skill_names and (
            not atlas_result
            or _warning_is_runtime_failure(atlas_result)
            or bool(result.get("error"))
            or _competitor_scan_artifact_needs_salvage(atlas_result)
        ):
            atlas_result = _salvage_competitor_scan_artifact(request)
            if atlas_result:
                atlas_warnings = [*atlas_warnings, "bounded_competitor_scan_salvaged_after_research_failure"]
        if _request_is_customer_research(request, skills_used) and (
            not atlas_result
            or bool(result.get("error"))
            or not result_citations
            or _research_text_contains_unverified_quantification(atlas_result)
            or any(item == "placeholder_citations_detected_in_research_output" for item in atlas_warnings)
        ):
            atlas_result = _salvage_customer_research_artifact(request)
            if atlas_result:
                atlas_warnings = [*atlas_warnings, "customer_research_starter_salvaged_after_unverified_research"]
        receipt = {
            "agent_id": specialist.registry_id,
            "role": specialist_role,
            "task_kind": specialist.task_kind,
            "request_id": str(result.get("job_id") or ""),
            "session_key": session_key,
            "provider_profile": specialist.profile_name,
            "model": specialist.model,
            "transport_kind": "loom_capability",
            "result": atlas_result,
            "confidence": "",
            "citations": [],
            "warnings": [item for item in atlas_warnings if item],
            "status": "ok" if atlas_result else "error",
            "raw": result,
            "skills_used": skills_used,
        }
        append_session_event(session_key, {
            "history_type": "worker_receipt",
            "status": receipt["status"],
            "agent_id": specialist.registry_id,
            "speaker": "worker",
            "role": specialist_role,
            "task_kind": specialist.task_kind,
            "request_id": receipt["request_id"],
            "provider_profile": specialist.profile_name,
            "model": specialist.model,
            "transport_kind": receipt["transport_kind"],
            "text": receipt["result"],
            "confidence": receipt["confidence"],
            "citations": receipt["citations"],
            "warnings": receipt["warnings"],
            "skills_used": skills_used,
        }, loom_root=LOOM_ROOT)
        return receipt

    if agent_key == "AEGIS":
        qa_timeout = _specialist_timeout_for_request(agent_key, request, skills_used)
        prior_steps = list(plan.get("steps") or []) if isinstance(plan.get("steps"), list) else []
        candidate_artifact = _best_usable_step_artifact(prior_steps, request, skills_used)
        qa_sections: list[str] = []
        if candidate_artifact:
            qa_sections.append(f"Candidate artifact to verify:\n{candidate_artifact}")
        else:
            qa_sections.append(f"Original request:\n{request}")
        qa_sections.append(f"Verified Meridian host facts:\n{verified_facts_block}")
        if skill_guidance_block:
            qa_sections.append(skill_guidance_block)
        if skill_execution_addendum:
            qa_sections.append(f"Execution constraints:\n{skill_execution_addendum}")
        lowered_skill_names = {str(item).strip().lower() for item in skills_used}
        if (
            bool(lowered_skill_names.intersection({"mail-gui", "book-meeting"}))
            or any("follow" in name for name in lowered_skill_names)
        ):
            qa_sections.append(
                "For placeholder-based communication drafts, PASS is acceptable when placeholders are explicit, no external send/book action is falsely claimed, and the draft is immediately usable."
            )
        if "scan-doi-thu" in lowered_skill_names:
            qa_sections.append(
                "For bounded competitor scans, PASS is acceptable when verified findings remain clearly separated from explicit unknowns and the next official-source checks are named."
            )
        if "safe-web-research" in lowered_skill_names:
            qa_sections.append(
                "For safe web research, PASS is acceptable when the artifact names the fetched public URL, reports the bounded fetch status or blocked reason truthfully, includes a normalized text excerpt or clearly says none was recovered, and does not claim JS-rendered or hidden content was inspected."
            )
        if _request_is_security_questionnaire(request, skills_used):
            qa_sections.append(
                "For questionnaire packs, PASS is acceptable only when approved evidence, draft answers, and open gaps are clearly separated and no unsupported certification, retention, privacy, or subprocessor claim is presented as fact."
            )
        if _request_is_ai_stack_watch(request, skills_used):
            qa_sections.append(
                "For AI stack watch, PASS is acceptable only when watched changes are bounded to provider/model/pricing/policy/regulatory signals and the trust-answer impact is stated explicitly."
            )
        if _request_is_customer_research(request, skills_used):
            qa_sections.append(
                "For customer research starter packs, PASS is acceptable when the artifact is explicitly labeled hypothesis-led, avoids quantified market claims without verified sources, and ends with concrete interview or validation next steps."
            )
        result = mcp_server.do_qa_verify_route(
            "\n\n".join(section for section in qa_sections if section),
            str(plan.get("criteria") or "factual"),
            agent_id=specialist.registry_id,
            session_id=session_key,
            timeout=qa_timeout,
        )
        receipt = {
            "agent_id": specialist.registry_id,
            "role": specialist_role,
            "task_kind": specialist.task_kind,
            "request_id": str(result.get("job_id") or ""),
            "session_key": session_key,
            "provider_profile": specialist.profile_name,
            "model": specialist.model,
            "transport_kind": str(result.get("transport_kind") or "loom_capability").strip() or "loom_capability",
            "result": str(result.get("verification") or result.get("error") or "").strip(),
            "confidence": str(result.get("confidence") or "").strip(),
            "citations": [],
            "warnings": (
                list(result.get("warnings") or [])
                if isinstance(result.get("warnings"), list)
                else ([str(result.get("error") or "").strip()] if result.get("error") else [])
            ),
            "status": "ok" if not result.get("error") else "error",
            "raw": result,
            "skills_used": skills_used,
        }
        append_session_event(session_key, {
            "history_type": "worker_receipt",
            "status": receipt["status"],
            "agent_id": specialist.registry_id,
            "speaker": "worker",
            "role": specialist_role,
            "task_kind": specialist.task_kind,
            "request_id": receipt["request_id"],
            "provider_profile": specialist.profile_name,
            "model": specialist.model,
            "transport_kind": receipt["transport_kind"],
            "text": receipt["result"],
            "confidence": receipt["confidence"],
            "citations": receipt["citations"],
            "warnings": receipt["warnings"],
            "skills_used": skills_used,
        }, loom_root=LOOM_ROOT)
        return receipt

    prompt = textwrap.dedent(
        f"""
        You are {specialist.name}, Meridian's {specialist_role}.
        Purpose: {specialist_purpose}
        Manager brief: {str(plan.get('manager_brief') or request).strip()}
        Verified Meridian host facts (treat these as the only trusted factual baseline):
        {verified_facts_block}
        Shared council context pack:
        {council_context_block or '(none)'}
        Your council role in this meeting:
        {council_role_block or '(none)'}
        Relevant internal skills:
        {skill_guidance_block or '(none)'}
        Execution constraints for this request:
        {skill_execution_addendum or '(none)'}
        Conversation continuity:
        {context_block or '(none)'}
        Governed memory recall:
        {memory_context_block or '(none)'}
        Governed trust evidence:
        {trust_evidence_context_block or '(none)'}

        User request:
        {request.strip()}

        If the request is underspecified, do not invent recipients, attendees, email addresses, dates, exact times,
        locations, availability, or confirmation state. Return the closest executable draft with placeholders or
        explicit draft/unknown markers, and list the missing fields in warnings.
        Return strict JSON only with keys:
        result, confidence, citations, warnings.
        Do not introduce governance facts, citations, controls, or delivery claims that are not supported by the verified facts above.
        """
    ).strip()
    specialist_timeout = _specialist_timeout_for_request(specialist.env_key, request, skills_used)
    specialist_max_tokens = 900
    if skill_execution_addendum and specialist.env_key == "QUILL":
        specialist_max_tokens = 420
    direct_fallback = None
    fallback_warning = ""
    if _prefer_direct_provider_first(specialist.env_key, request, skills_used):
        direct_provider_timeout = _direct_provider_timeout_for_request(
            specialist.env_key,
            request,
            skills_used,
            specialist_timeout,
        )
        direct_fallback = mcp_server._specialist_direct_provider_fallback(  # type: ignore[attr-defined]
            specialist.registry_id,
            system_prompt=f"You are {specialist.name}. {specialist_purpose}",
            user_prompt=prompt,
            max_tokens=specialist_max_tokens,
            timeout=direct_provider_timeout,
        )
        if direct_fallback.get("ok") and str(direct_fallback.get("output_text") or "").strip():
            loom_result = {
                "ok": True,
                "job_id": "",
                "warnings": ["Fast direct provider lane used for low-latency communication skill."],
            }
            fallback_warning = "Fast direct provider lane used for low-latency communication skill."
        else:
            direct_fallback = None
            loom_timeout = max(8, specialist_timeout - min(direct_provider_timeout, max(specialist_timeout - 6, 0)))
            loom_result = mcp_server._shared_run_loom_capability(  # type: ignore[attr-defined]
                _safe_runtime_context(),
                "loom.llm.inference.v1",
                {
                    "provider_profile": specialist.profile_name,
                    "model": specialist.model,
                    "system_prompt": f"You are {specialist.name}. {specialist_purpose}",
                    "user_prompt": prompt,
                    "max_tokens": specialist_max_tokens,
                },
                timeout=loom_timeout,
                agent_id=specialist.registry_id,
                session_id=session_key,
                action_type=specialist.task_kind,
                resource=session_key,
            )
    else:
        loom_result = mcp_server._shared_run_loom_capability(  # type: ignore[attr-defined]
            _safe_runtime_context(),
            "loom.llm.inference.v1",
            {
                "provider_profile": specialist.profile_name,
                "model": specialist.model,
                "system_prompt": f"You are {specialist.name}. {specialist_purpose}",
                "user_prompt": prompt,
                "max_tokens": specialist_max_tokens,
            },
            timeout=specialist_timeout,
            agent_id=specialist.registry_id,
            session_id=session_key,
            action_type=specialist.task_kind,
            resource=session_key,
        )
    output_text = ""
    worker_result = loom_result.get("worker_result") or {}
    if not isinstance(worker_result, dict) or not worker_result:
        worker_result = _load_runtime_job_result(str(loom_result.get("job_id") or ""))
    host_response = worker_result.get("host_response_json")
    if isinstance(host_response, dict):
        output_text = str(host_response.get("output_text") or "").strip()
    host_decision = str(host_response.get("decision") or "").strip().lower() if isinstance(host_response, dict) else ""
    host_note = str(host_response.get("note") or "").strip() if isinstance(host_response, dict) else ""
    if direct_fallback and direct_fallback.get("ok") and str(direct_fallback.get("output_text") or "").strip():
        output_text = str(direct_fallback.get("output_text") or "").strip()
        host_note = str(direct_fallback.get("note") or host_note)
    payload = _extract_json(output_text) if output_text else None
    if specialist.env_key in {"ATLAS", "QUILL", "PULSE"} and (not output_text or host_decision == "denied" or not loom_result.get("ok")):
        recovery_timeout = min(12, max(6, specialist_timeout // 3))
        direct_fallback = mcp_server._specialist_direct_provider_fallback(  # type: ignore[attr-defined]
            specialist.registry_id,
            system_prompt=f"You are {specialist.name}. {specialist_purpose}",
            user_prompt=prompt,
            max_tokens=specialist_max_tokens,
            timeout=recovery_timeout,
        )
        if direct_fallback.get("ok") and str(direct_fallback.get("output_text") or "").strip():
            output_text = str(direct_fallback.get("output_text") or "").strip()
            payload = _extract_json(output_text) if output_text else None
            fallback_warning = host_note or "Loom host call returned an empty specialist response; direct provider fallback recovered output."
            host_note = str(direct_fallback.get("note") or host_note)
        elif not loom_result.get("error") and host_note:
            loom_result = dict(loom_result)
            loom_result["error"] = host_note
    warnings = (payload or {}).get("warnings") if isinstance((payload or {}).get("warnings"), list) else []
    loom_warnings = loom_result.get("warnings") if isinstance(loom_result.get("warnings"), list) else []
    if loom_warnings:
        warnings = [*warnings, *[str(item).strip() for item in loom_warnings if str(item).strip()]]
    if fallback_warning:
        warnings = [*warnings, fallback_warning]
    elif not loom_result.get("ok"):
        warnings = [str(loom_result.get("error") or "loom failure")]
    elif host_decision == "denied" and host_note:
        warnings = [*warnings, host_note]
    if fallback_warning:
        transport_kind = "direct_provider_http_fallback"
    elif str(loom_result.get("execution_mode") or "").strip() == "direct_action_execute":
        transport_kind = "loom_direct_action_execute"
    else:
        transport_kind = "loom_capability"
    result_text = str((payload or {}).get("result") or output_text or loom_result.get("error") or "").strip()
    lowered_skill_names = {str(item).strip().lower() for item in skills_used}
    if specialist.env_key == "QUILL" and skills_used and (
        _looks_like_scope_document(result_text)
        or any("follow" in name for name in lowered_skill_names)
        or ("book-meeting" in lowered_skill_names and _meeting_output_needs_salvage(result_text))
    ):
        salvaged_artifact = _salvage_user_artifact(request, skills_used)
        if salvaged_artifact:
            result_text = salvaged_artifact
            warnings = [*warnings, "quill_output_drift_rewritten_to_user_artifact"]
    citations, citation_warnings = _sanitize_worker_citations(
        specialist,
        (payload or {}).get("citations"),
        transport_kind=transport_kind,
    )
    if citation_warnings:
        warnings = [*warnings, *citation_warnings]
    receipt = {
        "agent_id": specialist.registry_id,
        "role": specialist_role,
        "task_kind": specialist.task_kind,
        "request_id": str(loom_result.get("job_id") or ""),
        "session_key": session_key,
        "provider_profile": specialist.profile_name,
        "model": specialist.model,
        "transport_kind": transport_kind,
        "result": result_text,
        "confidence": str((payload or {}).get("confidence") or "").strip(),
        "citations": citations,
        "warnings": warnings,
        "status": "ok" if result_text else "error",
        "skills_used": skills_used,
        "raw": {
            "loom_result": loom_result,
            "direct_provider_fallback": direct_fallback,
        } if direct_fallback else loom_result,
    }
    append_session_event(session_key, {
        "history_type": "worker_receipt",
        "status": receipt["status"],
        "agent_id": specialist.registry_id,
        "speaker": "worker",
        "role": specialist_role,
        "task_kind": specialist.task_kind,
        "request_id": receipt["request_id"],
        "provider_profile": specialist.profile_name,
        "model": specialist.model,
        "transport_kind": receipt["transport_kind"],
        "text": receipt["result"],
        "confidence": receipt["confidence"],
        "citations": receipt["citations"],
        "warnings": receipt["warnings"],
        "skills_used": skills_used,
    }, loom_root=LOOM_ROOT)
    return receipt


def _qa_gate_allows_manager_fastpath(steps: list[dict[str, Any]]) -> bool:
    qa_steps = [
        step
        for step in list(steps or [])
        if str(step.get("task_kind") or "").strip() == "qa_gate"
        and _step_effective_status(step) == "ok"
    ]
    if not qa_steps:
        return False
    for step in qa_steps:
        if "fail" in _step_result_text(step).lower():
            return False
        for warning in _step_warning_texts(step):
            if _warning_is_hard_blocker(warning) or _warning_is_runtime_failure(warning):
                return False
    return True


def _manager_fastpath_artifact(
    goal: str,
    steps: list[dict[str, Any]],
    skill_names: list[str],
) -> tuple[str, str]:
    lowered_skill_names = {str(item or "").strip().lower() for item in skill_names}
    best_worker_artifact = _best_usable_step_artifact(steps, goal, skill_names)
    if _request_is_customer_research(goal, skill_names) and not _request_wants_research_writer(goal):
        if best_worker_artifact and _artifact_matches_skill_shape(best_worker_artifact, goal, skill_names):
            return best_worker_artifact, "manager_synthesis_fastpathed_to_best_worker_artifact"
        return _salvage_customer_research_artifact(goal), "manager_synthesis_fastpathed_to_customer_research_starter"
    if (
        _request_is_security_questionnaire(goal, skill_names)
        or _request_is_ai_stack_watch(goal, skill_names)
    ) and best_worker_artifact:
        if _artifact_matches_skill_shape(best_worker_artifact, goal, skill_names):
            return best_worker_artifact, "manager_synthesis_fastpathed_to_best_worker_artifact"
    if not _qa_gate_allows_manager_fastpath(steps):
        return "", ""
    if ("scan-doi-thu" in lowered_skill_names or "safe-web-research" in lowered_skill_names) and best_worker_artifact:
        if _artifact_matches_skill_shape(best_worker_artifact, goal, skill_names):
            return best_worker_artifact, "manager_synthesis_fastpathed_to_best_worker_artifact"
    return "", ""


def _manager_synthesis(goal: str, session_key: str, steps: list[dict[str, Any]], plan: dict[str, Any] | None = None) -> str:
    manager_defaults = _loom_manager_defaults()
    manager_meta = _manager_exec_metadata(manager_defaults.get("model", ""))
    skill_names = [
        str(item.get("name") or "").strip()
        for item in list((plan or {}).get("skills") or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    fastpath_artifact, fastpath_warning = _manager_fastpath_artifact(goal, steps, skill_names)
    if fastpath_artifact:
        append_session_event(session_key, {
            "history_type": "manager_response",
            "status": "completed",
            "agent_id": TEAM_MANAGER_AGENT_ID,
            "speaker": "manager",
            "text": fastpath_artifact,
            "provider_profile": manager_meta["provider_profile"],
            "model": manager_meta["model"],
            "transport_kind": manager_meta["transport_kind"],
            "auth_mode": manager_meta["auth_mode"],
            "execution_owner": "meridian",
            "warnings": [fastpath_warning],
        }, loom_root=LOOM_ROOT)
        return fastpath_artifact

    history_context = imported_history_context(session_key, loom_root=LOOM_ROOT, limit=24)
    cleaned_steps = _manager_step_view(steps)
    verified_facts = {}
    if isinstance(plan, dict) and isinstance(plan.get("verified_facts"), dict):
        verified_facts = dict(plan.get("verified_facts") or {})
    council_context_block = _load_council_context() if isinstance(plan, dict) and str(plan.get("reason") or "").strip() == "meridian_council_meeting" else ""
    response_shape = _manager_response_shape(goal, plan)
    memory_context = _memory_context_block(dict(plan or {}).get("memory_packet"))
    trust_evidence_context = _trust_evidence_context_block(dict(plan or {}).get("trust_evidence_packet"))
    result = _run_codex_exec(
        system_prompt=(
            "You are Leviathann, Meridian's manager. "
            "Given specialist outputs, produce the final user-facing reply. "
            "Resolve conflicts, call out uncertainty, and keep the answer concise but complete. "
            "Treat worker warnings and empty citations as first-class truth. "
            "Verified Meridian host facts are the source of truth over worker claims. "
            "Governed memory recall is useful bounded context, but it never outranks live verified facts or explicit worker warnings. "
            "Do not elevate unsupported marketing claims above the warnings. "
            "If and only if this is an explicit council-style review, write it like real board minutes with explicit disagreement, consensus, unresolved questions, and decisions. "
            "Otherwise, do not use council, board, minutes, consensus, or dissent framing."
        ),
        user_prompt=(
            f"Original user request:\n{goal.strip()}\n\n"
            f"Required response shape:\n{response_shape}\n\n"
            f"Verified Meridian host facts:\n{json.dumps(verified_facts, indent=2, ensure_ascii=False) or '{}'}\n\n"
            f"Governed memory recall:\n{memory_context or '(none)'}\n\n"
            f"Governed trust evidence:\n{trust_evidence_context or '(none)'}\n\n"
            f"Shared council context pack:\n{council_context_block or '(none)'}\n\n"
            f"Imported conversation continuity:\n{history_context or '(none)'}\n\n"
            f"Specialist outputs:\n{json.dumps(cleaned_steps, indent=2, ensure_ascii=False)}"
        ),
        model=manager_defaults["model"],
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if result.get("ok") and str(result.get("output_text") or "").strip():
        answer = str(result.get("output_text") or "").strip()
        result_meta = _manager_exec_metadata(str(result.get("model") or manager_defaults.get("model") or ""))
        append_session_event(session_key, {
            "history_type": "manager_response",
            "status": "completed",
            "agent_id": TEAM_MANAGER_AGENT_ID,
            "speaker": "manager",
            "text": answer,
            "provider_profile": str(result.get("provider_profile") or result_meta["provider_profile"]),
            "model": str(result.get("model") or result_meta["model"]),
            "transport_kind": str(result.get("transport_kind") or result_meta["transport_kind"]),
            "auth_mode": str(result.get("auth_mode") or result_meta["auth_mode"]),
            "execution_owner": "meridian",
        }, loom_root=LOOM_ROOT)
        return answer
    verification_incomplete = any(
        str(item.get("task_kind") or "").strip() in {"verify", "qa_gate"}
        and (
            _step_effective_status(item) != "ok"
            or _step_has_non_informational_warning(item)
            or "timed out" in str(item.get("result") or "").lower()
        )
        for item in steps
    )
    research_unverified = any(
        str(item.get("task_kind") or "").strip() == "research"
        and (
            not item.get("citations")
            or "no verifiable" in str(item.get("result") or "").lower()
            or "could not verify" in str(item.get("result") or "").lower()
        )
        for item in steps
    )
    fallback_artifact = _best_usable_step_artifact(steps, goal, skill_names)
    if fallback_artifact:
        preface: list[str] = []
        if research_unverified:
            preface.append("I could not verify a documented founder quote or external source for this exact rationale.")
        if verification_incomplete:
            preface.append("The verification step did not complete, so treat the answer below as founder positioning rather than a sourced factual claim.")
        if preface:
            fallback_artifact = "\n\n".join([" ".join(preface), fallback_artifact])
        append_session_event(session_key, {
            "history_type": "manager_response",
            "status": "degraded",
            "agent_id": TEAM_MANAGER_AGENT_ID,
            "speaker": "manager",
            "text": fallback_artifact,
            "provider_profile": manager_meta["provider_profile"],
            "model": manager_meta["model"],
            "transport_kind": manager_meta["transport_kind"],
            "auth_mode": manager_meta["auth_mode"],
            "execution_owner": "meridian",
            "warnings": ["manager_synthesis_fallback_to_best_worker_artifact"],
        }, loom_root=LOOM_ROOT)
        return fallback_artifact
    answer = "Unable to complete the managed team response."
    append_session_event(session_key, {
        "history_type": "manager_response",
        "status": "failed",
        "agent_id": TEAM_MANAGER_AGENT_ID,
        "speaker": "manager",
        "text": answer,
        "provider_profile": manager_meta["provider_profile"],
        "model": manager_meta["model"],
        "transport_kind": manager_meta["transport_kind"],
        "auth_mode": manager_meta["auth_mode"],
        "execution_owner": "meridian",
        "warnings": ["manager_synthesis_empty"],
    }, loom_root=LOOM_ROOT)
    return answer


def _run_team_route(text: str, session_key: str, runtime: AgentRuntime) -> tuple[str, dict[str, Any]]:
    parsed = _parse_telegram_command(text)
    mode = parsed["mode"]
    arg = parsed["arg"].strip()
    if mode == "help":
        return _telegram_help_text(), {"mode": "help", "steps": []}
    request = arg or text.strip()
    plan = _team_route_plan(request, session_key)
    skill_names = [
        str(item.get("name") or "").strip()
        for item in list(plan.get("skills") or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    routing_score = dict(plan.get("routing_score") or {})
    route_trace = _record_route_decision_trace(
        session_key=session_key,
        request=request,
        plan=plan,
        routing_score=routing_score,
        skill_names=skill_names,
    )
    if route_trace:
        plan["route_decision_trace"] = dict(route_trace)
    plan["memory_packet"] = _build_memory_packet(request, session_key, skill_names)
    plan["trust_evidence_packet"] = _build_trust_evidence_packet(request, session_key, skill_names)
    manager_defaults = _loom_manager_defaults()
    manager_meta = _manager_exec_metadata(manager_defaults.get("model", ""))
    append_session_event(session_key, {
        "history_type": "manager_plan",
        "status": "planned",
        "agent_id": TEAM_MANAGER_AGENT_ID,
        "speaker": "manager",
        "text": str(plan.get("manager_brief") or request).strip(),
        "workers": list(plan.get("workers") or []),
        "mode": str(plan.get("mode") or ""),
        "criteria": str(plan.get("criteria") or ""),
        "depth": str(plan.get("depth") or ""),
        "provider_profile": manager_meta["provider_profile"],
        "model": manager_meta["model"],
        "transport_kind": manager_meta["transport_kind"],
        "auth_mode": manager_meta["auth_mode"],
        "execution_owner": "meridian",
        "skills_used": skill_names,
        "routing_decision": str(routing_score.get("decision") or "").strip(),
        "routing_confidence": routing_score.get("confidence"),
        "routing_reason": str(routing_score.get("reason") or "").strip(),
        "routing_direct_score": routing_score.get("direct_score"),
        "routing_team_score": routing_score.get("team_score"),
        "routing_margin_required": routing_score.get("margin_required"),
        "routing_raw_margin": routing_score.get("raw_margin"),
        "routing_direct_guard_confidence": routing_score.get("direct_guard_confidence"),
        "routing_load_tier": str(dict(routing_score.get("adaptive_thresholds") or {}).get("load_tier") or "").strip(),
        "routing_load_pending_count": dict(routing_score.get("load_snapshot") or {}).get("pending_count"),
        "routing_load_latency_p50_ms": dict(routing_score.get("load_snapshot") or {}).get("latency_p50_ms"),
        "routing_load_fail_rate": dict(routing_score.get("load_snapshot") or {}).get("fail_rate"),
        "routing_estimated_direct_latency_seconds": routing_score.get("estimated_direct_latency_seconds"),
        "routing_estimated_team_latency_seconds": routing_score.get("estimated_team_latency_seconds"),
        "routing_estimated_direct_cost_usd": routing_score.get("estimated_direct_cost_usd"),
        "routing_estimated_team_cost_usd": routing_score.get("estimated_team_cost_usd"),
        "route_trace_schema_version": str(route_trace.get("schema_version") or "").strip(),
        "route_trace_id": str(route_trace.get("trace_id") or "").strip(),
        "route_trace_artifact_path": str(route_trace.get("artifact_path") or "").strip(),
        "memory_keys": _memory_packet_keys(plan.get("memory_packet")),
        "evidence_keys": _trust_evidence_packet_keys(plan.get("trust_evidence_packet")),
    }, loom_root=LOOM_ROOT)
    if plan.get("mode") == "direct":
        answer = _manager_direct_response(request, session_key, plan=plan)
        memory_outcome = _record_memory_recall_outcome(
            session_key,
            "success" if str(answer or "").strip() else "failure",
            _build_delivery_fingerprint(
                request,
                answer,
                session_key=session_key,
                skill_names=skill_names,
                artifact_source="manager_response",
            ),
            memory_packet=plan.get("memory_packet"),
        )
        if memory_outcome:
            append_session_event(
                session_key,
                {
                    "history_type": "memory_recall_update",
                    "status": memory_outcome.get("quality_status"),
                    "agent_id": TEAM_MANAGER_AGENT_ID,
                    "speaker": "manager",
                    "text": "Updated governed memory recall outcomes for this direct session.",
                    "memory_entries": memory_outcome.get("entries"),
                    "source_label": "governed_memory_retrieval",
                },
                loom_root=LOOM_ROOT,
            )
        return answer, {"mode": "direct", "steps": [], "plan": plan}
    if plan.get("mode") == "internal_status":
        answer = _render_meridian_internal_answer(request)
        return answer, {"mode": "internal_status", "steps": [], "plan": plan}

    steps: list[dict[str, Any]] = []
    final_job_id = ""
    for worker in plan.get("workers") or []:
        plan["steps"] = list(steps)
        step = _run_specialist_step(str(worker), request, session_key, plan)
        steps.append(step)
        final_job_id = str(step.get("request_id") or final_job_id).strip()
    answer = _manager_synthesis(request, session_key, steps, plan)
    skill_names = [str(item.get("name") or "").strip() for item in list(plan.get("skills") or []) if str(item.get("name") or "").strip()]
    lowered_skill_names = {item.strip().lower() for item in skill_names}
    repair_warnings: list[str] = []
    answer, repair_warnings = _repair_manager_answer(request, answer, steps, skill_names)
    questionnaire_outcome: dict[str, Any] | None = None
    if "security-questionnaire" in lowered_skill_names:
        questionnaire_outcome = _apply_security_questionnaire_workflow(
            request,
            session_key,
            skill_names,
            trust_packet=plan.get("trust_evidence_packet"),
        )
        answer = str(dict(questionnaire_outcome).get("rendered_artifact") or answer).strip()
    if "scan-doi-thu" in lowered_skill_names and _competitor_scan_artifact_needs_salvage(answer):
        answer = _salvage_competitor_scan_artifact(request)
        repair_warnings = [*repair_warnings, "bounded_competitor_scan_salvaged_after_research_failure"]
    quality_status, quality_reasons = _assess_skill_quality_outcome(
        steps,
        skill_names,
        final_artifact=answer,
    )
    if repair_warnings:
        quality_reasons = [*quality_reasons, *repair_warnings]
    artifact_source = _artifact_source_from_repairs(repair_warnings)
    delivery_fingerprint = _build_delivery_fingerprint(
        request,
        answer,
        session_key=session_key,
        skill_names=skill_names,
        artifact_source=artifact_source,
    )
    delivery_event = append_session_event(
        session_key,
        {
            "history_type": "manager_delivery_artifact",
            "status": quality_status,
            "agent_id": TEAM_MANAGER_AGENT_ID,
            "speaker": "manager",
            "text": answer,
            "skills_used": skill_names,
            "warnings": quality_reasons,
            "artifact_source": artifact_source,
            "request_text": request,
            "delivery_fingerprint": delivery_fingerprint,
            "final_artifact_usable": _final_artifact_is_usable(answer, skill_names),
            "memory_entries": _memory_packet_delivery_entries(plan.get("memory_packet")),
            "memory_retrieval_mode": str(dict(plan.get("memory_packet") or {}).get("retrieval_mode") or "").strip(),
            "evidence_entries": _trust_evidence_packet_delivery_entries(plan.get("trust_evidence_packet")),
            "evidence_retrieval_mode": str(dict(plan.get("trust_evidence_packet") or {}).get("retrieval_mode") or "").strip(),
            "questionnaire_id": str(dict(questionnaire_outcome or {}).get("questionnaire", {}).get("questionnaire_id") or "").strip(),
            "questionnaire_items": [
                dict(item)
                for item in list(dict(questionnaire_outcome or {}).get("questionnaire", {}).get("questions") or [])
                if isinstance(item, dict)
            ],
            "approval_queue_entries": [
                dict(item)
                for item in list(dict(questionnaire_outcome or {}).get("approval_queue_entries") or [])
                if isinstance(item, dict)
            ],
            "approval_gate_status": str(dict(questionnaire_outcome or {}).get("approval_gate_status") or "").strip(),
            "final_delivery_allowed": bool(dict(questionnaire_outcome or {}).get("final_delivery_allowed")),
            "contributors": _delivery_contributors_snapshot(
                steps,
                request_text=request,
                skill_names=skill_names,
                final_artifact=answer,
            ),
            "provider_profile": TEAM_TOPOLOGY.manager.profile_name,
            "model": TEAM_TOPOLOGY.manager.model,
            "transport_kind": "codex_session",
            "auth_mode": "codex_auth_json",
            "execution_owner": "meridian",
        },
        loom_root=LOOM_ROOT,
    )
    evidence_outcome = _remember_trust_evidence(delivery_event)
    if evidence_outcome:
        append_session_event(
            session_key,
            {
                "history_type": "trust_evidence_update",
                "status": quality_status,
                "agent_id": TEAM_MANAGER_AGENT_ID,
                "speaker": "manager",
                "text": "Updated governed trust evidence from this managed session.",
                "evidence_entries": evidence_outcome,
                "source_label": "governed_trust_evidence",
            },
            loom_root=LOOM_ROOT,
        )
    _remember_successful_delivery_memory(delivery_event)
    memory_outcome = _record_memory_recall_outcome(
        session_key,
        quality_status,
        delivery_fingerprint,
        memory_packet=plan.get("memory_packet"),
    )
    if memory_outcome:
        append_session_event(
            session_key,
            {
                "history_type": "memory_recall_update",
                "status": memory_outcome.get("quality_status"),
                "agent_id": TEAM_MANAGER_AGENT_ID,
                "speaker": "manager",
                "text": "Updated governed memory recall outcomes for this managed session.",
                "memory_entries": memory_outcome.get("entries"),
                "retrieval_mode": memory_outcome.get("retrieval_mode"),
                "source_label": "governed_memory_retrieval",
            },
            loom_root=LOOM_ROOT,
        )
    if skill_names:
        _record_skill_quality(
            skill_names,
            session_key=session_key,
            status=quality_status,
            reasons=quality_reasons,
        )
        append_session_event(
            session_key,
            {
                "history_type": "skill_quality_update",
                "status": quality_status,
                "agent_id": TEAM_MANAGER_AGENT_ID,
                "speaker": "manager",
                "text": f"Updated skill quality for {', '.join(skill_names)} as {quality_status}.",
                "skills_used": skill_names,
                "warnings": quality_reasons,
                "source_label": "live_skill_autonomy",
            },
            loom_root=LOOM_ROOT,
        )
    delivery_event_id = str(dict(delivery_event or {}).get("event_id") or "")
    score_summary = _score_user_session_delivery(session_key, delivery_event_id)
    if score_summary:
        append_session_event(
            session_key,
            {
                "history_type": "economy_score_update",
                "status": "completed",
                "agent_id": TEAM_MANAGER_AGENT_ID,
                "speaker": "manager",
                "text": f"Applied user-session economy scoring for {session_key}.",
                "artifact_source": score_summary.get("artifact_source"),
                "quality_status": score_summary.get("quality_status"),
                "delivery_fingerprint": score_summary.get("delivery_fingerprint"),
                "score_summary": score_summary.get("agents"),
                "court_actions": score_summary.get("court_actions"),
                "skills_used": skill_names,
                "source_label": "live_user_session_scoring",
            },
            loom_root=LOOM_ROOT,
        )
    return answer, {
        "mode": "team",
        "plan": plan,
        "steps": steps,
        "job_id": final_job_id,
    }


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._parts.append(data)

    @property
    def title(self) -> str:
        return " ".join(" ".join(self._parts).split()).strip()


class SkillRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.items: list[dict[str, str]] = []

    @staticmethod
    def _frontmatter_and_body(content: str) -> tuple[dict[str, str], str]:
        match = re.match(r"^---\n(.*?)\n---\n?", content, flags=re.DOTALL)
        if not match:
            return {}, content
        payload: dict[str, str] = {}
        for raw_line in match.group(1).splitlines():
            if ":" not in raw_line:
                continue
            key, value = raw_line.split(":", 1)
            key = key.strip().lower()
            value = value.strip().strip("'\"")
            if key in {"name", "description"} and value:
                payload[key] = value
        return payload, content[match.end() :]

    @staticmethod
    def _frontmatter_category(content: str) -> str:
        match = re.search(r'^\s*category:\s*"([^"]+)"\s*$', content, flags=re.MULTILINE)
        if match:
            return str(match.group(1) or "").strip().lower()
        return ""

    @staticmethod
    def _first_body_line(body: str) -> str:
        for line in body.splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                return stripped
        return ""

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        folded = _ascii_fold(text).lower()
        return {
            token
            for token in re.findall(r"[a-z0-9]+", folded)
            if token and token not in SKILL_STOPWORDS and len(token) > 1
        }

    @staticmethod
    def _body_excerpt(body: str, *, max_lines: int = 12) -> str:
        lines: list[str] = []
        for line in body.splitlines():
            stripped = line.rstrip()
            if not stripped.strip():
                continue
            lines.append(stripped)
            if len(lines) >= max_lines:
                break
        return "\n".join(lines).strip()

    @staticmethod
    def _workers_for_skill(name: str) -> list[str]:
        return list(SKILL_WORKER_HINTS.get((name or "").strip().lower(), []))

    @staticmethod
    def _workers_from_body(body: str) -> list[str]:
        patterns = (
            r"preferred specialists:\s*([A-Z,\s]+)",
            r"suggested workers:\s*([A-Z,\s]+)",
        )
        for pattern in patterns:
            match = re.search(pattern, body or "", flags=re.IGNORECASE)
            if not match:
                continue
            workers: list[str] = []
            for raw in re.split(r"[,\s]+", str(match.group(1) or "").strip()):
                value = str(raw or "").strip().upper()
                if value in SPECIALIST_KEYS and value not in workers:
                    workers.append(value)
            if workers:
                return workers
        return []

    def load(self) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        if not self.root.exists():
            self.items = []
            return self.items
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            rel = str(path.relative_to(self.root))
            if path.suffix.lower() == ".json":
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                name = str(payload.get("name") or path.stem).strip()
                description = str(payload.get("description") or "").strip()
                items.append(
                    {
                        "name": name,
                        "description": description,
                        "capability": str(payload.get("capability") or "").strip(),
                        "source": rel,
                        "path": str(path),
                        "body_excerpt": description,
                        "workers": ",".join(self._workers_for_skill(name)),
                        "autogenerated": bool(payload.get("created_by") == "meridian_skill_autonomy"),
                        "category": str(
                            payload.get("category")
                            or ((payload.get("metadata") or {}).get("category") if isinstance(payload.get("metadata"), dict) else "")
                            or ""
                        ).strip().lower(),
                        "search_tokens": " ".join(
                            sorted(
                                self._tokenize(name)
                                | self._tokenize(description)
                                | set(SKILL_ALIAS_HINTS.get(name.lower(), set()))
                            )
                        ),
                    }
                )
            elif path.suffix.lower() == ".md":
                if path.name != "SKILL.md":
                    continue
                content = path.read_text(encoding="utf-8")
                frontmatter, body = self._frontmatter_and_body(content)
                category = self._frontmatter_category(content)
                name = str(frontmatter.get("name") or path.parent.name or path.stem).strip()
                description = str(frontmatter.get("description") or self._first_body_line(body) or "").strip()
                excerpt = self._body_excerpt(body)
                items.append(
                    {
                        "name": name,
                        "description": description,
                        "capability": "",
                        "source": rel,
                        "path": str(path),
                        "body_excerpt": excerpt,
                        "workers": ",".join(self._workers_for_skill(name) or self._workers_from_body(body)),
                        "autogenerated": "created_by: meridian_skill_autonomy" in content,
                        "category": category,
                        "search_tokens": " ".join(
                            sorted(
                                self._tokenize(name)
                                | self._tokenize(description)
                                | self._tokenize(excerpt)
                                | set(SKILL_ALIAS_HINTS.get(name.lower(), set()))
                            )
                        ),
                    }
                )
        self.items = items
        return self.items

    def search(self, query: str, *, limit: int = 3) -> list[dict[str, Any]]:
        if not self.items:
            self.load()
        query_tokens = self._tokenize(query)
        lowered = (query or "").strip().lower()
        request_category = self._autonomy_category(query)
        matches: list[dict[str, Any]] = []
        for item in self.items:
            hay_tokens = set(str(item.get("search_tokens") or "").split())
            score = 0
            overlap = query_tokens & hay_tokens
            score += len(overlap) * 3
            alias_hits = {
                alias
                for alias in SKILL_ALIAS_HINTS.get(str(item.get("name") or "").strip().lower(), set())
                if alias in lowered
            }
            score += len(alias_hits) * 2
            name = str(item.get("name") or "").strip().lower()
            if name and name in lowered:
                score += 5
            description = str(item.get("description") or "").strip().lower()
            if description and description in lowered:
                score += 4
            category = str(item.get("category") or "").strip().lower()
            if category:
                if category == request_category:
                    score += 4
                elif bool(item.get("autogenerated")) and request_category != "general":
                    score -= 6
            if score < 4:
                continue
            pre_quality_score = score
            quality = _skill_quality_snapshot(str(item.get("name") or "").strip())
            success_count = int(quality.get("success_count") or 0)
            partial_count = int(quality.get("partial_count") or 0)
            failure_count = int(quality.get("failure_count") or 0)
            if pre_quality_score >= 8 or len(overlap) >= 2 or alias_hits or (name and name in lowered):
                score += min(success_count, 3) * 3
                score += min(partial_count, 2)
                score -= min(failure_count, 3) * 2
            match = dict(item)
            match["score"] = score
            match["workers"] = [value for value in str(item.get("workers") or "").split(",") if value]
            match["quality"] = quality
            matches.append(match)
        matches.sort(key=lambda item: (-int(item.get("score") or 0), str(item.get("name") or "")))
        return matches[:limit]

    def guidance_block(self, matches: list[dict[str, Any]], *, limit: int = 2) -> str:
        if not matches:
            return ""
        lines = ["Relevant internal skills:"]
        for item in matches[:limit]:
            description = str(item.get("description") or "").strip()
            excerpt = str(item.get("body_excerpt") or "").strip()
            workers = item.get("workers") if isinstance(item.get("workers"), list) else []
            worker_text = f" | suggested workers: {', '.join(workers)}" if workers else ""
            quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
            quality_text = ""
            if quality:
                last_status = str(quality.get("last_status") or "").strip()
                success_count = int(quality.get("success_count") or 0)
                partial_count = int(quality.get("partial_count") or 0)
                failure_count = int(quality.get("failure_count") or 0)
                quality_text = (
                    f" | quality: last={last_status or 'exploratory'}, "
                    f"s={success_count}, p={partial_count}, f={failure_count}"
                )
            lines.append(f"- {item['name']}: {description}{worker_text}{quality_text}")
            if excerpt:
                lines.append(textwrap.indent(excerpt, "  "))
        return "\n".join(lines).strip()

    @staticmethod
    def _autonomy_category(text: str) -> str:
        if _request_wants_protocol_artifact(text):
            return "planning"
        lowered = str(text or "").lower()
        for category, keywords in AUTONOMY_CATEGORY_KEYWORDS.items():
            if any(keyword in lowered for keyword in keywords):
                return category
        return "general"

    @staticmethod
    def _autonomy_slug(text: str, *, category: str) -> str:
        tokens = [
            token
            for token in re.findall(r"[a-z0-9]+", _ascii_fold(text).lower())
            if token and token not in SKILL_STOPWORDS and len(token) > 1
        ]
        preferred: list[str] = []
        if _request_wants_protocol_artifact(text):
            for candidate in ("protocol", "playbook", "deal", "revive", "hoi", "sinh"):
                if candidate in tokens and candidate not in preferred:
                    preferred.append(candidate)
        for candidate in (
            "follow",
            "followup",
            "demo",
            "email",
            "mail",
            "message",
            "founder",
            "status",
            "update",
            "ops",
            "snapshot",
            "research",
            "khach",
            "customer",
            "persona",
            "jtbd",
            "icp",
            "compare",
            "verify",
            "review",
            "plan",
            "scope",
            "pricing",
            "subscribe",
            "payment",
            "customer",
        ):
            if candidate in tokens and candidate not in preferred:
                preferred.append(candidate)
        parts = preferred[:3] or tokens[:3]
        for token in tokens:
            if token not in parts:
                parts.append(token)
            if len(parts) >= 3:
                break
        if len(parts) < 2 and category not in parts:
            parts = [category, *parts]
        slug = "-".join(parts[:3]).strip("-")
        if not slug:
            slug = f"autonomous-skill-{hashlib.sha1(str(text or '').encode('utf-8')).hexdigest()[:8]}"
        return slug[:48].rstrip("-")

    @staticmethod
    def _autonomy_workers(category: str) -> list[str]:
        return list(AUTONOMY_WORKER_PROFILES.get(category, AUTONOMY_WORKER_PROFILES["general"]))

    @staticmethod
    def _capability_hint_block(category: str) -> str:
        lines = AUTONOMY_CAPABILITY_HINTS.get(category, AUTONOMY_CAPABILITY_HINTS["general"])
        return "\n".join(f"- {line}" for line in lines)

    @staticmethod
    def _skill_example_line(text: str) -> str:
        return f"- {str(text or '').strip()[:180]}".rstrip()

    def _refine_autonomous_skill_file(
        self,
        item: dict[str, Any],
        *,
        request: str,
        session_key: str,
        manager_brief: str = "",
    ) -> bool:
        with SKILL_AUTONOMY_LOCK:
            path = Path(str(item.get("path") or "").strip())
            if not path.exists():
                return False
            content = path.read_text(encoding="utf-8")
            if "created_by: meridian_skill_autonomy" not in content:
                return False
            original_content = content
            category_match = re.search(r'^\s*category:\s*"([^"]+)"\s*$', content, re.MULTILINE)
            category = (
                str(category_match.group(1)).strip().lower()
                if category_match
                else self._autonomy_category(f"{request} {manager_brief}")
            )
            request_category = self._autonomy_category(f"{request} {manager_brief}")
            if category and request_category not in {"", "general"} and category != request_category:
                return False
            request_tokens = self._tokenize(f"{request} {manager_brief}")
            if len(request_tokens & (self._tokenize(str(item.get("name") or "")) | self._tokenize(str(item.get("description") or "")) | self._tokenize(content))) < 2:
                return False
            workers = self._autonomy_workers(category)
            content = re.sub(
                r"(^2\. Route the work through these preferred specialists: ).*$",
                rf"\1{', '.join(workers)}.",
                content,
                flags=re.MULTILINE,
            )
            content = re.sub(
                r"(## Reachable Capability Hints\s*\n\s*)(.*?)(\n## Guardrails)",
                lambda match: (
                    f"{match.group(1)}{self._capability_hint_block(category).strip()}\n\n"
                    f"{match.group(3).lstrip()}"
                ),
                content,
                flags=re.DOTALL,
            )
            line = self._skill_example_line(request or manager_brief)
            if line not in content:
                marker = "## Learned Variations\n"
                if marker in content:
                    content = content.replace(marker, f"{marker}{line}\n", 1)
                else:
                    content = content.rstrip() + textwrap.dedent(
                        f"""

                        ## Learned Variations
                        {line}

                        ## Refinement Notes
                        - Last refined automatically from session `{session_key}`.
                        """
                    )
            normalized_content = content.rstrip() + "\n"
            if normalized_content == original_content.rstrip() + "\n":
                return False
            path.write_text(normalized_content, encoding="utf-8")
            self.load()
            return True

    def create_autonomous_skill(
        self,
        request: str,
        *,
        session_key: str,
        manager_brief: str = "",
    ) -> dict[str, Any] | None:
        with SKILL_AUTONOMY_LOCK:
            raw_request = (request or manager_brief).strip()
            category = self._autonomy_category(f"{request} {manager_brief}")
            workers = self._autonomy_workers(category)
            slug = self._autonomy_slug(raw_request, category=category)
            tokens = list(self._tokenize(raw_request))
            if not tokens:
                return None
            skill_dir = self.root / slug
            if skill_dir.exists():
                self.load()
                existing = next((dict(item) for item in self.items if str(item.get("name") or "") == slug), None)
                if existing and self._refine_autonomous_skill_file(
                    existing,
                    request=request,
                    session_key=session_key,
                    manager_brief=manager_brief,
                ):
                    self.load()
                    existing = next((dict(item) for item in self.items if str(item.get("name") or "") == slug), None)
                    if existing:
                        existing["workers"] = [value for value in str(existing.get("workers") or "").split(",") if value]
                        existing["autogenerated"] = True
                        existing["autonomy_status"] = "refined"
                        return existing
                self.load()
                existing = next((dict(item) for item in self.items if str(item.get("name") or "") == slug), None)
                if existing:
                    existing["workers"] = [value for value in str(existing.get("workers") or "").split(",") if value]
                    existing["autogenerated"] = bool(existing.get("autogenerated"))
                    existing["autonomy_status"] = "reused"
                return existing

            safe_request = raw_request.replace('"', "'")
            description = (
                f"Use when a request like '{safe_request[:80]}' needs a reusable Meridian workflow instead of an ad hoc reply."
            )
            title = " ".join(part.capitalize() for part in slug.split("-")) or "Autonomous Skill"
            capability_hint_block = self._capability_hint_block(category).strip()
            content = "\n".join(
                [
                    "---",
                    f"name: {slug}",
                    f'description: "{description}"',
                    "metadata:",
                    "  created_by: meridian_skill_autonomy",
                    f'  session_key: "{session_key}"',
                    f'  category: "{category}"',
                    "---",
                    "",
                    f"# {title}",
                    "",
                    "Use this skill when the user gives a short prompt such as:",
                    f"- {safe_request}",
                    "",
                    "## Workflow",
                    "",
                    "1. Expand the request into a concrete Meridian task using session continuity and live host facts.",
                    "2. Prioritize the user-facing artifact they asked for, not a broader product or system design deliverable.",
                    f"3. Route the work through these preferred specialists: {', '.join(workers)}.",
                    "4. Search for the closest executable Meridian capability path before giving up.",
                    "5. If required details are missing, return a draft or next-step artifact with explicit placeholders instead of inventing specifics.",
                    "6. If the exact requested transport or external action is unavailable, complete the nearest executable artifact instead of stopping at a refusal.",
                    "7. Keep outputs bounded, operator-usable, and grounded in verified Meridian state.",
                    "8. Return only confirmed facts, explicit unknowns, and the next operational move.",
                    "",
                    "## Reachable Capability Hints",
                    "",
                    capability_hint_block,
                    "",
                    "## Guardrails",
                    "",
                    "- Do not invent missing facts, timelines, or citations.",
                    "- Do not invent recipients, participants, dates, exact times, locations, or confirmation state that the user did not provide.",
                    "- Prefer live Meridian host facts over generic web knowledge.",
                    "- Escalate uncertainty instead of pretending the request is fully specified.",
                    "- If an external transport is unavailable, say that plainly but still finish the best executable part of the job.",
                    "",
                    "## Learned Variations",
                    "",
                    self._skill_example_line(raw_request),
                    "",
                    "## Why Created",
                    "",
                    "- Created automatically because a user request exposed a missing reusable playbook.",
                    f"- Session: {session_key}",
                    "",
                ]
            )
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_path = skill_dir / "SKILL.md"
            skill_path.write_text(content, encoding="utf-8")
            if SKILL_VALIDATOR.exists():
                completed = subprocess.run(
                    ["python3", str(SKILL_VALIDATOR), str(skill_dir)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if completed.returncode != 0:
                    shutil.rmtree(skill_dir, ignore_errors=True)
                    return None
            self.load()
            created = next((dict(item) for item in self.items if str(item.get("name") or "") == slug), None)
            if created is None:
                return None
            created["workers"] = workers
            created["autogenerated"] = True
            created["autonomy_status"] = "created"
            return created

    def prompt_block(self) -> str:
        if not self.items:
            return "- none"
        lines = []
        for item in self.items[:24]:
            detail = item["description"] or item["source"]
            if item["capability"]:
                lines.append(f"- {item['name']}: {detail} (capability: {item['capability']})")
            else:
                lines.append(f"- {item['name']}: {detail}")
        return "\n".join(lines)

def _ascii_fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or "").replace("đ", "d").replace("Đ", "D"))
    return normalized.encode("ascii", "ignore").decode("ascii")


def _request_tokens(text: str) -> list[str]:
    folded = _ascii_fold(text).lower()
    return sorted(
        {
            token
            for token in re.findall(r"[a-z0-9]+", folded)
            if token and token not in SKILL_STOPWORDS and len(token) > 1
        }
    )


def _extract_request_url(text: str) -> str:
    match = re.search(r"https?://[^\s)>\]}\"']+", str(text or "").strip(), flags=re.IGNORECASE)
    return str(match.group(0) or "").strip() if match else ""


def _request_prefers_safe_web_research(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    if _extract_request_url(lowered):
        return True
    scrubbed = re.sub(r"\b[\w.+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", " ", lowered)
    if re.search(r"(?<![\w@.-])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(com|org|net|io|ai|dev|app|co|xyz|vn)(/[^\s]*)?(?![\w@.-])", scrubbed):
        return True
    tokens = set(_request_tokens(lowered))
    if tokens.intersection({"url", "link", "website", "domain", "web", "source", "page", "nguon"}):
        return True
    return any(
        phrase in lowered
        for phrase in (
            "trang web",
            "đọc trang",
            "doc trang",
            "đọc source",
            "doc source",
            "nguồn này",
            "nguon nay",
            "link này",
            "link nay",
            "website này",
            "website nay",
        )
    )


TEAM_SKILLS = SkillRegistry(SKILLS_DIR)
TEAM_SKILLS.load()


def _specialist_history_context(request: str, session_key: str, plan: dict[str, Any]) -> str:
    reason = str(plan.get("reason") or "").strip()
    if reason == "skill_routed_request" and (_short_prompt_skill_candidate(request) or _autonomy_skill_candidate(request)):
        return ""
    limit = 12 if reason == "skill_routed_request" else 20
    return imported_history_context(session_key, loom_root=LOOM_ROOT, limit=limit)


def _load_skill_quality_state() -> dict[str, Any]:
    try:
        if not SKILL_QUALITY_STATE_PATH.exists():
            return {}
        payload = json.loads(SKILL_QUALITY_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_skill_quality_state(payload: dict[str, Any]) -> None:
    try:
        SKILL_QUALITY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        SKILL_QUALITY_STATE_PATH.write_text(
            json.dumps(payload or {}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:
        return


def _skill_quality_snapshot(name: str) -> dict[str, Any]:
    state = _load_skill_quality_state()
    snapshot = state.get(str(name or "").strip(), {})
    return dict(snapshot) if isinstance(snapshot, dict) else {}


def _record_skill_quality(
    skill_names: list[str],
    *,
    session_key: str,
    status: str,
    reasons: list[str] | None = None,
) -> None:
    names = [str(item or "").strip() for item in skill_names if str(item or "").strip()]
    if not names:
        return
    state = _load_skill_quality_state()
    normalized_status = str(status or "partial").strip().lower()
    if normalized_status not in {"success", "partial", "failure"}:
        normalized_status = "partial"
    for name in names:
        record = state.get(name, {})
        if not isinstance(record, dict):
            record = {}
        for counter in ("success_count", "partial_count", "failure_count"):
            record[counter] = int(record.get(counter) or 0)
        record[f"{normalized_status}_count"] += 1
        record["last_status"] = normalized_status
        record["last_session_key"] = session_key
        record["last_recorded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record["last_reasons"] = [str(item).strip() for item in list(reasons or []) if str(item).strip()][:8]
        state[name] = record
    _save_skill_quality_state(state)


USER_SESSION_SCORE_DELTAS = {
    "manager_response": {
        "success": {"main": (6, 5)},
        "partial": {"main": (3, 2)},
        "failure": {"main": (-4, -5)},
    },
    "worker_artifact": {
        "success": {"main": (3, 2)},
        "partial": {"main": (2, 1)},
        "failure": {"main": (-4, -5)},
    },
    "salvage_template": {
        "success": {"main": (5, 4)},
        "partial": {"main": (2, 1)},
        "failure": {"main": (-4, -5)},
    },
}


def _load_user_session_score_state() -> dict[str, Any]:
    path = USER_SESSION_SCORE_STATE_PATH
    if not path.exists():
        return {
            "scored_events": {},
            "scored_fingerprints": {},
            "agent_outcomes": {},
            "court_actions": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "scored_events": {},
            "scored_fingerprints": {},
            "agent_outcomes": {},
            "court_actions": {},
        }
    if not isinstance(payload, dict):
        return {
            "scored_events": {},
            "scored_fingerprints": {},
            "agent_outcomes": {},
            "court_actions": {},
        }
    payload.setdefault("scored_events", {})
    payload.setdefault("scored_fingerprints", {})
    payload.setdefault("agent_outcomes", {})
    payload.setdefault("court_actions", {})
    if not isinstance(payload.get("scored_events"), dict):
        payload["scored_events"] = {}
    if not isinstance(payload.get("scored_fingerprints"), dict):
        payload["scored_fingerprints"] = {}
    if not isinstance(payload.get("agent_outcomes"), dict):
        payload["agent_outcomes"] = {}
    if not isinstance(payload.get("court_actions"), dict):
        payload["court_actions"] = {}
    return payload


def _save_user_session_score_state(state: dict[str, Any]) -> None:
    USER_SESSION_SCORE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_SESSION_SCORE_STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _load_memory_recall_state() -> dict[str, Any]:
    path = MEMORY_RECALL_STATE_PATH
    if not path.exists():
        return {"version": 1, "entries": {}, "session_packets": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "entries": {}, "session_packets": {}}
    if not isinstance(payload, dict):
        return {"version": 1, "entries": {}, "session_packets": {}}
    payload.setdefault("version", 1)
    payload.setdefault("entries", {})
    payload.setdefault("session_packets", {})
    if not isinstance(payload.get("entries"), dict):
        payload["entries"] = {}
    if not isinstance(payload.get("session_packets"), dict):
        payload["session_packets"] = {}
    return payload


def _save_memory_recall_state(state: dict[str, Any]) -> None:
    MEMORY_RECALL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_RECALL_STATE_PATH.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _memory_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _memory_heading_slug(text: str) -> str:
    folded = _ascii_fold(text).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")
    return slug or "general"


def _parse_markdown_memory_sections(markdown: str) -> list[dict[str, Any]]:
    lines = str(markdown or "").splitlines()
    sections: list[dict[str, Any]] = []
    current_heading = ""
    current_lines: list[str] = []
    for raw_line in lines:
        line = str(raw_line or "")
        heading_match = re.match(r"^\s*##\s+(.+?)\s*$", line)
        if heading_match:
            if current_heading or any(item.strip() for item in current_lines):
                content = "\n".join(item.rstrip() for item in current_lines).strip()
                if content:
                    sections.append(
                        {
                            "heading": current_heading or "General",
                            "key": f"section/{_memory_heading_slug(current_heading or 'general')}",
                            "category": "markdown_section",
                            "content": content,
                            "tokens": _request_tokens(f"{current_heading}\n{content}"),
                        }
                    )
            current_heading = heading_match.group(1).strip()
            current_lines = []
            continue
        if current_heading:
            current_lines.append(line)
    if current_heading or any(item.strip() for item in current_lines):
        content = "\n".join(item.rstrip() for item in current_lines).strip()
        if content:
            sections.append(
                {
                    "heading": current_heading or "General",
                    "key": f"section/{_memory_heading_slug(current_heading or 'general')}",
                    "category": "markdown_section",
                    "content": content,
                    "tokens": _request_tokens(f"{current_heading}\n{content}"),
                }
            )
    return sections


def _run_loom_memory_command(args: list[str]) -> dict[str, Any]:
    command = _loom_cli_prefix() + [
        LOOM_BIN,
        "memory",
        *args,
        "--root",
        LOOM_ROOT,
        "--format",
        "json",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "loom memory command failed").strip()
        return {"ok": False, "error": detail}
    parsed = _extract_json_value((completed.stdout or "").strip())
    return {"ok": True, "payload": parsed}


def _memory_entry_skills(entry: dict[str, Any]) -> list[str]:
    return [
        str(item or "").strip().lower()
        for item in list(entry.get("source_skill_names") or [])
        if str(item or "").strip()
    ]


def _memory_support_delivery_fingerprints(record: dict[str, Any]) -> list[str]:
    return [
        str(item or "").strip()
        for item in list(record.get("support_delivery_fingerprints") or [])
        if str(item or "").strip()
    ]


def _memory_inline_digest(text: str, *, limit: int = 220) -> str:
    flattened = re.sub(r"\s+", " ", str(text or "").strip()).strip()
    if len(flattened) <= int(limit or 0):
        return flattened
    return f"{flattened[: max(0, int(limit or 0) - 3)].rstrip()}..."


def _memory_markdown_heading(line: str) -> str:
    cleaned = str(line or "").strip()
    if not cleaned:
        return ""
    if cleaned.startswith("## "):
        return cleaned[3:].strip()
    if cleaned.startswith("**") and cleaned.endswith("**") and len(cleaned) > 4:
        return cleaned.strip("* ").strip()
    if cleaned.endswith(":") and not cleaned.startswith(("-", "*")) and len(cleaned.split()) <= 8:
        return cleaned.rstrip(":").strip()
    return ""


def _compress_successful_output_memory(
    content: str,
    skill_names: list[str] | None = None,
) -> str:
    raw = str(content or "").strip()
    if not raw:
        return ""
    lines = [str(line or "").rstrip() for line in raw.splitlines()]
    sections: list[tuple[str, list[str]]] = []
    current_heading = ""
    current_body: list[str] = []

    def flush_section() -> None:
        nonlocal current_heading, current_body
        if current_heading or any(item.strip() for item in current_body):
            sections.append((current_heading, list(current_body)))
        current_heading = ""
        current_body = []

    for line in lines:
        cleaned = str(line or "").strip()
        if not cleaned:
            continue
        heading = _memory_markdown_heading(cleaned)
        if heading:
            flush_section()
            current_heading = heading
            continue
        current_body.append(cleaned.lstrip("-* ").strip())
    flush_section()

    shortlist: list[str] = []
    for heading, body_lines in sections:
        if not any(item.strip() for item in body_lines):
            continue
        snippets = [_memory_inline_digest(item, limit=110) for item in body_lines if item.strip()]
        if not snippets:
            continue
        shortlist.append(f"{heading}: {' | '.join(snippets[:2])}" if heading else " | ".join(snippets[:2]))
        if len(shortlist) >= 4:
            break
    if not shortlist:
        fallback = [
            _memory_inline_digest(line.lstrip("-* ").strip(), limit=110)
            for line in lines
            if str(line or "").strip()
        ]
        shortlist = [item for item in fallback[:4] if item]
    compressed = "\n".join(f"- {item}" for item in shortlist if item).strip()
    return compressed[:MEMORY_COMPRESSED_OUTPUT_LIMIT].strip()


def _memory_timestamp_epoch(value: Any) -> int:
    raw = str(value or "").strip()
    if not raw:
        return 0
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return int(parsed.timestamp())


def _memory_entry_recency_bonus(entry: dict[str, Any]) -> int:
    timestamp = _memory_timestamp_epoch(
        entry.get("source_recorded_at")
        or entry.get("updated_at")
        or entry.get("last_recalled_at")
    )
    if timestamp <= 0:
        return 0
    age_seconds = max(0, int(time.time()) - int(timestamp))
    if age_seconds <= 6 * 3600:
        return 10
    if age_seconds <= 24 * 3600:
        return 7
    if age_seconds <= 72 * 3600:
        return 4
    if age_seconds <= 7 * 24 * 3600:
        return 2
    return 0


def _memory_entry_last_signal_epoch(entry: dict[str, Any]) -> int:
    return max(
        _memory_timestamp_epoch(entry.get("last_recalled_at")),
        _memory_timestamp_epoch(entry.get("updated_at")),
        _memory_timestamp_epoch(entry.get("source_recorded_at")),
    )


def _refresh_memory_value_score(record: dict[str, Any], *, now_epoch: int | None = None) -> dict[str, Any]:
    current_epoch = int(now_epoch if now_epoch is not None else time.time())
    category = str(record.get("category") or "").strip().lower()
    base_score = int(record.get("accepted_count") or 0) - int(record.get("failure_count") or 0)
    decay_penalty = 0
    if category in {"successful_output", "user_fact"}:
        last_signal_epoch = _memory_entry_last_signal_epoch(record)
        if last_signal_epoch > 0 and current_epoch > last_signal_epoch:
            age_days = max(0, (current_epoch - last_signal_epoch) // 86400)
            decay_after = (
                MEMORY_SUCCESSFUL_OUTPUT_DECAY_AFTER_DAYS
                if category == "successful_output"
                else MEMORY_USER_FACT_DECAY_AFTER_DAYS
            )
            if age_days >= int(decay_after or 0):
                decay_penalty = max(1, int(age_days // max(1, int(decay_after or 1))))
    record["baseline_value_score"] = base_score
    record["value_decay_penalty"] = decay_penalty
    record["memory_value_score"] = base_score - decay_penalty
    record["last_decay_applied_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(current_epoch))
    return record


def _memory_entry_should_evict(record: dict[str, Any], *, now_epoch: int | None = None) -> bool:
    current_epoch = int(now_epoch if now_epoch is not None else time.time())
    category = str(record.get("category") or "").strip().lower()
    if category not in {"successful_output", "user_fact"}:
        return False
    value_score = int(record.get("memory_value_score") or 0)
    if value_score <= int(MEMORY_LOW_VALUE_EVICT_THRESHOLD):
        return True
    last_signal_epoch = _memory_entry_last_signal_epoch(record)
    if last_signal_epoch <= 0 or current_epoch <= last_signal_epoch:
        return False
    age_days = max(0, (current_epoch - last_signal_epoch) // 86400)
    recall_count = int(record.get("recall_count") or 0)
    evict_after = (
        MEMORY_SUCCESSFUL_OUTPUT_EVICT_AFTER_DAYS
        if category == "successful_output"
        else MEMORY_USER_FACT_EVICT_AFTER_DAYS
    )
    if age_days < int(evict_after or 0):
        return False
    if category == "successful_output":
        return recall_count == 0 or value_score <= 0
    return value_score < 0


def _normalize_memory_entries(state: dict[str, Any], *, now_epoch: int | None = None) -> None:
    entries_state = state.setdefault("entries", {})
    current_epoch = int(now_epoch if now_epoch is not None else time.time())
    changed_records: list[dict[str, Any]] = []
    removed_records: list[dict[str, Any]] = []
    for key in list(entries_state):
        record = dict(entries_state.get(key) or {})
        if not record:
            continue
        category = str(record.get("category") or "").strip().lower()
        previous_content = str(record.get("content") or "")
        previous_value = int(record.get("memory_value_score") or 0)
        if category == "successful_output":
            compressed = _compress_successful_output_memory(previous_content, _memory_entry_skills(record))
            if compressed:
                record["content"] = compressed[:MEMORY_COMPRESSED_OUTPUT_LIMIT].strip()
            else:
                record["content"] = previous_content[:MEMORY_COMPRESSED_OUTPUT_LIMIT].strip()
            record["content_format"] = MEMORY_RECALL_ARTIFACT_VERSION
        elif category == "user_fact":
            record["content"] = previous_content[:MEMORY_FACT_CONTENT_LIMIT].strip()
            record["content_format"] = "user_fact_v1"
        else:
            record["content_format"] = str(record.get("content_format") or "markdown_section_v1").strip()
        record["content_hash"] = hashlib.sha256(str(record.get("content") or "").encode("utf-8")).hexdigest()
        _refresh_memory_value_score(record, now_epoch=current_epoch)
        entries_state[key] = record
        if _memory_entry_should_evict(record, now_epoch=current_epoch):
            removed_records.append(record)
            entries_state.pop(key, None)
            continue
        if str(record.get("content") or "") != previous_content or int(record.get("memory_value_score") or 0) != previous_value:
            changed_records.append(record)

    for record in removed_records:
        _memory_remove_entry(record)
    for record in changed_records:
        if str(record.get("category") or "").strip().lower() != "successful_output":
            continue
        _run_loom_memory_command(
            [
                "write",
                "--agent-id",
                MEMORY_RECALL_AGENT_ID,
                "--category",
                str(record.get("category") or "successful_output"),
                "--key",
                str(record.get("key") or "").strip(),
                "--content",
                str(record.get("content") or ""),
                "--source",
                str(record.get("source") or MEMORY_DELIVERY_SOURCE),
            ]
        )


def _memory_remove_entry(record: dict[str, Any]) -> None:
    _run_loom_memory_command(
        [
            "remove",
            "--agent-id",
            MEMORY_RECALL_AGENT_ID,
            "--category",
            str(record.get("category") or "markdown_section"),
            "--key",
            str(record.get("key") or "").strip(),
        ]
    )


def _matching_successful_output_memory_key(
    entries_state: dict[str, Any],
    candidate: dict[str, Any],
) -> str:
    candidate_content = str(candidate.get("content") or "").strip()
    candidate_origin = str(candidate.get("origin_agent") or "").strip().lower()
    candidate_skills = tuple(sorted(_memory_entry_skills(candidate)))
    candidate_key = str(candidate.get("key") or "").strip()
    if not candidate_content:
        return ""
    for existing_key, raw in list(entries_state.items()):
        record = dict(raw or {})
        if str(record.get("category") or "").strip().lower() != "successful_output":
            continue
        if str(existing_key or "").strip() == candidate_key:
            continue
        if str(record.get("content") or "").strip() != candidate_content:
            continue
        if str(record.get("origin_agent") or "").strip().lower() != candidate_origin:
            continue
        if tuple(sorted(_memory_entry_skills(record))) != candidate_skills:
            continue
        return str(existing_key).strip()
    return ""


def _upsert_memory_entry(state: dict[str, Any], entry: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
    key = str(entry.get("key") or "").strip()
    content = str(entry.get("content") or "").strip()
    if not key or not content:
        return None, False
    entries_state = state.setdefault("entries", {})
    record = dict(entries_state.get(key) or {})
    if not isinstance(record, dict):
        record = {}
    previous_hash = str(record.get("content_hash") or "").strip()
    record.setdefault("recall_count", 0)
    record.setdefault("accepted_count", 0)
    record.setdefault("failure_count", 0)
    record["key"] = key
    record["heading"] = str(entry.get("heading") or record.get("heading") or "Memory").strip()
    record["category"] = str(entry.get("category") or record.get("category") or "markdown_section").strip()
    category = str(entry.get("category") or "").strip()
    source_skill_names = [
        str(item or "").strip().lower()
        for item in list(entry.get("source_skill_names") or record.get("source_skill_names") or [])
        if str(item or "").strip()
    ]
    record["source_skill_names"] = source_skill_names
    if category == "successful_output":
        compressed = _compress_successful_output_memory(content, source_skill_names)
        record["content"] = (compressed or content)[:MEMORY_COMPRESSED_OUTPUT_LIMIT].strip()
        record["content_format"] = MEMORY_RECALL_ARTIFACT_VERSION
    elif category == "user_fact":
        record["content"] = content[:MEMORY_FACT_CONTENT_LIMIT]
        record["content_format"] = "user_fact_v1"
    else:
        record["content"] = content
        record["content_format"] = str(entry.get("content_format") or record.get("content_format") or "markdown_section_v1").strip()
    record["tokens"] = list(entry.get("tokens") or [])
    record["source"] = str(entry.get("source") or record.get("source") or MEMORY_RECALL_SOURCE).strip()
    record["source_session_key"] = str(entry.get("source_session_key") or record.get("source_session_key") or "").strip()
    record["source_event_id"] = str(entry.get("source_event_id") or record.get("source_event_id") or "").strip()
    record["source_quality_status"] = str(entry.get("source_quality_status") or record.get("source_quality_status") or "").strip().lower()
    record["source_recorded_at"] = str(entry.get("source_recorded_at") or record.get("source_recorded_at") or "").strip()
    record["artifact_source"] = str(entry.get("artifact_source") or record.get("artifact_source") or "").strip().lower()
    record["origin_agent"] = str(entry.get("origin_agent") or record.get("origin_agent") or "").strip().lower()
    record["origin_task_kind"] = str(entry.get("origin_task_kind") or record.get("origin_task_kind") or "").strip().lower()
    record["origin_delivery_fingerprint"] = str(
        entry.get("origin_delivery_fingerprint") or record.get("origin_delivery_fingerprint") or ""
    ).strip()
    if category == "successful_output":
        merged_key = _matching_successful_output_memory_key(entries_state, record)
        if merged_key:
            existing_record = dict(entries_state.get(merged_key) or {})
            preserved_counts = {
                "recall_count": int(existing_record.get("recall_count") or 0),
                "accepted_count": int(existing_record.get("accepted_count") or 0),
                "failure_count": int(existing_record.get("failure_count") or 0),
                "support_delivery_fingerprints": _memory_support_delivery_fingerprints(existing_record),
            }
            existing_record.update(record)
            existing_record.update(preserved_counts)
            record = existing_record
            key = merged_key
            record["key"] = key
        support_fingerprints = _memory_support_delivery_fingerprints(record)
        current_fingerprint = str(record.get("origin_delivery_fingerprint") or "").strip()
        if current_fingerprint and current_fingerprint not in support_fingerprints:
            support_fingerprints.append(current_fingerprint)
            record["accepted_count"] = int(record.get("accepted_count") or 0) + 1
        elif not support_fingerprints and str(record.get("source_quality_status") or "").strip().lower() == "success":
            record["accepted_count"] = max(1, int(record.get("accepted_count") or 0))
        record["support_delivery_fingerprints"] = support_fingerprints[-16:]
    record["updated_at"] = _memory_now_iso()
    record["content_hash"] = hashlib.sha256(record["content"].encode("utf-8")).hexdigest()
    _refresh_memory_value_score(record)
    changed = previous_hash != str(record.get("content_hash") or "").strip()
    entries_state[key] = record
    return record, changed


def _memory_best_origin_contributor_details(
    contributors: list[dict[str, Any]],
    *,
    task_kinds: set[str] | None = None,
    min_fit_score: int = 32,
) -> tuple[str, str]:
    best_agent = ""
    best_task_kind = ""
    best_score = -1000
    for contributor in contributors:
        agent_key = str(contributor.get("economy_key") or "").strip().lower()
        if not agent_key:
            continue
        task_kind = str(contributor.get("task_kind") or "").strip().lower()
        if task_kinds and task_kind not in task_kinds:
            continue
        if str(contributor.get("status") or "").strip().lower() != "ok":
            continue
        fit_score = int(contributor.get("artifact_fit_score") or -100)
        support_level = _contributor_support_level(contributor)
        drift_rewritten = bool(contributor.get("drift_rewritten"))
        if drift_rewritten and not (
            task_kind == "write"
            and bool(contributor.get("artifact_matches_shape"))
            and fit_score >= 48
            and support_level in {"primary", "supporting"}
        ):
            continue
        effective_min_fit = int(min_fit_score)
        if task_kind == "research" and bool(contributor.get("best_fit_contributor")):
            effective_min_fit = min(effective_min_fit, 24)
        if fit_score < effective_min_fit and support_level == "none":
            continue
        score = fit_score
        if bool(contributor.get("matches_final_artifact")):
            score += 80
        elif support_level == "primary":
            score += 50
        elif bool(contributor.get("best_fit_contributor")):
            score += 25
        if task_kind == "research":
            score += 8
        elif task_kind == "write":
            score += 4
        elif task_kind == "execute":
            score += 6
        elif task_kind in {"verify", "qa_gate"}:
            score += 2
        elif task_kind == "compress":
            score += 1
        if bool(contributor.get("usable_artifact")):
            score += 4
        if drift_rewritten:
            score -= 12
        if score > best_score:
            best_score = score
            best_agent = agent_key
            best_task_kind = task_kind
    return best_agent, best_task_kind


def _memory_best_origin_contributor(
    contributors: list[dict[str, Any]],
    *,
    task_kinds: set[str] | None = None,
    min_fit_score: int = 32,
) -> str:
    best_agent, _ = _memory_best_origin_contributor_details(
        contributors,
        task_kinds=task_kinds,
        min_fit_score=min_fit_score,
    )
    return best_agent


def _memory_preferred_origin_task_groups(
    request: str,
    skill_names: list[str] | None = None,
) -> list[tuple[set[str], int]]:
    lowered_skills = {str(item or "").strip().lower() for item in list(skill_names or []) if str(item or "").strip()}
    groups: list[tuple[set[str], int]] = []
    if _request_is_customer_research(request, list(lowered_skills)) or lowered_skills.intersection({"scan-doi-thu", "safe-web-research"}):
        groups.append(({"research"}, 24))
    if (
        _request_needs_writer(request)
        or _request_wants_protocol_artifact(request)
        or lowered_skills.intersection({"mail-gui", "follow-demo-soan", "book-meeting", "protocol-deal-hoi"})
    ):
        groups.append(({"write"}, 26))
    if lowered_skills.intersection({"ops-snapshot"}):
        groups.append(({"execute"}, 18))
        groups.append(({"compress"}, 24))
        groups.append(({"verify", "qa_gate"}, 28))
    groups.append(({"write", "execute", "research", "verify", "qa_gate", "compress"}, 42))
    return groups


def _memory_delivery_origin_details(delivery_event: dict[str, Any]) -> tuple[str, str]:
    artifact_source = str(delivery_event.get("artifact_source") or "").strip().lower()
    contributors = [item for item in list(delivery_event.get("contributors") or []) if isinstance(item, dict)]
    if artifact_source == "salvage_template":
        return str(TEAM_TOPOLOGY.manager.handle or "").strip().lower(), "manage"
    request_text = str(delivery_event.get("request_text") or "").strip()
    skill_names = [str(item or "").strip().lower() for item in list(delivery_event.get("skills_used") or []) if str(item or "").strip()]
    if artifact_source == "manager_response":
        for task_kinds, min_fit_score in _memory_preferred_origin_task_groups(request_text, skill_names):
            origin_agent, origin_task_kind = _memory_best_origin_contributor_details(
                contributors,
                task_kinds=task_kinds,
                min_fit_score=min_fit_score,
            )
            if origin_agent:
                return origin_agent, origin_task_kind
        return str(TEAM_TOPOLOGY.manager.handle or "").strip().lower(), "manage"
    origin_agent, origin_task_kind = _memory_best_origin_contributor_details(contributors)
    return origin_agent, origin_task_kind


def _memory_delivery_origin_agent(delivery_event: dict[str, Any]) -> str:
    origin_agent, _ = _memory_delivery_origin_details(delivery_event)
    return origin_agent


def _delivery_memory_entry_from_event(delivery_event: Any) -> dict[str, Any] | None:
    if not isinstance(delivery_event, dict):
        return None
    if str(delivery_event.get("status") or "").strip().lower() != "success":
        return None
    if not bool(delivery_event.get("final_artifact_usable")):
        return None
    request_text = str(delivery_event.get("request_text") or "").strip()
    skill_names = [str(item).strip().lower() for item in list(delivery_event.get("skills_used") or []) if str(item).strip()]
    raw_text = str(delivery_event.get("text") or "").strip()
    if not raw_text:
        return None
    artifact = _coerce_request_specific_artifact(raw_text, request_text) if request_text else raw_text
    if not artifact:
        return None
    if skill_names and request_text and not _artifact_matches_skill_shape(artifact, request_text, skill_names):
        return None
    compressed_artifact = _compress_successful_output_memory(artifact, skill_names)
    if not compressed_artifact:
        return None
    delivery_fingerprint = str(delivery_event.get("delivery_fingerprint") or "").strip()
    if not delivery_fingerprint:
        return None
    heading_label = ", ".join(skill_names[:2]) if skill_names else "general"
    origin_agent, origin_task_kind = _memory_delivery_origin_details(delivery_event)
    return {
        "key": f"delivery/{delivery_fingerprint}",
        "heading": f"Successful output: {heading_label}",
        "category": "successful_output",
        "content": compressed_artifact,
        "content_format": MEMORY_RECALL_ARTIFACT_VERSION,
        "tokens": _request_tokens(f"{request_text}\n{' '.join(skill_names)}\n{artifact[:MEMORY_DELIVERY_CONTENT_LIMIT]}"),
        "source": MEMORY_DELIVERY_SOURCE,
        "source_session_key": str(delivery_event.get("session_key") or "").strip(),
        "source_event_id": str(delivery_event.get("event_id") or "").strip(),
        "source_quality_status": "success",
        "source_recorded_at": str(delivery_event.get("recorded_at") or "").strip(),
        "artifact_source": str(delivery_event.get("artifact_source") or "").strip().lower(),
        "origin_agent": origin_agent,
        "origin_task_kind": origin_task_kind,
        "source_skill_names": skill_names,
        "origin_delivery_fingerprint": delivery_fingerprint,
    }


def _memory_history_events_dir() -> Path:
    return Path(LOOM_ROOT) / "state" / "session-history" / "events"


def _sync_successful_output_memory(state: dict[str, Any]) -> None:
    events_dir = _memory_history_events_dir()
    if not events_dir.exists():
        return
    history_files = sorted(
        events_dir.glob("*.json"),
        key=lambda item: item.stat().st_mtime_ns,
        reverse=True,
    )[: max(8, MEMORY_HISTORY_SCAN_LIMIT)]
    history_state = state.setdefault("history_sync", {})
    seen_event_ids = [str(item).strip() for item in list(history_state.get("event_ids") or []) if str(item).strip()]
    seen_set = set(seen_event_ids)
    max_mtime_ns = max((item.stat().st_mtime_ns for item in history_files), default=0)
    if int(history_state.get("source_mtime_ns") or 0) == int(max_mtime_ns) and seen_event_ids:
        return

    changed_records: list[dict[str, Any]] = []
    for path in history_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for event in list(payload.get("events") or []):
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("event_id") or "").strip()
            if not event_id or event_id in seen_set:
                continue
            if str(event.get("history_type") or "").strip() != "manager_delivery_artifact":
                continue
            entry = _delivery_memory_entry_from_event(event)
            if not entry:
                continue
            record, changed = _upsert_memory_entry(state, entry)
            if record and changed:
                changed_records.append(record)
            seen_event_ids.append(event_id)
            seen_set.add(event_id)

    for record in changed_records:
        _run_loom_memory_command(
            [
                "write",
                "--agent-id",
                MEMORY_RECALL_AGENT_ID,
                "--category",
                str(record.get("category") or "successful_output"),
                "--key",
                str(record.get("key") or "").strip(),
                "--content",
                str(record.get("content") or ""),
                "--source",
                str(record.get("source") or MEMORY_DELIVERY_SOURCE),
            ]
        )

    history_state["source_mtime_ns"] = int(max_mtime_ns)
    history_state["event_ids"] = seen_event_ids[-600:]


def _remember_successful_delivery_memory(delivery_event: Any) -> None:
    entry = _delivery_memory_entry_from_event(delivery_event)
    if not entry:
        return
    state = _load_memory_recall_state()
    record, changed = _upsert_memory_entry(state, entry)
    _normalize_memory_entries(state)
    _prune_memory_entries(state)
    _save_memory_recall_state(state)
    if record and changed:
        _run_loom_memory_command(
            [
                "write",
                "--agent-id",
                MEMORY_RECALL_AGENT_ID,
                "--category",
                str(record.get("category") or "successful_output"),
                "--key",
                str(record.get("key") or "").strip(),
                "--content",
                str(record.get("content") or ""),
                "--source",
                str(record.get("source") or MEMORY_DELIVERY_SOURCE),
            ]
        )


def _extract_request_user_fact_entries(request: str, session_key: str) -> list[dict[str, Any]]:
    text = str(request or "").strip()
    if not text:
        return []
    entries: list[dict[str, Any]] = []
    lowered = _ascii_fold(text).lower()

    email_matches = sorted(
        {
            match.strip().lower()
            for match in re.findall(r"\b[\w.+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", lowered, flags=re.IGNORECASE)
        }
    )
    for email in email_matches:
        entries.append(
            {
                "key": f"fact/email/{hashlib.sha1(email.encode('utf-8')).hexdigest()[:12]}",
                "heading": "User Contact",
                "category": "user_fact",
                "content": f"User contact email: {email}",
                "tokens": _request_tokens(f"user contact email {email} {text}"),
                "source": MEMORY_FACT_SOURCE,
                "source_session_key": session_key,
                "source_quality_status": "explicit",
                "source_recorded_at": _memory_now_iso(),
            }
        )

    founder_markers = (
        "toi la founder",
        "toi la nguoi sang lap",
        "i am the founder",
        "i'm the founder",
        "im the founder",
    )
    if any(marker in lowered for marker in founder_markers):
        entries.append(
            {
                "key": "fact/identity/founder",
                "heading": "User Identity",
                "category": "user_fact",
                "content": "The user is the founder.",
                "tokens": _request_tokens(f"user founder identity {text}"),
                "source": MEMORY_FACT_SOURCE,
                "source_session_key": session_key,
                "source_quality_status": "explicit",
                "source_recorded_at": _memory_now_iso(),
            }
        )

    name_match = re.search(
        r"(?:\btoi ten la\b|\bmy name is\b|\bcall me\b)\s+([a-z0-9 _-]{2,48})",
        lowered,
        flags=re.IGNORECASE,
    )
    if name_match:
        candidate = re.sub(r"\s+", " ", str(name_match.group(1) or "").strip()).strip(" .,:;")
        if candidate:
            entries.append(
                {
                    "key": f"fact/name/{hashlib.sha1(candidate.encode('utf-8')).hexdigest()[:12]}",
                    "heading": "User Name",
                    "category": "user_fact",
                    "content": f"User prefers the name: {candidate}",
                    "tokens": _request_tokens(f"user name {candidate} {text}"),
                    "source": MEMORY_FACT_SOURCE,
                    "source_session_key": session_key,
                    "source_quality_status": "explicit",
                    "source_recorded_at": _memory_now_iso(),
                }
            )
    return entries


def _sync_request_user_fact_memory(state: dict[str, Any], request: str, session_key: str) -> None:
    changed_records: list[dict[str, Any]] = []
    for entry in _extract_request_user_fact_entries(request, session_key):
        record, changed = _upsert_memory_entry(state, entry)
        if record and changed:
            changed_records.append(record)
    for record in changed_records:
        _run_loom_memory_command(
            [
                "write",
                "--agent-id",
                MEMORY_RECALL_AGENT_ID,
                "--category",
                str(record.get("category") or "user_fact"),
                "--key",
                str(record.get("key") or "").strip(),
                "--content",
                str(record.get("content") or ""),
                "--source",
                str(record.get("source") or MEMORY_FACT_SOURCE),
            ]
        )


def _prune_memory_entries(state: dict[str, Any]) -> None:
    entries_state = state.setdefault("entries", {})
    categories = {
        "user_fact": MEMORY_USER_FACT_LIMIT,
        "successful_output": MEMORY_SUCCESSFUL_OUTPUT_LIMIT,
    }
    for category, limit in categories.items():
        items = [
            dict(item)
            for item in list(entries_state.values())
            if isinstance(item, dict) and str(item.get("category") or "").strip() == category
        ]
        items.sort(
            key=lambda item: (
                int(item.get("memory_value_score") or 0),
                _memory_timestamp_epoch(item.get("last_recalled_at") or item.get("updated_at") or item.get("source_recorded_at")),
            ),
            reverse=True,
        )
        for record in items[int(limit):]:
            key = str(record.get("key") or "").strip()
            if not key:
                continue
            _memory_remove_entry(record)
            entries_state.pop(key, None)


def _sync_memory_retrieval_index() -> dict[str, Any]:
    markdown = MEMORY_PATH.read_text(encoding="utf-8").strip()
    source_mtime_ns = MEMORY_PATH.stat().st_mtime_ns if MEMORY_PATH.exists() else 0
    sections = _parse_markdown_memory_sections(markdown)
    state = _load_memory_recall_state()
    entries_state = state.setdefault("entries", {})
    retained_keys: set[str] = set()
    changed_keys: list[str] = []
    for section in sections:
        key = str(section.get("key") or "").strip()
        heading = str(section.get("heading") or "").strip() or "General"
        content = str(section.get("content") or "").strip()
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        retained_keys.add(key)
        record = dict(entries_state.get(key) or {})
        if not isinstance(record, dict):
            record = {}
        previous_hash = str(record.get("content_hash") or "").strip()
        record.setdefault("recall_count", 0)
        record.setdefault("accepted_count", 0)
        record.setdefault("failure_count", 0)
        record["key"] = key
        record["heading"] = heading
        record["category"] = str(section.get("category") or "markdown_section").strip()
        record["content"] = content
        record["tokens"] = list(section.get("tokens") or [])
        record["content_hash"] = content_hash
        record["source"] = MEMORY_RECALL_SOURCE
        record["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record["content_format"] = "markdown_section_v1"
        _refresh_memory_value_score(record)
        entries_state[key] = record
        if content_hash != previous_hash:
            changed_keys.append(key)
    stale_keys = [key for key in list(entries_state) if key not in retained_keys]
    for key in stale_keys:
        stale_record = dict(entries_state.get(key) or {})
        _run_loom_memory_command(
            [
                "remove",
                "--agent-id",
                MEMORY_RECALL_AGENT_ID,
                "--category",
                str(stale_record.get("category") or "markdown_section"),
                "--key",
                key,
            ]
        )
        entries_state.pop(key, None)
    if int(state.get("source_mtime_ns") or 0) != int(source_mtime_ns) or changed_keys:
        for key in changed_keys:
            record = dict(entries_state.get(key) or {})
            _run_loom_memory_command(
                [
                    "write",
                    "--agent-id",
                    MEMORY_RECALL_AGENT_ID,
                    "--category",
                    str(record.get("category") or "markdown_section"),
                    "--key",
                    str(record.get("key") or "").strip(),
                    "--content",
                    str(record.get("content") or ""),
                    "--source",
                    MEMORY_RECALL_SOURCE,
                ]
            )
    _sync_successful_output_memory(state)
    _normalize_memory_entries(state)
    _prune_memory_entries(state)
    state["source_mtime_ns"] = int(source_mtime_ns)
    state["updated_at"] = _memory_now_iso()
    _save_memory_recall_state(state)
    return state


def _memory_entry_score(
    entry: dict[str, Any],
    request: str,
    skill_names: list[str] | None = None,
    *,
    session_key: str = "",
) -> int:
    request_tokens = set(_request_tokens(request))
    entry_tokens = {str(item).strip().lower() for item in list(entry.get("tokens") or []) if str(item).strip()}
    overlap = request_tokens & entry_tokens
    heading = str(entry.get("heading") or "").strip().lower()
    category = str(entry.get("category") or "").strip().lower()
    content_lowered = _ascii_fold(str(entry.get("content") or "")).lower()
    lowered_skills = {str(item or "").strip().lower() for item in list(skill_names or []) if str(item or "").strip()}
    source_skills = set(_memory_entry_skills(entry))
    score = len(overlap) * 8
    if category == "markdown_section":
        if any(token in heading for token in ("founder", "mission")):
            score += 3
    if lowered_skills.intersection({"protocol-deal-hoi", "research-khach-hang", "scan-doi-thu"}):
        if category == "markdown_section" and any(token in heading for token in ("founder", "mission")):
            score += 5
    if lowered_skills.intersection({"mail-gui", "follow-demo-soan", "book-meeting"}):
        if category == "markdown_section" and "founder" in heading:
            score += 2
    if category == "user_fact":
        email_matches = re.findall(r"\b[\w.+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", content_lowered, flags=re.IGNORECASE)
        if overlap:
            score += 12
        if email_matches and any(email in _ascii_fold(request).lower() for email in email_matches):
            score += 16
        if "founder" in content_lowered and request_tokens.intersection({"founder", "positioning", "buyer", "mission"}):
            score += 8
    elif category == "successful_output":
        if overlap:
            score += 6
        if lowered_skills and source_skills.intersection(lowered_skills):
            score += 20
        elif lowered_skills and source_skills:
            score -= 40
        if session_key and str(entry.get("source_session_key") or "").strip() == str(session_key or "").strip():
            score += 6
        if _request_wants_protocol_artifact(request) and source_skills.intersection({"protocol-deal-hoi"}):
            score += 10
        if _request_is_customer_research(request, list(skill_names or [])) and source_skills.intersection({"research-khach-hang"}):
            score += 10
        if "scan-doi-thu" in lowered_skills and source_skills.intersection({"scan-doi-thu"}):
            score += 10
        score += _memory_entry_recency_bonus(entry)
        if str(entry.get("source_quality_status") or "").strip().lower() == "success":
            score += 4
    score += min(int(entry.get("accepted_count") or 0), 8)
    score += min(int(entry.get("memory_value_score") or 0), 8)
    score -= min(max(0, int(entry.get("failure_count") or 0)), 6)
    return score


def _memory_packet_delivery_entries(memory_packet: dict[str, Any] | None) -> list[dict[str, Any]]:
    packet = dict(memory_packet or {})
    entries: list[dict[str, Any]] = []
    for item in list(packet.get("entries") or []):
        if not isinstance(item, dict):
            continue
        entries.append(
            {
                "key": str(item.get("key") or "").strip(),
                "heading": str(item.get("heading") or "").strip(),
                "category": str(item.get("category") or "").strip(),
                "fit_score": int(item.get("fit_score") or 0),
                "memory_value_score": int(item.get("memory_value_score") or 0),
                "origin_agent": str(item.get("origin_agent") or "").strip().lower(),
                "source_skill_names": [
                    str(skill or "").strip().lower()
                    for skill in list(item.get("source_skill_names") or [])
                    if str(skill or "").strip()
                ],
                "source_quality_status": str(item.get("source_quality_status") or "").strip().lower(),
            }
        )
    return entries


def _memory_entry_packet_eligible(entry: dict[str, Any], skill_names: list[str] | None = None) -> bool:
    category = str(entry.get("category") or "").strip().lower()
    if category != "successful_output":
        return True
    lowered_skills = {str(item or "").strip().lower() for item in list(skill_names or []) if str(item or "").strip()}
    source_skills = set(_memory_entry_skills(entry))
    if lowered_skills and source_skills and not lowered_skills.intersection(source_skills):
        return False
    return True


def _build_memory_packet(
    request: str,
    session_key: str,
    skill_names: list[str] | None = None,
    *,
    limit: int = MEMORY_RECALL_LIMIT,
) -> dict[str, Any]:
    state = _sync_memory_retrieval_index()
    _sync_request_user_fact_memory(state, request, session_key)
    _normalize_memory_entries(state)
    _prune_memory_entries(state)
    entries = [
        dict(item)
        for item in list((state.get("entries") or {}).values())
        if isinstance(item, dict) and str(item.get("content") or "").strip()
    ]
    if not entries:
        return {"entries": [], "context": ""}
    ranked = sorted(
        (
            {
                **entry,
                "fit_score": _memory_entry_score(entry, request, skill_names, session_key=session_key),
            }
            for entry in entries
        ),
        key=lambda item: (
            int(item.get("fit_score") or 0),
            int(item.get("accepted_count") or 0),
            str(item.get("heading") or ""),
        ),
        reverse=True,
    )
    selected = [
        item
        for item in ranked
        if int(item.get("fit_score") or 0) > 0 and _memory_entry_packet_eligible(item, skill_names)
    ][: max(1, int(limit or 0))]
    if not selected:
        selected = [
            item for item in ranked
            if str(item.get("category") or "").strip() == "markdown_section"
        ][:1]
    packet_entries = [
        {
            "key": str(item.get("key") or "").strip(),
            "heading": str(item.get("heading") or "").strip(),
            "fit_score": int(item.get("fit_score") or 0),
            "memory_value_score": int(item.get("memory_value_score") or 0),
            "accepted_count": int(item.get("accepted_count") or 0),
            "failure_count": int(item.get("failure_count") or 0),
            "category": str(item.get("category") or "").strip(),
            "origin_agent": str(item.get("origin_agent") or "").strip().lower(),
            "source_skill_names": _memory_entry_skills(item),
            "source_quality_status": str(item.get("source_quality_status") or "").strip().lower(),
            "content_format": str(item.get("content_format") or "").strip(),
            "content": str(item.get("content") or "").strip(),
        }
        for item in selected
    ]
    context = "\n\n".join(
        f"[{item['heading']}]\n{item['content']}"
        for item in packet_entries
        if str(item.get("content") or "").strip()
    ).strip()
    state.setdefault("session_packets", {})[session_key] = {
        "keys": [str(item.get("key") or "").strip() for item in packet_entries],
        "entries": _memory_packet_delivery_entries({"entries": packet_entries}),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "request_hash": hashlib.sha256(str(request or "").encode("utf-8")).hexdigest(),
        "retrieval_mode": "scored_governed_memory_recall",
    }
    _save_memory_recall_state(state)
    return {
        "entries": packet_entries,
        "context": context,
        "retrieval_mode": "scored_governed_memory_recall",
    }


def _record_memory_recall_outcome(
    session_key: str,
    quality_status: str,
    delivery_fingerprint: str,
    *,
    memory_packet: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    packet = dict(memory_packet or {})
    keys = [str(item.get("key") or "").strip() for item in list(packet.get("entries") or []) if str(item.get("key") or "").strip()]
    state = _load_memory_recall_state()
    session_packets = state.setdefault("session_packets", {})
    remembered = dict(session_packets.get(session_key) or {})
    if not keys:
        keys = [str(item).strip() for item in list(remembered.get("keys") or []) if str(item).strip()]
    if not keys:
        return None
    normalized_quality = str(quality_status or "partial").strip().lower()
    if normalized_quality not in {"success", "partial", "failure"}:
        normalized_quality = "partial"
    entries_state = state.setdefault("entries", {})
    updated: list[dict[str, Any]] = []
    for key in keys:
        record = dict(entries_state.get(key) or {})
        if not record:
            continue
        record["recall_count"] = int(record.get("recall_count") or 0) + 1
        if normalized_quality == "success":
            record["accepted_count"] = int(record.get("accepted_count") or 0) + 2
        elif normalized_quality == "partial":
            record["accepted_count"] = int(record.get("accepted_count") or 0) + 1
        elif normalized_quality == "failure":
            record["failure_count"] = int(record.get("failure_count") or 0) + 2
        record["last_recalled_at"] = _memory_now_iso()
        record["last_quality_status"] = normalized_quality
        record["last_delivery_fingerprint"] = delivery_fingerprint
        _refresh_memory_value_score(record)
        entries_state[key] = record
        updated.append(
            {
                "key": key,
                "heading": str(record.get("heading") or "").strip(),
                "category": str(record.get("category") or "").strip(),
                "memory_value_score": int(record.get("memory_value_score") or 0),
                "recall_count": int(record.get("recall_count") or 0),
                "origin_agent": str(record.get("origin_agent") or "").strip().lower(),
            }
        )
    session_packets.pop(session_key, None)
    _normalize_memory_entries(state)
    _save_memory_recall_state(state)
    if not updated:
        return None
    return {
        "quality_status": normalized_quality,
        "entries": updated,
        "retrieval_mode": str(packet.get("retrieval_mode") or "scored_governed_memory_recall"),
    }


def _memory_context_block(memory_packet: dict[str, Any] | None) -> str:
    packet = dict(memory_packet or {})
    context = str(packet.get("context") or "").strip()
    if not context:
        return "(none)"
    return context


def _load_trust_evidence_state() -> dict[str, Any]:
    path = TRUST_EVIDENCE_STATE_PATH
    if not path.exists():
        return {"version": 1, "entries": {}, "session_packets": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "entries": {}, "session_packets": {}}
    if not isinstance(payload, dict):
        return {"version": 1, "entries": {}, "session_packets": {}}
    payload.setdefault("version", 1)
    payload.setdefault("entries", {})
    payload.setdefault("session_packets", {})
    if not isinstance(payload.get("entries"), dict):
        payload["entries"] = {}
    if not isinstance(payload.get("session_packets"), dict):
        payload["session_packets"] = {}
    return payload


def _save_trust_evidence_state(state: dict[str, Any]) -> None:
    TRUST_EVIDENCE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRUST_EVIDENCE_STATE_PATH.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _compress_trust_evidence_content(content: str) -> str:
    compressed = _compress_successful_output_memory(content)
    if compressed:
        return compressed[:TRUST_EVIDENCE_COMPRESSED_LIMIT].strip()
    return _memory_inline_digest(content, limit=TRUST_EVIDENCE_COMPRESSED_LIMIT)


def _trust_evidence_effective_status(entry: dict[str, Any], *, now_epoch: int | None = None) -> str:
    status = str(entry.get("approval_status") or "draft").strip().lower() or "draft"
    if status == "revoked":
        return "revoked"
    current_epoch = int(now_epoch if now_epoch is not None else time.time())
    freshness_days = max(0, int(entry.get("freshness_days") or 0))
    recorded_epoch = _memory_timestamp_epoch(
        entry.get("source_recorded_at") or entry.get("updated_at") or entry.get("approved_at")
    )
    if freshness_days > 0 and recorded_epoch > 0 and current_epoch - recorded_epoch > freshness_days * 86400:
        return "stale"
    if status not in {"approved", "draft", "stale", "revoked"}:
        return "draft"
    return status


def _trust_evidence_topics_from_text(*parts: str) -> list[str]:
    lowered = _ascii_fold("\n".join(str(part or "") for part in parts)).lower()
    topic_map = {
        "ai_governance": ("ai governance", "governance", "model risk"),
        "data_retention": ("data retention", "retention", "delete data"),
        "subprocessors": ("subprocessor", "subprocessors", "third-party processor"),
        "security_controls": ("security control", "security review", "soc2", "iso27001"),
        "privacy": ("privacy", "pii", "personal data", "gdpr"),
        "trust_center": ("trust center", "customer assurance", "due diligence"),
        "model_vendor_changes": ("pricing", "policy", "deprecation", "provider", "model", "api"),
        "regulatory": ("regulation", "regulatory", "compliance", "policy update"),
    }
    topics: list[str] = []
    for topic, keywords in topic_map.items():
        if any(keyword in lowered for keyword in keywords):
            topics.append(topic)
    return topics[:6]


def _trust_evidence_entry_score(
    entry: dict[str, Any],
    request: str,
    skill_names: list[str] | None = None,
    *,
    session_key: str = "",
) -> int:
    request_tokens = set(_request_tokens(request))
    entry_tokens = {str(item).strip().lower() for item in list(entry.get("tokens") or []) if str(item).strip()}
    topic_tags = {str(item).strip().lower() for item in list(entry.get("topic_tags") or []) if str(item).strip()}
    source_skills = {
        str(item).strip().lower()
        for item in list(entry.get("source_skill_names") or [])
        if str(item).strip()
    }
    lowered_skills = {
        str(item).strip().lower()
        for item in list(skill_names or [])
        if str(item).strip()
    }
    kind = str(entry.get("kind") or "").strip().lower()
    status = _trust_evidence_effective_status(entry)
    score = len(request_tokens & entry_tokens) * 6
    score += len(request_tokens & topic_tags) * 5
    if lowered_skills and source_skills.intersection(lowered_skills):
        score += 12
    if session_key and str(entry.get("source_session_key") or "").strip() == str(session_key or "").strip():
        score += 4
    if status == "approved":
        score += 18
    elif status == "draft":
        score += 6
    elif status == "stale":
        score -= 4
    elif status == "revoked":
        score -= 100
    if _request_is_security_questionnaire(request, list(skill_names or [])) and kind == "questionnaire_answer_pack":
        score += 12
    if _request_is_ai_stack_watch(request, list(skill_names or [])) and kind == "watch_brief":
        score += 12
    score += min(int(entry.get("accepted_count") or 0), 4)
    score += _memory_entry_recency_bonus(entry)
    return score


def _trust_evidence_packet_delivery_entries(trust_packet: dict[str, Any] | None) -> list[dict[str, Any]]:
    packet = dict(trust_packet or {})
    entries: list[dict[str, Any]] = []
    for item in list(packet.get("entries") or []):
        if not isinstance(item, dict):
            continue
        entries.append(
            {
                "key": str(item.get("key") or "").strip(),
                "heading": str(item.get("heading") or "").strip(),
                "kind": str(item.get("kind") or "").strip(),
                "fit_score": int(item.get("fit_score") or 0),
                "approval_status": str(item.get("approval_status") or "").strip().lower(),
                "origin_agent": str(item.get("origin_agent") or "").strip().lower(),
                "origin_task_kind": str(item.get("origin_task_kind") or "").strip().lower(),
                "topic_tags": [
                    str(tag).strip().lower()
                    for tag in list(item.get("topic_tags") or [])
                    if str(tag).strip()
                ],
                "source_skill_names": [
                    str(skill).strip().lower()
                    for skill in list(item.get("source_skill_names") or [])
                    if str(skill).strip()
                ],
            }
        )
    return entries


def _trust_evidence_packet_keys(trust_packet: dict[str, Any] | None) -> list[str]:
    return [
        str(item.get("key") or "").strip()
        for item in list(dict(trust_packet or {}).get("entries") or [])
        if isinstance(item, dict) and str(item.get("key") or "").strip()
    ]


def _build_trust_evidence_packet(
    request: str,
    session_key: str,
    skill_names: list[str] | None = None,
    *,
    limit: int = TRUST_EVIDENCE_LIMIT,
) -> dict[str, Any]:
    state = _load_trust_evidence_state()
    entries = [
        dict(item)
        for item in list((state.get("entries") or {}).values())
        if isinstance(item, dict) and str(item.get("content") or "").strip()
    ]
    if not entries:
        return {"entries": [], "context": "", "retrieval_mode": "scored_governed_trust_evidence"}
    ranked = sorted(
        (
            {
                **entry,
                "fit_score": _trust_evidence_entry_score(entry, request, skill_names, session_key=session_key),
                "approval_status": _trust_evidence_effective_status(entry),
            }
            for entry in entries
        ),
        key=lambda item: (
            int(item.get("fit_score") or 0),
            1 if str(item.get("approval_status") or "").strip().lower() == "approved" else 0,
            str(item.get("heading") or ""),
        ),
        reverse=True,
    )
    selected = [
        item
        for item in ranked
        if int(item.get("fit_score") or 0) > 0 and str(item.get("approval_status") or "").strip().lower() != "revoked"
    ][: max(1, int(limit or 0))]
    packet_entries = [
        {
            "key": str(item.get("key") or "").strip(),
            "heading": str(item.get("heading") or "").strip(),
            "kind": str(item.get("kind") or "").strip(),
            "fit_score": int(item.get("fit_score") or 0),
            "approval_status": str(item.get("approval_status") or "").strip().lower(),
            "origin_agent": str(item.get("origin_agent") or "").strip().lower(),
            "origin_task_kind": str(item.get("origin_task_kind") or "").strip().lower(),
            "topic_tags": [
                str(tag).strip().lower()
                for tag in list(item.get("topic_tags") or [])
                if str(tag).strip()
            ],
            "source_skill_names": [
                str(skill).strip().lower()
                for skill in list(item.get("source_skill_names") or [])
                if str(skill).strip()
            ],
            "content": str(item.get("content") or "").strip(),
        }
        for item in selected
    ]
    context = "\n\n".join(
        f"[{item['heading']}] ({item['approval_status']}; topics={', '.join(item['topic_tags']) or 'general'})\n{item['content']}"
        for item in packet_entries
        if str(item.get("content") or "").strip()
    ).strip()
    state.setdefault("session_packets", {})[session_key] = {
        "keys": _trust_evidence_packet_keys({"entries": packet_entries}),
        "entries": _trust_evidence_packet_delivery_entries({"entries": packet_entries}),
        "created_at": _memory_now_iso(),
        "request_hash": hashlib.sha256(str(request or "").encode("utf-8")).hexdigest(),
        "retrieval_mode": "scored_governed_trust_evidence",
    }
    _save_trust_evidence_state(state)
    return {
        "entries": packet_entries,
        "context": context,
        "retrieval_mode": "scored_governed_trust_evidence",
    }


def _trust_evidence_context_block(trust_packet: dict[str, Any] | None) -> str:
    packet = dict(trust_packet or {})
    context = str(packet.get("context") or "").strip()
    if not context:
        return "(none)"
    return context


def _delivery_trust_evidence_entry_from_event(delivery_event: Any) -> dict[str, Any] | None:
    if not isinstance(delivery_event, dict):
        return None
    quality_status = str(delivery_event.get("status") or "").strip().lower()
    if quality_status not in {"success", "partial"}:
        return None
    if not bool(delivery_event.get("final_artifact_usable")):
        return None
    request_text = str(delivery_event.get("request_text") or "").strip()
    skill_names = [
        str(item).strip().lower()
        for item in list(delivery_event.get("skills_used") or [])
        if str(item).strip()
    ]
    lowered_skills = set(skill_names)
    kind = ""
    heading = ""
    freshness_days = 0
    if "security-questionnaire" in lowered_skills:
        kind = "questionnaire_answer_pack"
        heading = "Approved questionnaire answer pack"
        freshness_days = TRUST_EVIDENCE_QUESTIONNAIRE_FRESHNESS_DAYS
    elif "ai-stack-watch" in lowered_skills:
        kind = "watch_brief"
        heading = "AI stack watch brief"
        freshness_days = TRUST_EVIDENCE_WATCH_FRESHNESS_DAYS
    if not kind:
        return None
    raw_text = str(delivery_event.get("text") or "").strip()
    if not raw_text:
        return None
    artifact = _coerce_request_specific_artifact(raw_text, request_text) if request_text else raw_text
    if not artifact or not _artifact_matches_skill_shape(artifact, request_text, skill_names):
        return None
    delivery_fingerprint = str(delivery_event.get("delivery_fingerprint") or "").strip()
    if not delivery_fingerprint:
        return None
    approval_gate_status = str(delivery_event.get("approval_gate_status") or "").strip().lower()
    if kind == "questionnaire_answer_pack" and approval_gate_status != "ready_for_final_delivery":
        approval_status = "draft"
    else:
        approval_status = "approved" if quality_status == "success" else "draft"
    origin_agent, origin_task_kind = _memory_delivery_origin_details(delivery_event)
    content = _compress_trust_evidence_content(artifact)
    if not content:
        return None
    topic_tags = _trust_evidence_topics_from_text(request_text, artifact, " ".join(skill_names))
    return {
        "key": f"trust/{kind}/{delivery_fingerprint}",
        "heading": heading,
        "kind": kind,
        "content": content,
        "tokens": _request_tokens(f"{request_text}\n{artifact}\n{' '.join(skill_names)}"),
        "approval_status": approval_status,
        "topic_tags": topic_tags,
        "source_skill_names": skill_names,
        "source_session_key": str(delivery_event.get("session_key") or "").strip(),
        "source_event_id": str(delivery_event.get("event_id") or "").strip(),
        "source_quality_status": quality_status,
        "source_recorded_at": str(delivery_event.get("recorded_at") or "").strip(),
        "origin_agent": origin_agent,
        "origin_task_kind": origin_task_kind,
        "origin_delivery_fingerprint": delivery_fingerprint,
        "freshness_days": freshness_days,
    }


def _upsert_trust_evidence_entry(state: dict[str, Any], entry: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
    key = str(entry.get("key") or "").strip()
    content = str(entry.get("content") or "").strip()
    if not key or not content:
        return None, False
    entries_state = state.setdefault("entries", {})
    record = dict(entries_state.get(key) or {})
    if not isinstance(record, dict):
        record = {}
    previous_hash = str(record.get("content_hash") or "").strip()
    record.setdefault("accepted_count", 0)
    record.setdefault("failure_count", 0)
    record["key"] = key
    record["heading"] = str(entry.get("heading") or record.get("heading") or "Trust evidence").strip()
    record["kind"] = str(entry.get("kind") or record.get("kind") or "").strip()
    record["content"] = content[:TRUST_EVIDENCE_COMPRESSED_LIMIT].strip()
    record["tokens"] = list(entry.get("tokens") or [])
    record["approval_status"] = str(entry.get("approval_status") or record.get("approval_status") or "draft").strip().lower()
    record["topic_tags"] = [
        str(tag).strip().lower()
        for tag in list(entry.get("topic_tags") or record.get("topic_tags") or [])
        if str(tag).strip()
    ]
    record["source_skill_names"] = [
        str(skill).strip().lower()
        for skill in list(entry.get("source_skill_names") or record.get("source_skill_names") or [])
        if str(skill).strip()
    ]
    record["source_session_key"] = str(entry.get("source_session_key") or record.get("source_session_key") or "").strip()
    record["source_event_id"] = str(entry.get("source_event_id") or record.get("source_event_id") or "").strip()
    record["source_quality_status"] = str(entry.get("source_quality_status") or record.get("source_quality_status") or "").strip().lower()
    record["source_recorded_at"] = str(entry.get("source_recorded_at") or record.get("source_recorded_at") or "").strip()
    record["origin_agent"] = str(entry.get("origin_agent") or record.get("origin_agent") or "").strip().lower()
    record["origin_task_kind"] = str(entry.get("origin_task_kind") or record.get("origin_task_kind") or "").strip().lower()
    record["origin_delivery_fingerprint"] = str(
        entry.get("origin_delivery_fingerprint") or record.get("origin_delivery_fingerprint") or ""
    ).strip()
    record["freshness_days"] = int(entry.get("freshness_days") or record.get("freshness_days") or 0)
    if record["approval_status"] == "approved":
        record["accepted_count"] = int(record.get("accepted_count") or 0) + 1
        record["approved_at"] = _memory_now_iso()
    elif record["approval_status"] == "draft":
        record["failure_count"] = int(record.get("failure_count") or 0)
    record["updated_at"] = _memory_now_iso()
    record["content_hash"] = hashlib.sha256(record["content"].encode("utf-8")).hexdigest()
    entries_state[key] = record
    changed = previous_hash != str(record.get("content_hash") or "").strip()
    return record, changed


def _remember_trust_evidence(delivery_event: Any) -> list[dict[str, Any]]:
    entry = _delivery_trust_evidence_entry_from_event(delivery_event)
    if not entry:
        return []
    state = _load_trust_evidence_state()
    record, changed = _upsert_trust_evidence_entry(state, entry)
    _save_trust_evidence_state(state)
    if not record:
        return []
    return [
        {
            "key": str(record.get("key") or "").strip(),
            "heading": str(record.get("heading") or "").strip(),
            "kind": str(record.get("kind") or "").strip(),
            "approval_status": _trust_evidence_effective_status(record),
            "origin_agent": str(record.get("origin_agent") or "").strip().lower(),
            "origin_task_kind": str(record.get("origin_task_kind") or "").strip().lower(),
            "topic_tags": [
                str(tag).strip().lower()
                for tag in list(record.get("topic_tags") or [])
                if str(tag).strip()
            ],
            "source_skill_names": [
                str(skill).strip().lower()
                for skill in list(record.get("source_skill_names") or [])
                if str(skill).strip()
            ],
            "content_updated": bool(changed),
        }
    ]


def _new_trust_assurance_state() -> dict[str, Any]:
    return {"version": 1, "questionnaires": {}, "approval_queue": {}}


def _load_trust_assurance_state() -> dict[str, Any]:
    path = TRUST_ASSURANCE_STATE_PATH
    if not path.exists():
        return _new_trust_assurance_state()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _new_trust_assurance_state()
    if not isinstance(payload, dict):
        return _new_trust_assurance_state()
    payload.setdefault("version", 1)
    payload.setdefault("questionnaires", {})
    payload.setdefault("approval_queue", {})
    if not isinstance(payload.get("questionnaires"), dict):
        payload["questionnaires"] = {}
    if not isinstance(payload.get("approval_queue"), dict):
        payload["approval_queue"] = {}
    return payload


def _save_trust_assurance_state(state: dict[str, Any]) -> None:
    TRUST_ASSURANCE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRUST_ASSURANCE_STATE_PATH.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _questionnaire_question_id(text: str) -> str:
    return "tqq_" + hashlib.sha256(str(text or "").strip().encode("utf-8")).hexdigest()[:12]


def _questionnaire_queue_id(questionnaire_id: str, question_id: str) -> str:
    raw = f"{questionnaire_id}:{question_id}".encode("utf-8")
    return "tqa_" + hashlib.sha256(raw).hexdigest()[:12]


def _normalize_questionnaire_prompt_line(line: str) -> str:
    text = str(line or "").strip()
    text = re.sub(r"^\s*(?:[-*•]+|\d+[.)]|q\d+[.)]?)\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*(?:question|cau hoi)\s*[:.-]?\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def _default_questionnaire_questions_from_topics(topics: list[str]) -> list[str]:
    topic_map = {
        "ai_governance": "What AI governance controls are currently documented for Meridian?",
        "data_retention": "What is Meridian's current data retention stance and boundary?",
        "subprocessors": "Which subprocessors or third-party processors are currently in scope for Meridian?",
        "security_controls": "Which security controls or certifications can Meridian support with evidence today?",
        "privacy": "What privacy and personal-data handling claims can Meridian support today?",
        "trust_center": "What customer assurance materials are currently approved for Meridian?",
        "model_vendor_changes": "Which provider or model changes could affect Meridian trust answers right now?",
        "regulatory": "Which regulatory changes currently affect Meridian trust answers or approvals?",
    }
    questions: list[str] = []
    for topic in topics:
        question = str(topic_map.get(str(topic or "").strip().lower()) or "").strip()
        if question and question not in questions:
            questions.append(question)
    return questions


def _extract_questionnaire_items(request_text: str) -> list[dict[str, Any]]:
    raw_request = str(request_text or "").strip()
    lines = [_normalize_questionnaire_prompt_line(line) for line in raw_request.splitlines()]
    explicit: list[str] = []
    for index, line in enumerate(lines):
        if not line or len(line) < 8:
            continue
        lowered = _ascii_fold(line).lower()
        if index == 0 and all(token not in lowered for token in ("?", "retention", "privacy", "subprocessor", "governance", "security", "processor")):
            continue
        if "security questionnaire" in lowered and "?" not in lowered:
            continue
        if (
            "?" in line
            or re.match(r"^(what|how|which|do|does|is|are|describe|list|provide)\b", lowered)
            or any(
                token in lowered
                for token in (
                    "ai governance",
                    "data retention",
                    "subprocessor",
                    "security",
                    "privacy",
                    "processor",
                    "trust center",
                    "model",
                    "policy",
                    "pricing",
                )
            )
        ):
            explicit.append(line.rstrip(":"))
    if not explicit:
        explicit = _default_questionnaire_questions_from_topics(_trust_evidence_topics_from_text(raw_request))
    if len(explicit) == 1:
        only_line = _ascii_fold(str(explicit[0] or "")).lower()
        request_topics = _trust_evidence_topics_from_text(raw_request)
        if "security questionnaire" in only_line and len(request_topics) > 1:
            explicit = _default_questionnaire_questions_from_topics(request_topics)
    if not explicit:
        explicit = ["What can Meridian support today with approved evidence for this trust review?"]
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for ordinal, question in enumerate(explicit, start=1):
        normalized = str(question or "").strip()
        if not normalized:
            continue
        dedup_key = _ascii_fold(normalized).lower()
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        topic_tags = _trust_evidence_topics_from_text(normalized, raw_request)
        critical = bool(
            {
                "ai_governance",
                "data_retention",
                "subprocessors",
                "security_controls",
                "privacy",
            }.intersection(topic_tags)
        )
        items.append(
            {
                "question_id": _questionnaire_question_id(normalized),
                "ordinal": ordinal,
                "text": normalized,
                "topic_tags": topic_tags,
                "critical": critical,
            }
        )
        if len(items) >= max(1, int(TRUST_QUESTIONNAIRE_MAX_QUESTIONS or 0)):
            break
    return items


def _review_trust_evidence_entry(
    evidence_key: str,
    decision: str,
    *,
    note: str = "",
    actor: str = "",
    state: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    key = str(evidence_key or "").strip()
    normalized_decision = str(decision or "").strip().lower()
    if not key or normalized_decision not in {"approve", "approved", "draft", "stale", "revoke", "revoked"}:
        return None
    payload = state if isinstance(state, dict) else _load_trust_evidence_state()
    entries = payload.setdefault("entries", {})
    record = dict(entries.get(key) or {})
    if not record:
        return None
    if normalized_decision in {"approve", "approved"}:
        record["approval_status"] = "approved"
        record["approved_at"] = _memory_now_iso()
    elif normalized_decision in {"revoke", "revoked"}:
        record["approval_status"] = "revoked"
        record["revoked_at"] = _memory_now_iso()
    elif normalized_decision == "stale":
        record["approval_status"] = "stale"
        record["stale_at"] = _memory_now_iso()
    else:
        record["approval_status"] = "draft"
    record["reviewed_at"] = _memory_now_iso()
    record["reviewed_by"] = str(actor or "").strip().lower()
    if note:
        record["review_note"] = str(note).strip()
    record["updated_at"] = _memory_now_iso()
    entries[key] = record
    if payload is not state:
        _save_trust_evidence_state(payload)
    session_key = str(record.get("source_session_key") or "").strip()
    origin_agent = str(record.get("origin_agent") or "").strip().lower()
    extra_details: dict[str, Any] = {
        "evidence_key": key,
        "decision": normalized_decision,
        "kind": str(record.get("kind") or "").strip(),
        "approval_status": str(record.get("approval_status") or "").strip().lower(),
        "origin_agent": origin_agent,
    }
    if note:
        extra_details["review_note"] = str(note).strip()
    if origin_agent:
        try:
            ledger = accounting_load_ledger()
            agent = dict((ledger.get("agents") or {}).get(origin_agent) or {})
            if agent:
                extra_details["authority_units"] = int(agent.get("authority_units") or 0)
                extra_details["reputation_units"] = int(agent.get("reputation_units") or 0)
        except Exception:
            pass
        try:
            extra_details["court_restrictions"] = [
                str(item).strip().lower()
                for item in list(court_get_restrictions(origin_agent, org_id=LOOM_ORG_ID) or [])
                if str(item).strip()
            ]
        except Exception:
            pass
    _record_gateway_audit(
        "trust_evidence_reviewed",
        session_key=session_key or key,
        channel="trust_ops",
        text=str(record.get("heading") or "").strip(),
        outcome=normalized_decision,
        extra_details=extra_details,
    )
    try:
        accounting_append_tx(
            {
                "type": "trust_evidence_review",
                "session_key": session_key,
                "evidence_key": key,
                "decision": normalized_decision,
                "kind": str(record.get("kind") or "").strip(),
                "origin_agent": origin_agent,
                "actor": str(actor or "").strip().lower(),
                "note": str(note).strip(),
            }
        )
    except Exception:
        pass
    return dict(record)


def _questionnaire_support_snapshot(
    question_text: str,
    request_text: str,
    skill_names: list[str],
    evidence_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    question_topics = {
        str(tag).strip().lower()
        for tag in _trust_evidence_topics_from_text(question_text)
        if str(tag).strip()
    }
    ranked = sorted(
        (
            (lambda fit_score, entry_dict: {
                **entry_dict,
                "fit_score": fit_score,
                "approval_status": _trust_evidence_effective_status(entry_dict),
            })(
                _trust_evidence_entry_score(
                    entry,
                    question_text,
                    skill_names,
                    session_key="",
                )
                + (
                    len(
                        question_topics.intersection(
                            {
                                str(tag).strip().lower()
                                for tag in list(dict(entry).get("topic_tags") or [])
                                if str(tag).strip()
                            }
                        )
                    )
                    * 12
                )
                - (
                    18
                    if question_topics
                    and not question_topics.intersection(
                        {
                            str(tag).strip().lower()
                            for tag in list(dict(entry).get("topic_tags") or [])
                            if str(tag).strip()
                        }
                    )
                    else 0
                ),
                dict(entry),
            )
            for entry in evidence_entries
            if isinstance(entry, dict)
        ),
        key=lambda item: (
            int(item.get("fit_score") or 0),
            1 if str(item.get("approval_status") or "").strip().lower() == "approved" else 0,
            str(item.get("heading") or ""),
        ),
        reverse=True,
    )
    best = dict(ranked[0]) if ranked else {}
    fit_score = int(best.get("fit_score") or 0)
    evidence_status = str(best.get("approval_status") or "").strip().lower()
    shared_topics = question_topics.intersection(
        {
            str(tag).strip().lower()
            for tag in list(best.get("topic_tags") or [])
            if str(tag).strip()
        }
    )
    if not best or fit_score < max(1, int(TRUST_QUESTIONNAIRE_DRAFT_FIT or 0)):
        answer_state = "open"
    elif question_topics and not shared_topics:
        answer_state = "draft"
    elif evidence_status == "revoked":
        answer_state = "revoked"
    elif evidence_status == "stale":
        answer_state = "stale"
    elif evidence_status == "approved" and fit_score >= max(1, int(TRUST_QUESTIONNAIRE_APPROVED_FIT or 0)):
        answer_state = "approved"
    else:
        answer_state = "draft"

    heading = str(best.get("heading") or "").strip()
    evidence_key = str(best.get("key") or "").strip()
    if answer_state == "approved" and heading:
        answer_text = f"Supported by approved evidence `{heading}`."
    elif answer_state == "draft" and heading:
        answer_text = f"Draft only. `{heading}` is relevant but not strong enough to ship as final without approval."
    elif answer_state == "stale" and heading:
        answer_text = f"`{heading}` is stale and must be refreshed before it can support a final answer."
    elif answer_state == "revoked" and heading:
        answer_text = f"`{heading}` is revoked and must not be used in a final trust pack."
    else:
        answer_text = "No approved evidence currently supports this answer."

    return {
        "request_text": request_text,
        "answer_state": answer_state,
        "support_fit_score": fit_score,
        "evidence_key": evidence_key,
        "evidence_heading": heading,
        "evidence_status": evidence_status or "missing",
        "answer_text": answer_text,
        "best_evidence_origin_agent": str(best.get("origin_agent") or "").strip().lower(),
        "best_evidence_topic_tags": [
            str(tag).strip().lower()
            for tag in list(best.get("topic_tags") or [])
            if str(tag).strip()
        ],
    }


def _rollup_trust_questionnaire(questionnaire: dict[str, Any]) -> dict[str, Any]:
    questions = [dict(item) for item in list(questionnaire.get("questions") or []) if isinstance(item, dict)]
    critical_questions = [item for item in questions if bool(item.get("critical"))]
    pending_questions = [item for item in questions if bool(item.get("approval_required"))]
    pending_critical = [item for item in pending_questions if bool(item.get("critical"))]
    revoked_critical = [item for item in critical_questions if str(item.get("answer_state") or "").strip().lower() == "revoked"]
    stale_critical = [item for item in critical_questions if str(item.get("answer_state") or "").strip().lower() == "stale"]
    unresolved_critical = [item for item in critical_questions if str(item.get("answer_state") or "").strip().lower() == "unresolved"]
    approved_critical = [item for item in critical_questions if str(item.get("answer_state") or "").strip().lower() == "approved"]
    if revoked_critical:
        approval_gate_status = "blocked_revoked"
        overall_status = "revoked"
    elif pending_critical or stale_critical:
        approval_gate_status = "pending_approval"
        overall_status = "stale" if stale_critical else "draft"
    else:
        approval_gate_status = "ready_for_final_delivery"
        overall_status = "approved"
    questionnaire["overall_status"] = overall_status
    questionnaire["approval_gate_status"] = approval_gate_status
    questionnaire["final_delivery_allowed"] = approval_gate_status == "ready_for_final_delivery"
    questionnaire["question_count"] = len(questions)
    questionnaire["critical_count"] = len(critical_questions)
    questionnaire["pending_approval_count"] = len(pending_questions)
    questionnaire["pending_critical_count"] = len(pending_critical)
    questionnaire["approved_critical_count"] = len(approved_critical)
    questionnaire["unresolved_critical_count"] = len(unresolved_critical)
    questionnaire["updated_at"] = _memory_now_iso()
    return questionnaire


def _sync_trust_approval_queue(state: dict[str, Any], questionnaire: dict[str, Any]) -> list[dict[str, Any]]:
    queue_state = state.setdefault("approval_queue", {})
    queue_entries: list[dict[str, Any]] = []
    for question in list(questionnaire.get("questions") or []):
        if not isinstance(question, dict):
            continue
        queue_id = str(
            question.get("queue_id")
            or _questionnaire_queue_id(
                str(questionnaire.get("questionnaire_id") or "").strip(),
                str(question.get("question_id") or "").strip(),
            )
        ).strip()
        if not queue_id:
            continue
        queue_record = dict(queue_state.get(queue_id) or {})
        queue_record["queue_id"] = queue_id
        queue_record["questionnaire_id"] = str(questionnaire.get("questionnaire_id") or "").strip()
        queue_record["source_session_key"] = str(questionnaire.get("source_session_key") or "").strip()
        queue_record["question_id"] = str(question.get("question_id") or "").strip()
        queue_record["question_text"] = str(question.get("text") or "").strip()
        queue_record["critical"] = bool(question.get("critical"))
        queue_record["topic_tags"] = [
            str(tag).strip().lower()
            for tag in list(question.get("topic_tags") or [])
            if str(tag).strip()
        ]
        queue_record["evidence_key"] = str(question.get("evidence_key") or "").strip()
        queue_record["evidence_status"] = str(question.get("evidence_status") or "").strip().lower()
        queue_record["answer_state"] = str(question.get("answer_state") or "").strip().lower()
        queue_record["approval_required"] = bool(question.get("approval_required"))
        queue_record["status"] = (
            "pending"
            if bool(question.get("approval_required"))
            else str(queue_record.get("status") or "cleared").strip().lower()
        )
        queue_record.setdefault("created_at", _memory_now_iso())
        queue_record["updated_at"] = _memory_now_iso()
        queue_state[queue_id] = queue_record
        question["queue_id"] = queue_id
        queue_entries.append(dict(queue_record))
    questionnaire["approval_queue_ids"] = [
        str(item.get("queue_id") or "").strip()
        for item in queue_entries
        if str(item.get("queue_id") or "").strip()
    ]
    questionnaire["approval_queue_entries"] = queue_entries
    return queue_entries


def _build_questionnaire_state(
    request_text: str,
    session_key: str,
    skill_names: list[str],
    *,
    trust_packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence_state = _load_trust_evidence_state()
    evidence_entries = [
        dict(item)
        for item in list((evidence_state.get("entries") or {}).values())
        if isinstance(item, dict) and str(item.get("content") or "").strip()
    ]
    questions = _extract_questionnaire_items(request_text)
    questionnaire_id = "tq_" + hashlib.sha256(f"{session_key}\n{request_text}".encode("utf-8")).hexdigest()[:12]
    built_questions: list[dict[str, Any]] = []
    for question in questions:
        record = dict(question)
        support = _questionnaire_support_snapshot(
            str(record.get("text") or "").strip(),
            request_text,
            skill_names,
            evidence_entries,
        )
        record.update(support)
        answer_state = str(record.get("answer_state") or "").strip().lower()
        record["approval_required"] = bool(record.get("critical")) and answer_state in {"draft", "open", "stale", "revoked"}
        built_questions.append(record)
    state = _load_trust_assurance_state()
    questionnaires = state.setdefault("questionnaires", {})
    questionnaire = dict(questionnaires.get(questionnaire_id) or {})
    questionnaire["questionnaire_id"] = questionnaire_id
    questionnaire["source_session_key"] = session_key
    questionnaire["request_text"] = request_text
    questionnaire["skill_names"] = [
        str(item).strip().lower()
        for item in list(skill_names or [])
        if str(item).strip()
    ]
    questionnaire["trust_evidence_keys"] = _trust_evidence_packet_keys(trust_packet)
    questionnaire["questions"] = built_questions
    questionnaire.setdefault("created_at", _memory_now_iso())
    _rollup_trust_questionnaire(questionnaire)
    _sync_trust_approval_queue(state, questionnaire)
    questionnaires[questionnaire_id] = questionnaire
    _save_trust_assurance_state(state)
    return questionnaire


def _render_questionnaire_answer_pack(questionnaire: dict[str, Any]) -> str:
    questions = [dict(item) for item in list(questionnaire.get("questions") or []) if isinstance(item, dict)]
    approved_lines: list[str] = []
    draft_lines: list[str] = []
    open_lines: list[str] = []
    for question in questions:
        text = str(question.get("text") or "").strip()
        state = str(question.get("answer_state") or "").strip().lower() or "open"
        heading = str(question.get("evidence_heading") or "").strip()
        fit_score = int(question.get("support_fit_score") or 0)
        prefix = f"- Q{int(question.get('ordinal') or 0)}: {text}"
        if state == "approved" and heading:
            approved_lines.append(f"{prefix} -> `{heading}` (fit {fit_score})")
        draft_lines.append(f"{prefix} [{state}] {str(question.get('answer_text') or '').strip()}")
        if state in {"draft", "open", "stale", "revoked", "unresolved"} or bool(question.get("approval_required")):
            gap_text = "approval queue" if bool(question.get("approval_required")) else state
            open_lines.append(f"{prefix} -> {gap_text}")

    if questionnaire.get("final_delivery_allowed"):
        status_line = "Final trust-pack delivery is currently allowed for this bounded questionnaire set."
    elif str(questionnaire.get("approval_gate_status") or "").strip() == "blocked_revoked":
        status_line = "Final trust-pack delivery is blocked because at least one critical answer depends on revoked evidence."
    else:
        status_line = "Final trust-pack delivery is still blocked pending approval or refresh on critical questions."

    next_moves = []
    if int(questionnaire.get("pending_approval_count") or 0) > 0:
        next_moves.append(
            f"Review {int(questionnaire.get('pending_approval_count') or 0)} queued question(s) before shipping a final pack."
        )
    if str(questionnaire.get("approval_gate_status") or "").strip() == "blocked_revoked":
        next_moves.append("Replace revoked evidence or mark the affected question unresolved with explicit buyer-facing wording.")
    if not next_moves:
        next_moves.append("Reuse only the approved answers below and keep any unresolved edge cases visible.")
    next_moves.append("Do not assert certifications, retention guarantees, privacy guarantees, or subprocessors beyond the evidence listed.")

    return textwrap.dedent(
        f"""
        **Status**

        - Questionnaire ID: `{str(questionnaire.get("questionnaire_id") or "").strip()}`
        - Approval gate: `{str(questionnaire.get("approval_gate_status") or "").strip()}`
        - Pending approvals: `{int(questionnaire.get("pending_approval_count") or 0)}`
        - Critical questions: `{int(questionnaire.get("critical_count") or 0)}`
        - {status_line}

        **Approved evidence**

        {chr(10).join(approved_lines) if approved_lines else '- No critical answer is currently backed by approved evidence.'}

        **Draft answers**

        {chr(10).join(draft_lines) if draft_lines else '- No questionnaire answers were derived in this run.'}

        **Open gaps**

        {chr(10).join(open_lines) if open_lines else '- No open gaps remain in this bounded questionnaire set.'}

        **Next move**

        {chr(10).join(f"{index}. {line}" for index, line in enumerate(next_moves, start=1))}
        """
    ).strip()


def _build_trust_assurance_summary(state: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = state if isinstance(state, dict) else _load_trust_assurance_state()
    evidence_state = _load_trust_evidence_state()
    queue_entries = [dict(item) for item in list((payload.get("approval_queue") or {}).values()) if isinstance(item, dict)]
    questionnaires = [dict(item) for item in list((payload.get("questionnaires") or {}).values()) if isinstance(item, dict)]
    pending_queue = [item for item in queue_entries if bool(item.get("approval_required"))]
    evidence_counts = {"approved": 0, "draft": 0, "stale": 0, "revoked": 0}
    for entry in list((evidence_state.get("entries") or {}).values()):
        if not isinstance(entry, dict):
            continue
        status = _trust_evidence_effective_status(entry)
        evidence_counts[status] = int(evidence_counts.get(status) or 0) + 1
    return {
        "queue_count": len(queue_entries),
        "pending_queue_count": len(pending_queue),
        "questionnaire_count": len(questionnaires),
        "ready_questionnaire_count": sum(1 for item in questionnaires if bool(item.get("final_delivery_allowed"))),
        "questionnaires": sorted(
            (
                {
                    "questionnaire_id": str(item.get("questionnaire_id") or "").strip(),
                    "approval_gate_status": str(item.get("approval_gate_status") or "").strip(),
                    "pending_approval_count": int(item.get("pending_approval_count") or 0),
                    "critical_count": int(item.get("critical_count") or 0),
                    "source_session_key": str(item.get("source_session_key") or "").strip(),
                }
                for item in questionnaires
            ),
            key=lambda item: (
                int(item.get("pending_approval_count") or 0),
                str(item.get("questionnaire_id") or ""),
            ),
            reverse=True,
        )[:10],
        "approval_queue": sorted(
            (
                {
                    "queue_id": str(item.get("queue_id") or "").strip(),
                    "questionnaire_id": str(item.get("questionnaire_id") or "").strip(),
                    "question_id": str(item.get("question_id") or "").strip(),
                    "question_text": str(item.get("question_text") or "").strip(),
                    "critical": bool(item.get("critical")),
                    "status": str(item.get("status") or "").strip().lower(),
                    "approval_required": bool(item.get("approval_required")),
                    "evidence_key": str(item.get("evidence_key") or "").strip(),
                    "evidence_status": str(item.get("evidence_status") or "").strip().lower(),
                }
                for item in queue_entries
            ),
            key=lambda item: (
                1 if bool(item.get("approval_required")) else 0,
                1 if bool(item.get("critical")) else 0,
                str(item.get("queue_id") or ""),
            ),
            reverse=True,
        )[:20],
        "evidence": {"counts": evidence_counts},
    }


def _trust_ops_queue_bucket(entry: dict[str, Any]) -> str:
    if bool(entry.get("approval_required")):
        return "pending"
    answer_state = str(entry.get("answer_state") or "").strip().lower()
    if answer_state in {"approved", "stale", "revoked", "unresolved", "draft"}:
        return answer_state
    status = str(entry.get("status") or "").strip().lower()
    if status in {"approve", "cleared"}:
        return "approved"
    return status or answer_state or "unknown"


def _build_trust_ops_operator_snapshot(
    state: dict[str, Any] | None = None,
    *,
    questionnaire_id: str = "",
    status_filter: str = "actionable",
    include_cleared: bool = False,
) -> dict[str, Any]:
    payload = state if isinstance(state, dict) else _load_trust_assurance_state()
    questionnaires_map = {
        str(item.get("questionnaire_id") or "").strip(): dict(item)
        for item in list((payload.get("questionnaires") or {}).values())
        if isinstance(item, dict) and str(item.get("questionnaire_id") or "").strip()
    }
    normalized_questionnaire_id = str(questionnaire_id or "").strip()
    normalized_filter = str(status_filter or "actionable").strip().lower()
    if normalized_filter not in {"actionable", "all", "pending", "approved", "stale", "revoked", "unresolved", "draft"}:
        normalized_filter = "actionable"
    queue_entries: list[dict[str, Any]] = []
    counts = {
        "total": 0,
        "actionable": 0,
        "pending": 0,
        "approved": 0,
        "stale": 0,
        "revoked": 0,
        "unresolved": 0,
        "draft": 0,
    }
    for item in list((payload.get("approval_queue") or {}).values()):
        if not isinstance(item, dict):
            continue
        queue_id = str(item.get("queue_id") or "").strip()
        qid = str(item.get("questionnaire_id") or "").strip()
        questionnaire = dict(questionnaires_map.get(qid) or {})
        if normalized_questionnaire_id and qid != normalized_questionnaire_id:
            continue
        questions = [dict(question) for question in list(questionnaire.get("questions") or []) if isinstance(question, dict)]
        question_id = str(item.get("question_id") or "").strip()
        question = next(
            (question for question in questions if str(question.get("question_id") or "").strip() == question_id),
            {},
        )
        projection = {
            "queue_id": queue_id,
            "questionnaire_id": qid,
            "question_id": question_id,
            "question_text": str(item.get("question_text") or question.get("text") or "").strip(),
            "critical": bool(item.get("critical") or question.get("critical")),
            "status": str(item.get("status") or "").strip().lower(),
            "approval_required": bool(item.get("approval_required") or question.get("approval_required")),
            "evidence_key": str(item.get("evidence_key") or question.get("evidence_key") or "").strip(),
            "evidence_status": str(item.get("evidence_status") or question.get("evidence_status") or "").strip().lower(),
            "answer_state": str(item.get("answer_state") or question.get("answer_state") or "").strip().lower(),
            "origin_agent": str(question.get("best_evidence_origin_agent") or "").strip().lower(),
            "reviewed_by": str(item.get("reviewed_by") or "").strip().lower(),
            "reviewed_at": str(item.get("reviewed_at") or "").strip(),
            "review_note": str(item.get("review_note") or "").strip(),
            "court_violation_id": str(item.get("court_violation_id") or "").strip(),
            "approval_gate_status": str(questionnaire.get("approval_gate_status") or "").strip(),
            "final_delivery_allowed": bool(questionnaire.get("final_delivery_allowed")),
            "pending_approval_count": int(questionnaire.get("pending_approval_count") or 0),
            "source_session_key": str(questionnaire.get("source_session_key") or "").strip(),
        }
        projection["bucket"] = _trust_ops_queue_bucket(projection)
        counts["total"] += 1
        if projection["bucket"] in counts:
            counts[projection["bucket"]] = int(counts.get(projection["bucket"]) or 0) + 1
        if projection["bucket"] in {"pending", "stale", "revoked", "unresolved", "draft"}:
            counts["actionable"] = int(counts.get("actionable") or 0) + 1
        queue_entries.append(projection)

    def _include_projection(projection: dict[str, Any]) -> bool:
        bucket = str(projection.get("bucket") or "").strip().lower()
        if normalized_filter == "actionable":
            return bucket in {"pending", "stale", "revoked", "unresolved", "draft"}
        if normalized_filter == "all":
            if include_cleared:
                return True
            return bucket != "approved" or bool(projection.get("approval_required"))
        return bucket == normalized_filter

    filtered_queue = [projection for projection in queue_entries if _include_projection(projection)]
    filtered_queue.sort(
        key=lambda projection: (
            1 if str(projection.get("bucket") or "") in {"pending", "stale", "revoked", "unresolved", "draft"} else 0,
            1 if bool(projection.get("critical")) else 0,
            str(projection.get("reviewed_at") or ""),
            str(projection.get("queue_id") or ""),
        ),
        reverse=True,
    )
    questionnaire_summaries = sorted(
        (
            {
                "questionnaire_id": str(item.get("questionnaire_id") or "").strip(),
                "approval_gate_status": str(item.get("approval_gate_status") or "").strip(),
                "pending_approval_count": int(item.get("pending_approval_count") or 0),
                "critical_count": int(item.get("critical_count") or 0),
                "source_session_key": str(item.get("source_session_key") or "").strip(),
                "question_count": len([question for question in list(item.get("questions") or []) if isinstance(question, dict)]),
                "final_delivery_allowed": bool(item.get("final_delivery_allowed")),
            }
            for item in questionnaires_map.values()
        ),
        key=lambda item: (
            int(item.get("pending_approval_count") or 0),
            int(item.get("critical_count") or 0),
            str(item.get("questionnaire_id") or ""),
        ),
        reverse=True,
    )
    selected_questionnaire_id = normalized_questionnaire_id
    if not selected_questionnaire_id and filtered_queue:
        selected_questionnaire_id = str(filtered_queue[0].get("questionnaire_id") or "").strip()
    if not selected_questionnaire_id and questionnaire_summaries:
        selected_questionnaire_id = str(questionnaire_summaries[0].get("questionnaire_id") or "").strip()
    selected_questionnaire = dict(questionnaires_map.get(selected_questionnaire_id) or {})
    selected_projection: dict[str, Any] | None = None
    if selected_questionnaire:
        selected_projection = {
            "questionnaire_id": str(selected_questionnaire.get("questionnaire_id") or "").strip(),
            "approval_gate_status": str(selected_questionnaire.get("approval_gate_status") or "").strip(),
            "final_delivery_allowed": bool(selected_questionnaire.get("final_delivery_allowed")),
            "pending_approval_count": int(selected_questionnaire.get("pending_approval_count") or 0),
            "critical_count": int(selected_questionnaire.get("critical_count") or 0),
            "source_session_key": str(selected_questionnaire.get("source_session_key") or "").strip(),
            "questions": [],
            "approval_queue_entries": [
                dict(entry)
                for entry in queue_entries
                if str(entry.get("questionnaire_id") or "").strip()
                == str(selected_questionnaire.get("questionnaire_id") or "").strip()
            ],
        }
        for question in [dict(item) for item in list(selected_questionnaire.get("questions") or []) if isinstance(item, dict)]:
            selected_projection["questions"].append(
                {
                    "question_id": str(question.get("question_id") or "").strip(),
                    "text": str(question.get("text") or "").strip(),
                    "critical": bool(question.get("critical")),
                    "answer_state": str(question.get("answer_state") or "").strip().lower(),
                    "approval_required": bool(question.get("approval_required")),
                    "evidence_key": str(question.get("evidence_key") or "").strip(),
                    "evidence_status": str(question.get("evidence_status") or "").strip().lower(),
                    "origin_agent": str(question.get("best_evidence_origin_agent") or "").strip().lower(),
                    "last_review_decision": str(question.get("last_review_decision") or "").strip().lower(),
                    "last_reviewed_at": str(question.get("last_reviewed_at") or "").strip(),
                    "resolution_note": str(question.get("resolution_note") or "").strip(),
                }
            )
    return {
        "summary": _build_trust_assurance_summary(payload),
        "filters": {
            "status": normalized_filter,
            "questionnaire_id": selected_questionnaire_id,
            "include_cleared": bool(include_cleared),
            "status_options": ["actionable", "all", "pending", "approved", "stale", "revoked", "unresolved", "draft"],
        },
        "counts": counts,
        "questionnaires": questionnaire_summaries,
        "queue": filtered_queue[:50],
        "selected_questionnaire": selected_projection,
    }


def _review_trust_approval_queue(
    queue_id: str,
    decision: str,
    *,
    note: str = "",
    actor: str = "",
) -> dict[str, Any] | None:
    queue_key = str(queue_id or "").strip()
    normalized_decision = str(decision or "").strip().lower()
    if not queue_key or normalized_decision not in {"approve", "stale", "revoke", "unresolved"}:
        return None
    state = _load_trust_assurance_state()
    queue_state = state.setdefault("approval_queue", {})
    queue_record = dict(queue_state.get(queue_key) or {})
    if not queue_record:
        return None
    questionnaires = state.setdefault("questionnaires", {})
    questionnaire_id = str(queue_record.get("questionnaire_id") or "").strip()
    questionnaire = dict(questionnaires.get(questionnaire_id) or {})
    if not questionnaire:
        return None
    questions = [dict(item) for item in list(questionnaire.get("questions") or []) if isinstance(item, dict)]
    question_id = str(queue_record.get("question_id") or "").strip()
    evidence_state = _load_trust_evidence_state()
    updated_question: dict[str, Any] | None = None
    prior_violation_id = str(queue_record.get("court_violation_id") or "").strip()
    for index, question in enumerate(questions):
        if str(question.get("question_id") or "").strip() != question_id:
            continue
        updated_question = dict(question)
        if normalized_decision == "approve":
            updated_question["answer_state"] = "approved"
            updated_question["approval_required"] = False
            updated_question["approved_at"] = _memory_now_iso()
            if str(updated_question.get("evidence_key") or "").strip():
                reviewed = _review_trust_evidence_entry(
                    str(updated_question.get("evidence_key") or "").strip(),
                    "approve",
                    note=note,
                    actor=actor,
                    state=evidence_state,
                )
                if reviewed:
                    updated_question["evidence_status"] = _trust_evidence_effective_status(reviewed)
        elif normalized_decision == "unresolved":
            updated_question["answer_state"] = "unresolved"
            updated_question["approval_required"] = False
            updated_question["resolution_note"] = str(note or "Marked unresolved for truthful final delivery.").strip()
        elif normalized_decision == "stale":
            updated_question["answer_state"] = "stale"
            updated_question["approval_required"] = True
            if str(updated_question.get("evidence_key") or "").strip():
                reviewed = _review_trust_evidence_entry(
                    str(updated_question.get("evidence_key") or "").strip(),
                    "stale",
                    note=note,
                    actor=actor,
                    state=evidence_state,
                )
                if reviewed:
                    updated_question["evidence_status"] = _trust_evidence_effective_status(reviewed)
        else:
            updated_question["answer_state"] = "revoked"
            updated_question["approval_required"] = True
            if str(updated_question.get("evidence_key") or "").strip():
                reviewed = _review_trust_evidence_entry(
                    str(updated_question.get("evidence_key") or "").strip(),
                    "revoke",
                    note=note,
                    actor=actor,
                    state=evidence_state,
                )
                if reviewed:
                    updated_question["evidence_status"] = _trust_evidence_effective_status(reviewed)
        updated_question["last_reviewed_at"] = _memory_now_iso()
        updated_question["last_review_decision"] = normalized_decision
        questions[index] = updated_question
        break
    if not updated_question:
        return None
    questionnaire["questions"] = questions
    _rollup_trust_questionnaire(questionnaire)
    _sync_trust_approval_queue(state, questionnaire)
    queue_record = dict(queue_state.get(queue_key) or {})
    queue_record["status"] = normalized_decision
    queue_record["approval_required"] = bool(updated_question.get("approval_required"))
    queue_record["evidence_status"] = str(updated_question.get("evidence_status") or "").strip().lower()
    queue_record["answer_state"] = str(updated_question.get("answer_state") or "").strip().lower()
    queue_record["review_note"] = str(note).strip()
    queue_record["reviewed_by"] = str(actor or "").strip().lower()
    queue_record["reviewed_at"] = _memory_now_iso()
    queue_record["updated_at"] = _memory_now_iso()
    origin_agent = str(updated_question.get("best_evidence_origin_agent") or "").strip().lower()
    if normalized_decision == "revoke" and bool(updated_question.get("critical")) and origin_agent and not prior_violation_id:
        try:
            violation_id = court_file_violation(
                agent_id=origin_agent,
                org_id=LOOM_ORG_ID,
                violation_type="trust_evidence_revoked",
                severity=3,
                evidence=(
                    f"Queue review {queue_key} revoked critical trust evidence for question: "
                    f"{str(updated_question.get('text') or '').strip()}"
                )[:500],
                policy_ref="trust_ops.approval_review",
            )
            queue_record["court_violation_id"] = str(violation_id or "").strip()
        except Exception:
            pass
    queue_state[queue_key] = queue_record
    questionnaires[questionnaire_id] = questionnaire
    _save_trust_evidence_state(evidence_state)
    _save_trust_assurance_state(state)
    session_key = str(questionnaire.get("source_session_key") or "").strip()
    extra_details: dict[str, Any] = {
        "queue_id": queue_key,
        "questionnaire_id": questionnaire_id,
        "question_id": question_id,
        "critical": bool(updated_question.get("critical")),
        "answer_state": str(updated_question.get("answer_state") or "").strip().lower(),
        "approval_required": bool(updated_question.get("approval_required")),
        "origin_agent": origin_agent,
        "court_violation_id": str(queue_record.get("court_violation_id") or "").strip(),
        "pending_approval_count": int(questionnaire.get("pending_approval_count") or 0),
        "approval_gate_status": str(questionnaire.get("approval_gate_status") or "").strip(),
    }
    if origin_agent:
        try:
            ledger = accounting_load_ledger()
            agent = dict((ledger.get("agents") or {}).get(origin_agent) or {})
            if agent:
                extra_details["authority_units"] = int(agent.get("authority_units") or 0)
                extra_details["reputation_units"] = int(agent.get("reputation_units") or 0)
        except Exception:
            pass
        try:
            extra_details["court_restrictions"] = [
                str(item).strip().lower()
                for item in list(court_get_restrictions(origin_agent, org_id=LOOM_ORG_ID) or [])
                if str(item).strip()
            ]
        except Exception:
            pass
    _record_gateway_audit(
        "trust_queue_reviewed",
        session_key=session_key or questionnaire_id or queue_key,
        channel="trust_ops",
        text=str(updated_question.get("text") or "").strip(),
        outcome=normalized_decision,
        extra_details=extra_details,
    )
    try:
        accounting_append_tx(
            {
                "type": "trust_queue_review",
                "session_key": session_key,
                "queue_id": queue_key,
                "questionnaire_id": questionnaire_id,
                "question_id": question_id,
                "decision": normalized_decision,
                "critical": bool(updated_question.get("critical")),
                "origin_agent": origin_agent,
                "actor": str(actor or "").strip().lower(),
                "note": str(note).strip(),
                "court_violation_id": str(queue_record.get("court_violation_id") or "").strip(),
            }
        )
    except Exception:
        pass
    if session_key:
        append_session_event(
            session_key,
            {
                "history_type": "trust_approval_review",
                "status": normalized_decision,
                "agent_id": TEAM_MANAGER_AGENT_ID,
                "speaker": "manager",
                "text": f"Reviewed queue item {queue_key} with decision {normalized_decision}.",
                "queue_id": queue_key,
                "questionnaire_id": questionnaire_id,
                "question_id": question_id,
                "review_note": str(note).strip(),
                "reviewed_by": str(actor or "").strip().lower(),
            },
            loom_root=LOOM_ROOT,
        )
    return {
        "queue": dict(queue_record),
        "questionnaire": {
            "questionnaire_id": questionnaire_id,
            "approval_gate_status": str(questionnaire.get("approval_gate_status") or "").strip(),
            "final_delivery_allowed": bool(questionnaire.get("final_delivery_allowed")),
            "pending_approval_count": int(questionnaire.get("pending_approval_count") or 0),
        },
        "question": dict(updated_question),
    }


def _review_trust_approval_queue_bulk(
    queue_ids: list[str] | tuple[str, ...],
    decision: str,
    *,
    note: str = "",
    actor: str = "",
) -> dict[str, Any] | None:
    normalized_decision = str(decision or "").strip().lower()
    if normalized_decision not in {"approve", "stale", "revoke", "unresolved"}:
        return None
    seen: set[str] = set()
    normalized_ids: list[str] = []
    for raw_queue_id in list(queue_ids or []):
        queue_id = str(raw_queue_id or "").strip()
        if not queue_id or queue_id in seen:
            continue
        seen.add(queue_id)
        normalized_ids.append(queue_id)
    if not normalized_ids:
        return None
    reviewed_results: list[dict[str, Any]] = []
    failed_queue_ids: list[str] = []
    questionnaire_ids: set[str] = set()
    critical_reviewed_count = 0
    source_session_keys: set[str] = set()
    for queue_id in normalized_ids:
        reviewed = _review_trust_approval_queue(
            queue_id,
            normalized_decision,
            note=note,
            actor=actor,
        )
        if not reviewed:
            failed_queue_ids.append(queue_id)
            continue
        reviewed_results.append(reviewed)
        questionnaire_ids.add(str(((reviewed.get("questionnaire") or {}).get("questionnaire_id") or "")).strip())
        if bool((reviewed.get("question") or {}).get("critical")):
            critical_reviewed_count += 1
        source_session_key = str(((reviewed.get("queue") or {}).get("source_session_key") or "")).strip()
        if source_session_key:
            source_session_keys.add(source_session_key)
    summary = {
        "decision": normalized_decision,
        "requested_count": len(normalized_ids),
        "reviewed_count": len(reviewed_results),
        "failed_queue_ids": failed_queue_ids,
        "questionnaire_ids": sorted(item for item in questionnaire_ids if item),
        "critical_reviewed_count": critical_reviewed_count,
    }
    if reviewed_results:
        _record_gateway_audit(
            "trust_queue_bulk_reviewed",
            session_key=next(iter(source_session_keys), next(iter(questionnaire_ids), normalized_ids[0])),
            channel="trust_ops",
            text=f"Bulk reviewed {len(reviewed_results)} Trust Ops queue item(s).",
            outcome=normalized_decision,
            extra_details={
                "decision": normalized_decision,
                "requested_count": len(normalized_ids),
                "reviewed_count": len(reviewed_results),
                "failed_queue_ids": failed_queue_ids,
                "questionnaire_ids": sorted(item for item in questionnaire_ids if item),
                "critical_reviewed_count": critical_reviewed_count,
                "actor": str(actor or "").strip().lower(),
            },
        )
        try:
            accounting_append_tx(
                {
                    "type": "trust_queue_bulk_review",
                    "decision": normalized_decision,
                    "requested_count": len(normalized_ids),
                    "reviewed_count": len(reviewed_results),
                    "failed_queue_ids": failed_queue_ids,
                    "questionnaire_ids": sorted(item for item in questionnaire_ids if item),
                    "actor": str(actor or "").strip().lower(),
                    "note": str(note).strip(),
                }
            )
        except Exception:
            pass
    return {
        "summary": summary,
        "results": reviewed_results,
        "trust_ops": _build_trust_assurance_summary(),
    }


def _apply_security_questionnaire_workflow(
    request_text: str,
    session_key: str,
    skill_names: list[str],
    *,
    trust_packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    questionnaire = _build_questionnaire_state(
        request_text,
        session_key,
        skill_names,
        trust_packet=trust_packet,
    )
    return {
        "questionnaire": questionnaire,
        "rendered_artifact": _render_questionnaire_answer_pack(questionnaire),
        "approval_queue_entries": [
            dict(item)
            for item in list(questionnaire.get("approval_queue_entries") or [])
            if isinstance(item, dict)
        ],
        "approval_gate_status": str(questionnaire.get("approval_gate_status") or "").strip(),
        "final_delivery_allowed": bool(questionnaire.get("final_delivery_allowed")),
    }


def _atlas_memory_research_block(
    memory_packet: dict[str, Any] | None,
    request: str,
    skill_names: list[str] | None = None,
) -> str:
    entries = [dict(item) for item in list(dict(memory_packet or {}).get("entries") or []) if isinstance(item, dict)]
    if not entries:
        return ""
    lowered_skills = {str(item or "").strip().lower() for item in list(skill_names or []) if str(item or "").strip()}
    ranked = sorted(
        entries,
        key=lambda item: (
            3 if str(item.get("category") or "").strip().lower() == "successful_output" else
            2 if str(item.get("category") or "").strip().lower() == "user_fact" else 1,
            1 if lowered_skills.intersection(set(_memory_entry_skills(item))) else 0,
            int(item.get("fit_score") or 0),
            int(item.get("memory_value_score") or 0),
        ),
        reverse=True,
    )
    shortlist = ranked[:3]
    if not shortlist:
        return ""
    lines = [
        "Governed memory shortlist for research planning:",
        "Use this only as prior bounded context and reusable patterns. Do not treat it as live evidence.",
    ]
    for item in shortlist:
        category = str(item.get("category") or "").strip().lower()
        if category == "successful_output":
            label = "Reusable prior pattern"
        elif category == "user_fact":
            label = "Known user fact"
        else:
            label = "Stable Meridian context"
        skills_label = ", ".join(_memory_entry_skills(item)[:2])
        skills_suffix = f"; skills={skills_label}" if skills_label else ""
        lines.append(
            f"- {label} [{str(item.get('heading') or 'Memory').strip()}] "
            f"(fit={int(item.get('fit_score') or 0)}, value={int(item.get('memory_value_score') or 0)}{skills_suffix}): "
            f"{_memory_inline_digest(str(item.get('content') or ''), limit=220)}"
        )
    return "\n".join(lines).strip()


def _memory_packet_keys(memory_packet: dict[str, Any] | None) -> list[str]:
    return [
        str(item.get("key") or "").strip()
        for item in list(dict(memory_packet or {}).get("entries") or [])
        if isinstance(item, dict) and str(item.get("key") or "").strip()
    ]


def _live_skill_registry_root() -> bool:
    try:
        return Path(TEAM_SKILLS.root).resolve() == SKILLS_DIR.resolve()
    except Exception:
        return False


def _governed_skill_autonomy_begin(
    *,
    request: str,
    session_key: str,
    manager_brief: str,
    phase: str,
    skill_name: str,
) -> dict[str, Any]:
    estimated_cost = SKILL_SYNTHESIS_CREATE_COST_USD if phase == "create" else SKILL_SYNTHESIS_REFINE_COST_USD
    action = f"governed_skill_synthesis_{phase}"
    payload = {
        "request": str(request or "").strip(),
        "manager_brief": str(manager_brief or "").strip(),
        "phase": phase,
        "skill_name": skill_name,
        "session_key": session_key,
    }
    try:
        budget = treasury_reserve_runtime_budget(
            TEAM_MANAGER_AGENT_ID,
            estimated_cost,
            org_id=LOOM_ORG_ID,
            action=action,
            resource=skill_name,
            context=payload,
            lease_seconds=300,
            policy_ref=GOVERNED_SKILL_SYNTHESIS_POLICY_REF,
        )
    except (SystemExit, Exception) as exc:
        return {
            "allowed": False,
            "phase": phase,
            "skill_name": skill_name,
            "estimated_cost_usd": estimated_cost,
            "budget": {},
            "reason": f"governance_unavailable: {str(exc).strip()}",
            "error_type": type(exc).__name__,
        }
    if not bool(budget.get("allowed")):
        return {
            "allowed": False,
            "phase": phase,
            "skill_name": skill_name,
            "estimated_cost_usd": estimated_cost,
            "budget": budget,
            "reason": str(budget.get("reason") or "budget reservation denied").strip(),
        }
    reservation = dict(budget.get("reservation") or {})
    try:
        warrant = warrants_issue_warrant(
            LOOM_ORG_ID,
            "budget_spend",
            GOVERNED_SKILL_BOUNDARY_NAME,
            TEAM_MANAGER_AGENT_ID,
            session_id=session_key,
            request_payload=payload,
            risk_class="moderate" if phase == "create" else "low",
            evidence_refs=[f"session:{session_key}", f"skill:{skill_name}"],
            policy_refs=[GOVERNED_SKILL_SYNTHESIS_POLICY_REF],
            note=f"Governed dynamic skill synthesis ({phase}) for {skill_name}",
        )
        approved = warrants_review_warrant(
            str(warrant.get("warrant_id") or "").strip(),
            "approve",
            "system:leviathann-governor",
            org_id=LOOM_ORG_ID,
            note="Bounded internal skill synthesis approved under governed autonomy policy.",
        )
        validated = warrants_validate_warrant_for_execution(
            str(warrant.get("warrant_id") or "").strip(),
            org_id=LOOM_ORG_ID,
            action_class="budget_spend",
            boundary_name=GOVERNED_SKILL_BOUNDARY_NAME,
            actor_id=TEAM_MANAGER_AGENT_ID,
            session_id=session_key,
            request_payload=payload,
        )
    except (SystemExit, Exception) as exc:
        reservation_id = str(reservation.get("reservation_id") or "").strip()
        if reservation_id:
            try:
                treasury_release_runtime_budget(
                    reservation_id,
                    TEAM_MANAGER_AGENT_ID,
                    org_id=LOOM_ORG_ID,
                    status="aborted",
                    reason=f"governance_path_failed:{phase}",
                    refs={"skill_name": skill_name, "error_type": type(exc).__name__},
                )
            except (SystemExit, Exception):
                pass
        return {
            "allowed": False,
            "phase": phase,
            "skill_name": skill_name,
            "estimated_cost_usd": estimated_cost,
            "budget": budget,
            "reservation": reservation,
            "reason": f"governance_warrant_failed: {str(exc).strip()}",
            "error_type": type(exc).__name__,
        }
    return {
        "allowed": True,
        "phase": phase,
        "skill_name": skill_name,
        "estimated_cost_usd": estimated_cost,
        "budget": budget,
        "reservation": reservation,
        "warrant": dict(warrant or {}),
        "approved_warrant": dict(approved or {}),
        "validated_warrant": dict(validated or {}),
        "reason": "ok",
    }


def _governed_skill_autonomy_finish(
    governance: dict[str, Any] | None,
    *,
    executed: bool,
    note: str = "",
    extra_refs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = dict(governance or {})
    if not bool(state.get("allowed")):
        return state
    reservation = dict(state.get("reservation") or {})
    reservation_id = str(reservation.get("reservation_id") or "").strip()
    warrant_id = str(dict(state.get("warrant") or {}).get("warrant_id") or "").strip()
    if not reservation_id:
        return state
    if executed:
        commit = treasury_commit_runtime_budget(
            reservation_id,
            actual_cost_usd=float(state.get("estimated_cost_usd") or 0.0),
            org_id=LOOM_ORG_ID,
            note=note or "governed skill synthesis executed",
        )
        if warrant_id:
            warrants_mark_warrant_executed(
                warrant_id,
                org_id=LOOM_ORG_ID,
                execution_refs={
                    "reservation_id": reservation_id,
                    "skill_name": str(state.get("skill_name") or "").strip(),
                    "phase": str(state.get("phase") or "").strip(),
                    **dict(extra_refs or {}),
                },
            )
        state["commit"] = commit
    else:
        release = treasury_release_runtime_budget(
            reservation_id,
            org_id=LOOM_ORG_ID,
            reason=note or "governed skill synthesis not executed",
        )
        state["release"] = release
    return state


def _eligible_user_session_for_economy(session_key: str, skill_names: list[str] | None = None) -> bool:
    normalized = str(session_key or "").strip().lower()
    if not normalized:
        return False
    if normalized.startswith("cron:"):
        return False
    if normalized.startswith("web_api:loom-schedule"):
        return False
    if normalized.startswith("web_api:notifications"):
        return False
    if not (normalized.startswith("web_api:") or normalized.startswith("telegram:")):
        return False
    return bool([str(item or "").strip() for item in list(skill_names or []) if str(item or "").strip()])


def _economy_handle_for_agent_id(agent_id: str) -> str:
    normalized = str(agent_id or "").strip()
    if not normalized:
        return ""
    if normalized == TEAM_MANAGER_AGENT_ID:
        return str(TEAM_TOPOLOGY.manager.handle or "").strip()
    specialist = TEAM_TOPOLOGY.specialist_by_id(normalized)
    if specialist:
        return str(specialist.handle or "").strip()
    return normalized.removeprefix("agent_").strip().lower()


def _apply_user_session_delta(agent: dict[str, Any], rep_delta: int, auth_delta: int) -> tuple[int, int, int, int]:
    old_rep = int(agent.get("reputation_units") or 0)
    old_auth = int(agent.get("authority_units") or 0)
    actual_rep = int(rep_delta)
    actual_auth = int(auth_delta)
    if agent.get("zero_authority") and actual_auth > 0:
        actual_auth = 0
    if agent.get("probation") and actual_rep > 0:
        actual_rep = max(1, actual_rep // 2)
    new_rep = max(0, min(100, old_rep + actual_rep))
    new_auth = max(0, min(100, old_auth + actual_auth))
    return new_rep, new_auth, actual_rep, actual_auth


def _artifact_source_from_repairs(repair_warnings: list[str]) -> str:
    lowered = {str(item or "").strip().lower() for item in list(repair_warnings or [])}
    if "manager_response_repaired_from_best_worker_artifact" in lowered:
        return "worker_artifact"
    if "manager_response_repaired_from_worker_artifact" in lowered:
        return "worker_artifact"
    if "manager_response_repaired_from_salvage_template" in lowered:
        return "salvage_template"
    if "bounded_competitor_scan_salvaged_after_research_failure" in lowered:
        return "salvage_template"
    return "manager_response"


def _normalize_delivery_fingerprint_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text[:4000]


def _build_delivery_fingerprint(
    request_text: str,
    delivery_text: str,
    *,
    session_key: str,
    skill_names: list[str] | None = None,
    artifact_source: str = "",
) -> str:
    fingerprint_payload = {
        "channel": str(session_key or "").split(":", 1)[0].strip().lower(),
        "request": _normalize_delivery_fingerprint_text(request_text),
        "delivery": _normalize_delivery_fingerprint_text(delivery_text),
        "skills": sorted(
            str(item or "").strip().lower()
            for item in list(skill_names or [])
            if str(item or "").strip()
        ),
        "artifact_source": str(artifact_source or "").strip().lower(),
    }
    raw = json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True)
    return f"udf_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:20]}"


def _delivery_contributors_snapshot(
    steps: list[dict[str, Any]],
    request_text: str = "",
    skill_names: list[str] | None = None,
    final_artifact: str = "",
) -> list[dict[str, Any]]:
    contributors: list[dict[str, Any]] = []
    normalized_final_artifact = ""
    if final_artifact:
        coerced_final_artifact = (
            _coerce_request_specific_artifact(final_artifact, request_text)
            if request_text
            else str(final_artifact or "").strip()
        )
        normalized_final_artifact = _normalize_delivery_fingerprint_text(coerced_final_artifact)
    for step in list(steps or []):
        agent_id = str(step.get("agent_id") or "").strip()
        warnings = _step_warning_texts(step)[:6]
        raw_result = _step_result_text(step)
        coerced_artifact = (
            _coerce_request_specific_artifact(raw_result, request_text)
            if request_text
            else raw_result
        )
        normalized_step_artifact = _normalize_delivery_fingerprint_text(coerced_artifact) if coerced_artifact else ""
        citations = step.get("citations") if isinstance(step.get("citations"), list) else []
        fit_score = (
            _step_artifact_fit_score(step, request_text, list(skill_names or []))
            if request_text
            else (12 if _step_has_usable_artifact(step) else -100)
        )
        contributors.append(
            {
                "agent_id": agent_id,
                "economy_key": _economy_handle_for_agent_id(agent_id),
                "role": str(step.get("role") or "").strip(),
                "task_kind": str(step.get("task_kind") or "").strip(),
                "status": str(step.get("status") or "").strip().lower(),
                "usable_artifact": _step_has_usable_artifact(step),
                "qa_pass": str(step.get("task_kind") or "").strip() == "qa_gate"
                and "pass" in _step_result_text(step).lower(),
                "qa_fail": str(step.get("task_kind") or "").strip() == "qa_gate"
                and "fail" in _step_result_text(step).lower(),
                "drift_rewritten": any(
                    "quill_output_drift_rewritten_to_user_artifact" in str(item or "").strip().lower()
                    for item in warnings
                ),
                "warnings": warnings,
                "artifact_fit_score": fit_score,
                "artifact_matches_shape": bool(
                    request_text
                    and coerced_artifact
                    and _artifact_matches_skill_shape(coerced_artifact, request_text, list(skill_names or []))
                ),
                "matches_final_artifact": bool(
                    normalized_final_artifact
                    and normalized_step_artifact
                    and normalized_step_artifact == normalized_final_artifact
                ),
                "citation_count": len(citations),
                "confidence_bonus": _confidence_fit_bonus(step.get("confidence")),
                "hard_blocker_count": sum(1 for item in warnings if _warning_is_hard_blocker(item)),
                "runtime_failure_count": sum(1 for item in warnings if _warning_is_runtime_failure(item)),
                "recoverable_gap_count": sum(1 for item in warnings if _warning_is_recoverable_gap(item)),
                "informational_warning_count": sum(1 for item in warnings if _warning_is_informational(item)),
            }
        )
    best_fit_score = max(
        (
            int(item.get("artifact_fit_score") or -100)
            for item in contributors
            if str(item.get("status") or "").strip().lower() == "ok"
        ),
        default=-100,
    )
    for item in contributors:
        item["best_fit_contributor"] = best_fit_score > 0 and int(item.get("artifact_fit_score") or -100) == best_fit_score
    return contributors


def _contributor_support_level(contributor: dict[str, Any]) -> str:
    fit_score = int(contributor.get("artifact_fit_score") or -100)
    if bool(contributor.get("matches_final_artifact")):
        return "primary"
    if bool(contributor.get("best_fit_contributor")) and fit_score >= 36:
        return "primary"
    if bool(contributor.get("artifact_matches_shape")) or fit_score >= 28:
        return "supporting"
    if bool(contributor.get("usable_artifact")):
        return "weak"
    return "none"


def _contributors_show_writer_issue(contributors: list[dict[str, Any]]) -> bool:
    for contributor in list(contributors or []):
        if str(contributor.get("task_kind") or "").strip().lower() != "write":
            continue
        if not bool(contributor.get("usable_artifact")):
            return True
        if bool(contributor.get("drift_rewritten")):
            return True
        if int(contributor.get("artifact_fit_score") or -100) < 18:
            return True
        if int(contributor.get("hard_blocker_count") or 0) > 0:
            return True
    return False


def _delivery_warning_texts(event: dict[str, Any]) -> list[str]:
    return [str(item).strip() for item in list(event.get("warnings") or []) if str(item).strip()]


def _delivery_has_only_recoverable_warnings(event: dict[str, Any]) -> bool:
    warnings = _delivery_warning_texts(event)
    if not warnings:
        return False
    return all(_warning_is_informational(item) or _warning_is_recoverable_gap(item) for item in warnings)


def _remember_user_session_agent_outcome(
    state: dict[str, Any],
    *,
    agent_key: str,
    delivery_fingerprint: str,
    session_key: str,
    quality_status: str,
    sanction_relevant: bool,
) -> list[dict[str, Any]]:
    agent_outcomes = state.setdefault("agent_outcomes", {})
    bucket = agent_outcomes.get(agent_key)
    if not isinstance(bucket, list):
        bucket = []
    bucket = [
        item for item in bucket
        if isinstance(item, dict) and str(item.get("delivery_fingerprint") or "").strip() != delivery_fingerprint
    ]
    bucket.append(
        {
            "delivery_fingerprint": delivery_fingerprint,
            "session_key": session_key,
            "quality_status": quality_status,
            "sanction_relevant": bool(sanction_relevant),
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )
    bucket = bucket[-24:]
    agent_outcomes[agent_key] = bucket
    return [dict(item) for item in bucket if isinstance(item, dict)]


def _recent_bad_outcome_count(outcomes: list[dict[str, Any]]) -> int:
    count = 0
    for item in list(outcomes or []):
        if not isinstance(item, dict):
            continue
        if not bool(item.get("sanction_relevant")):
            continue
        quality_status = str(item.get("quality_status") or "").strip().lower()
        if quality_status in {"partial", "failure"}:
            count += 1
    return count


def _severity_with_existing_restrictions(base_severity: int, restrictions: list[str]) -> int:
    severity = max(1, min(6, int(base_severity)))
    if restrictions:
        return min(severity, 2)
    return severity


def _build_user_session_court_candidates(
    *,
    session_key: str,
    delivery_event: dict[str, Any],
    artifact_source: str,
    quality_status: str,
    contributors: list[dict[str, Any]],
    skill_names: list[str],
    state: dict[str, Any],
    delivery_fingerprint: str,
) -> list[dict[str, Any]]:
    if quality_status not in {"partial", "failure"}:
        return []
    if _delivery_has_only_recoverable_warnings(delivery_event):
        return []

    candidates: list[dict[str, Any]] = []
    current_manager_restrictions = court_get_restrictions(TEAM_TOPOLOGY.manager.handle, org_id=LOOM_ORG_ID) or []
    manager_outcomes = _remember_user_session_agent_outcome(
        state,
        agent_key=TEAM_TOPOLOGY.manager.handle,
        delivery_fingerprint=delivery_fingerprint,
        session_key=session_key,
        quality_status=quality_status,
        sanction_relevant=True,
    )
    manager_bad_count = _recent_bad_outcome_count(manager_outcomes)
    manager_severity = 3 if quality_status == "failure" else 2
    if artifact_source == "salvage_template":
        manager_severity = max(manager_severity, 4)
    if manager_bad_count >= 3:
        manager_severity = min(5, manager_severity + 1)
    manager_severity = _severity_with_existing_restrictions(manager_severity, current_manager_restrictions)
    candidates.append(
        {
            "agent_key": TEAM_TOPOLOGY.manager.handle,
            "violation_type": "rework" if artifact_source == "salvage_template" and quality_status == "failure" else "rejected_output",
            "severity": manager_severity,
            "evidence": (
                f"User-session delivery {delivery_fingerprint} on {session_key} shipped as {quality_status} "
                f"from {artifact_source}. Leviathann had to carry final responsibility for the user-facing artifact."
            ),
        }
    )

    for contributor in contributors:
        agent_key = str(contributor.get("economy_key") or "").strip().lower()
        if not agent_key:
            continue
        task_kind = str(contributor.get("task_kind") or "").strip().lower()
        status = str(contributor.get("status") or "").strip().lower()
        usable = bool(contributor.get("usable_artifact"))
        drift_rewritten = bool(contributor.get("drift_rewritten"))
        fit_score = int(contributor.get("artifact_fit_score") or -100)
        matches_shape = bool(contributor.get("artifact_matches_shape"))
        matches_final_artifact = bool(contributor.get("matches_final_artifact"))
        hard_blocker_count = int(contributor.get("hard_blocker_count") or 0)
        warnings = [str(item).strip() for item in list(contributor.get("warnings") or []) if str(item).strip()]
        restrictions = court_get_restrictions(agent_key, org_id=LOOM_ORG_ID) or []

        candidate: dict[str, Any] | None = None
        if task_kind == "write" and (
            drift_rewritten
            or (quality_status == "failure" and not usable)
            or (fit_score < 18 and (matches_final_artifact or usable))
            or hard_blocker_count > 0
        ):
            severity = 4 if quality_status == "failure" else 3
            agent_outcomes = _remember_user_session_agent_outcome(
                state,
                agent_key=agent_key,
                delivery_fingerprint=delivery_fingerprint,
                session_key=session_key,
                quality_status=quality_status,
                sanction_relevant=True,
            )
            if _recent_bad_outcome_count(agent_outcomes) >= 3:
                severity = min(5, severity + 1)
            if fit_score < 12 or hard_blocker_count > 0:
                severity = min(5, severity + 1)
            candidate = {
                "agent_key": agent_key,
                "violation_type": "rework",
                "severity": _severity_with_existing_restrictions(severity, restrictions),
                "evidence": (
                    f"Writer contribution on {delivery_fingerprint} required manager repair or remained unusable. "
                    f"status={status}, drift_rewritten={drift_rewritten}, usable={usable}, "
                    f"fit_score={fit_score}, matches_shape={matches_shape}, matches_final_artifact={matches_final_artifact}, "
                    f"hard_blockers={hard_blocker_count}."
                ),
            }
        elif task_kind == "execute" and status in {"error", "timeout"} and quality_status == "failure":
            agent_outcomes = _remember_user_session_agent_outcome(
                state,
                agent_key=agent_key,
                delivery_fingerprint=delivery_fingerprint,
                session_key=session_key,
                quality_status=quality_status,
                sanction_relevant=True,
            )
            severity = 4 if _recent_bad_outcome_count(agent_outcomes) < 3 else 5
            candidate = {
                "agent_key": agent_key,
                "violation_type": "critical_failure",
                "severity": _severity_with_existing_restrictions(severity, restrictions),
                "evidence": (
                    f"Execution lane failed during user delivery {delivery_fingerprint}. "
                    f"status={status}. warnings={'; '.join(warnings[:3]) or 'none'}."
                ),
            }
        else:
            _remember_user_session_agent_outcome(
                state,
                agent_key=agent_key,
                delivery_fingerprint=delivery_fingerprint,
                session_key=session_key,
                quality_status=quality_status,
                sanction_relevant=False,
            )

        if candidate and int(candidate.get("severity") or 0) >= 3:
            candidates.append(candidate)

    return candidates


def _apply_user_session_court_actions(
    *,
    state: dict[str, Any],
    session_key: str,
    delivery_fingerprint: str,
    delivery_event_id: str,
    delivery_event: dict[str, Any],
    artifact_source: str,
    quality_status: str,
    skill_names: list[str],
    contributors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates = _build_user_session_court_candidates(
        session_key=session_key,
        delivery_event=delivery_event,
        artifact_source=artifact_source,
        quality_status=quality_status,
        contributors=contributors,
        skill_names=skill_names,
        state=state,
        delivery_fingerprint=delivery_fingerprint,
    )
    if not candidates:
        return []

    court_state = state.setdefault("court_actions", {})
    if not isinstance(court_state, dict):
        court_state = {}
        state["court_actions"] = court_state

    actions: list[dict[str, Any]] = []
    for candidate in candidates:
        agent_key = str(candidate.get("agent_key") or "").strip().lower()
        if not agent_key:
            continue
        court_key = f"{delivery_fingerprint}:{agent_key}"
        if court_key in court_state:
            previous = court_state.get(court_key)
            if isinstance(previous, dict):
                actions.append(dict(previous))
            continue
        try:
            violation_id = court_file_violation(
                agent_id=agent_key,
                org_id=LOOM_ORG_ID,
                violation_type=str(candidate.get("violation_type") or "rejected_output"),
                severity=int(candidate.get("severity") or 3),
                evidence=str(candidate.get("evidence") or "").strip(),
                policy_ref="user_session_scoring.court_loop",
            )
            action = {
                "agent": agent_key,
                "violation_id": violation_id,
                "severity": int(candidate.get("severity") or 3),
                "violation_type": str(candidate.get("violation_type") or "rejected_output"),
                "delivery_fingerprint": delivery_fingerprint,
                "session_key": session_key,
                "session_event_id": delivery_event_id,
                "quality_status": quality_status,
                "artifact_source": artifact_source,
                "skills_used": list(skill_names),
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            court_state[court_key] = action
            actions.append(dict(action))
        except Exception as exc:
            actions.append(
                {
                    "agent": agent_key,
                    "error": f"{exc.__class__.__name__}: {exc}",
                    "delivery_fingerprint": delivery_fingerprint,
                }
            )
    return actions


def _score_user_session_delivery(session_key: str, delivery_event_id: str) -> dict[str, Any] | None:
    if not delivery_event_id:
        return None
    state = _load_user_session_score_state()
    if delivery_event_id in state.get("scored_events", {}):
        return None

    payload = load_session_events(session_key, loom_root=LOOM_ROOT) or {}
    events = [event for event in list(payload.get("events") or []) if isinstance(event, dict)]
    delivery_event = next(
        (event for event in reversed(events) if str(event.get("event_id") or "") == delivery_event_id),
        None,
    )
    if not delivery_event:
        return None

    skill_names = [str(item).strip() for item in list(delivery_event.get("skills_used") or []) if str(item).strip()]
    lowered_skill_names = {item.lower() for item in skill_names}
    if not _eligible_user_session_for_economy(session_key, skill_names):
        return None

    artifact_source = str(delivery_event.get("artifact_source") or "manager_response").strip() or "manager_response"
    request_text = str(delivery_event.get("request_text") or "").strip()
    delivery_fingerprint = str(delivery_event.get("delivery_fingerprint") or "").strip()
    if not delivery_fingerprint:
        delivery_fingerprint = _build_delivery_fingerprint(
            request_text,
            str(delivery_event.get("text") or ""),
            session_key=session_key,
            skill_names=skill_names,
            artifact_source=artifact_source,
        )
    if delivery_fingerprint in state.get("scored_fingerprints", {}):
        state.setdefault("scored_events", {})[delivery_event_id] = {
            "session_key": session_key,
            "scored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "quality_status": str(delivery_event.get("status") or "partial").strip().lower(),
            "artifact_source": artifact_source,
            "delivery_fingerprint": delivery_fingerprint,
            "deduped_by_fingerprint": True,
        }
        _save_user_session_score_state(state)
        return None
    quality_status = str(delivery_event.get("status") or "partial").strip().lower()
    if quality_status not in {"success", "partial", "failure"}:
        quality_status = "partial"
    contributors = [item for item in list(delivery_event.get("contributors") or []) if isinstance(item, dict)]
    research_skill_active = (
        "scan-doi-thu" in lowered_skill_names
        or "safe-web-research" in lowered_skill_names
        or any("research" in name for name in lowered_skill_names)
    )

    ledger = accounting_load_ledger()
    agents = ledger.get("agents") or {}
    deltas: dict[str, dict[str, Any]] = {}
    writer_issue_detected = _contributors_show_writer_issue(contributors)
    contributor_agent_keys = {
        str(item.get("economy_key") or "").strip().lower()
        for item in contributors
        if isinstance(item, dict) and str(item.get("economy_key") or "").strip()
    }

    def add_delta(agent_key: str, rep_delta: int, auth_delta: int, reason: str) -> None:
        normalized = str(agent_key or "").strip().lower()
        if not normalized or normalized not in agents:
            return
        bucket = deltas.setdefault(normalized, {"rep": 0, "auth": 0, "reasons": []})
        bucket["rep"] += int(rep_delta)
        bucket["auth"] += int(auth_delta)
        if reason and reason not in bucket["reasons"]:
            bucket["reasons"].append(reason)

    base = USER_SESSION_SCORE_DELTAS.get(artifact_source, USER_SESSION_SCORE_DELTAS["manager_response"]).get(quality_status, {})
    for agent_key, delta in base.items():
        add_delta(agent_key, int(delta[0]), int(delta[1]), f"{artifact_source}:{quality_status}")

    for contributor in contributors:
        agent_key = str(contributor.get("economy_key") or "").strip().lower()
        if not agent_key:
            continue
        task_kind = str(contributor.get("task_kind") or "").strip().lower()
        status = str(contributor.get("status") or "").strip().lower()
        usable = bool(contributor.get("usable_artifact"))
        qa_pass = bool(contributor.get("qa_pass"))
        qa_fail = bool(contributor.get("qa_fail"))
        drift_rewritten = bool(contributor.get("drift_rewritten"))
        fit_score = int(contributor.get("artifact_fit_score") or -100)
        matches_shape = bool(contributor.get("artifact_matches_shape"))
        matches_final_artifact = bool(contributor.get("matches_final_artifact"))
        citation_count = int(contributor.get("citation_count") or 0)
        hard_blocker_count = int(contributor.get("hard_blocker_count") or 0)
        runtime_failure_count = int(contributor.get("runtime_failure_count") or 0)
        support_level = _contributor_support_level(contributor)

        if task_kind == "research" and research_skill_active and status == "ok" and quality_status in {"success", "partial"}:
            rep_delta = 0
            auth_delta = 0
            if support_level == "primary":
                rep_delta = 4 if quality_status == "success" else 2
                auth_delta = 3 if quality_status == "success" else 2
            elif support_level == "supporting":
                rep_delta = 3 if quality_status == "success" else 1
                auth_delta = 1
            elif usable:
                rep_delta = 1
                if fit_score >= 20:
                    auth_delta = 1 if quality_status in {"success", "partial"} else 0
            rep_delta += min(citation_count, 2)
            if hard_blocker_count:
                rep_delta -= 1
                auth_delta -= 1
            if rep_delta or auth_delta:
                add_delta(agent_key, rep_delta, auth_delta, f"research_input_{support_level}")
        elif task_kind == "write" and status == "ok":
            if artifact_source == "worker_artifact" and usable:
                if support_level == "primary":
                    add_delta(
                        agent_key,
                        7 if quality_status == "success" else 4,
                        6 if quality_status == "success" else 3,
                        "writer_primary_artifact_shipped",
                    )
                elif support_level == "supporting":
                    add_delta(
                        agent_key,
                        4 if quality_status == "success" else 2,
                        3 if quality_status == "success" else 1,
                        "writer_supporting_artifact_shipped",
                    )
                elif fit_score < 18 or hard_blocker_count:
                    add_delta(agent_key, 0, -1 if quality_status != "success" else 0, "writer_low_fit_artifact_shipped")
            elif artifact_source == "manager_response":
                if matches_final_artifact or support_level == "primary":
                    add_delta(
                        agent_key,
                        5 if quality_status == "success" else 2,
                        4 if quality_status == "success" else 1,
                        "writer_best_fit_supported_manager_answer",
                    )
                elif drift_rewritten or fit_score < 18 or hard_blocker_count:
                    add_delta(
                        agent_key,
                        1 if quality_status == "success" else 0,
                        -1 if quality_status in {"partial", "failure"} else 0,
                        "writer_draft_needed_manager_repair",
                    )
                elif usable or matches_shape:
                    add_delta(
                        agent_key,
                        3 if quality_status == "success" else 1,
                        2 if quality_status == "success" else 1,
                        "writer_supported_manager_answer",
                    )
            elif artifact_source == "salvage_template":
                if drift_rewritten or fit_score < 18 or hard_blocker_count:
                    add_delta(agent_key, 0, -1 if quality_status == "failure" else 0, "writer_drift_forced_salvage")
                elif usable or support_level == "supporting":
                    add_delta(agent_key, 1, 0, "writer_partial_input_salvaged")
        elif task_kind == "qa_gate":
            if qa_pass and quality_status in {"success", "partial"}:
                add_delta(agent_key, 2 if quality_status == "success" else 1, 2 if quality_status == "success" else 1, "qa_gate_confirmed")
            elif qa_fail and writer_issue_detected:
                add_delta(
                    agent_key,
                    2 if quality_status == "failure" else 1,
                    1 if quality_status in {"partial", "failure"} else 0,
                    "qa_gate_caught_low_fit_artifact",
                )
            elif qa_fail and quality_status == "failure":
                add_delta(agent_key, -1, -2, "qa_gate_blocked_delivery")
        elif task_kind == "execute":
            if status == "ok" and quality_status == "success":
                add_delta(agent_key, 2, 2, "execution_supported_delivery")
            elif status in {"error", "timeout"}:
                add_delta(agent_key, -1 if runtime_failure_count else 0, -1, "execution_lane_failed")
        elif task_kind == "compress" and status == "ok" and quality_status == "success":
            add_delta(agent_key, 1, 1, "compression_supported_delivery")
        elif task_kind == "verify" and qa_pass and quality_status == "success":
            add_delta(agent_key, 1, 1, "verification_supported_delivery")

    memory_entries = [item for item in list(delivery_event.get("memory_entries") or []) if isinstance(item, dict)]
    for memory_entry in memory_entries:
        origin_agent = str(memory_entry.get("origin_agent") or "").strip().lower()
        if not origin_agent or origin_agent not in agents:
            continue
        category = str(memory_entry.get("category") or "").strip().lower()
        if category != "successful_output":
            continue
        fit_score = int(memory_entry.get("fit_score") or 0)
        value_score = int(memory_entry.get("memory_value_score") or 0)
        source_quality_status = str(memory_entry.get("source_quality_status") or "").strip().lower()
        source_skill_names = {
            str(item or "").strip().lower()
            for item in list(memory_entry.get("source_skill_names") or [])
            if str(item or "").strip()
        }
        same_skill = bool(lowered_skill_names.intersection(source_skill_names))
        origin_is_current_contributor = origin_agent in contributor_agent_keys

        if quality_status == "success" and fit_score >= 18:
            support_tier = "weak"
            if same_skill and fit_score >= 64 and source_quality_status == "success":
                support_tier = "primary"
            elif (same_skill and fit_score >= 34) or (fit_score >= 48 and value_score >= 3):
                support_tier = "supporting"

            if support_tier == "primary":
                rep_delta = 4
                auth_delta = 3
                if value_score >= 4:
                    rep_delta += 1
                if origin_is_current_contributor:
                    auth_delta = max(2, auth_delta - 1)
            elif support_tier == "supporting":
                rep_delta = 2 if same_skill else 1
                auth_delta = 1
                if value_score >= 4:
                    rep_delta += 1
                if source_quality_status == "success" and fit_score >= 40:
                    auth_delta += 1
                if origin_is_current_contributor:
                    rep_delta = max(1, rep_delta - 1)
            else:
                rep_delta = 1
                auth_delta = 0
                if origin_is_current_contributor:
                    rep_delta = 0
            if rep_delta or auth_delta:
                add_delta(origin_agent, rep_delta, auth_delta, f"memory_recall_supported_delivery_{support_tier}")
        elif quality_status == "partial" and fit_score >= 18 and value_score < 0:
            add_delta(origin_agent, -1, -1, "memory_recall_low_value_drag")
        elif quality_status == "failure" and fit_score >= 18:
            rep_penalty = -2 if value_score < 0 else -1
            auth_penalty = -2 if value_score < 0 else -1
            if origin_is_current_contributor:
                rep_penalty = max(rep_penalty, -1)
                auth_penalty = max(auth_penalty, -1)
            add_delta(origin_agent, rep_penalty, auth_penalty, "memory_recall_failed_delivery")

    evidence_entries = [item for item in list(delivery_event.get("evidence_entries") or []) if isinstance(item, dict)]
    for evidence_entry in evidence_entries:
        origin_agent = str(evidence_entry.get("origin_agent") or "").strip().lower()
        if not origin_agent or origin_agent not in agents:
            continue
        fit_score = int(evidence_entry.get("fit_score") or 0)
        approval_status = str(evidence_entry.get("approval_status") or "").strip().lower()
        source_skill_names = {
            str(item or "").strip().lower()
            for item in list(evidence_entry.get("source_skill_names") or [])
            if str(item or "").strip()
        }
        same_skill = bool(lowered_skill_names.intersection(source_skill_names))
        if quality_status == "success" and approval_status == "approved" and fit_score >= 18:
            support_tier = "weak"
            if same_skill and fit_score >= 60:
                support_tier = "primary"
            elif same_skill or fit_score >= 36:
                support_tier = "supporting"
            if support_tier == "primary":
                add_delta(origin_agent, 4, 3, "trust_evidence_supported_delivery_primary")
            elif support_tier == "supporting":
                add_delta(origin_agent, 2, 1, "trust_evidence_supported_delivery_supporting")
            else:
                add_delta(origin_agent, 1, 0, "trust_evidence_supported_delivery_weak")
        elif quality_status == "partial" and approval_status in {"draft", "stale"} and fit_score >= 24:
            add_delta(origin_agent, 0, -1, "trust_evidence_dragged_partial_delivery")

    evidence_update_event = next(
        (
            event for event in reversed(events)
            if str(event.get("history_type") or "").strip() == "trust_evidence_update"
        ),
        None,
    )
    if isinstance(evidence_update_event, dict):
        for evidence_entry in list(evidence_update_event.get("evidence_entries") or []):
            if not isinstance(evidence_entry, dict):
                continue
            origin_agent = str(evidence_entry.get("origin_agent") or "").strip().lower()
            if not origin_agent or origin_agent not in agents:
                continue
            approval_status = str(evidence_entry.get("approval_status") or "").strip().lower()
            kind = str(evidence_entry.get("kind") or "").strip().lower()
            if approval_status == "approved":
                rep_delta = 3 if kind == "watch_brief" else 4
                auth_delta = 2 if kind == "watch_brief" else 3
                add_delta(origin_agent, rep_delta, auth_delta, f"trust_evidence_written_{kind}")
            elif approval_status == "draft":
                add_delta(origin_agent, 1, 0, f"trust_evidence_drafted_{kind or 'entry'}")

    applied: dict[str, dict[str, Any]] = {}
    for agent_key, delta in deltas.items():
        agent = agents.get(agent_key)
        if not isinstance(agent, dict):
            continue
        new_rep, new_auth, actual_rep, actual_auth = _apply_user_session_delta(
            agent,
            int(delta.get("rep") or 0),
            int(delta.get("auth") or 0),
        )
        old_rep = int(agent.get("reputation_units") or 0)
        old_auth = int(agent.get("authority_units") or 0)
        agent["reputation_units"] = new_rep
        agent["authority_units"] = new_auth
        agent["last_scored_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        agent["last_score_reason"] = (
            f"user_session:{quality_status} | {artifact_source} | {session_key}"
        )[:180]
        accounting_append_tx(
            {
                "type": "user_session_score",
                "session_key": session_key,
                "session_event_id": delivery_event_id,
                "agent": agent_key,
                "artifact_source": artifact_source,
                "quality_status": quality_status,
                "skills_used": skill_names,
                "rep_before": old_rep,
                "rep_after": new_rep,
                "rep_delta": actual_rep,
                "auth_before": old_auth,
                "auth_after": new_auth,
                "auth_delta": actual_auth,
                "reasons": list(delta.get("reasons") or []),
                "randomized": False,
            }
        )
        applied[agent_key] = {
            "rep_delta": actual_rep,
            "auth_delta": actual_auth,
            "rep_after": new_rep,
            "auth_after": new_auth,
            "reasons": list(delta.get("reasons") or []),
        }

    if not applied:
        state.setdefault("scored_events", {})[delivery_event_id] = {
            "session_key": session_key,
            "scored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "quality_status": quality_status,
            "artifact_source": artifact_source,
            "delivery_fingerprint": delivery_fingerprint,
            "agents": {},
        }
        state.setdefault("scored_fingerprints", {})[delivery_fingerprint] = {
            "session_key": session_key,
            "scored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "quality_status": quality_status,
            "artifact_source": artifact_source,
            "agents": {},
        }
        _save_user_session_score_state(state)
        return None

    accounting_save_ledger(ledger)
    court_actions = _apply_user_session_court_actions(
        state=state,
        session_key=session_key,
        delivery_fingerprint=delivery_fingerprint,
        delivery_event_id=delivery_event_id,
        delivery_event=delivery_event,
        artifact_source=artifact_source,
        quality_status=quality_status,
        skill_names=skill_names,
        contributors=contributors,
    )
    accounting_append_tx(
        {
            "type": "user_session_score_summary",
            "session_key": session_key,
            "session_event_id": delivery_event_id,
            "delivery_fingerprint": delivery_fingerprint,
            "artifact_source": artifact_source,
            "quality_status": quality_status,
            "skills_used": skill_names,
            "agents": applied,
            "court_actions": court_actions,
        }
    )
    state.setdefault("scored_events", {})[delivery_event_id] = {
        "session_key": session_key,
        "scored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "quality_status": quality_status,
        "artifact_source": artifact_source,
        "delivery_fingerprint": delivery_fingerprint,
        "agents": applied,
        "court_actions": court_actions,
    }
    state.setdefault("scored_fingerprints", {})[delivery_fingerprint] = {
        "session_key": session_key,
        "scored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "quality_status": quality_status,
        "artifact_source": artifact_source,
        "agents": applied,
        "court_actions": court_actions,
    }
    scored_items = state.get("scored_events", {})
    if len(scored_items) > 2000:
        for event_id in list(scored_items.keys())[:-1500]:
            scored_items.pop(event_id, None)
    scored_fingerprints = state.get("scored_fingerprints", {})
    if len(scored_fingerprints) > 2000:
        for fingerprint in list(scored_fingerprints.keys())[:-1500]:
            scored_fingerprints.pop(fingerprint, None)
    _save_user_session_score_state(state)

    try:
        from agent_registry import sync_from_economy
        sync_from_economy()
    except Exception:
        pass

    return {
        "artifact_source": artifact_source,
        "quality_status": quality_status,
        "delivery_fingerprint": delivery_fingerprint,
        "agents": applied,
        "court_actions": court_actions,
    }


def _step_result_text(step: dict[str, Any]) -> str:
    return str(step.get("result") or "").strip()


def _step_warning_texts(step: dict[str, Any]) -> list[str]:
    return [str(item).strip() for item in list(step.get("warnings") or []) if str(item).strip()]


def _step_effective_status(step: dict[str, Any]) -> str:
    status = str(step.get("status") or "").strip().lower()
    if status:
        return status
    if _step_result_text(step):
        return "ok"
    warning_texts = _step_warning_texts(step)
    if any(_warning_is_hard_blocker(item) or _warning_is_runtime_failure(item) for item in warning_texts):
        return "error"
    return "unknown"


def _step_has_non_informational_warning(step: dict[str, Any]) -> bool:
    return any(not _warning_is_informational(item) for item in _step_warning_texts(step))


def _warning_is_hard_blocker(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return any(token in lowered for token in ("hard_deny", "hard deny", "sanction", "denied by policy"))


def _warning_is_runtime_failure(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return any(
        token in lowered
        for token in (
            "timed out",
            "timeout",
            "service is not running",
            "service_status=crashed",
            "health=crashed",
            "preflight failed",
            "llm request failed",
            "loom failure",
        )
    )


def _warning_is_informational(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return any(
        token in lowered
        for token in (
            "safe_text_fetch_completed",
            "fast direct provider lane used",
            "fast direct qa lane used",
            "quill_output_drift_rewritten_to_user_artifact",
            "bounded_competitor_scan_salvaged_after_research_failure",
            "customer_research_starter_salvaged_after_unverified_research",
            "manager_synthesis_fastpathed_to_best_worker_artifact",
            "manager_synthesis_fastpathed_to_customer_research_starter",
            "manager_response_repaired_from_best_worker_artifact",
            "manager_response_repaired_from_worker_artifact",
            "manager_response_repaired_from_salvage_template",
            "artifact explicitly frames claims as unverified hypotheses",
            "artifact explicitly labels all claims as unvalidated hypotheses",
            "no unverified market data presented as fact",
            "all buyer segments, pain points, and pricing claims are correctly labeled as hypotheses",
            "next steps align with meridian research-khach-hang workflow",
            "recommended next steps align with meridian's research-khach-hang workflow",
            "no explicit timeline or resource allocation is provided for execution of research methods",
            "sample size justification for surveys/interviews is not included",
            "execution constraints (no fabricated findings, bounded artifact) are followed",
            "payout_execution_gate:",
            "disk pressure and scheduled-job status were not independently verified in this snapshot",
            "bounded llm host call completed against",
        )
    )


def _warning_is_recoverable_gap(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return any(
        token in lowered
        for token in (
            "missing",
            "lack",
            "not provided",
            "no specific",
            "no verified",
            "no session continuity",
            "minimal",
            "draft",
            "availability",
            "concrete details",
            "host facts",
            "no evidence",
            "no market evidence",
            "unknown",
            "success rate",
            "placeholder",
            "time zone",
            "undefined",
            "follow-up targets",
            "narrower next query",
            "source limitations",
            "múi giờ",
        )
    )


def _step_has_usable_artifact(step: dict[str, Any]) -> bool:
    if str(step.get("status") or "").strip().lower() != "ok":
        return False
    if str(step.get("task_kind") or "").strip() == "qa_gate":
        return False
    text = _step_result_text(step)
    if not text:
        return False
    lowered = text.lower()
    if _looks_like_scope_document(text):
        return False
    warning_texts = _step_warning_texts(step)
    if lowered in {"fail", "partial", "pass"}:
        return False
    if any(lowered == warning.lower() for warning in warning_texts):
        return False
    if _warning_is_runtime_failure(text):
        return False
    if text.startswith("{") and any(
        token in lowered for token in ("subject", "body", "meeting", "schedule", "plan", "draft", "status")
    ):
        return True
    if any(token in lowered for token in ("subject:", "agenda", "workflow", "next step", "1.", "draft", "schedule")):
        return True
    return len(text) >= 24


def _latest_usable_step_artifact(steps: list[dict[str, Any]]) -> str:
    for step in reversed(list(steps or [])):
        if _step_has_usable_artifact(step):
            return _step_result_text(step).strip()
    return ""


def _confidence_fit_bonus(value: Any) -> int:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return 0
    if any(token in lowered for token in ("high", "strong", "confident", "cao", "clear")):
        return 4
    if any(token in lowered for token in ("medium", "moderate", "partial", "vừa", "tam")):
        return 2
    if any(token in lowered for token in ("low", "weak", "tentative", "thấp")):
        return 0
    return 0


def _step_artifact_fit_score(
    step: dict[str, Any],
    request: str,
    skill_names: list[str] | None = None,
) -> int:
    raw_text = _step_result_text(step)
    artifact = _coerce_request_specific_artifact(raw_text, request)
    if not artifact:
        return -100
    score = 0
    status = str(step.get("status") or "").strip().lower()
    task_kind = str(step.get("task_kind") or "").strip().lower()
    agent_id = str(step.get("agent_id") or "").strip().lower()
    lowered_skill_names = {str(item or "").strip().lower() for item in (skill_names or [])}

    if status == "ok":
        score += 8
    else:
        score -= 30
    if _artifact_matches_skill_shape(artifact, request, skill_names):
        score += 40
    elif _final_artifact_is_usable(artifact, skill_names):
        score += 24
    if _looks_like_scope_document(artifact):
        score -= 40
    if task_kind == "write":
        score += 8
    elif task_kind == "research":
        score += 3
    elif task_kind in {"verify", "qa_gate"}:
        score -= 8

    if _request_wants_protocol_artifact(request):
        if task_kind == "write":
            score += 8
        if agent_id == "agent_quill":
            score += 4
        if agent_id == "agent_forge":
            score += 2
    if _request_is_customer_research(request, list(skill_names or [])):
        if task_kind == "research":
            score += 8
        if agent_id == "agent_atlas":
            score += 4
    if "safe-web-research" in lowered_skill_names and task_kind == "research":
        score += 6
    if "scan-doi-thu" in lowered_skill_names and task_kind == "research":
        score += 6

    citations = step.get("citations") if isinstance(step.get("citations"), list) else []
    score += min(len(citations), 3) * 2
    score += _confidence_fit_bonus(step.get("confidence"))

    for warning in _step_warning_texts(step):
        if _warning_is_informational(warning):
            continue
        if _warning_is_hard_blocker(warning):
            score -= 50
        elif _warning_is_runtime_failure(warning):
            score -= 25
        elif _warning_is_recoverable_gap(warning):
            score -= 5
        else:
            score -= 2

    if raw_text.lstrip().startswith("{") and artifact != raw_text:
        score += 4
    if len(artifact) >= 120:
        score += 2
    return score


def _best_usable_step_artifact(
    steps: list[dict[str, Any]],
    request: str,
    skill_names: list[str] | None = None,
) -> str:
    best_artifact = ""
    best_score = -1000
    for step in list(steps or []):
        raw_text = _step_result_text(step)
        artifact = _coerce_request_specific_artifact(raw_text, request)
        if not artifact:
            continue
        score = _step_artifact_fit_score(step, request, skill_names)
        if score > best_score:
            best_score = score
            best_artifact = artifact
    return best_artifact if best_score > 0 else ""


def _request_wants_protocol_artifact(request: str) -> bool:
    lowered = str(request or "").strip().lower()
    if not lowered:
        return False
    return (
        any(token in lowered for token in ("protocol", "playbook", "quy trình", "quy trinh"))
        and any(token in lowered for token in ("giả thuyết", "gia thuyet", "hypothesis"))
        and any(token in lowered for token in ("câu hỏi", "cau hoi", "question"))
        and any(token in lowered for token in ("follow-up", "follow up", "followup", "tin nhắn", "tin nhan", "message"))
        and any(token in lowered for token in ("tiêu chí dừng", "tieu chi dung", "stop rule", "exit criteria"))
    )


def _salvage_protocol_artifact(request: str) -> str:
    if _request_prefers_vietnamese(request):
        return textwrap.dedent(
            """
            **Protocol xử lý nhanh**

            **2-3 giả thuyết**
            1. Vấn đề không nằm ở nhu cầu, mà nằm ở ưu tiên hoặc timing.
            2. Vấn đề không nằm ở giá, mà nằm ở rủi ro quyết định chưa được bóc tách.
            3. Vấn đề không nằm ở sản phẩm, mà nằm ở người quyết định hoặc ngưỡng cam kết nội bộ.

            **Câu hỏi bóc tách**
            1. Điều gì đang chặn quyết định thật sự lúc này?
            2. Nếu không làm bây giờ, ưu tiên nào đang đứng trước?
            3. Ai là người còn chưa đồng thuận?
            4. Điều gì cần đúng thì deal mới quay lại bàn?

            **Tin nhắn follow-up**
            Chào anh/chị, để tránh follow-up vô hạn, cho em xin một câu trả lời thẳng: hiện điều gì đang chặn quyết định nhất để bên em xử lý đúng điểm nghẽn?

            **Tiêu chí dừng**
            Nếu không có owner rõ, mốc thời gian rõ, hoặc điều kiện mở lại rõ, thì dừng theo đuổi thay vì kéo dài thêm.
            """
        ).strip()
    return textwrap.dedent(
        """
        **Rapid Recovery Protocol**

        **2-3 hypotheses**
        1. The deal is blocked by priority or timing, not by lack of need.
        2. The deal is blocked by unresolved decision risk, not by price alone.
        3. The deal is blocked by ownership or internal commitment, not by product fit alone.

        **Debiasing questions**
        1. What is the real blocker right now?
        2. What is taking priority over this deal?
        3. Who still needs to agree?
        4. What would need to be true for this deal to restart?

        **Follow-up message**
        Hello, to avoid endless follow-up, could you tell me the single biggest blocker on your side so we can address the right issue directly?

        **Stop rule**
        If there is no clear owner, timeline, or reactivation condition, stop pursuing the deal instead of stretching the cycle.
        """
    ).strip()


def _artifact_matches_protocol_request_shape(text: str, request: str) -> bool:
    if not _request_wants_protocol_artifact(request):
        return False
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    return _artifact_looks_like_protocol_answer(text)


def _artifact_looks_like_protocol_answer(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    return (
        any(token in lowered for token in ("giả thuyết", "gia thuyet", "hypothesis"))
        and any(token in lowered for token in ("câu hỏi", "cau hoi", "question"))
        and any(token in lowered for token in ("follow-up", "follow up", "followup", "tin nhắn", "tin nhan", "message"))
        and any(token in lowered for token in ("tiêu chí dừng", "tieu chi dung", "stop rule", "exit criteria"))
    )


def _artifact_matches_skill_shape(text: str, request: str, skill_names: list[str] | None = None) -> bool:
    lowered_skills = {str(item or "").strip().lower() for item in (skill_names or [])}
    artifact = str(text or "").strip()
    lowered = artifact.lower()
    if not artifact:
        return False
    if _looks_like_scope_document(artifact):
        return False
    if _artifact_matches_protocol_request_shape(artifact, request):
        return True
    if "security-questionnaire" in lowered_skills or _request_is_security_questionnaire(request, list(skill_names or [])):
        return all(
            section in lowered
            for section in ("status", "approved evidence", "draft answers", "open gaps", "next move")
        )
    if "ai-stack-watch" in lowered_skills or _request_is_ai_stack_watch(request, list(skill_names or [])):
        return all(
            section in lowered
            for section in ("status", "watched changes", "impact on trust answers", "next move")
        )
    if "scan-doi-thu" in lowered_skills:
        return not _competitor_scan_artifact_needs_salvage(artifact)
    if "safe-web-research" in lowered_skills:
        return all(section in lowered for section in ("status", "verified source", "unknowns", "next move"))
    if "book-meeting" in lowered_skills:
        if _meeting_output_needs_salvage(artifact):
            return False
        return (
            ("please confirm" in lowered or "cần bổ sung" in lowered or "cần xác nhận" in lowered)
            and ("invite" in lowered or "lời mời" in lowered or "mẫu nhắn" in lowered)
        )
    if "mail-gui" in lowered_skills:
        return ("subject:" in lowered or "tiêu đề:" in lowered) and ("body:" in lowered or "nội dung:" in lowered)
    if any("follow" in name for name in lowered_skills):
        return "thank you" in lowered or "cảm ơn" in lowered
    if _request_is_customer_research(request, list(skill_names or [])):
        return all(section in lowered for section in ("status", "likely buyer", "what must be validated", "next move"))
    if _request_wants_protocol_artifact(request):
        return False
    return True


def _repair_manager_answer(
    request: str,
    answer: str,
    steps: list[dict[str, Any]],
    skill_names: list[str] | None = None,
) -> tuple[str, list[str]]:
    artifact = _coerce_request_specific_artifact(answer, request)
    if _artifact_matches_skill_shape(artifact, request, skill_names):
        return artifact, []

    best_step_artifact = _best_usable_step_artifact(steps, request, list(skill_names or []))
    if best_step_artifact and _artifact_matches_skill_shape(best_step_artifact, request, skill_names):
        return best_step_artifact, ["manager_response_repaired_from_best_worker_artifact"]

    salvaged_artifact = _salvage_user_artifact(request, list(skill_names or []))
    if salvaged_artifact and _artifact_matches_skill_shape(salvaged_artifact, request, skill_names):
        return salvaged_artifact, ["manager_response_repaired_from_salvage_template"]

    return artifact, []


def _qa_fail_is_recoverable(step: dict[str, Any]) -> bool:
    warnings = _step_warning_texts(step)
    if not warnings:
        return False
    return all(
        _warning_is_recoverable_gap(item)
        or _warning_is_runtime_failure(item)
        or _warning_is_informational(item)
        for item in warnings
    )


def _competitor_scan_artifact_needs_salvage(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return True
    required_sections = ("status", "verified findings", "unknowns", "next move")
    if any(section not in lowered for section in required_sections):
        return True
    if "official-source" not in lowered and "official source" not in lowered:
        return True
    if "narrower next query" not in lowered:
        return True
    if (
        ("không có verified findings" in lowered or "no verified findings" in lowered)
        and "source limitation" not in lowered
        and "nguồn/citation khả dụng" not in lowered
        and "official-source follow-up targets" not in lowered
    ):
        return True
    return False


def _final_artifact_is_usable(final_artifact: str, skill_names: list[str] | None = None) -> bool:
    lowered_skills = {str(item or "").strip().lower() for item in (skill_names or [])}
    text = str(final_artifact or "").strip()
    if not text:
        return False
    if _artifact_looks_like_protocol_answer(text):
        return True
    if "security-questionnaire" in lowered_skills:
        lowered = text.lower()
        return all(section in lowered for section in ("status", "approved evidence", "draft answers", "open gaps", "next move"))
    if "ai-stack-watch" in lowered_skills:
        lowered = text.lower()
        return all(section in lowered for section in ("status", "watched changes", "impact on trust answers", "next move"))
    if "scan-doi-thu" in lowered_skills:
        return not _competitor_scan_artifact_needs_salvage(text)
    if "mail-gui" in lowered_skills:
        lowered = text.lower()
        return ("subject:" in lowered or "tiêu đề:" in lowered) and ("body:" in lowered or "nội dung:" in lowered)
    if "book-meeting" in lowered_skills:
        lowered = text.lower()
        return not _meeting_output_needs_salvage(text) and (
            ("please confirm" in lowered or "cần bổ sung" in lowered or "cần xác nhận" in lowered)
            and ("invite" in lowered or "lời mời" in lowered or "mẫu nhắn" in lowered)
        )
    if "safe-web-research" in lowered_skills:
        lowered = text.lower()
        return all(section in lowered for section in ("status", "verified source", "unknowns", "next move"))
    if any("follow" in name for name in lowered_skills):
        lowered = text.lower()
        return "thank you" in lowered or "cảm ơn" in lowered
    if _request_is_customer_research("", list(skill_names or [])):
        lowered = text.lower()
        return all(section in lowered for section in ("status", "likely buyer", "what must be validated", "next move"))
    return False


def _placeholder_completion_is_success(skill_names: list[str]) -> bool:
    lowered_skills = {str(item or "").strip().lower() for item in skill_names}
    return (
        bool(lowered_skills.intersection({"mail-gui", "book-meeting"}))
        or "security-questionnaire" in lowered_skills
        or "ai-stack-watch" in lowered_skills
        or "safe-web-research" in lowered_skills
        or any("follow" in name for name in lowered_skills)
        or "scan-doi-thu" in lowered_skills
        or any(
            "research" in name and any(token in name for token in ("khach", "customer", "persona", "jtbd", "icp"))
            for name in lowered_skills
        )
    )


def _assess_skill_quality_outcome(
    steps: list[dict[str, Any]],
    skill_names: list[str] | None = None,
    *,
    final_artifact: str = "",
) -> tuple[str, list[str]]:
    if not steps:
        return "partial", ["No worker execution steps were recorded."]
    usable_artifact = any(_step_has_usable_artifact(step) for step in steps) or _final_artifact_is_usable(
        final_artifact,
        skill_names or [],
    )
    blocking_reasons: list[str] = []
    recoverable_reasons: list[str] = []
    has_warning = False
    placeholder_completion_ok = _placeholder_completion_is_success(skill_names or [])
    for step in steps:
        status = _step_effective_status(step)
        task_kind = str(step.get("task_kind") or "").strip()
        if status != "ok":
            reason = f"{str(step.get('agent_id') or 'worker').strip() or 'worker'} status={status or 'unknown'}"
            if usable_artifact and status in {"error", "timeout"}:
                recoverable_reasons.append(reason)
            else:
                blocking_reasons.append(reason)
        warnings = _step_warning_texts(step)
        if warnings:
            for warning in warnings[:4]:
                if _warning_is_informational(warning):
                    continue
                has_warning = True
                if _warning_is_hard_blocker(warning):
                    blocking_reasons.append(warning)
                elif _warning_is_runtime_failure(warning) or _warning_is_recoverable_gap(warning):
                    recoverable_reasons.append(warning)
        if task_kind == "qa_gate" and "fail" in _step_result_text(step).lower():
            if usable_artifact and _qa_fail_is_recoverable(step):
                recoverable_reasons.append("QA gate returned FAIL.")
            else:
                blocking_reasons.append("QA gate returned FAIL.")
    reasons = [*blocking_reasons, *recoverable_reasons]
    if blocking_reasons:
        if usable_artifact and not any(_warning_is_hard_blocker(item) for item in blocking_reasons):
            return "partial", reasons
        return "failure", reasons
    if recoverable_reasons:
        if placeholder_completion_ok and usable_artifact and all(
            _warning_is_recoverable_gap(item)
            or _warning_is_runtime_failure(item)
            or item == "QA gate returned FAIL."
            for item in recoverable_reasons
        ):
            return "success", []
        return ("partial" if usable_artifact or has_warning else "success"), reasons
    if has_warning:
        return "partial", ["Execution completed with non-fatal warnings."]
    return "success", []


def _short_prompt_skill_candidate(text: str) -> bool:
    tokens = _request_tokens(text)
    return 1 <= len(tokens) <= 6 and len(str(text or "").split()) <= 10


def _request_is_actionable(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    tokens = set(_request_tokens(text))
    if tokens & AUTONOMY_ACTION_TERMS:
        return True
    return any(term in lowered for term in AUTONOMY_ACTION_TERMS)


def _autonomy_skill_candidate(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _looks_like_meridian_internal_query(stripped) or _looks_like_meridian_operator_workflow_query(stripped):
        return False
    lowered = stripped.lower()
    if lowered in {"hi", "hello", "hey", "yo", "ping", "/help"}:
        return False
    words = stripped.split()
    tokens = _request_tokens(stripped)
    if not tokens:
        return False
    if _short_prompt_skill_candidate(stripped):
        return True
    if _request_wants_protocol_artifact(stripped):
        return True
    if len(words) > 48 or len(tokens) > 24:
        return False
    return _request_is_actionable(stripped)


def _skill_route_should_activate(request: str, bundle: dict[str, Any]) -> bool:
    matches = bundle.get("matches") if isinstance(bundle.get("matches"), list) else []
    if not matches:
        return False
    if bundle.get("created_skill") is not None:
        return True
    if any(
        isinstance(item.get("quality"), dict)
        and int(item["quality"].get("success_count") or 0) == 0
        and int(item["quality"].get("failure_count") or 0) > 0
        for item in matches
    ) and not _request_is_actionable(request):
        return False
    if _short_prompt_skill_candidate(request):
        return True
    if _request_is_actionable(request):
        return True
    for item in matches:
        if bool(item.get("autogenerated")):
            return True
        if int(item.get("score") or 0) >= 8:
            return True
    return False


def _skill_route_verified_facts(request: str, matches: list[dict[str, Any]]) -> dict[str, Any]:
    lowered = (request or "").strip().lower()
    skill_names = {str(item.get("name") or "").strip().lower() for item in matches}
    if "council-meeting" in skill_names or _looks_like_meridian_council_query(request):
        return _build_meridian_council_truth_packet()
    if skill_names & {"ops-snapshot", "founder-update"}:
        return _build_meridian_operator_truth_packet()
    if any(token in lowered for token in {"founder", "update", "status", "snapshot", "ops", "health", "payout", "treasury"}):
        return _build_meridian_operator_truth_packet()
    return {}


def _skill_item_category(item: dict[str, Any]) -> str:
    return str(item.get("category") or "").strip().lower()


def _autogenerated_skill_supports_request(request: str, item: dict[str, Any]) -> bool:
    request_category = TEAM_SKILLS._autonomy_category(request)
    item_category = _skill_item_category(item)
    if item_category and request_category not in {"", "general"} and item_category != request_category:
        return False
    request_tokens = set(_request_tokens(request))
    semantic_tokens = TEAM_SKILLS._tokenize(str(item.get("name") or "")) | TEAM_SKILLS._tokenize(str(item.get("description") or ""))
    semantic_overlap = request_tokens & semantic_tokens
    return int(item.get("score") or 0) >= 12 and len(semantic_overlap) >= 1


def _request_prefers_specific_skill(request: str, matches: list[dict[str, Any]]) -> bool:
    if not matches:
        return False
    has_supporting_autogenerated_match = any(
        bool(item.get("autogenerated")) and _autogenerated_skill_supports_request(request, item)
        for item in matches
    )
    if _request_wants_protocol_artifact(request):
        return not has_supporting_autogenerated_match
    request_category = TEAM_SKILLS._autonomy_category(request)
    if request_category == "general":
        return False
    if has_supporting_autogenerated_match:
        return False
    names = {str(item.get("name") or "").strip().lower() for item in matches}
    if _request_prefers_safe_web_research(request) and "safe-web-research" in names:
        return False
    if names and names.issubset(GENERIC_AUTONOMY_SKILLS):
        return True
    request_tokens = set(_request_tokens(request))
    if request_category == "research" and request_tokens.intersection({"khach", "customer", "persona", "jtbd", "icp"}):
        return True
    return False


def _best_specific_fallback_match(
    request: str,
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates = [dict(item) for item in matches if isinstance(item, dict)]
    if not candidates:
        return []
    request_category = TEAM_SKILLS._autonomy_category(request)
    if request_category and request_category != "general":
        category_matches = [
            item for item in candidates
            if _skill_item_category(item) == request_category
        ]
        if category_matches:
            candidates = category_matches
    candidates.sort(
        key=lambda item: int(item.get("score") or 0),
        reverse=True,
    )
    return [candidates[0]] if candidates else []


def _skill_bundle_for_request(
    request: str,
    session_key: str,
    *,
    manager_brief: str = "",
    allow_create: bool = False,
) -> dict[str, Any]:
    matches = TEAM_SKILLS.search(request, limit=2)
    if matches:
        filtered = [
            item
            for item in matches
            if not bool(item.get("autogenerated")) or _autogenerated_skill_supports_request(request, item)
        ]
        if filtered:
            matches = filtered
    seed_matches = [dict(item) for item in matches if isinstance(item, dict)]
    if matches and _request_is_security_questionnaire(request):
        questionnaire_matches = [
            item
            for item in matches
            if str(item.get("name") or "").strip().lower() == "security-questionnaire"
        ]
        if questionnaire_matches:
            matches = questionnaire_matches
    if matches and _request_is_ai_stack_watch(request):
        watch_matches = [
            item
            for item in matches
            if str(item.get("name") or "").strip().lower() == "ai-stack-watch"
        ]
        if watch_matches:
            matches = watch_matches
    if matches and _request_prefers_safe_web_research(request):
        safe_matches = [
            item
            for item in matches
            if str(item.get("name") or "").strip().lower() == "safe-web-research"
        ]
        if safe_matches:
            matches = safe_matches
    if matches and allow_create and _autonomy_skill_candidate(request):
        strongest = max(int(item.get("score") or 0) for item in matches)
        if _request_prefers_specific_skill(request, matches):
            matches = []
        elif strongest < 8 and not any(bool(item.get("autogenerated")) for item in matches):
            matches = []
    created_skill = None
    refined_skill = None
    if not matches and allow_create and _autonomy_skill_candidate(request):
        governance = None
        target_skill_name = TEAM_SKILLS._autonomy_slug(  # type: ignore[attr-defined]
            (request or manager_brief).strip(),
            category=TEAM_SKILLS._autonomy_category(f"{request} {manager_brief}"),  # type: ignore[attr-defined]
        )
        if _live_skill_registry_root():
            governance = _governed_skill_autonomy_begin(
                request=request,
                session_key=session_key,
                manager_brief=manager_brief,
                phase="create",
                skill_name=target_skill_name,
            )
        if governance is None or bool(governance.get("allowed")):
            try:
                created_skill = TEAM_SKILLS.create_autonomous_skill(
                    request,
                    session_key=session_key,
                    manager_brief=manager_brief,
                )
            except Exception:
                if governance is not None:
                    _governed_skill_autonomy_finish(
                        governance,
                        executed=False,
                        note="skill materialization raised an exception",
                    )
                raise
            else:
                if governance is not None:
                    _governed_skill_autonomy_finish(
                        governance,
                        executed=bool(created_skill),
                        note=(
                            "governed skill materialization committed"
                            if created_skill
                            else "no skill was materialized from this request"
                        ),
                        extra_refs={"created_skill_name": str((created_skill or {}).get("name") or "").strip()},
                    )
                if governance is not None:
                    append_session_event(
                        session_key,
                        {
                            "history_type": "skill_governance",
                            "status": "committed" if created_skill else "released",
                            "agent_id": TEAM_MANAGER_AGENT_ID,
                            "speaker": "manager",
                            "text": (
                                f"Governed skill synthesis {('created' if created_skill else 'released')} for {target_skill_name}."
                            ),
                            "skill_name": target_skill_name,
                            "source_label": "governed_dynamic_skill_synthesis",
                            "reservation_id": str(dict(governance.get('reservation') or {}).get("reservation_id") or "").strip(),
                            "warrant_id": str(dict(governance.get('warrant') or {}).get("warrant_id") or "").strip(),
                        },
                        loom_root=LOOM_ROOT,
                    )
        else:
            append_session_event(
                session_key,
                {
                    "history_type": "skill_governance",
                    "status": "blocked",
                    "agent_id": TEAM_MANAGER_AGENT_ID,
                    "speaker": "manager",
                    "text": f"Governed skill synthesis blocked for {target_skill_name}: {str(governance.get('reason') or '').strip()}",
                    "skill_name": target_skill_name,
                    "source_label": "governed_dynamic_skill_synthesis",
                },
                loom_root=LOOM_ROOT,
            )
        if created_skill:
            matches = [created_skill]
            append_session_event(
                session_key,
                {
                    "history_type": "skill_materialization",
                    "status": "created",
                    "agent_id": TEAM_MANAGER_AGENT_ID,
                    "speaker": "manager",
                    "text": f"Created internal skill {created_skill['name']} for adaptive request routing.",
                    "skill_name": created_skill["name"],
                    "source_label": "live_skill_autonomy",
                    "workers": list(created_skill.get("workers") or []),
                },
                loom_root=LOOM_ROOT,
            )
    elif matches and allow_create and _autonomy_skill_candidate(request):
        autogenerated_match = next(
            (
                dict(item)
                for item in matches
                if bool(item.get("autogenerated")) and _autogenerated_skill_supports_request(request, item)
            ),
            None,
        )
        if autogenerated_match:
            governance = None
            if _live_skill_registry_root():
                governance = _governed_skill_autonomy_begin(
                    request=request,
                    session_key=session_key,
                    manager_brief=manager_brief,
                    phase="refine",
                    skill_name=str(autogenerated_match.get("name") or "").strip(),
                )
            refined = False
            if governance is None or bool(governance.get("allowed")):
                refined = TEAM_SKILLS._refine_autonomous_skill_file(  # type: ignore[attr-defined]
                    autogenerated_match,
                    request=request,
                    session_key=session_key,
                    manager_brief=manager_brief,
                )
                if governance is not None:
                    _governed_skill_autonomy_finish(
                        governance,
                        executed=bool(refined),
                        note=(
                            "governed skill refinement committed"
                            if refined
                            else "autonomous skill refinement made no changes"
                        ),
                        extra_refs={"refined_skill_name": str(autogenerated_match.get("name") or "").strip()},
                    )
                    append_session_event(
                        session_key,
                        {
                            "history_type": "skill_governance",
                            "status": "committed" if refined else "released",
                            "agent_id": TEAM_MANAGER_AGENT_ID,
                            "speaker": "manager",
                            "text": (
                                f"Governed skill refinement {('updated' if refined else 'released')} for {str(autogenerated_match.get('name') or '').strip()}."
                            ),
                            "skill_name": str(autogenerated_match.get("name") or "").strip(),
                            "source_label": "governed_dynamic_skill_synthesis",
                            "reservation_id": str(dict(governance.get('reservation') or {}).get("reservation_id") or "").strip(),
                            "warrant_id": str(dict(governance.get('warrant') or {}).get("warrant_id") or "").strip(),
                        },
                        loom_root=LOOM_ROOT,
                    )
            elif governance is not None:
                append_session_event(
                    session_key,
                    {
                        "history_type": "skill_governance",
                        "status": "blocked",
                        "agent_id": TEAM_MANAGER_AGENT_ID,
                        "speaker": "manager",
                        "text": (
                            f"Governed skill refinement blocked for {str(autogenerated_match.get('name') or '').strip()}: "
                            f"{str(governance.get('reason') or '').strip()}"
                        ),
                        "skill_name": str(autogenerated_match.get("name") or "").strip(),
                        "source_label": "governed_dynamic_skill_synthesis",
                    },
                    loom_root=LOOM_ROOT,
                )
            if refined:
                TEAM_SKILLS.load()
                refreshed = TEAM_SKILLS.search(request, limit=2)
                if refreshed:
                    matches = refreshed
                    refined_skill = next((dict(item) for item in matches if bool(item.get("autogenerated"))), None)
                if refined_skill:
                        append_session_event(
                            session_key,
                            {
                                "history_type": "skill_refinement",
                                "status": "updated",
                                "agent_id": TEAM_MANAGER_AGENT_ID,
                                "speaker": "manager",
                                "text": f"Refined internal skill {refined_skill['name']} with a new learned variation.",
                                "skill_name": refined_skill["name"],
                                "source_label": "live_skill_autonomy",
                                "workers": list(refined_skill.get("workers") or []),
                            },
                            loom_root=LOOM_ROOT,
                        )
    if not matches and allow_create and seed_matches:
        matches = _best_specific_fallback_match(request, seed_matches)
    lowered = (request or "").strip().lower()
    if matches:
        names = {str(item.get("name") or "").strip().lower() for item in matches}
        meridian_internal_skill = (
            _looks_like_meridian_internal_query(request)
            or _looks_like_meridian_operator_workflow_query(request)
            or _looks_like_meridian_positioning_query(request)
            or any(
                term in lowered
                for term in (
                    "meridian",
                    "loom_native",
                    "preflight",
                    "treasury",
                    "reserve floor",
                    "payout",
                    "telegram",
                    "ops snapshot",
                )
            )
        )
        if meridian_internal_skill and "ai-intelligence" in names and len(matches) > 1:
            filtered = [
                item
                for item in matches
                if str(item.get("name") or "").strip().lower() != "ai-intelligence"
            ]
            if filtered:
                matches = filtered
                names = {str(item.get("name") or "").strip().lower() for item in matches}
        if "ops-snapshot" in names and any(term in lowered for term in ("ops", "snapshot", "health", "status")):
            filtered = [
                item for item in matches if str(item.get("name") or "").strip().lower() == "ops-snapshot"
            ]
            if filtered:
                matches = filtered
                names = {str(item.get("name") or "").strip().lower() for item in matches}
        if "council-meeting" in names and not _looks_like_meridian_council_query(request):
            filtered = [
                item for item in matches if str(item.get("name") or "").strip().lower() != "council-meeting"
            ]
            if filtered:
                matches = filtered
                names = {str(item.get("name") or "").strip().lower() for item in matches}
            elif allow_create and _autonomy_skill_candidate(request):
                matches = []
                names = set()
        if "council-meeting" in names and _looks_like_meridian_council_query(request) and len(matches) > 1:
            filtered = [
                item for item in matches if str(item.get("name") or "").strip().lower() == "council-meeting"
            ]
            if filtered:
                matches = filtered
                names = {"council-meeting"}
        if "founder-update" in names and any(term in lowered for term in ("founder", "update", "brief")):
            filtered = [
                item for item in matches if str(item.get("name") or "").strip().lower() == "founder-update"
            ]
            if filtered:
                matches = filtered
                names = {"founder-update"}
        if "mail-gui" in names and any(term in lowered for term in ("mail", "email", "gửi mail", "gui mail")):
            filtered = [
                item
                for item in matches
                if str(item.get("name") or "").strip().lower() == "mail-gui"
            ]
            if filtered and not any(
                term in lowered for term in ("follow up", "follow-up", "followup", "sau demo", "demo hôm qua", "demo hom qua")
            ):
                matches = filtered
                names = {"mail-gui"}
        if "book-meeting" in names and any(term in lowered for term in ("book meeting", "đặt lịch", "dat lich", "meeting")):
            filtered = [
                item
                for item in matches
                if str(item.get("name") or "").strip().lower() == "book-meeting"
            ]
            if filtered:
                matches = filtered
                names = {"book-meeting"}
        elif "research-khach-hang" in names and any(term in lowered for term in ("book meeting", "đặt lịch", "dat lich", "meeting")):
            refreshed = TEAM_SKILLS.search("book meeting", limit=4)
            meeting_matches = [
                item
                for item in refreshed
                if str(item.get("name") or "").strip().lower() == "book-meeting"
            ]
            if meeting_matches:
                matches = meeting_matches
                names = {"book-meeting"}
        if "research-khach-hang" in names and _request_is_customer_research(request, list(names)):
            filtered = [
                item
                for item in matches
                if str(item.get("name") or "").strip().lower() == "research-khach-hang"
            ]
            if filtered:
                matches = filtered
                names = {"research-khach-hang"}
        if "follow-demo-soan" in names and not any(
            term in lowered for term in ("follow up", "follow-up", "followup", "sau demo", "demo hôm qua", "demo hom qua")
        ):
            filtered = [
                item
                for item in matches
                if str(item.get("name") or "").strip().lower() != "follow-demo-soan"
            ]
            if filtered:
                matches = filtered
                names = {str(item.get("name") or "").strip().lower() for item in matches}
            elif any(term in lowered for term in ("mail", "email", "gửi mail", "gui mail")):
                refreshed = TEAM_SKILLS.search("gửi mail", limit=4)
                mail_matches = [
                    item
                    for item in refreshed
                    if str(item.get("name") or "").strip().lower() == "mail-gui"
                ]
                if mail_matches:
                    matches = mail_matches
                    names = {"mail-gui"}
                else:
                    matches = []
                    names = set()
        names = {str(item.get("name") or "").strip().lower() for item in matches}
        autogenerated_specific = [
            item
            for item in matches
            if bool(item.get("autogenerated")) and str(item.get("name") or "").strip().lower() != "safe-web-research"
        ]
        if autogenerated_specific and "ai-intelligence" in names:
            filtered = [
                item
                for item in matches
                if str(item.get("name") or "").strip().lower() != "ai-intelligence"
            ]
            if filtered:
                matches = filtered
                names = {str(item.get("name") or "").strip().lower() for item in matches}
        if autogenerated_specific and "safe-web-research" in names and not _request_prefers_safe_web_research(request):
            filtered = [
                item
                for item in matches
                if str(item.get("name") or "").strip().lower() != "safe-web-research"
            ]
            if filtered:
                matches = filtered
        if _request_wants_protocol_artifact(request):
            protocol_specific = [
                item
                for item in matches
                if bool(item.get("autogenerated"))
                and _skill_item_category(item) == "planning"
                and "protocol" in str(item.get("name") or "").strip().lower()
            ]
            if protocol_specific:
                matches = protocol_specific[:1]
    guidance = TEAM_SKILLS.guidance_block(matches)
    workers: list[str] = []
    for item in matches:
        for worker in item.get("workers") or []:
            if worker in SPECIALIST_KEYS and worker not in workers:
                workers.append(worker)
    return {
        "matches": matches,
        "created_skill": created_skill,
        "refined_skill": refined_skill,
        "guidance": guidance,
        "workers": workers,
    }


def _log(message: str, *, color: str = ANSI_CYAN) -> None:
    print(f"{ANSI_BOLD}{color}{message}{ANSI_RESET}", flush=True)


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1B\[[0-?]*[ -/]*[@-~]", "", text)


def _extract_json_value(text: str) -> Any:
    raw = text.strip()
    if not raw:
        return None
    candidates = [raw]
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, flags=re.DOTALL)
    if fence_match:
        candidates.append(fence_match.group(1))
    bracket_pairs = (("{", "}"), ("[", "]"))
    for opener, closer in bracket_pairs:
        first = raw.find(opener)
        last = raw.rfind(closer)
        if first != -1 and last != -1 and last > first:
            candidates.append(raw[first : last + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(candidate)
            except Exception:
                continue
        if isinstance(parsed, (dict, list)):
            return parsed
    return None


def _extract_json(text: str) -> dict[str, Any] | None:
    parsed = _extract_json_value(text)
    return parsed if isinstance(parsed, dict) else None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _protocol_payload_to_artifact(text: str, request: str) -> str:
    payload = _extract_json(text)
    if not isinstance(payload, dict):
        return ""
    protocol = payload.get("protocol")
    if not isinstance(protocol, dict):
        protocol = payload.get("revive_deal_protocol")
    if not isinstance(protocol, dict):
        return ""
    hypotheses = _string_list(protocol.get("hypotheses") or protocol.get("reverse_hypotheses"))
    questions = _string_list(
        protocol.get("debiasing_questions")
        or protocol.get("questions")
        or protocol.get("probing_questions")
    )
    follow_up = str(
        protocol.get("follow_up_message")
        or protocol.get("reengagement_message")
        or protocol.get("message")
        or ""
    ).strip()
    stop_rule = str(
        protocol.get("stop_rule")
        or protocol.get("exit_criteria")
        or protocol.get("stop_criteria")
        or protocol.get("stop_condition")
        or ""
    ).strip()
    if not hypotheses and not questions and not follow_up and not stop_rule:
        return ""
    if _request_prefers_vietnamese(request):
        lines = ["**Protocol xử lý**", ""]
        if hypotheses:
            lines.append("**Giả thuyết**")
            lines.extend(f"{idx}. {item}" for idx, item in enumerate(hypotheses, start=1))
            lines.append("")
        if questions:
            lines.append("**Câu hỏi bóc tách**")
            lines.extend(f"{idx}. {item}" for idx, item in enumerate(questions, start=1))
            lines.append("")
        if follow_up:
            lines.append("**Tin nhắn follow-up**")
            lines.append(follow_up)
            lines.append("")
        if stop_rule:
            lines.append("**Tiêu chí dừng**")
            lines.append(stop_rule)
        return "\n".join(line for line in lines if line is not None).strip()
    lines = ["**Protocol**", ""]
    if hypotheses:
        lines.append("**Hypotheses**")
        lines.extend(f"{idx}. {item}" for idx, item in enumerate(hypotheses, start=1))
        lines.append("")
    if questions:
        lines.append("**Questions**")
        lines.extend(f"{idx}. {item}" for idx, item in enumerate(questions, start=1))
        lines.append("")
    if follow_up:
        lines.append("**Follow-up message**")
        lines.append(follow_up)
        lines.append("")
    if stop_rule:
        lines.append("**Stop rule**")
        lines.append(stop_rule)
    return "\n".join(line for line in lines if line is not None).strip()


def _coerce_request_specific_artifact(text: str, request: str) -> str:
    artifact = str(text or "").strip()
    if not artifact:
        return ""
    if _request_wants_protocol_artifact(request):
        normalized = _protocol_payload_to_artifact(artifact, request)
        if normalized:
            return normalized
    return artifact


def _sanitize_worker_citations(
    specialist: TeamSpecialist,
    citations: Any,
    *,
    transport_kind: str,
) -> tuple[list[Any], list[str]]:
    normalized = citations if isinstance(citations, list) else []
    warnings: list[str] = []
    if transport_kind == "direct_provider_http_fallback" and specialist.env_key in {"ATLAS", "QUILL", "PULSE"}:
        if normalized:
            warnings.append("direct fallback citations stripped because they were not independently verified")
        return [], warnings
    return normalized, warnings


def _request_prefers_vietnamese(text: str) -> bool:
    raw = str(text or "")
    if any(ch in raw for ch in "ăâêôơưđĂÂÊÔƠƯĐ"):
        return True
    lowered = raw.lower()
    return any(token in lowered for token in ("gửi", "gui", "khách", "lịch", "lich", "sáng mai", "toi", "tôi"))


def _mail_request_wants_status_update(request: str) -> bool:
    lowered = str(request or "").strip().lower()
    if not lowered:
        return False
    status_terms = (
        "trạng thái",
        "trang thai",
        "status update",
        "current status",
        "cập nhật",
        "cap nhat",
        "update",
    )
    subject_terms = (
        "agent",
        "agents",
        "meridian",
        "bạn và các agent",
        "you and the other agents",
    )
    return any(term in lowered for term in status_terms) and any(term in lowered for term in subject_terms)


def _mail_request_wants_meeting(request: str) -> bool:
    lowered = str(request or "").strip().lower()
    if not lowered:
        return False
    meeting_terms = (
        "lịch hẹn",
        "lich hen",
        "đặt lịch",
        "dat lich",
        "meeting",
        "meet",
        "zoom",
        "teams",
        "google meet",
        "follow-up",
    )
    return any(term in lowered for term in meeting_terms)


def _looks_like_scope_document(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    markers = (
        "product goal",
        "user and use case",
        "must-have",
        "nice-to-have",
        "non-goals",
        "acceptance criteria",
        "release steps",
        "scope:",
    )
    return sum(1 for marker in markers if marker in lowered) >= 2


def _meeting_output_needs_salvage(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    return any(
        token in lowered
        for token in (
            "'to': 'forge, aegis'",
            '"to": "forge, aegis"',
            "'attendees': ['atlas', 'quill', 'forge']",
            '"attendees": ["atlas", "quill", "forge"]',
            'our team (quill, forge, aegis)',
        )
    )


def _salvage_mail_artifact(request: str) -> str:
    if _mail_request_wants_status_update(request):
        if _request_prefers_vietnamese(request):
            return textwrap.dedent(
                """
                **Tiêu đề:** Cập nhật trạng thái hiện tại của Meridian và các Agent

                **Nội dung:**

                Chào anh/chị,

                Đây là bản cập nhật ngắn về trạng thái hiện tại của Meridian và các Agent trên host đang chạy:

                - **Meridian:** đang vận hành theo hướng governed Trust Ops, với boundary công khai và các proof route đang hoạt động trên host hiện tại.
                - **Leviathann:** giữ vai trò manager, điều phối output cuối và route các lane theo boundary hiện tại.
                - **Atlas:** phụ trách research và signal discovery cho các lane cần evidence hoặc watch output.
                - **Quill:** phụ trách drafting các artifact gửi người dùng như email, brief, questionnaire pack, và output buyer-facing.
                - **Aegis / Sentinel:** phụ trách quality gate, contradiction check, và cảnh báo khi output không đủ proof.
                - **Forge / Pulse:** phụ trách execution bounded steps và nén/đóng gói output cho delivery.

                Nếu anh/chị muốn, em có thể viết tiếp bản này thành memo rõ hơn theo format:
                1. trạng thái host hiện tại,
                2. trạng thái từng Agent,
                3. phần nào đã live,
                4. phần nào vẫn còn bounded hoặc phase-gated.

                Trân trọng,
                [Tên bạn]
                [Chức danh]
                [Công ty]
                [Email]
                """
            ).strip()
        return textwrap.dedent(
            """
            **Subject:** Current Status Update for Meridian and Its Agents

            **Body:**

            Hello,

            Here is a short update on the current status of Meridian and the agents running on the current host:

            - **Meridian:** operating as a governed Trust Ops system with a public boundary and live proof routes on the current host.
            - **Leviathann:** acting as the manager, routing work and choosing the final user-facing artifact.
            - **Atlas:** handling research and signal discovery for evidence-heavy and watch-oriented lanes.
            - **Quill:** drafting buyer-facing output such as emails, briefs, questionnaire packs, and communication artifacts.
            - **Aegis / Sentinel:** handling quality gates, contradiction checks, and warning when output lacks enough proof.
            - **Forge / Pulse:** handling bounded execution steps and compressing output for delivery.

            If useful, I can also turn this into a more formal status memo with:
            1. current host status,
            2. per-agent status,
            3. what is live now,
            4. what remains bounded or phase-gated.

            Best,
            [Your Name]
            [Title]
            [Company]
            [Email]
            """
        ).strip()
    if _mail_request_wants_meeting(request):
        if _request_prefers_vietnamese(request):
            return textwrap.dedent(
                """
                **Tiêu đề:** Chào anh/chị và xin lịch hẹn ngày mai

                **Nội dung:**

                Chào anh/chị [Tên khách],

                Em là [Tên bạn] từ [Tên công ty].

                Em gửi lời chào và mong được sắp xếp một buổi trao đổi ngắn với anh/chị vào ngày mai, [ngày/tháng/năm]. Nếu thuận tiện, anh/chị cho em xin khung giờ phù hợp trong buổi sáng theo múi giờ [Múi giờ] để em chốt lịch ngay.

                Nếu cần, em cũng có thể gửi lời mời họp qua `Google Meet`, `Zoom`, hoặc `Teams`.

                Trân trọng,
                [Tên bạn]
                [Chức danh]
                [Công ty]
                [Số điện thoại]
                [Email]
                """
            ).strip()
        return textwrap.dedent(
            """
            **Subject:** Welcome and Meeting Availability for Tomorrow

            **Body:**

            Hello [Customer Name],

            I hope you're doing well. I wanted to send a quick welcome note and ask whether you have any availability for a short meeting tomorrow.

            If you prefer, I can send the invite via Google Meet, Zoom, or Teams once you confirm a suitable time.

            Best,
            [Your Name]
            [Title]
            [Company]
            """
        ).strip()
    if _request_prefers_vietnamese(request):
        return textwrap.dedent(
            """
            **Tiêu đề:** Bản nháp email cần hoàn thiện trước khi gửi

            **Nội dung:**

            Chào [Tên người nhận],

            Đây là bản nháp email an toàn vì yêu cầu gốc vẫn còn thiếu vài chi tiết cụ thể.

            - Mục đích email: [điền mục tiêu chính]
            - Nội dung chính cần truyền đạt: [điền thông tin cốt lõi]
            - Hành động mong muốn từ người nhận: [điền next step]
            - Mốc thời gian hoặc deadline (nếu có): [điền thời gian]

            Trân trọng,
            [Tên bạn]
            [Chức danh]
            [Công ty]
            [Email]
            """
        ).strip()
    return textwrap.dedent(
        """
        **Subject:** Draft email to finalize before sending

        **Body:**

        Hello [Recipient Name],

        This is a safe draft because the original request is still missing some concrete details.

        - Main goal of the email: [fill this in]
        - Key point to communicate: [fill this in]
        - Desired next step from the recipient: [fill this in]
        - Timeline or deadline, if relevant: [fill this in]

        Best,
        [Your Name]
        [Title]
        [Company]
        """
    ).strip()


def _salvage_follow_up_artifact(request: str) -> str:
    if _request_prefers_vietnamese(request):
        return textwrap.dedent(
            """
            Chào anh/chị [Tên khách],

            Cảm ơn anh/chị đã dành thời gian tham gia buổi demo hôm qua.

            Em gửi lại một vài ý chính đã trao đổi:
            - [Giá trị chính 1]
            - [Giá trị chính 2]
            - [Điểm khách quan tâm]

            Nếu anh/chị thấy phù hợp, em có thể:
            - gửi lại tài liệu hoặc demo recording
            - trả lời thêm các câu hỏi còn mở
            - sắp xếp buổi trao đổi tiếp theo để chốt bước kế tiếp

            Thông tin đang để placeholder để điền nhanh:
            - Demo: [Sản phẩm/chủ đề đã demo]
            - Điểm khách quan tâm: [Mối quan tâm chính]
            - Bước tiếp theo đề xuất: [Ví dụ: gửi tài liệu / lên lịch trao đổi / báo giá]

            Anh/chị phản hồi giúp em khung giờ phù hợp hoặc các câu hỏi còn lại, em sẽ hỗ trợ ngay.

            Trân trọng,
            [Tên bạn]
            """
        ).strip()
    return textwrap.dedent(
        """
        Hello [Customer Name],

        Thank you again for taking the time to join the demo yesterday.

        Here is a short recap of the key points:
        - [Key value point 1]
        - [Key value point 2]
        - [Customer priority or open question]

        If helpful, I can also:
        - resend the materials or recording
        - answer any remaining questions
        - schedule a short next-step discussion

        Let me know what would be most useful and I will send it right away.

        Best,
        [Your Name]
        """
    ).strip()


def _salvage_competitor_scan_artifact(request: str) -> str:
    target = "đối thủ này"
    lowered = str(request or "").strip().lower()
    match = re.search(r"(openai|anthropic|google|gemini|meta|mistral|cohere|deepseek)", lowered)
    if match:
        target = match.group(1).upper() if match.group(1).lower() == "openai" else match.group(1).title()
    if _request_prefers_vietnamese(request):
        return textwrap.dedent(
            f"""
            **Status**
            Chưa có phát hiện đã xác minh cho {target} trong lần chạy này.

            **Verified findings**
            - Không có verified findings khả dụng từ live research lane hiện tại.
            - Không được phép bịa update tuần này nếu chưa có bằng chứng.

            **Unknowns**
            - Chưa rõ {target} có thay đổi mới về pricing / API / model / policy trong 7 ngày gần nhất hay không.
            - Chưa có link nguồn chính thức đủ mạnh để xác nhận thay đổi.

            **Next move**
            - Official-source follow-up targets:
              - blog hoặc changelog chính thức của {target}
              - trang docs / pricing / models / API của {target}
              - status page hoặc release notes nếu có
            - Narrower next query:
              - `scan đối thủ {target} pricing tuần này`
              - `scan đối thủ {target} model release tuần này`
            """
        ).strip()
    return textwrap.dedent(
        f"""
        **Status**
        No verified weekly findings were recovered for {target} in this run.

        **Verified findings**
        - No verified live findings are available from the current research lane.
        - It would be incorrect to invent weekly changes without evidence.

        **Unknowns**
        - It remains unknown whether {target} shipped pricing, API, model, or policy updates in the last 7 days.
        - No official-source links strong enough to confirm a weekly change were recovered.

        **Next move**
        - Official-source follow-up targets:
          - {target} official blog or changelog
          - {target} docs, pricing, models, or API pages
          - status or release notes if available
        - Narrower next query:
          - `{target} pricing this week`
          - `{target} model release this week`
        """
    ).strip()


def _safe_web_research_artifact(request: str, fetch_result: dict[str, Any]) -> str:
    requested_url = str(fetch_result.get("url") or _extract_request_url(request) or "").strip()
    if _request_prefers_vietnamese(request):
        if fetch_result.get("ok"):
            excerpt = _excerpt(str(fetch_result.get("normalized_text") or "").strip(), limit=700)
            status = fetch_result.get("status")
            content_type = str(fetch_result.get("content_type") or "").strip() or "unknown"
            return textwrap.dedent(
                f"""
                **Status**
                Đã fetch an toàn nguồn này theo chế độ text-only.

                **Verified source**
                - URL: {requested_url}
                - HTTP status: {status if status is not None else "unknown"}
                - content-type: {content_type}

                **Normalized excerpt**
                {excerpt or "- Không lấy được excerpt đủ hữu ích từ source."}

                **Unknowns**
                - Chưa thực thi JavaScript hay đọc nội dung động ngoài phần text fetch hiện có.
                - Chưa có kết luận vượt quá nội dung hiện diện trong excerpt này.

                **Next move**
                - Nếu cần, tôi có thể tóm tắt sâu hơn, trích 5 ý chính, hoặc đối chiếu nguồn này với một nguồn chính thức khác.
                """
            ).strip()
        error = str(fetch_result.get("error") or "safe_web_fetch_failed").strip()
        return textwrap.dedent(
            f"""
            **Status**
            Không thể fetch an toàn nguồn này trong lần chạy hiện tại.

            **Verified source**
            - URL: {requested_url or '[chưa xác định]'}
            - Lý do: {error}

            **Unknowns**
            - Chưa có normalized text để tóm tắt.

            **Next move**
            - Kiểm tra lại URL, hoặc cung cấp một nguồn công khai khác cùng chủ đề để tôi fetch theo cùng chế độ an toàn.
            """
        ).strip()
    if fetch_result.get("ok"):
        excerpt = _excerpt(str(fetch_result.get("normalized_text") or "").strip(), limit=700)
        status = fetch_result.get("status")
        content_type = str(fetch_result.get("content_type") or "").strip() or "unknown"
        return textwrap.dedent(
            f"""
            **Status**
            Safe text-only fetch completed.

            **Verified source**
            - URL: {requested_url}
            - HTTP status: {status if status is not None else "unknown"}
            - content-type: {content_type}

            **Normalized excerpt**
            {excerpt or "- No useful excerpt was recovered from the source."}

            **Unknowns**
            - JavaScript-rendered or hidden content was not executed.
            - No claim beyond the fetched excerpt is being made here.

            **Next move**
            - I can summarize this source, extract 5 key points, or compare it with another official source next.
            """
        ).strip()
    error = str(fetch_result.get("error") or "safe_web_fetch_failed").strip()
    return textwrap.dedent(
        f"""
        **Status**
        Safe fetch could not complete for this source.

        **Verified source**
        - URL: {requested_url or '[unknown]'}
        - Reason: {error}

        **Unknowns**
        - No normalized text was recovered.

        **Next move**
        - Check the URL or provide a different public source for the same topic.
        """
    ).strip()


def _salvage_meeting_artifact(request: str) -> str:
    if _request_prefers_vietnamese(request):
        return textwrap.dedent(
            """
            Chưa thể đặt lịch ngay vì còn thiếu dữ liệu bắt buộc.

            Cần bổ sung:
            - tên hoặc email khách hàng
            - giờ cụ thể
            - múi giờ
            - mục đích buổi họp
            - nền tảng họp (`Google Meet`, `Zoom`, `Teams`) hoặc gặp trực tiếp

            **Mẫu nhắn xác nhận:**
            Chào [Tên khách], em muốn đặt một buổi trao đổi ngắn vào sáng mai. Anh/chị thuận tiện khung giờ nào theo múi giờ [Múi giờ]? Nếu phù hợp, em sẽ gửi lời mời họp ngay.
            """
        ).strip()
    return textwrap.dedent(
        """
        I cannot book the meeting yet because required details are missing.

        Please confirm:
        - customer name or email
        - exact time
        - time zone
        - meeting purpose
        - meeting platform (`Google Meet`, `Zoom`, `Teams`) or in-person

        **Quick draft to send now:**
        Hello, I would like to schedule a short meeting for tomorrow morning. What time works best for you? Once you confirm, I will send the calendar invite right away.
        """
    ).strip()


def _request_is_security_questionnaire(request: str, skills_used: list[str] | None = None) -> bool:
    lowered = str(request or "").strip().lower()
    if not lowered:
        return False
    lowered_skills = {str(item or "").strip().lower() for item in list(skills_used or [])}
    if "security-questionnaire" in lowered_skills:
        return True
    if _request_wants_protocol_artifact(request):
        return False
    keywords = (
        "ai governance",
        "customer assurance",
        "data retention",
        "due diligence",
        "evidence pack",
        "questionnaire",
        "security review",
        "soc2",
        "subprocessor",
        "trust center",
        "vendor risk",
    )
    return any(token in lowered for token in keywords)


def _request_is_ai_stack_watch(request: str, skills_used: list[str] | None = None) -> bool:
    lowered = str(request or "").strip().lower()
    if not lowered:
        return False
    lowered_skills = {str(item or "").strip().lower() for item in list(skills_used or [])}
    if "ai-stack-watch" in lowered_skills:
        return True
    if _request_wants_protocol_artifact(request):
        return False
    keywords = (
        "ai stack",
        "api change",
        "deprecation",
        "model watch",
        "monitor",
        "policy change",
        "pricing change",
        "provider watch",
        "regulation",
        "regulatory",
        "vendor watch",
        "watch",
    )
    if any(token in lowered for token in keywords):
        return True
    tokens = set(_request_tokens(request))
    return bool(tokens.intersection({"watch", "monitor"})) and bool(
        tokens.intersection({"model", "provider", "pricing", "policy", "regulation", "vendor"})
    )


def _request_is_customer_research(request: str, skills_used: list[str] | None = None) -> bool:
    lowered = str(request or "").strip().lower()
    tokens = set(_request_tokens(request))
    lowered_skills = {str(item or "").strip().lower() for item in list(skills_used or [])}
    if _request_wants_protocol_artifact(request):
        return False
    if _request_is_security_questionnaire(request, list(lowered_skills)) or _request_is_ai_stack_watch(request, list(lowered_skills)):
        return False
    if "book-meeting" in lowered_skills or "mail-gui" in lowered_skills or any("follow" in name for name in lowered_skills):
        return False
    if any(token in lowered for token in ("book meeting", "đặt lịch", "dat lich", "meeting", "gửi mail", "gui mail", "email")):
        return False
    if any(
        "research" in name and any(token in name for token in ("khach", "customer", "persona", "jtbd", "icp"))
        for name in lowered_skills
    ):
        return True
    return (
        ("research" in tokens or "customer" in tokens or "khach" in tokens)
        and (
            "customer" in tokens
            or "khach" in tokens
            or "persona" in tokens
            or "jtbd" in tokens
            or "icp" in tokens
            or "khách" in lowered
        )
    )


def _atlas_result_uses_placeholder_sources(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return any(token in lowered for token in ("example.com", "placeholder source", "placeholder citation"))


def _research_text_contains_unverified_quantification(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    if "%" in lowered:
        return True
    if re.search(r"\b\d+(?:\.\d+)?\b", lowered) and any(
        token in lowered for token in ("survey", "cagr", "market share", "adoption", "conversions", "willingness to pay")
    ):
        return True
    return False


def _salvage_customer_research_artifact(request: str) -> str:
    return textwrap.dedent(
        """
        **Status**

        Đây là research starter dạng **giả thuyết cần kiểm chứng**, chưa phải market evidence đã xác minh.

        **Likely buyer / user**

        - Product Marketing / Competitive Intelligence lead
        - Founder hoặc GM ở công ty B2B software
        - Sales enablement / strategy team cần cập nhật biến động đối thủ

        **Likely pains**

        - Theo dõi đối thủ đang thủ công, rời rạc, và chậm
        - Khó biến tin tức đối thủ thành insight dùng được cho pricing, sales, và roadmap
        - Khó giữ alert/brief đủ ngắn nhưng vẫn có nguồn đáng tin

        **What must be validated**

        - Nhóm buyer nào đau nhất và sẵn sàng trả tiền trước
        - Trigger mua hàng: mất deal, pricing shift, launch mới, board pressure, hay sales enablement
        - Cadence thật họ cần: realtime alert, weekly brief, hay battlecard theo yêu cầu
        - Ngưỡng trả tiền đầu tiên cho founder-led service

        **Next move**

        1. Chọn 10 khách hàng phỏng vấn theo 3 vai trò: Product Marketing, Sales Lead, Founder/GM.
        2. Kiểm tra 5 giả thuyết: pain lớn nhất, nguồn dữ liệu quan trọng nhất, trigger mua hàng, tần suất dùng, willingness to pay.
        3. Chỉ sau đó mới chốt ICP, pricing, và messaging.
        """
    ).strip()


def _salvage_ai_stack_watch_artifact(request: str) -> str:
    return textwrap.dedent(
        """
        **Status**

        Đây là watch brief dạng bounded, chỉ nêu thay đổi cần theo dõi tiếp chứ không khẳng định mọi thay đổi đã được xác minh đầy đủ.

        **Watched changes**

        - Cần theo dõi thay đổi về model/provider, pricing, policy, deprecation, và regulatory signals.
        - Chưa có gói thay đổi đã phê duyệt để dùng như trust answer chính thức trong lần chạy này.

        **Impact on trust answers**

        - Mọi câu trả lời customer assurance liên quan provider/model/policy phải được rà lại trước khi ship.
        - Nếu không có approved evidence mới, giữ câu trả lời ở trạng thái draft hoặc escalation.

        **Next move**

        1. Xác minh changelog / pricing / policy page chính thức của vendor hoặc model liên quan.
        2. Cập nhật approved evidence nếu thay đổi làm ảnh hưởng security, privacy, retention, hoặc governance answers.
        3. Chỉ ship trust answer mới sau khi Aegis pass và evidence được approve.
        """
    ).strip()


def _salvage_security_questionnaire_artifact(request: str) -> str:
    return textwrap.dedent(
        """
        **Status**

        Đây là questionnaire draft có governance boundary, không phải final answer pack đã đủ proof cho mọi câu.

        **Approved evidence**

        - Chưa có approved evidence đủ mạnh cho toàn bộ câu hỏi trong lần chạy này.
        - Chỉ được tái sử dụng evidence đã được xác minh hoặc approve rõ ràng.

        **Draft answers**

        - Trả lời từng câu dưới dạng draft nếu evidence hiện có còn yếu hoặc đang thiếu.
        - Mỗi câu critical phải lộ rõ state hiện tại: approved, draft, stale, revoked, hoặc unresolved.
        - Không được tự khẳng định SOC 2 / ISO 27001 / retention / subprocessors nếu chưa có proof.

        **Open gaps**

        - Cần xác nhận câu nào đã có approved evidence.
        - Cần approval queue cho các claim security, privacy, retention, AI governance còn thiếu proof.
        - Nếu còn pending critical approvals thì chưa được gọi đây là final trust pack.

        **Next move**

        1. Đánh dấu câu nào answerable from approved evidence ngay bây giờ.
        2. Với câu còn thiếu proof, tạo escalation thay vì bịa câu trả lời chắc chắn.
        3. Ship final pack chỉ sau khi các câu critical đã được approve hoặc gắn cờ unresolved rõ ràng.
        """
    ).strip()


def _salvage_user_artifact(request: str, skills_used: list[str]) -> str:
    lowered_skills = {str(item or "").strip().lower() for item in skills_used}
    if _request_wants_protocol_artifact(request):
        return _salvage_protocol_artifact(request)
    if "security-questionnaire" in lowered_skills or _request_is_security_questionnaire(request, list(lowered_skills)):
        return _salvage_security_questionnaire_artifact(request)
    if "ai-stack-watch" in lowered_skills or _request_is_ai_stack_watch(request, list(lowered_skills)):
        return _salvage_ai_stack_watch_artifact(request)
    if "mail-gui" in lowered_skills:
        return _salvage_mail_artifact(request)
    if any("follow" in name for name in lowered_skills):
        return _salvage_follow_up_artifact(request)
    if "book-meeting" in lowered_skills:
        return _salvage_meeting_artifact(request)
    if "scan-doi-thu" in lowered_skills:
        return _salvage_competitor_scan_artifact(request)
    if _request_is_customer_research(request, skills_used):
        return _salvage_customer_research_artifact(request)
    return ""


def _manager_response_shape(goal: str, plan: dict[str, Any] | None = None) -> str:
    skill_names = {
        str(item.get("name") or "").strip().lower()
        for item in list((plan or {}).get("skills") or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    if _request_wants_protocol_artifact(goal):
        return (
            "Do not write council minutes, internal analysis, or generic advice. "
            "Return the structured protocol the user asked for directly, with explicit sections for hypotheses, questions, follow-up message, and stop rule."
        )
    if "security-questionnaire" in skill_names:
        return (
            "Do not write generic policy prose or internal notes. "
            "Return a bounded questionnaire answer pack with sections: Status, Approved evidence, Draft answers, Open gaps, Next move. "
            "Track each critical question explicitly, show its current state, and block final-pack language while approvals are still pending. "
            "Never claim a certification, retention promise, subprocessor fact, or AI-governance fact without clear evidence."
        )
    if "ai-stack-watch" in skill_names:
        return (
            "Do not write a broad market report. "
            "Return a bounded watch brief with sections: Status, Watched changes, Impact on trust answers, Next move. "
            "Keep it focused on provider/model/policy/regulatory changes that affect trust answers."
        )
    if "safe-web-research" in skill_names:
        return (
            "Do not write council minutes, governance review language, or product planning. "
            "Return a bounded source check with short sections: Status, Verified source, Normalized excerpt, Unknowns, Next move. "
            "If the safe fetch was blocked or failed, say that plainly and keep the answer compact."
        )
    if "scan-doi-thu" in skill_names:
        return (
            "Do not write council minutes, board minutes, or governance review language. "
            "Return a bounded competitor scan with short sections: Status, Verified findings, Unknowns, Next move. "
            "If no verified findings are available, say that plainly and keep the answer compact."
        )
    if bool(skill_names.intersection({"mail-gui", "book-meeting"})) or any("follow" in name for name in skill_names):
        return (
            "Do not write internal analysis, worker summaries, or council language. "
            "Return the user-facing draft, checklist, or next executable artifact directly."
        )
    return "Return a concise end-user answer, not internal minutes."


def _skill_specific_execution_addendum(request: str, matched_skills: list[dict[str, Any]]) -> str:
    names = {str(item.get("name") or "").strip().lower() for item in matched_skills}
    lowered = str(request or "").strip().lower()
    lines: list[str] = []
    if _request_wants_protocol_artifact(request):
        lines.extend(
            [
                "The expected artifact is a structured recovery protocol, not internal minutes and not a single email draft.",
                "Return explicit sections for hypotheses, debiasing questions, one follow-up message, and a clear stop rule.",
                "Do not collapse the answer into a council memo, product strategy note, or communication-only template.",
            ]
        )
    if any("follow" in name for name in names) or any(token in lowered for token in ("follow up", "followup", "sau demo", "follow-up")):
        lines.extend(
            [
                "The expected artifact is a concise customer follow-up message or email the user can send immediately.",
                "Do not return product goals, feature scope, acceptance criteria, roadmap, implementation notes, or system design.",
                "If customer name, company, or next step is missing, keep placeholders explicit and offer 2-3 optional follow-up variants.",
            ]
        )
    if "mail-gui" in names or any(token in lowered for token in ("mail", "email", "gửi mail", "gui mail")):
        lines.extend(
            [
                "The expected artifact is a send-ready email or message draft the user can copy now.",
                "Do not return product goals, scope, acceptance criteria, roadmap, implementation notes, or system design.",
                "If recipient or delivery details are missing, use explicit placeholders like [Tên khách], [Email], and [Múi giờ], then list the missing fields in warnings.",
            ]
        )
    if "book-meeting" in names or any(token in lowered for token in ("book meeting", "đặt lịch", "dat lich", "meeting")):
        lines.extend(
            [
                "The expected artifact is either a concise meeting invite draft or a short checklist of missing scheduling details.",
                "Do not invent attendees, exact times, locations, availability, or confirmation state.",
                "Do not return product requirements, feature scope, release planning, or system design.",
                "If details are missing, the sample message must keep placeholders explicit, including [Tên khách] and [Múi giờ].",
            ]
        )
    if "scan-doi-thu" in names or any(token in lowered for token in ("scan", "đối thủ", "doi thu", "competitor")):
        lines.extend(
            [
                "The expected artifact is a bounded competitor scan with verified findings and citations when available.",
                "If live research cannot produce verified findings within the execution window, return a safe scan with explicit unknowns, official-source follow-up targets, and the best narrower next query.",
                "Do not fabricate findings, trend summaries, or bullets without evidence.",
            ]
        )
    if "safe-web-research" in names or _request_prefers_safe_web_research(request):
        lines.extend(
            [
                "The expected artifact is a bounded source check or summary of a public URL using safe text-only fetch behavior.",
                "If a public URL is present, report the fetched URL, fetch status or blocked reason, and a normalized text excerpt or summary based only on that text.",
                "Do not claim JavaScript-rendered, hidden, authenticated, or private content was inspected.",
            ]
        )
    if "security-questionnaire" in names or _request_is_security_questionnaire(request, list(names)):
        lines.extend(
            [
                "The expected artifact is a governed questionnaire answer pack, not generic compliance marketing copy.",
                "Separate approved evidence from draft answers and open gaps, and make each critical question's state visible.",
                "If any critical question is still pending approval, stale, or revoked, say that final trust-pack delivery is blocked.",
                "Never assert certifications, retention guarantees, privacy guarantees, or subprocessor details without explicit proof.",
            ]
        )
    if "ai-stack-watch" in names or _request_is_ai_stack_watch(request, list(names)):
        lines.extend(
            [
                "The expected artifact is a bounded watch brief for AI stack risk, not a competitor battlecard or generic market scan.",
                "Focus on provider, model, pricing, policy, deprecation, or regulatory changes that could change trust answers.",
                "Make the impact on trust answers explicit and name the next verification step.",
            ]
        )
    if _request_is_customer_research(request, [str(item.get("name") or "").strip() for item in matched_skills]):
        lines.extend(
            [
                "The expected artifact is a customer-research starter pack, not a fabricated market report.",
                "If verified evidence is missing, label every buyer segment, pain point, or pricing claim as a hypothesis to validate.",
                "Do not include percentages, market sizes, survey figures, vendor rankings, or citations unless they are actually verified in the current execution context.",
                "End with explicit interview or validation next steps the user can run immediately.",
            ]
        )
    return "\n".join(f"- {line}" for line in lines).strip()


def _manager_step_view(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for step in steps:
        cleaned.append({
            "agent_id": str(step.get("agent_id") or "").strip(),
            "role": str(step.get("role") or "").strip(),
            "task_kind": str(step.get("task_kind") or "").strip(),
            "status": str(step.get("status") or "").strip(),
            "provider_profile": str(step.get("provider_profile") or "").strip(),
            "model": str(step.get("model") or "").strip(),
            "transport_kind": str(step.get("transport_kind") or "").strip(),
            "result": str(step.get("result") or "").strip(),
            "confidence": str(step.get("confidence") or "").strip(),
            "citations": step.get("citations") if isinstance(step.get("citations"), list) else [],
            "warnings": step.get("warnings") if isinstance(step.get("warnings"), list) else [],
            "skills_used": step.get("skills_used") if isinstance(step.get("skills_used"), list) else [],
        })
    return cleaned


def _extract_title(html: str) -> str:
    parser = _TitleParser()
    parser.feed(html)
    return parser.title


def _strip_html(html: str) -> str:
    body = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    body = re.sub(r"<style\b[^>]*>.*?</style>", " ", body, flags=re.IGNORECASE | re.DOTALL)
    body = re.sub(r"<[^>]+>", " ", body)
    body = unescape(body)
    return " ".join(body.split()).strip()


def _excerpt(text: str, limit: int = 320) -> str:
    value = " ".join(text.split()).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _mirror_fetch(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "MeridianGateway/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            html = response.read().decode("utf-8", "replace")
            return {
                "ok": True,
                "final_url": response.geturl(),
                "http_status": getattr(response, "status", None),
                "title": _extract_title(html),
                "excerpt": _excerpt(_strip_html(html)),
                "note": "Local urllib fallback after truthful Loom browser observation.",
            }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"HTTPError {exc.code}: {exc.reason}", "final_url": url}
    except urllib.error.URLError as exc:
        return {"ok": False, "error": f"URLError: {exc.reason}", "final_url": url}
    except Exception as exc:
        return {"ok": False, "error": f"{exc.__class__.__name__}: {exc}", "final_url": url}


def _run_safe_web_fetch(url: str) -> dict[str, Any]:
    script = SKILLS_DIR / "safe-web-research" / "scripts" / "fetch_safe.py"
    if not script.exists():
        return {"ok": False, "error": f"safe_web_fetch_script_missing: {script}"}
    try:
        completed = subprocess.run(
            [sys.executable, str(script), "--url", str(url).strip()],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}
    parsed = _extract_json((completed.stdout or "").strip())
    if not isinstance(parsed, dict):
        return {
            "ok": False,
            "error": (completed.stderr or completed.stdout or "safe_web_fetch_failed").strip(),
        }
    results = list(parsed.get("results") or []) if isinstance(parsed.get("results"), list) else []
    blocked = list(parsed.get("blocked") or []) if isinstance(parsed.get("blocked"), list) else []
    first = dict(results[0]) if results else {}
    if first:
        return {
            "ok": True,
            "url": str(first.get("url") or url).strip(),
            "status": first.get("status"),
            "content_type": str(first.get("content_type") or "").strip(),
            "normalized_text": str(first.get("normalized_text") or "").strip(),
            "bytes": first.get("bytes"),
            "blocked": blocked,
        }
    if blocked:
        reason = str(dict(blocked[0]).get("reason") or "").strip()
        return {"ok": False, "url": str(url).strip(), "blocked": blocked, "error": reason or "safe_web_fetch_blocked"}
    return {"ok": False, "url": str(url).strip(), "error": "safe_web_fetch_returned_no_result"}


def _loom_cli_prefix() -> list[str]:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return ["sudo", "-u", "ubuntu", "-H"]
    return []


def _load_runtime_config_or_exit() -> dict[str, Any]:
    global LLM_BASE_URL, LLM_MODEL, LLM_API_KEY
    try:
        config = load_config(required=True)
    except FileNotFoundError:
        print("Configuration missing. Run python3 meridian_setup.py first.", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"Failed to load meridian_config.json: {exc}", file=sys.stderr)
        raise SystemExit(1)

    config["telegram_bot_token"] = (
        os.environ.get("MERIDIAN_TELEGRAM_BOT_TOKEN")
        or os.environ.get("TELEGRAM_BOT_TOKEN")
        or str(config.get("telegram_bot_token") or "")
    ).strip()
    config["allowed_origin"] = (
        os.environ.get("MERIDIAN_ALLOWED_ORIGIN")
        or str(config.get("allowed_origin") or "")
    ).strip()

    LLM_BASE_URL = str(config.get("llm_base_url") or "").strip()
    LLM_MODEL = str(config.get("llm_model") or "").strip()
    LLM_API_KEY = str(config.get("llm_api_key") or "").strip()
    return config


def _load_workspace_basic_credentials() -> tuple[str, str]:
    user = ""
    password = ""
    try:
        for raw_line in WORKSPACE_CREDENTIALS_FILE.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key == "user":
                user = value
            elif key == "pass":
                password = value
    except Exception:
        return "", ""
    return user, password


def _workspace_api_get_json(path: str, *, timeout_seconds: float = 20.0) -> dict[str, Any]:
    normalized_path = path if path.startswith("/") else f"/{path}"
    url = f"{WORKSPACE_API_BASE}{normalized_path}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "MeridianGateway/1.0",
    }
    user, password = _load_workspace_basic_credentials()
    if user and password:
        token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=max(0.1, float(timeout_seconds or 20.0))) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
            return {
                "ok": True,
                "status_code": getattr(response, "status", 200),
                "payload": payload if isinstance(payload, dict) else {"status": "success", "output": payload},
            }
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        payload = _extract_json(detail)
        return {
            "ok": False,
            "status_code": exc.code,
            "payload": payload if isinstance(payload, dict) else {"status": "error", "output": detail or exc.reason},
        }
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "status_code": 502,
            "payload": {"status": "error", "output": f"workspace_unreachable: {exc.reason}"},
        }
    except Exception as exc:
        return {
            "ok": False,
            "status_code": 502,
            "payload": {"status": "error", "output": f"{exc.__class__.__name__}: {exc}"},
        }


def _workspace_api_post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_path = path if path.startswith("/") else f"/{path}"
    url = f"{WORKSPACE_API_BASE}{normalized_path}"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "MeridianGateway/1.0",
    }
    user, password = _load_workspace_basic_credentials()
    if user and password:
        token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    body = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8", "replace")
            parsed = _extract_json(raw)
            return {
                "ok": True,
                "status_code": getattr(response, "status", 200),
                "payload": parsed if isinstance(parsed, dict) else {"status": "success", "output": raw},
            }
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        payload = _extract_json(detail)
        return {
            "ok": False,
            "status_code": exc.code,
            "payload": payload if isinstance(payload, dict) else {"status": "error", "output": detail or exc.reason},
        }
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "status_code": 502,
            "payload": {"status": "error", "output": f"workspace_unreachable: {exc.reason}"},
        }
    except Exception as exc:
        return {
            "ok": False,
            "status_code": 502,
            "payload": {"status": "error", "output": f"{exc.__class__.__name__}: {exc}"},
        }


def _workspace_api_get_json_with_timeout(path: str, timeout_seconds: float) -> dict[str, Any]:
    try:
        return _workspace_api_get_json(path, timeout_seconds=timeout_seconds)
    except TypeError:
        # Backward compatibility for tests that patch _workspace_api_get_json(path).
        return _workspace_api_get_json(path)


def _float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _status_payload_repair_treasury(payload: dict[str, Any]) -> dict[str, Any]:
    treasury = dict(payload.get("treasury") or {})
    balance_usd = _float_or_none(treasury.get("balance_usd"))
    reserve_floor_usd = _float_or_none(treasury.get("reserve_floor_usd"))
    if balance_usd is not None:
        treasury["balance_usd"] = balance_usd
    if reserve_floor_usd is not None:
        treasury["reserve_floor_usd"] = reserve_floor_usd

    if balance_usd is None or reserve_floor_usd is None:
        treasury_result = _workspace_api_get_json_with_timeout(
            "/api/treasury",
            min(4.0, max(0.1, WORKSPACE_STATUS_UPSTREAM_TIMEOUT_SECONDS)),
        )
        treasury_payload = dict(treasury_result.get("payload") or {}) if treasury_result.get("ok") else {}
        if balance_usd is None:
            fallback_balance = _float_or_none(treasury_payload.get("balance_usd"))
            if fallback_balance is not None:
                treasury["balance_usd"] = fallback_balance
        if reserve_floor_usd is None:
            fallback_floor = _float_or_none(treasury_payload.get("reserve_floor_usd"))
            if fallback_floor is not None:
                treasury["reserve_floor_usd"] = fallback_floor
        if treasury.get("paid_orders") is None:
            paid_orders = treasury_payload.get("paid_orders")
            try:
                treasury["paid_orders"] = int(paid_orders)
            except (TypeError, ValueError):
                pass

    payload["treasury"] = treasury
    return payload


_STATUS_WORDING_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("founder_led_pilot_with_public_paid_checkout", "open_source_setup_only"),
    ("pilot_intake_with_public_checkout_preview", "deprecated_intake_open_source_mode"),
    ("/api/pilot/intake/operator/review", "/setup"),
    ("/api/pilot/intake/operator", "/setup"),
    ("/api/pilot/intake", "/setup"),
    ("/api/subscriptions/checkout-capture", "deprecated_capture_open_source_mode"),
    ("Deliver brief through the current honest customer path", "Deliver brief through the current honest operator path"),
    (
        "Record first external support contribution or first real customer payment",
        "Record first external support contribution or first verified external settlement",
    ),
    ("Founder-Backed Build", "Maintainer-Backed Build"),
    ("founding_service_only", "host_bound_service_only"),
    ("founding_workspace_local", "host_bound_workspace_local"),
    ("founding_locked", "host_bound_locked"),
    ("founding-locked", "host-bound-locked"),
    ("founding-only", "host-bound only"),
    ("founding only", "host-bound only"),
    ("founding institution only", "host-bound institution only"),
    ("founding institution", "host-bound institution"),
)

_STATUS_KEY_REPLACEMENTS: dict[str, str] = {
    "pilot_intake": "community_intake",
    "subscription_preview": "service_preview",
    "public_checkout_paths": "public_support_paths",
    "checkout_preview_publication_enabled": "support_preview_publication_enabled",
    "checkout_claimed_count": "support_claimed_count",
    "checkout_capture_path": "capture_path",
    "checkout_capture": "capture",
    "pilot_intake_requested": "community_intake_requested",
    "pilot_intake_reviewed": "community_intake_reviewed",
}


def _normalize_status_keys(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = _STATUS_KEY_REPLACEMENTS.get(str(key), str(key))
            normalized[normalized_key] = _normalize_status_keys(item)
        return normalized
    if isinstance(value, list):
        return [_normalize_status_keys(item) for item in value]
    return value


def _normalize_status_wording(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _normalize_status_wording(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_status_wording(item) for item in value]
    if isinstance(value, str):
        normalized = value
        for source, target in _STATUS_WORDING_REPLACEMENTS:
            normalized = normalized.replace(source, target)
        return normalized
    return value


def _normalize_status_payload_for_open_source(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_status_wording(_normalize_status_keys(payload))

    service_state = normalized.get("service_state")
    if isinstance(service_state, dict):
        if isinstance(service_state.get("community_intake"), dict):
            service_state["setup_intake"] = {
                "status": "deprecated",
                "reason": "open_source_mode",
                "message": "Public intake preview routes are deprecated in open-source mode.",
                "setup_path": "/setup",
            }
            service_state.pop("community_intake", None)

        subscriptions_state = service_state.get("subscriptions")
        if isinstance(subscriptions_state, dict):
            subscriptions_state["public_support_paths"] = {}
            subscriptions_state["open_source_mode"] = True

        preview_state = service_state.get("service_preview")
        if isinstance(preview_state, dict):
            preview_state["public_intake_path"] = "/setup"
            queue_paths = preview_state.get("queue_paths")
            if isinstance(queue_paths, dict):
                queue_paths["public_intake"] = "/setup"
                queue_paths["source_review"] = "/setup"
                queue_paths.pop("capture", None)
                queue_paths["capture"] = "deprecated_open_source_mode"

    observability = normalized.get("observability")
    if isinstance(observability, dict):
        metrics = observability.get("metrics")
        if isinstance(metrics, dict):
            audit_metrics = metrics.get("audit")
            if isinstance(audit_metrics, dict):
                actions = audit_metrics.get("actions")
                if isinstance(actions, dict):
                    remapped_actions: dict[str, Any] = {}
                    for key, value in actions.items():
                        if key in {"pilot_intake_requested", "community_intake_requested"}:
                            remapped_actions["setup_intake_requested_deprecated"] = value
                        elif key in {"pilot_intake_reviewed", "community_intake_reviewed"}:
                            remapped_actions["setup_intake_reviewed_deprecated"] = value
                        else:
                            remapped_actions[key] = value
                    audit_metrics["actions"] = remapped_actions

    persistence = normalized.get("persistence")
    if isinstance(persistence, dict) and isinstance(persistence.get("seams"), list):
        filtered_seams = []
        for seam in persistence.get("seams") or []:
            if not isinstance(seam, dict):
                filtered_seams.append(seam)
                continue
            fingerprint = " ".join(
                str(seam.get(field) or "").lower()
                for field in ("name", "path", "owner")
            )
            if "pilot_intake" in fingerprint or "checkout" in fingerprint:
                continue
            filtered_seams.append(seam)
        persistence["seams"] = filtered_seams

    return normalized


def _workspace_status_snapshot_cached() -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    with WORKSPACE_STATUS_CACHE_LOCK:
        cached_at = int(WORKSPACE_STATUS_CACHE.get("fetched_at_unix_ms") or 0)
        cached_snapshot = WORKSPACE_STATUS_CACHE.get("snapshot")
        has_cached = isinstance(cached_snapshot, dict)
        if (
            has_cached
            and cached_at > 0
            and (now_ms - cached_at) <= max(1, WORKSPACE_STATUS_CACHE_TTL_SECONDS) * 1000
        ):
            payload = _normalize_status_payload_for_open_source(
                _status_payload_repair_treasury(dict(cached_snapshot))
            )
            payload["gateway_cache"] = {
                "state": "fresh",
                "cached_at_unix_ms": cached_at,
                "age_ms": now_ms - cached_at,
            }
            return {"ok": True, "status_code": 200, "payload": payload}

    if has_cached:
        with WORKSPACE_STATUS_REFRESH_LOCK:
            global WORKSPACE_STATUS_REFRESH_IN_FLIGHT
            if not WORKSPACE_STATUS_REFRESH_IN_FLIGHT:
                WORKSPACE_STATUS_REFRESH_IN_FLIGHT = True

                def _refresh_workspace_status() -> None:
                    try:
                        refreshed = _workspace_api_get_json_with_timeout(
                            "/api/status",
                            WORKSPACE_STATUS_UPSTREAM_TIMEOUT_SECONDS,
                        )
                        if refreshed.get("ok") and isinstance(refreshed.get("payload"), dict):
                            with WORKSPACE_STATUS_CACHE_LOCK:
                                WORKSPACE_STATUS_CACHE["fetched_at_unix_ms"] = int(time.time() * 1000)
                                WORKSPACE_STATUS_CACHE["snapshot"] = dict(refreshed["payload"])
                    finally:
                        with WORKSPACE_STATUS_REFRESH_LOCK:
                            global WORKSPACE_STATUS_REFRESH_IN_FLIGHT
                            WORKSPACE_STATUS_REFRESH_IN_FLIGHT = False

                threading.Thread(target=_refresh_workspace_status, daemon=True).start()

        payload = _normalize_status_payload_for_open_source(
            _status_payload_repair_treasury(dict(cached_snapshot))
        )
        payload["gateway_cache"] = {
            "state": "stale_fallback",
            "cached_at_unix_ms": cached_at,
            "age_ms": max(0, now_ms - cached_at),
            "refreshing": True,
        }
        return {"ok": True, "status_code": 200, "payload": payload}

    proxied = _workspace_api_get_json_with_timeout(
        "/api/status",
        WORKSPACE_STATUS_UPSTREAM_TIMEOUT_SECONDS,
    )
    if proxied.get("ok") and isinstance(proxied.get("payload"), dict):
        snapshot = _normalize_status_payload_for_open_source(
            _status_payload_repair_treasury(dict(proxied["payload"]))
        )
        with WORKSPACE_STATUS_CACHE_LOCK:
            WORKSPACE_STATUS_CACHE["fetched_at_unix_ms"] = now_ms
            WORKSPACE_STATUS_CACHE["snapshot"] = snapshot
        payload = dict(snapshot)
        payload["gateway_cache"] = {
            "state": "fresh",
            "cached_at_unix_ms": now_ms,
            "age_ms": 0,
        }
        return {"ok": True, "status_code": 200, "payload": payload}

    degraded = {
        "runtime_id": "loom_native",
        "proof_mode": "live_single_host_loom_deployment",
        "queue_count": 0,
        "pending_delivery_count": 0,
        "delivered_count": 0,
        "slo": {
            "policy_name": "meridian_observability_slo_v1",
            "status": "degraded",
            "alert_count": 1,
            "objective_count": 0,
            "healthy_objective_count": 0,
            "alerts": [],
        },
        "runtime_proof": {
            "runtime_proof_status": "degraded",
            "channel_surface_status": "degraded",
            "trust_ops_status": "degraded",
        },
        "treasury": {
            "balance_usd": 0.0,
            "reserve_floor_usd": 0.0,
        },
        "gateway_cache": {
            "state": "degraded_fallback",
            "upstream_status_code": int(proxied.get("status_code") or 0),
            "upstream_error": str((proxied.get("payload") or {}).get("output") or "workspace_status_unavailable"),
            "generated_at_unix_ms": now_ms,
        },
    }
    degraded = _normalize_status_payload_for_open_source(_status_payload_repair_treasury(degraded))
    return {"ok": True, "status_code": 200, "payload": degraded}


def _workflow_showcase_snapshot_cached() -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    with WORKFLOW_SHOWCASE_CACHE_LOCK:
        cached_at = int(WORKFLOW_SHOWCASE_CACHE.get("fetched_at_unix_ms") or 0)
        cached_snapshot = WORKFLOW_SHOWCASE_CACHE.get("snapshot")
        has_cached = isinstance(cached_snapshot, dict)
        if (
            has_cached
            and cached_at > 0
            and (now_ms - cached_at) <= max(1, WORKFLOW_SHOWCASE_CACHE_TTL_SECONDS) * 1000
        ):
            snapshot = _normalize_status_wording(dict(cached_snapshot))
            snapshot["gateway_cache"] = {
                "state": "fresh",
                "cached_at_unix_ms": cached_at,
                "age_ms": now_ms - cached_at,
            }
            return snapshot

    if has_cached:
        with WORKFLOW_SHOWCASE_REFRESH_LOCK:
            global WORKFLOW_SHOWCASE_REFRESH_IN_FLIGHT
            if not WORKFLOW_SHOWCASE_REFRESH_IN_FLIGHT:
                WORKFLOW_SHOWCASE_REFRESH_IN_FLIGHT = True

                def _refresh_workflow_showcase() -> None:
                    try:
                        refreshed = _build_workflow_showcase_snapshot()
                        with WORKFLOW_SHOWCASE_CACHE_LOCK:
                            WORKFLOW_SHOWCASE_CACHE["fetched_at_unix_ms"] = int(time.time() * 1000)
                            WORKFLOW_SHOWCASE_CACHE["snapshot"] = dict(refreshed)
                    finally:
                        with WORKFLOW_SHOWCASE_REFRESH_LOCK:
                            global WORKFLOW_SHOWCASE_REFRESH_IN_FLIGHT
                            WORKFLOW_SHOWCASE_REFRESH_IN_FLIGHT = False

                threading.Thread(target=_refresh_workflow_showcase, daemon=True).start()

        snapshot = _normalize_status_wording(dict(cached_snapshot))
        snapshot["gateway_cache"] = {
            "state": "stale_fallback",
            "cached_at_unix_ms": cached_at,
            "age_ms": max(0, now_ms - cached_at),
            "refreshing": True,
        }
        return snapshot

    try:
        snapshot = _normalize_status_wording(_build_workflow_showcase_snapshot())
        with WORKFLOW_SHOWCASE_CACHE_LOCK:
            WORKFLOW_SHOWCASE_CACHE["fetched_at_unix_ms"] = now_ms
            WORKFLOW_SHOWCASE_CACHE["snapshot"] = dict(snapshot)
        snapshot["gateway_cache"] = {
            "state": "fresh",
            "cached_at_unix_ms": now_ms,
            "age_ms": 0,
        }
        return snapshot
    except Exception as exc:
        with WORKFLOW_SHOWCASE_CACHE_LOCK:
            cached_at = int(WORKFLOW_SHOWCASE_CACHE.get("fetched_at_unix_ms") or 0)
            cached_snapshot = WORKFLOW_SHOWCASE_CACHE.get("snapshot")
        if isinstance(cached_snapshot, dict):
            snapshot = _normalize_status_wording(dict(cached_snapshot))
            snapshot["gateway_cache"] = {
                "state": "stale_fallback",
                "cached_at_unix_ms": cached_at,
                "age_ms": max(0, now_ms - cached_at),
                "error": f"{exc.__class__.__name__}: {exc}",
            }
            return snapshot
        return {
            "schema_version": "meridian.workflow_showcase.v1",
            "generated_at_unix_ms": now_ms,
            "runtime_id": "loom_native",
            "proof_type": "degraded",
            "treasury_balance_usd": 0.0,
            "treasury_reserve_floor_usd": 0.0,
            "paid_orders": 0,
            "payout_proposals": 0,
            "payout_phase": {
                "number": None,
                "name": "degraded_fallback",
                "execution_gate_ok": False,
                "execution_gate_reason": f"{exc.__class__.__name__}: {exc}",
            },
            "telegram_delivery": {"recent_count": 0, "last_delivery_at": "", "recent": []},
            "workflows": [],
            "gateway_cache": {
                "state": "degraded_fallback",
                "generated_at_unix_ms": now_ms,
                "error": f"{exc.__class__.__name__}: {exc}",
            },
        }


class AgentRuntime:
    def __init__(self, skills: SkillRegistry) -> None:
        self.skills = skills
        self.lock = threading.Lock()

    def _load_soul(self) -> str:
        return SOUL_PATH.read_text(encoding="utf-8").strip()

    def _load_memory(self) -> str:
        return MEMORY_PATH.read_text(encoding="utf-8").strip()

    def _system_prompt(self, soul: str, memory: str) -> str:
        return textwrap.dedent(
            f"""
            {soul}

            Current Markdown memory:
            {memory}

            You are Meridian Gateway AgentRuntime.
            Return strictly valid JSON with:
            - thought: string
            - tool_call: null or {{ capability: string, payload: object }}
            - final_answer: optional string when done

            Available capabilities:
            - loom.browser.navigate.v1 -> fetches a URL. payload {{"url": "https://example.com"}}
            - loom.fs.write.v1 -> writes content into the bounded Loom workspace. payload {{"path": "workspace/file.txt", "content": "text"}}
            - loom.system.info.v1 -> returns a bounded system snapshot. payload {{}}
            - loom.memory.core.v1 -> safely updates MEMORY.md via Loom. payload {{"markdown": "# MEMORY.md ..."}}

            Loaded skills:
            {self.skills.prompt_block()}

            Rules:
            - Use one tool call at a time.
            - Be truthful about failures.
            - If no proactive action is needed during heartbeat, return final_answer exactly SLEEP.
            - For direct user requests, complete the task if possible and keep final answers concise.
            """
        ).strip()

    def _chat(self, messages: list[dict[str, str]]) -> str:
        system_prompt = ""
        user_parts: list[str] = []
        for message in messages:
            role = str(message.get("role") or "user").strip().lower()
            content = str(message.get("content") or "")
            if role == "system" and not system_prompt:
                system_prompt = content
            elif content.strip():
                if role == "user":
                    user_parts.append(content)
                else:
                    user_parts.append(f"[{role}] {content}")
        defaults = _loom_manager_defaults()
        user_prompt = "\n\n".join(part for part in user_parts if part.strip())
        manager_result = _run_codex_exec(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=defaults["model"],
        )
        if not manager_result.get("ok"):
            raise RuntimeError(manager_result.get("stderr") or manager_result.get("stdout") or "manager route failed")
        output = str(manager_result.get("output_text") or "").strip()
        if not output:
            raise RuntimeError("manager route returned empty output_text")
        return output

    def _valid_step(self, payload: dict[str, Any] | None) -> bool:
        if not isinstance(payload, dict):
            return False
        if not isinstance(payload.get("thought"), str):
            return False
        tool_call = payload.get("tool_call")
        final_answer = str(payload.get("final_answer") or "").strip()
        if tool_call is None and not final_answer:
            return False
        if tool_call is not None and not isinstance(tool_call, dict):
            return False
        return True

    def _llm_step(self, goal: str, history: list[dict[str, Any]], *, heartbeat: bool) -> dict[str, Any]:
        soul = self._load_soul()
        memory = self._load_memory()
        system_prompt = self._system_prompt(soul, memory)
        instruction = (
            "Decide the next single action. Return strict JSON only. Include either a tool_call or a final_answer."
        )
        if heartbeat:
            instruction = (
                "Silent heartbeat review: decide whether proactive action is needed right now. "
                "If no action is needed, return final_answer exactly SLEEP and tool_call null. "
                "If action is needed, choose the smallest safe next step. Return strict JSON only."
            )
        base_messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "goal": goal,
                        "history": history,
                        "instruction": instruction,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
            },
        ]
        raw = self._chat(base_messages)
        parsed = _extract_json(raw)
        if self._valid_step(parsed):
            return parsed
        last = raw
        for _attempt in range(2):
            repair_messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "goal": goal,
                            "history": history,
                            "bad_response": last,
                            "instruction": "Repair bad_response into strict JSON with keys thought, tool_call, final_answer. Return JSON only.",
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                },
            ]
            last = self._chat(repair_messages)
            parsed = _extract_json(last)
            if self._valid_step(parsed):
                return parsed
        raise ValueError(f"LLM did not return valid JSON after repair attempts: {last}")

    def _normalize_tool_call(self, tool_call: Any) -> tuple[str, dict[str, Any]]:
        if not isinstance(tool_call, dict):
            raise ValueError(f"tool_call must be an object, got: {tool_call!r}")
        capability = str(tool_call.get("capability") or "").strip()
        if not capability:
            raise ValueError("tool_call missing capability")
        payload = tool_call.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        if capability == "loom.browser.navigate.v1":
            payload = {"url": str(payload.get("url") or payload.get("href") or payload.get("target_url") or "").strip()}
        elif capability == "loom.fs.write.v1":
            payload = {
                "path": str(payload.get("path") or payload.get("file_path") or "workspace/output.txt").strip(),
                "content": str(payload.get("content") or payload.get("text") or payload.get("body") or ""),
            }
        elif capability == "loom.memory.core.v1":
            payload = {"markdown": str(payload.get("markdown") or payload.get("content") or payload.get("text") or "").strip()}
        elif capability == "loom.system.info.v1":
            payload = {}
        return capability, payload

    def _load_json_file(self, path: str) -> dict[str, Any]:
        candidate = str(path or "").strip()
        if not candidate or not os.path.exists(candidate):
            return {}
        with open(candidate, encoding="utf-8") as handle:
            return json.load(handle)

    def _run_loom(self, capability: str, payload: dict[str, Any]) -> dict[str, Any]:
        resolved_action_type = "execute"
        resolved_resource = capability
        if capability == "loom.browser.navigate.v1":
            resolved_action_type = "research"
            resolved_resource = str(payload.get("url") or "web_fetch").strip() or "web_fetch"
        elif capability == "loom.fs.write.v1":
            resolved_action_type = "write"
            resolved_resource = str(payload.get("path") or "workspace/output.txt").strip() or "workspace/output.txt"
        elif capability == "loom.memory.core.v1":
            resolved_action_type = "write"
            resolved_resource = LOOM_MEMORY_PATH
        elif capability == "loom.system.info.v1":
            resolved_action_type = "observe"
            resolved_resource = "system_snapshot"
        elif capability == "loom.llm.inference.v1":
            resolved_action_type = "synthesize"
            resolved_resource = str(payload.get("model") or "llm_inference").strip() or "llm_inference"
        estimated_cost_usd = estimate_capability_cost_usd(
            capability,
            payload,
            action_type=resolved_action_type,
            resource=resolved_resource,
        )
        command = _loom_cli_prefix() + [
            LOOM_BIN,
            "action",
            "execute",
            "--root",
            LOOM_ROOT,
            "--org-id",
            LOOM_ORG_ID,
            "--agent-id",
            LOOM_AGENT_ID,
            "--capability",
            capability,
            "--action-type",
            resolved_action_type,
            "--resource",
            resolved_resource,
            "--estimated-cost-usd",
            format_estimated_cost_usd(estimated_cost_usd),
            "--payload-json",
            json.dumps(payload, ensure_ascii=False),
            "--format",
            "json",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=REQUEST_TIMEOUT_SECONDS,
                check=False,
            )
        except Exception as exc:
            return {"ok": False, "capability": capability, "payload": payload, "error": f"{exc.__class__.__name__}: {exc}"}

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        parsed_stdout = _extract_json(stdout) or {}
        observation: dict[str, Any] = {
            "ok": completed.returncode == 0,
            "capability": capability,
            "payload": payload,
            "estimated_cost_usd": estimated_cost_usd,
            "action_type": resolved_action_type,
            "resource": resolved_resource,
            "returncode": completed.returncode,
            "stderr": stderr,
        }
        if parsed_stdout:
            observation["runtime"] = {
                "status": parsed_stdout.get("status"),
                "runtime_outcome": parsed_stdout.get("runtime_outcome"),
                "worker_status": parsed_stdout.get("worker_status"),
            }
        worker_result = self._load_json_file(parsed_stdout.get("worker_result_path", ""))
        if worker_result:
            observation["worker_status"] = worker_result.get("status")
            host_response = worker_result.get("host_response_json", {})
            if isinstance(host_response, str):
                try:
                    host_response = json.loads(host_response)
                except json.JSONDecodeError:
                    host_response = {}
            if capability == "loom.browser.navigate.v1" and isinstance(host_response, dict):
                observation["browser_view"] = {
                    "final_url": str(host_response.get("final_url") or payload.get("url") or "").strip(),
                    "title": str(host_response.get("title") or "").strip(),
                    "note": str(host_response.get("note") or "").strip(),
                }
                excerpt = _excerpt(str(host_response.get("body_excerpt_utf8") or "").strip())
                if excerpt:
                    observation["browser_view"]["excerpt"] = excerpt
                if not observation["browser_view"].get("title") and not observation["browser_view"].get("excerpt"):
                    observation["mirror_fetch"] = _mirror_fetch(payload.get("url", ""))
            elif capability == "loom.fs.write.v1" and isinstance(host_response, dict):
                observation["fs_write"] = {
                    "path": str(host_response.get("path") or payload.get("path") or "").strip(),
                    "bytes_written": host_response.get("bytes_written"),
                    "note": str(host_response.get("note") or "").strip(),
                }
            elif capability == "loom.system.info.v1" and isinstance(host_response, dict):
                observation["system_info"] = {
                    "hostname": str(host_response.get("hostname_utf8") or "").strip(),
                    "uname": str(host_response.get("uname_utf8") or "").strip(),
                    "note": str(host_response.get("note") or "").strip(),
                }
            elif capability == "loom.llm.inference.v1" and isinstance(host_response, dict):
                observation["llm_response"] = {
                    "model": str(host_response.get("model") or payload.get("model") or "").strip(),
                    "output_text": str(host_response.get("output_text") or "").strip(),
                    "finish_reason": str(host_response.get("finish_reason") or "").strip(),
                    "prompt_tokens": host_response.get("prompt_tokens"),
                    "completion_tokens": host_response.get("completion_tokens"),
                    "note": str(host_response.get("note") or "").strip(),
                }
        else:
            observation["stdout_excerpt"] = stdout[:500]
        return observation

    def _run_tool(self, capability: str, payload: dict[str, Any]) -> dict[str, Any]:
        if capability == "loom.memory.core.v1":
            markdown = str(payload.get("markdown") or "").strip()
            executed = self._run_loom("loom.fs.write.v1", {"path": LOOM_MEMORY_PATH, "content": markdown})
            executed["capability"] = capability
            if executed.get("ok") and markdown:
                MEMORY_PATH.write_text(markdown + ("\n" if not markdown.endswith("\n") else ""), encoding="utf-8")
                executed["memory_path"] = str(MEMORY_PATH)
                executed["loom_memory_path"] = LOOM_MEMORY_PATH
            return executed
        return self._run_loom(capability, payload)

    def _history_view(self, observation: dict[str, Any]) -> dict[str, Any]:
        history = {
            "ok": bool(observation.get("ok")),
            "capability": observation.get("capability"),
            "worker_status": observation.get("worker_status"),
            "stderr": observation.get("stderr") or "",
        }
        for key in ("browser_view", "mirror_fetch", "fs_write", "system_info", "memory_path", "loom_memory_path"):
            if key in observation:
                history[key] = observation[key]
        return history

    def run_goal(self, goal: str, *, heartbeat: bool = False) -> str:
        with self.lock:
            history: list[dict[str, Any]] = []
            for _step in range(1, MAX_STEPS + 1):
                step = self._llm_step(goal, history, heartbeat=heartbeat)
                thought = str(step.get("thought") or "").strip()
                tool_call = step.get("tool_call")
                final_answer = str(step.get("final_answer") or "").strip()
                if tool_call is not None:
                    capability, payload = self._normalize_tool_call(tool_call)
                    observation = self._run_tool(capability, payload)
                    history.append({"role": "thought", "value": thought})
                    history.append({"role": "tool_call", "value": {"capability": capability, "payload": payload}})
                    history.append({"role": "observation", "value": self._history_view(observation)})
                    continue
                if final_answer:
                    if heartbeat and final_answer.strip().upper() == "SLEEP":
                        return ""
                    return final_answer
                history.append({"role": "thought", "value": thought})
                history.append({"role": "observation", "value": {"ok": False, "error": "missing tool_call and final_answer"}})
            return "Unable to complete the request within the configured step limit."


class ChannelAdapter(ABC):
    def __init__(self, runtime: AgentRuntime, name: str) -> None:
        self.runtime = runtime
        self.name = name
        self._active = False

    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def send_message(self, text: str, *, source: str = "runtime") -> None:
        raise NotImplementedError

    def is_active(self) -> bool:
        return self._active


class TelegramAdapter(ChannelAdapter):
    def __init__(self, runtime: AgentRuntime, bot_token: str) -> None:
        super().__init__(runtime, "telegram")
        self.bot_token = bot_token.strip()
        self.thread: threading.Thread | None = None
        self.drain_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.next_offset: int | None = None
        self.active_chats: set[int | str] = set()
        self.active_lock = threading.Lock()

    def start(self) -> None:
        if not self.bot_token:
            _log("telegram adapter disabled: no bot token configured", color=ANSI_YELLOW)
            return
        self._active = True
        self.thread = threading.Thread(target=self._poll_loop, name="telegram-adapter", daemon=True)
        self.thread.start()
        self.drain_thread = threading.Thread(target=self._drain_loop, name="telegram-drain", daemon=True)
        self.drain_thread.start()
        _log("telegram adapter started: polling active", color=ANSI_GREEN)

    def stop(self) -> None:
        self.stop_event.set()

    def _telegram_request(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{self.bot_token}/{method}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=40) as response:
            body = json.loads(response.read().decode("utf-8", "replace"))
        if not body.get("ok"):
            raise RuntimeError(body.get("description") or f"Telegram API call failed: {method}")
        return body

    def _send_direct(self, chat_id: int | str, text: str, *, reply_to_message_id: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
        body = self._telegram_request("sendMessage", payload)
        result = body.get("result") if isinstance(body, dict) else {}
        return result if isinstance(result, dict) else {}

    def send_message(self, text: str, *, source: str = "runtime") -> None:
        with self.active_lock:
            targets = list(self.active_chats)
        for chat_id in targets:
            session_key = f"telegram:{chat_id}"
            duplicate = _recent_telegram_delivery_duplicate(str(chat_id), text)
            if duplicate:
                _record_gateway_audit(
                    "telegram_proactive_delivery_deduped",
                    session_key=session_key,
                    channel="telegram",
                    text=text,
                    extra_details={
                        "existing_delivery_id": str(duplicate.get("delivery_id") or "").strip(),
                        "source": source,
                    },
                )
                continue
            delivery = _loom_channel_send("telegram", str(chat_id), text)
            delivery_payload = delivery.get("payload") if isinstance(delivery, dict) else {}
            delivery_id = str((delivery_payload or {}).get("delivery_id") or "").strip()
            try:
                result = self._send_direct(chat_id, text)
                _loom_channel_update(
                    delivery_id,
                    "delivered",
                    external_ref=str((result or {}).get("message_id") or str(chat_id)).strip(),
                    detail="",
                )
                _loom_session_route(
                    session_key,
                    agent_id=TEAM_MANAGER_AGENT_ID,
                    org_id=LOOM_ORG_ID,
                    delivery_id=delivery_id,
                )
            except Exception as exc:
                _loom_channel_update(delivery_id, "failed", detail=f"{exc.__class__.__name__}: {exc}")
                _log(f"telegram proactive delivery failed for {chat_id}: {exc}", color=ANSI_YELLOW)

    def _drain_loop(self) -> None:
        while not self.stop_event.wait(2):
            try:
                self._drain_pending_deliveries()
            except Exception as exc:
                _log(f"telegram drain warning: {exc}", color=ANSI_YELLOW)

    def _drain_pending_deliveries(self) -> None:
        cutoff_ms = int(time.time() * 1000) - 1000
        for record in _loom_channel_deliveries(limit=50):
            if str(record.get("channel_id") or "").strip() != "telegram":
                continue
            if str(record.get("status") or "").strip() != "queued":
                continue
            submitted_at = int(record.get("submitted_at_unix_ms") or 0)
            if submitted_at > cutoff_ms:
                continue
            delivery_id = str(record.get("delivery_id") or "").strip()
            recipient = str(record.get("recipient") or "").strip()
            text = str(record.get("display_text") or "").strip()
            if not delivery_id or not recipient or not text:
                continue
            duplicate = _recent_telegram_delivery_duplicate(recipient, text)
            if duplicate and str(duplicate.get("delivery_id") or "").strip() != delivery_id:
                _loom_channel_update(
                    delivery_id,
                    "delivered",
                    external_ref=f"dedup:{str(duplicate.get('delivery_id') or '').strip()}",
                    detail="duplicate queued telegram delivery suppressed",
                )
                _record_gateway_audit(
                    "telegram_queued_delivery_deduped",
                    session_key=f"telegram:{recipient}",
                    channel="telegram",
                    text=text,
                    delivery_id=delivery_id,
                    extra_details={"existing_delivery_id": str(duplicate.get("delivery_id") or "").strip()},
                )
                continue
            try:
                result = self._send_direct(recipient, text)
                with self.active_lock:
                    self.active_chats.add(recipient)
                _loom_channel_update(
                    delivery_id,
                    "delivered",
                    external_ref=str((result or {}).get("message_id") or recipient).strip(),
                    detail="",
                )
                _loom_session_route(
                    f"telegram:{recipient}",
                    agent_id=TEAM_MANAGER_AGENT_ID,
                    org_id=LOOM_ORG_ID,
                    delivery_id=delivery_id,
                )
            except Exception as exc:
                _loom_channel_update(delivery_id, "failed", detail=f"{exc.__class__.__name__}: {exc}")
                _log(f"telegram queued delivery failed for {recipient}: {exc}", color=ANSI_YELLOW)

    def _poll_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                payload: dict[str, Any] = {"timeout": 30, "allowed_updates": ["message"]}
                if self.next_offset is not None:
                    payload["offset"] = self.next_offset
                body = self._telegram_request("getUpdates", payload)
                for update in body.get("result") or []:
                    if not isinstance(update, dict):
                        continue
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        self.next_offset = update_id + 1
                    message = update.get("message")
                    if isinstance(message, dict):
                        self._handle_message(message)
            except Exception as exc:
                _log(f"telegram adapter warning: {exc}", color=ANSI_YELLOW)
                self.stop_event.wait(2)

    def _handle_message(self, message: dict[str, Any]) -> None:
        text = message.get("text")
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        message_id = message.get("message_id")
        if not isinstance(text, str) or not text.strip() or chat_id is None:
            return
        if _telegram_inbound_seen_recently(chat_id, message_id, text.strip()):
            _record_gateway_audit(
                "manager_request_deduped",
                session_key=f"telegram:{chat_id}",
                channel="telegram",
                text=text.strip(),
                extra_details={"telegram_chat_id": str(chat_id), "reply_to_message_id": message_id or ""},
            )
            return
        with self.active_lock:
            self.active_chats.add(chat_id)
        ingress = _loom_channel_ingest("telegram", str(chat_id), text.strip(), thread_id=str(message_id or ""))
        ingress_payload = ingress.get("payload") if isinstance(ingress, dict) else {}
        session_key = str((ingress_payload or {}).get("session_key") or f"telegram:{chat_id}").strip()
        ingress_request_id = str((ingress_payload or {}).get("ingress_id") or "").strip()
        _record_gateway_audit(
            "manager_request_received",
            session_key=session_key,
            channel="telegram",
            text=text.strip(),
            ingress_request_id=ingress_request_id,
            extra_details={"telegram_chat_id": str(chat_id), "reply_to_message_id": message_id or ""},
        )
        answer, team_meta = _run_team_route(text.strip(), session_key, self.runtime)
        delivery_id = ""
        if answer:
            duplicate = _recent_telegram_delivery_duplicate(str(chat_id), answer)
            if duplicate:
                delivery_id = str(duplicate.get("delivery_id") or "").strip()
                _record_gateway_audit(
                    "manager_response_deduped",
                    session_key=session_key,
                    channel="telegram",
                    text=answer,
                    ingress_request_id=ingress_request_id,
                    delivery_id=delivery_id,
                    extra_details={"telegram_chat_id": str(chat_id)},
                )
            else:
                delivery = _loom_channel_send("telegram", str(chat_id), answer)
                delivery_payload = delivery.get("payload") if isinstance(delivery, dict) else {}
                delivery_id = str((delivery_payload or {}).get("delivery_id") or "").strip()
            if duplicate:
                _loom_session_route(
                    session_key,
                    agent_id=TEAM_MANAGER_AGENT_ID,
                    org_id=LOOM_ORG_ID,
                    ingress_request_id=ingress_request_id,
                    delivery_id=delivery_id,
                    job_id=str((team_meta or {}).get("job_id") or "").strip(),
                )
                return
            try:
                result = self._send_direct(chat_id, answer, reply_to_message_id=message_id if isinstance(message_id, int) else None)
                _loom_channel_update(
                    delivery_id,
                    "delivered",
                    external_ref=str((result or {}).get("message_id") or str(chat_id)).strip(),
                    detail="",
                )
            except Exception as exc:
                _loom_channel_update(delivery_id, "failed", detail=f"{exc.__class__.__name__}: {exc}")
                _record_gateway_audit(
                    "manager_response_delivery_failed",
                    session_key=session_key,
                    channel="telegram",
                    text=answer,
                    outcome="failed",
                    ingress_request_id=ingress_request_id,
                    delivery_id=delivery_id,
                    extra_details={"error": f"{exc.__class__.__name__}: {exc}"},
                )
                raise
            else:
                _record_gateway_audit(
                    "manager_response_delivered",
                    session_key=session_key,
                    channel="telegram",
                    text=answer,
                    ingress_request_id=ingress_request_id,
                    delivery_id=delivery_id,
                    extra_details={"telegram_chat_id": str(chat_id)},
                )
        _loom_session_route(
            session_key,
            agent_id=TEAM_MANAGER_AGENT_ID,
            org_id=LOOM_ORG_ID,
            ingress_request_id=ingress_request_id,
            delivery_id=delivery_id,
            job_id=str((team_meta or {}).get("job_id") or "").strip(),
        )


class WebAPIAdapter(ChannelAdapter):
    def __init__(self, runtime: AgentRuntime, allowed_origin: str) -> None:
        super().__init__(runtime, "web")
        self.allowed_origin = allowed_origin.strip()
        self.notifications: queue.Queue[dict[str, str]] = queue.Queue()
        self.stream_subscribers: set[queue.Queue[dict[str, str]]] = set()
        self.stream_subscribers_lock = threading.Lock()
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def _publish_event(self, event: dict[str, str]) -> None:
        self.notifications.put(dict(event))
        with self.stream_subscribers_lock:
            subscribers = list(self.stream_subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(dict(event))
            except queue.Full:
                try:
                    subscriber.get_nowait()
                except queue.Empty:
                    pass
                try:
                    subscriber.put_nowait(dict(event))
                except queue.Full:
                    continue

    def _stream_events(self, handler: BaseHTTPRequestHandler) -> None:
        subscriber: queue.Queue[dict[str, str]] = queue.Queue(maxsize=64)
        with self.stream_subscribers_lock:
            self.stream_subscribers.add(subscriber)
        try:
            handler.send_response(200)
            handler._send_cors_headers()
            handler.send_header("Content-Type", "text/event-stream")
            handler.send_header("Cache-Control", "no-cache")
            handler.send_header("Connection", "keep-alive")
            handler.end_headers()
            handler.wfile.write(b": meridian_events_stream_v1\n\n")
            handler.wfile.flush()
            while True:
                try:
                    event = subscriber.get(timeout=15)
                    event_name = "event"
                except queue.Empty:
                    event = {"source": "gateway", "text": "heartbeat", "ts": str(int(time.time()))}
                    event_name = "heartbeat"
                payload = json.dumps(event, ensure_ascii=False)
                handler.wfile.write(f"event: {event_name}\ndata: {payload}\n\n".encode("utf-8"))
                handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        finally:
            with self.stream_subscribers_lock:
                self.stream_subscribers.discard(subscriber)

    def _make_handler(self):
        adapter = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "MeridianGatewayWeb/0.1"

            def _origin_allowed(self, request_path: str = "") -> bool:
                origin = str(self.headers.get("Origin") or "").strip()
                if origin == adapter.allowed_origin:
                    return True
                if not origin and self._public_read_allowed(request_path):
                    return True
                return False

            def _trust_ops_route(self, request_path: str) -> bool:
                return str(request_path or "").strip() in {
                    "/api/trust-ops/status",
                    "/api/trust-ops/queue",
                    "/api/trust-ops/queue/review",
                    "/api/trust-ops/queue/bulk-review",
                    "/api/trust-ops/evidence/review",
                }

            def _operator_authorized(self) -> bool:
                return _operator_token_valid(self.headers)

            def _public_read_allowed(self, request_path: str) -> bool:
                return str(request_path or "").strip() in {
                    "/api/events",
                    "/api/events/stream",
                    "/api/workflows/showcase",
                    "/api/status",
                    "/api/runtime-proof",
                    "/api/kernel-proof-bundle",
                    "/api/institution/template",
                    "/api/treasury",
                    "/api/payouts",
                }

            def _send_cors_headers(self) -> None:
                self.send_header("Access-Control-Allow-Origin", adapter.allowed_origin)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header(
                    "Access-Control-Allow-Headers",
                    "Authorization, Content-Type, X-Meridian-Operator-Token, X-Meridian-Session-Id",
                )
                self.send_header("Vary", "Origin")

            def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status_code)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _reconcile_stale_web_deliveries(self) -> None:
                cutoff_ms = int(time.time() * 1000) - 5000
                for record in _loom_channel_deliveries(limit=50):
                    if str(record.get("channel_id") or "").strip() != "web_api":
                        continue
                    if str(record.get("status") or "").strip() != "queued":
                        continue
                    submitted_at = int(record.get("submitted_at_unix_ms") or 0)
                    if submitted_at > cutoff_ms:
                        continue
                    delivery_id = str(record.get("delivery_id") or "").strip()
                    if not delivery_id:
                        continue
                    _loom_channel_update(
                        delivery_id,
                        "failed",
                        detail="client_disconnected_or_unacknowledged_http_response",
                    )

            def do_OPTIONS(self) -> None:  # noqa: N802
                request_path = urlparse(self.path).path
                if self._trust_ops_route(request_path):
                    self.send_response(204)
                    self._send_cors_headers()
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if not self._origin_allowed(request_path):
                    self._send_json(403, {"status": "error", "output": "origin_not_allowed"})
                    return
                self.send_response(204)
                self._send_cors_headers()
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                request_path = parsed.path
                proxied_path = request_path + (f"?{parsed.query}" if parsed.query else "")
                if self._trust_ops_route(request_path):
                    if not self._operator_authorized():
                        self._send_json(401, {"status": "error", "output": "operator_auth_required"})
                        return
                elif not self._origin_allowed(request_path) and not self._public_read_allowed(request_path):
                    self._send_json(403, {"status": "error", "output": "origin_not_allowed"})
                    return
                if request_path == "/api/events":
                    events = []
                    while True:
                        try:
                            events.append(adapter.notifications.get_nowait())
                        except queue.Empty:
                            break
                    self._send_json(200, {"status": "success", "events": events})
                    return
                if request_path == "/api/events/stream":
                    adapter._stream_events(self)
                    return
                if request_path == "/api/trust-ops/status":
                    self._send_json(200, {"status": "success", "trust_ops": _build_trust_assurance_summary()})
                    return
                if request_path == "/api/trust-ops/queue":
                    query = parse_qs(parsed.query or "")
                    status_filter = str((query.get("status") or ["actionable"])[0] or "actionable").strip().lower()
                    questionnaire_id = str((query.get("questionnaire_id") or [""])[0] or "").strip()
                    include_cleared = str((query.get("include_cleared") or ["false"])[0] or "").strip().lower() in {
                        "1",
                        "true",
                        "yes",
                        "on",
                    }
                    self._send_json(
                        200,
                        {
                            "status": "success",
                            "operator": _build_trust_ops_operator_snapshot(
                                questionnaire_id=questionnaire_id,
                                status_filter=status_filter,
                                include_cleared=include_cleared,
                            ),
                        },
                    )
                    return
                if request_path == "/api/workflows/showcase":
                    self._send_json(
                        200,
                        {
                            "status": "success",
                            "showcase": _normalize_status_wording(_workflow_showcase_snapshot_cached()),
                        },
                    )
                    return
                if request_path == "/api/status":
                    proxied = _workspace_status_snapshot_cached()
                    self._send_json(int(proxied.get("status_code") or 200), dict(proxied.get("payload") or {}))
                    return
                if request_path == "/api/institution/template":
                    proxied = _workspace_api_get_json(proxied_path)
                    payload = _normalize_status_wording(dict(proxied.get("payload") or {}))
                    boundary = payload.get("boundary")
                    if isinstance(boundary, dict):
                        boundary["service_scope"] = "host_bound_service_only"
                        boundary["note"] = (
                            "Template is production-ready for host-bound open-source deployments; "
                            "multi-institution self-serve remains intentionally bounded."
                        )
                    self._send_json(int(proxied.get("status_code") or 200), payload)
                    return
                if request_path == "/api/kernel-proof-bundle":
                    proxied = _workspace_api_get_json(proxied_path)
                    payload = _normalize_status_wording(dict(proxied.get("payload") or {}))
                    self._send_json(int(proxied.get("status_code") or 200), payload)
                    return
                if request_path == "/api/institution/license/catalog":
                    self._send_json(410, {
                        "status": "deprecated",
                        "reason": "open_source_mode",
                        "message": "This legacy monetization route has been deprecated. Meridian now runs in open-source setup mode.",
                        "next_steps": [
                            "Run one-command setup: curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash",
                            "Visit https://github.com/mapleleaflatte03/meridian for source and documentation",
                            "The institution template remains available at /api/institution/template",
                        ],
                    })
                    return
                if request_path == "/api/pilot/intake":
                    self._send_json(410, {
                        "status": "deprecated",
                        "reason": "open_source_mode",
                        "message": "Public pilot intake has been deprecated. Use /pilot for open-source setup.",
                        "next_steps": [
                            "Open /pilot and follow the local bootstrap path",
                            "Run one-command setup: curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash",
                            "Use the monorepo: https://github.com/mapleleaflatte03/meridian",
                        ],
                    })
                    return
                if request_path == "/api/subscriptions/checkout-capture":
                    self._send_json(410, {
                        "status": "deprecated",
                        "reason": "open_source_mode",
                        "message": "This legacy payment-capture route has been deprecated. Meridian now runs in open-source setup mode.",
                        "next_steps": [
                            "Run local setup from /pilot",
                            "Run one-command setup: curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash",
                            "Use /api/workflows/showcase and /api/proofs to verify runtime behavior",
                            "Contribute via https://github.com/mapleleaflatte03/meridian/issues",
                        ],
                    })
                    return
                if request_path in {
                    "/api/context",
                    "/api/institution",
                    "/api/institution/template",
                    "/api/agents",
                    "/api/authority",
                    "/api/runtime-proof",
                    "/api/kernel-proof-bundle",
                    "/api/warrants",
                    "/api/commitments",
                    "/api/cases",
                    "/api/court",
                    "/api/admission",
                    "/api/federation",
                    "/api/federation/peers",
                    "/api/federation/inbox",
                    "/api/federation/execution-jobs",
                    "/api/federation/manifest",
                    "/api/federation/witness/archive",
                    "/api/alerts",
                    "/api/session/validate",
                    "/api/subscriptions",
                    "/api/subscriptions/delivery-targets",
                    "/api/subscriptions/loom-delivery-jobs",
                    "/api/subscriptions/loom-delivery-runs",
                    "/api/subscriptions/preview-queue",
                    "/api/pilot/intake",
                    "/api/pilot/intake/operator",
                    "/api/payouts",
                    "/api/accounting",
                    "/api/treasury",
                    "/api/treasury/accounts",
                    "/api/treasury/funding-sources",
                    "/api/treasury/settlement-adapters",
                }:
                    proxied = _workspace_api_get_json(proxied_path)
                    self._send_json(int(proxied.get("status_code") or 200), dict(proxied.get("payload") or {}))
                    return
                self._send_json(404, {"status": "error", "output": "not_found"})

            def do_POST(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                request_path = parsed.path
                if self._trust_ops_route(request_path):
                    if not self._operator_authorized():
                        self._send_json(401, {"status": "error", "output": "operator_auth_required"})
                        return
                elif not self._origin_allowed(request_path):
                    self._send_json(403, {"status": "error", "output": "origin_not_allowed"})
                    return
                self._reconcile_stale_web_deliveries()
                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._send_json(400, {"status": "error", "output": "invalid_content_length"})
                    return
                raw_body = self.rfile.read(content_length)
                try:
                    payload = json.loads(raw_body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    self._send_json(400, {"status": "error", "output": f"invalid_json: {exc}"})
                    return
                if not isinstance(payload, dict):
                    self._send_json(400, {"status": "error", "output": "json_object_required"})
                    return
                if request_path == "/api/trust-ops/queue/review":
                    queue_id = str(payload.get("queue_id") or "").strip()
                    decision = str(payload.get("decision") or "").strip().lower()
                    reviewed = _review_trust_approval_queue(
                        queue_id,
                        decision,
                        note=str(payload.get("note") or "").strip(),
                        actor=str(payload.get("actor") or "").strip(),
                    )
                    if not reviewed:
                        self._send_json(400, {"status": "error", "output": "invalid_queue_review"})
                        return
                    self._send_json(200, {"status": "success", "review": reviewed, "trust_ops": _build_trust_assurance_summary()})
                    return
                if request_path == "/api/trust-ops/queue/bulk-review":
                    queue_ids = payload.get("queue_ids") or []
                    if not isinstance(queue_ids, list):
                        self._send_json(400, {"status": "error", "output": "queue_ids_list_required"})
                        return
                    decision = str(payload.get("decision") or "").strip().lower()
                    reviewed = _review_trust_approval_queue_bulk(
                        [str(item or "").strip() for item in queue_ids],
                        decision,
                        note=str(payload.get("note") or "").strip(),
                        actor=str(payload.get("actor") or "").strip(),
                    )
                    if not reviewed:
                        self._send_json(400, {"status": "error", "output": "invalid_bulk_queue_review"})
                        return
                    self._send_json(200, {"status": "success", "bulk_review": reviewed})
                    return
                if request_path == "/api/trust-ops/evidence/review":
                    evidence_key = str(payload.get("evidence_key") or "").strip()
                    decision = str(payload.get("decision") or "").strip().lower()
                    reviewed = _review_trust_evidence_entry(
                        evidence_key,
                        decision,
                        note=str(payload.get("note") or "").strip(),
                        actor=str(payload.get("actor") or "").strip(),
                    )
                    if not reviewed:
                        self._send_json(400, {"status": "error", "output": "invalid_evidence_review"})
                        return
                    self._send_json(
                        200,
                        {
                            "status": "success",
                            "evidence": {
                                "key": str(reviewed.get("key") or "").strip(),
                                "approval_status": _trust_evidence_effective_status(reviewed),
                                "reviewed_at": str(reviewed.get("reviewed_at") or "").strip(),
                            },
                            "trust_ops": _build_trust_assurance_summary(),
                        },
                    )
                    return
                if request_path == "/api/institution/license/checkout-capture":
                    self._send_json(410, {
                        "status": "deprecated",
                        "reason": "open_source_mode",
                        "message": "This legacy payment-capture route has been deprecated. Meridian now runs in open-source setup mode.",
                        "next_steps": [
                            "Run one-command setup: curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash",
                            "Visit https://github.com/mapleleaflatte03/meridian for source and documentation",
                            "The institution template remains available at /api/institution/template",
                        ],
                    })
                    return
                if request_path == "/api/pilot/intake":
                    self._send_json(410, {
                        "status": "deprecated",
                        "reason": "open_source_mode",
                        "message": "Public pilot intake has been deprecated. Use /pilot for open-source setup.",
                        "next_steps": [
                            "Open /pilot and follow the local bootstrap path",
                            "Run one-command setup: curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash",
                            "Use the monorepo: https://github.com/mapleleaflatte03/meridian",
                        ],
                    })
                    return
                if request_path == "/api/subscriptions/checkout-capture":
                    self._send_json(410, {
                        "status": "deprecated",
                        "reason": "open_source_mode",
                        "message": "This legacy payment-capture route has been deprecated. Meridian now runs in open-source setup mode.",
                        "next_steps": [
                            "Run local setup from /pilot",
                            "Run one-command setup: curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash",
                            "Use /api/workflows/showcase and /api/proofs to verify runtime behavior",
                            "Contribute via https://github.com/mapleleaflatte03/meridian/issues",
                        ],
                    })
                    return
                if request_path in {
                    "/api/authority/kill-switch",
                    "/api/authority/approve",
                    "/api/authority/request",
                    "/api/authority/delegate",
                    "/api/authority/revoke",
                    "/api/court/file",
                    "/api/court/resolve",
                    "/api/court/appeal",
                    "/api/court/decide-appeal",
                    "/api/court/auto-review",
                    "/api/court/remediate",
                    "/api/warrants/issue",
                    "/api/warrants/approve",
                    "/api/warrants/stay",
                    "/api/warrants/revoke",
                    "/api/commitments/propose",
                    "/api/commitments/accept",
                    "/api/commitments/reject",
                    "/api/commitments/breach",
                    "/api/commitments/settle",
                    "/api/cases/open",
                    "/api/cases/stay",
                    "/api/cases/resolve",
                    "/api/federation/execution-jobs/execute",
                    "/api/federation/peers/upsert",
                    "/api/federation/peers/refresh",
                    "/api/federation/peers/suspend",
                    "/api/federation/peers/revoke",
                    "/api/federation/witness/archive",
                    "/api/federation/send",
                    "/api/institution/charter",
                    "/api/institution/lifecycle",
                    "/api/session/issue",
                    "/api/session/revoke",
                    "/api/pilot/intake",
                    "/api/pilot/intake/operator/review",
                    "/api/payouts/propose",
                    "/api/payouts/submit",
                    "/api/payouts/review",
                    "/api/payouts/approve",
                    "/api/payouts/open-dispute-window",
                    "/api/payouts/reject",
                    "/api/payouts/cancel",
                    "/api/payouts/execute",
                    "/api/admission/admit",
                    "/api/admission/suspend",
                    "/api/admission/revoke",
                    "/api/alerts/dispatch",
                    "/api/subscriptions/add",
                    "/api/subscriptions/draft-from-preview",
                    "/api/subscriptions/checkout-capture",
                    "/api/subscriptions/activate-from-preview",
                    "/api/subscriptions/loom-delivery-jobs/run",
                    "/api/subscriptions/convert",
                    "/api/subscriptions/verify-payment",
                    "/api/subscriptions/remove",
                    "/api/subscriptions/set-email",
                    "/api/subscriptions/record-delivery",
                    "/api/accounting/expense",
                    "/api/accounting/reimburse",
                    "/api/accounting/draw",
                    "/api/treasury/contribute",
                    "/api/treasury/reserve-floor",
                    "/api/treasury/settlement-adapters/preflight",
                }:
                    proxied = _workspace_api_post_json(request_path, payload if isinstance(payload, dict) else {})
                    self._send_json(int(proxied.get("status_code") or 200), dict(proxied.get("payload") or {}))
                    return
                if request_path != "/api/run":
                    self._send_json(404, {"status": "error", "output": "not_found"})
                    return
                goal = payload.get("goal")
                if not isinstance(goal, str) or not goal.strip():
                    self._send_json(400, {"status": "error", "output": "goal_required"})
                    return
                web_session = _resolve_web_request_session(payload, self.headers, goal.strip())
                session_id = str(web_session.get("session_id") or "").strip()
                ingress = _loom_channel_ingest("web_api", LOOM_ORG_ID, goal.strip(), thread_id=session_id)
                ingress_payload = ingress.get("payload") if isinstance(ingress, dict) else {}
                session_key = _effective_web_session_key(session_id, ingress_payload)
                ingress_request_id = str((ingress_payload or {}).get("ingress_id") or "").strip()
                _record_gateway_audit(
                    "manager_request_received",
                    session_key=session_key,
                    channel="web_api",
                    text=goal.strip(),
                    ingress_request_id=ingress_request_id,
                )
                answer, team_meta = _run_team_route(goal.strip(), session_key, adapter.runtime)
                delivery_id = ""
                if answer:
                    delivery = _loom_channel_send("web_api", LOOM_ORG_ID, answer)
                    delivery_payload = delivery.get("payload") if isinstance(delivery, dict) else {}
                    delivery_id = str((delivery_payload or {}).get("delivery_id") or "").strip()
                _loom_session_route(
                    session_key,
                    agent_id=TEAM_MANAGER_AGENT_ID,
                    org_id=LOOM_ORG_ID,
                    ingress_request_id=ingress_request_id,
                    delivery_id=delivery_id,
                    job_id=str((team_meta or {}).get("job_id") or "").strip(),
                )
                try:
                    self._send_json(200, {
                        "status": "success",
                        "output": answer,
                        "session_id": session_id,
                        "session_key": session_key,
                    })
                except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError) as exc:
                    if delivery_id:
                        _loom_channel_update(
                            delivery_id,
                            "failed",
                            detail=f"{exc.__class__.__name__}: {exc}",
                        )
                    _record_gateway_audit(
                        "manager_response_delivery_failed",
                        session_key=session_key,
                        channel="web_api",
                        text=answer,
                        outcome="failed",
                        ingress_request_id=ingress_request_id,
                        delivery_id=delivery_id,
                        extra_details={"error": f"{exc.__class__.__name__}: {exc}"},
                    )
                    return
                if delivery_id:
                    _loom_channel_update(delivery_id, "delivered", external_ref="http_response", detail="")
                _record_gateway_audit(
                    "manager_response_delivered",
                    session_key=session_key,
                    channel="web_api",
                    text=answer,
                    ingress_request_id=ingress_request_id,
                    delivery_id=delivery_id,
                    extra_details={"response_channel": "http_response"},
                )

            def log_message(self, format: str, *args: object) -> None:  # noqa: A003
                return

        return Handler

    def start(self) -> None:
        if not self.allowed_origin:
            _log("web adapter disabled: allowed_origin missing", color=ANSI_YELLOW)
            return
        handler = self._make_handler()
        self.server = ThreadingHTTPServer((HOST, PORT), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="web-api-adapter", daemon=True)
        self.thread.start()
        self._active = True
        _log(f"web adapter listening on http://{HOST}:{PORT} origin={self.allowed_origin}", color=ANSI_GREEN)

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()

    def send_message(self, text: str, *, source: str = "runtime") -> None:
        session_key = "web_api:notifications"
        delivery = _loom_channel_send("web_api", LOOM_ORG_ID, text)
        delivery_payload = delivery.get("payload") if isinstance(delivery, dict) else {}
        delivery_id = str((delivery_payload or {}).get("delivery_id") or "").strip()
        self._publish_event({"source": source, "text": text, "ts": str(int(time.time()))})
        if delivery_id:
            _loom_channel_update(delivery_id, "delivered", external_ref="notification_queue", detail="")
            _loom_session_route(
                session_key,
                agent_id=TEAM_MANAGER_AGENT_ID,
                org_id=LOOM_ORG_ID,
                delivery_id=delivery_id,
            )


class HeartbeatEngine(threading.Thread):
    def __init__(self, runtime: AgentRuntime, adapters: list[ChannelAdapter], interval_seconds: int = HEARTBEAT_INTERVAL_SECONDS) -> None:
        super().__init__(name="heartbeat-engine", daemon=True)
        self.runtime = runtime
        self.adapters = adapters
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()

    def run(self) -> None:
        while not self.stop_event.wait(self.interval_seconds):
            try:
                answer = self.runtime.run_goal(
                    "Silent heartbeat check. Decide whether proactive action is needed right now.",
                    heartbeat=True,
                )
                if answer:
                    for adapter in self.adapters:
                        if adapter.is_active():
                            adapter.send_message(answer, source="heartbeat")
            except Exception as exc:
                _log(f"heartbeat warning: {exc}", color=ANSI_YELLOW)

    def stop(self) -> None:
        self.stop_event.set()


def main() -> int:
    config = _load_runtime_config_or_exit()
    skills = TEAM_SKILLS
    loaded_skills = skills.items or skills.load()
    runtime = AgentRuntime(skills)
    telegram_adapter = TelegramAdapter(runtime, str(config.get("telegram_bot_token") or ""))
    web_adapter = WebAPIAdapter(runtime, str(config.get("allowed_origin") or ""))
    adapters: list[ChannelAdapter] = [telegram_adapter, web_adapter]
    heartbeat = HeartbeatEngine(runtime, adapters)

    _log("Meridian Gateway starting", color=ANSI_GREEN)
    _log(f"SOUL loaded: {SOUL_PATH}")
    _log(f"MEMORY loaded: {MEMORY_PATH}")
    _log(f"skills loaded: {len(loaded_skills)} definitions from {SKILLS_DIR}")

    web_adapter.start()
    telegram_adapter.start()
    heartbeat.start()
    _log(f"heartbeat started: interval={HEARTBEAT_INTERVAL_SECONDS}s", color=ANSI_GREEN)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _log("Meridian Gateway shutting down", color=ANSI_YELLOW)
    finally:
        heartbeat.stop()
        for adapter in adapters:
            adapter.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
