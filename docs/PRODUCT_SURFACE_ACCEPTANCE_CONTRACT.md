# Meridian Product Surface Acceptance Contract

**Scope:** website (`intelligence/company/www/*.html`), root `README.md`, and the
workspace dashboard shell (`DASHBOARD_HTML` in
`intelligence/company/meridian_platform/workspace.py`).

**Purpose:** protect product quality, focus, and correct live behavior —
**not** legacy anatomy. CI acceptance gates derived from this document must
assert outcomes, not section inventories.

This document supersedes the homepage-anatomy token requirements previously
baked into `intelligence/scripts/acceptance_publish_live_lane.sh` and the
legacy token list in `intelligence/company/www/brand_contract_v1.json`.

---

## Principle

> The surface is a front door. Acceptance protects the door, not the wallpaper.

Every requirement below is either:

- **structural truth** (the door exists and opens the right way), or
- **semantic truth** (the words on the door are not lying), or
- **focus protection** (the door has not been re-glued to a warehouse).

No requirement enforces a specific section ID, card type, or trust-bar
phrase. If the redesign swaps a `feature-card` for a prose paragraph and
the door still tells the truth, acceptance passes.

---

## Website Contract

### W1. All public HTML pages — shared shell truth
Every file in `intelligence/company/www/*.html` MUST:

- declare `<!doctype html>` and `<html lang="en">`.
- include a viewport meta tag.
- contain at least one `<header` element and at least one `<footer` element.
- reference the canonical asset marker from `.asset-version`
  (already gated by `scripts/ci/check_asset_versions.py`).
- load `/assets/meridian.css` (the shared stylesheet) exactly once.

### W2. All public HTML pages — banned legacy commercial wording
None of these substrings may appear on any public HTML page:

- `Constitutional Institution License`
- `Get License`
- `$299`
- `$79`
- `checkout-capture`
- `manual pilot`

These reflect retired commercial funnels. Their absence is semantic truth.

### W3. Homepage (`index.html`) — focus
- Exactly **one** `<h1>` element. The hero proposition is dominant.
- At least one anchor with `href="/pilot"` (install/start path is visible).
- Mentions both `Core` and `Team` (the two-depth distinction is understood).
- Mentions `local` in some form (local-first truth — not a forced phrase).
- Body length ceiling: the raw `index.html` bytes must stay **under 60 KB**
  to prevent regression back to a warehouse homepage. (Measured against the
  source file, not post-minification.)

### W4. Homepage — banned reintroductions
- No `<form` element with `action` pointing at a `/api/subscriptions/…` or
  `/api/institution/license/…` endpoint.
- No `data-paywall` or `data-checkout` attribute.
- No `pricing-grid`, `price-card`, `checkout-card`, `pricing-section`,
  `checkout-section`, or `premium-pricing` class (already partially gated
  by `acceptance_ui_anatomy_lane.sh`; we keep this alignment).

### W5. `proofs.html` — truth
- `<title>` contains "Proof".
- References either `/api/runtime-proof` or `/api/kernel-proof-bundle`.

### W6. `workflows.html` — truth
- `<title>` contains "Workflow".
- References `/api/workflows/showcase`.

### W7. What this contract does NOT require
The following were required by the old lane and are explicitly **not**
required here. A redesign is free to use them, drop them, or replace them:

- Section IDs: `trust-bar`, `non-goals`, `why-meridian`, `governance-model`,
  `research-hub`, `how-to-contribute`, `install-demo`, `live-snapshot-section`.
- Component class tokens: `brand-mark`, `brand-wordmark`, `nav-cta`,
  `cta-group`, `feature-card`, `metric-card`, `live-chart-card`, `lane-card`,
  `step-card`, `premium-footer`, `page-intro`, `live-chart-grid`,
  `proof-summary-shell`, `operator-stream-log`, `data-workflow-showcase-grid`,
  `data-usdc-surface`.
- Trust-bar wording including `Local-first`.
- Specific media files such as `install_in_60_seconds.gif` or
  `meridian_demo_2m20s.mp4`.
- The 7-label overloaded nav: `Product`, `Governance`, `Proofs`, `Workflows`,
  `Community`, `Support`, `Docs`.
- The phrase `Governed Agent Runtime` as a forced intro token.

---

## README Contract (root `README.md`)

The README is a **doorway**. A reader must reach install and first success
without walking past a gallery or a dev-maintenance wall.

### R1. Ordering (intent-based)
Within the first 120 non-blank lines, the following must appear in this
order (case-insensitive, substring match against markdown source):

