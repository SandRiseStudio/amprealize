"""Lightweight OSS project service for personal projects.

Provides basic project CRUD against PostgreSQL without requiring the
enterprise OrganizationService. Orgs are an enterprise feature — this
service handles personal (user-owned) projects only.

Used as a fallback when amprealize-enterprise is not installed.
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

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OSSProjectService:
    """Minimal project service for OSS (personal projects, no org features).

    Implements the subset of OrganizationService methods used by projects_api.py.
    Backs onto the existing auth.projects / execution.project_agent_assignments tables.
    """

    def __init__(self, *, dsn: str) -> None:
        self._dsn = dsn

    def _get_conn(self):
        import psycopg2
        return psycopg2.connect(self._dsn)

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

    def list_project_participants(
        self,
        project_id: str,
    ) -> List[Dict[str, Any]]:
        """List all project-scoped participants.

        Includes:
        - project owner
        - explicit project memberships
        - collaborators on shared personal projects (when table exists)
        - assigned agents
        """
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT p.project_id,
                           p.owner_id,
                           p.org_id,
                           owner.display_name,
                           owner.email
                    FROM auth.projects p
                    LEFT JOIN auth.users owner ON owner.id = p.owner_id
                    WHERE p.project_id = %s
                    """,
                    (project_id,),
                )
                project_row = cur.fetchone()
                if project_row is None:
                    return []

                _, owner_id, _org_id, owner_display_name, owner_email = project_row

                participants: List[Dict[str, Any]] = []
                seen_humans: set[str] = set()

                def add_human(
                    *,
                    user_id: Optional[str],
                    role: str,
                    membership_source: str,
                    display_name: Optional[str] = None,
                    email: Optional[str] = None,
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

                add_human(
                    user_id=owner_id,
                    role="owner",
                    membership_source="owner",
                    display_name=owner_display_name,
                    email=owner_email,
                )

                cur.execute(
                    """
                    SELECT pm.user_id,
                           pm.role,
                           u.display_name,
                           u.email
                    FROM auth.project_memberships pm
                    LEFT JOIN auth.users u ON u.id = pm.user_id
                    WHERE pm.project_id = %s
                    ORDER BY pm.created_at ASC
                    """,
                    (project_id,),
                )
                for user_id, role, display_name, email in cur.fetchall():
                    add_human(
                        user_id=user_id,
                        role=role or "contributor",
                        membership_source="project_membership",
                        display_name=display_name,
                        email=email,
                    )

                cur.execute("SELECT to_regclass('auth.project_collaborators')")
                has_collaborators_table = cur.fetchone()[0] is not None
                if has_collaborators_table:
                    cur.execute(
                        """
                        SELECT pc.user_id,
                               pc.role,
                               u.display_name,
                               u.email
                        FROM auth.project_collaborators pc
                        LEFT JOIN auth.users u ON u.id = pc.user_id
                        WHERE pc.project_id = %s
                        ORDER BY pc.invited_at ASC
                        """,
                        (project_id,),
                    )
                    for user_id, role, display_name, email in cur.fetchall():
                        add_human(
                            user_id=user_id,
                            role=role or "contributor",
                            membership_source="project_collaborator",
                            display_name=display_name,
                            email=email,
                        )

                cur.execute(
                    """
                    SELECT pa.agent_id,
                           pa.role,
                           pa.status,
                           a.name,
                           a.slug,
                           a.description,
                           COALESCE(ap.presence_status,
                               CASE
                                   WHEN pa.status = 'active' THEN 'available'
                                   WHEN pa.status = 'inactive' THEN 'paused'
                                   ELSE 'offline'
                               END
                           ) AS presence_status
                    FROM execution.project_agent_assignments pa
                    LEFT JOIN execution.agents a ON a.agent_id = pa.agent_id
                    LEFT JOIN execution.agent_presence ap
                        ON ap.agent_id = pa.agent_id AND ap.project_id = pa.project_id
                    WHERE pa.project_id = %s
                      AND pa.status <> 'removed'
                    ORDER BY pa.assigned_at ASC
                    """,
                    (project_id,),
                )
                for agent_id, role, status, name, slug, description, presence_status in cur.fetchall():
                    participants.append({
                        "id": agent_id,
                        "kind": "agent",
                        "agent_id": agent_id,
                        "display_name": name,
                        "agent_slug": slug,
                        "description": description,
                        "role": role or "primary",
                        "assignment_status": status or "active",
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
        """Assign a registry agent to a project."""
        import json

        assignment_id = f"pa-{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        config = config_overrides or {}

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO execution.project_agent_assignments
                        (id, project_id, agent_id, assigned_by, assigned_at,
                         config_overrides, role, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (assignment_id, project_id, agent_id, assigned_by, now,
                     json.dumps(config), role.value, ProjectAgentStatus.ACTIVE.value),
                )
                conn.commit()
        finally:
            conn.close()

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
