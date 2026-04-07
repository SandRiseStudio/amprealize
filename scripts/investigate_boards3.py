#!/usr/bin/env python3
"""Check board table metadata and pg_stat_statements."""
import psycopg2

conn = psycopg2.connect("postgresql://amprealize:amprealize_dev@localhost:5432/amprealize")
cur = conn.cursor()

# Check pg_stat_statements for truncate/drop on board
try:
    cur.execute("""
        SELECT query, calls, rows
        FROM pg_stat_statements
        WHERE query ILIKE '%truncate%board%' OR query ILIKE '%drop%board%'
        ORDER BY calls DESC LIMIT 10
    """)
    rows = cur.fetchall()
    print("=== pg_stat_statements (TRUNCATE/DROP board) ===")
    for r in rows:
        print(f"  query={r[0][:120]}, calls={r[1]}, rows={r[2]}")
    if not rows:
        print("  (none found)")
except Exception as e:
    print(f"pg_stat_statements not available: {e}")
    conn.rollback()

# Check table metadata
cur.execute("""
    SELECT c.relname,
           COALESCE(pg_stat_get_last_vacuum_time(c.oid)::text, 'never') as last_vacuum,
           COALESCE(pg_stat_get_last_autovacuum_time(c.oid)::text, 'never') as last_autovacuum,
           COALESCE(pg_stat_get_last_analyze_time(c.oid)::text, 'never') as last_analyze
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = 'board' AND c.relkind = 'r'
    ORDER BY c.relname
""")
print("\n=== board table vacuum/analyze times ===")
for r in cur.fetchall():
    print(f"  {r[0]}: vacuum={r[1]}, autovacuum={r[2]}, analyze={r[3]}")

# Check if any test recently ran that might have cleared data
cur.execute("""
    SELECT s.n_tup_ins, s.n_tup_del, s.n_tup_upd, s.n_live_tup, s.n_dead_tup,
           s.last_vacuum, s.last_autovacuum, s.last_analyze, s.last_autoanalyze
    FROM pg_stat_user_tables s
    WHERE s.schemaname = 'board' AND s.relname IN ('boards', 'work_items', 'columns')
""")
print("\n=== Detailed stats for boards/work_items/columns ===")
cols = [d[0] for d in cur.description]
for r in cur.fetchall():
    print(f"  {dict(zip(cols, r))}")

cur.close()
conn.close()
