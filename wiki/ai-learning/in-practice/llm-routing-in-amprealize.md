---
title: "LLM Routing in Amprealize"
type: in-practice
difficulty: advanced
prerequisites:
  - concepts/agents.md
  - concepts/prompt-engineering.md
  - in-practice/context-composition.md
tags:
  - amprealize
  - llm-routing
  - governance
  - byok
last_updated: "2026-05-27"
sources:
  - "amprealize/chat_action_router.py"
  - "amprealize/chat_query_planner.py"
  - "amprealize/chat_workspace_targeted_fetch.py"
  - "amprealize/services/conversation_reply_service.py"
  - "amprealize/mcp/handlers/config_handlers.py"
  - "amprealize/web-console/src/api/conversations.ts"
  - "amprealize/web-console/src/components/projects/ProjectSettingsPage.tsx"
  - "amprealize/web-console/src/components/boards/WorkItemDrawer.tsx"
  - "amprealize/execution_gateway.py"
  - "amprealize/llm/types.py"
  - "amprealize/work_item_execution_service.py"
  - "amprealize/llm/model_readiness.py"
  - "amprealize/llm/credential_factory.py"
  - "amprealize/llm/byok_policy.py"
amprealize_relevance: "Explains how Amprealize lets chat choose models while preserving governed action routing and permission recomputation."
visibility: internal
---

# LLM Routing in Amprealize

## What It Is

LLM routing lets Amprealize use a language model to classify a chat message into a governed action, while still treating the existing typed route contract as the safety boundary. The model can propose a route, but it cannot invent permissions or grant itself approval.

## The Flow

```
Chat composer selects model
    ↓
Message metadata records provider/model/credential scope
    ↓
ChatRouteGateway chooses deterministic, LLM, or hybrid routing
    ↓
LLMChatActionRouter returns strict JSON candidates
    ↓
Post-validation rebuilds ChatActionCandidate
    ↓
Permission scopes and approval flags are recomputed from the permission matrix
    ↓
Conversation replies store route metadata and emit governed audit records
```

For read-only workspace answers, Amprealize now has a second, smaller planning layer inside `ConversationReplyService`: `ChatQueryPlanner` emits a typed `ChatQueryPlan` (`operation`, `resource_type`, `topic`, metrics, latency tier, confidence), deterministic validation checks scope and approval boundaries, then generic resource executors fetch and render data. This keeps project-board questions fast without creating a hardcoded detector for every phrasing.

## Safety Boundary

The LLM output is accepted only when it maps to known route categories, permission surfaces, permission actions, risk values, and action IDs. After parsing, Amprealize recomputes required scopes and approval flags with `get_chat_permission_requirement()` rather than trusting the model's text.

If the LLM returns invalid JSON, unknown actions, hallucinated enum values, or no candidates, routing falls back to the deterministic router and records the fallback reason in metadata.

## Model And Credential Selection

The web and VS Code chat composers pass `llm_model_id`, `llm_provider`, and `credential_scope` in message metadata. The backend validates that the selected model exists and that a user, project, org, or platform credential is available before persisting model metadata.

**Model readiness (2026-04):** REST exposes `GET /api/v1/model-readiness` and MCP exposes `config.getModelReadiness` with the same payload shape as `amprealize.llm.model_readiness.compute_model_readiness_payload`. The web console calls readiness before the first send and disables Send while `can_send` is false. REST and WebSocket both validate metadata through `validate_and_enrich_chat_message_metadata`, which uses a single `CredentialStore` built via `amprealize.llm.credential_factory.build_credential_store` so WebSocket chat no longer misses DB-backed BYOK. MCP `LLMClient` resolves keys through `execution_wiring._create_credential_resolver_from_store`, which maps each provider to a catalog model via `first_chat_model_id_for_provider` instead of a hard-coded short list.

Global/personal chat intentionally defaults to the NVIDIA free/open model plan for now. The user model availability endpoint defaults to `provider_filter=nvidia` and `free_open_only=true`, and the web console passes those query params explicitly so frontier platform models do not appear in the global chat selector. The curated global chat list maps the short product names to NVIDIA NIM API model names: DeepSeek V4 Flash (`deepseek-ai/deepseek-v4-flash`), DeepSeek V4 Pro (`deepseek-ai/deepseek-v4-pro`), MiniMax M2.7 (`minimaxai/minimax-m2.7`), Kimi K2 Thinking (`moonshotai/kimi-k2-thinking`), Qwen3 Coder (`qwen/qwen3-coder-480b-a35b-instruct`), GPT-OSS 120B (`openai/gpt-oss-120b`), Mistral Large 3 (`mistralai/mistral-large-3-675b-instruct-2512`), GLM 5.1 (`z-ai/glm-5.1`), Llama 3.1 Nemotron Ultra (`nvidia/llama-3.1-nemotron-ultra-253b-v1`), and Llama 3.3 70B (`meta/llama-3.3-70b-instruct`).

BYOK resolution keeps the fail-closed invariant: when a scoped key exists but is invalid, Amprealize does not silently fall back to a platform key for that provider.

Users manage personal BYOK provider keys from the web console account settings page at `/settings`. The UI calls the user-scoped credential endpoints through authenticated requests, stores only encrypted keys server-side, displays masked key prefixes, and invalidates model availability after add/delete/re-enable so global chat picks up newly saved NVIDIA keys without a manual refresh.

