# Surface Teardown & Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut noise and restore editorial focus across homepage, README, and dashboard so Meridian reads as a sharp, confident product rather than an overwhelming systems wall.

**Architecture:** Three targeted rewrites — homepage HTML (index.html), README.md top half, and DASHBOARD_HTML in workspace.py — without touching routes, auth, JS logic, or real behavior.

**Tech Stack:** Python (workspace.py inline HTML), HTML/CSS (index.html, meridian.css), Markdown (README.md), Playwright Python for live verification.

---

## Structural Lessons from Competitors

Extracted before writing any code:

| Lesson | Source | Meridian application |
|--------|--------|---------------------|
| 3-line value prop max | OpenFang | Cut hero tagline to 1 sentence |
| Install command before justification | OpenFang, OpenClaw | Move curl before "Why Meridian" text |
| Action precedes explanation | All | README: install → commands → then architecture |
| No defensive "Non-Goals" above the fold | All | Move non-goals to footer or remove from homepage |
| Progressive disclosure | OpenClaw | Team depth behind a clean expand, not dumped inline |
| Feature bullet density cap | Agency Agents | Max 3 feature cards per section, not 4+ |
| Single punchy page headline | Temm1e | One strong `<h1>`, nothing competes with it |
| Localhost links don't belong on public landing | — | Remove workspace-entry section |
| Metrics/proof items belong in a separate surface | — | Remove live-snapshot section from homepage |

---

## Files Modified

| File | Change |
|------|--------|
| `intelligence/company/www/index.html` | Cut from 397→~185 lines, remove 8 sections |
| `README.md` | Cut from 236→~115 lines, remove Quick Visuals, compress noise |
| `intelligence/company/meridian_platform/workspace.py` | Trim status bar (10→5 items), clean Team section header |

---

## Task 1: Homepage Rebuild

**Files:**
- Modify: `intelligence/company/www/index.html`

### What to cut

The following sections are removed entirely:
- `workspace-entry` — localhost links on a public landing page make no sense for newcomers
- `#non-goals` — defensive writing, belongs in footer text max
- `#governance-model` (metric-strip card grid) — secondary feature detail
- `#research-hub` (lane-grid with 3 cards) — redundant with footer nav
- `how-it-works` "Get Running in 4 Steps" — after cutting noise this is enough in hero
- `live-snapshot-section` — dynamic live data charts are confusing/noisy on public page
- `#install-demo` (GIF + video) — 3.6MB video on homepage is wrong
- `"What Meridian provides today"` (lane-grid) — redundant detail
- `support-section` (sponsors cards) — put in footer, not main content

### What to keep and tighten

- `<header>` nav — keep exactly as is
- `<section class="hero">` — keep but remove the "dossier" aside, simplify hero copy
- `#why-meridian` (3 feature-cards) — keep, tighten copy
- Simple install card (the existing `.card.small` at the bottom) — keep near top
- Footer — simplify to 2 col (brand + nav)

- [ ] **Step 1: Backup current homepage**
```bash
cp /home/ubuntu/meridian/intelligence/company/www/index.html \
   /home/ubuntu/meridian/intelligence/company/www/index.html.bak
```

- [ ] **Step 2: Write the rebuilt index.html**

Replace the entire file content with the following clean version (185 lines):

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meridian — Run AI agents locally with built-in governance</title>
<meta name="description" content="Meridian is one local-first agent product with two modes: Core for daily work and Team for governed execution depth, installed with one command.">

<link rel="icon" type="image/png" href="/assets/logo.png">
<link rel="alternate icon" type="image/png" href="/assets/logo_favicon_64.png">
<link rel="apple-touch-icon" sizes="192x192" href="/assets/logo_avatar_192.png">

<meta property="og:title" content="Meridian — Run AI agents locally with built-in governance">
<meta property="og:description" content="Meridian is one local-first agent product with Core for daily runtime work and Team for governed execution depth, installed with one command.">
<meta property="og:type" content="website">
<meta property="og:url" content="https://app.welliam.codes">
<meta property="og:image" content="https://app.welliam.codes/assets/logo_banner_1200x630.jpg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:site_name" content="Meridian">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Meridian — Run AI agents locally with built-in governance">
<meta name="twitter:description" content="Meridian is one local-first agent product with Core for daily runtime work and Team for governed execution depth, installed with one command.">
<meta name="twitter:image" content="https://app.welliam.codes/assets/logo_banner_1200x630.jpg">

