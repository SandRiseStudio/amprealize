# Prior perf-work timeline

Distilled from [cursor_performance_issues_in_web_consol.md](../../../cursor_performance_issues_in_web_consol.md) (the 187KB export from the earlier Cursor session). Chronological, with hypothesis → change → observed outcome (as captured in that transcript).

1. **Initial report (~4/15/2026)**
   - *Symptom:* Cold open of the web console is slow — sidebar project names, dashboard header, work items, and the bottom chat bar all take a long time to populate. Only happens against Neon cloud postgres.
   - *Noise:* React "Encountered two children with the same key …" warnings in `BoardPage` / `ColumnLane`.
   - *First suspect:* duplicate keys causing extra reconciliation + data-shape problems.

2. **Round 1 implementation ("Implement the plan")**
   - *Hypothesis:* duplicates + sidebar N+1 `useBoards` per project + wasted `/dashboard/stats` fallback chain.
   - *Changes:* dedup inside `fetchAllWorkItems` + `hierarchyView` `useMemo`; introduce `useBoardsMultiProject` and pass boards down from `SidebarNav`/`Dashboard`; reduce `useDashboardStats` fallbacks; reduce org-endpoint probing.
   - *Outcome (per transcript):* duplicate-key warnings resolved; perceived load improved somewhat.

3. **User follow-up — still slow, plus `GET /v1/boards` 422s**
   - *Hypothesis:* backend requires `project_id` but `useBoardsMultiProject` was calling `/v1/boards` without one.
   - *Fix:* parallel per-project `GET /v1/boards?project_id=…` via `Promise.allSettled`.
   - *Outcome:* 422s gone.

4. **Neon vs local framing**
   - *Hypothesis:* RTT + number of round-trips dominates on Neon.
   - *Changes (frontend):* larger page size (up to 250), parallel page fetches, shorter sleep.
   - *Claimed outcome (assistant estimate in transcript):* ~1.35s → ~300ms for a 500-item board on Neon. Not independently verified.

5. **User: "still pretty slow"**
   - *Noted:* tail pagination still sequential; 15s work-item poll heavy; no virtualization yet.

6. **Round 2 plan**
   - *Backend:* honest `total`/`has_more` via counting; optional cursor pagination later; recommend Neon pooler DSN + `sslmode`; Podman not hosting DB for API reads.
   - *Frontend:* parallel tail batches; virtualize long columns.

7. **Round 2 implementation**
   - *Frontend:* parallel tail batches; `useWorkItems` poll `15s → 60s`; `staleTime: 3s → 20s`; `refetchOnWindowFocus: true`; `BoardPage` execution poll `10s → 30s`.
   - *Backend:* honest `count` + `list` for `GET /v1/work-items`; docs in `cloud-dev.yaml`.
   - *Noted risk:* every page now runs `COUNT + SELECT` — extra Neon load. Follow-up idea: `LIMIT+1` instead of full count.

8. **Round 3 (current uncommitted state, inferred from file contents)**
   - `include_total` param added; page 1 does full count, subsequent pages use `LIMIT+1`.
   - `useWorkItems` polling disabled entirely; progressive background pagination with `sleep(400)` between pages.
   - `@tanstack/react-virtual` gated at >80 rows with `deferColumnVirtualization` to avoid visible gaps during hydration.
   - `razeLog` milestones added for `board.shell_ready`, `board.first_items_page_ready`, `board.full_hydration_ready`, `dashboard.chrome_ready`, `dashboard.agent_panel_ready`.
   - `logger.info` timing added on every `GET /v1/work-items`.
   - Cloud-specific pool tuning in `postgres_pool.py` + one-time `SET search_path` per physical connection.
   - New migration for `work_items` indexes.

9. **User: "its still pretty slow"** — ongoing after rounds 1–3.

**Implication for this pass:** lots of plausible improvements have been layered together with no measurement, so wins and regressions are compounding. Phase 2 builds the harness needed to actually know.
