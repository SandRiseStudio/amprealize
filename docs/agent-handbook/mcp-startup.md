# Amprealize MCP Startup Protocol


At the start of every new agent session or Amprealize task, use the MCP server as the source of truth before searching manifests or guessing tool names:

1. Call `tools.guide` for the current startup protocol.
2. Call `auth.authStatus` before any non-auth Amprealize tool call.
3. If auth is expired but refreshable, call `auth.refreshToken` and re-check status. If login is needed, call `auth.deviceLogin` or `auth.deviceInit` + `auth.devicePoll`. In this MCP agent environment, device login/init is approved automatically after the auth tool call; do not ask the user to visit the URL unless polling explicitly cannot complete and the tool says manual consent is required.
4. If any Amprealize call returns unauthorized/auth expired, pause that workflow, complete the auth flow, then retry the original call.
5. Call `behaviors.getForTask` for task-specific behavior retrieval.
6. Call `context.getContext` to inspect active org/project/session defaults.
7. Call `tools.activeGroups` to see loaded groups.
8. Call `tools.catalog` with a `group`, `query`, or `use_case` before guessing tool names. Use `tools.listGroups` and `tools.activateGroup` when the needed domain is inactive.

Use catalog `original_name` values for docs and reasoning, and catalog `normalized_name` values for clients like Cursor that expose `workItems.get` as `workitems_get`. Prefer MCP session defaults for `user_id`, `org_id`, `project_id`, actor, and author fields.