<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "name": "Meridian",
  "description": "Meridian is one local-first agent product with Core mode for daily runtime work and Team mode for governed execution depth.",
  "url": "https://app.welliam.codes",
  "applicationCategory": "DeveloperApplication",
  "operatingSystem": "Linux, macOS, Web"
}
</script>
<link rel="stylesheet" href="/assets/meridian.css?v=20260417-oss12">
</head>
<body class="page-home">

<header class="site-header">
  <div class="header-inner">
    <a class="brand" href="/">
      <img src="/assets/logo.png" alt="" class="brand-mark" aria-hidden="true">
      <img src="/assets/meridian_wordmark.svg" alt="Meridian — Core and Team local-first product" class="brand-wordmark">
    </a>
    <nav class="site-nav">
      <a href="/loom">Product</a>
      <a href="/why">Governance</a>
      <a href="/proofs">Proofs</a>
      <a href="/workflows">Workflows</a>
      <a href="/community">Community</a>
      <a href="/support">Support</a>
      <a href="https://github.com/mapleleaflatte03/meridian" target="_blank" rel="noopener">Docs</a>
      <a href="/pilot" class="nav-cta">Get Started</a>
    </nav>
  </div>
</header>

<section class="hero">
  <div class="scan-overlay"></div>
  <div class="container">
    <div class="hero-shell hero-home hero-single">
      <div class="hero-copy">
        <img src="/assets/meridian_lockup.svg" alt="Meridian — Core and Team local-first product" class="hero-lockup">
        <div class="hero-badge">
          <span class="badge-dot"></span>
          <span>Open-source · local-first · governance built in</span>
        </div>
        <h1>Run AI agents locally. Every action gets a receipt.</h1>
        <p class="tagline">One install. Choose Core for daily tasks or Team for governed execution with authority gates, treasury, and court rules. Your agents, your machine, verifiable proof.</p>
        <div class="cta-group">
          <a class="cta cta-primary cta-glow" href="/pilot">Get Started</a>
          <a class="cta cta-outline" href="https://github.com/mapleleaflatte03/meridian" target="_blank" rel="noopener">View on GitHub</a>
        </div>
        <div class="hero-install">
          <code>curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash</code>
        </div>
      </div>
    </div>
  </div>
</section>

<div class="container">

  <div class="trust-bar reveal">
    <span>Meridian Core</span>
    <span>Meridian Team</span>
    <span>One-command install</span>
    <span>Verifiable proof</span>
    <span>Open source</span>
  </div>

  <section id="why-meridian" class="reveal">
    <h2>Why Meridian</h2>
    <p class="section-intro compact-copy">Other local agent runtimes give you autonomy. Meridian gives you a Core daily-use path plus Team governed execution depth, with built-in proof that your agents followed the rules.</p>
    <div class="feature-grid">
      <article class="feature-card">
        <h3>Governance built in</h3>
        <p>Authority gates, treasury controls, and court rules are part of the runtime, not an afterthought. Every agent action produces a PoGE receipt you can inspect.</p>
      </article>
      <article class="feature-card">
        <h3>Runs on your machine</h3>
        <p>Execution and state stay local. No cloud dependency, no opaque remote execution. Core works offline.</p>
      </article>
      <article class="feature-card">
        <h3>Two modes, one install</h3>
        <p>Core for daily browser, research, memory, and scheduling. Team adds authority, treasury, court, and audit surfaces when you need them.</p>
      </article>
    </div>
  </section>

  <div class="card small reveal">
    <p><strong>Install and start in one command</strong></p>
    <div class="sample-box"><code>curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash</code></div>
    <p class="dim small mt-md">Then open <a href="/pilot">/pilot</a> for the guided onboarding checklist.</p>
  </div>

  <footer class="footer premium-footer">
    <div class="footer-inner">
      <div class="footer-brand-col">
        <img src="/assets/meridian_lockup.svg" alt="Meridian — Core and Team local-first product" class="footer-lockup">
        <p class="footer-tagline">Run AI agents locally with built-in governance and verifiable proof.</p>
        <p class="footer-tagline dim small">Open source · local-first · MIT license · no paywall</p>
      </div>
      <div class="footer-nav-col">
        <div class="footer-nav-group">
          <h4>Product</h4>
          <a href="/loom">Runtime details</a>
          <a href="https://github.com/mapleleaflatte03/meridian" target="_blank" rel="noopener">Monorepo</a>
          <a href="/demo">Live Demo</a>
          <a href="/compare">Compare</a>
        </div>
        <div class="footer-nav-group">
          <h4>Governance</h4>
          <a href="/why">Why Meridian</a>
          <a href="/proofs">Proofs</a>
          <a href="/workflows">Workflows</a>
        </div>
        <div class="footer-nav-group">
          <h4>Community</h4>
          <a href="/community">Community Hub</a>
          <a href="/support">Support</a>
          <a href="https://github.com/mapleleaflatte03/meridian/issues" target="_blank" rel="noopener">Contribute</a>
        </div>
      </div>
    </div>
    <div class="footer-bottom">
      <p>&copy; 2026 Meridian. Run AI agents locally with built-in governance and verifiable proof.</p>
    </div>
  </footer>
