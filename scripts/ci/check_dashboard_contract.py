#!/usr/bin/env python3
"""Fail CI if the workspace dashboard shell breaks the Core/Team contract.

Contract (DASHBOARD_HTML in intelligence/company/meridian_platform/workspace.py):
  * Must contain a Core tab/panel (Core cockpit) and a Team tab/panel
    (Team governed depth) served as structural siblings, not a collapsible.
  * Must not use `<details id="team-details"` (the previous cheap disclosure
    pattern) or any `<summary class="team-section-toggle"` toggle — Team depth
    is entered on purpose via the tab, not by expanding a disclosure widget.
  * Must expose both panels via `panel-core` and `panel-team` tabpanel ids so
    the JS setDashboardView switcher keeps working.

Production failure class this prevents: silent regression back to a Team-
collapsible Core shell where governance spam leaks into the daily cockpit.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "intelligence" / "company" / "meridian_platform" / "workspace.py"


def extract_dashboard_html(source: str) -> str | None:
    match = re.search(r'DASHBOARD_HTML\s*=\s*r"""(.*?)"""', source, re.DOTALL)
    return match.group(1) if match else None


REQUIRED = (
    "Core cockpit",
    "Team governed depth",
    'id="panel-core"',
    'id="panel-team"',
    'id="tab-core"',
    'id="tab-team"',
    'role="tablist"',
)

FORBIDDEN = (
    '<details id="team-details"',
    'class="h2 team-section-toggle"',
    "class=\"team-section-toggle\"",
)


def main() -> int:
    if not WORKSPACE.exists():
        sys.stderr.write(f"missing workspace: {WORKSPACE}\n")
        return 2
    source = WORKSPACE.read_text(encoding="utf-8")
    html = extract_dashboard_html(source)
    if html is None:
        sys.stderr.write("DASHBOARD_HTML not found in workspace.py\n")
        return 2

    missing = [token for token in REQUIRED if token not in html]
    leaked = [token for token in FORBIDDEN if token in html]

    if missing or leaked:
        sys.stderr.write("[dashboard-contract] FAIL\n")
        for token in missing:
            sys.stderr.write(f"  MISSING required marker: {token!r}\n")
        for token in leaked:
            sys.stderr.write(f"  FORBIDDEN marker present: {token!r}\n")
        sys.stderr.write(
            "Fix: restore Core/Team tab structure in DASHBOARD_HTML. "
            "Team depth is a tabpanel, not a disclosure widget.\n"
        )
        return 1

    sys.stdout.write("[dashboard-contract] ok core=panel-core team=panel-team\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
