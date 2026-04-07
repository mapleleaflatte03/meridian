#!/usr/bin/env python3
"""
Lightweight CLI cold-start benchmark for Meridian Loom and adjacent runtimes.

Measures wall-clock time plus an approximate peak RSS for short-lived commands.
This is intentionally a simple reproducible harness, not a lab-grade benchmark.
"""

from __future__ import annotations

import argparse
import math
import shlex
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class Sample:
    wall_ms: float
    peak_rss_kib: int
    returncode: int


@dataclass
class CaseResult:
    name: str
    command: str
    samples: list[Sample]

    @property
    def mean_ms(self) -> float:
        return statistics.fmean(sample.wall_ms for sample in self.samples)

    @property
    def p95_ms(self) -> float:
        ordered = sorted(sample.wall_ms for sample in self.samples)
        if not ordered:
            return 0.0
        index = max(0, math.ceil(len(ordered) * 0.95) - 1)
        return ordered[index]

    @property
    def peak_rss_kib(self) -> int:
        return max((sample.peak_rss_kib for sample in self.samples), default=0)

    @property
    def exit_codes(self) -> str:
        return ",".join(str(sample.returncode) for sample in self.samples)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark short-lived CLI commands for cold start time and peak RSS."
    )
    parser.add_argument(
        "--case",
        action="append",
        required=True,
        help='Benchmark case in the form "name::command". Repeat for multiple binaries.',
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Measured iterations per case (default: 5).",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="Warmup iterations per case before measurement (default: 1).",
    )
    parser.add_argument(
        "--poll-ms",
        type=float,
        default=10.0,
        help="RSS sampling interval in milliseconds (default: 10).",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format (default: markdown).",
    )
    return parser.parse_args()


def parse_case(raw: str) -> tuple[str, str]:
    if "::" not in raw:
        raise SystemExit(f"invalid --case '{raw}' (expected name::command)")
    name, command = raw.split("::", 1)
    name = name.strip()
    command = command.strip()
    if not name or not command:
        raise SystemExit(f"invalid --case '{raw}' (name and command are both required)")
    return name, command


def sample_rss_kib(pid: int) -> int:
    proc_status = Path(f"/proc/{pid}/status")
    if proc_status.exists():
        try:
            for line in proc_status.read_text(encoding="utf-8").splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
        except OSError:
            return 0
    try:
        output = subprocess.check_output(
            ["ps", "-o", "rss=", "-p", str(pid)],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return int(output.strip() or "0")
    except Exception:
        return 0


def run_once(command: str, poll_ms: float) -> Sample:
    start = time.perf_counter()
    proc = subprocess.Popen(
        shlex.split(command),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=False,
    )
    peak_rss = 0
    while True:
        returncode = proc.poll()
        peak_rss = max(peak_rss, sample_rss_kib(proc.pid))
        if returncode is not None:
            break
        time.sleep(poll_ms / 1000.0)
    wall_ms = (time.perf_counter() - start) * 1000.0
    return Sample(wall_ms=wall_ms, peak_rss_kib=peak_rss, returncode=proc.returncode or 0)


def benchmark_case(name: str, command: str, warmup: int, iterations: int, poll_ms: float) -> CaseResult:
    for _ in range(warmup):
        run_once(command, poll_ms)
    samples = [run_once(command, poll_ms) for _ in range(iterations)]
    return CaseResult(name=name, command=command, samples=samples)


def render_markdown(results: Iterable[CaseResult]) -> str:
    lines = [
        "| Case | Command | Mean cold start (ms) | p95 (ms) | Peak RSS (MiB) | Exit codes |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for result in results:
        lines.append(
            "| {name} | `{command}` | {mean:.1f} | {p95:.1f} | {rss:.1f} | `{codes}` |".format(
                name=result.name,
                command=result.command,
                mean=result.mean_ms,
                p95=result.p95_ms,
                rss=result.peak_rss_kib / 1024.0,
                codes=result.exit_codes,
            )
        )
    return "\n".join(lines) + "\n"


def render_json(results: Iterable[CaseResult]) -> str:
    import json

    payload = []
    for result in results:
        payload.append(
            {
                "name": result.name,
                "command": result.command,
                "mean_ms": round(result.mean_ms, 3),
                "p95_ms": round(result.p95_ms, 3),
                "peak_rss_kib": result.peak_rss_kib,
                "exit_codes": [sample.returncode for sample in result.samples],
            }
        )
    return json.dumps(payload, indent=2) + "\n"


def main() -> int:
    args = parse_args()
    results = []
    for raw_case in args.case:
        name, command = parse_case(raw_case)
        results.append(
            benchmark_case(name, command, args.warmup, args.iterations, args.poll_ms)
        )
    sys.stdout.write(render_json(results) if args.format == "json" else render_markdown(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