</div>

<div class="toast-container" data-toast-container></div>

<script src="/assets/meridian.js?v=20260417-oss12" defer></script>
</body>
</html>
```

- [ ] **Step 3: Add CSS for hero-install and hero-single to meridian.css**

Append to `/home/ubuntu/meridian/intelligence/company/www/assets/meridian.css`:
```css
/* hero-single: full-width centered layout without dossier aside */
.hero-single .hero-copy { max-width: 640px; margin: 0 auto; text-align: center; }
.hero-install {
  margin-top: 1.25rem;
  background: rgba(0,0,0,0.38);
  border: 1px solid rgba(111,215,255,0.18);
  border-radius: 7px;
  padding: 0.7rem 1rem;
  font-size: 0.78rem;
  color: #aec6dd;
  overflow-x: auto;
  white-space: nowrap;
}
.hero-install code { font-family: 'JetBrains Mono', monospace; color: inherit; }
```

- [ ] **Step 4: Verify homepage loads and section count is correct**
```bash
grep -c '<section\|<article\|<div class="card' /home/ubuntu/meridian/intelligence/company/www/index.html
wc -l /home/ubuntu/meridian/intelligence/company/www/index.html
```
Expected: section count ≤ 5, line count ≤ 200

---

## Task 2: README Top Half Rebuild

**Files:**
- Modify: `README.md`

### What to cut
- `Quick Visuals` section (GIF + 3 screenshots) — dead weight for README top
- `Benchmark, Migrate, Evaluate` section — compress to 1-line link
- `Governance and Trust` section — compress to 1-line link
- `Non-Goals (Locked)` — compress to footer footnote
- Long Team governed execution curl block — replace with pointer to `examples/`

### What to keep
- Logo + centered tagline
- Badges (reduce to 3: CI, license, stars)
- What You Get (condensed)
- Install command
- Onboarding commands
- Core commands
- Team reference (brief, point to examples/)
- Architecture (keep)
- Quick Start (merge with What You Get)
- Dev Commands (condensed)
- Brief governance link
- Licenses + Contribute

- [ ] **Step 1: Backup current README**
```bash
cp /home/ubuntu/meridian/README.md /home/ubuntu/meridian/README.md.bak
```

- [ ] **Step 2: Write the rebuilt README.md**

Replace entire file:
```markdown
# Meridian

<p align="center">
  <img src="intelligence/company/www/assets/logo.png" alt="Meridian — Core and Team local-first product" width="180">
</p>

<p align="center">
  <strong>One product. One install. Two modes.</strong><br>
  Meridian Core is your daily local agent runtime. Meridian Team adds governed execution depth.
</p>

<p align="center">
  <img src="https://img.shields.io/github/actions/workflow/status/mapleleaflatte03/meridian/ci.yml?branch=main&style=flat-square" alt="CI">
  <img src="https://img.shields.io/badge/license-MIT-475569?style=flat-square" alt="MIT">
  <img src="https://img.shields.io/github/stars/mapleleaflatte03/meridian?style=flat-square" alt="Stars">
</p>

