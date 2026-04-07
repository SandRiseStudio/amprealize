<!-- GWS:START -->
## Work Item Naming Standard (GWS v1.0)

**Hierarchy**: goal → feature → task/bug

**Title rules**:
- Start with an uppercase letter
- Use imperative verb phrases: "Add X", "Implement Y", "Fix Z"
- 5-120 characters; letters, numbers, spaces, basic punctuation
- Sizing: use **points** (not story_points)
- Depth levels: `goal_only` | `goal_and_features` | `full`

**Forbidden title patterns** (use the indicated field instead):
| Pattern | Example | Use Instead |
|---------|---------|-------------|
| Phase/Sprint/Track numbering | "Phase 1: Work Items" | `labels: ["phase:1"]` |
| Type-number prefix | "EPIC-001 Foo" | system-assigned IDs |
| Manual numbering | "1. Do X" | `position` field |
| Status prefix | "TODO: Fix Y" | `status` field |
| Coded-section prefix | "A1: Setup Auth" | `labels: ["section:a1"]` |
| Bracket prefix | "[Bug] Fix crash" | `item_type` field |

**Good examples**:
- goal: "Standardize Work Item Creation Across Agents"
- feature: "Add GWS Title Validation to MCP Handler"
- task: "Write unit tests for title regex"
- bug: "Fix race condition in board column reorder"

When creating work items, always follow these conventions.
<!-- GWS:END -->
