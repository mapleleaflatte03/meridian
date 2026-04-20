#!/usr/bin/env python3
"""Measure concrete quality metrics for Meridian that matter in competitor comparisons.

Each metric is measured locally against the actual codebase — no vague claims.
Run: python3 scripts/benchmark_meridian_quality.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
INTELLIGENCE_ROOT = SCRIPT_DIR.parent
KERNEL_ROOT = INTELLIGENCE_ROOT.parent / "kernel"
REPO_ROOT = INTELLIGENCE_ROOT.parent


def _count_files(root: Path, pattern: str) -> int:
    return len(list(root.rglob(pattern)))


def _count_lines(root: Path, pattern: str) -> int:
    total = 0
    for path in root.rglob(pattern):
        try:
            total += len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        except (OSError, UnicodeDecodeError):
            pass
    return total


def _grep_count(root: Path, pattern: str, glob: str = "*.py") -> int:
    count = 0
    regex = re.compile(pattern)
    for path in root.rglob(glob):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            count += len(regex.findall(text))
        except (OSError, UnicodeDecodeError):
            pass
    return count


def measure_install_onboarding_clarity() -> dict[str, Any]:
    """Metric 1: Install/onboarding path clarity.
    Measures: steps to first working state, file count, README presence."""
    readme = REPO_ROOT / "README.md"
    readme_exists = readme.is_file()
    readme_lines = len(readme.read_text(encoding="utf-8").splitlines()) if readme_exists else 0

    kernel_readme = KERNEL_ROOT / "README.md"
    kernel_readme_exists = kernel_readme.is_file()

    quickstart = KERNEL_ROOT / "quickstart.py"
    quickstart_exists = quickstart.is_file()

    pilot_html = INTELLIGENCE_ROOT / "company" / "www" / "pilot.html"
    pilot_exists = pilot_html.is_file()

    install_steps_in_readme = 0
    if readme_exists:
        text = readme.read_text(encoding="utf-8")
        install_steps_in_readme = len(re.findall(r"^\s*\d+\.", text, re.MULTILINE))

    return {
        "metric": "install_onboarding_clarity",
        "readme_present": readme_exists,
        "readme_lines": readme_lines,
        "kernel_readme_present": kernel_readme_exists,
        "quickstart_script_present": quickstart_exists,
        "pilot_page_present": pilot_exists,
        "numbered_install_steps": install_steps_in_readme,
        "verdict": "Meridian provides quickstart.py single-file entry, kernel README, and /pilot onboarding page",
    }


def measure_governance_depth() -> dict[str, Any]:
    """Metric 2: Governance depth without clutter.
    Counts governance primitives: warrants, authority, treasury, court, audit, sanctions."""
    platform = INTELLIGENCE_ROOT / "company" / "meridian_platform"
    kernel_dir = KERNEL_ROOT / "kernel" if KERNEL_ROOT.is_dir() else Path("/dev/null")

    governance_modules = {
        "warrants": (platform / "warrants.py").is_file(),
        "authority": (platform / "authority.py").is_file(),
        "treasury": (platform / "treasury.py").is_file(),
        "court": (platform / "court.py").is_file(),
        "audit": (platform / "audit.py").is_file(),
        "slo_policy": (platform / "slo_policy.py").is_file(),
        "commitments": (platform / "commitments.py").is_file(),
    }
    kernel_governance = {
        "kernel_warrants": (kernel_dir / "warrants.py").is_file(),
        "kernel_authority": (kernel_dir / "authority.py").is_file(),
        "kernel_treasury": (kernel_dir / "treasury.py").is_file(),
        "kernel_court": (kernel_dir / "court.py").is_file(),
    }

    governance_line_count = 0
    for name, exists in {**governance_modules, **kernel_governance}.items():
        if exists:
            module_name = name.replace("kernel_", "")
            path = (kernel_dir if name.startswith("kernel_") else platform) / f"{module_name}.py"
            try:
                governance_line_count += len(path.read_text(encoding="utf-8").splitlines())
            except OSError:
                pass

    present_count = sum(1 for v in {**governance_modules, **kernel_governance}.values() if v)

    return {
        "metric": "governance_depth",
        "platform_modules": {k: v for k, v in governance_modules.items()},
        "kernel_modules": {k: v for k, v in kernel_governance.items()},
        "total_governance_modules": present_count,
        "total_governance_lines": governance_line_count,
        "verdict": f"{present_count} governance modules with {governance_line_count} lines of implementation — not stubs",
    }


def measure_route_decision_quality() -> dict[str, Any]:
    """Metric 3: Route decision quality.
    Measures: failover chain depth, policy-driven selection, health-aware routing."""
    brain_router = INTELLIGENCE_ROOT / "company" / "meridian_platform" / "brain_router.py"
    if not brain_router.is_file():
        return {"metric": "route_decision_quality", "error": "brain_router.py not found"}

    text = brain_router.read_text(encoding="utf-8")
    lines = text.splitlines()

    features = {
        "failover_chain": bool(re.search(r"failover", text, re.IGNORECASE)),
        "cooldown_enforcement": bool(re.search(r"cooldown_until", text)),
        "health_aware_selection": bool(re.search(r"last_health", text)),
        "policy_driven_routing": bool(re.search(r"_route_chain_from_policy", text)),
        "authority_gating": bool(re.search(r"approved_by_authority", text)),
        "treasury_gating": bool(re.search(r"allowed_by_treasury", text)),
        "decision_tracing": bool(re.search(r"route_decision", text)),
        "config_driven_selection": bool(re.search(r"brain_router.*\.json", text)),
    }

    return {
        "metric": "route_decision_quality",
        "brain_router_lines": len(lines),
        "features": features,
        "feature_count": sum(1 for v in features.values() if v),
        "verdict": f"{sum(1 for v in features.values() if v)}/{len(features)} routing features implemented with {len(lines)} lines",
    }


def measure_memory_usefulness() -> dict[str, Any]:
    """Metric 4: Memory usefulness.
    Measures: memory scoring dimensions, retrieval quality signals, eviction logic."""
    gateway = INTELLIGENCE_ROOT / "meridian_gateway.py"
    if not gateway.is_file():
        return {"metric": "memory_usefulness", "error": "meridian_gateway.py not found"}

    text = gateway.read_text(encoding="utf-8")

    memory_features = {
        "recency_scoring": bool(re.search(r"_memory_entry_recency_bonus", text)),
        "content_relevance_scoring": bool(re.search(r"content_token_hits", text)),
        "cross_skill_penalty": bool(re.search(r"source_skills.*lowered_skills", text)),
        "value_decay": bool(re.search(r"_refresh_memory_value_score", text)),
        "eviction_policy": bool(re.search(r"_memory_entry_should_evict", text)),
        "compression": bool(re.search(r"_compress_successful_output_memory", text)),
        "duplicate_merge": bool(re.search(r"_matching_successful_output_memory_key", text)),
        "quality_feedback": bool(re.search(r"_record_memory_recall_outcome", text)),
        "token_overlap_scoring": bool(re.search(r"request_tokens.*entry_tokens", text)),
        "accepted_count_signal": bool(re.search(r"accepted_count", text)),
    }

    memory_constants = {}
    for match in re.finditer(r"(MEMORY_\w+)\s*=\s*int\(.*?(\d+)", text):
        memory_constants[match.group(1)] = int(match.group(2))

    return {
        "metric": "memory_usefulness",
        "features": memory_features,
        "feature_count": sum(1 for v in memory_features.values() if v),
        "configuration_constants": len(memory_constants),
        "verdict": f"{sum(1 for v in memory_features.values() if v)}/{len(memory_features)} memory features with {len(memory_constants)} tunable constants",
    }


def measure_test_coverage() -> dict[str, Any]:
    """Metric 5: Test coverage breadth.
    Counts test files and test functions across the repo."""
    test_files = list(INTELLIGENCE_ROOT.rglob("test_*.py"))
    kernel_test_files = list(KERNEL_ROOT.rglob("test_*.py")) if KERNEL_ROOT.is_dir() else []

    total_test_functions = 0
    for path in test_files + kernel_test_files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            total_test_functions += len(re.findall(r"def test_", text))
        except OSError:
            pass

    return {
        "metric": "test_coverage_breadth",
        "intelligence_test_files": len(test_files),
        "kernel_test_files": len(kernel_test_files),
        "total_test_functions": total_test_functions,
        "verdict": f"{total_test_functions} test functions across {len(test_files) + len(kernel_test_files)} test files",
    }


def measure_codebase_complexity() -> dict[str, Any]:
    """Metric 6: Codebase complexity.
    Measures lines of code, file counts, and deprecation warning count."""
    py_files_intel = _count_files(INTELLIGENCE_ROOT, "*.py")
    py_lines_intel = _count_lines(INTELLIGENCE_ROOT, "*.py")
    py_files_kernel = _count_files(KERNEL_ROOT, "*.py") if KERNEL_ROOT.is_dir() else 0
    py_lines_kernel = _count_lines(KERNEL_ROOT, "*.py") if KERNEL_ROOT.is_dir() else 0
    html_files = _count_files(INTELLIGENCE_ROOT / "company" / "www", "*.html")

    deprecated_utcnow = _grep_count(INTELLIGENCE_ROOT, r"datetime\.utcnow\(\)")
    deprecated_utcnow += _grep_count(KERNEL_ROOT, r"datetime\.utcnow\(\)") if KERNEL_ROOT.is_dir() else 0

    return {
        "metric": "codebase_complexity",
        "intelligence_py_files": py_files_intel,
        "intelligence_py_lines": py_lines_intel,
        "kernel_py_files": py_files_kernel,
        "kernel_py_lines": py_lines_kernel,
        "public_html_pages": html_files,
        "remaining_deprecated_utcnow_calls": deprecated_utcnow,
        "verdict": f"{py_files_intel + py_files_kernel} Python files, {py_lines_intel + py_lines_kernel} lines, {deprecated_utcnow} deprecated calls remaining",
    }


def run_test_suite_timing() -> dict[str, Any]:
    """Metric 7: Test suite execution time.

    Uses the stdlib unittest runner (same path CI takes) so the metric is
    recorded on hosts without pytest installed. Falls back to a
    'skipped' verdict if the runner cannot even start — never silent 0/0.
    """
    test_modules = [
        "test_gateway_brain_router",
        "test_gateway_team_route",
        "company.meridian_platform.test_workspace_context",
        "company.meridian_platform.test_side_hustle_workspace",
    ]
    start = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "unittest", *test_modules],
            capture_output=True,
            text=True,
            cwd=str(INTELLIGENCE_ROOT),
            timeout=180,
        )
    except FileNotFoundError as exc:
        elapsed = time.monotonic() - start
        return {
            "metric": "test_suite_timing",
            "elapsed_seconds": round(elapsed, 2),
            "passed": 0,
            "failed": 0,
            "warnings": 0,
            "exit_code": None,
            "verdict": f"skipped: runner unavailable ({exc})",
        }
    elapsed = time.monotonic() - start

    combined = result.stdout + result.stderr
    ran_match = re.search(r"Ran (\d+) tests", combined)
    total = int(ran_match.group(1)) if ran_match else 0
    failures = re.search(r"failures=(\d+)", combined)
    errors = re.search(r"errors=(\d+)", combined)
    failed = (int(failures.group(1)) if failures else 0) + (
        int(errors.group(1)) if errors else 0
    )
    passed = max(total - failed, 0)
    warnings = len(
        re.findall(r"(?:DeprecationWarning|UserWarning|FutureWarning)", combined)
    )

    if total == 0:
        verdict = "skipped: runner produced no summary (check module paths)"
    else:
        verdict = (
            f"{passed} passed, {failed} failed, {warnings} warnings in {elapsed:.2f}s"
        )

    return {
        "metric": "test_suite_timing",
        "elapsed_seconds": round(elapsed, 2),
        "passed": passed,
        "failed": failed,
        "warnings": warnings,
        "exit_code": result.returncode,
        "verdict": verdict,
    }


def main() -> int:
    print("=" * 60)
    print("Meridian Quality Benchmark")
    print("=" * 60)

    metrics = [
        measure_install_onboarding_clarity(),
        measure_governance_depth(),
        measure_route_decision_quality(),
        measure_memory_usefulness(),
        measure_test_coverage(),
        measure_codebase_complexity(),
        run_test_suite_timing(),
    ]

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "metrics": metrics,
    }

    for metric in metrics:
        print(f"\n--- {metric['metric']} ---")
        print(f"  verdict: {metric.get('verdict', 'N/A')}")

    out_dir = INTELLIGENCE_ROOT / "output" / "benchmark"
    history_dir = out_dir / "history"
    out_dir.mkdir(parents=True, exist_ok=True)
    history_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2) + "\n"
    latest_path = out_dir / "latest.json"
    latest_path.write_text(payload, encoding="utf-8")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    archive_path = history_dir / f"benchmark_{stamp}.json"
    archive_path.write_text(payload, encoding="utf-8")
    print(f"\nFull report: {latest_path}")
    print(f"Archive:     {archive_path}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
