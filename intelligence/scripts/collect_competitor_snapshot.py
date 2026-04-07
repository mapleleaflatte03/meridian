#!/usr/bin/env python3
"""Collect repeatable repo activity snapshots for Meridian vs Claw-family repos."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List

REPOS: List[str] = [
    "mapleleaflatte03/meridian-loom",
    "mapleleaflatte03/meridian-kernel",
    "mapleleaflatte03/meridian-intelligence",
    "nagisanzenin/skyclaw",
    "RightNow-AI/openfang",
    "zeroclaw-labs/zeroclaw",
    "clawdotnet/openclaw.net",
    "nearai/ironclaw",
    "clawsouls/soulclaw",
    "openclaw/openclaw",
]


def gh_api(path: str) -> Any:
    out = subprocess.check_output(["gh", "api", path], text=True)
    return json.loads(out)


def count_recent(commits: List[Dict[str, Any]], now_unix: int, window_seconds: int) -> int:
    total = 0
    for commit in commits:
        date = (
            commit.get("commit", {})
            .get("author", {})
            .get("date")
        )
        if not date:
            continue
        ts = int(dt.datetime.fromisoformat(date.replace("Z", "+00:00")).timestamp())
        if now_unix - ts <= window_seconds:
            total += 1
    return total


def collect_snapshot() -> Dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    now_unix = int(now.timestamp())
    rows: List[Dict[str, Any]] = []
    for repo in REPOS:
        meta = gh_api(f"repos/{repo}")
        commits = gh_api(f"repos/{repo}/commits?per_page=50")
        rows.append(
            {
                "repo": repo,
                "stars": meta.get("stargazers_count", 0),
                "forks": meta.get("forks_count", 0),
                "language": meta.get("language"),
                "default_branch": meta.get("default_branch"),
                "pushed_at": meta.get("pushed_at"),
                "updated_at": meta.get("updated_at"),
                "commit_velocity": {
                    "last_24h": count_recent(commits, now_unix, 24 * 3600),
                    "last_72h": count_recent(commits, now_unix, 72 * 3600),
                    "last_7d": count_recent(commits, now_unix, 7 * 24 * 3600),
                },
                "recent_commits": [
                    {
                        "date": c.get("commit", {}).get("author", {}).get("date"),
                        "author": (c.get("author") or {}).get("login", "unknown"),
                        "message": (
                            c.get("commit", {}).get("message", "").splitlines() or [""]
                        )[0],
                    }
                    for c in commits[:10]
                ],
            }
        )
    return {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "source": "github_api_via_gh",
        "repos": rows,
    }


def render_markdown(payload: Dict[str, Any]) -> str:
    lines = [
        "# Meridian vs Claw Snapshot",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- repos: `{len(payload['repos'])}`",
        "",
        "| Repo | Stars | Forks | 24h commits | 72h commits | 7d commits |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in payload["repos"]:
        velocity = row["commit_velocity"]
        lines.append(
            "| {repo} | {stars} | {forks} | {c24} | {c72} | {c7d} |".format(
                repo=row["repo"],
                stars=row["stars"],
                forks=row["forks"],
                c24=velocity["last_24h"],
                c72=velocity["last_72h"],
                c7d=velocity["last_7d"],
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-json",
        default="output/competitor_snapshot/latest.json",
        help="Output JSON path.",
    )
    parser.add_argument(
        "--out-md",
        default="output/competitor_snapshot/latest.md",
        help="Output Markdown path.",
    )
    args = parser.parse_args()

    payload = collect_snapshot()

    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)

    out_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(render_markdown(payload), encoding="utf-8")
    print(f"snapshot_json={out_json}")
    print(f"snapshot_md={out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