Project and work-item execution now reuse the same model availability payload. Project settings store `agent_model_preferences.default_model_id` in `auth.projects.settings`, and the work item drawer can pass a one-run `model_override` when starting execution. `ExecutionGateway._resolve_model` and the legacy work-item execution path apply the precedence `work item override -> project default -> agent policy preferred model -> policy fallbacks`, then resolve credentials through the existing project/org/platform BYOK order. That keeps user choice visible in the UI without bypassing provider credential governance.

## Key Files

- `amprealize/chat_action_router.py` — `ChatRouteGateway`, `LLMChatActionRouter`, and the deterministic fallback contract.
- `amprealize/services/conversation_reply_service.py` — live reply routing, selected model forwarding, route metadata, and governed audit records.
- `amprealize/services/conversation_api.py` — REST model metadata validation (shared readiness helper).
- `amprealize/services/conversation_events_api.py` — WebSocket model metadata transport and validation (same helper + pooled BYOK store).
- `amprealize/mcp/handlers/config_handlers.py` — model availability filtering and serialization.
- `amprealize/llm/types.py` — provider/model catalog, including NVIDIA NIM defaults.
- `amprealize/work_item_execution_service.py` — BYOK credential precedence and model availability.
- `amprealize/execution_gateway.py` — work-item execution model precedence and credential resolution.
- `web-console/src/components/projects/ProjectSettingsPage.tsx` — project-level agent model default picker.
- `web-console/src/components/boards/WorkItemDrawer.tsx` — per-run work item model override picker.
- `web-console/src/components/UserLLMCredentialsSection.tsx` — account settings UI for user-scoped BYOK keys.

## Read/Action Boundary (Deterministic Router)

The deterministic router enforces intent classification _before_ any LLM call. Three guards prevent execution false-positives:

- **Polar-question guard**: Messages matching `_POLAR_QUESTION_PHRASES` (e.g. "have we", "did we", "do we have") are skipped for `EXECUTION_START` unless an explicit imperative marker (`_IMPERATIVE_EXECUTION_MARKERS`) is also present.
- **Negated-execution guard**: Messages in `_NEGATED_EXECUTION_PHRASES` (e.g. "not asking you to execute", "asking you a question") are excluded from `EXECUTION_START` even if execution keywords appear.
- **Fast query planner before capability facts**: Project-scoped implementation/progress questions such as "from GuideAI, have we implemented agent execution?" are planned as `summarize_resources` over `work_items` with a topic such as `agent execution`. `_try_execution_capability_answer` remains a fallback for explicit platform-capability questions about Amprealize itself.

## Fast Chat Query Planner

The planner is intentionally smaller than the main answer model:

1. It receives only the user message, scope hints, compact inventory summary, allowed operations/resources, and user capability hints.
2. It returns strict JSON, not final answer prose.
3. `ChatQueryPlanValidator` rejects unsupported enum values, low confidence, inaccessible project scope, and mutating action plans that do not require approval.
4. `chat_plan_to_resource_query_plan()` converts valid read-only plans into `ResourceAnalysisService.answer_plan_sync()`.
5. `render_chat_plan_resource_answer()` renders common shapes such as work-item status breakdowns with matching item lists.

This gives Amprealize a generic path for "implementation status," "what is blocked," "which work items mention billing," and similar board/resource questions. The important distinction is that the model interprets intent, while deterministic code still owns permissions, action approval, execution, and telemetry.

When composed inventory is too sparse, `build_fetch_plan_from_chat_query_plan()` can turn a validated `work_items` + `topic` plan into project-scoped `BoardService.list_work_items(text_search=...)` calls. That extends retrieval without creating a new topic-specific route.

## Follow-up and Clarification Context

The clarification short-circuit (`answer_path="routing_clarification"`) can mask valid follow-up questions when routing assigns low confidence to a message that already has prior context. Two bypass conditions prevent this:

- **Referential follow-up**: If the message contains referential words ("these", "those", "it", "that board") and prior turns exist, `request.metadata["referential_followup"]` is `True` and the service uses `answer_path="llm_followup_bypass"` instead of the generic template.
- **Meta-correction**: If the message contains correction phrases ("I'm asking you a question", "that's not what I asked") and prior turns exist, `request.metadata["meta_correction"]` is `True` and the same bypass applies.

Both flags are injected by `_routing_tail_hints_sync` before the clarification guard evaluates.

## Answer Synthesis for Large Result Sets

When `ResourceAnalysisService._list_answer` receives more than `_SYNTHESIS_THRESHOLD` (15) rows, it returns a structured summary rather than a raw dump:

1. Total count ("I found 30 work items in this scope.")
2. Status breakdown ("Status breakdown: 20 todo, 10 done.")
3. Top 10 items as bullet points.
4. Overflow notice ("…and 20 more. Use a filter to narrow the list.")

This prevents LLM context overflow from large board inventories and gives users immediately actionable information.

## See Also

- [Agent Orchestration in Amprealize](agent-orchestration.md)
- [Context Composition in Amprealize](context-composition.md)
- [Prompt Engineering](../concepts/prompt-engineering.md)
