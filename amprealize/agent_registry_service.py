"""
Agent Registry Service - PostgreSQL-backed agent discovery and management.

Provides:
- CRUD operations for agents and agent versions
- Search and discovery with tags, capabilities, role_alignment filtering
- Publishing workflow (auto-publish for owners)
- Bootstrap from existing playbooks for builtin system agents
- Multi-tenant support via org_id

Follows patterns established in behavior_service.py.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from amprealize.agent_registry_contracts import (
    Agent,
    AgentSearchResult,
    AgentStatus,
    AgentVersion,
    AgentVisibility,
    CreateAgentRequest,
    CreateAgentResponse,
    CreateNewVersionRequest,
    DeprecateAgentRequest,
    ListAgentsRequest,
    PublishAgentRequest,
    RoleAlignment,
    SearchAgentsRequest,
    UpdateAgentRequest,
)
from amprealize.services.agent_loader import AgentPlaybookLoader, ParsedPlaybook
from amprealize.storage.postgres_pool import PostgresPool
from amprealize.utils.dsn import resolve_postgres_dsn
from amprealize.telemetry import TelemetryClient

# Import for optional ServicePrincipalService dependency
try:
    from amprealize.auth.service_principal_service import (
        ServicePrincipalService,
        CreateServicePrincipalRequest,
    )
    SERVICE_PRINCIPAL_AVAILABLE = True
except ImportError:
    SERVICE_PRINCIPAL_AVAILABLE = False
    ServicePrincipalService = None  # type: ignore[assignment, misc]
    CreateServicePrincipalRequest = None  # type: ignore[assignment, misc]

logger = logging.getLogger(__name__)


def _enum_value(v: Any) -> str:
    """Extract string value from enum or return string as-is."""
    return v.value if hasattr(v, 'value') else str(v)

# Environment variable for PostgreSQL DSN
_AGENT_REGISTRY_PG_DSN_ENV = "AMPREALIZE_AGENT_REGISTRY_PG_DSN"
_DEFAULT_PG_DSN = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"

# System owner ID for builtin agents
SYSTEM_OWNER_ID = "system"


def utc_now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def generate_slug(name: str) -> str:
    """Generate URL-safe slug from name."""
    # Convert to lowercase, replace spaces/underscores with hyphens
    slug = name.lower().strip()
    slug = re.sub(r"[_\s]+", "-", slug)
    # Remove non-alphanumeric characters (except hyphens)
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    # Remove multiple consecutive hyphens
    slug = re.sub(r"-+", "-", slug)
    # Strip leading/trailing hyphens
    return slug.strip("-")


@dataclass
class Actor:
    """Represents the actor performing an operation."""
    id: str
    role: str = "user"
    surface: str = "api"


class AgentRegistryError(Exception):
    """Base exception for agent registry errors."""
    pass


class AgentNotFoundError(AgentRegistryError):
    """Raised when an agent is not found."""
    pass


class AgentVersionNotFoundError(AgentRegistryError):
    """Raised when an agent version is not found."""
    pass


class AgentVersionError(AgentRegistryError):
    """Raised for version-related errors (invalid transitions, etc.)."""
    pass


class AgentRegistryService:
    """PostgreSQL-backed agent registry service.

    Uses the 'execution' schema in the consolidated database.
    """

    def __init__(
        self,
        *,
        dsn: Optional[str] = None,
        telemetry: Optional[TelemetryClient] = None,
        agents_dir: Optional[Path] = None,
        pool: Optional[PostgresPool] = None,
        service_principal_service: Optional["ServicePrincipalService"] = None,
    ) -> None:
        """Initialize agent registry service.

        Args:
            dsn: PostgreSQL connection string. Falls back to DATABASE_URL.
            telemetry: Telemetry client for event emission.
            agents_dir: Path to agents directory for playbook bootstrapping.
            pool: Optional pre-configured PostgresPool (takes precedence over dsn)
            service_principal_service: Optional ServicePrincipalService for creating
                API credentials when request_api_credentials=True.
        """
        self._telemetry = telemetry or TelemetryClient.noop()
        self._agents_dir = agents_dir
        self._playbook_loader: Optional[AgentPlaybookLoader] = None
        self._service_principal_service = service_principal_service

        if pool is not None:
            self._pool = pool
            self._dsn = None
        else:
            self._dsn = resolve_postgres_dsn(
                service="AGENT_REGISTRY",
                explicit_dsn=dsn,
                env_var=_AGENT_REGISTRY_PG_DSN_ENV,
                default_dsn=_DEFAULT_PG_DSN,
            )
            self._pool = PostgresPool(self._dsn)

    def _get_playbook_loader(self) -> AgentPlaybookLoader:
        """Lazy-load playbook loader."""
        if self._playbook_loader is None:
            self._playbook_loader = AgentPlaybookLoader(agents_dir=self._agents_dir)
        return self._playbook_loader

    # ------------------------------------------------------------------
    # Public API - CRUD Operations
    # ------------------------------------------------------------------

    def create_agent(
        self,
        request: CreateAgentRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> CreateAgentResponse:
        """Create a new agent.

        Args:
            request: Agent creation request data.
            actor: The actor creating the agent.
            org_id: Optional organization ID for multi-tenant isolation.

        Returns:
            CreateAgentResponse containing the agent and optional API credentials.
        """
        agent_id = str(uuid.uuid4())
        version = "1.0.0"
        timestamp = utc_now_iso()
        slug = request.slug or generate_slug(request.name)

        _org_id = org_id

        # Create service principal if requested and service is available
        service_principal_id: Optional[str] = None
        client_id: Optional[str] = None
        client_secret: Optional[str] = None

        if request.request_api_credentials:
            if not SERVICE_PRINCIPAL_AVAILABLE or self._service_principal_service is None:
                raise ValueError(
                    "API credentials requested but ServicePrincipalService is not available. "
                    "Ensure the auth module is properly installed."
                )

            # Create service principal for this agent
            sp_request = CreateServicePrincipalRequest(
                name=f"Agent: {request.name}",
                description=f"API credentials for agent '{request.name}' ({slug})",
                allowed_scopes=["read", "write", "execute"],  # Standard agent scopes
                role="STUDENT",  # Default role for agent credentials
                metadata={
                    "agent_slug": slug,
                    "created_for": "agent",
                },
            )
            sp_response = self._service_principal_service.create(
                sp_request,
                created_by=actor.id,
            )
            service_principal_id = sp_response.service_principal.id
            client_id = sp_response.service_principal.client_id
            client_secret = sp_response.client_secret

            logger.info(
                f"Created service principal {service_principal_id} for agent {slug}"
            )

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                # Set tenant context if org_id provided (for RLS)
                if _org_id:
                    cur.execute("SELECT set_config('app.current_org_id', %s, true)", (_org_id,))

                # Insert agent
                cur.execute(
                    """
                    INSERT INTO execution.agents (
                        agent_id, name, slug, description, tags, status, visibility,
                        owner_id, org_id, is_builtin, latest_version, created_at, updated_at,
                        service_principal_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        agent_id,
                        request.name,
                        slug,
                        request.description,
                        json.dumps(request.tags),
                        AgentStatus.DRAFT.value,
                        _enum_value(request.visibility),
                        actor.id,
                        _org_id,
                        False,  # User-created agents are not builtin
                        version,
                        timestamp,
                        timestamp,
                        service_principal_id,
                    ),
                )

                # Insert initial version
                cur.execute(
                    """
                    INSERT INTO execution.agent_versions (
                        agent_id, version, mission, role_alignment,
                        capabilities, default_behaviors, playbook_content, status,
                        effective_from, created_by, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        agent_id,
                        version,
                        request.mission,
                        _enum_value(request.role_alignment),
                        json.dumps(request.capabilities),
                        json.dumps(request.default_behaviors),
                        request.playbook_content or "",
                        AgentStatus.DRAFT.value,
                        timestamp,
                        actor.id,
                        timestamp,
                    ),
                )

        self._pool.run_transaction(
            operation="agent.create",
            service_prefix="agent_registry",
            actor=self._actor_payload(actor),
            metadata={
                "agent_id": agent_id,
                "version": version,
                "visibility": _enum_value(request.visibility),
                "has_api_credentials": request.request_api_credentials,
            },
            executor=_execute,
            telemetry=self._telemetry,
        )

        agent = self._fetch_agent(agent_id)
        self._telemetry.emit_event(
            event_type="agent_registry.agent_created",
            payload={
                "agent_id": agent_id,
                "name": request.name,
                "version": version,
                "visibility": _enum_value(request.visibility),
                "has_api_credentials": request.request_api_credentials,
            },
            actor=self._actor_payload(actor),
        )

        return CreateAgentResponse(
            agent=agent,
            client_id=client_id,
            client_secret=client_secret,
        )

    def update_agent(
        self,
        request: UpdateAgentRequest,
        actor: Actor,
    ) -> Agent:
        """Update an existing agent's metadata.

        Only updates agent-level fields (name, description, tags, visibility).
        Version content is updated via create_new_version.
        """
        agent = self._fetch_agent(request.agent_id)
        timestamp = utc_now_iso()

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                updates = []
                values = []

                if request.name is not None:
                    updates.append("name = %s")
                    values.append(request.name)
                    # Update slug too
                    updates.append("slug = %s")
                    values.append(generate_slug(request.name))

                if request.description is not None:
                    updates.append("description = %s")
                    values.append(request.description)

                if request.tags is not None:
                    updates.append("tags = %s")
                    values.append(json.dumps(request.tags))

                if request.visibility is not None:
                    updates.append("visibility = %s")
                    values.append(_enum_value(request.visibility))

                if updates:
                    updates.append("updated_at = %s")
                    values.append(timestamp)
                    values.append(request.agent_id)

                    cur.execute(
                        f"UPDATE execution.agents SET {', '.join(updates)} WHERE agent_id = %s",
                        values,
                    )

        self._pool.run_transaction(
            operation="agent.update",
            service_prefix="agent_registry",
            actor=self._actor_payload(actor),
            metadata={"agent_id": request.agent_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        updated = self._fetch_agent(request.agent_id)
        self._telemetry.emit_event(
            event_type="agent_registry.agent_updated",
            payload={"agent_id": request.agent_id},
            actor=self._actor_payload(actor),
        )

        return updated

    def get_agent(
        self,
        agent_id: str,
        version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get an agent with its versions.

        Args:
            agent_id: The agent ID.
            version: Optional specific version to return.

        Returns:
            Dict with 'agent' and 'versions' keys.
        """
        agent = self._fetch_agent(agent_id)
        versions = self._fetch_agent_versions(agent_id)

        if version:
            versions = [v for v in versions if v.version == version]
            if not versions:
                raise AgentVersionNotFoundError(
                    f"Version '{version}' not found for agent '{agent_id}'"
                )

        return {
            "agent": agent.to_dict(),
            "versions": [v.to_dict() for v in versions],
        }

    def delete_agent(
        self,
        agent_id: str,
        actor: Actor,
    ) -> None:
        """Delete an agent and all its versions.

        Only draft agents can be deleted. Published agents must be deprecated.
        """
        agent = self._fetch_agent(agent_id)

        if agent.status == AgentStatus.ACTIVE:
            raise AgentVersionError(
                "Cannot delete a published agent. Deprecate it instead."
            )

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                # Delete versions first (foreign key constraint)
                cur.execute(
                    "DELETE FROM execution.agent_versions WHERE agent_id = %s",
                    (agent_id,),
                )
                # Delete agent
                cur.execute(
                    "DELETE FROM execution.agents WHERE agent_id = %s",
                    (agent_id,),
                )

        self._pool.run_transaction(
            operation="agent.delete",
            service_prefix="agent_registry",
            actor=self._actor_payload(actor),
            metadata={"agent_id": agent_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        self._telemetry.emit_event(
            event_type="agent_registry.agent_deleted",
            payload={"agent_id": agent_id},
            actor=self._actor_payload(actor),
        )

    # ------------------------------------------------------------------
    # Public API - Versioning
    # ------------------------------------------------------------------

    def create_new_version(
        self,
        request: CreateNewVersionRequest,
        actor: Actor,
    ) -> AgentVersion:
        """Create a new version of an agent.

        Creates a new version based on the previous one with updates.
        """
        agent = self._fetch_agent(request.agent_id)
        current_version = self._fetch_latest_version(request.agent_id)

        # Calculate new version number
        parts = current_version.version.split(".")
        new_version = f"{parts[0]}.{int(parts[1]) + 1}.0"

        timestamp = utc_now_iso()

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO execution.agent_versions (
                        agent_id, version, mission, role_alignment,
                        capabilities, default_behaviors, playbook_content, status,
                        effective_from, created_from, created_by, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        request.agent_id,
                        new_version,
                        request.mission or current_version.mission,
                        (_enum_value(request.role_alignment) if request.role_alignment
                         else current_version.role_alignment.value),
                        json.dumps(request.capabilities or current_version.capabilities),
                        json.dumps(request.default_behaviors or current_version.default_behaviors),
                        request.playbook_content or current_version.playbook_content,
                        AgentStatus.DRAFT.value,
                        timestamp,
                        current_version.version,  # Track lineage
                        actor.id,
                        timestamp,
                    ),
                )

                # Update agent's latest_version
                cur.execute(
                    """
                    UPDATE execution.agents SET latest_version = %s, updated_at = %s
                    WHERE agent_id = %s
                    """,
                    (new_version, timestamp, request.agent_id),
                )

        self._pool.run_transaction(
            operation="agent.create_version",
            service_prefix="agent_registry",
            actor=self._actor_payload(actor),
            metadata={
                "agent_id": request.agent_id,
                "version": new_version,
                "created_from": current_version.version,
            },
            executor=_execute,
            telemetry=self._telemetry,
        )

        version = self._fetch_agent_version(request.agent_id, new_version)
        self._telemetry.emit_event(
            event_type="agent_registry.version_created",
            payload={
                "agent_id": request.agent_id,
                "version": new_version,
                "created_from": current_version.version,
            },
            actor=self._actor_payload(actor),
        )

        return version

    # ------------------------------------------------------------------
    # Public API - Publishing Workflow
    # ------------------------------------------------------------------

    def publish_agent(
        self,
        request: PublishAgentRequest,
        actor: Actor,
    ) -> Agent:
        """Publish an agent version, making it available for use.

        This is auto-publish: owner can publish immediately without approval.
        Previous published version is automatically deprecated.
        """
        agent = self._fetch_agent(request.agent_id)
        version = self._fetch_agent_version(request.agent_id, request.version)

        if version.status == AgentStatus.ACTIVE:
            raise AgentVersionError(f"Version {request.version} is already published.")

        if version.status == AgentStatus.DEPRECATED:
            raise AgentVersionError("Cannot publish a deprecated version.")

        timestamp = utc_now_iso()
        effective_from = request.effective_from or timestamp

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                # Deprecate previous published versions
                cur.execute(
                    """
                    UPDATE execution.agent_versions
                    SET status = %s, effective_to = %s
                    WHERE agent_id = %s
                      AND status = %s
                      AND version != %s
                    """,
                    (
                        AgentStatus.DEPRECATED.value,
                        effective_from,
                        request.agent_id,
                        AgentStatus.ACTIVE.value,
                        request.version,
                    ),
                )

                # Publish the new version
                cur.execute(
                    """
                    UPDATE execution.agent_versions
                    SET status = %s, effective_from = %s
                    WHERE agent_id = %s AND version = %s
                    """,
                    (
                        AgentStatus.ACTIVE.value,
                        effective_from,
                        request.agent_id,
                        request.version,
                    ),
                )

                # Update agent status
                cur.execute(
                    """
                    UPDATE execution.agents SET status = %s, updated_at = %s
                    WHERE agent_id = %s
                    """,
                    (AgentStatus.ACTIVE.value, timestamp, request.agent_id),
                )

        self._pool.run_transaction(
            operation="agent.publish",
            service_prefix="agent_registry",
            actor=self._actor_payload(actor),
            metadata={
                "agent_id": request.agent_id,
                "version": request.version,
            },
            executor=_execute,
            telemetry=self._telemetry,
        )

        published = self._fetch_agent(request.agent_id)
        self._telemetry.emit_event(
            event_type="agent_registry.agent_published",
            payload={
                "agent_id": request.agent_id,
                "version": request.version,
            },
            actor=self._actor_payload(actor),
        )

        return published

    def deprecate_agent(
        self,
        request: DeprecateAgentRequest,
        actor: Actor,
    ) -> Agent:
        """Deprecate an agent version.

        Deprecated agents remain visible but are marked as no longer recommended.
        """
        agent = self._fetch_agent(request.agent_id)
        version = self._fetch_agent_version(request.agent_id, request.version)

        if version.status != AgentStatus.ACTIVE:
            raise AgentVersionError("Only published versions can be deprecated.")

        timestamp = utc_now_iso()
        effective_to = request.effective_to or timestamp

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE execution.agent_versions
                    SET status = %s, effective_to = %s
                    WHERE agent_id = %s AND version = %s
                    """,
                    (
                        AgentStatus.DEPRECATED.value,
                        effective_to,
                        request.agent_id,
                        request.version,
                    ),
                )

                # Check if any non-deprecated versions remain
                cur.execute(
                    """
                    SELECT COUNT(*) FROM execution.agent_versions
                    WHERE agent_id = %s AND status != %s
                    """,
                    (request.agent_id, AgentStatus.DEPRECATED.value),
                )
                remaining = cur.fetchone()[0]

                if remaining == 0:
                    # All versions deprecated, mark agent as deprecated
                    cur.execute(
                        """
                        UPDATE execution.agents SET status = %s, updated_at = %s
                        WHERE agent_id = %s
                        """,
                        (AgentStatus.DEPRECATED.value, timestamp, request.agent_id),
                    )

        self._pool.run_transaction(
            operation="agent.deprecate",
            service_prefix="agent_registry",
            actor=self._actor_payload(actor),
            metadata={
                "agent_id": request.agent_id,
                "version": request.version,
                "successor_agent_id": request.successor_agent_id,
            },
            executor=_execute,
            telemetry=self._telemetry,
        )

        deprecated = self._fetch_agent(request.agent_id)
        self._telemetry.emit_event(
            event_type="agent_registry.agent_deprecated",
            payload={
                "agent_id": request.agent_id,
                "version": request.version,
                "successor_agent_id": request.successor_agent_id,
            },
            actor=self._actor_payload(actor),
        )

        return deprecated

    # ------------------------------------------------------------------
    # Public API - List and Search
    # ------------------------------------------------------------------

    def list_agents(
        self,
        request: Optional[ListAgentsRequest] = None,
        *,
        org_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List agents matching criteria.

        Args:
            request: Optional filter criteria.
            org_id: Optional org_id for tenant filtering.

        Returns:
            List of dicts with 'agent' and 'active_version' keys.
        """
        request = request or ListAgentsRequest()

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                # Build query with filters
                query = """
                    SELECT DISTINCT ON (a.agent_id)
                        a.agent_id, a.name, a.slug, a.description, a.tags,
                        a.status, a.visibility, a.owner_id, a.org_id, a.is_builtin,
                        a.latest_version, a.created_at, a.updated_at,
                        av.agent_id || ':' || av.version as version_id, av.version, av.mission, av.role_alignment,
                        av.capabilities, av.default_behaviors, av.playbook_content,
                        av.status as version_status, av.effective_from, av.effective_to,
                        av.created_from, av.created_by, av.created_at as version_created_at
                    FROM execution.agents a
                    LEFT JOIN execution.agent_versions av ON a.agent_id = av.agent_id
                        AND av.status = COALESCE(
                            (SELECT status FROM execution.agent_versions
                             WHERE agent_id = a.agent_id AND status = 'ACTIVE'
                             LIMIT 1),
                            a.status
                        )
                    WHERE 1=1
                """
                params: List[Any] = []

                if request.status:
                    query += " AND a.status = %s"
                    params.append(request.status.value)

                if request.visibility:
                    query += " AND a.visibility = %s"
                    params.append(_enum_value(request.visibility))

                if request.owner_id:
                    query += " AND a.owner_id = %s"
                    params.append(request.owner_id)

                if request.include_builtin is not None and not request.include_builtin:
                    query += " AND a.is_builtin = %s"
                    params.append(False)

                if org_id:
                    query += " AND (a.org_id = %s OR a.org_id IS NULL)"
                    params.append(org_id)
                else:
                    # Return only global agents when no org specified
                    query += " AND a.org_id IS NULL"

                query += " ORDER BY a.agent_id, av.effective_from DESC NULLS LAST"

                if request.limit:
                    query += f" LIMIT {request.limit}"

                cur.execute(query, params)
                rows = cur.fetchall()
                desc = cur.description

        results = []
        for row in rows:
            agent, version = self._row_to_agent_and_version(row, desc)
            results.append({
                "agent": agent.to_dict(),
                "active_version": version.to_dict() if version else None,
            })

        return results

    def search_agents(
        self,
        request: SearchAgentsRequest,
        actor: Optional[Actor] = None,
    ) -> List[AgentSearchResult]:
        """Search agents by query, tags, capabilities, role_alignment.

        Args:
            request: Search criteria.
            actor: Optional actor for telemetry.

        Returns:
            List of AgentSearchResult with relevance scores.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                # Build search query using full-text search
                # Using inline to_tsvector since we don't have a materialized search_vector column
                query = """
                    SELECT
                        a.agent_id, a.name, a.slug, a.description, a.tags,
                        a.status, a.visibility, a.owner_id, a.org_id, a.is_builtin,
                        a.latest_version, a.created_at, a.updated_at,
                        av.agent_id || ':' || av.version as version_id, av.version, av.mission, av.role_alignment,
                        av.capabilities, av.default_behaviors, av.playbook_content,
                        av.status as version_status, av.effective_from, av.effective_to,
                        av.created_from, av.created_by, av.created_at as version_created_at,
                        ts_rank_cd(to_tsvector('english', a.name || ' ' || a.description), plainto_tsquery('english', %s)) as score
                    FROM execution.agents a
                    LEFT JOIN execution.agent_versions av ON a.agent_id = av.agent_id
                        AND av.status = 'ACTIVE'
                    WHERE 1=1
                """
                params: List[Any] = [request.query or ""]

                # Text search filter
                if request.query:
                    query += " AND to_tsvector('english', a.name || ' ' || a.description) @@ plainto_tsquery('english', %s)"
                    params.append(request.query)

                # Status filter
                if request.status:
                    query += " AND a.status = %s"
                    params.append(request.status.value)

                # Role alignment filter
                if request.role_alignment:
                    query += " AND av.role_alignment = %s"
                    params.append(_enum_value(request.role_alignment))

                # Tags filter (must have all specified tags)
                if request.tags:
                    query += " AND a.tags @> %s"
                    params.append(json.dumps(request.tags))

                # Visibility filter (exclude private by default for non-owners)
                if request.visibility:
                    query += " AND a.visibility = %s"
                    params.append(_enum_value(request.visibility))
                else:
                    query += " AND a.visibility != %s"
                    params.append(AgentVisibility.PRIVATE.value)

                # Order by relevance score
                query += " ORDER BY score DESC, a.updated_at DESC"

                if request.limit:
                    query += f" LIMIT {request.limit}"

                cur.execute(query, params)
                rows = cur.fetchall()
                desc = cur.description

        results = []
        for row in rows:
            agent, version = self._row_to_agent_and_version(row, desc)
            # Score is the last column
            score = float(row[-1]) if row[-1] else 0.0

            results.append(AgentSearchResult(
                agent=agent,
                active_version=version,
                score=score,
            ))

        if actor:
            self._telemetry.emit_event(
                event_type="agent_registry.search",
                payload={
                    "query": request.query,
                    "result_count": len(results),
                    "filters": {
                        "status": request.status.value if request.status else None,
                        "role_alignment": _enum_value(request.role_alignment) if request.role_alignment else None,
                        "tags": request.tags,
                    },
                },
                actor=self._actor_payload(actor),
            )

        return results

    # ------------------------------------------------------------------
    # Bootstrap from Playbooks
    # ------------------------------------------------------------------

    def bootstrap_from_playbooks(
        self,
        actor: Optional[Actor] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Bootstrap builtin agents from playbook markdown files.

        Scans the agents/ directory for AGENT_*.md files and creates
        corresponding agents in the registry with is_builtin=True.

        Args:
            actor: Optional actor (defaults to system).
            force: If True, updates existing builtin agents.

        Returns:
            Summary of bootstrap operation.
        """
        actor = actor or Actor(id=SYSTEM_OWNER_ID, role="system", surface="bootstrap")
        loader = self._get_playbook_loader()
        playbooks = loader.load_all()

        created = []
        updated = []
        skipped = []
        errors = []

        for playbook in playbooks:
            try:
                # Check if agent already exists
                existing = self._find_agent_by_slug(playbook.agent_id)

                if existing and not force:
                    skipped.append(playbook.agent_id)
                    continue

                if existing:
                    # Update existing builtin agent
                    self._update_builtin_agent(existing, playbook, actor)
                    updated.append(playbook.agent_id)
                else:
                    # Create new builtin agent
                    self._create_builtin_agent(playbook, actor)
                    created.append(playbook.agent_id)

            except Exception as e:
                logger.error(f"Failed to bootstrap agent {playbook.agent_id}: {e}")
                errors.append({"agent_id": playbook.agent_id, "error": str(e)})

        result = {
            "total_playbooks": len(playbooks),
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }

        self._telemetry.emit_event(
            event_type="agent_registry.bootstrap_completed",
            payload=result,
            actor=self._actor_payload(actor),
        )

        logger.info(
            f"Bootstrap completed: {len(created)} created, {len(updated)} updated, "
            f"{len(skipped)} skipped, {len(errors)} errors"
        )

        return result

    def _create_builtin_agent(
        self,
        playbook: ParsedPlaybook,
        actor: Actor,
    ) -> Agent:
        """Create a builtin agent from a parsed playbook."""
        agent_id = str(uuid.uuid4())
        version = "1.0.0"
        timestamp = utc_now_iso()

        # Map role alignment string to enum
        role_alignment = RoleAlignment(playbook.role_alignment.upper())

        # Read full playbook content
        playbook_content = None
        if playbook.playbook_path:
            path = Path(playbook.playbook_path)
            if path.exists():
                playbook_content = path.read_text()

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                # Insert agent
                cur.execute(
                    """
                    INSERT INTO execution.agents (
                        agent_id, name, slug, description, tags, status, visibility,
                        owner_id, org_id, is_builtin, latest_version, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        agent_id,
                        playbook.display_name,
                        playbook.agent_id,  # Use agent_id as slug for builtins
                        playbook.raw_sections.get("Mission", "")[:500],  # Truncate for description
                        json.dumps(list(playbook.capabilities)[:10]),  # Use capabilities as tags
                        AgentStatus.ACTIVE.value,  # Builtins are published by default
                        AgentVisibility.PUBLIC.value,
                        SYSTEM_OWNER_ID,
                        None,  # No org_id for builtin agents
                        True,  # is_builtin
                        version,
                        timestamp,
                        timestamp,
                    ),
                )

                # Insert version
                cur.execute(
                    """
                    INSERT INTO execution.agent_versions (
                        agent_id, version, mission, role_alignment,
                        capabilities, default_behaviors, playbook_content, status,
                        effective_from, created_by, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        agent_id,
                        version,
                        playbook.raw_sections.get("Mission", ""),
                        role_alignment.value,
                        json.dumps(playbook.capabilities),
                        json.dumps(playbook.default_behaviors),
                        playbook_content,
                        AgentStatus.ACTIVE.value,
                        timestamp,
                        SYSTEM_OWNER_ID,
                        timestamp,
                    ),
                )

        self._pool.run_transaction(
            operation="agent.bootstrap_create",
            service_prefix="agent_registry",
            actor=self._actor_payload(actor),
            metadata={
                "agent_id": agent_id,
                "playbook_id": playbook.agent_id,
                "is_builtin": True,
            },
            executor=_execute,
            telemetry=self._telemetry,
        )

        return self._fetch_agent(agent_id)

    def _update_builtin_agent(
        self,
        existing: Agent,
        playbook: ParsedPlaybook,
        actor: Actor,
    ) -> None:
        """Update an existing builtin agent from playbook."""
        timestamp = utc_now_iso()

        # Create new version with updated content
        current_version = self._fetch_latest_version(existing.agent_id)
        parts = current_version.version.split(".")
        new_version = f"{parts[0]}.{int(parts[1]) + 1}.0"

        # Map role alignment
        role_alignment = RoleAlignment(playbook.role_alignment.upper())

        # Read playbook content
        playbook_content = None
        if playbook.playbook_path:
            path = Path(playbook.playbook_path)
            if path.exists():
                playbook_content = path.read_text()

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                # Deprecate old versions
                cur.execute(
                    """
                    UPDATE execution.agent_versions
                    SET status = %s, effective_to = %s
                    WHERE agent_id = %s AND status = %s
                    """,
                    (
                        AgentStatus.DEPRECATED.value,
                        timestamp,
                        existing.agent_id,
                        AgentStatus.ACTIVE.value,
                    ),
                )

                # Insert new version
                cur.execute(
                    """
                    INSERT INTO execution.agent_versions (
                        agent_id, version, mission, role_alignment,
                        capabilities, default_behaviors, playbook_content, status,
                        effective_from, created_from, created_by, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        existing.agent_id,
                        new_version,
                        playbook.raw_sections.get("Mission", ""),
                        role_alignment.value,
                        json.dumps(playbook.capabilities),
                        json.dumps(playbook.default_behaviors),
                        playbook_content,
                        AgentStatus.ACTIVE.value,
                        timestamp,
                        current_version.version,
                        SYSTEM_OWNER_ID,
                        timestamp,
                    ),
                )

                # Update agent metadata
                cur.execute(
                    """
                    UPDATE execution.agents
                    SET name = %s, description = %s, tags = %s,
                        latest_version = %s, updated_at = %s
                    WHERE agent_id = %s
                    """,
                    (
                        playbook.display_name,
                        playbook.raw_sections.get("Mission", "")[:500],
                        json.dumps(list(playbook.capabilities)[:10]),
                        new_version,
                        timestamp,
                        existing.agent_id,
                    ),
                )

        self._pool.run_transaction(
            operation="agent.bootstrap_update",
            service_prefix="agent_registry",
            actor=self._actor_payload(actor),
            metadata={
                "agent_id": existing.agent_id,
                "playbook_id": playbook.agent_id,
                "new_version": new_version,
            },
            executor=_execute,
            telemetry=self._telemetry,
        )

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _fetch_agent(self, agent_id: str) -> Agent:
        """Fetch a single agent by ID."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM execution.agents WHERE agent_id = %s",
                    (agent_id,),
                )
                row = cur.fetchone()
                desc = cur.description

        if row is None:
            raise AgentNotFoundError(f"Agent '{agent_id}' not found")

        return self._row_to_agent(row, desc)

    def _find_agent_by_slug(self, slug: str) -> Optional[Agent]:
        """Find an agent by slug."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM execution.agents WHERE slug = %s",
                    (slug,),
                )
                row = cur.fetchone()
                desc = cur.description

        if row is None:
            return None

        return self._row_to_agent(row, desc)

    def _fetch_agent_version(self, agent_id: str, version: str) -> AgentVersion:
        """Fetch a specific agent version."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM execution.agent_versions WHERE agent_id = %s AND version = %s",
                    (agent_id, version),
                )
                row = cur.fetchone()
                desc = cur.description

        if row is None:
            raise AgentVersionNotFoundError(
                f"Version '{version}' not found for agent '{agent_id}'"
            )

        return self._row_to_agent_version(row, desc)

    def _fetch_agent_versions(self, agent_id: str) -> List[AgentVersion]:
        """Fetch all versions for an agent."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM execution.agent_versions
                    WHERE agent_id = %s
                    ORDER BY status = 'ACTIVE' DESC, effective_from DESC NULLS LAST
                    """,
                    (agent_id,),
                )
                rows = cur.fetchall()
                desc = cur.description

        return [self._row_to_agent_version(row, desc) for row in rows]

    def _fetch_latest_version(self, agent_id: str) -> AgentVersion:
        """Fetch the latest version for an agent."""
        agent = self._fetch_agent(agent_id)
        return self._fetch_agent_version(agent_id, agent.latest_version)

    @staticmethod
    def _row_to_agent(row: tuple, description) -> Agent:
        """Convert database row to Agent object."""
        columns = [desc[0] for desc in description]
        data = dict(zip(columns, row))

        # Parse JSONB fields
        tags = data.get("tags", [])
        if isinstance(tags, str):
            tags = json.loads(tags)

        # Normalize enum values (DB stores lowercase, enums expect uppercase)
        status_value = data["status"]
        if isinstance(status_value, str):
            status_value = status_value.upper()
        visibility_value = data["visibility"]
        if isinstance(visibility_value, str):
            visibility_value = visibility_value.upper()

        return Agent(
            agent_id=str(data["agent_id"]),
            name=data["name"],
            slug=data["slug"],
            description=data["description"],
            tags=tags,
            status=AgentStatus(status_value),
            visibility=AgentVisibility(visibility_value),
            owner_id=data["owner_id"],
            org_id=data.get("org_id"),
            is_builtin=data.get("is_builtin", False),
            latest_version=data["latest_version"],
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            service_principal_id=data.get("service_principal_id"),
        )

    @staticmethod
    def _row_to_agent_version(row: tuple, description) -> AgentVersion:
        """Convert database row to AgentVersion object."""
        columns = [desc[0] for desc in description]
        data = dict(zip(columns, row))

        # Parse JSONB fields
        capabilities = data.get("capabilities", [])
        if isinstance(capabilities, str):
            capabilities = json.loads(capabilities)

        default_behaviors = data.get("default_behaviors", [])
        if isinstance(default_behaviors, str):
            default_behaviors = json.loads(default_behaviors)

        return AgentVersion(
            agent_id=str(data["agent_id"]),
            version=data["version"],
            mission=data.get("mission", ""),
            role_alignment=data["role_alignment"],
            capabilities=capabilities,
            default_behaviors=default_behaviors,
            playbook_content=data.get("playbook_content") or "",
            status=data["status"],
            effective_from=str(data["effective_from"]) if data.get("effective_from") else "",
            effective_to=str(data["effective_to"]) if data.get("effective_to") else None,
            created_from=data.get("created_from"),
            created_by=data.get("created_by") or "",
            created_at=str(data["created_at"]) if data.get("created_at") else "",
        )

    def _row_to_agent_and_version(
        self, row: tuple, description
    ) -> Tuple[Agent, Optional[AgentVersion]]:
        """Convert a joined row to Agent and AgentVersion objects."""
        columns = [desc[0] for desc in description]
        data = dict(zip(columns, row))

        # Parse agent fields
        tags = data.get("tags", [])
        if isinstance(tags, str):
            tags = json.loads(tags)

        # Normalize enum values (DB stores lowercase, enums expect uppercase)
        status_value = data["status"]
        if isinstance(status_value, str):
            status_value = status_value.upper()
        visibility_value = data["visibility"]
        if isinstance(visibility_value, str):
            visibility_value = visibility_value.upper()

        agent = Agent(
            agent_id=str(data["agent_id"]),
            name=data["name"],
            slug=data["slug"],
            description=data["description"],
            tags=tags,
            status=AgentStatus(status_value),
            visibility=AgentVisibility(visibility_value),
            owner_id=data["owner_id"],
            org_id=data.get("org_id"),
            is_builtin=data.get("is_builtin", False),
            latest_version=data["latest_version"],
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
        )

        # Parse version fields if present (version_id is synthetic: agent_id:version)
        version = None
        if data.get("version_id"):
            capabilities = data.get("capabilities", [])
            if isinstance(capabilities, str):
                capabilities = json.loads(capabilities)

            default_behaviors = data.get("default_behaviors", [])
            if isinstance(default_behaviors, str):
                default_behaviors = json.loads(default_behaviors)

            version = AgentVersion(
                agent_id=str(data["agent_id"]),
                version=data["version"],
                mission=data.get("mission", ""),
                role_alignment=data["role_alignment"],
                capabilities=capabilities,
                default_behaviors=default_behaviors,
                playbook_content=data.get("playbook_content") or "",
                status=data["version_status"],
                effective_from=str(data["effective_from"]) if data.get("effective_from") else "",
                effective_to=str(data["effective_to"]) if data.get("effective_to") else None,
                created_from=data.get("created_from"),
                created_by=data.get("created_by") or "",
                created_at=str(data["version_created_at"]) if data.get("version_created_at") else "",
            )

        return agent, version

    @staticmethod
    def _resolve_dsn(dsn: Optional[str]) -> str:
        """Resolve PostgreSQL DSN from argument or environment."""
        return resolve_postgres_dsn(
            service="AGENT_REGISTRY",
            explicit_dsn=dsn,
            env_var=_AGENT_REGISTRY_PG_DSN_ENV,
            default_dsn=_DEFAULT_PG_DSN,
        )

    @staticmethod
    def _actor_payload(actor: Actor) -> Dict[str, str]:
        """Convert Actor to telemetry payload."""
        return {
            "id": actor.id,
            "role": actor.role,
            "surface": actor.surface,
        }


