#!/usr/bin/env python3
"""Autonomous researcher orchestration for the live Meridian workspace.

This script stays truthful:
- governance bootstrap and warrant issuance use the real kernel CLI/helpers
- target acquisition executes the real Loom browser capability
- cognitive analysis only claims Loom LLM output if the runtime actually returns it
- persistent memory only claims Loom FS write if the runtime proves it wrote the file
- audit output is built from the real Loom parity artifacts
- settlement reuses the real kernel-backed broadcast attempt and surfaces the real RPC boundary
"""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from typing import Any

import ops_meridian_delivery_engine as engine
import ops_meridian_golden_path as golden


MONOREPO_ROOT = str(os.environ.get("MERIDIAN_ROOT") or "").strip()
WORKSPACE = str(
    os.environ.get("MERIDIAN_WORKSPACE_ROOT")
    or (os.path.join(MONOREPO_ROOT, "intelligence") if MONOREPO_ROOT else "")
    or os.path.dirname(os.path.abspath(__file__))
).strip()
DEFAULT_URL = "https://news.ycombinator.com/"
KERNEL_ROOT_BASE = str(
    os.environ.get("MERIDIAN_KERNEL_ROOT")
    or (os.path.join(MONOREPO_ROOT, "kernel") if MONOREPO_ROOT else "")
    or "/opt/meridian-kernel"
).strip()
LEGACY_ALIAS_PATH = os.path.join(KERNEL_ROOT_BASE, "kernel", "adapters", "legacy_v1_compatible.py")
LEGACY_ADAPTER_PATHS = [
    os.path.join(
        KERNEL_ROOT_BASE,
        "kernel",
        "adapters",
        "legacy_v1_compatible.py",
    ),
    "/opt/meridian-kernel/kernel/adapters/legacy_v1_compatible.py",
    "/tmp/meridian-kernel/kernel/adapters/legacy_v1_compatible.py",
]
LOOM_WORKSPACE_ROOT = os.path.join(engine.DIRECT_LOOM_ROOT, "workspace")
COMPETITOR_BRIEF_PATH = os.path.join(LOOM_WORKSPACE_ROOT, "competitor_brief.md")
LLM_CAPABILITY = "loom.llm.inference.v1"
FS_WRITE_CAPABILITY = "loom.fs.write.v1"
LLM_TIMEOUT_SECONDS = 30

RESET = golden.RESET
BOLD = golden.BOLD
CYAN = golden.CYAN
GREEN = golden.GREEN
YELLOW = golden.YELLOW
MAGENTA = golden.MAGENTA
RED = golden.RED


def _step(title: str) -> None:
    golden._step(title)


def _line(label: str, value: str, *, color: str = GREEN) -> None:
    golden._line(label, value, color=color)


def _multiline(label: str, text: str, *, color: str = YELLOW) -> None:
    golden._multiline(label, text, color=color)


def _target_url(cli_value: str = "") -> str:
    raw = str(cli_value or "").strip()
    if raw:
        return raw
    return (
        os.environ.get("MERIDIAN_RESEARCH_TARGET_URL")
        or os.environ.get("MERIDIAN_TARGET_URL")
        or DEFAULT_URL
    ).strip()


def _ensure_legacy_v1_adapter_alias() -> dict[str, Any]:
    if os.path.exists(LEGACY_ALIAS_PATH):
        return {"ok": True, "created": False, "path": LEGACY_ALIAS_PATH}
    adapter_path = next((path for path in LEGACY_ADAPTER_PATHS if path and os.path.exists(path)), "")
    if not adapter_path:
        return {
            "ok": False,
            "created": False,
            "path": LEGACY_ALIAS_PATH,
            "error": f"legacy_v1 adapter missing at {LEGACY_ADAPTER_PATHS[-1]}",
        }
    os.makedirs(os.path.dirname(LEGACY_ALIAS_PATH), exist_ok=True)
    with open(LEGACY_ALIAS_PATH, "w", encoding="utf-8") as handle:
        handle.write("from adapters.legacy_v1_compatible import *  # noqa: F401,F403\n")
    return {"ok": True, "created": True, "path": LEGACY_ALIAS_PATH, "source_path": adapter_path}


