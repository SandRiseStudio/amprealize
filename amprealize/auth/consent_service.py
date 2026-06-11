"""
Consent Request Service

Manages JIT (Just-In-Time) authorization consent flows across Web, CLI, and VS Code.
Part of Phase 6: Consent UX Dashboard from MCP Auth Implementation Plan.

Key Features:
- Creates consent requests with user-friendly codes (e.g., "ABCD-1234")
- Supports approval/denial with audit trail
- Enables polling from MCP clients waiting for user decisions
- Manages consent request lifecycle (pending → approved/denied/expired)
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
import secrets
import logging
import os

from ..storage.postgres_pool import PostgresPool

logger = logging.getLogger(__name__)


@dataclass
class ConsentRequest:
    """Represents a consent request for JIT authorization."""
    id: str
    user_id: str
    agent_id: str
    tool_name: str
    scopes: List[str]
    context: Dict[str, Any]
    status: str  # pending, approved, denied, expired
    user_code: str
    verification_uri: str
    expires_at: datetime
    created_at: datetime
    decided_at: Optional[datetime] = None
    decision_by: Optional[str] = None
    decision_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "tool_name": self.tool_name,
            "scopes": self.scopes,
            "context": self.context,
            "status": self.status,
            "user_code": self.user_code,
            "verification_uri": self.verification_uri,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "decision_by": self.decision_by,
            "decision_reason": self.decision_reason,
        }

    def is_expired(self) -> bool:
        """Check if the request has expired."""
        return datetime.now(timezone.utc) > self.expires_at

    def is_pending(self) -> bool:
        """Check if the request is still pending."""
        return self.status == "pending" and not self.is_expired()


@dataclass
class ConsentPollResult:
    """Result of polling a consent request status."""
    status: str  # pending, approved, denied, expired, not_found
    scopes: Optional[List[str]] = None
    decided_at: Optional[str] = None
    reason: Optional[str] = None
    expires_in_seconds: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        result = {"status": self.status}
        if self.scopes:
            result["scopes"] = self.scopes
        if self.decided_at:
            result["decided_at"] = self.decided_at
        if self.reason:
            result["reason"] = self.reason
        if self.expires_in_seconds is not None:
            result["expires_in_seconds"] = self.expires_in_seconds
        return result


class ConsentService:
    """
    Manages consent request lifecycle.

    Thread-safe for use with async PostgreSQL connections.
    """

    # Characters for user code generation (avoiding confusing chars: I, O, 0, 1, L)
    USER_CODE_LETTERS = "ABCDEFGHJKMNPQRSTUVWXYZ"
    USER_CODE_DIGITS = "23456789"

    def __init__(
        self,
        pool: PostgresPool,
        base_url: Optional[str] = None,
        default_expiry_seconds: int = 600,  # 10 minutes
    ):
        """
        Initialize the consent service.

        Args:
            pool: PostgreSQL connection pool
            base_url: Base URL for verification URIs (defaults to env var)
            default_expiry_seconds: Default consent request expiry time
        """
        self._pool = pool
        self._base_url = base_url or os.getenv("AMPREALIZE_BASE_URL", "https://app.amprealize.dev")
        self._default_expiry = default_expiry_seconds

    def _generate_user_code(self) -> str:
        """
        Generate a user-friendly code like ABCD-1234.

        Uses characters that are easy to read and type.
        Avoids confusing characters (I/1, O/0, L).
        """
        part1 = "".join(secrets.choice(self.USER_CODE_LETTERS) for _ in range(4))
        part2 = "".join(secrets.choice(self.USER_CODE_DIGITS) for _ in range(4))
        return f"{part1}-{part2}"

    def _normalize_user_code(self, user_code: str) -> str:
        """Normalize user code for lookup (remove hyphens, uppercase)."""
        return user_code.replace("-", "").replace(" ", "").upper()

    async def create_request(
        self,
        user_id: str,
        agent_id: str,
        tool_name: str,
        scopes: List[str],
        context: Optional[Dict[str, Any]] = None,
        expires_in: Optional[int] = None,
    ) -> ConsentRequest:
        """
        Create a new consent request.

        Args:
            user_id: User who must approve the request
            agent_id: Agent/service principal requesting access
            tool_name: MCP tool that triggered the request
            scopes: List of scope strings being requested
            context: Additional context (tool params, session info)
            expires_in: Custom expiry time in seconds

        Returns:
            ConsentRequest with generated user code and verification URI
        """
        user_code = self._generate_user_code()
        normalized_code = self._normalize_user_code(user_code)
        verification_uri = f"{self._base_url}/consent/{user_code}"
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=expires_in or self._default_expiry
        )

        query = """
            INSERT INTO auth.consent_requests
                (user_id, agent_id, tool_name, scopes, context,
                 user_code, user_code_normalized, verification_uri, expires_at)
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $8, $9)
            RETURNING id, created_at
        """

        import json
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                query,
                user_id,
                agent_id,
                tool_name,
                json.dumps(scopes),
                json.dumps(context or {}),
                user_code,
                normalized_code,
                verification_uri,
                expires_at,
            )

        logger.info(
            f"Created consent request {row['id']} for user {user_id}, "
            f"code={user_code}, tool={tool_name}, scopes={scopes}"
        )

        return ConsentRequest(
            id=str(row["id"]),
            user_id=user_id,
            agent_id=agent_id,
            tool_name=tool_name,
            scopes=scopes,
            context=context or {},
            status="pending",
            user_code=user_code,
            verification_uri=verification_uri,
            expires_at=expires_at,
            created_at=row["created_at"],
        )

    async def get_by_user_code(self, user_code: str) -> Optional[ConsentRequest]:
        """
        Look up consent request by user code.

        Args:
            user_code: The user-friendly code (e.g., "ABCD-1234")

        Returns:
            ConsentRequest if found, None otherwise
        """
        normalized = self._normalize_user_code(user_code)

        query = """
            SELECT id, user_id, agent_id, tool_name, scopes, context,
                   status, user_code, verification_uri, expires_at,
                   created_at, decided_at, decision_by, decision_reason
            FROM auth.consent_requests
            WHERE user_code_normalized = $1
        """

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, normalized)

        if not row:
            return None

        return self._row_to_request(row)

    async def get_by_id(self, request_id: str) -> Optional[ConsentRequest]:
        """Look up consent request by ID."""
        query = """
            SELECT id, user_id, agent_id, tool_name, scopes, context,
                   status, user_code, verification_uri, expires_at,
                   created_at, decided_at, decision_by, decision_reason
            FROM auth.consent_requests
            WHERE id = $1::uuid
        """

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, request_id)

        if not row:
            return None

        return self._row_to_request(row)

    async def list_pending_for_user(
        self,
        user_id: str,
        limit: int = 20,
    ) -> List[ConsentRequest]:
        """
        List pending consent requests for a user.

        Args:
            user_id: User ID to filter by
            limit: Maximum number of results

        Returns:
            List of pending ConsentRequest objects
        """
        query = """
            SELECT id, user_id, agent_id, tool_name, scopes, context,
                   status, user_code, verification_uri, expires_at,
                   created_at, decided_at, decision_by, decision_reason
            FROM auth.consent_requests
            WHERE user_id = $1
              AND status = 'pending'
              AND expires_at > NOW()
            ORDER BY created_at DESC
            LIMIT $2
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, user_id, limit)

        return [self._row_to_request(row) for row in rows]

    async def approve(
        self,
        user_code: str,
        approver_id: str,
        reason: Optional[str] = None,
    ) -> bool:
        """
        Approve a consent request.

        Args:
            user_code: The user-friendly code
            approver_id: User ID of the approver
            reason: Optional reason for approval

        Returns:
            True if approved, False if request not found or already decided
        """
        normalized = self._normalize_user_code(user_code)

        query = """
            UPDATE auth.consent_requests
            SET status = 'approved',
                decided_at = NOW(),
                decision_by = $2,
                decision_reason = $3
            WHERE user_code_normalized = $1
              AND status = 'pending'
              AND expires_at > NOW()
        """

        async with self._pool.acquire() as conn:
            result = await conn.execute(query, normalized, approver_id, reason)

        success = result == "UPDATE 1"
        if success:
            logger.info(f"Consent request {user_code} approved by {approver_id}")
        else:
            logger.warning(f"Failed to approve consent request {user_code}")

        return success

    async def deny(
        self,
        user_code: str,
        denier_id: str,
        reason: Optional[str] = None,
    ) -> bool:
        """
        Deny a consent request.

        Args:
            user_code: The user-friendly code
            denier_id: User ID of the person denying
            reason: Optional reason for denial

        Returns:
            True if denied, False if request not found or already decided
        """
        normalized = self._normalize_user_code(user_code)

        query = """
            UPDATE auth.consent_requests
            SET status = 'denied',
                decided_at = NOW(),
                decision_by = $2,
                decision_reason = $3
            WHERE user_code_normalized = $1
              AND status = 'pending'
              AND expires_at > NOW()
        """

        async with self._pool.acquire() as conn:
            result = await conn.execute(query, normalized, denier_id, reason)

        success = result == "UPDATE 1"
        if success:
            logger.info(f"Consent request {user_code} denied by {denier_id}")
        else:
            logger.warning(f"Failed to deny consent request {user_code}")

        return success

    async def poll_status(self, user_code: str) -> ConsentPollResult:
        """
        Poll consent request status (for CLI/MCP clients).

        Args:
            user_code: The user-friendly code to poll

        Returns:
            ConsentPollResult with current status
        """
        request = await self.get_by_user_code(user_code)

        if not request:
            return ConsentPollResult(status="not_found")

        # Check for expiry
        if request.status == "pending" and request.is_expired():
            # Mark as expired in database
            await self._mark_expired(user_code)
            return ConsentPollResult(status="expired")

        if request.status == "approved":
            return ConsentPollResult(
                status="approved",
                scopes=request.scopes,
                decided_at=request.decided_at.isoformat() if request.decided_at else None,
                reason=request.decision_reason,
            )

        if request.status == "denied":
            return ConsentPollResult(
                status="denied",
                decided_at=request.decided_at.isoformat() if request.decided_at else None,
                reason=request.decision_reason,
            )

        if request.status == "expired":
            return ConsentPollResult(status="expired")

        # Still pending
        expires_in = int((request.expires_at - datetime.now(timezone.utc)).total_seconds())
        return ConsentPollResult(
            status="pending",
            expires_in_seconds=max(0, expires_in),
        )

    async def _mark_expired(self, user_code: str) -> None:
        """Mark a consent request as expired."""
        normalized = self._normalize_user_code(user_code)

        query = """
            UPDATE auth.consent_requests
            SET status = 'expired'
            WHERE user_code_normalized = $1
              AND status = 'pending'
        """

        async with self._pool.acquire() as conn:
            await conn.execute(query, normalized)

    async def cleanup_expired(self, older_than_days: int = 30) -> int:
        """
        Clean up old expired/decided consent requests.

        Args:
            older_than_days: Delete requests older than this many days

        Returns:
            Number of deleted requests
        """
        query = """
            DELETE FROM auth.consent_requests
            WHERE (status IN ('expired', 'denied')
                   OR (status = 'approved' AND decided_at < NOW() - INTERVAL '%s days'))
              AND created_at < NOW() - INTERVAL '%s days'
        """

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                query.replace('%s', str(older_than_days)),
            )

        # Extract count from "DELETE X"
        count = int(result.split()[-1]) if result.startswith("DELETE") else 0
        if count > 0:
            logger.info(f"Cleaned up {count} old consent requests")

        return count

    def _row_to_request(self, row) -> ConsentRequest:
        """Convert a database row to ConsentRequest."""
        return ConsentRequest(
            id=str(row["id"]),
            user_id=row["user_id"],
            agent_id=row["agent_id"],
            tool_name=row["tool_name"],
            scopes=row["scopes"] if isinstance(row["scopes"], list) else list(row["scopes"]),
            context=row["context"] if isinstance(row["context"], dict) else dict(row["context"]),
            status=row["status"],
            user_code=row["user_code"],
            verification_uri=row["verification_uri"],
            expires_at=row["expires_at"],
            created_at=row["created_at"],
            decided_at=row["decided_at"],
            decision_by=row["decision_by"],
            decision_reason=row["decision_reason"],
        )


# Singleton instance for service integration
_consent_service: Optional[ConsentService] = None


def get_consent_service(pool: Optional[PostgresPool] = None) -> ConsentService:
    """Get or create the singleton ConsentService instance."""
    global _consent_service

    if _consent_service is None:
        if pool is None:
            raise ValueError("Pool required for first initialization")
        _consent_service = ConsentService(pool=pool)

    return _consent_service