# ------------------------------------------------------------------
# Convenience Functions
# ------------------------------------------------------------------

def get_agent_registry_service(
    dsn: Optional[str] = None,
    telemetry: Optional[TelemetryClient] = None,
) -> AgentRegistryService:
    """Get or create an AgentRegistryService instance.

    This is a convenience function for getting a service instance.
    For long-running processes, prefer creating a single instance.
    """
    return AgentRegistryService(dsn=dsn, telemetry=telemetry)


if __name__ == "__main__":
    # Simple test when run directly
    import sys

    logging.basicConfig(level=logging.DEBUG)

    service = AgentRegistryService()

    # Test bootstrap
    if len(sys.argv) > 1 and sys.argv[1] == "bootstrap":
        result = service.bootstrap_from_playbooks(force="--force" in sys.argv)
        print(json.dumps(result, indent=2))
    else:
        # List agents
        agents = service.list_agents()
        print(f"\nFound {len(agents)} agents:\n")
        for a in agents:
            agent = a["agent"]
            print(f"  {agent['slug']}: {agent['name']}")
            print(f"    Status: {agent['status']}, Builtin: {agent['is_builtin']}")
            if a.get("active_version"):
                v = a["active_version"]
                print(f"    Version: {v['version']} ({v['role_alignment']})")
            print()
