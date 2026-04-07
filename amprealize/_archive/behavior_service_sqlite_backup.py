"""BehaviorService runtime implementation with PostgreSQL persistence."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .action_contracts import Actor, utc_now_iso
from .telemetry import TelemetryClient

_BEHAVIOR_PG_DSN_ENV = "AMPREALIZE_BEHAVIOR_PG_DSN"
_DEFAULT_PG_DSN = "postgresql://amprealize_behavior:dev_behavior_pass@localhost:6433/behaviors"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Behavior:
    behavior_id: str
    name: str
    description: str
    tags: List[str]
    created_at: str
    updated_at: str
    latest_version: str
    status: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "behavior_id": self.behavior_id,
            "name": self.name,
            "description": self.description,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "latest_version": self.latest_version,
            "status": self.status,
        }


@dataclass(frozen=True)
class BehaviorVersion:
    behavior_id: str
    version: str
    instruction: str
    role_focus: str
    status: str
    trigger_keywords: List[str]
    examples: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    effective_from: str
    effective_to: Optional[str]
    created_by: str
    approval_action_id: Optional[str]
    embedding_checksum: Optional[str]
    embedding: Optional[List[float]] = None

    def to_dict(self, include_metadata: bool = True) -> Dict[str, Any]:
        payload = {
            "behavior_id": self.behavior_id,
            "version": self.version,
            "instruction": self.instruction,
            "role_focus": self.role_focus,
            "status": self.status,
            "trigger_keywords": list(self.trigger_keywords),
            "examples": [dict(example) for example in self.examples],
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "created_by": self.created_by,
            "approval_action_id": self.approval_action_id,
            "embedding_checksum": self.embedding_checksum,
        }
        if include_metadata:
            payload["metadata"] = dict(self.metadata)
            if self.embedding is not None:
                payload["embedding"] = list(self.embedding)
        return payload


@dataclass(frozen=True)
class BehaviorSearchResult:
    behavior: Behavior
    active_version: BehaviorVersion
    score: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "behavior": self.behavior.to_dict(),
            "active_version": self.active_version.to_dict(),
            "score": self.score,
        }


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


@dataclass
class CreateBehaviorDraftRequest:
    name: str
    description: str
    instruction: str
    role_focus: str
    trigger_keywords: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    examples: List[Dict[str, Any]] = field(default_factory=list)
    embedding: Optional[List[float]] = None
    base_version: Optional[str] = None


@dataclass
class UpdateBehaviorDraftRequest:
    behavior_id: str
    version: str
    instruction: Optional[str] = None
    description: Optional[str] = None
    trigger_keywords: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    examples: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None
    embedding: Optional[List[float]] = None


@dataclass
class ApproveBehaviorRequest:
    behavior_id: str
    version: str
    effective_from: str
    approval_action_id: Optional[str] = None


@dataclass
class DeprecateBehaviorRequest:
    behavior_id: str
    version: str
    effective_to: str
    successor_behavior_id: Optional[str] = None


@dataclass
class SearchBehaviorsRequest:
    query: Optional[str] = None
    tags: Optional[List[str]] = None
    role_focus: Optional[str] = None
    status: Optional[str] = None
    limit: int = 25


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BehaviorServiceError(Exception):
    """Base error for behavior operations."""


class BehaviorNotFoundError(BehaviorServiceError):
    """Raised when a behavior is missing."""


class BehaviorVersionError(BehaviorServiceError):
    """Raised when version transitions are invalid."""


class PersistenceError(BehaviorServiceError):
    """Raised when the underlying store fails."""


# ---------------------------------------------------------------------------
# BehaviorService implementation
# ---------------------------------------------------------------------------


class BehaviorService:
    """PostgreSQL-backed behavior service runtime."""

    def __init__(
        self,
        *,
        dsn: Optional[str] = None,
        telemetry: Optional[TelemetryClient] = None,
        behavior_retriever: Optional[Any] = None,
    ) -> None:
        self._dsn = self._resolve_dsn(dsn)
        self._telemetry = telemetry or TelemetryClient.noop()
        self._behavior_retriever = behavior_retriever
        self._conn = None
        self._connect()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_behavior_draft(self, request: CreateBehaviorDraftRequest, actor: Actor) -> BehaviorVersion:
        """Create a new behavior and initial draft version."""

        behavior_id = str(uuid.uuid4())
        version = "1.0.0"
        timestamp = utc_now_iso()
        embedding_checksum = self._calculate_embedding_checksum(request.embedding)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO behaviors (
                    behavior_id, name, description, tags, created_at, updated_at, latest_version, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    behavior_id,
                    request.name,
                    request.description,
                    json.dumps(request.tags),
                    timestamp,
                    timestamp,
                    version,
                    "DRAFT",
                ),
            )
            conn.execute(
                """
                INSERT INTO behavior_versions (
                    behavior_id,
                    version,
                    instruction,
                    role_focus,
                    status,
                    trigger_keywords,
                    examples,
                    metadata,
                    effective_from,
                    effective_to,
                    created_by,
                    approval_action_id,
                    embedding_checksum,
                    embedding
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    behavior_id,
                    version,
                    request.instruction,
                    request.role_focus,
                    "DRAFT",
                    json.dumps(request.trigger_keywords),
                    json.dumps(request.examples),
                    json.dumps(request.metadata),
                    timestamp,
                    None,
                    actor.id,
                    None,
                    embedding_checksum,
                    self._encode_embedding(request.embedding),
                ),
            )

        behavior = self._fetch_behavior(behavior_id)
        version_obj = self._fetch_behavior_version(behavior_id, version)
        self._telemetry.emit_event(
            event_type="behaviors.draft_created",
            payload={
                "behavior_id": behavior_id,
                "version": version,
                "tags": list(request.tags),
                "role_focus": request.role_focus,
            },
            actor=self._actor_payload(actor),
        )
        return version_obj

    def update_behavior_draft(self, request: UpdateBehaviorDraftRequest, actor: Actor) -> BehaviorVersion:
        """Update an existing draft or in-review behavior version."""

        version = self._fetch_behavior_version(request.behavior_id, request.version)
        if version.status not in {"DRAFT", "IN_REVIEW"}:
            raise BehaviorVersionError(
                f"Cannot update behavior {request.behavior_id} version {request.version}: status={version.status}"
            )

        updates: Dict[str, Any] = {}
        if request.instruction is not None:
            updates["instruction"] = request.instruction
        if request.trigger_keywords is not None:
            updates["trigger_keywords"] = json.dumps(request.trigger_keywords)
        if request.examples is not None:
            updates["examples"] = json.dumps(request.examples)
        if request.metadata is not None:
            updates["metadata"] = json.dumps(request.metadata)
        if request.embedding is not None:
            updates["embedding"] = self._encode_embedding(request.embedding)
            updates["embedding_checksum"] = self._calculate_embedding_checksum(request.embedding)
        if updates:
            updates["updated_fields"] = list(updates.keys())

        with self._connect() as conn:
            if updates:
                assignments = ", ".join(f"{column} = ?" for column in updates if column != "updated_fields")
                values = [value for key, value in updates.items() if key != "updated_fields"]
                values.extend([request.behavior_id, request.version])
                conn.execute(
                    f"UPDATE behavior_versions SET {assignments} WHERE behavior_id = ? AND version = ?",
                    tuple(values),
                )
            if request.description is not None or request.tags is not None:
                behavior_updates = {
                    "updated_at": utc_now_iso(),
                }
                if request.description is not None:
                    behavior_updates["description"] = request.description
                if request.tags is not None:
                    behavior_updates["tags"] = json.dumps(request.tags)
                assignments = ", ".join(f"{column} = ?" for column in behavior_updates)
                values = list(behavior_updates.values())
                values.extend([request.behavior_id])
                conn.execute(
                    f"UPDATE behaviors SET {assignments} WHERE behavior_id = ?",
                    tuple(values),
                )

        updated_version = self._fetch_behavior_version(request.behavior_id, request.version)
        self._telemetry.emit_event(
            event_type="behaviors.draft_updated",
            payload={
                "behavior_id": request.behavior_id,
                "version": request.version,
                "updated_fields": updates.get("updated_fields", []),
            },
            actor=self._actor_payload(actor),
        )
        return updated_version

    def submit_for_review(self, behavior_id: str, version: str, actor: Actor) -> BehaviorVersion:
        """Move a draft version into review."""

        version_obj = self._fetch_behavior_version(behavior_id, version)
        if version_obj.status != "DRAFT":
            raise BehaviorVersionError(
                f"Only drafts can be submitted for review (status={version_obj.status})."
            )
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE behavior_versions
                   SET status = ?, effective_from = ?
                 WHERE behavior_id = ? AND version = ?
                """,
                ("IN_REVIEW", utc_now_iso(), behavior_id, version),
            )
            conn.execute(
                "UPDATE behaviors SET status = ?, updated_at = ? WHERE behavior_id = ?",
                ("IN_REVIEW", utc_now_iso(), behavior_id),
            )
        updated = self._fetch_behavior_version(behavior_id, version)
        self._telemetry.emit_event(
            event_type="behaviors.submitted_for_review",
            payload={
                "behavior_id": behavior_id,
                "version": version,
            },
            actor=self._actor_payload(actor),
        )
        return updated

    def approve_behavior(self, request: ApproveBehaviorRequest, actor: Actor) -> BehaviorVersion:
        """Approve a behavior version and mark it active."""

        version_obj = self._fetch_behavior_version(request.behavior_id, request.version)
        if version_obj.status not in {"IN_REVIEW", "DRAFT"}:
            raise BehaviorVersionError(
                f"Cannot approve version with status={version_obj.status}."
            )

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE behavior_versions
                   SET status = ?, effective_from = ?, approval_action_id = ?
                 WHERE behavior_id = ? AND version = ?
                """,
                ("APPROVED", request.effective_from, request.approval_action_id, request.behavior_id, request.version),
            )
            conn.execute(
                """
                UPDATE behaviors
                   SET latest_version = ?, status = ?, updated_at = ?
                 WHERE behavior_id = ?
                """,
                (request.version, "APPROVED", utc_now_iso(), request.behavior_id),
            )
            conn.execute(
                """
                UPDATE behavior_versions
                   SET status = 'DEPRECATED', effective_to = ?
                 WHERE behavior_id = ? AND version != ? AND status = 'APPROVED' AND effective_to IS NULL
                """,
                (request.effective_from, request.behavior_id, request.version),
            )

        approved = self._fetch_behavior_version(request.behavior_id, request.version)
        self._telemetry.emit_event(
            event_type="behaviors.approved",
            payload={
                "behavior_id": request.behavior_id,
                "version": request.version,
                "approval_action_id": request.approval_action_id,
            },
            actor=self._actor_payload(actor),
        )

        # Trigger index rebuild when behaviors are approved
        if self._behavior_retriever is not None:
            try:
                rebuild_result = self._behavior_retriever.rebuild_index()
                self._telemetry.emit_event(
                    event_type="bci.behavior_retriever.auto_rebuild",
                    payload={
                        "trigger": "behavior_approved",
                        "behavior_id": request.behavior_id,
                        "version": request.version,
                        "rebuild_status": rebuild_result.get("status"),
                        "behavior_count": rebuild_result.get("behavior_count", 0),
                        "mode": rebuild_result.get("mode"),
                    },
                )
            except Exception as exc:
                # Log but don't fail approval if rebuild fails
                self._telemetry.emit_event(
                    event_type="bci.behavior_retriever.auto_rebuild_failed",
                    payload={
                        "trigger": "behavior_approved",
                        "behavior_id": request.behavior_id,
                        "error": str(exc),
                    },
                )

        return approved

    def deprecate_behavior(self, request: DeprecateBehaviorRequest, actor: Actor) -> BehaviorVersion:
        """Deprecate an active behavior version."""

        version_obj = self._fetch_behavior_version(request.behavior_id, request.version)
        if version_obj.status != "APPROVED":
            raise BehaviorVersionError("Only approved versions can be deprecated.")

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE behavior_versions
                   SET status = ?, effective_to = ?
                 WHERE behavior_id = ? AND version = ?
                """,
                ("DEPRECATED", request.effective_to, request.behavior_id, request.version),
            )
            conn.execute(
                "UPDATE behaviors SET status = ?, updated_at = ? WHERE behavior_id = ?",
                ("DEPRECATED", utc_now_iso(), request.behavior_id),
            )

        deprecated = self._fetch_behavior_version(request.behavior_id, request.version)
        self._telemetry.emit_event(
            event_type="behaviors.deprecated",
            payload={
                "behavior_id": request.behavior_id,
                "version": request.version,
                "successor_behavior_id": request.successor_behavior_id,
            },
            actor=self._actor_payload(actor),
        )
        return deprecated

    def delete_behavior_draft(self, behavior_id: str, version: str, actor: Actor) -> None:
        version_obj = self._fetch_behavior_version(behavior_id, version)
        if version_obj.status != "DRAFT":
            raise BehaviorVersionError("Only draft versions can be deleted.")
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM behavior_versions WHERE behavior_id = ? AND version = ?",
                (behavior_id, version),
            )
            remaining = conn.execute(
                "SELECT COUNT(*) FROM behavior_versions WHERE behavior_id = ?",
                (behavior_id,),
            ).fetchone()[0]
            if remaining == 0:
                conn.execute("DELETE FROM behaviors WHERE behavior_id = ?", (behavior_id,))
        self._telemetry.emit_event(
            event_type="behaviors.draft_deleted",
            payload={"behavior_id": behavior_id, "version": version},
            actor=self._actor_payload(actor),
        )

    def get_behavior(self, behavior_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        behavior = self._fetch_behavior(behavior_id)
        versions = self._fetch_behavior_versions(behavior_id)
        if version:
            versions = [v for v in versions if v.version == version]
            if not versions:
                raise BehaviorVersionError(f"Version {version} not found for behavior {behavior_id}")
        return {
            "behavior": behavior.to_dict(),
            "versions": [v.to_dict() for v in versions],
        }

    def list_behaviors(
        self,
        *,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None,
        role_focus: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = self._fetch_behaviors(status=status)
        results = []
        for behavior in rows:
            active_versions = self._fetch_behavior_versions(behavior.behavior_id)
            if role_focus:
                active_versions = [v for v in active_versions if v.role_focus == role_focus]
                if not active_versions:
                    continue
            if tags:
                if not set(tags).issubset(set(behavior.tags)):
                    continue
            results.append({
                "behavior": behavior.to_dict(),
                "active_version": active_versions[0].to_dict() if active_versions else None,
            })
        return results

    def search_behaviors(self, request: SearchBehaviorsRequest, actor: Optional[Actor] = None) -> List[BehaviorSearchResult]:
        query = (request.query or "").lower()
        behaviors = self._fetch_behaviors(status=request.status)
        matches: List[BehaviorSearchResult] = []
        for behavior in behaviors:
            versions = self._fetch_behavior_versions(behavior.behavior_id)
            active = next((v for v in versions if v.status == "APPROVED"), versions[0] if versions else None)
            if not active:
                continue
            if request.role_focus and active.role_focus != request.role_focus:
                continue
            if request.tags and not set(request.tags).issubset(set(behavior.tags)):
                continue
            score = self._calculate_score(query, behavior, active)
            if request.query and score == 0.0:
                continue
            matches.append(BehaviorSearchResult(behavior=behavior, active_version=active, score=score))
        matches.sort(key=lambda result: result.score, reverse=True)
        limited = matches[: request.limit]
        self._telemetry.emit_event(
            event_type="behaviors.search_performed",
            payload={
                "query": request.query or "",
                "tags": request.tags or [],
                "role_focus": request.role_focus,
                "status": request.status,
                "results": len(limited),
            },
            actor=self._actor_payload(actor) if actor else None,
        )
        return limited

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as exc:  # pragma: no cover - catastrophic failure
            raise PersistenceError(f"Failed to connect to behavior database: {exc}") from exc

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS behaviors (
                    behavior_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    latest_version TEXT NOT NULL,
                    status TEXT NOT NULL
                )
                """,
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS behavior_versions (
                    behavior_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    instruction TEXT NOT NULL,
                    role_focus TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trigger_keywords TEXT NOT NULL,
                    examples TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    effective_from TEXT NOT NULL,
                    effective_to TEXT,
                    created_by TEXT NOT NULL,
                    approval_action_id TEXT,
                    embedding_checksum TEXT,
                    embedding BLOB,
                    PRIMARY KEY (behavior_id, version),
                    FOREIGN KEY (behavior_id) REFERENCES behaviors(behavior_id) ON DELETE CASCADE
                )
                """,
            )

    def _fetch_behavior(self, behavior_id: str) -> Behavior:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM behaviors WHERE behavior_id = ?",
                (behavior_id,),
            ).fetchone()
        if row is None:
            raise BehaviorNotFoundError(f"Behavior '{behavior_id}' not found")
        return self._row_to_behavior(row)

    def _fetch_behaviors(self, status: Optional[str] = None) -> List[Behavior]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM behaviors WHERE status = ? ORDER BY updated_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM behaviors ORDER BY updated_at DESC",
                ).fetchall()
        return [self._row_to_behavior(row) for row in rows]

    def _fetch_behavior_version(self, behavior_id: str, version: str) -> BehaviorVersion:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM behavior_versions
                 WHERE behavior_id = ? AND version = ?
                """,
                (behavior_id, version),
            ).fetchone()
        if row is None:
            raise BehaviorVersionError(f"Version '{version}' not found for behavior '{behavior_id}'")
        return self._row_to_behavior_version(row)

    def _fetch_behavior_versions(self, behavior_id: str) -> List[BehaviorVersion]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM behavior_versions
                 WHERE behavior_id = ?
                 ORDER BY status = 'APPROVED' DESC, effective_from DESC
                """,
                (behavior_id,),
            ).fetchall()
        return [self._row_to_behavior_version(row) for row in rows]

    @staticmethod
    def _calculate_embedding_checksum(embedding: Optional[Iterable[float]]) -> Optional[str]:
        if embedding is None:
            return None
        encoded = json.dumps(list(embedding))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _encode_embedding(embedding: Optional[Iterable[float]]) -> Optional[bytes]:
        if embedding is None:
            return None
        return json.dumps(list(embedding)).encode("utf-8")

    @staticmethod
    def _decode_embedding(blob: Optional[bytes]) -> Optional[List[float]]:
        if blob is None:
            return None
        return json.loads(blob.decode("utf-8"))

    @staticmethod
    def _calculate_score(query: str, behavior: Behavior, version: BehaviorVersion) -> float:
        if not query:
            return 1.0
        haystacks = [
            behavior.name.lower(),
            behavior.description.lower(),
            " ".join(behavior.tags).lower(),
            version.instruction.lower(),
            " ".join(version.trigger_keywords).lower(),
        ]
        matches = sum(1 for haystack in haystacks if query in haystack)
        return matches / len(haystacks)

    @staticmethod
    def _resolve_db_path(db_path: Optional[Path]) -> Path:
        if db_path is not None:
            return db_path.expanduser().resolve()
        env_override = os.getenv(_BEHAVIOR_DB_ENV)
        if env_override:
            return Path(env_override).expanduser().resolve()
        return _DEFAULT_DB_PATH

    @staticmethod
    def _actor_payload(actor: Actor) -> Dict[str, str]:
        return {
            "id": actor.id,
            "role": actor.role,
            "surface": actor.surface,
        }

    @staticmethod
    def _row_to_behavior(row: sqlite3.Row) -> Behavior:
        return Behavior(
            behavior_id=row["behavior_id"],
            name=row["name"],
            description=row["description"],
            tags=list(json.loads(row["tags"] or "[]")),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            latest_version=row["latest_version"],
            status=row["status"],
        )

    def _row_to_behavior_version(self, row: sqlite3.Row) -> BehaviorVersion:
        return BehaviorVersion(
            behavior_id=row["behavior_id"],
            version=row["version"],
            instruction=row["instruction"],
            role_focus=row["role_focus"],
            status=row["status"],
            trigger_keywords=list(json.loads(row["trigger_keywords"] or "[]")),
            examples=list(json.loads(row["examples"] or "[]")),
            metadata=dict(json.loads(row["metadata"] or "{}")),
            effective_from=row["effective_from"],
            effective_to=row["effective_to"],
            created_by=row["created_by"],
            approval_action_id=row["approval_action_id"],
            embedding_checksum=row["embedding_checksum"],
            embedding=self._decode_embedding(row["embedding"]),
        )
