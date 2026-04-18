#!/usr/bin/env python3
"""README contract gate — doorway ordering, not warehouse inventory.

Derives from docs/PRODUCT_SURFACE_ACCEPTANCE_CONTRACT.md rules R1-R3.

The README must be a front door: identity → install → onboarding →
Core/Team distinction → first commands. No gallery, no benchmark wall,
no dev-maintenance clutter before the first-success path.

Failure classes prevented:
  * README becoming a warehouse (long sections before first use).
  * README losing the doorway (install/onboarding buried).
  * Commercial wording re-drift (same banned list as website).
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
README = ROOT / "README.md"

# Same banned list as website contract
BANNED_COMMERCIAL = (
    "Constitutional Institution License",
    "Get License",
    "$299",
    "$79",
    "checkout-capture",
    "manual pilot",
)

# Forbidden early-section headings (must not appear in first 120 non-blank lines)
FORBIDDEN_EARLY_HEADINGS = (
    "quick visuals",
    "gallery",
    "screenshots",
    "benchmarks",
    "benchmark",
    "migration",
    "dev and maintenance",
    "developer commands",
    "governance, benchmark, and migration",
)

# Maximum lines to scan for doorway ordering
DOORWAY_LINE_LIMIT = 120


def get_non_blank_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


def check_doorway_ordering(text: str, errors: list[str]) -> None:
    """R1: Identity → Install → Onboarding → Core/Team → First commands."""
    lines = get_non_blank_lines(text)
    scan = "\n".join(lines[:DOORWAY_LINE_LIMIT]).lower()

    # 1. Identity: "Meridian" must appear near the top (in first 10 non-blank lines)
    early_scan = "\n".join(lines[:10]).lower()
    if "meridian" not in early_scan:
        errors.append("R1: 'Meridian' identity not found in first 10 lines")

    # 2. Install: must have install-full.sh or curl-to-install pattern
    has_install_block = "install-full.sh" in scan or re.search(
        r'curl.*install.*\.sh', scan
    )
    if not has_install_block:
        errors.append("R1: Install command (install-full.sh or curl-to-install) not found in first 120 lines")

    # 3. Onboarding: must reference ./scripts/onboard.sh
    if "./scripts/onboard.sh" not in scan:
        errors.append("R1: Onboarding command (./scripts/onboard.sh) not found in first 120 lines")

    # 4. Core/Team distinction: both tokens must appear
    has_core = re.search(r'\bcore\b', scan) is not None
    has_team = re.search(r'\bteam\b', scan) is not None
    if not has_core:
        errors.append("R1: 'Core' token not found in first 120 lines (needs Core/Team distinction)")
    if not has_team:
        errors.append("R1: 'Team' token not found in first 120 lines (needs Core/Team distinction)")

    # 5. First commands: heading or section with executable snippet
    first_commands_pattern = re.search(
        r'^(#{1,3}\s*(first commands|first use|first success|quick start|getting started))',
        "\n".join(lines[:DOORWAY_LINE_LIMIT]),
        re.MULTILINE | re.IGNORECASE
    )
    has_code_after = False
    if first_commands_pattern:
        # Check there's a code block after this heading
        heading_pos = first_commands_pattern.start()
        after_heading = "\n".join(lines[:DOORWAY_LINE_LIMIT])[heading_pos:heading_pos+500]
        has_code_after = "```" in after_heading
    else:
        # Alternative: any fenced code block containing core.sh commands
        has_code_after = re.search(r'```.*\n\./scripts/core\.sh', scan, re.MULTILINE) is not None

    if not first_commands_pattern and not has_code_after:
        errors.append("R1: 'First commands' section or executable code snippet not found in first 120 lines")


def check_section_ordering(text: str, errors: list[str]) -> None:
    """R2: Doorway sections must come before warehouse sections.
    
    The README must present these in order before any forbidden sections:
    1. Identity (Meridian mention)
    2. Install
    3. Onboarding
    4. First commands
    
    Forbidden sections (gallery, benchmark, migration, dev-maintenance) must NOT
    appear as the 2nd, 3rd, or 4th section.
    """
    # Find all level-2 headings (## Heading)
    heading_pattern = re.compile(r'^##\s+(.+)$', re.MULTILINE | re.IGNORECASE)
    headings = [m.group(1).strip() for m in heading_pattern.finditer(text)]
    
    if len(headings) < 4:
        errors.append("R2: README has fewer than 4 sections; cannot verify doorway ordering")
        return
    
    # Map headings to their position (1-indexed for clarity)
    heading_positions = {h.lower(): i+1 for i, h in enumerate(headings)}
    
    # Find position of doorway markers
    install_pos = heading_positions.get('install', 999)
    onboarding_pos = heading_positions.get('onboarding', 999)
    first_commands_pos = None
    for h in headings:
        hl = h.lower()
        if hl in ('first commands', 'first use', 'first success', 'quick start', 'getting started'):
            first_commands_pos = heading_positions[hl]
            break
    
    # Check doorway sections come early (within first 5 sections)
    if install_pos > 5:
        errors.append(f"R2: 'Install' section is #{install_pos}, should be within first 5 sections")
    if onboarding_pos > 5:
        errors.append(f"R2: 'Onboarding' section is #{onboarding_pos}, should be within first 5 sections")
    if first_commands_pos and first_commands_pos > 6:
        errors.append(f"R2: 'First commands' section is #{first_commands_pos}, should be within first 6 sections")
    
    # Check forbidden sections don't appear too early (before or as 2nd/3rd/4th)
    for heading in FORBIDDEN_EARLY_HEADINGS:
        pos = heading_positions.get(heading)
        if pos and pos <= 4:
            errors.append(
                f"R2: Forbidden heading '{heading}' is section #{pos} "
                f"(must not be 2nd, 3rd, or 4th section - README must stay a doorway)"
            )


def check_identity_truth(text: str, errors: list[str]) -> None:
    """R3: No banned commercial wording anywhere in README."""
    for banned in BANNED_COMMERCIAL:
        if banned in text:
            errors.append(f"R3: Banned commercial wording: {banned!r}")


def main() -> int:
    if not README.exists():
        sys.stderr.write(f"missing README: {README}\n")
        return 2

    text = README.read_text(encoding="utf-8", errors="replace")
    errors: list[str] = []

    check_doorway_ordering(text, errors)
    check_section_ordering(text, errors)
    check_identity_truth(text, errors)

    if errors:
        sys.stderr.write("[readme-contract] FAIL\n")
        for err in errors:
            sys.stderr.write(f"  {err}\n")
        sys.stderr.write(
            "Fix: reorder README to doorway structure (identity → install → onboarding → Core/Team → first commands)\n"
            "See docs/PRODUCT_SURFACE_ACCEPTANCE_CONTRACT.md rules R1-R3.\n"
        )
        return 1

    sys.stdout.write("[readme-contract] ok doorway=identity→install→onboarding→core/team→first-commands\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
