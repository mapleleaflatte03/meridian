#!/usr/bin/env python3
"""Canonical Meridian golden-path orchestrator.

This script is intentionally truthful:
- it uses the real local kernel bootstrap and warrant CLI
- it reads the real kernel agent registry state
- it executes the real local Loom browser capability against httpbin
- it settles through the live Meridian treasury adapter supported by this host
- it never fabricates tx hashes or delivery content
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import ops_meridian_delivery_engine as engine


HOME_DIR = str(Path.home())
MONOREPO_ROOT = str(os.environ.get("MERIDIAN_ROOT") or "").strip()
WORKSPACE = str(
    os.environ.get("MERIDIAN_WORKSPACE_ROOT")
    or (os.path.join(MONOREPO_ROOT, "intelligence") if MONOREPO_ROOT else "")
    or os.path.dirname(os.path.abspath(__file__))
).strip()
CANONICAL_KERNEL_ROOT = str(
    os.environ.get("MERIDIAN_KERNEL_ROOT")
    or (os.path.join(MONOREPO_ROOT, "kernel") if MONOREPO_ROOT else "")
    or "/opt/meridian-kernel"
).strip()
LEGACY_KERNEL_ROOT = "/tmp/meridian-kernel"
MERIDIAN_HOME = str(os.environ.get("MERIDIAN_HOME") or os.path.join(HOME_DIR, ".meridian")).strip()


def _resolve_kernel_root() -> str:
    override = str(os.environ.get("MERIDIAN_KERNEL_ROOT") or "").strip()
    candidates = [override, CANONICAL_KERNEL_ROOT, LEGACY_KERNEL_ROOT]
    for candidate in candidates:
        if candidate and os.path.isdir(os.path.join(candidate, "kernel")):
            return candidate
    return CANONICAL_KERNEL_ROOT


KERNEL_ROOT = _resolve_kernel_root()
KERNEL_DIR = os.path.join(KERNEL_ROOT, "kernel")
QUICKSTART_PATH = os.path.join(KERNEL_ROOT, "quickstart.py")
BOOTSTRAP_PATH = os.path.join(KERNEL_DIR, "bootstrap.py")
WARRANTS_PATH = os.path.join(KERNEL_DIR, "warrants.py")
AGENT_REGISTRY_FILE = os.path.join(KERNEL_DIR, "agent_registry.json")
ORGANIZATIONS_FILE = os.path.join(KERNEL_DIR, "organizations.json")
TARGET_URL = "https://httpbin.org/html"
WORKSPACE_CREDENTIALS_PATH = str(
    os.environ.get("MERIDIAN_WORKSPACE_CREDENTIALS_PATH")
    or os.path.join(MERIDIAN_HOME, ".workspace_credentials")
).strip()
WORKSPACE_GATEWAY_URL = str(os.environ.get("MERIDIAN_GATEWAY_URL") or "http://127.0.0.1:8266").strip()
STEP_DELAY_SECONDS = 0.2

RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"


def _step(title: str) -> None:
    print(f"{BOLD}{CYAN}[{title}]{RESET}")
    time.sleep(STEP_DELAY_SECONDS)


def _line(label: str, value: str, *, color: str = GREEN) -> None:
    print(f"{color}{label}{RESET} {value}")
    time.sleep(0.05)


def _multiline(label: str, text: str, *, color: str = YELLOW) -> None:
    print(f"{color}{label}{RESET}")
    if not text.strip():
        print("  <none>")
        return
    for line in text.strip().splitlines():
        print(f"  {line}")


def _run_kernel_python(script_path: str, *args: str):
    script_dir = os.path.dirname(script_path)
    if script_dir == KERNEL_DIR:
        cwd = KERNEL_DIR
        pythonpath = KERNEL_DIR
    else:
        cwd = KERNEL_ROOT
        pythonpath = os.pathsep.join([KERNEL_ROOT, KERNEL_DIR])
    completed = subprocess.run(
        ["python3", script_path, *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": pythonpath},
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or f"{os.path.basename(script_path)} failed").strip()
        raise RuntimeError(detail)
    return completed.stdout.strip()


def _load_json_file(path: str):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _load_workspace_credentials():
    payload = {}
    if not os.path.exists(WORKSPACE_CREDENTIALS_PATH):
        return payload
    with open(WORKSPACE_CREDENTIALS_PATH, encoding="utf-8") as handle:
        for raw_line in handle:
            line = str(raw_line or "").strip()
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            payload[key.strip()] = value.strip()
    return payload


def _workspace_api_post(path: str, payload: dict) -> dict:
    credentials = _load_workspace_credentials()
    user = str(credentials.get("user") or "").strip()
    password = str(credentials.get("pass") or "").strip()
    if not user or not password:
        raise RuntimeError("Workspace credentials are missing; cannot call Meridian mutation surface")
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    body = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        f"{WORKSPACE_GATEWAY_URL}{path}",
        data=body,
        headers={
            "Authorization": f"Basic {token}",
            "Origin": "https://app.welliam.codes",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "MeridianGoldenPath/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(detail or exc.reason) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"workspace_unreachable: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid Meridian API response for {path}: {exc}") from exc
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(str(data.get("error")))
    return data


def _kernel_meridian_state_ready() -> bool:
    organizations = dict(_load_json_file(ORGANIZATIONS_FILE).get("organizations") or {})
    registry = dict(_load_json_file(AGENT_REGISTRY_FILE).get("agents") or {})
    org = organizations.get(engine.DIRECT_LOOM_ORG_ID)
    if not org or org.get("slug") != "meridian":
        return False
    bound_agents = [
        agent for agent in registry.values()
        if agent.get("org_id") == engine.DIRECT_LOOM_ORG_ID
        and dict(agent.get("runtime_binding") or {}).get("runtime_id") == "loom_native"
    ]
    return len(bound_agents) >= 7


def _bootstrap_governance():
    quickstart_output = ""
    if _kernel_meridian_state_ready():
        bootstrap_output = (
            "Existing Meridian kernel state detected; skipped demo bootstrap and reused canonical live institution state."
        )
    else:
        try:
            bootstrap_output = _run_kernel_python(BOOTSTRAP_PATH)
        except RuntimeError as exc:
            detail = str(exc)
            if "is not initialized" not in detail or not os.path.exists(QUICKSTART_PATH):
                raise
            quickstart_output = _run_kernel_python(QUICKSTART_PATH, "--init-only")
            bootstrap_output = _run_kernel_python(BOOTSTRAP_PATH)
    ledger_path = os.path.join(KERNEL_ROOT, "economy", "ledger.json")
    ledger = {}
    if os.path.exists(ledger_path):
        with open(ledger_path) as handle:
            ledger = json.load(handle)
    treasury = dict(ledger.get("treasury") or {})
    return {
        "bootstrap_output": "\n".join(
            part for part in (quickstart_output.strip(), bootstrap_output.strip()) if part
        ),
        "ledger_path": ledger_path,
        "treasury_cash_usd": treasury.get("cash_usd"),
        "agent_count": len(dict(ledger.get("agents") or {})),
    }


def _resolve_agent():
    registry = _load_json_file(AGENT_REGISTRY_FILE)
    agents = dict(registry.get("agents") or {})
    direct_id = str(engine.DIRECT_LOOM_AGENT_ID or "").strip()
    direct_key = direct_id if direct_id.startswith("agent_") else f"agent_{direct_id}"
    desired_handle = direct_id.removeprefix("agent_")
    agent = agents.get(direct_key)
    if agent is not None and agent.get("org_id") != engine.DIRECT_LOOM_ORG_ID:
        agent = None
    if agent is None:
        for candidate in agents.values():
            if (
                candidate.get("org_id") == engine.DIRECT_LOOM_ORG_ID
                and candidate.get("economy_key") == desired_handle
            ):
                agent = candidate
                break
    if agent is None:
        raise RuntimeError(
            f"Governed agent {engine.DIRECT_LOOM_AGENT_ID!r} was not found in org {engine.DIRECT_LOOM_ORG_ID!r}"
        )
    return agent


def _issue_warrant(agent):
    response = _workspace_api_post(
        "/api/warrants/issue",
        {
            "action_class": "federated_execution",
            "boundary_name": engine.DIRECT_LOOM_CAPABILITY,
            "risk_class": "moderate",
            "auto_issue": True,
            "note": "Meridian golden path warrant issuance",
            "request_payload": {
                "requested_agent_id": agent["id"],
                "requested_agent_name": agent.get("name", ""),
                "requested_agent_role": agent.get("role", ""),
                "requested_boundary": engine.DIRECT_LOOM_CAPABILITY,
            },
        },
    )
    warrant = dict(response.get("warrant") or {})
    if not warrant:
        raise RuntimeError("Meridian workspace did not return a warrant payload")
    return warrant


def _brief_preview(result):
    capture_result = dict((result or {}).get("capture_result") or {})
    artifact = dict(capture_result.get("delivery_artifact") or {})
    brief_text = str(artifact.get("brief_text") or "").strip()
    if not brief_text:
        return "<none>"
    lines = [line.rstrip() for line in brief_text.splitlines() if line.strip()]
    return "\n".join(lines[:6])


def main() -> int:
    print(f"{BOLD}{MAGENTA}Meridian Golden Path{RESET}")
    print("Governed digital labor exercised against real local runtime boundaries.")
    time.sleep(STEP_DELAY_SECONDS)

    _step("STEP 1: Governance Bootstrap")
    boot = _bootstrap_governance()
    _line("kernel_ledger:", boot["ledger_path"])
    _line("bootstrap_agent_count:", str(boot["agent_count"]))
    _line("treasury_cash_usd:", str(boot["treasury_cash_usd"]))
    _multiline("bootstrap_output:", boot["bootstrap_output"])

    _step("STEP 2: Agent Admission")
    agent = _resolve_agent()
    _line("agent_id:", agent.get("id", ""))
    _line("agent_name:", agent.get("name", ""))
    _line("agent_role:", agent.get("role", ""))
    _line("agent_org_id:", agent.get("org_id", ""))
    runtime_binding = dict(agent.get("runtime_binding") or {})
    _line("runtime_id:", str(runtime_binding.get("runtime_id") or ""))
    _line("boundary_name:", str(runtime_binding.get("boundary_name") or ""))

    _step("STEP 3: Warrant Issuance")
    warrant = _issue_warrant(agent)
    _line("warrant_id:", warrant["warrant_id"])
    _line("court_review_state:", warrant.get("court_review_state", ""))
    _line("execution_state:", warrant.get("execution_state", ""))
    _line("expires_at:", warrant.get("expires_at", ""))

    _step("STEP 4: Loom Execution")
    result = engine.run_engine(
        target_url=TARGET_URL,
        disable_outbound_dispatch=True,
        keep_state=False,
        timeout=20,
        warrant_id=warrant["warrant_id"],
    )
    runtime = dict(result.get("runtime") or {})
    capture_result = dict(result.get("capture_result") or {})
    artifact = dict(capture_result.get("delivery_artifact") or {})
    execution = dict(capture_result.get("delivery_execution") or {})
    _line("loom_bin:", str(runtime.get("loom_bin") or ""))
    _line("capability_name:", str(runtime.get("capability_name") or ""))
    _line("preflight_ok:", str(bool(runtime.get("preflight", {}).get("ok"))).lower())
    _line("execution_ok:", str(bool(execution.get("ok"))).lower())
    _line("brief_result_path:", str(artifact.get("result_path") or "<none>"))
    _multiline("brief_preview:", _brief_preview(result))

    _step("STEP 5: Treasury Settlement")
    settlement = engine.delivery_settlement_artifact(result)
    sender_address = engine._settlement_sender_address(result)
    settlement_error = engine._settlement_error(result)
    finalized_warrant = dict(result.get("warrant") or {})
    artifact_type = str(settlement.get("artifact_type") or "")
    artifact_value = str(settlement.get("artifact") or "")
    _line("settlement_adapter:", str(settlement.get("settlement_adapter") or "<none>"))
    if settlement.get("proof_type"):
        _line("settlement_proof_type:", str(settlement.get("proof_type") or "<none>"))
    if settlement.get("verification_state"):
        _line("verification_state:", str(settlement.get("verification_state") or "<none>"))
    if settlement.get("finality_state"):
        _line("finality_state:", str(settlement.get("finality_state") or "<none>"))
    if sender_address:
        _line("sender_address:", sender_address)
    if artifact_value:
        _line(f"settlement_{artifact_type}:", artifact_value)
    else:
        _line("settlement_reference:", "<none>", color=RED)
    if settlement_error:
        _line("settlement_error:", settlement_error, color=RED)
    else:
        _line("settlement_error:", "<none>")
    if finalized_warrant:
        _line("warrant_execution_state:", str(finalized_warrant.get("execution_state") or ""))
        _line("warrant_executed_at:", str(finalized_warrant.get("executed_at") or ""))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