def _read_json(path: str) -> dict[str, Any]:
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _fetch_http_mirror(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MeridianAutonomousResearcher/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", "replace")
            final_url = str(response.geturl() or url).strip()
            return {
                "ok": True,
                "url": final_url,
                "title": _extract_html_title(body),
                "body": body,
                "preview": _html_preview(body),
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "url": url,
            "title": "",
            "body": "",
            "preview": "",
            "error": str(exc),
        }


def _extract_html_title(html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html or "", re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _html_preview(html: str, limit: int = 10) -> str:
    text = re.sub(r"(?is)<script.*?</script>", " ", html or "")
    text = re.sub(r"(?is)<style.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    lines = [re.sub(r"\s+", " ", chunk).strip() for chunk in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines[:limit])


def _extract_worker_text(worker_result: dict[str, Any]) -> str:
    worker_result = dict(worker_result or {})
    host_response = worker_result.get("host_response_json")
    if isinstance(host_response, str):
        try:
            host_response = json.loads(host_response)
        except json.JSONDecodeError:
            host_response = {}
    if isinstance(host_response, dict):
        for key in ("output_text", "body_excerpt_utf8", "note"):
            value = str(host_response.get(key) or "").strip()
            if value:
                return value
    summary = str(worker_result.get("summary") or "").strip()
    if summary:
        return summary
    return ""


def _capability_show(name: str, *, timeout: int = 10) -> dict[str, Any]:
    return engine._run_loom_json(
        [
            "capability",
            "show",
            "--root",
            engine.DIRECT_LOOM_ROOT,
            "--name",
            name,
            "--format",
            "json",
        ],
        loom_bin=engine.DIRECT_LOOM_BIN,
        timeout=timeout,
    )


def _execute_capability(name: str, payload: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    command_result = engine._run_loom_json(
        [
            "action",
            "execute",
            "--root",
            engine.DIRECT_LOOM_ROOT,
            "--org-id",
            engine.DIRECT_LOOM_ORG_ID,
            "--agent-id",
            engine.DIRECT_LOOM_AGENT_ID,
            "--capability",
            name,
            "--payload-json",
            json.dumps(payload),
            "--format",
            "json",
        ],
        loom_bin=engine.DIRECT_LOOM_BIN,
        timeout=timeout,
    )
    payload_json = dict(command_result.get("payload") or {})
    worker_result_path = str(
        payload_json.get("worker_result_path")
        or payload_json.get("result_path")
        or ""
    ).strip()
    worker_result = _read_json(worker_result_path)
    return {
        "ok": bool(command_result.get("ok")),
        "error": str(command_result.get("error") or "").strip(),
        "stderr": str(command_result.get("stderr") or "").strip(),
        "payload": payload_json,
        "worker_result_path": worker_result_path,
        "worker_result": worker_result,
    }


def _maybe_analyze_with_loom(page_source: str, *, target_url: str, timeout: int) -> dict[str, Any]:
    capability = _capability_show(LLM_CAPABILITY, timeout=10)
    if not capability.get("ok"):
        return {
            "ok": False,
            "state": "capability_unavailable",
            "capability_name": LLM_CAPABILITY,
            "error": str(capability.get("error") or "loom llm capability is unavailable").strip(),
            "summary": "",
        }
    if not page_source.strip():
        return {
            "ok": False,
            "state": "no_source_text",
            "capability_name": LLM_CAPABILITY,
            "error": "no target content was available for runtime-backed analysis",
            "summary": "",
        }
    prompt = (
        "Produce exactly three markdown bullet points for a competitor brief.\n"
        f"URL: {target_url}\n\n"
        "Source material follows:\n"
        f"{page_source[:12000]}"
    )
    execution = _execute_capability(
        LLM_CAPABILITY,
        {
            "user_prompt": prompt,
            "system_prompt": (
                "You are Meridian Autonomous Researcher. Return exactly three concise markdown bullets "
                "grounded only in the provided source material."
            ),
            "model": "gpt-4o-mini",
            "max_tokens": 220,
            "timeout_ms": max(1000, min(timeout * 1000, 30000)),
        },
        timeout=max(timeout, LLM_TIMEOUT_SECONDS),
    )
    summary = _extract_worker_text(execution.get("worker_result") or {})
    if execution["ok"] and summary:
        return {
            "ok": True,
            "state": "completed",
            "capability_name": LLM_CAPABILITY,
            "summary": summary,
            "worker_result_path": execution.get("worker_result_path", ""),
        }
    error = execution.get("error") or execution.get("stderr") or "loom llm execution produced no summary"
    return {
        "ok": False,
        "state": "execution_failed",
        "capability_name": LLM_CAPABILITY,
        "error": str(error).strip(),
        "summary": summary,
        "worker_result_path": execution.get("worker_result_path", ""),
    }


def _maybe_persist_summary_with_loom(summary: str, *, timeout: int) -> dict[str, Any]:
    if not summary.strip():
        return {
            "ok": False,
            "state": "skipped_no_summary",
            "capability_name": FS_WRITE_CAPABILITY,
            "error": "no runtime-backed summary was available to persist",
            "path": COMPETITOR_BRIEF_PATH,
        }
    capability = _capability_show(FS_WRITE_CAPABILITY, timeout=10)
    if not capability.get("ok"):
        return {
            "ok": False,
            "state": "capability_unavailable",
            "capability_name": FS_WRITE_CAPABILITY,
            "error": str(capability.get("error") or "loom fs.write capability is unavailable").strip(),
            "path": COMPETITOR_BRIEF_PATH,
        }
    execution = _execute_capability(
        FS_WRITE_CAPABILITY,
        {
            "path": "competitor_brief.md",
            "content_utf8": summary.rstrip() + "\n",
            "create_dirs": True,
        },
        timeout=max(10, timeout),
    )
    if execution["ok"] and os.path.exists(COMPETITOR_BRIEF_PATH):
        return {
            "ok": True,
            "state": "written",
            "capability_name": FS_WRITE_CAPABILITY,
            "path": COMPETITOR_BRIEF_PATH,
            "worker_result_path": execution.get("worker_result_path", ""),
        }
    error = execution.get("error") or execution.get("stderr") or "loom fs.write did not prove a bounded file write"
    return {
        "ok": False,
        "state": "execution_failed",
        "capability_name": FS_WRITE_CAPABILITY,
        "error": str(error).strip(),
        "path": COMPETITOR_BRIEF_PATH,
        "worker_result_path": execution.get("worker_result_path", ""),
    }


def capture_legacy_v1_probe(engine_result: dict[str, Any]) -> dict[str, Any]:
    runtime = dict(engine_result.get("runtime") or {})
    capture_result = dict(engine_result.get("capture_result") or {})
    execution = dict(capture_result.get("delivery_execution") or {})
    submit = dict(execution.get("submit") or {})
    parity_path = str(
        submit.get("parity_report_path")
        or execution.get("parity_report_path")
        or ""
    ).strip()
    parity = _read_json(parity_path)
    transcript_bits = [
        "route=legacy_v1_parity_summary",
        "requested=loom",
        "selected=loom",
        f"preflight={'ok' if runtime.get('preflight', {}).get('ok') else 'blocked'}",
    ]
    capability_name = str(runtime.get("capability_name") or "").strip()
    if capability_name:
        transcript_bits.append(f"capability={capability_name}")
    worker_status = str(submit.get("worker_status") or execution.get("worker_result", {}).get("status") or "").strip()
    if worker_status:
        transcript_bits.append(f"worker_status={worker_status}")
    parity_status = str(parity.get("parity_status") or submit.get("parity_status") or "").strip()
    if parity_status:
        transcript_bits.append(f"parity_status={parity_status}")
    parity_reason = str(parity.get("parity_reason") or submit.get("parity_reason") or "").strip()
    if parity_reason:
        transcript_bits.append(f"parity_reason={parity_reason}")
    return {
        "transcript": " | ".join(transcript_bits),
        "parity_report_path": parity_path,
        "parity_status": parity_status or "<none>",
        "parity_reason": parity_reason or "<none>",
        "reference_probe_status": str(parity.get("reference_probe_status") or submit.get("reference_probe_status") or "<none>"),
        "effective_stage": str(parity.get("effective_stage") or submit.get("effective_stage") or "<none>"),
        "overall_decision": str(parity.get("overall_decision") or submit.get("overall_decision") or "<none>"),
    }


def _research_title(target_url: str, mirror: dict[str, Any]) -> str:
    title = str(mirror.get("title") or "").strip()
    if title:
        return title
    return target_url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Meridian Autonomous Researcher live loop")
    parser.add_argument("--url", default="", help="Target URL for governed acquisition")
    parser.add_argument("--timeout", type=int, default=25, help="Execution timeout in seconds")
    args = parser.parse_args(argv)

    target_url = _target_url(args.url)

    print(f"{BOLD}{MAGENTA}Meridian Autonomous Researcher{RESET}")
    print("Governed acquisition, runtime-backed analysis attempts, parity audit, and real settlement boundaries.")

    _step("Governance Bootstrap")
    boot = golden._bootstrap_governance()
    agent = golden._resolve_agent()
    warrant = golden._issue_warrant(agent)
    _line("kernel_ledger:", boot["ledger_path"])
    _line("bootstrap_agent_count:", str(boot["agent_count"]))
    _line("treasury_cash_usd:", str(boot["treasury_cash_usd"]))
    _line("agent_id:", str(agent.get("id") or ""))
    _line("warrant_id:", str(warrant.get("warrant_id") or ""))
    _line("court_review_state:", str(warrant.get("court_review_state") or ""))
    _line("execution_state:", str(warrant.get("execution_state") or ""))

    _step("Target Acquisition")
    alias = _ensure_legacy_v1_adapter_alias()
    if alias.get("ok"):
        _line(
            "legacy_v1_adapter_compatibility:",
            "created" if alias.get("created") else "present",
        )
    else:
        _line("legacy_v1_adapter_compatibility:", str(alias.get("error") or "missing"), color=RED)
    engine_result = engine.run_engine(
        target_url=target_url,
        disable_outbound_dispatch=True,
        keep_state=False,
        timeout=int(args.timeout),
    )
    runtime = dict(engine_result.get("runtime") or {})
    capture_result = dict(engine_result.get("capture_result") or {})
    execution = dict(capture_result.get("delivery_execution") or {})
    submit = dict(execution.get("submit") or {})
    mirror = _fetch_http_mirror(target_url)
    _line("target_url:", target_url)
    _line("loom_bin:", str(runtime.get("loom_bin") or ""))
    _line("capability_name:", str(runtime.get("capability_name") or "<unset>"))
    _line("preflight_ok:", str(bool(runtime.get("preflight", {}).get("ok"))).lower())
    _line("execution_ok:", str(bool(execution.get("ok"))).lower())
    _line("parity_report_path:", str(submit.get("parity_report_path") or "<none>"))
    _line("target_title:", _research_title(target_url, mirror))
    if mirror.get("ok"):
        _multiline("target_preview:", str(mirror.get("preview") or "<none>"))
    else:
        _line("target_preview_error:", str(mirror.get("error") or "mirror fetch failed"), color=RED)

    _step("Cognitive Analysis")
    source_material = str(mirror.get("body") or "").strip()
    analysis = _maybe_analyze_with_loom(source_material, target_url=target_url, timeout=int(args.timeout))
    _line("analysis_capability:", str(analysis.get("capability_name") or "<none>"))
    _line("analysis_state:", str(analysis.get("state") or "<none>"))
    if analysis.get("ok") and str(analysis.get("summary") or "").strip():
        _multiline("analysis_summary:", str(analysis.get("summary") or ""))
    else:
        _line("analysis_error:", str(analysis.get("error") or "no runtime-backed summary produced"), color=RED)
        _multiline("analysis_summary:", str(analysis.get("summary") or "<none>"))

    _step("Persistent Memory")
    memory = _maybe_persist_summary_with_loom(str(analysis.get("summary") or ""), timeout=int(args.timeout))
    _line("memory_capability:", str(memory.get("capability_name") or "<none>"))
    _line("memory_state:", str(memory.get("state") or "<none>"))
    _line("competitor_brief_path:", str(memory.get("path") or "<none>"))
    if memory.get("ok"):
        _line("memory_write_proved:", "true")
    else:
        _line("memory_write_proved:", "false", color=RED)
        _line("memory_error:", str(memory.get("error") or "loom fs.write did not prove a write"), color=RED)

    _step("The Audit")
    audit = capture_legacy_v1_probe(engine_result)
    _line("legacy_v1_parity_status:", str(audit.get("parity_status") or "<none>"))
    _line("legacy_v1_overall_decision:", str(audit.get("overall_decision") or "<none>"))
    _line("legacy_v1_effective_stage:", str(audit.get("effective_stage") or "<none>"))
    _line("legacy_v1_reference_probe_status:", str(audit.get("reference_probe_status") or "<none>"))
    _line("legacy_v1_parity_report_path:", str(audit.get("parity_report_path") or "<none>"))
    _multiline("legacy_v1_transcript:", str(audit.get("transcript") or "<none>"))

    _step("Cryptographic Settlement")
    blockchain = engine.delivery_blockchain_artifact(engine_result)
    sender_address = engine._blockchain_sender_address(engine_result)
    rpc_error = engine._blockchain_rpc_error(engine_result)
    artifact_type = str(blockchain.get("artifact_type") or "").strip()
    artifact_value = str(blockchain.get("artifact") or "").strip()
    _line("sender_address:", sender_address or "<none>")
    if artifact_type == "tx_hash" and artifact_value:
        _line("settlement_tx_hash:", artifact_value)
    else:
        _line("settlement_tx_hash:", "<none>", color=RED)
    if rpc_error:
        _line("settlement_error:", rpc_error, color=RED)
    else:
        _line("settlement_error:", "<none>")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