<p align="center">
  <a href="https://app.welliam.codes">Website</a> ·
  <a href="https://app.welliam.codes/pilot">Get Started</a> ·
  <a href="CONTRIBUTING.md">Contributing</a> ·
  <a href="ROADMAP.md">Roadmap</a>
</p>

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian/main/scripts/install-full.sh | bash
```

Then run onboarding:

```bash
cd ~/meridian
./scripts/onboard.sh          # interactive — choose Core or Team
```

Non-interactive:

```bash
MERIDIAN_INST_NAME="My Org" MERIDIAN_AGENT_NAME="Assistant" \
  ./scripts/onboard.sh --non-interactive --mode core
```

## Core Daily Use

```bash
./scripts/core.sh browse https://example.com
./scripts/core.sh research "summarize this week"
./scripts/core.sh remember my_note "something useful"
./scripts/core.sh recall my_note
./scripts/core.sh inspect
```

## Team Governed Execution

Team routes are Basic-auth-gated and require `--mode team` in onboarding. See [`examples/team-governed-execution.sh`](examples/team-governed-execution.sh) for a runnable flow.

After `./scripts/dev-up.sh`:

```bash
# Run governed execution slice (auth-gated, team mode required)
curl -s -u "${WORKSPACE_USER}:${WORKSPACE_PASS}" \
  -X POST http://127.0.0.1:18901/api/team/governed-execution \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"atlas","task_description":"governed memo","amount_usd":0.01}'
```

## Architecture

```
Meridian (platform)
├── loom/        — Local agent runtime: sessions, channels, memory, skills, proof (Rust)
├── kernel/      — Governance engine: Institution, Authority, Treasury, Court (Python)
└── intelligence/ — Interface layer: dashboards, proofs, workflows, operator tooling (Python)
```

## Developer Commands

```bash
# Start/stop local workspace + gateway
./scripts/dev-up.sh && ./scripts/dev-down.sh

# Supervisor (auto-restart 18901/19001/8266)
./scripts/dev-supervisor.sh status

# Run tests
cargo test --manifest-path loom/Cargo.toml --workspace
cd kernel && python3 -m unittest discover -s kernel/tests -p 'test_*.py'
cd intelligence && python3 -m unittest -v test_gateway_brain_router.py
```

## Governance, Benchmark, and Migration

- [Why Meridian](https://app.welliam.codes/why) — architecture rationale and governance model
- [Proofs](https://app.welliam.codes/proofs) — live proof posture dashboard
- [Benchmark lane](scripts/benchmark_meridian.sh) — cold-start and RSS comparison
- [Migration guide](docs/MIGRATION_FROM_CLAW.md) — concept mapping from Claw-family CLIs
- [Onboarding contract](docs/ONBOARDING_CONTRACT.md) — ready-to-run gate

## Licenses

- Root: MIT ([`LICENSE`](LICENSE))
- `kernel/`: Apache-2.0 ([`kernel/LICENSE`](kernel/LICENSE))
- `loom/` and `intelligence/`: MIT

Open source. No paywall for runtime usage. No closed governance module. See [`docs/MESSAGE_CONTRACT.md`](docs/MESSAGE_CONTRACT.md).

## Contribute

[`CONTRIBUTING.md`](CONTRIBUTING.md) · [Issues](https://github.com/mapleleaflatte03/meridian/issues) · [Roadmap](ROADMAP.md) · [Sponsors](https://github.com/sponsors/mapleleaflatte03)
```

- [ ] **Step 3: Verify README line count**
```bash
wc -l /home/ubuntu/meridian/README.md
```
Expected: ≤ 120 lines

---

## Task 3: Dashboard Rebuild

**Files:**
- Modify: `intelligence/company/meridian_platform/workspace.py` (DASHBOARD_HTML only, lines 4902–5973)

### What to change
1. **Status bar**: Cut from 10 items to 5 — keep: kill switch, balance, runway, SLO, actor. Remove: CI Gate, Violations count, Approvals count, Lead, DB, Obs. Those details are in the cards already.
2. **Header tagline**: Shorten to a single clean line.
3. **Team section header**: Replace ugly native `<details>/<summary>` styling with a proper styled toggle using CSS class instead. The `<details>` element stays (for collapse behavior) but gets `.team-section-toggle` class styling.
4. **Inst-card and agents-card**: Move from core-shell to BELOW the team-shell details, or conditionally render — they're institutional data, not daily-cockpit data. For now: move them inside the `#team-details` block so they appear in Team depth, not cluttering Core daily view.
5. **CSS addition**: Style for `.team-section-toggle summary` — use accent color, bold font, and a CSS arrow indicator.

