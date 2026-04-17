"""Lightweight OSS project service for personal projects.

Provides basic project CRUD against PostgreSQL without requiring the
enterprise OrganizationService. Orgs are an enterprise feature — this
service handles personal (user-owned) projects only.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .contracts import (
    AgentPresenceResponse,
    PresenceStatus,
    Project,
    ProjectAgentAssignmentResponse,
    ProjectAgentRole,
    ProjectAgentStatus,
    ProjectVisibility,
)
from amprealize.perf_log import perf_span

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Module-level cache: `auth.project_collaborators` is an optional enterprise
# table. Probing `to_regclass` on every `list_project_participants` call was
# the same pattern Phase A fixed for `information_schema.columns` — cheap per
# call but a wasted Neon round-trip we only need once. Keyed by DSN so the
# cache can't bleed across unrelated databases in tests.
_collaborators_table_probe_cache: Dict[str, bool] = {}


def _has_collaborators_table(cur, dsn: str) -> bool:
    cached = _collaborators_table_probe_cache.get(dsn)
    if cached is not None:
        return cached
    cur.execute("SELECT to_regclass('auth.project_collaborators')")
    found = cur.fetchone()[0] is not None
    _collaborators_table_probe_cache[dsn] = found
    return found


class OSSProjectService:
    """Minimal project service for OSS (personal projects, no org features).

    Implements the subset of OrganizationService methods used by projects_api.py.
    Backs onto the existing auth.projects / execution.project_agent_assignments tables.
    """

    def __init__(self, *, dsn: str) -> None:
        self._dsn = dsn
        self._engine = None

    def _get_conn(self):
        # Use the shared SQLAlchemy engine pool so the Neon connection
        # TCP+TLS+auth handshake (~75-150 ms each) is paid once per physical
        # connection, not per call. `raw_connection()` returns a pooled
        # psycopg2 connection whose `.close()` releases it back to the pool,
        # so existing `conn = self._get_conn(); try: ...; finally: conn.close()`
        # call sites continue to work unchanged.
        if self._engine is None:
            from amprealize.storage.postgres_pool import _get_engine  # lazy
            self._engine = _get_engine(self._dsn)
        return self._engine.raw_connection()

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def list_projects(
        self,
        owner_id: str,
        org_id: Optional[str] = None,
    ) -> List[Project]:
        """List projects owned by a user (personal projects)."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                if org_id:
                    cur.execute(
                        """
                        SELECT project_id, org_id, owner_id, name, slug,
                               description, visibility, settings,
                               created_at, updated_at
                        FROM auth.projects
                        WHERE owner_id = %s AND org_id = %s
                        ORDER BY created_at DESC
                        """,
                        (owner_id, org_id),
                    )
                else:
                    cur.execute(
                        """
                        SELECT project_id, org_id, owner_id, name, slug,
                               description, visibility, settings,
                               created_at, updated_at
                        FROM auth.projects
                        WHERE owner_id = %s
                        ORDER BY created_at DESC
                        """,
                        (owner_id,),
                    )
                rows = cur.fetchall()
                return [self._row_to_project(r) for r in rows]
        finally:
            conn.close()

    def create_project(
        self,
        *,
        name: str,
        owner_id: str,
        org_id: Optional[str] = None,
        slug: Optional[str] = None,
        description: Optional[str] = None,
        visibility: str = "private",
    ) -> Project:
        """Create a personal project."""
        project_id = f"proj-{uuid.uuid4().hex[:12]}"
        if not slug:
            slug = name.strip().lower().replace(" ", "-")
            import re
            slug = re.sub(r"[^a-z0-9-]", "", slug) or f"proj-{uuid.uuid4().hex[:8]}"

        now = _utc_now()
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO auth.projects
                        (project_id, org_id, owner_id, name, slug,
                         description, visibility, settings, created_by,
                         created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, '{}', %s, %s, %s)
                    RETURNING project_id
                    """,
                    (project_id, org_id, owner_id, name, slug,
                     description, visibility, owner_id, now, now),
                )
                conn.commit()
        finally:
            conn.close()

        return Project(
            id=project_id,
            org_id=org_id,
            owner_id=owner_id,
            name=name,
            slug=slug,
            description=description,
            visibility=ProjectVisibility(visibility) if visibility in ProjectVisibility.__members__.values() else ProjectVisibility.PRIVATE,
            settings={},
            created_at=now,
            updated_at=now,
        )

    def get_project(self, project_id: str) -> Optional[Project]:
        """Get a single project by ID."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT project_id, org_id, owner_id, name, slug,
                           description, visibility, settings,
                           created_at, updated_at
                    FROM auth.projects
                    WHERE project_id = %s
                    """,
                    (project_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_project(row)
        finally:
            conn.close()

    def get_projects(self, project_ids: List[str]) -> List[Project]:
        """Batch-load multiple projects by id in one round-trip.

        Callers that authorise N project ids before a batched workload
        (e.g. /v1/projects/agents/presence?project_ids=...) previously paid
        N Neon round-trips walking `get_project` per id. This collapses that
        to a single `WHERE project_id = ANY(%s)` SELECT. Missing ids are
        silently omitted; the caller is responsible for comparing input vs
        output length / membership to detect access violations.
        """
        if not project_ids:
            return []
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                with perf_span("projects.get_projects_batch") as span:
                    span["id_count"] = len(project_ids)
                    cur.execute(
                        """
                        SELECT project_id, org_id, owner_id, name, slug,
                               description, visibility, settings,
                               created_at, updated_at
                        FROM auth.projects
                        WHERE project_id = ANY(%s)
                        """,
                        (list(project_ids),),
                    )
                    rows = cur.fetchall()
                    span["row_count"] = len(rows)
                    return [self._row_to_project(r) for r in rows]
        finally:
            conn.close()

    def list_project_participants(
        self,
        project_id: str,
    ) -> List[Dict[str, Any]]:
        """List all project-scoped participants.

        Previously ran up to four sequential queries — project+owner,
        project_memberships, a `to_regclass` probe, (conditional)
        project_collaborators, and project_agent_assignments — which added
        up to the slowest projects endpoint (~2.4s p50 on Neon cloud-dev).
        Now runs the existence probe once per process (module-level cache)
        and the data load as a single UNION ALL with a `kind` discriminator
        so PostgreSQL returns every participant row in one round-trip.

        Includes:
        - project owner
        - explicit project memberships
        - collaborators on shared personal projects (when table exists)
        - assigned agents
        """
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                with perf_span("projects.list_participants_query") as span:
                    has_collab = _has_collaborators_table(cur, self._dsn)
                    span["has_collab_table"] = has_collab

                    # Each UNION branch emits the same 14 columns. `sort_priority`
                    # pins owner→members→collaborators→agents; `sort_ts` preserves
                    # the original per-branch ORDER BYs (created_at / invited_at /
                    # assigned_at ASC) while NULLS FIRST keeps owner (ts=NULL) at
                    # the head of its group.
                    branches: List[str] = []
                    params: List[Any] = []

                    branches.append(
                        """
                        SELECT 'owner'::text       AS kind,
                               p.owner_id          AS id,
                               p.owner_id          AS user_id,
                               NULL::text          AS agent_id,
                               owner.display_name  AS display_name,
                               owner.email         AS email,
                               'owner'::text       AS role,
                               'owner'::text       AS membership_source,
                               NULL::text          AS agent_slug,
                               NULL::text          AS description,
                               NULL::text          AS assignment_status,
                               NULL::text          AS presence_status,
                               0                   AS sort_priority,
                               NULL::timestamptz   AS sort_ts
                        FROM auth.projects p
                        LEFT JOIN auth.users owner ON owner.id = p.owner_id
                        WHERE p.project_id = %s
                        """
                    )
                    params.append(project_id)

                    branches.append(
                        """
                        SELECT 'member'::text             AS kind,
                               pm.user_id                 AS id,
                               pm.user_id                 AS user_id,
                               NULL::text                 AS agent_id,
                               u.display_name             AS display_name,
                               u.email                    AS email,
                               COALESCE(pm.role, 'contributor') AS role,
                               'project_membership'::text AS membership_source,
                               NULL::text                 AS agent_slug,
                               NULL::text                 AS description,
                               NULL::text                 AS assignment_status,
                               NULL::text                 AS presence_status,
                               1                          AS sort_priority,
                               pm.created_at              AS sort_ts
                        FROM auth.project_memberships pm
                        LEFT JOIN auth.users u ON u.id = pm.user_id
                        WHERE pm.project_id = %s
                        """
                    )
                    params.append(project_id)

                    if has_collab:
                        branches.append(
                            """
                            SELECT 'collaborator'::text          AS kind,
                                   pc.user_id                    AS id,
                                   pc.user_id                    AS user_id,
                                   NULL::text                    AS agent_id,
                                   u.display_name                AS display_name,
                                   u.email                       AS email,
                                   COALESCE(pc.role, 'contributor') AS role,
                                   'project_collaborator'::text  AS membership_source,
                                   NULL::text                    AS agent_slug,
                                   NULL::text                    AS description,
                                   NULL::text                    AS assignment_status,
                                   NULL::text                    AS presence_status,
                                   2                             AS sort_priority,
                                   pc.invited_at                 AS sort_ts
                            FROM auth.project_collaborators pc
                            LEFT JOIN auth.users u ON u.id = pc.user_id
                            WHERE pc.project_id = %s
                            """
                        )
                        params.append(project_id)

                    branches.append(
                        """
                        SELECT 'agent'::text          AS kind,
                               pa.agent_id            AS id,
                               NULL::text             AS user_id,
                               pa.agent_id            AS agent_id,
                               a.name                 AS display_name,
                               NULL::text             AS email,
                               COALESCE(pa.role, 'primary') AS role,
                               NULL::text             AS membership_source,
                               a.slug                 AS agent_slug,
                               a.description          AS description,
                               COALESCE(pa.status, 'active') AS assignment_status,
                               COALESCE(ap.presence_status,
                                   CASE
                                       WHEN pa.status = 'active'   THEN 'available'
                                       WHEN pa.status = 'inactive' THEN 'paused'
                                       ELSE 'offline'
                                   END
                               )                      AS presence_status,
                               3                      AS sort_priority,
                               pa.assigned_at         AS sort_ts
                        FROM execution.project_agent_assignments pa
                        LEFT JOIN execution.agents a ON a.agent_id = pa.agent_id
                        LEFT JOIN execution.agent_presence ap
                            ON ap.agent_id = pa.agent_id AND ap.project_id = pa.project_id
                        WHERE pa.project_id = %s
                          AND pa.status <> 'removed'
                        """
                    )
                    params.append(project_id)

                    sql = (
                        "\nUNION ALL\n".join(branches)
                        + "\nORDER BY sort_priority ASC, sort_ts ASC NULLS FIRST"
                    )
                    cur.execute(sql, tuple(params))
                    rows = cur.fetchall()
                    span["row_count"] = len(rows)

                # If the owner branch returned no rows, the project either
                # doesn't exist or has no owner. Preserve the pre-B3 behaviour
                # of returning `[]` in that case so the API does not leak
                # orphaned membership/agent rows for deleted projects.
                has_owner_row = any(r[0] == "owner" for r in rows)
                if not has_owner_row:
                    return []

                participants: List[Dict[str, Any]] = []
                seen_humans: set[str] = set()

                def _add_human(
                    user_id: Optional[str],
                    role: str,
                    membership_source: str,
                    display_name: Optional[str],
                    email: Optional[str],
                ) -> None:
                    if not user_id or user_id in seen_humans:
                        return
                    seen_humans.add(user_id)
                    participants.append({
                        "id": user_id,
                        "kind": "human",
                        "user_id": user_id,
                        "display_name": display_name,
                        "email": email,
                        "role": role,
                        "membership_source": membership_source,
                    })

                for row in rows:
                    (
                        kind, row_id, user_id, agent_id,
                        display_name, email, role, membership_source,
                        agent_slug, description, assignment_status,
                        presence_status, _sort_priority, _sort_ts,
                    ) = row
                    if kind in ("owner", "member", "collaborator"):
                        _add_human(
                            user_id,
                            role or "contributor",
                            membership_source or kind,
                            display_name,
                            email,
                        )
                    elif kind == "agent":
                        participants.append({
                            "id": agent_id,
                            "kind": "agent",
                            "agent_id": agent_id,
                            "display_name": display_name,
                            "agent_slug": agent_slug,
                            "description": description,
                            "role": role or "primary",
                            "assignment_status": assignment_status or "active",
                            "presence": presence_status or "offline",
                        })

                return participants
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Project-Agent Assignments
    # ------------------------------------------------------------------

    def list_user_project_agent_assignments(
        self,
        owner_id: str,
        project_id: Optional[str] = None,
    ) -> List[ProjectAgentAssignmentResponse]:
        """List agent assignments for projects owned by a user."""
        with perf_span(
            "projects.list_user_agents",
            owner_id=owner_id,
            project_id=project_id,
        ):
            conn = self._get_conn()
            try:
                with conn.cursor() as cur:
                    if project_id:
                        cur.execute(
                            """
                            SELECT pa.id, pa.project_id, pa.agent_id,
                                   pa.assigned_by, pa.assigned_at,
                                   pa.config_overrides, pa.role, pa.status,
                                   a.name as agent_name, a.slug as agent_slug,
                                   a.description as agent_description
                            FROM execution.project_agent_assignments pa
                            JOIN auth.projects p ON p.project_id = pa.project_id
                            LEFT JOIN execution.agents a ON a.agent_id = pa.agent_id
                            WHERE p.owner_id = %s AND pa.project_id = %s
                            ORDER BY pa.assigned_at DESC
                            """,
                            (owner_id, project_id),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT pa.id, pa.project_id, pa.agent_id,
                                   pa.assigned_by, pa.assigned_at,
                                   pa.config_overrides, pa.role, pa.status,
                                   a.name as agent_name, a.slug as agent_slug,
                                   a.description as agent_description
                            FROM execution.project_agent_assignments pa
                            JOIN auth.projects p ON p.project_id = pa.project_id
                            LEFT JOIN execution.agents a ON a.agent_id = pa.agent_id
                            WHERE p.owner_id = %s
                            ORDER BY pa.assigned_at DESC
                            """,
                            (owner_id,),
                        )
                    rows = cur.fetchall()
                    return [self._row_to_agent_assignment(r) for r in rows]
            finally:
                conn.close()

    def list_project_agent_assignments(
        self,
        project_id: str,
    ) -> List[ProjectAgentAssignmentResponse]:
        """List agent assignments for a specific project."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pa.id, pa.project_id, pa.agent_id,
                           pa.assigned_by, pa.assigned_at,
                           pa.config_overrides, pa.role, pa.status,
                           a.name as agent_name, a.slug as agent_slug,
                           a.description as agent_description
                    FROM execution.project_agent_assignments pa
                    LEFT JOIN execution.agents a ON a.agent_id = pa.agent_id
                    WHERE pa.project_id = %s
                    ORDER BY pa.assigned_at DESC
                    """,
                    (project_id,),
                )
                rows = cur.fetchall()
                return [self._row_to_agent_assignment(r) for r in rows]
        finally:
            conn.close()

    def assign_registry_agent_to_project(
        self,
        *,
        project_id: str,
        agent_id: str,
        assigned_by: str,
        config_overrides: Optional[Dict[str, Any]] = None,
        role: ProjectAgentRole = ProjectAgentRole.PRIMARY,
    ) -> ProjectAgentAssignmentResponse:
        """Assign a registry agent to a project.

        Inserts the assignment and, in the same round-trip, joins to
        `execution.agents` so the returned response carries the full
        (name, slug, description) shape the REST layer exposes. Previously
        this returned a bare assignment with `name=""` and the handler had
        to issue a second `list_project_agent_assignments` SELECT just to
        pick the freshly-inserted row back out — two Neon round-trips per
        create. CTE collapses that to one.
        """
        import json

        assignment_id = f"pa-{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        config = config_overrides or {}

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH inserted AS (
                        INSERT INTO execution.project_agent_assignments
                            (id, project_id, agent_id, assigned_by, assigned_at,
                             config_overrides, role, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id, project_id, agent_id, assigned_by,
                                  assigned_at, config_overrides, role, status
                    )
                    SELECT ins.id, ins.project_id, ins.agent_id,
                           ins.assigned_by, ins.assigned_at,
                           ins.config_overrides, ins.role, ins.status,
                           a.name AS agent_name, a.slug AS agent_slug,
                           a.description AS agent_description
                    FROM inserted ins
                    LEFT JOIN execution.agents a ON a.agent_id = ins.agent_id
                    """,
                    (assignment_id, project_id, agent_id, assigned_by, now,
                     json.dumps(config), role.value, ProjectAgentStatus.ACTIVE.value),
                )
                row = cur.fetchone()
                conn.commit()
        finally:
            conn.close()

        if row is not None:
            return self._row_to_agent_assignment(row)

        # Defensive fallback — should not trigger because the CTE RETURNING
        # guarantees at least one row, but keep the original response shape
        # so a schema mismatch surfaces as a degraded (blank name) response
        # rather than an exception.
        return ProjectAgentAssignmentResponse(
            id=assignment_id,
            project_id=project_id,
            agent_id=agent_id,
            name="",
            assigned_by=assigned_by,
            assigned_at=now,
            config=config,
            role=role,
            status=ProjectAgentStatus.ACTIVE,
        )

    def remove_project_agent_assignment(
        self,
        *,
        assignment_id: str,
        removed_by: str,
    ) -> bool:
        """Remove an agent assignment."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM execution.project_agent_assignments WHERE id = %s",
                    (assignment_id,),
                )
                removed = cur.rowcount > 0
                conn.commit()
                return removed
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_project(row) -> Project:
        """Convert a DB row tuple to a Project contract."""
        import json

        (project_id, org_id, owner_id, name, slug,
         description, visibility, settings,
         created_at, updated_at) = row

        if isinstance(settings, str):
            settings = json.loads(settings)
        elif settings is None:
            settings = {}

        vis = ProjectVisibility.PRIVATE
        if visibility:
            try:
                vis = ProjectVisibility(visibility)
            except ValueError:
                pass

        return Project(
            id=project_id,
            org_id=org_id,
            owner_id=owner_id or "",
            name=name or "",
            slug=slug or "",
            description=description,
            visibility=vis,
            settings=settings,
            created_at=created_at,
            updated_at=updated_at,
        )

    @staticmethod
    def _row_to_agent_assignment(row) -> ProjectAgentAssignmentResponse:
        """Convert a DB row tuple to a ProjectAgentAssignmentResponse."""
        import json

        (assign_id, project_id, agent_id,
         assigned_by, assigned_at,
         config_overrides, role, assign_status,
         agent_name, agent_slug, agent_description) = row

        # SQLAlchemy's psycopg2 dialect enables `register_uuid()` on engine
        # init, so UUID columns now return `uuid.UUID` instances rather than
        # bare strings (the pre-pool `psycopg2.connect()` default). Coerce
        # the identifier columns the Pydantic contract expects as `str`.
        if assign_id is not None and not isinstance(assign_id, str):
            assign_id = str(assign_id)
        if agent_id is not None and not isinstance(agent_id, str):
            agent_id = str(agent_id)

        if isinstance(config_overrides, str):
            config_overrides = json.loads(config_overrides)
        elif config_overrides is None:
            config_overrides = {}

        try:
            role_enum = ProjectAgentRole(role)
        except (ValueError, KeyError):
            role_enum = ProjectAgentRole.PRIMARY

        try:
            status_enum = ProjectAgentStatus(assign_status)
        except (ValueError, KeyError):
            status_enum = ProjectAgentStatus.ACTIVE

        return ProjectAgentAssignmentResponse(
            id=assign_id,
            project_id=project_id,
            agent_id=agent_id,
            name=agent_name or "",
            agent_name=agent_name,
            agent_slug=agent_slug,
            agent_description=agent_description,
            assigned_by=assigned_by,
            assigned_at=assigned_at or _utc_now(),
            config=config_overrides,
            role=role_enum,
            status=status_enum,
        )

    # ------------------------------------------------------------------
    # Agent Presence
    # ------------------------------------------------------------------

    def list_agent_presence(
        self,
        project_id: str,
    ) -> List[AgentPresenceResponse]:
        """List presence state for all assigned agents in a project."""
        with perf_span("projects.list_agent_presence", project_id=project_id):
            conn = self._get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT ap.agent_id, ap.project_id,
                               ap.presence_status,
                               ap.last_activity_at, ap.last_completed_at,
                               ap.active_item_count, ap.capacity_max,
                               ap.current_work_item_id, ap.updated_at,
                               a.name as agent_name, a.slug as agent_slug
                        FROM execution.agent_presence ap
                        LEFT JOIN execution.agents a ON a.agent_id = ap.agent_id
                        WHERE ap.project_id = %s
                        ORDER BY ap.presence_status, a.name
                        """,
                        (project_id,),
                    )
                    rows = cur.fetchall()
                    return [self._row_to_presence(r) for r in rows]
            finally:
                conn.close()

    def list_agent_presence_batch(
        self,
        project_ids: List[str],
    ) -> Dict[str, List[AgentPresenceResponse]]:
        """Batched version of `list_agent_presence` for multiple projects.

        Single round-trip using `ANY(%s)`, returning a map of project_id to
        presence rows. Preserves per-project ordering (status, agent name).
        """
        if not project_ids:
            return {}
        # Dedupe while preserving order for a stable response.
        seen: Dict[str, None] = {}
        for pid in project_ids:
            if pid and pid not in seen:
                seen[pid] = None
        ordered_ids = list(seen.keys())
        with perf_span(
            "projects.list_agent_presence_batch",
            project_count=len(ordered_ids),
        ):
            conn = self._get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT ap.agent_id, ap.project_id,
                               ap.presence_status,
                               ap.last_activity_at, ap.last_completed_at,
                               ap.active_item_count, ap.capacity_max,
                               ap.current_work_item_id, ap.updated_at,
                               a.name as agent_name, a.slug as agent_slug
                        FROM execution.agent_presence ap
                        LEFT JOIN execution.agents a ON a.agent_id = ap.agent_id
                        WHERE ap.project_id = ANY(%s)
                        ORDER BY ap.project_id, ap.presence_status, a.name
                        """,
                        (ordered_ids,),
                    )
                    rows = cur.fetchall()
            finally:
                conn.close()
        out: Dict[str, List[AgentPresenceResponse]] = {pid: [] for pid in ordered_ids}
        for row in rows:
            presence = self._row_to_presence(row)
            out.setdefault(presence.project_id, []).append(presence)
        return out

    def update_agent_presence(
        self,
        *,
        agent_id: str,
        project_id: str,
        presence_status: Optional[PresenceStatus] = None,
        active_item_count: Optional[int] = None,
        capacity_max: Optional[int] = None,
        current_work_item_id: Optional[str] = None,
    ) -> AgentPresenceResponse:
        """Upsert an agent's presence state in a project."""
        import json

        now = _utc_now()
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO execution.agent_presence
                        (agent_id, project_id, presence_status,
                         active_item_count, capacity_max,
                         current_work_item_id, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (agent_id, project_id) DO UPDATE SET
                        presence_status = COALESCE(%s, execution.agent_presence.presence_status),
                        active_item_count = COALESCE(%s, execution.agent_presence.active_item_count),
                        capacity_max = COALESCE(%s, execution.agent_presence.capacity_max),
                        current_work_item_id = COALESCE(%s, execution.agent_presence.current_work_item_id),
                        updated_at = %s
                    RETURNING agent_id, project_id, presence_status,
                              last_activity_at, last_completed_at,
                              active_item_count, capacity_max,
                              current_work_item_id, updated_at
                    """,
                    (
                        agent_id, project_id,
                        (presence_status or PresenceStatus.OFFLINE).value,
                        active_item_count if active_item_count is not None else 0,
                        capacity_max if capacity_max is not None else 4,
                        current_work_item_id,
                        now,
                        # ON CONFLICT SET values
                        presence_status.value if presence_status else None,
                        active_item_count,
                        capacity_max,
                        current_work_item_id,
                        now,
                    ),
                )
                row = cur.fetchone()
                conn.commit()

                # Fetch agent name for the response
                cur.execute(
                    "SELECT name, slug FROM execution.agents WHERE agent_id = %s",
                    (agent_id,),
                )
                agent_row = cur.fetchone()
                agent_name = agent_row[0] if agent_row else ""
                agent_slug = agent_row[1] if agent_row else None

                return AgentPresenceResponse(
                    agent_id=row[0],
                    project_id=row[1],
                    name=agent_name,
                    agent_slug=agent_slug,
                    presence_status=PresenceStatus(row[2]),
                    last_activity_at=row[3],
                    last_completed_at=row[4],
                    active_item_count=row[5],
                    capacity_max=row[6],
                    current_work_item_id=row[7],
                    updated_at=row[8],
                )
        finally:
            conn.close()

    @staticmethod
    def _row_to_presence(row) -> AgentPresenceResponse:
        """Convert a DB row tuple to an AgentPresenceResponse."""
        (agent_id, project_id,
         presence_status,
         last_activity_at, last_completed_at,
         active_item_count, capacity_max,
         current_work_item_id, updated_at,
         agent_name, agent_slug) = row

        # See `_row_to_agent_assignment`: the SQLAlchemy psycopg2 dialect
        # returns UUID columns as `uuid.UUID` rather than `str`.
        if agent_id is not None and not isinstance(agent_id, str):
            agent_id = str(agent_id)
        if current_work_item_id is not None and not isinstance(current_work_item_id, str):
            current_work_item_id = str(current_work_item_id)

        try:
            status_enum = PresenceStatus(presence_status)
        except (ValueError, KeyError):
            status_enum = PresenceStatus.OFFLINE

        return AgentPresenceResponse(
            agent_id=agent_id,
            project_id=project_id,
            name=agent_name or "",
            agent_slug=agent_slug,
            presence_status=status_enum,
            last_activity_at=last_activity_at,
            last_completed_at=last_completed_at,
            active_item_count=active_item_count or 0,
            capacity_max=capacity_max or 4,
            current_work_item_id=current_work_item_id,
            updated_at=updated_at,
        )
