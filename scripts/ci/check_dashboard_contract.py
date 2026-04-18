#!/usr/bin/env python3
"""Fail CI if the workspace dashboard breaks Core/Team shell or product-quality contracts.

Shell contract (original):
  * Must contain a Core tab/panel (Core cockpit) and a Team tab/panel
    (Team governed depth) served as structural siblings, not a collapsible.
  * Must not use `<details id="team-details"` or any `<summary
    class="team-section-toggle"` toggle — Team depth is entered on purpose
    via the tab, not by expanding a disclosure widget.
  * Must expose both panels via `panel-core` and `panel-team` tabpanel ids so
    the JS setDashboardView switcher keeps working.

Product-quality contract (outcome-based, anti-clutter):
  * Exactly ONE mode-switch surface: the `role="tablist"` mode-nav. The old
    hero `mode-strip` / "Core mode Team mode" pill row must stay gone.
  * Exactly ONE Core task composer (`id="core-task-input"`) in the first fold.
  * Core first-fold copy must stay short and action-first: the Core composer
    section must not carry a long hero subtitle or the old "One product · two
    modes · one runtime truth" framing.
  * Team governed controls must not render inside panel-core (no Team
    composer/authority/treasury ids leaking into the Core panel).
  * The primary `#status-bar` render code must emit at most 3 chips at
    initial render (Runtime / Actor / Treasury). Secondary status moves to
    `#signals-overview` below the fold.

Production failure class this prevents:
  - Silent regression back to a Team-collapsible Core shell where governance
    spam leaks into the daily cockpit.
  - Re-introduction of the "badge cemetery" primary status bar.
  - Duplicate mode-switch surfaces (hero pills + tabs).
  - Hero subtitle drift on Core first fold.
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
    'id="panel-core"',
    'id="panel-team"',
    'id="tab-core"',
    'id="tab-team"',
    'role="tablist"',
    'id="core-task-input"',
    'id="status-bar"',
    'id="signals-overview"',
)

SHELL_FORBIDDEN = (
    '<details id="team-details"',
    'class="h2 team-section-toggle"',
    'class="team-section-toggle"',
)

# Clutter patterns that must not reappear.
CLUTTER_FORBIDDEN = (
    # Hero pill duplicate of the tab switcher.
    'id="mode-strip"',
    'class="mode-strip"',
    # Old hero framing that crowded the first fold.
    "One product · two modes · one runtime truth",
    "One product &middot; two modes &middot; one runtime truth",
)


def _find_panel(html: str, panel_id: str) -> str:
    """Return the inner HTML of `<section id="panel-X" ...> ... </section>`.

    Uses a brace-counter across nested <section>…</section> so we capture the
    full panel body, not just up to the first closing </section>.
    """
    opener = re.search(rf'<section\s+id="{panel_id}"[^>]*>', html)
    if not opener:
        return ""
    start = opener.end()
    depth = 1
    i = start
    section_re = re.compile(r'<section\b|</section>', re.IGNORECASE)
    while depth > 0 and i < len(html):
        m = section_re.search(html, i)
        if not m:
            break
        if m.group(0).startswith('</'):
            depth -= 1
            if depth == 0:
                return html[start:m.start()]
        else:
            depth += 1
        i = m.end()
    return html[start:]


def _check_core_composer_single(core_panel: str) -> list[str]:
    count = len(re.findall(r'id="core-task-input"', core_panel))
    if count != 1:
        return [f"Core panel must contain exactly one #core-task-input composer; found {count}"]
    return []


def _check_no_team_leakage_in_core(core_panel: str) -> list[str]:
    bad_ids = ['id="task-agent"', 'id="task-description"', 'id="task-amount"',
               'id="treasury-card"', 'id="authority-section"', 'id="court-section"',
               'id="ci-card"']
    leaks = [tok for tok in bad_ids if tok in core_panel]
    return [f"Team control id leaked into panel-core: {t}" for t in leaks]


_STATUS_BAR_RENDER_RE = re.compile(
    r"var\s+primary\s*=\s*''\s*;(?P<body>.*?)document\.getElementById\('status-bar'\)\.innerHTML\s*=\s*primary\s*;",
    re.DOTALL,
)


def _check_primary_status_bar_chip_cap(source: str) -> list[str]:
    """The primary #status-bar render block must emit ≤3 chips."""
    m = _STATUS_BAR_RENDER_RE.search(source)
    if not m:
        return [
            "Primary status-bar render block not found; expected a "
            "`var primary = ''; …; document.getElementById('status-bar').innerHTML = primary;` block",
        ]
    body = m.group("body")
    chip_count = len(re.findall(r"primary\s*\+=\s*'<span class=\"item\">", body))
    if chip_count > 3:
        return [f"Primary status-bar first-fold chip count must be ≤3; found {chip_count}"]
    if chip_count == 0:
        return ["Primary status-bar produced 0 chips — confidence signal missing"]
    return []


def _check_team_kicker_present(html: str) -> list[str]:
    # Accept either "Team governed depth" (old heading) or "Team · governed depth" kicker.
    if "Team governed depth" in html or "Team · governed depth" in html:
        return []
    return ["Team panel must state its depth purpose (kicker or heading containing 'governed depth')"]


def main() -> int:
    if not WORKSPACE.exists():
        sys.stderr.write(f"missing workspace: {WORKSPACE}\n")
        return 2
    source = WORKSPACE.read_text(encoding="utf-8")
    html = extract_dashboard_html(source)
    if html is None:
        sys.stderr.write("DASHBOARD_HTML not found in workspace.py\n")
        return 2

    failures: list[str] = []

    for token in REQUIRED:
        if token not in html:
            failures.append(f"MISSING required marker: {token!r}")
    for token in SHELL_FORBIDDEN:
        if token in html:
            failures.append(f"FORBIDDEN shell marker present: {token!r}")
    for token in CLUTTER_FORBIDDEN:
        if token in html:
            failures.append(f"FORBIDDEN clutter pattern present: {token!r}")

    # Exactly one mode-switch surface.
    tablist_count = len(re.findall(r'role="tablist"', html))
    if tablist_count != 1:
        failures.append(f"Expected exactly one role=\"tablist\" mode switcher; found {tablist_count}")

    core_panel = _find_panel(html, "panel-core")
    if not core_panel:
        failures.append("Could not locate panel-core body")
    else:
        failures.extend(_check_core_composer_single(core_panel))
        failures.extend(_check_no_team_leakage_in_core(core_panel))

    failures.extend(_check_team_kicker_present(html))
    failures.extend(_check_primary_status_bar_chip_cap(source))

    if failures:
        sys.stderr.write("[dashboard-contract] FAIL\n")
        for f in failures:
            sys.stderr.write(f"  {f}\n")
        sys.stderr.write(
            "Fix: keep Core composer first-fold, one tab-based mode switch, "
            "≤3 primary status chips; demote secondary signals to "
            "#signals-overview; keep Team controls inside panel-team.\n"
        )
        return 1

    sys.stdout.write(
        "[dashboard-contract] ok "
        "core=panel-core team=panel-team "
        "one-mode-switcher=tablist "
        "one-core-composer=core-task-input "
        "primary-chips<=3\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
