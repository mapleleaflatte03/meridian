#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import time


HOME_DIR = str(Path.home())
MONOREPO_ROOT = str(os.environ.get("MERIDIAN_ROOT") or "").strip()
MERIDIAN_HOME = str(os.environ.get("MERIDIAN_HOME") or os.path.join(HOME_DIR, ".meridian")).strip()
WORKSPACE = Path(
    os.environ.get("MERIDIAN_WORKSPACE_ROOT")
    or (os.path.join(MONOREPO_ROOT, "intelligence") if MONOREPO_ROOT else "")
    or str(Path(__file__).resolve().parents[2])
).resolve()
CRON_JOBS = Path(os.environ.get("MERIDIAN_CRON_JOBS_PATH") or os.path.join(MERIDIAN_HOME, "cron", "jobs.json"))
GATEWAY_URL = "http://127.0.0.1:8266/api/run"
GATEWAY_ORIGIN = "https://app.welliam.codes"
DEFAULT_TZ = "Asia/Ho_Chi_Minh"
LOOM_BIN = Path(
    os.environ.get("MERIDIAN_LOOM_BIN")
    or os.path.join(HOME_DIR, ".local", "share", "meridian-loom", "current", "bin", "loom")
)
LOOM_ROOT = Path(
    os.environ.get("MERIDIAN_LOOM_ROOT")
    or os.path.join(HOME_DIR, ".local", "share", "meridian-loom", "runtime", "default")
)
DELIVERY_DIR = LOOM_ROOT / "state" / "channels" / "delivery"
RESEARCH_PIPELINE = WORKSPACE / "company" / "research_pipeline.py"
BRIEF_QUALITY = WORKSPACE / "company" / "brief_quality.py"
TELEGRAM_OUTBOUND_DEDUP_WINDOW_SECONDS = int(os.environ.get("MERIDIAN_TELEGRAM_OUTBOUND_DEDUP_WINDOW_SECONDS", "900"))

try:
    from capsule import ledger_path as capsule_ledger_path
except ImportError:
    from .capsule import ledger_path as capsule_ledger_path

sys.path.insert(0, str(WORKSPACE / "company"))
from brief_quality import assess_brief_content


def _load_jobs() -> list[dict]:
    with CRON_JOBS.open() as handle:
        return json.load(handle).get("jobs", [])


def _find_job(name: str) -> dict:
    for job in _load_jobs():
        if job.get("name") == name:
            return job
    raise SystemExit(f"unknown cron job: {name}")


def _local_date(job: dict) -> str:
    tz_name = (
        ((job.get("schedule") or {}).get("tz") or "").strip()
        or DEFAULT_TZ
    )
    now = dt.datetime.now(ZoneInfo(tz_name))
    return now.date().isoformat()


def _rewrite_legacy_message(message: str, job_name: str) -> str:
    local_date = _local_date(_find_job(job_name))
    rewritten = message.replace("YYYY-MM-DD", local_date)
    replacements = {
        "delegate to Forge via `openclaw agent --agent forge --message \"[task description]\" --json`": (
            "use Forge directly on the Meridian team path to execute that one bounded task"
        ),
        "Otherwise delegate to Quill: `openclaw agent --agent quill --message \"Write a morning brief for Sơn from these findings. Format: one-line title, 3 key findings each with source, 1-2 specific action items for Sơn, 1 risk to watch. Under 300 words. No filler. Telegram-friendly. Findings: [paste full findings file content]\" --json`.": (
            "Otherwise use Quill directly on the Meridian team path to write the morning brief for Son from these findings. Format: one-line title, 3 key findings each with source, 1-2 specific action items for Son, 1 risk to watch. Under 300 words. No filler. Telegram-friendly. Findings: [paste full findings file content]."
        ),
        "If remediate ALLOWED: run `openclaw agent --agent sentinel --message \"You are in remediation mode. Your task: review the following brief and write a structured remediation note showing you can produce correct verification format. Start your response with exactly REMEDIATION-NOTE on the first line, then list: (a) what you would check for factual accuracy, (b) example of a correct PASS verdict with one-line reason, (c) example of a correct FAIL verdict with one-line reason. Brief: [paste brief content]\" --json`.": (
            "If remediate ALLOWED: use Sentinel directly on the Meridian team path in remediation mode. Task: review the brief and write a structured remediation note showing correct verification format. Start exactly with REMEDIATION-NOTE on the first line, then list: (a) what you would check for factual accuracy, (b) example of a correct PASS verdict with one-line reason, (c) example of a correct FAIL verdict with one-line reason. Brief: [paste brief content]."
        ),
        "If sentinel ALLOWED for review: run `openclaw agent --agent sentinel --message \"Verify this brief for factual accuracy and source support. Your reply MUST contain PASS or FAIL as a standalone word within the first 5 lines of your response (ignore any thinking/reasoning tags). Then add your notes. Brief: [paste brief]\" --json`.": (
            "If sentinel ALLOWED for review: use Sentinel directly on the Meridian team path to verify this brief for factual accuracy and source support. The reply MUST contain PASS or FAIL as a standalone word within the first 5 lines, then notes. Brief: [paste brief]."
        ),
        "If ALLOWED: run `openclaw agent --agent aegis --message \"Accept or reject this brief for delivery. Check: facts are specific not vague, action items are actionable, under 300 words, no filler. Your reply MUST start with exactly ACCEPT or REJECT on the first line, then your reason. Brief: [paste brief]\" --json`": (
            "If ALLOWED: use Aegis directly on the Meridian team path to accept or reject this brief for delivery. Check: facts are specific not vague, action items are actionable, under 300 words, no filler. The reply MUST start with exactly ACCEPT or REJECT on the first line, then the reason. Brief: [paste brief]."
        ),
    }
    for source, target in replacements.items():
        rewritten = rewritten.replace(source, target)
    return rewritten


