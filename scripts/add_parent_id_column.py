#!/usr/bin/env python3
"""Add parent_id column to work_items table for hierarchy support."""
import psycopg2

def main():
    conn = psycopg2.connect('postgresql://amprealize:amprealize_dev@localhost:5432/amprealize')
    conn.autocommit = True
    with conn.cursor() as cur:
        # Set search path to include board schema
        cur.execute("SET search_path TO board, public")

        # Add parent_id column for hierarchy support
        cur.execute("""
            ALTER TABLE board.work_items
            ADD COLUMN IF NOT EXISTS parent_id UUID REFERENCES board.work_items(id) ON DELETE SET NULL
        """)
        print("Added parent_id column to board.work_items table")

        # Add index for efficient lookups
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_work_items_parent_id ON board.work_items(parent_id) WHERE parent_id IS NOT NULL
        """)
        print("Created index on parent_id")

        # Verify
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'board' AND table_name = 'work_items' AND column_name = 'parent_id'
        """)
        result = cur.fetchone()
        if result:
            print(f"Verification: parent_id column exists with type {result[1]}")
        else:
            print("ERROR: parent_id column not found!")
    conn.close()

if __name__ == '__main__':
    main()
