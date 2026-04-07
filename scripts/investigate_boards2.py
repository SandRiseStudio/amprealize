#!/usr/bin/env python3
"""Investigate what happened to boards and work items."""
import psycopg2

conn = psycopg2.connect("postgresql://amprealize:amprealize_dev@localhost:5432/amprealize")
cur = conn.cursor()

# Check board table stats
print("=== pg_stat for board schema ===")
cur.execute("""
    SELECT relname, n_tup_ins, n_tup_del, n_tup_upd
    FROM pg_stat_user_tables
    WHERE schemaname = 'board'
    ORDER BY relname
""")
for r in cur.fetchall():
    print(f"  {r[0]}: inserts={r[1]}, deletes={r[2]}, updates={r[3]}")

# Check audit log for board/work_item related entries
print("\n=== audit_log (board/work_item related) ===")
cur.execute("""
    SELECT id, event_type, actor_id, resource_type, resource_id, action, status, created_at
    FROM audit.audit_log
    WHERE resource_type LIKE '%board%' OR resource_type LIKE '%work_item%'
       OR event_type LIKE '%board%' OR event_type LIKE '%work_item%'
    ORDER BY created_at DESC
    LIMIT 30
""")
cols = [d[0] for d in cur.description]
rows = cur.fetchall()
for r in rows:
    d = dict(zip(cols, r))
    print(f"  {d}")
if not rows:
    print("  (no board-related audit entries)")

# Check if the board schema was recently dropped/recreated via alembic
print("\n=== alembic_version ===")
cur.execute("SELECT version_num FROM public.alembic_version")
for r in cur.fetchall():
    print(f"  {r[0]}")

# Check git log for recent migrations that touched board
print("\n=== board.columns (column definitions on boards table) ===")
cur.execute("SELECT * FROM board.columns LIMIT 5")
rows = cur.fetchall()
if rows:
    cols = [d[0] for d in cur.description]
    for r in rows:
        print(f"  {dict(zip(cols, r))}")
else:
    print("  (empty)")

# Try to find if boards were ever created by checking dead tuples
print("\n=== Dead tuples in board tables ===")
cur.execute("""
    SELECT relname, n_dead_tup, n_live_tup
    FROM pg_stat_user_tables
    WHERE schemaname = 'board'
""")
for r in cur.fetchall():
    print(f"  {r[0]}: live={r[2]}, dead={r[1]}")

# Check if there's a backup or WAL we could use
print("\n=== PostgreSQL version and WAL info ===")
cur.execute("SELECT version()")
print(f"  {cur.fetchone()[0]}")

# Check all board-schema tables with their row counts
print("\n=== Row counts for all board tables ===")
cur.execute("""
    SELECT table_name FROM information_schema.tables
    WHERE table_schema = 'board' ORDER BY table_name
""")
tables = [r[0] for r in cur.fetchall()]
for t in tables:
    cur.execute(f"SELECT COUNT(*) FROM board.{t}")
    count = cur.fetchone()[0]
    print(f"  board.{t}: {count} rows")

cur.close()
conn.close()
