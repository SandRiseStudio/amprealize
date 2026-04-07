---
name: App Store Screenshot Infographic Guidelines
globs: "**/*.{md,json,tsx,js,png,jpg,jpeg}"
alwaysApply: true
description: Guidelines for designing App Store promotional infographic screenshots (text overlays + device frames + UI shots)
---

# App Store Screenshot Design Agent Playbook

## Mission
Turn raw app screenshots into App Store–ready, high-conversion “promo infographic” images: clear headline, strong visual hierarchy, consistent branding, and correct export specs for iOS App Store listings.

Primary outcome: a set of screenshots that communicate the product’s value in <3 seconds per image.

---

## Required Inputs Before Starting
Minimum:
- App name
- One-line value proposition
- Target audience + primary use case
- Top 5–8 features (ranked)
- Brand basics (logo/app icon + primary/secondary colors)

Recommended:
- Pricing/monetization model (free, freemium, subscription)
- Primary funnel goal (installs, trials, sign-ups)
- Raw screenshots (prefer 6–12 options, including your strongest “hero” screen)
- Competitor examples (2–3 App Store listings)

If any input is missing, proceed with reasonable defaults and list assumptions at the end.

---

## Output Deliverables
1. **Screenshot storyboard** (ordered frames: headline + supporting line + which UI screenshot + layout pattern)
2. **Design system notes** (type scale, spacing, backgrounds, icon usage, device frame rules)
3. **Production checklist** (capture, layout, export, QA)
4. **Export spec sheet** (sizes and naming convention)
5. **Iteration notes** (what to A/B test later)

## Default Behaviors
- Apply `behavior_craft_messaging` for concise, benefit-led screenshot headlines and supporting copy.
- Apply `behavior_validate_accessibility` for readable contrast, legible typography, and glanceable layouts.
- Apply `behavior_plan_go_to_market` when sequencing frames around conversion, positioning, and market-facing value.

---

## Core Principles (Non-Negotiable)
### 1) One idea per screenshot
Each image should communicate one primary value. No “feature soup.”

### 2) Lead with outcome, then prove it
Headline = benefit. UI screenshot = proof.

### 3) Readable at a glance
Assume fast scrolling. Headlines must be legible on a small phone.

### 4) Consistency beats creativity
A cohesive set converts better than seven different styles.

### 5) Honest visuals
Do not imply capabilities the product doesn’t have. Avoid fake badges (“#1”, “award-winning”) unless verifiable.

---

## Recommended Screenshot Set Structure (Generic)
Use 6–8 images for simpler apps; 8–10 for complex apps.

### Frame categories (choose the best fit)
**Frame 1 — Value prop / Hero**
- What it is + why it matters (fast)
- Shows your most impressive screen

**Frame 2 — Primary outcome**
- The #1 user job to be done
- Demonstrate the “before → after” outcome if possible

**Frame 3 — Differentiator**
- The reason to choose your app over alternatives
- Feature or approach that is uniquely strong

**Frame 4 — Trust / Safety / Privacy (if relevant)**
- Privacy, security, permissions, verification, controls
- Especially important for camera, finance, health, kids, location

**Frame 5 — Core workflow**
- Show how the user actually uses it day-to-day
- Keep it simple: “do X in one tap” style

**Frame 6 — Secondary feature**
- A supporting feature that drives retention or delight

**Frame 7 — Social / Sharing / Collaboration (if relevant)**
- Invites, sharing, groups, community, multi-device

**Frame 8 — Personalization / Automation (if relevant)**
- AI, recommendations, scheduled updates, templates, routines

**Optional**
- Pricing/value: “Try free” / “No ads” / “Cancel anytime” (only if true and approved)
- Cross-platform: iPhone/iPad/web/macOS (only if true)

---

## Layout System (Use One Pattern Across the Set)
Default to one layout for cohesion. Pick one:

### Pattern A: Text top, device bottom (most common)
- Top 35–45%: headline + short supporting line
- Bottom 55–65%: device frame with UI inside
Best for: clarity + easy scanning

### Pattern B: Split left/right (modern, informational)
- Left: headline + max 2 bullets
- Right: device frame
Best for: slightly more explanation without clutter

### Pattern C: Full-bleed UI with gradient + overlay text (advanced)
- Only if readability stays excellent
Best for: visually striking consumer apps

Default to Pattern A unless there’s a strong reason not to.

---

## Copy Rules for Screenshot Overlays
### Headlines
- 3–7 words ideal, max 9
- Benefit-driven and concrete
- Avoid filler: “Amazing”, “Next-gen”, “Revolutionary”
- Prefer sentence case unless brand explicitly uses title case

### Supporting line (optional)
- 1 short sentence or phrase (max ~12 words)
- Clarifies the headline or removes ambiguity

### Bullets (only if needed)
- Max 2 bullets
- Max 5 words each

### Terminology consistency
- Use the same terms as the product UI and App Store description
- Never rename features across screenshots (confuses users)

### Compliance / claims
- No medical/financial/legal guarantees
- No unverifiable performance claims (“2x faster”) unless measured and defensible

---

## Visual Style Guidelines
### Branding
- Use brand accent color for emphasis (key words, icons, highlights)
- Background should be simple:
  - solid
  - subtle gradient
  - low-contrast abstract shapes
Avoid busy photo backgrounds unless heavily blurred and low-contrast.

### Typography
- Use a clean sans-serif (system or brand font)
- Clear hierarchy:
  - Headline: large + bold
  - Supporting: smaller + medium
- Headline max 2 lines

### Device Frames
- Use one consistent device frame style for the entire set
- Keep UI crisp (no stretching)
- Light shadow under the device is okay; avoid heavy effects

### UI Screenshot Selection
Prefer screens that show:
- the primary action or outcome
- recognizable content (not empty states)
- the feature you’re claiming in the headline

Avoid screens that require reading paragraphs to understand.

---

## Platform Specs (Practical Defaults)
### iOS App Store screenshot sizes
Design at the largest required iPhone size first, then adapt down.
Common needs:
- 6.7" iPhone (primary)
- 6.5" iPhone (often also required depending on App Store Connect setup)

If the app supports iPad, create a separate iPad set.

### Safe area heuristic
- Keep all text at least ~6–8% inset from each edge
- Keep critical content away from extreme top/bottom (store previews can crop)

---

## Workflow
### Step 1 — Storyboard
Draft 6–10 frames. For each frame:
- Headline
- Supporting line (optional)
- UI screenshot to use
- Layout pattern
- Single goal (what the user learns)

Check the story:
1) what it is
2) why it matters
3) why you
4) how it works
5) trust + proof
6) retention/delight

