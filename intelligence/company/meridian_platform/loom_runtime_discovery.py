"""
Loom runtime discovery — shared module for Intelligence layer.

Centralizes binary/root discovery, CLI invocation, and runtime-info parsing
so that the gateway, workspace, readiness, and other Intelligence modules
do not each re-implement Loom discovery logic.

All generic runtime truth lives in Loom. This module is a thin delegation
layer that calls `loom runtime-info` and caches the result for the process
lifetime.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

_DEFAULT_LOOM_BINS = [
    "/home/ubuntu/.local/share/meridian-loom/current/bin/loom",
    "/root/.local/share/meridian-loom/current/bin/loom",
]

_DEFAULT_LOOM_ROOTS = [
    "/home/ubuntu/.local/share/meridian-loom/runtime/default",
    "/root/.local/share/meridian-loom/runtime/default",
]

_CACHED_INFO: Optional[dict] = None


def _fallback_runtime_info(runtime_env: Optional[dict] = None, error: str = '') -> dict[str, Any]:
    env = runtime_env or os.environ
    return {
        'version': 'unknown',
        'binary_path': preferred_loom_bin(env),
        'runtime_root': preferred_loom_root(env),
        'mode': 'unknown',
        'org_id': env.get('MERIDIAN_LOOM_ORG_ID', 'unknown'),
        '_fallback': True,
        '_error': error,
    }


def preferred_loom_bin(runtime_env: Optional[dict] = None) -> str:
    """Discover the Loom binary path."""
    env = runtime_env or os.environ
    explicit = (env.get("MERIDIAN_LOOM_BIN") or "").strip()
    if explicit and os.path.exists(explicit):
        return explicit
    for candidate in _DEFAULT_LOOM_BINS:
        if os.path.exists(candidate):
            return candidate
    which = shutil.which("loom")
    if which:
        return which
    return _DEFAULT_LOOM_BINS[0]


def preferred_loom_root(runtime_env: Optional[dict] = None) -> str:
    """Discover the Loom runtime root path."""
    env = runtime_env or os.environ
    explicit = (env.get("MERIDIAN_LOOM_ROOT") or "").strip()
    if explicit and os.path.exists(explicit):
        return explicit
    for candidate in _DEFAULT_LOOM_ROOTS:
        if os.path.exists(candidate):
            return candidate
    return _DEFAULT_LOOM_ROOTS[0]


def loom_cli_prefix(runtime_env: Optional[dict] = None) -> list[str]:
    """Return the base command prefix for invoking Loom CLI."""
    return [preferred_loom_bin(runtime_env)]


def loom_cmd(subcmd: list[str], extra: Optional[list[str]] = None,
             runtime_env: Optional[dict] = None) -> list[str]:
    """Build a full loom command with --root and --format json."""
    root = preferred_loom_root(runtime_env)
    return loom_cli_prefix(runtime_env) + subcmd + ["--root", root] + (extra or [])


def run_loom_json(subcmd: list[str], extra: Optional[list[str]] = None,
                  timeout: int = 30, runtime_env: Optional[dict] = None) -> dict[str, Any]:
    """Run a Loom CLI command expecting JSON output."""
    cmd = loom_cmd(subcmd, (extra or []) + ["--format", "json"], runtime_env)
    try:
        completed = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError:
        return {"ok": False, "error": f"loom binary not found: {cmd[0]}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {timeout}s"}

    if completed.returncode != 0:
        return {
            "ok": False,
            "error": (completed.stderr or completed.stdout or "").strip(),
            "returncode": completed.returncode,
        }

    stdout = (completed.stdout or "").strip()
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        payload = {"raw_output": stdout}

    return {"ok": True, "payload": payload}


def runtime_info(force_refresh: bool = False,
                 runtime_env: Optional[dict] = None) -> dict[str, Any]:
    """Get Loom runtime info (cached for process lifetime)."""
    global _CACHED_INFO
    if _CACHED_INFO is not None and not force_refresh:
        return _CACHED_INFO

    resp = run_loom_json(["runtime-info"], runtime_env=runtime_env)
    if resp.get("ok"):
        _CACHED_INFO = resp["payload"]
        return _CACHED_INFO

    _CACHED_INFO = _fallback_runtime_info(runtime_env, resp.get('error', ''))
    return _CACHED_INFO


def runtime_value(
    key: str,
    default: str = '',
    *,
    force_refresh: bool = False,
    runtime_env: Optional[dict] = None,
) -> str:
    """Return a single runtime-info value with a safe fallback."""
    payload = runtime_info(force_refresh=force_refresh, runtime_env=runtime_env)
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def clear_cache() -> None:
    """Clear the cached runtime info."""
    global _CACHED_INFO
    _CACHED_INFO = None
