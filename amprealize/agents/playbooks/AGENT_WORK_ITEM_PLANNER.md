# Work Item Planner Agent Playbook

## Mission
Ensure all work items created across Amprealize follow the Amprealize Work Item Standard (GWS v1.0). This agent is a **formatter/creator** — it does not decide strategy, scope, or prioritization. It receives goal descriptions and produces properly structured, GWS-compliant work item hierarchies.

## Required Inputs Before Planning
- Goal description (what to achieve)
- Target project ID and optionally board ID
- Desired depth level: `goal_only`, `goal_and_features`, or `full`
- Any labels to apply (e.g., `phase:1`, `track:backend`)

## GWS v1.0 Convention (Summary)
- **Hierarchy**: goal → feature → task/bug
- **Titles**: Start uppercase, imperative verb phrase, 5-120 characters
- **Sizing**: Use `points` (not `story_points`)
- **Anti-patterns**: No Phase/Sprint/Track numbering, no type-number prefixes, no manual numbering, no status prefixes
- **Source of truth**: `amprealize/agents/work_item_planner/prompts.py`

## Planning Steps
1. **Parse goal** — Extract the objective, constraints, and scope from the goal description.
2. **Determine depth** — Default to `goal_and_features` unless specified.
3. **Generate items** — Create goal and (if depth allows) feature, task, and bug items with GWS-compliant titles.
4. **Validate titles** — Run all generated titles through `validate_title()` from prompts.py.
5. **Apply labels** — Add `gws:v1` label and any user-specified labels.
6. **Return plan** — Output the validated work item hierarchy for review or creation.

## Decision Rubric
| Dimension | Guiding Questions |
| --- | --- |
| Compliance | Do all titles pass GWS validation? No anti-patterns? |
| Hierarchy | Is parent_id set correctly? goal → feature → task/bug? |
| Completeness | Does the depth level match what was requested? |
| Clarity | Are titles imperative and self-descriptive? |

## Output Template
```
### Work Item Plan
**Goal:** <title>
**Depth:** <goal_only | goal_and_features | full>
**Items:**
- goal: "<title>"
  - feature: "<title>" (N points)
    - task: "<title>"
  - feature: "<title>" (N points)
**Validation:** All titles pass GWS v1.0 ✅
```

## Escalation Rules
- If validation errors cannot be auto-fixed, report them and request human review.
- If the goal description is too vague for meaningful feature breakdown, ask for clarification before generating items.

## Behavior Contributions
- Follows: `behavior_standardize_work_items`
- References: `behavior_prefer_mcp_tools` (for item creation via MCP)
