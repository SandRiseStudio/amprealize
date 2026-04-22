"""Load and persist global boolean rows in the ``feature_flags`` table."""

from __future__ import annotations

import logging
from typing import Dict

logger = logging.getLogger(__name__)

_GLOBAL_SCOPE = "global"
_GLOBAL_SCOPE_ID = "__global__"


def load_global_boolean_overrides(dsn: str) -> Dict[str, bool]:
    """Return ``flag_name -> enabled`` for global boolean flags. Empty on error."""
    try:
        import psycopg2
    except ImportError:
        logger.warning("psycopg2 not installed; feature flag DB overrides unavailable")
        return {}

    sql = """
        SELECT flag_name, enabled
        FROM feature_flags
        WHERE scope = %s AND scope_id = %s AND flag_type = %s
    """
    try:
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (_GLOBAL_SCOPE, _GLOBAL_SCOPE_ID, "boolean"))
                rows = cur.fetchall()
        return {str(r[0]): bool(r[1]) for r in rows}
    except Exception as exc:
        logger.warning("Could not load feature_flags overrides: %s", exc)
        return {}


def upsert_global_boolean(dsn: str, flag_name: str, enabled: bool) -> None:
    """Insert or update a global boolean flag row."""
    import psycopg2

    from psycopg2.extras import Json

    sql = """
        INSERT INTO feature_flags (
            flag_name, scope, scope_id, flag_type, enabled,
            percentage, user_list, description, metadata_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (flag_name, scope, scope_id)
        DO UPDATE SET
            enabled = EXCLUDED.enabled,
            flag_type = EXCLUDED.flag_type,
            updated_at = now()
    """
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    flag_name,
                    _GLOBAL_SCOPE,
                    _GLOBAL_SCOPE_ID,
                    "boolean",
                    enabled,
                    0,
                    [],
                    None,
                    Json({}),
                ),
            )
        conn.commit()
