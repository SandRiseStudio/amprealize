# EXPLAIN: board `list_work_items` (default sort)

Use this on the **same database** you benchmark (e.g. Neon cloud-dev) to
confirm the planner uses the board-item indexes from migration
`20260415_board_item_perf_indexes` (`revision = 20260415_board_item_perf_indexes`).

## 1. Confirm migration head

```bash
cd amprealize && alembic current
```

Expect revision `20260415_board_item_perf_indexes` or later on the chain.

## 2. Indexes created by that migration

- `board.idx_board_work_items_board_position_created_at` on `(board_id, position, created_at)`
- `board.idx_board_work_items_parent_id` on `(parent_id)` where `parent_id IS NOT NULL` (may be renamed from legacy)
- `board.idx_board_work_items_labels_gin` — GIN on `labels`

## 3. Representative EXPLAIN (board-only, default ORDER BY)

Replace `:board_id` with a UUID that has enough rows to matter.

The service uses a `WITH page AS (...)` CTE for the windowed rowset, then joins a **single**
grouped subquery over `work_items` children whose `parent_id` is in the page IDs (replaces
per-row `LATERAL` scans).

```sql
EXPLAIN (ANALYZE, BUFFERS)
WITH page AS (
  SELECT w.*, p.slug AS _project_slug,
         COUNT(*) OVER()::bigint AS _total
  FROM board.work_items w
  LEFT JOIN board.boards b ON w.board_id = b.id
  LEFT JOIN auth.projects p ON b.project_id = p.project_id AND p.archived_at IS NULL
  WHERE w.board_id = :board_id::uuid
  ORDER BY w.position, w.created_at
  LIMIT 100 OFFSET 0
)
SELECT page.*,
       COALESCE(ca.child_count, 0)::int AS _child_count,
       COALESCE(ca.completed_child_count, 0)::int AS _completed_child_count
FROM page
LEFT JOIN (
  SELECT children.parent_id AS pid,
         COUNT(*)::int AS child_count,
         COUNT(*) FILTER (WHERE children.status IN ('done'))::int AS completed_child_count
  FROM board.work_items children
  WHERE children.parent_id IN (SELECT id FROM page)
  GROUP BY children.parent_id
) ca ON ca.pid = page.id
ORDER BY page.position, page.created_at;
```

**Pass criteria for default board list:** the plan should **prefer** an
index that starts with `board_id` and supports the sort (often
`Index Scan` / `Bitmap Index Scan` on
`idx_board_work_items_board_position_created_at`), not a sequential scan
on the whole `work_items` table — unless the board is tiny (planner may
still choose seq scan).

## 4. With `include_total=True` (bootstrap / API)

The CTE SELECT includes `COUNT(*) OVER()` on the same rowset as `LIMIT`/`OFFSET`.
EXPLAIN the full statement from application logs or temporarily log the emitted SQL; expect
similar index use on the base scan with a **WindowAgg** node.

## 5. When indexes will not help

- Heavy filters (`title ILIKE`, many labels, complex joins) may force
  different plans; add narrow composite indexes only after EXPLAIN proves
  a regression.
- Wrong `search_path`: always qualify `board.work_items` in ad-hoc SQL.

Following `behavior_update_docs_after_changes` and `behavior_migrate_postgres_schema` (Student).
