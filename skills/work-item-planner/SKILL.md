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

## MCP Workflow

1. Start with `tools.guide`, then use `tools.catalog` to confirm exact work item and board tool names before trying unfamiliar calls.
2. Check auth first with `auth.authStatus` / `amprealize/auth_authstatus`. If auth is expired but refreshable, call `auth.refreshToken`; if login is needed, call `auth.deviceLogin` or `auth.deviceInit` + `auth.devicePoll`. Device login/init is approved automatically in this MCP agent environment, so do not ask the user to visit the URL unless polling explicitly cannot complete.
3. If an Amprealize call returns unauthorized/auth expired, run the auth flow and retry the original call.
4. Retrieve active context first (`context.getContext` / `amprealize/context_getcontext`).
5. If the session has `project_id`, use it by default. Ask for a project only when missing, ambiguous, or overridden by the user.
6. Check for related or duplicate work with `board.filterItems` / `amprealize/board_filteritems`; fall back to `workItems.list` / `amprealize/workitems_list` for broad searches.
7. Create items top-down with `workItems.create` / `amprealize/workitems_create`:
   - create the goal first
   - use the returned goal ID as feature `parent_id`
   - use each returned feature ID as task/bug `parent_id`
8. Use `points`, never `story_points`.
9. Use session-backed defaults for `project_id`, `org_id`, `user_id`, and comment `author_id` when available.
10. Prefer `workItems.moveToColumn` for new instructions; `workItems.move` is compatibility-only.

## Amprealize Repo Parity

Amprealize platform work is dual-repo by default. When work items involve implementation, MCP tools, manifests, tests, docs, or timelines, plan for both the OSS `amprealize` checkout and the `amprealize-enterprise` checkout (typically a sibling directory; use `AMPREALIZE_ENTERPRISE_REPO_PATH` when not) unless the user explicitly says OSS-only or Enterprise-only.

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
