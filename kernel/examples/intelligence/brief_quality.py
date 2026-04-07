#!/usr/bin/env python3
"""
Brief quality gate for the intelligence vertical.

Validates a brief against the stated quality bar using the brief body
and, when available, its paired findings file.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
from typing import Any

# Resolve paths relative to repo root
EXAMPLES_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(EXAMPLES_DIR))

# Configurable: override via environment variable.
# `MERIDIAN_NS_DIR` remains for backward compatibility with older deployments.
ARTIFACT_DIR = (
    os.environ.get('MERIDIAN_ARTIFACT_DIR')
    or os.environ.get('MERIDIAN_NS_DIR')
    or os.path.join(WORKSPACE, 'examples', 'intelligence', 'sample-data')
)

# Minimum sellable brief bar for delivery/money paths.
MIN_WORDS = 200
TARGET_WORDS = 400
MIN_DISTINCT_SOURCES = 5
TARGET_DISTINCT_SOURCES = 6
MIN_FINDINGS = 4
FRESH_FINDING_WINDOW_DAYS = 14
MIN_FRESH_FINDINGS = 2


def load_text(path: str) -> str:
    with open(path) as f:
        return f.read()


def parse_iso_date(text: str) -> dt.date | None:
    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if not match:
        return None
    try:
        return dt.date.fromisoformat(match.group(1))
    except ValueError:
        return None


def detect_date_from_path(path: str) -> dt.date | None:
    return parse_iso_date(os.path.basename(path))


def count_words(text: str) -> int:
    return len(re.findall(r"\b\S+\b", text))


def extract_sources(text: str) -> list[str]:
    sources: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        lo = stripped.lower()
        if not any(token in lo for token in ("source", "source url")):
            continue
        if ":" not in stripped:
            continue
        if (
            lo.startswith("- *source*:")
            or lo.startswith("*source*:")
            or lo.startswith("- source:")
            or lo.startswith("source:")
            or lo.startswith("- **source:**")
            or lo.startswith("**source:**")
            or lo.startswith("- **source url:**")
            or lo.startswith("**source url:**")
            or lo.startswith("- source url:")
            or lo.startswith("source url:")
        ):
            sources.append(stripped.split(":", 1)[1].strip())
    return [s for s in sources if s]


def extract_findings_count(brief_text: str) -> int:
    count = 0
    for line in brief_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- **"):
            continue
        if stripped.lower().startswith("- **action items"):
            continue
        if stripped.lower().startswith("- **risk to watch"):
            continue
        count += 1
    return count


def has_action_items(brief_text: str) -> bool:
    return "**Action Items**" in brief_text or "Action Items:" in brief_text


def has_risk_watch(brief_text: str) -> bool:
    patterns = (
        "**Risk to Watch**",
        "Risk to Watch:",
        "**Risk Watch**",
        "Risk Watch:",
    )
    return any(p in brief_text for p in patterns)


def has_headline(brief_text: str) -> bool:
    first_nonempty = next((line.strip() for line in brief_text.splitlines() if line.strip()), "")
    return first_nonempty.startswith("**") and first_nonempty.endswith("**")


def resolve_findings_path(brief_path: str, findings_path: str | None) -> str | None:
    if findings_path:
        return findings_path if os.path.exists(findings_path) else None
    brief_date = detect_date_from_path(brief_path)
    if not brief_date:
        return None
    candidate = os.path.join(ARTIFACT_DIR, f"findings-{brief_date.isoformat()}.md")
    if os.path.exists(candidate):
        return candidate
    findings = sorted(glob.glob(os.path.join(ARTIFACT_DIR, "findings-*.md")))
    return findings[-1] if findings else None


def _assess(brief_text: str, brief_date: dt.date, findings_text: str = "") -> dict[str, Any]:
    word_count = count_words(brief_text)
    brief_sources = set(extract_sources(brief_text))
    findings_sources = set(extract_sources(findings_text))
    distinct_sources = max(len(brief_sources), len(findings_sources))
    findings_count = extract_findings_count(brief_text)

    findings_dates: list[str] = []
    stale_dates: list[str] = []
    fresh_dates: list[str] = []
    for line in findings_text.splitlines():
        stripped = line.strip()
        lo = stripped.lower()
        if not stripped.startswith("-"):
            continue
        if not any(token in lo for token in ("recency", "date", "observed")):
            continue
        parsed = parse_iso_date(stripped)
        if not parsed:
            continue
        findings_dates.append(parsed.isoformat())
        age_days = (brief_date - parsed).days
        if age_days <= FRESH_FINDING_WINDOW_DAYS:
            fresh_dates.append(parsed.isoformat())
        else:
            stale_dates.append(parsed.isoformat())

    checks = {
        "headline_present": has_headline(brief_text),
        "minimum_words": word_count >= MIN_WORDS,
        "minimum_distinct_sources": distinct_sources >= MIN_DISTINCT_SOURCES,
        "minimum_findings": findings_count >= MIN_FINDINGS,
        "has_action_items": has_action_items(brief_text),
        "has_risk_watch": has_risk_watch(brief_text),
        "findings_recency_ok": len(fresh_dates) >= MIN_FRESH_FINDINGS,
    }

    failures: list[str] = []
    if not checks["headline_present"]:
        failures.append("missing headline")
    if not checks["minimum_words"]:
        failures.append(f"under {MIN_WORDS} words ({word_count})")
    if not checks["minimum_distinct_sources"]:
        failures.append(f"fewer than {MIN_DISTINCT_SOURCES} distinct sources ({distinct_sources})")
    if not checks["minimum_findings"]:
        failures.append(f"fewer than {MIN_FINDINGS} findings ({findings_count})")
    if not checks["has_action_items"]:
        failures.append("missing Action Items section")
    if not checks["has_risk_watch"]:
        failures.append("missing Risk Watch section")
    if not checks["findings_recency_ok"]:
        if findings_dates:
            failures.append(
                f"fewer than {MIN_FRESH_FINDINGS} findings within {FRESH_FINDING_WINDOW_DAYS} days "
                f"({len(fresh_dates)} fresh)"
            )
        else:
            failures.append("no parseable findings recency evidence")

    warnings: list[str] = []
    if word_count < TARGET_WORDS:
        warnings.append(f"below target {TARGET_WORDS} words ({word_count})")
    if distinct_sources < TARGET_DISTINCT_SOURCES:
        warnings.append(f"below target {TARGET_DISTINCT_SOURCES} distinct sources ({distinct_sources})")
    if stale_dates:
        warnings.append(
            f"contains older context findings outside {FRESH_FINDING_WINDOW_DAYS}-day fresh window "
            f"({', '.join(stale_dates)})"
        )

    return {
        "brief_date": brief_date.isoformat(),
        "word_count": word_count,
        "distinct_sources": distinct_sources,
        "findings_count": findings_count,
        "findings_dates": findings_dates,
        "fresh_dates": fresh_dates,
        "stale_dates": stale_dates,
        "checks": checks,
        "pass": len(failures) == 0,
        "passed": len(failures) == 0,
        "failures": failures,
        "warnings": warnings,
    }


def assess_brief_content(content: str, brief_date: str | None = None) -> dict[str, Any]:
    parsed_brief_date = parse_iso_date(brief_date or "") or dt.date.today()
    findings_text = ""
    if brief_date:
        findings_path = os.path.join(ARTIFACT_DIR, f"findings-{parsed_brief_date.isoformat()}.md")
        if os.path.exists(findings_path):
            findings_text = load_text(findings_path)
    return _assess(content, parsed_brief_date, findings_text=findings_text)


def analyze_brief(brief_path: str, findings_path: str | None = None) -> dict[str, Any]:
    brief_text = load_text(brief_path)
    resolved_findings_path = resolve_findings_path(brief_path, findings_path)
    findings_text = load_text(resolved_findings_path) if resolved_findings_path else ""
    brief_date = detect_date_from_path(brief_path) or dt.date.today()
    result = _assess(brief_text, brief_date, findings_text=findings_text)
    result["brief_path"] = brief_path
    result["findings_path"] = resolved_findings_path
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate brief quality")
    parser.add_argument("--brief", required=True, help="Brief markdown file")
    parser.add_argument("--findings", default=None, help="Optional findings markdown file")
    parser.add_argument("--json", action="store_true", help="Print JSON")
    args = parser.parse_args()

    if not os.path.exists(args.brief):
        print(f"ERROR: brief not found: {args.brief}", file=sys.stderr)
        return 2

    result = analyze_brief(args.brief, args.findings)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status = "PASS" if result["pass"] else "FAIL"
        print(f"{status}: {os.path.basename(result['brief_path'])}")
        print(f"  words={result['word_count']} sources={result['distinct_sources']} findings={result['findings_count']}")
        if result["failures"]:
            for failure in result["failures"]:
                print(f"  - {failure}")

    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
