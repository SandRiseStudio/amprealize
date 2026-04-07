-- Migration: Remove 'To Do' columns and 'todo'/'cancelled' statuses
-- Maps everything to the 4-column model: Backlog, In Progress, In Review, Done

BEGIN;

-- Board 0b08794b: has no Backlog column, only 'To Do'. Rename it.
UPDATE board.columns
SET name = 'Backlog', status_mapping = 'backlog', color = '#6B7280'
WHERE id = '6033870e-6eb9-4b62-b060-30162ccb65a1';

-- Board 0e66be3d: has both Backlog and To Do. Move items, delete To Do.
UPDATE board.work_items
SET column_id = '5c04fefb-a5c5-4808-9baf-ce40612291d0'
WHERE column_id = '8591e9ce-223e-42f2-8e21-409d89cbb1f2';

DELETE FROM board.columns WHERE id = '8591e9ce-223e-42f2-8e21-409d89cbb1f2';

UPDATE board.columns SET position = position - 1
WHERE board_id = '0e66be3d-e773-445f-afa4-92299d8f299d' AND position > 1;

-- Board 523b3a4f (Amprealize): has both Backlog and To Do. Move items, delete To Do.
UPDATE board.work_items
SET column_id = '5561dc09-30b0-4f07-84b3-0f5c57635322'
WHERE column_id = '02d4e038-203c-4718-9f50-4b67db7de09d';

DELETE FROM board.columns WHERE id = '02d4e038-203c-4718-9f50-4b67db7de09d';

UPDATE board.columns SET position = position - 1
WHERE board_id = '523b3a4f-4157-4fd1-b5e9-93437eca6009' AND position > 1;

-- Update all work items with old statuses
UPDATE board.work_items SET status = 'backlog' WHERE status = 'todo';
UPDATE board.work_items SET status = 'backlog' WHERE status = 'cancelled';

-- Fix orphaned work items (no column) - assign to first column of their board
UPDATE board.work_items wi
SET column_id = (
    SELECT c.id FROM board.columns c
    WHERE c.board_id = wi.board_id
    ORDER BY c.position LIMIT 1
)
WHERE wi.column_id IS NULL;

COMMIT;
