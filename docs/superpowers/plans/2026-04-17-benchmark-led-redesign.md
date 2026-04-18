# 2026-04-17 Benchmark-led Surface Redesign (Meridian)

## 1) Meridian is doing wrong now

1. **Homepage is a feature shelf, not a decision surface.**
   Too many equal-priority sections (`non-goals`, `governance-model`, `research-hub`, live charts, install media, feature inventory, support) dilute first impression.
2. **Hero competes with itself.**
   The proposition, mode explanation, local dashboard links, trust bar, and multiple nav destinations fight for attention above and immediately below the fold.
3. **Top navigation is overexposed.**
   Too many top-level choices before users understand the product.
4. **README still front-loads too much.**
   The top half contains install + usage, but then quickly expands into long governance/team cURL sections and still has visual/media-heavy framing in the wrong place.
5. **Dashboard still feels like a governance dump.**
   Core and Team are notionally separated, but first fold remains crowded (status chips + composer + many cards). Team depth still relies on a native-feeling `<details>/<summary>` pattern.
6. **Editorial judgment is weak.**
   Surfaces optimize for completeness and proof of work, not for first-task clarity.

---

## 2) What each competitor does well (surface lessons)

> Sources benchmarked:  
> `nagisanzenin/skyclaw`, `RightNow-AI/openfang`, `zeroclaw-labs/zeroclaw`, `clawdotnet/openclaw.net`, `nearai/ironclaw`, `clawsouls/soulclaw`, `openclaw/openclaw`, `paperclipai/paperclip`, `msitarzewski/agency-agents`

### skyclaw
- Strong install reveal early (“Install in 30 seconds”).
- Clear first CTA despite long README.
- Lesson: immediate run path can coexist with deep content if first action is unmistakable.

### openfang
- Strong one-liner + concrete quickstart command block near top.
- Intro tells exactly what product category it is.
- Lesson: short category framing + executable starter commands reduce friction.

### zeroclaw
- Heavy content, but “preferred setup” and onboarding command are explicit.
- Repeats the canonical setup path consistently.
- Lesson: one canonical path repeated > many alternative starts.

### openclaw.net
- Starts with purpose (“Why this project exists”) and practical differentiation.
- Technical breadth appears after framing.
- Lesson: rationale before inventory creates trust.

### ironclaw
- Security-first narrative with structured headings and clear progression.
- Install section appears early and is easy to find.
- Lesson: single posture (security) gives coherence.

### soulclaw
- Deep technical content but immediate identity statement at top.
- Uses one mental model (memory tiers) repeatedly.
- Lesson: one stable mental model beats many disconnected claims.

### openclaw
- Fast declaration of product identity + direct onboarding instruction.
- “Preferred setup” and “new install? start here” are explicit.
- Lesson: onboarding pointer should be visible immediately.

### paperclip
- Memorable category framing and strong “what this is” section.
- Clear quickstart anchor in top navigation links.
- Lesson: users remember one category sentence, not ten feature bullets.

### agency-agents
- Fast “what is this” and direct quick-start options.
- Task-oriented reading order.
- Lesson: action first, taxonomy second.

---

## 3) What Meridian should adopt structurally

1. **One dominant proposition per surface.**
   - Website: “local daily runtime with governed depth” as one line, one primary CTA.
   - README: install + first commands before anything else.
   - Dashboard: Core cockpit first fold focused on immediate action + live status.
2. **Reduce choices above the fold.**
   Hard-cap top navigation and hero decisions.
3. **Progressive disclosure.**
   Move governance/proof/inventory depth down or behind intentional entry points.
4. **Separate Core vs Team by interaction depth, not co-equal stacking.**
   Team must be intentionally entered, not dumped in same visual priority.
5. **Replace cheap collapsible patterns for important Team controls.**
   Use designed tabs/segmented depth instead of native details-summary UX.
6. **Kill vanity and duplicate proof blocks in primary surfaces.**
   Keep only evidence that helps first decision.

---

## 4) What Meridian must explicitly NOT copy

1. Do **not** copy competitor branding language, mascots, slogans, or playful identity tropes.
2. Do **not** copy metric-flex hero walls (LOC/tests/chips overload) as first impression.
3. Do **not** copy long sponsor/social blocks near top.
4. Do **not** copy README mega-lists and giant feature matrices in the first half.
5. Do **not** become a benchmark-comparison page in the homepage first fold.
6. Do **not** use “all capabilities visible now” as IA strategy.

---

## 5) Exact redesign rules to implement now

1. **Website IA rules**
   - Keep only essential top-nav items + one CTA.
   - Hero: one proposition, one primary action, one secondary action max.
   - Remove homepage sections that are inventory/filler/support-heavy from primary path.
   - Keep only a minimal “proof/credibility” strip and concise “how to start” flow.

2. **README rules**
   - Top order: identity → one-line proposition → install → onboarding → first commands.
   - Remove “Quick Visuals” completely.
   - Move long Team governed execution cURL and deep governance exposition below core start path.
   - Keep badges restrained.

3. **Dashboard rules**
   - Core first fold: status + immediate action + next step only.
   - Team depth behind explicit mode tab/switch (designed interaction), not native details-summary.
   - No automatic UI behavior that feels broken/surprising.
   - No large institutional table overload in first fold.
   - Preserve all live routes/functionality; presentation changes only.

4. **Visual rules**
   - Fewer cards, larger breathing room, stronger spacing rhythm.
   - Reduce equal-emphasis surfaces; make primary path visually dominant.
   - Keep language plain, direct, product-grade (no gimmicks).

5. **Verification rules**
   - Verify homepage is materially shorter and calmer.
   - Verify README top half is operationally scannable and has no Quick Visuals.
   - Verify dashboard Core first fold is cleaner and Team depth feels intentional.
   - Verify routes and controls still function.
