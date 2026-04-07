#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from loom_runtime_discovery import preferred_loom_root

HOME_DIR = str(Path.home())
MONOREPO_ROOT = str(os.environ.get("MERIDIAN_ROOT") or "").strip()
MERIDIAN_HOME = str(os.environ.get("MERIDIAN_HOME") or os.path.join(HOME_DIR, ".meridian")).strip()
WORKSPACE = Path(
    os.environ.get("MERIDIAN_WORKSPACE_ROOT")
    or (os.path.join(MONOREPO_ROOT, "intelligence") if MONOREPO_ROOT else "")
    or str(Path(__file__).resolve().parents[2])
).resolve()
CRON_JOBS = Path(os.environ.get("MERIDIAN_CRON_JOBS_PATH") or os.path.join(MERIDIAN_HOME, "cron", "jobs.json"))
BRIDGE = WORKSPACE / "company" / "meridian_platform" / "loom_schedule_bridge.py"
SCHEDULE_PREFIX = "night-shift-"
PLACEHOLDER_IDS = {
    "night_shift_kickoff",
    "night_shift_research",
    "night_shift_write",
    "morning_brief",
}


def _next_fire_utc(hhmm: str, now: dt.datetime) -> int:
    hour, minute = [int(part) for part in hhmm.split(":", 1)]
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += dt.timedelta(days=1)
    return int(candidate.timestamp() * 1000)


def _cron_expr_to_utc_hhmm(expr: str, tz_name: str) -> str:
    minute, hour, *_ = expr.split()
    src_now = dt.datetime.now(ZoneInfo(tz_name))
    local_target = src_now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    utc_target = local_target.astimezone(dt.timezone.utc)
    return f"{utc_target.hour:02d}:{utc_target.minute:02d}"


def _night_shift_records() -> list[dict]:
    with CRON_JOBS.open() as handle:
        jobs = json.load(handle).get("jobs", [])
    now_utc = dt.datetime.now(dt.timezone.utc)
    records = []
    for job in jobs:
        name = str(job.get("name") or "")
        if not name.startswith(SCHEDULE_PREFIX):
            continue
        schedule = job.get("schedule") or {}
        expr = str(schedule.get("expr") or "").strip()
        if not expr:
            continue
        tz_name = str(schedule.get("tz") or "UTC").strip() or "UTC"
        hhmm_utc = _cron_expr_to_utc_hhmm(expr, tz_name)
        records.append({
            "job_id": name,
            "agent_id": str(job.get("agentId") or "main"),
            "job_kind": name,
            "schedule_kind": "daily",
            "schedule_expression": hhmm_utc,
            "timezone": "UTC",
            "every_seconds": 0,
            "not_before_unix_ms": None,
            "payload_json": json.dumps({
                "exec_argv": [
                    "python3",
                    str(BRIDGE),
                    "--job-name",
                    name,
                    "--json",
                ],
                "message": f"Meridian bridge schedule for {name}",
            }),
            "delivery_target": None,
            "source_kind": "meridian_cron_bridge",
            "enabled": bool(job.get("enabled", False)),
            "status": "scheduled" if bool(job.get("enabled", False)) else "paused",
            "max_attempts": 1,
            "run_count": 0,
            "last_fire_at_unix_ms": None,
            "next_fire_at_unix_ms": _next_fire_utc(hhmm_utc, now_utc),
        })
    return records


def main() -> int:
    root = Path(preferred_loom_root())
    registry_path = root / "state" / "schedules" / "registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    existing = {"schedules": []}
    if registry_path.exists():
        with registry_path.open() as handle:
            existing = json.load(handle)
    records = []
    for record in existing.get("schedules", []):
        job_id = str(record.get("job_id") or "")
        if job_id in PLACEHOLDER_IDS or job_id.startswith(SCHEDULE_PREFIX):
            continue
        records.append(record)
    records.extend(_night_shift_records())
    records.sort(key=lambda item: str(item.get("job_id") or ""))
    with registry_path.open("w") as handle:
        json.dump({"schedules": records}, handle, indent=2)
        handle.write("\n")
    print(json.dumps({
        "registry_path": str(registry_path),
        "job_ids": [record.get("job_id", "") for record in records],
        "count": len(records),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