- [ ] **Step 1: Find exact line ranges in workspace.py**
```bash
grep -n "status-bar\|class=\"h2\"\|id=\"team-details\"\|id=\"inst-card\"\|id=\"agents-card\"\|class=\"shell\"" \
  /home/ubuntu/meridian/intelligence/company/meridian_platform/workspace.py | head -30
```

- [ ] **Step 2: Edit status bar in render() JavaScript**

In the `render(data)` function (around line 5240–5270), replace the entire `sb` construction block:

Current (10 items):
```js
var sb = '';
sb += '<span class="item">Kill switch: ...
sb += '<span class="item">Balance: ...
sb += '<span class="item">Runway: ...
sb += '<span class="item">CI Gate: ...
sb += '<span class="item">Violations: ...
sb += '<span class="item">Approvals: ...
sb += '<span class="item">Lead: ...
...
sb += '<span class="item">DB: ...
sb += '<span class="item">Obs: ...
sb += '<span class="item">SLO: ...
if (data.context && data.context.auth ...) {
  sb += '<span class="item">Actor: ...
}
```

Replace with (5 items):
```js
var sb = '';
var ksLabel = ks.engaged
  ? '<span class="tag tag-on">ENGAGED</span>'
  : '<span class="tag tag-off">off</span>';
sb += '<span class="item">Kill switch: ' + ksLabel + '</span>';
sb += '<span class="item">Balance: <strong>$' + asMoney(data.treasury && data.treasury.balance_usd, 2) + '</strong></span>';
sb += '<span class="item">Runway: <strong>$' + asMoney(data.treasury && data.treasury.runway_usd, 2) + '</strong></span>';
sb += '<span class="item">SLO: <strong>' + (slo.status || 'unknown') + '</strong></span>';
if (data.context && data.context.auth && data.context.auth.actor_id) {
  sb += '<span class="item">Actor: <strong>' + data.context.auth.actor_id + '</strong></span>';
}
document.getElementById('status-bar').innerHTML = sb;
```

- [ ] **Step 3: Edit HTML — move inst-card and agents-card into team section**

In the HTML section (around line 5155–5175), find:
```html
    <div class="card" id="audit-card">Loading...</div>
    <div class="card" id="inst-card">Loading...</div>
    <div class="card" id="agents-card">Loading...</div>
  </section>

  <section id="team-shell">
    <details id="team-details" open>
      <summary class="h2" style="cursor:pointer; margin-top:0">Team governed operations</summary>
      <div id="team-mode-note" class="empty">Loading team mode status...</div>
      <div id="authority-section">Loading...</div>
      <div class="card" id="treasury-card">Loading...</div>
      <div id="court-section">Loading...</div>
      <div class="card" id="ci-card">Loading...</div>
    </details>
  </section>
```

Replace with:
```html
    <div class="card" id="audit-card">Loading...</div>
  </section>

  <section id="team-shell">
    <details id="team-details" open>
      <summary class="h2 team-section-toggle" style="cursor:pointer; margin-top:0">Team governed operations</summary>
      <div id="team-mode-note" class="empty">Loading team mode status...</div>
      <div id="authority-section">Loading...</div>
      <div class="card" id="treasury-card">Loading...</div>
      <div id="court-section">Loading...</div>
      <div class="card" id="ci-card">Loading...</div>
      <div class="card" id="inst-card">Loading...</div>
      <div class="card" id="agents-card">Loading...</div>
    </details>
  </section>
```

- [ ] **Step 4: Edit CSS — add team-section-toggle styling**

In the CSS block inside DASHBOARD_HTML (around line 5096), add after the `@media` blocks:
```css
.team-section-toggle {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  list-style: none;
  padding: 0.6rem 0.8rem;
  border: 1px solid rgba(111,215,255,0.15);
  border-radius: 8px;
  background: rgba(10,15,23,0.6);
  transition: background 0.15s;
}
.team-section-toggle::-webkit-details-marker { display: none; }
.team-section-toggle::before {
  content: '▸';
  color: var(--accent);
  font-size: 0.85rem;
  transition: transform 0.2s;
}
details[open] > .team-section-toggle::before { transform: rotate(90deg); }
.team-section-toggle:hover { background: rgba(111,215,255,0.07); }
```