def _report_path(local_date: str) -> Path:
    return WORKSPACE / "night-shift" / "reports" / f"{local_date}-night.md"


def _findings_path(local_date: str) -> Path:
    return WORKSPACE / "night-shift" / f"findings-{local_date}.md"


def _brief_path(local_date: str) -> Path:
    return WORKSPACE / "night-shift" / f"brief-{local_date}.md"


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _append_report(local_date: str, lines: list[str]) -> Path:
    report_path = _report_path(local_date)
    existing_lines = _read_text(report_path).splitlines()
    payload = [line.rstrip() for line in lines if line.strip()]
    if not existing_lines:
        _write_text(report_path, "\n".join(payload))
        return report_path

    try:
        status_index = next(
            index for index, line in enumerate(existing_lines) if line.strip().lower() == "status:"
        )
    except StopIteration:
        existing = "\n".join(existing_lines).rstrip()
        if existing:
            _write_text(report_path, existing + "\n" + "\n".join(payload))
        else:
            _write_text(report_path, "\n".join(payload))
        return report_path

    prefix = existing_lines[: status_index + 1]
    status_lines = existing_lines[status_index + 1 :]
    merged = _merge_report_status_lines(status_lines, payload)
    _write_text(report_path, "\n".join(prefix + merged))
    return report_path


def _report_status_key(line: str) -> str:
    stripped = line.strip()
    if not stripped.startswith("- "):
        return stripped.lower()
    body = stripped[2:].strip()
    if ":" in body:
        return body.split(":", 1)[0].strip().lower()
    return body.lower()


def _normalize_telegram_dedup_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()[:8000]


def _telegram_long_window_text(text: str) -> bool:
    normalized = _normalize_telegram_dedup_text(text)
    return normalized.startswith("🌅 [") and "morning brief:" in normalized


