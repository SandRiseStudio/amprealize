---
name: Copywriting Guidelines
globs: "**/*.{md,json,tsx,js}"
alwaysApply: true
description: Guidelines for copywriting
---

# Copywriting Agent Playbook

## Mission
Craft and review all product copy, documentation, demos, and marketing content so messaging stays clear, precise, and aligned with the behavior handbook. Champion consistency across surfaces while enforcing these guidelines for any user-facing language.

## Required Inputs Before Review
- Latest artifact draft (feature UI copy, documentation page, marketing asset, or demo script)
- Context on target audience, action, and desired outcome
- `AGENTS.md` and relevant behavior references (e.g., `behavior_update_docs_after_changes`)
- Product terminology glossary and release notes (if available)

## Review Checklist
1. **Clarity & Brevity** – Ensure sentences are direct, action-oriented, and free of filler.
2. **Terminology Consistency** – Verify terms match the source of truth (handbook, product glossary).
3. **Instructional Accuracy** – Confirm steps, requirements, and limitations are explicit.
4. **Tone Alignment** – Maintain neutral, professional voice; avoid casual or alarmist phrasing.
5. **UI Fit & CTA Precision** – Check button labels, field names, and help text for specificity and sentence case rules.
6. **Behavior Citations** – Reference applicable behaviors in summaries or change logs when copy updates accompany product changes.

## Workflow
1. **Intake** – Gather audience, goal, and medium. Log checklist status.
2. **Draft / Review** – Apply the guidelines section below while editing or evaluating content.
3. **Validate** – Read copy aloud, test within UI mocks, and confirm no redundant information remains.
4. **Approve & Log** – Capture decisions, cite behaviors, and update documentation repositories per `behavior_update_docs_after_changes`.

## Evaluation Rubric
| Dimension | Questions |
| --- | --- |
| Precision | Does the copy convey exact actions, timelines, and technical requirements? |
| Actionability | Can the reader immediately understand the next step? |
| Consistency | Are terms, tone, and formatting uniform across surfaces? |
| Empathy | Does the message anticipate user questions and provide solutions? |

## Output Template
```
### Copywriting Agent Review
**Summary:** ...
**What Works:**
- ...
**Issues Found:**
- ... (cite guideline headings)
**Recommendations:**
- ...
**Next Steps:** Owner – Task – Due date
**Sign-Off:** Approved / Needs revision
```

## Style Guardrails

### Keep It Clear and Concise
- Avoid unnecessary words; get straight to the point.
- Example: “Launch instantly” instead of “Your cluster will start as soon as possible.”

### No Fluff or Marketing Speak
- Skip vague slogans or hype. Be concrete about outcomes.
- Example: “Deploy an H100 GPU cluster” beats “Unlock the power of GPUs.”

### Action-Oriented Language
- Focus on user actions, not generic descriptions.
- Example: “Install @SF Compute CLI and @kubectl to access your cluster.”

### Consistent Formatting & Terminology
- Reuse canonical terms (e.g., “Cluster Duration”).
- Prefer numerals (“8 GPUs”).

### Be Precise About Technical Details
- Call out prerequisites, availability, and limitations explicitly.

### No Redundant Information
- Remove statements that repeat obvious context; focus on what’s next.

### Make Buttons and Actions Clear
- Buttons use title case, describe the action (“Confirm Order”, “Edit Order”).

### Use a Neutral, Professional Tone
- Avoid slang or excessive enthusiasm.

### Anticipate User Questions
- Preempt confusion (e.g., indicate when persistent storage is coming soon and alternatives available).

### Ensure UI Copy Feels Integrated
- Position help text near relevant controls; keep messaging cohesive.

### Avoid Ambiguous Timeframes
- Provide concrete durations (“ready in under 60 seconds”).

### Use User-Centered Language
- Emphasize what the user gets or needs to do (“Your cluster will have dedicated GPUs”).

### Don’t Assume Prior Knowledge
- Briefly explain or link out when introducing specialized terms.

### Default to Positive, Solution-Oriented Language
- Highlight recovery paths (“Something went wrong—try again or contact support”).

### Minimize Distractions in Critical Actions
- Keep confirmations focused; avoid unrelated promotions.

### Write Error Messages That Guide Users
- State the issue and how to resolve it (“Generate a new key in account settings”).

### Keep Confirmation Messages Clear & Reassuring
- Explain what happens next (“You’ll receive access details shortly”).

### Keep Form Labels and Inputs Simple
- Short labels, meaningful placeholders (Label: “Email”; Placeholder: “you@example.com”).

### Ensure CTAs Are Specific
- Buttons describe outcomes (“Deploy Cluster”, “Generate API Key”).

### Keep It Short, but Not Cryptic
- Use minimal words without sacrificing clarity (“Provisioning your cluster…”).

### Prioritize Clarity Over Cleverness
- Avoid jargon unless the audience expects it.

### Show, Don’t Tell
- Let UI elements communicate actions; avoid redundant instructions.

### Use Sentence Case Everywhere (Except Buttons/Links)
- Example: “Confirm your order.”

### Error Messages Should Be Helpful, Not Alarming
- Calm, constructive language (“Server is temporarily unavailable. Try again in a few minutes.”).

### CTA Buttons Should Be Actionable
- Avoid vague labels like “Submit” unless paired with context.

### Use Progressive Disclosure for Complex Information
- Reveal advanced settings on demand (“Show advanced settings”).

### Default to a Professional, Neutral Tone
- Balance warmth with clarity; avoid emotive emojis unless intentional.

### Confirm Actions with Context
- After key actions, state the result and next step (“View it live at @yourdomain.com.”).

### Avoid Passive Voice
- “Deploying your cluster…” instead of “Clusters are being deployed.”

### Keep the UI Copy Consistent
- Align term usage across every surface.

### Assume the User Knows What They’re Doing
- Link to docs instead of over-explaining fundamentals.

### If It’s Not Necessary, Remove It
- Cut any copy that doesn’t drive action or clarity.

## Escalation Rules
- Block publication if copy violates clarity, accuracy, or compliance guardrails.
- Loop in legal/compliance when messaging touches regulated commitments or timelines.

## Behavior Contributions
When new copy patterns emerge (e.g., standard runbook confirmation language), propose behaviors with triggers and validation steps so the handbook evolves alongside the product.
