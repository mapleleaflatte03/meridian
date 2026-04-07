#!/usr/bin/env python3
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


def check_page(page_path: Path, required_tokens: Dict[str, List[str]], errors: List[str]) -> None:
    if not page_path.exists():
        errors.append(f"missing page: {page_path.name}")
        return
    content = page_path.read_text(encoding="utf-8")
    for token in required_tokens.get("header", []):
        if token not in content:
            errors.append(f"{page_path.name}: missing header token `{token}`")
    for token in required_tokens.get("footer", []):
        if token not in content:
            errors.append(f"{page_path.name}: missing footer token `{token}`")
    intro_tokens = required_tokens.get("intro", [])
    for token in intro_tokens:
        if token not in content:
            errors.append(f"{page_path.name}: missing intro token `{token}`")

    has_intro_shell = ('class="page-intro"' in content) or ('class="hero-lockup"' in content)
    if not has_intro_shell:
        errors.append(
            f"{page_path.name}: missing page intro shell (expected page-intro or hero-lockup)"
        )


def run(contract_path: Path, output: str) -> int:
    contract = load_json(contract_path)
    base = contract_path.parent
    errors: List[str] = []

    assets = contract.get("canonical_assets", {})
    for relpath in assets.values():
        check_asset(base, relpath, errors)

    required_tokens = contract.get("required_tokens", {})
    pages = contract.get("public_pages", [])
    for page in pages:
        check_page(base / page, required_tokens, errors)

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
