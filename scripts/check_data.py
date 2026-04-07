#!/usr/bin/env python3
"""Quick DB data check."""
import psycopg2

conn = psycopg2.connect("postgresql://amprealize:amprealize_dev@localhost:5432/amprealize")
cur = conn.cursor()

cur.execute("SELECT project_id, name, org_id, owner_id, created_by FROM auth.projects LIMIT 20")
rows = cur.fetchall()
print("=== auth.projects ===")
for r in rows:
    print(f"  project_id={r[0]}, name={r[1]}, org_id={r[2]}, owner_id={r[3]}, created_by={r[4]}")
print(f"  Total: {len(rows)}")

cur.execute("SELECT id, name, project_id, org_id FROM board.boards LIMIT 20")
rows = cur.fetchall()
print("\n=== board.boards ===")
for r in rows:
    print(f"  id={r[0]}, name={r[1]}, project_id={r[2]}, org_id={r[3]}")
print(f"  Total: {len(rows)}")

cur.execute("SELECT id, title, board_id, status, assignee_id, project_id, org_id FROM board.work_items LIMIT 20")
rows = cur.fetchall()
print("\n=== board.work_items ===")
for r in rows:
    print(f"  id={r[0]}, title={r[1]}, board={r[2]}, status={r[3]}, assignee={r[4]}, proj={r[5]}, org={r[6]}")
print(f"  Total: {len(rows)}")

cur.close()
conn.close()
