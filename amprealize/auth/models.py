"""
Data models for Amprealize authentication.

Architecture (as of 2026-01-08):
- auth.users: Human users authenticated via OAuth device flow
- auth.federated_identities: OAuth provider links (Google, GitHub, etc.)
- auth.service_principals: Machine/agent API credentials (client_credentials flow)
- execution.agents.owner_id: FK to auth.users (human who created the agent)
- execution.agents.service_principal_id: Optional FK for agent's API identity

Human users authenticate via:
- OAuth device flow → creates federated_identity → links to users record
- JWT tokens issued after successful OAuth

Service principals (for agents) authenticate via:
- client_credentials flow with client_id/client_secret
- Created explicitly when an agent needs its own API access
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class AgentRole(str, Enum):
    """Role for service principals following AGENTS.md role hierarchy."""
    STUDENT = "STUDENT"          # Routine execution following established patterns
    TEACHER = "TEACHER"          # Creating examples, documentation, reviews
    STRATEGIST = "STRATEGIST"    # Novel problems, pattern extraction, behavior curation
    ADMIN = "ADMIN"              # Administrative access
    OBSERVER = "OBSERVER"        # Read-only access


@dataclass
class User:
    """Human user authenticated via OAuth device flow.

    This maps to auth.users table. Human users authenticate via OAuth
    (Google, GitHub, etc.) and get a corresponding federated_identity record.
    """

    id: str  # UUID
    email: str  # Email address from OAuth provider
    display_name: Optional[str] = None  # User's display name
    avatar_url: Optional[str] = None  # Avatar URL from OAuth provider
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    is_active: bool = True
    metadata: dict = field(default_factory=dict)  # JSONB for additional properties

    def to_dict(self) -> dict:
        """Convert to dictionary (safe for serialization)."""
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "is_active": self.is_active,
        }


@dataclass
class FederatedIdentity:
    """OAuth identity linked to a User.

    Maps to auth.federated_identities table. Each user can have multiple
    federated identities from different OAuth providers.
    """

    id: Optional[str] = None  # UUID
    user_id: Optional[str] = None  # FK to auth.users
    provider: Optional[str] = None  # OAuth provider (e.g., 'google', 'github')
    provider_user_id: Optional[str] = None  # User ID from the OAuth provider
    provider_email: Optional[str] = None  # Email from the OAuth provider
    provider_username: Optional[str] = None  # Username from the OAuth provider
    provider_display_name: Optional[str] = None  # Display name from the OAuth provider
    provider_avatar_url: Optional[str] = None  # Avatar URL from the OAuth provider
    access_token_encrypted: Optional[str] = None  # Encrypted OAuth access token
    refresh_token_encrypted: Optional[str] = None  # Encrypted OAuth refresh token
    token_expires_at: Optional[datetime] = None  # When the OAuth token expires
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "provider": self.provider,
            "provider_user_id": self.provider_user_id,
            "provider_email": self.provider_email,
            "provider_username": self.provider_username,
            "provider_display_name": self.provider_display_name,
            "provider_avatar_url": self.provider_avatar_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class ServicePrincipal:
    """Machine/agent identity for API access via client_credentials flow.

    Maps to auth.service_principals table. Used when an agent needs its own
    API identity independent of the human user who created it.
    """

    id: str  # UUID
    name: str  # Human-readable name
    client_id: str  # Unique identifier for client_credentials auth
    role: AgentRole = AgentRole.STUDENT  # Agent role per AGENTS.md
    description: Optional[str] = None
    allowed_scopes: list = field(default_factory=lambda: ["read", "write"])
    rate_limit: int = 1000  # Requests per minute
    is_active: bool = True
    created_by: Optional[str] = None  # FK to auth.users
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary (safe for serialization, excludes secret)."""
        return {
            "id": self.id,
            "name": self.name,
            "client_id": self.client_id,
            "role": self.role.value if isinstance(self.role, AgentRole) else self.role,
            "description": self.description,
            "allowed_scopes": self.allowed_scopes,
            "rate_limit": self.rate_limit,
            "is_active": self.is_active,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
        }


# SQL Schemas for reference (canonical schema in Alembic migrations)

USERS_TABLE_SCHEMA = """
-- Human users authenticated via OAuth
CREATE TABLE IF NOT EXISTS auth.users (
    id VARCHAR(36) PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(255),
    avatar_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_users_email ON auth.users(email);
"""

FEDERATED_IDENTITIES_TABLE_SCHEMA = """
-- OAuth provider identities linked to users
CREATE TABLE IF NOT EXISTS auth.federated_identities (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL,
    provider_user_id VARCHAR(255) NOT NULL,
    provider_email VARCHAR(255),
    provider_username VARCHAR(255),
    provider_display_name VARCHAR(255),
    provider_avatar_url TEXT,
    access_token_encrypted TEXT,
    refresh_token_encrypted TEXT,
    token_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(provider, provider_user_id)
);

CREATE INDEX IF NOT EXISTS idx_federated_user_id ON auth.federated_identities(user_id);
CREATE INDEX IF NOT EXISTS idx_federated_provider ON auth.federated_identities(provider, provider_user_id);
"""

SERVICE_PRINCIPALS_TABLE_SCHEMA = """
-- Machine/agent API credentials for client_credentials flow
CREATE TABLE IF NOT EXISTS auth.service_principals (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    client_id VARCHAR(64) UNIQUE NOT NULL,
    client_secret_hash VARCHAR(255) NOT NULL,
    allowed_scopes JSONB DEFAULT '["read", "write"]'::jsonb,
    rate_limit INTEGER DEFAULT 1000,
    role VARCHAR(20) NOT NULL DEFAULT 'STUDENT'
        CHECK (role IN ('STRATEGIST', 'TEACHER', 'STUDENT', 'ADMIN', 'OBSERVER')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by VARCHAR(36) REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_service_principals_client_id ON auth.service_principals(client_id);
CREATE INDEX IF NOT EXISTS idx_service_principals_created_by ON auth.service_principals(created_by);
"""
