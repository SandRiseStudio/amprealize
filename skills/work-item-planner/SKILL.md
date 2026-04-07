# Skill: Work Item Planner

**Slug**: `work-item-planner`
**Version**: 1.0
**Role**: Student (follows GWS v1.0 conventions)

## Purpose

Formats and creates GWS-compliant work items. This skill is a **formatter/creator only** — it does not decide strategy, prioritize, or scope work. It receives a goal description and produces properly structured work items.

## Input Contract

| Parameter    | Type    | Required | Default              | Description |
|-------------|---------|----------|----------------------|-------------|
| `goal`      | string  | yes      | —                    | Natural-language description of what to achieve |
| `project_id`| string  | yes      | —                    | Target project ID |
| `board_id`  | string  | no       | project default board| Target board ID |
| `depth`     | enum    | no       | `goal_and_features`  | `goal_only` \| `goal_and_features` \| `full` |
| `create`    | boolean | no       | `false`              | If true, create items via MCP; if false, return plan only |
| `labels`    | list    | no       | `[]`                 | Labels to apply to all created items |

## Output Contract

Returns a list of work item definitions:

```json
{
  "gws_version": "1.0",
  "depth": "goal_and_features",
  "work_items": [
    {
      "item_type": "goal",
      "title": "Standardize Work Item Creation Across Agents",
      "description": "...",
      "priority": "high",
      "labels": ["gws:v1"],
      "points": null,
      "parent_ref": null,
      "children": [
        {
          "item_type": "feature",
          "title": "Add GWS Title Validation to MCP Handler",
          "description": "...",
          "priority": "medium",
          "labels": ["gws:v1"],
          "points": 3,
          "parent_ref": "goal:0"
        }
      ]
    }
  ]
}
```

## Depth Levels

| Level | Creates | Use When |
|-------|---------|----------|
| `goal_only` | 1 goal | Quick tracking, epics only |
| `goal_and_features` | 1 goal + N features | Standard planning, team review |
| `full` | 1 goal + N features + M tasks/bugs | Sprint-ready, full breakdown |

## Validation

All generated titles are validated against GWS v1.0 patterns before output:
- Uppercase start, imperative verb phrase, 5-120 chars
- No Phase/Sprint/Track numbering (use labels)
- No type-number prefixes (system assigns IDs)
- No manual numbering (use position)
- No status prefixes (use status field)

## Usage

```python
from amprealize.agents.work_item_planner.planner import WorkItemPlanner

planner = WorkItemPlanner()
result = planner.plan(
    goal="Implement user authentication with OAuth2",
    project_id="proj_abc",
    depth="goal_and_features",
)
```

Or via MCP (when planner agent is registered):
```
mcp_amprealize_workitems_plan(
    goal="Implement user authentication with OAuth2",
    project_id="proj_abc",
    depth="goal_and_features"
)
```
