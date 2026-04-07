#!/usr/bin/env python3
"""Recreate boards for Amprealize and Windy projects after data loss."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from amprealize.services.board_service import BoardService, Actor
from amprealize.multi_tenant.board_contracts import CreateBoardRequest

DSN = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"
USER_ID = "112316240869466547718"

PROJECTS = [
    {"project_id": "proj-b575d734aa37", "name": "Amprealize Board", "description": "Amprealize platform issue tracking"},
    {"project_id": "proj-c3b47e3fd775", "name": "Windy Board", "description": "Windy SaaS learning platform"},
]

def main():
    svc = BoardService(dsn=DSN)
    actor = Actor(id=USER_ID, role="admin", surface="script")

    for p in PROJECTS:
        req = CreateBoardRequest(
            project_id=p["project_id"],
            name=p["name"],
            description=p["description"],
            is_default=True,
            create_default_columns=True,
        )
        board = svc.create_board(req, actor)
        print(f"Created board: {board.name} (board_id={board.board_id}) for project {p['project_id']}")
        print(f"  display_number={board.display_number}")

    # Verify
    import psycopg2
    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute("SET search_path = board, public;")
        cur.execute("SELECT b.id, b.name, b.project_id, b.display_number FROM boards b;")
        rows = cur.fetchall()
        print(f"\nBoards in DB ({len(rows)}):")
        for r in rows:
            print(f"  {r[1]} | id={r[0]} | project={r[2]} | display_number={r[3]}")

        cur.execute("SELECT c.id, c.board_id, c.name, c.position, c.color, c.status_mapping FROM columns c ORDER BY c.board_id, c.position;")
        rows = cur.fetchall()
        print(f"\nColumns in DB ({len(rows)}):")
        for r in rows:
            print(f"  [{r[3]}] {r[2]} | board={r[1]} | color={r[4]} | status={r[5]}")
    conn.close()
    print("\nDone!")

if __name__ == "__main__":
    main()
