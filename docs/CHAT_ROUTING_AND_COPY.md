# Chat routing, scope hints, and user-visible copy

This note describes how workspace chat chooses **deterministic vs hybrid (LLM) routing**, how **project/board scope** is anchored, and where **user-visible strings** are reviewed.

## Routing modes

- **`AMPREALIZE_CHAT_ROUTE_MODE`** (default `deterministic`): global default for `ChatRouteGateway`.
- Per-request override: `metadata.chat_route_mode` on `ChatActionRouteRequest` / `ReplyRequest.metadata`.
- **`enrich_chat_routing_metadata(metadata, message)`** (in `chat_action_router.py`) copies metadata, sets **`chat_query_intent`**, and—unless `chat_route_mode` is already set—selects **`hybrid`** when intent is **`analytics_or_rate`** or **`ambiguous_scope`**. **`conversational_non_inventory`** is used for **reply fast-path** gating only (see below); it does **not** force hybrid action routing, to avoid unintended LLM router calls for simple chat.

### Intent buckets (`ChatWorkspaceIntent`)

| Intent | Typical triggers |
|--------|------------------|
| `list_inventory` | Default; questions that look like lists/counts without analytics or mutations |
| `mutate` | create, update, delete, run, execute, … |
| `analytics_or_rate` | velocity, throughput, lead/cycle time, how quickly, median/p95, or backlog + in-progress + time/moving wording |
| `ambiguous_scope` | “which board”, “what project”, … |
| `conversational_non_inventory` | Meta / capability / local access (e.g. who are you, what model, do you have access to paths or local files, can you read my disk) — not tabular workspace lists |

**Reply path note:** `chat_route_mode` on the **action router** (deterministic vs LLM routing for `ChatRouteGateway`) is separate from the **workspace inventory fast path** in `ConversationReplyService`. The fast path is additionally gated by **`should_use_workspace_inventory_fast_path`** in `chat_inventory_fast_path_policy.py`: intents **`conversational_non_inventory`**, **`ambiguous_scope`**, and **`workspace_prioritize`** always skip the inventory/resource-analysis shortcut so the **main LLM** (or targeted fetch / analysis runner) answers. When **`feature.chat_inventory_fast_path_strict`** is on, **`list_inventory`** only uses that fast path if the message matches a **tabular allowlist** and does not contain **conversational soft markers** (see policy module).

Conversation reply audit logs include **`chat_query_intent`** alongside **`chat_route_mode`** (merged from enriched routing metadata and the routed primary candidate).

## Principal data science system layer (LLM)

When **`ReplyRequest.system_prompt_override`** is unset, **`ConversationReplyService`** may append a compact **Principal data science operating mode** block to the default system prompt if any of the following hold:

- **`metadata.principal_data_science`** is true (explicit client opt-in).
- **`metadata.function_key`** or **`metadata.work_item_function_key`** is **`data_science`** (work routed to the Data Science function).
- **`detect_chat_workspace_intent(message)`** returns **`analytics_or_rate`** or **`ambiguous_scope`** (same heuristics as hybrid routing).
- The user message matches a bounded keyword hint (insights, dashboard, cohort, SQL, drift, hypothesis, visualization, etc.).

The suffix is defined in **`amprealize/services/conversation_reply_service.py`** as **`PRINCIPAL_DS_SYSTEM_SUFFIX`**; it points agents at **`behavior_principal_data_science_workflow`** and **`AGENT_DATA_SCIENCE.md`** without pasting the full playbook. Overrides always win: if a caller supplies **`system_prompt`**, no automatic append occurs.

## Chat analysis modes (Layer 1 / Layer 2)

Boolean flags (evaluated with **`user_id`** context only; **`org_id` is optional** on the platform):

| Flag | Purpose |
|------|---------|
| **`feature.chat_insight_narrator`** | After a deterministic **`resource_analysis`** fast-path hit, optionally appends a short LLM **interpretation** that must not invent new numbers (uses only structured JSON facts). Env override: `AMPREALIZE_ENABLE_CHAT_INSIGHT_NARRATOR` (default true). |
| **`feature.chat_analysis_runner`** | When the fast path **misses**, **`chat_query_intent`** is **`analytics_or_rate`** or **`ambiguous_scope`**, inventory is present, and the message is not a mutation, runs a **bounded** planner + up to 3 in-process **`ResourceAnalysisService.answer_sync`** calls. Results attach **`structured_payload.analysis_run.cells`** for UI transparency. Env override: `AMPREALIZE_ENABLE_CHAT_ANALYSIS_RUNNER` (default true). |
| **`feature.chat_query_planner`** | Before static topic-specific answer paths, uses a small strict-JSON planner to emit a typed `ChatQueryPlan` (`operation`, `resource_type`, `topic`, `metrics`, `latency_tier`, confidence). Deterministic validation enforces read/action boundaries, approval requirements, and accessible project scope before generic executors run. Env override: `AMPREALIZE_ENABLE_CHAT_QUERY_PLANNER` (default true). |
| **`feature.chat_inventory_fast_path_strict`** | When **on**, **`list_inventory`** messages only use the workspace inventory fast path if they match a **high-confidence tabular allowlist** and lack **soft conversational markers** (otherwise the main LLM answers). Env override: `AMPREALIZE_ENABLE_CHAT_INVENTORY_FAST_PATH_STRICT` (default false). |

Telemetry merges **`answer_path`** from the reply metadata (`deterministic`, **`chat_query_planner`**, **`analysis_runner`**, `platform_action`, or `llm`). Governed-chat audit records **`chat.analysis_runner.sub_query`** tool-style rows when an audit logger is wired.

