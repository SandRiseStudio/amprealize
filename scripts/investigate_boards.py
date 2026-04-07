#!/usr/bin/env python3
"""Investigate what happened to boards and work items."""
import psycopg2

conn = psycopg2.connect("postgresql://amprealize:amprealize_dev@localhost:5432/amprealize")
cur = conn.cursor()

# Check if there are any columns in the boards table
print("=== board.columns ===")
cur.execute("SELECT * FROM board.columns LIMIT 20")
cols = [d[0] for d in cur.description]
print(f"  Columns: {cols}")
for r in cur.fetchall():
    print(f"  {dict(zip(cols, r))}")

# Check sprints
print("\n=== board.sprints ===")
cur.execute("SELECT * FROM board.sprints LIMIT 10")
cols = [d[0] for d in cur.description]
for r in cur.fetchall():
    print(f"  {dict(zip(cols, r))}")
if cur.rowcount == 0:
    print("  (empty)")

# Check audit log for board-related operations
print("\n=== audit.audit_log (board related) ===")
cur.execute("""
    SELECT * FROM audit.audit_log
    WHERE service_prefix = 'board' OR operation LIKE '%board%' OR operation LIKE '%work_item%'
    ORDER BY created_at DESC
    LIMIT 20
""")
cols = [d[0] for d in cur.description]
for r in cur.fetchall():
    d = dict(zip(cols, r))
    print(f"  op={d.get('operation')}, actor={d.get('actor')}, meta={d.get('metadata')}, at={d.get('created_at')}")
if cur.rowcount == 0:
    print("  (no board audit entries)")

# Check if board schema was recently recreated (look at table creation times)
print("\n=== pg_stat_user_tables for board schema ===")
cur.execute("""
    SELECT relname, n_tup_ins, n_tup_del, n_tup_upd, last_vacuum, last_autovacuum, last_analyze
    FROM pg_stat_user_tables
    WHERE schemaname = 'board'
    ORDER BY relname
""")
for r in cur.fetchall():
    print(f"  table={r[0]}, inserts={r[1]}, deletes={r[2]}, updates={r[3]}")

# Check alembic migration history
print("\n=== alembic_version ===")
cur.execute("SELECT * FROM public.alembic_version")
for r in cur.fetchall():
    print(f"  {r}")

# Check for any recent DDL on board schema
print("\n=== Recent Alembic migrations (if tracked) ===")
try:
    cur.execute("""
        SELECT version_num FROM public.alembic_version
    """)
    for r in cur.fetchall():
        print(f"  Current version: {r[0]}")
except Exception as e:
    print(f"  Error: {e}")

# Check pg_stat for board tables - any activity?
print("\n=== board.work_items stats ===")
cur.execute("""
    SELECT seq_scan, seq_tup_read, idx_scan, idx_tup_fetch, n_tup_ins, n_tup_upd, n_tup_del
    FROM pg_stat_user_tables
    WHERE schemaname = 'board' AND relname = 'work_items'
""")
row = cur.fetchone()
if row:
    print(f"  seq_scan={row[0]}, seq_tup_read={row[1]}, idx_scan={row[2]}, inserts={row[4]}, updates={row[5]}, deletes={row[6]}")

# Look for board data in execution schema (some boards might have been created via runs)
print("\n=== execution.runs with board references ===")
try:
    cur.execute("""
        SELECT id, status, metadata
        FROM execution.runs
        WHERE metadata::text LIKE '%board%'
        LIMIT 5
    """)
    for r in cur.fetchall():
        print(f"  run={r[0]}, status={r[1]}, meta={r[2]}")
except Exception as e:
    print(f"  {e}")

cur.close()
conn.close()