### Step 2 — Capture and prep screenshots
- Capture clean UI (no debug overlays)
- Use consistent status bar styling if possible
- Remove sensitive personal data
- Prefer consistent UI theme (light/dark) across the set

### Step 3 — Compose in a design tool
Good options:
- Figma (best for components + reuse)
- Canva (fast)
- Adobe Express (fine)

Build reusable components:
- Background
- Headline block
- Device frame
- Screenshot mask
- Optional icon element

### Step 4 — Export
- PNG
- sRGB
- Avoid visible compression artifacts
- Naming convention:
  - `appname_ios_67_01_hero.png`
  - `appname_ios_67_02_primary_outcome.png`
  - etc.

### Step 5 — QA checklist
- Readable at 25–35% zoom
- Consistent alignment, spacing, and typography
- No typos; consistent punctuation and case
- No cut-off UI; device frame not blurry
- Each frame still makes sense independently

---

## Common Mistakes to Avoid
- Too much text
- Inconsistent fonts/device frames/background styles
- Headlines that describe features, not outcomes
- Low contrast text
- Empty or confusing UI shots
- Overpromising or implying features that don’t exist

---

## Generic Headline Templates (Reusable)
Use these patterns to draft quickly:

### Value prop
- “<Outcome> in <time/effort>”
- “The easiest way to <job>”
- “<Job>, made simple”
- “Stay <benefit> with <product>”

### Differentiator
- “Built for <audience>”
- “<Unique approach> that actually works”
- “Automate <task>”
- “Smarter <job> with <feature>”

### Trust
- “Private by default”
- “You control access”
- “Secure sign-in”
- “Your data stays yours”

### Workflow
- “Do it in one tap”
- “Start in seconds”
- “Track everything in one place”
- “Personalized to your goals”

---

## Iteration / A-B Test Ideas (Later)
- Frame 1 headline variants (2–3 options)
- Background style: solid vs gradient
- Layout: centered vs offset device
- Supporting line on/off
- More benefit-forward vs more feature-forward framing

Measure with: App Store page conversion (impressions → page views → installs).

---

## Reporting Template (What the agent outputs each run)
### Screenshot Plan
1) Frame 1 — Headline: “...” / Supporting: “...” / Screenshot: ... / Layout: ... / Goal: ...
2) ...

### Design Decisions
- Layout pattern: ...
- Background: ...
- Type scale: ...
- Device frame: ...

### Export List
- iPhone 6.7": ...
- iPhone 6.5": ...
- iPad (if applicable): ...

### Assumptions / Risks
- ...
