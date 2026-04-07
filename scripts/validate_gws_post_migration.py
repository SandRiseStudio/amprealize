#!/usr/bin/env python3
"""Post-migration validation: check all items pass GWS."""
import sys
sys.path.insert(0, ".")
import psycopg2
from amprealize.agents.work_item_planner.prompts import validate_title

DSN = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"
PROJECT_ID = "proj-b575d734aa37"

conn = psycopg2.connect(DSN)
cur = conn.cursor()
cur.execute(
    "SELECT id, title, item_type, display_number FROM board.work_items"
    " WHERE project_id = %s ORDER BY display_number NULLS LAST",
    (PROJECT_ID,),
)
rows = cur.fetchall()
conn.close()

violations = []
for item_id, title, item_type, dn in rows:
    itype = (item_type or "task").lower()
    err = validate_title(itype, title)
    if err:
        did = "amprealize-{}".format(dn) if dn else "None"
        violations.append((did, title, err))

print("Total items: {}".format(len(rows)))
print("Violations remaining: {}".format(len(violations)))
if violations:
    for did, title, err in violations:
        print("  {}: {}".format(did, repr(title)))
        print("    -> {}".format(err))
else:
    print("All items are GWS-compliant!")