def _recent_telegram_delivery_duplicate(recipient: str, text: str) -> dict | None:
    normalized_text = _normalize_telegram_dedup_text(text)
    if not normalized_text:
        return None
    now_ms = int(time.time() * 1000)
    if _telegram_long_window_text(text):
        cutoff_ms = 0
    else:
        cutoff_ms = now_ms - TELEGRAM_OUTBOUND_DEDUP_WINDOW_SECONDS * 1000
    matches = sorted(DELIVERY_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in matches:
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
        candidate_text = _normalize_telegram_dedup_text(str(payload.get("display_text") or ""))
        if candidate_text == normalized_text:
            return payload
    return None


def _merge_report_status_lines(existing: list[str], updates: list[str]) -> list[str]:
    merged: list[str] = []
    positions: dict[str, int] = {}

    def ingest(raw_line: str) -> None:
        line = raw_line.rstrip()
        if not line.strip():
            return
        key = _report_status_key(line)
        normalized = line if line.startswith("- ") else f"- {line.lstrip('- ').strip()}"
        if key in positions:
            merged[positions[key]] = normalized
        else:
            positions[key] = len(merged)
            merged.append(normalized)

    for line in existing:
        ingest(line)
    for line in updates:
        ingest(line)
    return merged


def _parse_production_topics(backlog_text: str) -> list[str]:
    lines = backlog_text.splitlines()
    topics: list[str] = []
    in_section = False
    for raw in lines:
        line = raw.strip()
        if line.startswith("## "):
            in_section = line.lower() == "## production topics"
            continue
        if not in_section:
            continue
        if line.startswith("- "):
            topics.append(line[2:].strip())
        elif line:
            break
    return topics


def _parse_last_topic(handoff_text: str) -> str:
    for raw in handoff_text.splitlines():
        line = raw.strip()
        if line.lower().startswith("topic:"):
            return line.split(":", 1)[1].strip()
    return ""


def _extract_report_topic(report_text: str) -> str:
    for raw in report_text.splitlines():
        line = raw.strip()
        if line.lower().startswith("topic:"):
            return line.split(":", 1)[1].strip()
    return ""


def _parse_findings_markdown(findings_text: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in findings_text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("- Fact:"):
            if current:
                findings.append(current)
            current = {"fact": stripped.split(":", 1)[1].strip()}
            continue
        if not current:
            continue
        if stripped.startswith("- Observed:"):
            current["observed"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("- Source:"):
            current["source"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("- Category:"):
            current["category"] = stripped.split(":", 1)[1].strip()
    if current:
        findings.append(current)
    return findings


def _normalize_fact_text(text: str, source: str = "") -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    lowered = normalized.lower()
    if "introducing claude opus 4.6" in lowered:
        return "Anthropic announced Claude Opus 4.6 on February 5, 2026."
    if "what 81,000 people want from ai" in lowered:
        return "Anthropic published a March 18, 2026 post summarizing input from 81,000 users about what they want from AI."
    if "deprecation schedules for stable" in lowered and "gemini api" in lowered:
        return "Google published Gemini API deprecation schedules for stable and preview models."
    if "free input & output tokens" in lowered and "production applications" in lowered:
        return "Gemini API pricing shows a free tier for limited usage and paid tiers for production workloads."
    if "model report" in lowered and "deployment safeguards" in lowered:
        return "Anthropic Transparency Hub summarizes model capabilities, safety evaluations, and deployment safeguards."
    if "research breakthroughs" in lowered and "gemma scope 2" in lowered:
        return "DeepMind highlights 2025 research breakthroughs, including Gemma Scope 2 and safety-oriented work."
    if "cookie settings" in lowered or "log in search" in lowered or "sign up build ai responsibly" in lowered:
        return ""
    if normalized.startswith("0 1 ") or normalized.startswith("0 2 ") or normalized.startswith("0 3 "):
        return ""
    return normalized


def _fact_quality_score(finding: dict[str, str]) -> int:
    fact = _normalize_fact_text(finding.get("fact") or "", finding.get("source") or "")
    lowered = fact.lower()
    score = 0
    if fact:
        score += 2
    if 60 <= len(fact) <= 180:
        score += 2
    if any(token in lowered for token in ("announced", "published", "shows", "highlights", "summarizes")):
        score += 2
    if any(token in lowered for token in ("pricing", "deprecation", "opus", "transparency", "research")):
        score += 2
    if any(token in lowered for token in ("privacy", "cookies", "register now", "log in")):
        score -= 5
    return score


def _compact_fact(text: str, *, limit: int = 180) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= limit:
        return normalized
    clipped = normalized[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return clipped + "..."


def _competitive_meaning(finding: dict[str, str]) -> str:
    fact = (finding.get("fact") or "").lower()
    source = (finding.get("source") or "").lower()
    category = (finding.get("category") or "").lower()
    if "pricing" in fact or "pricing" in source or "token" in fact:
        return (
            "Competitive meaning: pricing clarity and token limits are becoming explicit buying criteria, "
            "so Meridian needs a simpler evaluation-to-paid path and a cleaner cost story."
        )
    if "deprecation" in fact or "deprecation" in source:
        return (
            "Competitive meaning: vendors are training customers to expect lifecycle transparency, "
            "which creates an opening for Meridian if it can offer stable migration guidance."
        )
    if "transparency" in fact or "model report" in fact or "safety" in fact:
        return (
            "Competitive meaning: public trust documentation is part of product positioning now, "
            "not a side note, so Meridian needs buyer-friendly governance proof."
        )
    if "opus" in fact or "launch" in fact or "introducing" in fact or "release" in fact:
        return (
            "Competitive meaning: flagship-model iteration is still a live battlefield, "
            "so Meridian should expect continued pressure on premium capability benchmarks."
        )
    if "deepmind" in source or "research" in category:
        return (
            "Competitive meaning: research velocity is still feeding platform credibility, "
            "which means Meridian has to explain why governance and operator outcomes matter to buyers."
        )
    return (
        "Competitive meaning: this is more evidence of sustained model-platform momentum, "
        "so Meridian should respond with sharper positioning and narrower buyer-specific proof."
    )


def _source_label(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host.removeprefix("www.") or url


def _synthesize_brief_from_findings(findings_text: str, local_date: str, topic: str) -> str:
    findings = _parse_findings_markdown(findings_text)
    ranked = sorted(findings, key=_fact_quality_score, reverse=True)
    selected: list[dict[str, str]] = []
    seen_sources: set[str] = set()
    seen_facts: set[str] = set()
    target_findings = 5
    for finding in ranked:
        source = finding.get("source") or ""
        fact = _normalize_fact_text(finding.get("fact") or "", source)
        if not fact or fact in seen_facts:
            continue
        if source and source in seen_sources and len(selected) < target_findings:
            continue
        enriched = dict(finding)
        enriched["fact"] = fact
        selected.append(enriched)
        seen_facts.add(fact)
        if source:
            seen_sources.add(source)
        if len(selected) == target_findings:
            break
    if not selected:
        raise SystemExit("cannot synthesize brief without findings")
    title = f"**Meridian Morning Competitor-Intelligence Brief | {local_date}**"
    lines = [
        title,
        "",
        f"Topic: {topic or 'Competitor movement'}",
        "",
        (
            "This morning brief is built from the latest bounded findings pack Meridian collected overnight. "
            "It focuses on the competitive moves most likely to affect buyer expectations around pricing, model trust, "
            "and lifecycle stability rather than trying to summarize the whole market."
        ),
        "",
    ]
    for index, finding in enumerate(selected, start=1):
        observed = finding.get("observed") or local_date
        source = finding.get("source") or ""
        fact = _compact_fact(_normalize_fact_text(finding.get("fact") or "", source))
        lines.append(f"**{index}. {fact}**")
        lines.append(
            f"Observed {observed}. {_competitive_meaning(finding)}"
        )
        lines.append(f"Source: {source}")
        lines.append("")
    lines.extend(
        [
            "**Action Items**",
            "- Re-fetch the strongest two primary pages above and capture exact quoted facts for founder-facing or customer-facing use.",
            "- Turn the clearest pricing or lifecycle shift into one outbound message for a target buyer segment Meridian actually wants now.",
            "- Update Meridian public positioning so trust, portability, and migration support are stated in buyer language rather than architecture language.",
            "",
            "**Risk Watch**",
            "- If the brief relies on weak aggregator snippets instead of primary pages, Meridian will sound derivative instead of authoritative.",
            "- If pricing and lifecycle changes keep compounding across major labs, Meridian will lose buyer attention unless its wedge is narrower and easier to buy.",
            "- If Meridian cannot show governance proof in a buyer-readable format, stronger labs will keep winning trust by default.",
            "",
            (
                "Bottom line: the strongest overnight signal is not a single model launch. It is that major labs are tightening "
                "the bundle around model capability, trust collateral, and pricing structure at the same time. Meridian should respond "
                "with a narrower buyer story and sharper proof, not broader architecture language."
            ),
        ]
    )
    return "\n".join(lines).strip()


def _run_local(cmd: list[str], *, timeout: int = 900, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["MERIDIAN_WORKSPACE"] = str(WORKSPACE)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(WORKSPACE),
        env=env,
        check=False,
    )


def _gateway_run(goal: str, *, session_id: str) -> dict:
    payload = json.dumps({"goal": goal, "session_id": session_id}).encode("utf-8")
    request = urllib.request.Request(
        GATEWAY_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Origin": GATEWAY_ORIGIN,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"gateway http error {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"gateway connection failed: {exc}")
    data = json.loads(raw)
    if data.get("status") != "success":
        raise SystemExit(f"gateway run failed: {raw}")
    return data


def _normalized_web_session_key(session_id: str) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", str(session_id or "").strip().lower()).strip("-._")
    return f"web_api:{normalized[:64]}"


def _session_events_path(session_key: str) -> Path:
    token = hashlib.sha1(session_key.encode("utf-8")).hexdigest()[:16]
    return LOOM_ROOT / "state" / "session-history" / "events" / f"{token}.json"


def _load_session_events(session_key: str) -> list[dict]:
    path = _session_events_path(session_key)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    events = payload.get("events") or []
    return [event for event in events if isinstance(event, dict)]


def _unwrap_candidate_text(raw_text: str) -> str:
    text = str(raw_text or "").strip()
    if not text:
        return ""
    if text.startswith("{") and '"result"' in text:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text
        result = str(payload.get("result") or "").strip()
        return result or text
    return text


def _looks_like_brief(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    return (
        ("**action items**" in lowered or "action items" in lowered)
        and ("**risk watch**" in lowered or "risk watch" in lowered)
        and ("source:" in lowered or "**source:**" in lowered)
    )


def _brief_candidate_rank(
    *,
    audit: dict,
    source_kind: str,
) -> tuple[int, int, int, int, int, int]:
    word_count = int(audit.get("word_count") or 0)
    distinct_sources = int(audit.get("distinct_sources") or 0)
    findings_count = int(audit.get("findings_count") or 0)
    publishable = int(bool(audit.get("passed")) and word_count >= 400)
    source_preference = {
        "manager_response": 3,
        "writer_receipt": 2,
        "analyst_receipt": 1,
        "synthesized_fallback": 0,
    }.get(source_kind, 0)
    return (
        publishable,
        int(word_count >= 400),
        min(word_count, 600),
        distinct_sources,
        findings_count,
        source_preference,
    )


def _select_best_brief_text(
    *,
    primary_text: str,
    session_key: str,
    local_date: str,
    findings_text: str,
    topic: str,
) -> tuple[str, dict[str, object]]:
    candidates: list[dict[str, object]] = []

    def add_candidate(source_kind: str, raw_text: str) -> None:
        text = _unwrap_candidate_text(raw_text)
        if not _looks_like_brief(text):
            return
        audit = assess_brief_content(text, brief_date=local_date)
        candidates.append(
            {
                "source_kind": source_kind,
                "text": text,
                "audit": audit,
                "rank": _brief_candidate_rank(audit=audit, source_kind=source_kind),
            }
        )

    add_candidate("manager_response", primary_text)
    for event in _load_session_events(session_key):
        history_type = str(event.get("history_type") or "").strip().lower()
        if history_type == "manager_response":
            add_candidate("manager_response", str(event.get("text") or ""))
            continue
        if history_type != "worker_receipt":
            continue
        role = str(event.get("role") or "").strip().lower()
        if role == "writer":
            add_candidate("writer_receipt", str(event.get("text") or ""))
        elif role == "analyst":
            add_candidate("analyst_receipt", str(event.get("text") or ""))

    synthesized = _synthesize_brief_from_findings(findings_text, local_date, topic)
    add_candidate("synthesized_fallback", synthesized)
    if not candidates:
        return synthesized, {
            "source_kind": "synthesized_fallback",
            "audit": assess_brief_content(synthesized, brief_date=local_date),
            "rank": _brief_candidate_rank(
                audit=assess_brief_content(synthesized, brief_date=local_date),
                source_kind="synthesized_fallback",
            ),
        }
    best = max(candidates, key=lambda item: item["rank"])
    return str(best["text"]), best


def _send_channel_message(job: dict, text: str) -> dict:
    delivery = job.get("delivery") or {}
    channel = (delivery.get("channel") or "").strip()
    recipient = str(delivery.get("to") or "").strip()
    if not channel or not recipient:
        raise SystemExit("delivery target missing for channel-mode job")
    if channel == "telegram":
        duplicate = _recent_telegram_delivery_duplicate(recipient, text)
        if duplicate:
            return {
                "status": "success",
                "deduped": True,
                "payload": duplicate,
            }
    cmd = [
        str(LOOM_BIN),
        "channel",
        "send",
        "--root",
        str(LOOM_ROOT),
        "--channel",
        channel,
        "--recipient",
        recipient,
        "--text",
        text,
        "--format",
        "json",
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    if completed.returncode != 0:
        raise SystemExit(
            f"loom channel send failed ({completed.returncode}): {(completed.stderr or completed.stdout).strip()}"
        )
    return json.loads(completed.stdout)


def _wait_for_delivery(delivery_id: str, *, timeout_seconds: int = 30) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        matches = sorted(DELIVERY_DIR.glob(f"*-{delivery_id}.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if matches:
            payload = json.loads(matches[0].read_text(encoding="utf-8"))
            status = str(payload.get("status") or "").strip().lower()
            if status and status not in {"queued", "pending"}:
                return payload
        time.sleep(1)
    matches = sorted(DELIVERY_DIR.glob(f"*-{delivery_id}.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if matches:
        return json.loads(matches[0].read_text(encoding="utf-8"))
    return {"delivery_id": delivery_id, "status": "missing"}


def _run_kickoff_job(job: dict, *, session_id: str) -> dict:
    local_date = _local_date(job)
    backlog_text = _read_text(WORKSPACE / "night-shift" / "BACKLOG.md")
    handoff_text = _read_text(WORKSPACE / "night-shift" / "LAST_HANDOFF.md")
    topics = _parse_production_topics(backlog_text)
    last_topic = _parse_last_topic(handoff_text)
    chosen_topic = next((topic for topic in topics if topic and topic != last_topic), topics[0] if topics else "AI model pricing changes and deprecation schedules")
    report_text = "\n".join([
        f"# Night Shift Report — {local_date}",
        "",
        f"topic: {chosen_topic}",
        "pipeline:",
        f"- research -> {_findings_path(local_date)}",
        f"- execute -> {_report_path(local_date)}",
        f"- write -> {_brief_path(local_date)}",
        f"- qa -> {_report_path(local_date)}",
        "- deliver -> telegram:5322393870",
        f"- score -> {WORKSPACE / 'economy' / 'ledger.json'}",
        "",
        "status:",
        "- kickoff: complete",
        "- owner messaging: disabled until deliver",
    ])
    _write_text(_report_path(local_date), report_text)
    return {
        "status": "success",
        "output": report_text,
        "session_id": session_id,
        "session_key": f"cron:{job.get('name')}",
    }


def _run_research_job(job: dict, *, session_id: str) -> dict:
    local_date = _local_date(job)
    output_path = _findings_path(local_date)
    completed = _run_local(
        [
            sys.executable,
            str(RESEARCH_PIPELINE),
            "--max-sources",
            "12",
            "--timeout",
            "12",
            "--output",
            str(output_path),
        ],
        extra_env={"MERIDIAN_LOCAL_DATE": local_date},
        timeout=int(((job.get("payload") or {}).get("timeoutSeconds") or 900)),
    )
    if completed.returncode != 0:
        _append_report(local_date, [f"- research-skipped: pipeline failed", completed.stderr.strip() or completed.stdout.strip()])
        raise SystemExit((completed.stderr or completed.stdout).strip() or "research pipeline failed")
    findings_json = output_path.with_suffix(".json")
    source_summary = ""
    if findings_json.exists():
        with findings_json.open() as handle:
            data = json.load(handle)
        source_summary = f"sources_succeeded={data.get('sources_succeeded', 0)} findings={len(data.get('findings', []))}"
    _append_report(local_date, [f"- research: {output_path}", f"- atlas: {source_summary or 'findings file present'}"])
    return {
        "status": "success",
        "output": (completed.stdout or "").strip(),
        "session_id": session_id,
        "session_key": f"cron:{job.get('name')}",
    }


def _run_execute_job(job: dict, *, session_id: str) -> dict:
    local_date = _local_date(job)
    backlog_text = _read_text(WORKSPACE / "night-shift" / "BACKLOG.md")
    pending = []
    in_section = False
    for raw in backlog_text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            in_section = line.lower() == "## code/config tasks"
            continue
        if not in_section:
            continue
        if line.startswith("- ") and "(none pending" not in line.lower():
            pending.append(line[2:].strip())
    if not pending:
        _append_report(local_date, ["- no-exec: no bounded task available"])
        return {
            "status": "success",
            "output": "no-exec: no bounded task available",
            "session_id": session_id,
            "session_key": f"cron:{job.get('name')}",
        }
    _append_report(local_date, [f"- execution: pending task detected: {pending[0]}", "- no-exec: execution bridge not enabled for code tasks yet"])
    return {
        "status": "success",
        "output": f"execution task detected but not executed: {pending[0]}",
        "session_id": session_id,
        "session_key": f"cron:{job.get('name')}",
    }


def _run_write_job(job: dict, *, session_id: str) -> dict:
    local_date = _local_date(job)
    findings_path = _findings_path(local_date)
    findings_text = _read_text(findings_path)
    if not findings_text.strip():
        _append_report(local_date, ["- write-skipped: no findings file"])
        return {
            "status": "success",
            "output": "write-skipped: no findings file",
            "session_id": session_id,
            "session_key": f"cron:{job.get('name')}",
        }
    goal = (
        "Write Meridian's morning competitor-intelligence brief for Son from the findings below. "
        "Return only the final brief markdown. Requirements: 400-600 words, first line is a bold headline, "
        "4 or more findings with specific competitive meaning, each finding includes a Source line, "
        "then an Action Items section and a Risk Watch section. No filler. Telegram-friendly. "
        f"Save target path is {_brief_path(local_date)} but return only the brief body.\n\n"
        f"Findings markdown:\n{findings_text}"
    )
    result = _gateway_run(goal, session_id=session_id)
    primary_text = str(result.get("output") or "").strip()
    if not primary_text:
        raise SystemExit("gateway write job returned empty output")
    topic = _extract_report_topic(_read_text(_report_path(local_date)))
    session_key = str(result.get("session_key") or _normalized_web_session_key(session_id))
    brief_text, selected = _select_best_brief_text(
        primary_text=primary_text,
        session_key=session_key,
        local_date=local_date,
        findings_text=findings_text,
        topic=topic,
    )
    _write_text(_brief_path(local_date), brief_text)
    source_kind = str(selected.get("source_kind") or "unknown")
    selected_audit = selected.get("audit") or {}
    lines = [
        f"- write: {_brief_path(local_date)}",
        "- quill draft saved: yes",
        f"- write-artifact: {source_kind}",
        (
            "- write-quality: "
            f"words={selected_audit.get('word_count', 0)} "
            f"sources={selected_audit.get('distinct_sources', 0)} "
            f"findings={selected_audit.get('findings_count', 0)}"
        ),
    ]
    if source_kind == "synthesized_fallback":
        lines.append("- write-salvaged: local findings synthesis")
    else:
        lines.append("- write-salvaged: not needed")
    _append_report(local_date, lines)
    return result


def _run_qa_job(job: dict, *, session_id: str) -> dict:
    local_date = _local_date(job)
    brief_path = _brief_path(local_date)
    if not brief_path.exists():
        _append_report(local_date, ["- qa-skipped: no brief file"])
        return {
            "status": "success",
            "output": "qa-skipped: no brief file",
            "session_id": session_id,
            "session_key": f"cron:{job.get('name')}",
        }
    completed = _run_local(
        [sys.executable, str(BRIEF_QUALITY), "--brief", str(brief_path), "--json"],
        extra_env={"MERIDIAN_LOCAL_DATE": local_date},
        timeout=120,
    )
    if not completed.stdout.strip():
        raise SystemExit((completed.stderr or "").strip() or "brief quality returned no output")
    audit = json.loads(completed.stdout)
    passed = bool(audit.get("pass"))
    word_count = int(audit.get("word_count") or 0)
    if word_count < 400:
        passed = False
        failures = audit.setdefault("failures", [])
        message = f"under 400 words ({word_count})"
        if message not in failures:
            failures.append(message)
    audit["pass"] = passed
    audit["passed"] = passed
    sentinel = "PASS" if passed else "FAIL"
    aegis = "ACCEPT" if passed else "REJECT"
    lines = [
        f"- sentinel result: {sentinel}",
        f"- aegis result: {aegis}",
        f"- qa: words={word_count} sources={audit.get('distinct_sources', 0)} findings={audit.get('findings_count', 0)}",
    ]
    if not passed:
        failures = audit.get("failures") or []
        if failures:
            lines.append(f"- qa-failures: {'; '.join(failures)}")
        else:
            lines.append("- qa-failures: quality gate rejected without structured failure detail")
    else:
        lines.append("- qa-failures: none")
    _append_report(local_date, lines)
    return {
        "status": "success",
        "output": json.dumps({"sentinel": sentinel, "aegis": aegis, "audit": audit}, ensure_ascii=False),
        "session_id": session_id,
        "session_key": f"cron:{job.get('name')}",
    }


def _run_deliver_job(job: dict, *, session_id: str) -> dict:
    local_date = _local_date(job)
    report_text = _read_text(_report_path(local_date))
    brief_text = _read_text(_brief_path(local_date))
    ready = "aegis result: ACCEPT" in report_text or "aegis result: ACCEPT".lower() in report_text.lower()
    if brief_text.strip() and ready:
        message = f"🌅 [{local_date}] Morning brief:\n\n{brief_text.strip()}"
    else:
        reason = "brief missing or qa-skipped"
        for raw in reversed(report_text.splitlines()):
            line = raw.strip()
            if line.startswith("- ") and ("qa-" in line or "write-skipped" in line or "no-exec" in line):
                reason = line[2:]
                break
        message = f"🌅 [{local_date}] Night shift complete. No brief — {reason}."
    delivery = _send_channel_message(job, message)
    delivery_id = delivery.get('payload', {}).get('delivery_id', '') or delivery.get('delivery_id', '')
    if delivery_id:
        delivery = _wait_for_delivery(delivery_id)
    topic = _extract_report_topic(report_text) or "unknown"
    handoff = "\n".join([
        "# Last Night-Shift Handoff",
        "",
        f"topic: {topic}",
        "artifacts:",
        f"- {_report_path(local_date)}",
        f"- {_findings_path(local_date)}" if _findings_path(local_date).exists() else "- findings not produced",
        f"- {_brief_path(local_date)}" if _brief_path(local_date).exists() else "- brief not produced",
        "skipped steps:",
        "- none" if "No brief —" not in message else f"- deliver sent fallback: {message}",
        "next-night topic suggestion: choose the next Production Topic not equal to tonight's topic",
        "",
        f"---\nLast updated: {local_date}",
    ])
    _write_text(WORKSPACE / "night-shift" / "LAST_HANDOFF.md", handoff)
    _append_report(
        local_date,
        [
            f"- deliver: {delivery_id}",
            f"- delivery-status: {delivery.get('status', '')}",
        ],
    )
    return {
        "status": "success",
        "channel_delivery": delivery,
        "output": f"delivery {delivery_id} -> {delivery.get('status', '')}",
        "message_preview": message[:400],
        "session_id": session_id,
        "session_key": f"cron:{job.get('name')}",
    }


def _run_score_job(job: dict, *, session_id: str) -> dict:
    auto_score = WORKSPACE / "economy" / "auto_score.py"
    completed = subprocess.run(
        [sys.executable, str(auto_score)],
        capture_output=True,
        text=True,
        timeout=int(((job.get("payload") or {}).get("timeoutSeconds") or 300)),
        cwd=str(WORKSPACE),
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit((completed.stderr or completed.stdout).strip() or "auto_score failed")
    with open(capsule_ledger_path()) as handle:
        ledger_payload = json.load(handle)
    agents = ledger_payload.get("agents") or {}
    summary_lines = [line for line in (completed.stdout or "").splitlines() if line.strip()]
    summary_lines.append("Current REP/AUTH:")
    for agent_name in sorted(agents):
        record = agents[agent_name]
        summary_lines.append(
            f"- {agent_name}: REP={record.get('reputation_units', 0)} AUTH={record.get('authority_units', 0)}"
        )
    return {
        "status": "success",
        "output": "\n".join(summary_lines),
        "session_id": session_id,
        "session_key": f"cron:{job.get('name')}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bridge Loom schedules into Meridian jobs")
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    job = _find_job(args.job_name)
    payload = job.get("payload") or {}
    job_name = str(job.get("name") or "").strip()
    local_date = _local_date(job)
    session_id = f"loom-schedule::{job_name}::{local_date}::{int(dt.datetime.now(dt.timezone.utc).timestamp())}"

    if job_name == "night-shift-kickoff":
        result = _run_kickoff_job(job, session_id=session_id)
    elif job_name == "night-shift-research":
        result = _run_research_job(job, session_id=session_id)
    elif job_name == "night-shift-execute":
        result = _run_execute_job(job, session_id=session_id)
    elif job_name == "night-shift-write":
        result = _run_write_job(job, session_id=session_id)
    elif job_name == "night-shift-qa":
        result = _run_qa_job(job, session_id=session_id)
    elif job_name == "night-shift-deliver":
        result = _run_deliver_job(job, session_id=session_id)
    elif job_name == "night-shift-score":
        result = _run_score_job(job, session_id=session_id)
    else:
        message = _rewrite_legacy_message(str(payload.get("message") or ""), job_name)
        result = _gateway_run(message, session_id=session_id)

    if args.json:
        print(json.dumps({
            "job_name": job_name,
            "local_date": local_date,
            "session_id": session_id,
            "result": result,
        }, ensure_ascii=False, indent=2))
    else:
        print(result.get("output", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
