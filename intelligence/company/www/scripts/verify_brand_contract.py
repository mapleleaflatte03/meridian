#!/usr/bin/env python3
"""Verify the Meridian brand contract v1 — minimal structural truth.

Contract shape (intelligence/company/www/brand_contract_v1.json):
  * canonical_assets: dict of logical name -> relative path. Each path
    must exist and be non-empty on disk.
  * public_pages: list of HTML filenames. Each must exist and include
    every pattern in ``shared_shell_required_patterns``.
  * shared_shell_required_patterns: substrings that must appear in every
    public page (shared shell truth: <header>, <footer>, viewport meta,
    canonical stylesheet, brand identity text).

This verifier does NOT enforce section IDs, component class tokens, or
product copy. Those belong to the outcome-based website contract gate —
see docs/PRODUCT_SURFACE_ACCEPTANCE_CONTRACT.md.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List


def load_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_asset(base: Path, relpath: str, errors: List[str]) -> None:
    target = base / relpath
    if not target.exists():
        errors.append(f"missing asset: {relpath}")
        return
    if target.stat().st_size == 0:
        errors.append(f"empty asset: {relpath}")


def check_page(page_path: Path, required_patterns: List[str], errors: List[str]) -> None:
    if not page_path.exists():
        errors.append(f"missing page: {page_path.name}")
        return
    content = page_path.read_text(encoding="utf-8")
    for pattern in required_patterns:
        if pattern not in content:
            errors.append(f"{page_path.name}: missing shared-shell pattern `{pattern}`")


def run(contract_path: Path, output: str) -> int:
    contract = load_json(contract_path)
    base = contract_path.parent
    errors: List[str] = []

    for relpath in (contract.get("canonical_assets") or {}).values():
        check_asset(base, relpath, errors)

    required_patterns: List[str] = list(contract.get("shared_shell_required_patterns") or [])
    pages = contract.get("public_pages") or []
    for page in pages:
        check_page(base / page, required_patterns, errors)

    payload = {
        "schema_version": contract.get("schema_version", "unknown"),
        "status": "pass" if not errors else "fail",
        "contract_path": str(contract_path),
        "checked_pages": len(pages),
        "errors": errors,
    }
    if output == "json":
        print(json.dumps(payload, indent=2))
    else:
        print("Meridian Brand Contract")
        print("=======================")
        print(f"schema_version: {payload['schema_version']}")
        print(f"contract_path:  {payload['contract_path']}")
        print(f"checked_pages:  {payload['checked_pages']}")
        print(f"status:         {payload['status']}")
        if errors:
            print("errors:")
            for error in errors:
                print(f"- {error}")

    return 0 if not errors else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Meridian brand contract v1 across public pages."
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "brand_contract_v1.json",
        help="Path to brand contract JSON",
    )
    parser.add_argument(
        "--output",
        choices=["human", "json"],
        default="human",
        help="Output format",
    )
    args = parser.parse_args()
    return run(args.contract.resolve(), args.output)


if __name__ == "__main__":
    raise SystemExit(main())
