#!/usr/bin/env python3
"""Fail CI if any runtime-facing HTML references a stale asset marker.

Every HTML file under intelligence/company/www/ must reference
`/assets/meridian.css?v=<canonical>` and `/assets/meridian.js?v=<canonical>`
where <canonical> is the value in intelligence/company/www/.asset-version.

This gate prevents the exact production failure class where a source bump
(e.g. v=20260408-oss11 -> v=20260418-oss12) lands in some HTML files but
not others, leaving live browsers on mixed/stale cache entries and breaking
CSS/JS contracts without a crash the operator would notice.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
WWW = ROOT / "intelligence" / "company" / "www"
VERSION_FILE = WWW / ".asset-version"
ASSET_MARKER = re.compile(r"/assets/meridian\.(?:css|js)\?v=([0-9A-Za-z-]+)")


def canonical_version() -> str:
    if not VERSION_FILE.exists():
        sys.stderr.write(f"missing canonical version file: {VERSION_FILE}\n")
        sys.exit(2)
    value = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not value:
        sys.stderr.write(f"canonical version file is empty: {VERSION_FILE}\n")
        sys.exit(2)
    return value


def scan() -> int:
    canonical = canonical_version()
    failures: list[tuple[pathlib.Path, str]] = []
    files_scanned = 0
    for html in sorted(WWW.rglob("*.html")):
        if not html.is_file():
            continue
        files_scanned += 1
        text = html.read_text(encoding="utf-8", errors="replace")
        versions = set(ASSET_MARKER.findall(text))
        for seen in sorted(versions):
            if seen != canonical:
                failures.append((html.relative_to(ROOT), seen))
    if failures:
        sys.stderr.write(
            f"[asset-version] canonical={canonical} "
            f"stale_markers={len(failures)} files_scanned={files_scanned}\n"
        )
        for path, seen in failures:
            sys.stderr.write(f"  STALE: {path} references v={seen}\n")
        sys.stderr.write(
            "Fix: update the stale files to the canonical version, or bump "
            f"{VERSION_FILE.relative_to(ROOT)} and all HTML together.\n"
        )
        return 1
    sys.stdout.write(
        f"[asset-version] ok canonical={canonical} files_scanned={files_scanned}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(scan())
