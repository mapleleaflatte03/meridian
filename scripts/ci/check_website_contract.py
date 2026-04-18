#!/usr/bin/env python3
"""Website contract gate — outcome-based, not anatomy-based.

Derives from docs/PRODUCT_SURFACE_ACCEPTANCE_CONTRACT.md rules W1-W7.

For every HTML file in ``intelligence/company/www/``:
  W1. shared shell: <!doctype html>, <html lang="en">, viewport meta,
      <header>, <footer>, loads /assets/meridian.css exactly once.
  W2. banned legacy commercial wording absent on every page.

For ``index.html`` specifically:
  W3. exactly one <h1>; at least one href="/pilot"; mentions Core, Team,
      and some "local" wording; body size < 60 KB (focus ceiling).
  W4. no form action pointing at /api/subscriptions/... or
      /api/institution/license/...; no pricing/checkout class tokens.

For ``proofs.html``:
  W5. <title> contains "Proof"; references /api/runtime-proof or
      /api/kernel-proof-bundle.

For ``workflows.html``:
  W6. <title> contains "Workflow"; references /api/workflows/showcase.

Production failure classes prevented:
  * Homepage creep into a warehouse section-inventory.
  * Silent re-introduction of retired commercial/paywall wording.
  * Proofs/workflows pages losing their identifying content.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
WWW = ROOT / "intelligence" / "company" / "www"

BANNED_COMMERCIAL = (
    "Constitutional Institution License",
    "Get License",
    "$299",
    "$79",
    "checkout-capture",
    "manual pilot",
)

BANNED_CLASS_TOKENS = (
    "pricing-grid",
    "price-card",
    "pricing-section",
    "checkout-card",
    "checkout-section",
    "premium-pricing",
)

HOMEPAGE_SIZE_CEILING_BYTES = 60 * 1024  # W3 focus ceiling


def check_shared_shell(path: pathlib.Path, body: str, errors: list[str]) -> None:
    rel = path.relative_to(ROOT)
    if "<!doctype html>" not in body.lower():
        errors.append(f"{rel}: missing <!doctype html>")
    if not re.search(r'<html\s+lang="en"', body, flags=re.IGNORECASE):
        errors.append(f"{rel}: missing <html lang=\"en\">")
    if not re.search(r'name="viewport"', body):
        errors.append(f"{rel}: missing viewport meta")
    if not re.search(r"<header[\s>]", body, flags=re.IGNORECASE):
        errors.append(f"{rel}: missing <header>")
    if not re.search(r"<footer[\s>]", body, flags=re.IGNORECASE):
        errors.append(f"{rel}: missing <footer>")
    css_refs = re.findall(r"/assets/meridian\.css", body)
    if len(css_refs) == 0:
        errors.append(f"{rel}: missing /assets/meridian.css reference")
    elif len(css_refs) > 1:
        errors.append(
            f"{rel}: /assets/meridian.css referenced {len(css_refs)}x (expected 1)"
        )


def check_banned_commercial(path: pathlib.Path, body: str, errors: list[str]) -> None:
    rel = path.relative_to(ROOT)
    for banned in BANNED_COMMERCIAL:
        if banned in body:
            errors.append(f"{rel}: banned commercial wording present: {banned!r}")


def check_homepage_focus(path: pathlib.Path, body: str, errors: list[str]) -> None:
    rel = path.relative_to(ROOT)
    size = len(body.encode("utf-8"))
    if size >= HOMEPAGE_SIZE_CEILING_BYTES:
        errors.append(
            f"{rel}: {size} bytes exceeds focus ceiling "
            f"{HOMEPAGE_SIZE_CEILING_BYTES} — homepage is drifting toward warehouse"
        )
    h1_count = len(re.findall(r"<h1[\s>]", body, flags=re.IGNORECASE))
    if h1_count != 1:
        errors.append(f"{rel}: must have exactly one <h1>, found {h1_count}")
    if not re.search(r'href="/pilot"', body):
        errors.append(f"{rel}: missing install path href=\"/pilot\"")
    if not re.search(r"\bCore\b", body):
        errors.append(f"{rel}: must mention Core")
    if not re.search(r"\bTeam\b", body):
        errors.append(f"{rel}: must mention Team")
    if not re.search(r"local", body, flags=re.IGNORECASE):
        errors.append(f"{rel}: must reference local-first runtime")


def check_homepage_banned_reintroductions(
    path: pathlib.Path, body: str, errors: list[str]
) -> None:
    rel = path.relative_to(ROOT)
    # Forms pointed at retired funnels
    for pat in (
        r'<form[^>]*action="/api/subscriptions/',
        r'<form[^>]*action="/api/institution/license/',
    ):
        if re.search(pat, body, flags=re.IGNORECASE):
            errors.append(f"{rel}: form pointed at retired commercial endpoint: {pat}")
    for attr in ("data-paywall", "data-checkout"):
        if attr in body:
            errors.append(f"{rel}: retired attribute present: {attr}")
    for cls in BANNED_CLASS_TOKENS:
        if cls in body:
            errors.append(f"{rel}: retired class token present: {cls}")


def check_proofs(path: pathlib.Path, body: str, errors: list[str]) -> None:
    rel = path.relative_to(ROOT)
    title_match = re.search(r"<title>([^<]*)</title>", body, flags=re.IGNORECASE)
    title = (title_match.group(1) if title_match else "")
    if "proof" not in title.lower():
        errors.append(f"{rel}: <title> must mention Proof (got {title!r})")
    if "/api/runtime-proof" not in body and "/api/kernel-proof-bundle" not in body:
        errors.append(
            f"{rel}: must reference /api/runtime-proof or /api/kernel-proof-bundle"
        )


def check_workflows(path: pathlib.Path, body: str, errors: list[str]) -> None:
    rel = path.relative_to(ROOT)
    title_match = re.search(r"<title>([^<]*)</title>", body, flags=re.IGNORECASE)
    title = (title_match.group(1) if title_match else "")
    if "workflow" not in title.lower():
        errors.append(f"{rel}: <title> must mention Workflow (got {title!r})")
    if "/api/workflows/showcase" not in body:
        errors.append(f"{rel}: must reference /api/workflows/showcase")


def main() -> int:
    if not WWW.is_dir():
        sys.stderr.write(f"missing www directory: {WWW}\n")
        return 2

    errors: list[str] = []
    files_scanned = 0
    for html in sorted(WWW.rglob("*.html")):
        if not html.is_file():
            continue
        files_scanned += 1
        body = html.read_text(encoding="utf-8", errors="replace")
        check_shared_shell(html, body, errors)
        check_banned_commercial(html, body, errors)
        if html.name == "index.html":
            check_homepage_focus(html, body, errors)
            check_homepage_banned_reintroductions(html, body, errors)
        elif html.name == "proofs.html":
            check_proofs(html, body, errors)
        elif html.name == "workflows.html":
            check_workflows(html, body, errors)

    if errors:
        sys.stderr.write(
            f"[website-contract] FAIL files_scanned={files_scanned} "
            f"errors={len(errors)}\n"
        )
        for err in errors:
            sys.stderr.write(f"  {err}\n")
        sys.stderr.write(
            "See docs/PRODUCT_SURFACE_ACCEPTANCE_CONTRACT.md for rules W1-W7.\n"
        )
        return 1

    sys.stdout.write(
        f"[website-contract] ok files_scanned={files_scanned}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