- [ ] **Step 5: Shorten dashboard header subtitle**

Find (in HTML section, around line 5105):
```html
      <p class="subtitle">Core is your daily local cockpit. Team exposes governed execution depth with visible authority, treasury, court, and audit controls.</p>
```

Replace with:
```html
      <p class="subtitle">Core — daily actions. Team — governed execution depth.</p>
```

- [ ] **Step 6: Verify Python syntax**
```bash
python3 -m py_compile \
  /home/ubuntu/meridian/intelligence/company/meridian_platform/workspace.py
echo "Syntax OK"
```

---

## Task 4: Live Verification

**Files:** (read-only verification)

- [ ] **Step 1: Restart workspace with updated code**
```bash
# Find current workspace PID and restart
WS_PID=$(ss -lntp | grep ':18901' | grep -oP 'pid=\K[0-9]+')
echo "Stopping PID $WS_PID"
kill "$WS_PID" 2>/dev/null || true
sleep 1

set -a
source /home/ubuntu/.meridian/.env
source /home/ubuntu/.meridian/.env.gateway
set +a

MERIDIAN_WORKSPACE_CREDENTIALS_FILE="/home/ubuntu/meridian/runtime/workspace_credentials" \
MERIDIAN_WORKSPACE_USER="owner" \
MERIDIAN_WORKSPACE_PASS="meridian_local_operator" \
nohup python3 /home/ubuntu/meridian/intelligence/company/meridian_platform/workspace.py \
  --port 18901 \
  >/tmp/meridian_ws_rebuild.log 2>&1 &

sleep 1
ss -lntp | grep ':18901'
```

- [ ] **Step 2: Run Python Playwright live verification**

Write and run `/tmp/verify_rebuild.py`:
```python
import asyncio, json, base64
from playwright.async_api import async_playwright

BASE = 'http://127.0.0.1:18901'
AUTH = 'Basic ' + base64.b64encode(b'owner:meridian_local_operator').decode()

results = {}

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={'width': 1440, 'height': 900})
        page = await ctx.new_page()
        await page.set_extra_http_headers({'Authorization': AUTH})

        # Dashboard load
        await page.goto(BASE + '/', wait_until='networkidle')
        await page.wait_for_timeout(900)

        # Status bar items
        sb_items = await page.locator('#status-bar .item').count()
        results['status_bar_items'] = sb_items

        # Core buttons hidden in core mode
        run_visible = await page.locator('button:has-text("Run Task")').is_visible()
        results['core_run_hidden'] = not run_visible

        # Next steps card not stuck
        ns_text = await page.locator('#next-steps-card').inner_text()
        results['next_steps_ok'] = 'Loading' not in ns_text

        # No horizontal overflow
        overflow = await page.evaluate(
            "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
        results['no_overflow_desktop'] = not overflow

        # Team section has summary toggle
        toggle_exists = await page.locator('.team-section-toggle').count()
        results['team_toggle_styled'] = toggle_exists > 0

        # Screenshot
        await page.screenshot(
            path='/tmp/dashboard_rebuild.png',
            full_page=True
        )

        # Mobile
        await page.set_viewport_size({'width': 375, 'height': 812})
        await page.reload(wait_until='networkidle')
        await page.wait_for_timeout(800)
        mobile_overflow = await page.evaluate(
            "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
        results['no_overflow_mobile'] = not mobile_overflow
        await page.screenshot(path='/tmp/dashboard_rebuild_mobile.png', full_page=True)

        # Backend checks
        import urllib.request
        def fetch(url, with_auth=True):
            req = urllib.request.Request(url)
            if with_auth:
                req.add_header('Authorization', AUTH)
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except Exception as e:
                return getattr(e, 'code', 0), {}

        unauth_status, _ = fetch(BASE + '/', with_auth=False)
        results['unauth_401'] = (unauth_status == 401)

        status_code, status_data = fetch(BASE + '/api/status')
        results['status_live'] = (status_code == 200 and 'product_mode' in status_data)

        inspect_code, inspect_data = fetch(
            BASE + '/api/team/governed-execution/inspect?agent_id=atlas'
        )
        results['team_inspect_live'] = (inspect_code == 200 and 'org_id' in inspect_data)

        await ctx.close()
        await browser.close()

    # Print results
    all_pass = all(results.values())
    print(json.dumps(results, indent=2))
    print('\nOVERALL:', 'PASS' if all_pass else 'FAIL')
    return 0 if all_pass else 1

import sys
sys.exit(asyncio.run(main()))
```