## Fast chat query planning layer

`ConversationReplyService` now evaluates `ChatQueryPlanner` after context composition and before static capability answers. The planner returns a plan, not prose. Valid read-only plans execute through `ResourceAnalysisService.answer_plan_sync`; work-item topic plans can also derive a targeted `BoardService.list_work_items(text_search=...)` fetch plan when the composed inventory is too sparse.

For the GuideAI-style question, "from the GuideAI project, have we already implemented agent execution?", the planner should produce `operation=summarize_resources`, `resource_type=work_items`, `topic="agent execution"`, and metrics including `status_breakdown`. The renderer then leads with board progress and matching work items. Static platform capability facts remain available when the user explicitly asks whether Amprealize itself supports a capability.

## Scope hints (`ResourceAnalysisService.answer_sync`)

Optional **`scope_hints`** (`Mapping`):

- **`project_id`**: conversation default when the query does not name another project.
- **`board_id`**: from metadata or a **`resource_links`** entry with `resource_type` **`board`**.
- **`chat_query_intent`**: forwarded into answer **metadata** for Raze / tuning (see `_telemetry_extra_from_hints`).

`ConversationReplyService._workspace_scope_hints` builds this from `ReplyRequest`.

## User-visible copy (resource analysis)

- Machine codes stay in **`structured_payload.empty_reason`** and **`metadata.empty_reason`** (e.g. `empty_inventory`, `filters_excluded_all`, `ambiguous_board`, `insufficient_transition_timestamps`).
- **`ResourceAnalysisAnswer.content`** must stay free of implementation jargon such as **“inventory”**, **“rows”**, and **“filters”** in user-facing sentences.
- Raze event **`resource_analysis.completed`** includes **`empty_reason`** and **`chat_query_intent`** when present.

## Backlog → in-progress timing

When the question matches the backlog/in-progress velocity heuristic, the service computes **median and p95 hours** from per-row timestamps (`created_at` plus `in_progress_at` / `started_at` / related fields). If no row has usable transition timestamps, the user gets **`work_items.velocity.insufficient_data`**—no invented numbers.

## Read/action boundary (`chat_action_router.py`)

The router enforces a **read vs action** boundary so informational questions never trigger execution flows:

- **Polar-question guard**: Messages matching `_POLAR_QUESTION_PHRASES` (e.g. "have we", "did we", "do we have") do not produce `EXECUTION_START` candidates unless an explicit imperative marker from `_IMPERATIVE_EXECUTION_MARKERS` is also present.
- **Negated-execution guard**: Messages containing `_NEGATED_EXECUTION_PHRASES` (e.g. "not asking you to execute", "asking you a question") are excluded from `EXECUTION_START` routing even when action keywords like "execute" appear in context.
- **Capability and progress questions**: "have we implemented agent execution?" routes as `read`/`resource_analysis`, not `execution.start`. Project-scoped wording is handled first by the generic chat query planner over `work_items`; explicit platform-capability wording can still fall back to `_try_execution_capability_answer`.

## Follow-up and clarification context (`conversation_reply_service.py`)

The clarification short-circuit is bypassed when prior conversation context resolves ambiguity:

- **Referential follow-up detection**: If `request.metadata["referential_followup"]` is `True` (message contains "these", "those", "it", "that board", etc.) and prior turns exist (`has_prior_turns`), the service uses `answer_path="llm_followup_bypass"` instead of the generic "Please clarify..." template.
- **Meta-correction detection**: If `request.metadata["meta_correction"]` is `True` (message contains "I'm asking you a question", "that's not what I asked", etc.) and prior turns exist, the same bypass is applied.
- Hard clarification is preserved for genuinely ambiguous mutating actions without prior context.

## Work-item text search

`BoardService.list_work_items` accepts `text_search: Optional[str]` which filters by `(title ILIKE %s OR description ILIKE %s)`. The same parameter is exposed through:
- MCP handler `workItems.list` tool schema and `handle_list_work_items` / `handle_filter_items`
- Targeted fetch `FetchQuerySpec.text_search` and the LLM planner prompt
- `build_fetch_plan_from_chat_query_plan(...)` when a validated `ChatQueryPlan` asks for `work_items` with a `topic`
- `BoardPlatformManagementAdapter.list_work_items(payload)` via `payload["text_search"]`
- `ResourceAnalysisService._apply_filters` as an in-memory post-filter for inventory-based answers

## Large result-set synthesis (`resource_analysis.py`)

When a work-item query matches more than `_SYNTHESIS_THRESHOLD` (15) rows, `_list_answer` returns:
- A total count line ("I found N work items in this scope.")
- A status breakdown ("Status breakdown: X todo, Y done, …")
- The top `_INLINE_LIMIT` (10) items as bullet points
- A "…and N more. Use a filter to narrow the list." closing line

This replaces the previous behavior of dumping all rows inline.

## Review checklist

When changing chat or resource analysis:

1. Run `pytest tests/test_resource_analysis.py tests/test_chat_action_router.py tests/test_conversation_reply_routing.py tests/test_conversation_reply_followup_context.py tests/test_chat_inventory_fast_path_policy.py tests/test_chat_analysis_stack.py tests/test_mcp_board_workitem_handlers.py tests/test_platform_management_actions.py`.
2. Scan new **`content`** strings for banned jargon above.
3. If routing defaults change, update this doc and **`BUILD_TIMELINE.md`**.