1. Identity line: "Meridian" in the first H1 or paragraph.
2. Install section: a fenced code block containing `install-full.sh`
   (or an explicit line starting with `curl` that fetches an install script).
3. Onboarding section: an `./scripts/onboard.sh` invocation.
4. Core/Team distinction: both the tokens `Core` and `Team` appear after
   identity and before architecture/dev-maintenance headings.
5. First commands: a heading that includes `First commands` OR `First use`
   OR `First success`, followed by an executable snippet.

### R2. Forbidden top-of-README patterns
Within the first 120 non-blank lines, the following must NOT appear:

- A heading whose title is only "Quick Visuals" or "Gallery" or "Screenshots".
- A heading named "Benchmarks" or "Benchmark".
- A heading named "Migration" or "Dev and Maintenance" or
  "Developer commands" or "Governance, benchmark, and migration".

These may live further down in the README; they must not be the second,
third, or fourth section encountered by a new reader.

### R3. Identity truth
The README must not use retired commercial wording
(same banned list as W2) anywhere in the file.

---

## Dashboard Contract

The workspace dashboard (`DASHBOARD_HTML` in
`intelligence/company/meridian_platform/workspace.py`) is the operator's
daily cockpit. Acceptance protects Core-first operation and Team-depth
separation.

### D1. Structural shell
`DASHBOARD_HTML` MUST contain:

- `Core cockpit` and `Team governed depth` as visible headings.
- `id="panel-core"` and `id="panel-team"` as sibling `role="tabpanel"`
  containers.
- `id="tab-core"` and `id="tab-team"` inside a `role="tablist"` container.

### D2. Forbidden disclosure regression
`DASHBOARD_HTML` MUST NOT contain any of:

- `<details id="team-details"` (the old Team collapse widget).
- `class="team-section-toggle"` or `class="h2 team-section-toggle"`
  (its summary toggle).
- A `<summary` tag whose text matches `Team governed operations`.

Team depth is reached by selecting the Team tab, not by expanding a
disclosure.

### D3. Core first-fold hygiene
The first-fold Core panel (the contents of `id="panel-core"`, up to but
not including `id="panel-team"`) MUST NOT reference any of these routes
as primary governance-execution actions in its initial action row:

- `/api/court/rules`, `/api/court/proposals`, `/api/court/vote`
- `/api/authority/approve`, `/api/authority/reject`
- `/api/payouts/submit`, `/api/treasury/transfer`

The Core cockpit may link to read-only Team context (e.g. a link stub
indicating Team mode is available), but governance write-execution
entry points belong in the Team panel.

### D4. Live auth boundary (runtime truth)
The live workspace `/workspace` route MUST return HTTP 401 without basic
auth and HTTP 200 with correct basic auth. This is verified at the
acceptance level via `acceptance_onboarding_ready_lane.sh`; the
dashboard-shell gate at rest only inspects HTML source.

---

## Asset Version Contract (unchanged)

Every runtime-facing HTML file in `intelligence/company/www/` must
reference the canonical version marker in
`intelligence/company/www/.asset-version`. Gated by
`scripts/ci/check_asset_versions.py`.

Rationale: stops partial bumps (e.g. some files at `v=oss11`, others at
`v=oss12`) that leave browsers on mixed stylesheet/JS caches.

---

## What Each Gate Protects

| Gate | Layer | Failure class prevented |
|---|---|---|
| `scripts/ci/check_asset_versions.py` | source | Partial asset-marker bumps across HTML |
| `scripts/ci/check_dashboard_contract.py` | source | Regression to `<details>` Team collapse or Core-fold governance spam |
| `scripts/ci/check_website_contract.py` | source | Homepage focus regression, commercial wording re-drift, warehouse-size regression |
| `scripts/ci/check_readme_contract.py` | source | README becoming a warehouse or losing the doorway ordering |
| `intelligence/scripts/acceptance_publish_live_lane.sh` | live | Publisher integrations + live API endpoints (status, kernel-proof-bundle, deprecated 410s) |
| `scripts/acceptance_onboarding_ready_lane.sh` | live | Real workspace/gateway bootstrap, auth, bid/court/treasury round-trip |
| `intelligence/company/www/scripts/verify_brand_contract.py` | source | Canonical brand assets present; public page set intact |

---

## Change Control

This contract is the source of truth. Any CI acceptance rule that conflicts
with it must be updated to reference it, and a short note (`Why changed:`
plus a `How to apply:` line, per the team's feedback-memory convention)
must be included in the commit message that adjusts the rule.