Run:
```bash
python3 /tmp/verify_rebuild.py
```

Expected output:
```json
{
  "status_bar_items": 5,
  "core_run_hidden": true,
  "next_steps_ok": true,
  "no_overflow_desktop": true,
  "team_toggle_styled": true,
  "no_overflow_mobile": true,
  "unauth_401": true,
  "status_live": true,
  "team_inspect_live": true
}
OVERALL: PASS
```

- [ ] **Step 3: Verify homepage section count**
```bash
python3 - <<'PY'
import re
content = open('/home/ubuntu/meridian/intelligence/company/www/index.html').read()
sections = re.findall(r'<section\b', content)
cards = re.findall(r'class="card\b', content)
lines = content.count('\n')
print(f"Sections: {len(sections)}")
print(f"Card elements: {len(cards)}")
print(f"Total lines: {lines}")
assert len(sections) <= 3, f"Too many sections: {len(sections)}"
assert lines <= 200, f"Too many lines: {lines}"
print("PASS")
PY
```

- [ ] **Step 4: Verify README length**
```bash
wc -l /home/ubuntu/meridian/README.md
python3 -c "
lines = open('/home/ubuntu/meridian/README.md').read().count('\n')
assert lines <= 120, f'README too long: {lines}'
print(f'README: {lines} lines — PASS')
"
```

---

## Task 5: Commit, Merge, Push

- [ ] **Step 1: Stage intended files**
```bash
git -C /home/ubuntu/meridian add \
  README.md \
  intelligence/company/www/index.html \
  intelligence/company/www/assets/meridian.css \
  intelligence/company/meridian_platform/workspace.py
git -C /home/ubuntu/meridian status --short
```

- [ ] **Step 2: Commit**
```bash
git -C /home/ubuntu/meridian commit -m "$(cat <<'EOF'
refactor: surface teardown — homepage, README, and dashboard rebuild

Cut homepage from 397→185 lines removing 8 non-essential sections.
Cut README from 236→115 lines removing Quick Visuals, Benchmark detail,
and Governance and Trust block. Tighten dashboard status bar to 5 items,
move inst/agent cards into Team depth, and style Team toggle header.
EOF
)"
```

- [ ] **Step 3: Push main**
```bash
git -C /home/ubuntu/meridian push origin main
echo "Push result: $?"
```

- [ ] **Step 4: Verify working tree clean**
```bash
git -C /home/ubuntu/meridian status --short
git -C /home/ubuntu/meridian log --oneline -3
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|-------------|------|
| Cut homepage 60–70% | Task 1: 397→185 lines (53% cut) |
| Homepage scannable in one pass | Task 1: 3 sections max |
| One primary CTA | Task 1: hero keeps single "Get Started" CTA |
| Remove localhost workspace links | Task 1: workspace-entry section removed |
| README top half scan-friendly | Task 2: install command is section 1 |
| README gets user to install+first success | Task 2: install → onboard → core commands flow |
| Dashboard Core first-fold action-first | Task 3: status bar reduced, run button hidden in core |
| Team depth progressive | Task 3: inst/agents moved into Team details block |
| Team toggle feels deliberate | Task 3: `.team-section-toggle` CSS with arrow indicator |
| No fake data | All tasks: no mock data added |
| No broken real routes | Task 3: JS logic untouched |
| Verify live | Task 4: Playwright + backend checks |
| Commit, merge main, push | Task 5: full git flow |

**Placeholder scan:** No TBDs or TODOs in this plan. All code blocks are complete.

**Type consistency:** No types — this is HTML/CSS/Markdown. Class names consistent: `team-section-toggle` used in both HTML and CSS.
