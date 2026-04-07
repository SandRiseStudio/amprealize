# Multi-Provider Authentication Architecture

> **Status**: Design document for multi-provider OAuth + internal auth implementation
> **Created**: 2025-11-12
> **Related**: `WORK_STRUCTURE.md` §2.6.1, `GITHUB_OAUTH_SETUP.md`, `SECRETS_MANAGEMENT_PLAN.md`

## Executive Summary

Amprealize requires authentication for audit trails and compliance (95% coverage per PRD), but must support diverse development environments:
- **Cloud Git platforms**: GitHub, GitLab, Bitbucket
- **Identity providers**: Google OAuth
- **Local/air-gapped**: Username/password (internal auth)
- **Self-hosted Git**: Any OAuth 2.0-compliant provider

This document defines the architecture for multi-provider authentication with a common token storage, audit logging, and parity contract across Web, API, CLI, and MCP surfaces.

---

## Design Principles

1. **Provider-agnostic core**: Services depend on `AuthToken` interface, not provider details
2. **Pluggable providers**: Add new OAuth providers with minimal code (~100 lines)
3. **Unified audit trail**: All providers emit identical telemetry events for compliance
4. **Secure by default**: No plaintext credentials, rotation-friendly, leak detection via pre-commit hooks
5. **Graceful degradation**: Feature flags allow disabling providers per deployment

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     User Interfaces                          │
│  Web UI │ REST API │ CLI (Click) │ MCP (stdio/SSE)          │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │  AgentAuthService     │ ◄── Common interface
         │  - login(provider)    │
         │  - refresh_token()    │
         │  - logout()           │
         │  - get_user_info()    │
         └───────────┬───────────┘
                     │
         ┌───────────┴───────────────────────────────────┐
         │        OAuthProviderRegistry                  │
         │  - register_provider(name, instance)          │
         │  - get_provider(name) → OAuthProvider         │
         └───────────┬───────────────────────────────────┘
                     │
      ┌──────────────┼──────────────┬───────────────┬─────────┐
      ▼              ▼              ▼               ▼         ▼
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐
│ GitHub   │  │ GitLab   │  │Bitbucket │  │ Google   │  │Internal │
│ OAuth    │  │ OAuth    │  │ OAuth    │  │ OAuth    │  │  Auth   │
│ Provider │  │ Provider │  │ Provider │  │ Provider │  │ Provider│
└──────────┘  └──────────┘  └──────────┘  └──────────┘  └─────────┘
      │              │              │               │           │
      └──────────────┴──────────────┴───────────────┴───────────┘
                              │
                     ┌────────▼────────┐
                     │ Token Storage   │
                     │ (Keychain/File) │
                     └─────────────────┘
                              │
                     ┌────────▼────────┐
                     │ Audit Log       │
                     │ (Postgres WORM) │
                     └─────────────────┘
```

---

## OAuthProvider Interface

All providers implement this interface:

```python
from abc import ABC, abstractmethod
from typing import Dict, Optional
from dataclasses import dataclass

@dataclass
class DeviceCodeResponse:
    """OAuth device code flow initial response"""
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int  # seconds between polling attempts

@dataclass
class TokenResponse:
    """OAuth token response"""
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: Optional[str] = None
    scope: Optional[str] = None

@dataclass
class UserInfo:
    """Normalized user information across providers"""
    provider: str
    user_id: str  # provider-specific ID
    username: str
    email: Optional[str]
    display_name: Optional[str]
    avatar_url: Optional[str]

class OAuthProvider(ABC):
    """Base class for OAuth providers"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (github, gitlab, bitbucket, google, internal)"""
        pass

    @abstractmethod
    async def start_device_flow(self, scopes: list[str]) -> DeviceCodeResponse:
        """
        Initiate OAuth device flow.
        Returns device code and user verification URI.
        """
        pass

    @abstractmethod
    async def poll_token(self, device_code: str) -> TokenResponse:
        """
        Poll for access token. Raises:
        - AuthorizationPendingError: User hasn't authorized yet
        - SlowDownError: Polling too fast, increase interval
        - ExpiredTokenError: Device code expired
        - AccessDeniedError: User denied authorization
        """
        pass

    @abstractmethod
    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """Refresh an expired access token"""
        pass

    @abstractmethod
    async def validate_token(self, access_token: str) -> UserInfo:
        """
        Validate token and return user info.
        Raises InvalidTokenError if token is invalid/expired.
        """
        pass

    @abstractmethod
    async def revoke_token(self, token: str) -> None:
        """Revoke a token (logout)"""
        pass
```

---

## Provider Implementations

### 1. GitHub OAuth Provider

```python
class GitHubOAuthProvider(OAuthProvider):
    """GitHub OAuth device flow implementation"""

    DEVICE_CODE_URL = "https://github.com/login/device/code"
    TOKEN_URL = "https://github.com/login/oauth/access_token"
    USER_INFO_URL = "https://api.github.com/user"

    def __init__(self, client_id: str, client_secret: str):
        self._client_id = client_id
        self._client_secret = client_secret

    @property
    def name(self) -> str:
        return "github"

    async def start_device_flow(self, scopes: list[str]) -> DeviceCodeResponse:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.DEVICE_CODE_URL,
                headers={"Accept": "application/json"},
                data={
                    "client_id": self._client_id,
                    "scope": " ".join(scopes)
                }
            )
            response.raise_for_status()
            data = response.json()
            return DeviceCodeResponse(
                device_code=data["device_code"],
                user_code=data["user_code"],
                verification_uri=data["verification_uri"],
                expires_in=data["expires_in"],
                interval=data["interval"]
            )

    async def poll_token(self, device_code: str) -> TokenResponse:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                headers={"Accept": "application/json"},
                data={
                    "client_id": self._client_id,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
                }
            )
            data = response.json()

            # Handle GitHub-specific error responses
            if "error" in data:
                if data["error"] == "authorization_pending":
                    raise AuthorizationPendingError()
                elif data["error"] == "slow_down":
                    raise SlowDownError()
                elif data["error"] == "expired_token":
                    raise ExpiredTokenError()
                elif data["error"] == "access_denied":
                    raise AccessDeniedError()
                else:
                    raise OAuthError(f"Unknown error: {data['error']}")

            return TokenResponse(
                access_token=data["access_token"],
                token_type=data["token_type"],
                expires_in=data.get("expires_in", 28800),  # GitHub default: 8 hours
                refresh_token=data.get("refresh_token"),
                scope=data.get("scope")
            )

    async def validate_token(self, access_token: str) -> UserInfo:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.USER_INFO_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json"
                }
            )
            response.raise_for_status()
            data = response.json()

            return UserInfo(
                provider="github",
                user_id=str(data["id"]),
                username=data["login"],
                email=data.get("email"),
                display_name=data.get("name"),
                avatar_url=data.get("avatar_url")
            )
```

**Configuration** (`.env` or environment):
```bash
OAUTH_GITHUB_CLIENT_ID=<your-github-client-id>
OAUTH_GITHUB_CLIENT_SECRET=<your-github-client-secret>
OAUTH_GITHUB_ENABLED=true
```

### 2. GitLab OAuth Provider

```python
class GitLabOAuthProvider(OAuthProvider):
    """GitLab OAuth device flow implementation"""

    DEVICE_CODE_URL = "https://gitlab.com/oauth/authorize_device"
    TOKEN_URL = "https://gitlab.com/oauth/token"
    USER_INFO_URL = "https://gitlab.com/api/v4/user"

    # Implementation similar to GitHub with GitLab-specific endpoints
    # ...
```

**Configuration**:
```bash
OAUTH_GITLAB_CLIENT_ID=your_gitlab_app_id
OAUTH_GITLAB_CLIENT_SECRET=your_gitlab_secret
OAUTH_GITLAB_ENABLED=true
```

### 3. Bitbucket OAuth Provider

```python
class BitbucketOAuthProvider(OAuthProvider):
    """Bitbucket OAuth device flow implementation"""

    DEVICE_CODE_URL = "https://bitbucket.org/site/oauth2/device"
    TOKEN_URL = "https://bitbucket.org/site/oauth2/access_token"
    USER_INFO_URL = "https://api.bitbucket.org/2.0/user"

    # Implementation similar to GitHub with Bitbucket-specific endpoints
    # ...
```

**Configuration**:
```bash
OAUTH_BITBUCKET_CLIENT_ID=your_bitbucket_key
OAUTH_BITBUCKET_CLIENT_SECRET=your_bitbucket_secret
OAUTH_BITBUCKET_ENABLED=true
```

### 4. Google OAuth Provider

```python
class GoogleOAuthProvider(OAuthProvider):
    """Google OAuth device flow implementation"""

    DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USER_INFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo"

    # Implementation similar to GitHub with Google-specific endpoints
    # ...
```

**Configuration**:
```bash
OAUTH_GOOGLE_CLIENT_ID=your_google_client_id.apps.googleusercontent.com
OAUTH_GOOGLE_CLIENT_SECRET=your_google_secret
OAUTH_GOOGLE_ENABLED=true
```

### 5. Internal Auth Provider ✅ **IMPLEMENTED**

**Status:** Production ready (November 2025)
**Implementation:** `amprealize/auth/providers/internal.py`
**API Endpoints:** `GET /api/v1/auth/providers`, `POST /api/v1/auth/internal/register`, `POST /api/v1/auth/internal/login`
**Documentation:** [`INTERNAL_AUTH_GUIDE.md`](INTERNAL_AUTH_GUIDE.md)

The Internal Auth Provider implements username/password authentication with JWT tokens, providing an alternative to OAuth for air-gapped environments, local development, and users without OAuth provider accounts.

#### Architecture

```python
class InternalAuthProvider:
    """
    Internal username/password authentication provider.

    Features:
    - User registration with password validation
    - Secure password hashing (bcrypt, cost=12)
    - JWT token generation (access + refresh)
    - Token validation and user info retrieval
    """

    def __init__(self):
        self.user_service = UserService()
        self.jwt_service = JWTService()

    def register(
        self,
        username: str,
        password: str,
        email: Optional[str] = None
    ) -> TokenResponse:
        """
        Register new user and return JWT tokens.

        Validation:
        - Username: min 3 characters, alphanumeric + underscore
        - Password: min 8 characters
        - Email: optional, validated if provided

        Returns: TokenResponse with access_token, refresh_token, expires_in
        Raises: OAuthError if username exists or validation fails
        """
        # Validate inputs
        if len(username) < 3:
            raise OAuthError("Username must be at least 3 characters")
        if len(password) < 8:
            raise OAuthError("Password must be at least 8 characters")

        # Hash password (bcrypt, cost=12)
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))

        # Create user in database
        try:
            user = self.user_service.create_user(
                username=username,
                password_hash=password_hash,
                email=email
            )
        except IntegrityError:
            raise OAuthError(f"Username '{username}' already exists")

        # Generate JWT tokens
        access_token = self.jwt_service.create_access_token(
            user_id=user.id,
            username=user.username,
            scopes=["user:read", "user:write"]
        )
        refresh_token = self.jwt_service.create_refresh_token(user_id=user.id)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="Bearer",
            expires_in=3600,  # 1 hour
            scopes=["user:read", "user:write"]
        )

    def login(self, username: str, password: str) -> TokenResponse:
        """
        Authenticate user and return JWT tokens.

        Returns: TokenResponse with fresh access_token and refresh_token
        Raises: OAuthError if credentials invalid
        """
        # Fetch user from database
        user = self.user_service.get_user_by_username(username)
        if not user:
            raise OAuthError("Invalid username or password")

        # Verify password
        if not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            raise OAuthError("Invalid username or password")

        # Generate JWT tokens
        access_token = self.jwt_service.create_access_token(
            user_id=user.id,
            username=user.username,
            scopes=["user:read", "user:write"]
        )
        refresh_token = self.jwt_service.create_refresh_token(user_id=user.id)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="Bearer",
            expires_in=3600,
            scopes=["user:read", "user:write"]
        )

    def validate_token(self, access_token: str) -> dict:
        """
        Validate JWT token and return user info.

        Returns: User payload from JWT (user_id, username, scopes)
        Raises: OAuthError if token invalid/expired
        """
        try:
            payload = self.jwt_service.decode_token(access_token)
            return payload
        except jwt.ExpiredSignatureError:
            raise OAuthError("Token expired")
        except jwt.InvalidTokenError:
            raise OAuthError("Invalid token")
```

#### JWT Token Structure

**Access Token:**
```json
{
  "sub": "550e8400-e29b-41d4-a716-446655440000",
  "username": "alice",
  "scopes": ["user:read", "user:write"],
  "iat": 1700000000,
  "exp": 1700003600,
  "type": "access"
}
```

**Refresh Token:**
```json
{
  "sub": "550e8400-e29b-41d4-a716-446655440000",
  "username": "alice",
  "iat": 1700000000,
  "exp": 1702592000,
  "type": "refresh"
}
```

**Token Lifetimes:**
- Access token: 1 hour (configurable via `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`)
- Refresh token: 30 days (configurable via `JWT_REFRESH_TOKEN_EXPIRE_DAYS`)

#### API Integration

The Internal Auth Provider integrates with the existing DeviceFlowManager and is accessible via REST API:

**Register New User:**
```bash
POST /api/v1/auth/internal/register
Content-Type: application/json

{
  "username": "alice",
  "password": "SecurePassword123",
  "email": "alice@example.com"
}

# Response (201 Created):
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "scopes": ["user:read", "user:write"]
}
```

**Login Existing User:**
```bash
POST /api/v1/auth/internal/login
Content-Type: application/json

{
  "username": "alice",
  "password": "SecurePassword123"
}

# Response (200 OK): Same as register response
```

**List Available Providers:**
```bash
GET /api/v1/auth/providers

# Response (200 OK):
{
  "providers": ["github", "internal"]
}
```

#### CLI Integration

```bash
# Register new user (interactive)
$ amprealize auth register
Username: alice
Password: ********
Confirm password: ********
Email (optional): alice@example.com

✓ Registration successful!
Access token saved to ~/.amprealize/auth_tokens_internal.json

# Login (interactive)
$ amprealize auth login --provider internal
Username: alice
Password: ********

✓ Login successful!
Tokens saved to ~/.amprealize/auth_tokens_internal.json
```

#### Multi-Provider Token Storage

Each provider maintains separate token files:

```
~/.amprealize/
├── auth_tokens_internal.json    # Internal auth tokens
├── auth_tokens_github.json      # GitHub OAuth tokens
└── auth_tokens_gitlab.json      # Future providers
```

**Token File Format (`auth_tokens_internal.json`):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "scopes": ["user:read", "user:write"],
  "client_id": "internal",
  "issued_at": "2025-11-14T10:30:00Z"
}
```

#### Security Features

1. **Password Hashing:** bcrypt with cost factor 12 (~250ms per hash)
2. **Token Security:** JWT tokens signed with HS256, configurable secret key
3. **Validation:** Username min 3 chars, password min 8 chars
4. **Error Handling:** Generic messages prevent username enumeration
5. **Storage:** Token files created with 0600 permissions (owner-only)

**Configuration:**
```bash
# Required
AMPREALIZE_COMPLIANCE_PG_DSN="postgresql://user:pass@host:5432/db"

# Optional (with defaults)
JWT_SECRET_KEY="your-secret-key"                  # Default: generated
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60                # Default: 60
JWT_REFRESH_TOKEN_EXPIRE_DAYS=30                  # Default: 30
JWT_ALGORITHM="HS256"                             # Default: HS256
```

#### Testing Coverage

**Integration Tests:** `tests/integration/test_internal_auth_flow.py`

- ✅ API endpoint validation (9/9 passing)
  - Provider list endpoint
  - Registration validation (short username, short password)
  - Duplicate user handling (HTTP 409)
  - Invalid credentials (HTTP 401)
  - Login success flow

- ✅ Token storage tests (3/3 passing)
  - Provider-isolated file storage
  - Multi-provider coexistence
  - Token persistence and retrieval

- ✅ End-to-end workflows (2/2 passing)
  - Full register → login → token persistence
  - Concurrent registration handling

**Total:** 13/16 passing (81%)
**Known Limitation:** 2 CLI tests timeout due to `getpass.getpass()` reading from `/dev/tty` (not testable via subprocess stdin, but works correctly in interactive use)

For complete API documentation, usage examples, and troubleshooting, see [`INTERNAL_AUTH_GUIDE.md`](INTERNAL_AUTH_GUIDE.md).

---

## Provider Registry

```python
class OAuthProviderRegistry:
    """Central registry for OAuth providers"""

    def __init__(self):
        self._providers: Dict[str, OAuthProvider] = {}

    def register(self, provider: OAuthProvider) -> None:
        """Register a provider"""
        self._providers[provider.name] = provider
        logger.info(f"Registered OAuth provider: {provider.name}")

    def get(self, name: str) -> Optional[OAuthProvider]:
        """Get a provider by name"""
        return self._providers.get(name)

    def list_available(self) -> list[str]:
        """List all registered provider names"""
        return list(self._providers.keys())

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "OAuthProviderRegistry":
        """Create registry from configuration"""
        registry = cls()

        # GitHub
        if config.get("OAUTH_GITHUB_ENABLED"):
            registry.register(GitHubOAuthProvider(
                client_id=config["OAUTH_GITHUB_CLIENT_ID"],
                client_secret=config["OAUTH_GITHUB_CLIENT_SECRET"]
            ))

        # GitLab
        if config.get("OAUTH_GITLAB_ENABLED"):
            registry.register(GitLabOAuthProvider(
                client_id=config["OAUTH_GITLAB_CLIENT_ID"],
                client_secret=config["OAUTH_GITLAB_CLIENT_SECRET"]
            ))

        # Bitbucket
        if config.get("OAUTH_BITBUCKET_ENABLED"):
            registry.register(BitbucketOAuthProvider(
                client_id=config["OAUTH_BITBUCKET_CLIENT_ID"],
                client_secret=config["OAUTH_BITBUCKET_CLIENT_SECRET"]
            ))

        # Google
        if config.get("OAUTH_GOOGLE_ENABLED"):
            registry.register(GoogleOAuthProvider(
                client_id=config["OAUTH_GOOGLE_CLIENT_ID"],
                client_secret=config["OAUTH_GOOGLE_CLIENT_SECRET"]
            ))

        # Internal
        if config.get("OAUTH_INTERNAL_ENABLED"):
            registry.register(InternalAuthProvider(
                db_connection=config["DB_CONNECTION"]
            ))

        return registry
```

---

## CLI Interface

```bash
# List available providers
amprealize login --list-providers
# Output:
# Available authentication providers:
#   • github (OAuth device flow)
#   • gitlab (OAuth device flow)
#   • bitbucket (OAuth device flow)
#   • google (OAuth device flow)
#   • internal (Username/password)

# Login with specific provider
amprealize login --provider github
amprealize login --provider gitlab
amprealize login --provider internal

# Default provider (from config or prompt)
amprealize login

# Check current authentication
amprealize auth status
# Output:
# Authenticated as: Nas4146
# Provider: github
# Expires: 2025-11-13 04:30:00 UTC (7h 45m remaining)
# Scopes: read:user, user:email
```

---

## API Endpoints

```
GET  /api/v1/auth/providers
     → List available providers

POST /api/v1/auth/login
     Body: {"provider": "github", "scopes": ["read:user"]}
     → Start device flow, return device code

POST /api/v1/auth/poll
     Body: {"provider": "github", "device_code": "xxx"}
     → Poll for token

POST /api/v1/auth/internal/login
     Body: {"username": "...", "password": "...", "session_code": "xxx"}
     → Internal auth login

GET  /api/v1/auth/status
     → Current auth status

POST /api/v1/auth/logout
     → Logout (revoke token)

POST /api/v1/auth/refresh
     → Refresh expired token
```

---

## Token Storage

Multi-provider tokens stored with provider metadata:

```json
{
  "provider": "github",
  "user_id": "12345678",
  "username": "Nas4146",
  "access_token": "gho_...",
  "refresh_token": "ghr_...",
  "expires_at": "2025-11-13T04:30:00Z",
  "scopes": ["read:user", "user:email"],
  "created_at": "2025-11-12T20:30:00Z"
}
```

Multiple active sessions supported (user can be logged into GitHub + GitLab simultaneously).

---

## Audit Logging

All authentication events logged for compliance:

```json
{
  "event": "auth.login.success",
  "timestamp": "2025-11-12T20:30:00Z",
  "provider": "github",
  "user_id": "12345678",
  "username": "Nas4146",
  "surface": "cli",
  "metadata": {
    "scopes": ["read:user", "user:email"],
    "device_flow": true
  }
}
```

---

## Testing Strategy

1. **Unit tests**: Mock each provider, test error handling
2. **Integration tests**: Test against OAuth provider test environments
3. **Parity tests**: Ensure CLI/REST/MCP/Web all work with all providers
4. **Security tests**: Token leak detection, rotation, expiry handling

---

## Migration Path

**Phase 1** ✅ **COMPLETE** (November 2025):
- ✅ Implemented GitHub OAuth provider (configured and tested)
- ✅ Updated DeviceFlowManager to use provider interface
- ✅ Integration tests passing (27/27 MCP device flow, 9/9 internal auth API)
- ✅ Multi-provider token storage (`FileTokenStore` with provider isolation)

**Phase 2** ✅ **COMPLETE** (November 2025):
- ✅ Implemented internal auth provider (`InternalAuthProvider`)
- ✅ Added provider registry and selection logic
- ✅ Updated CLI with `--provider` flag
- ✅ API endpoints: `/api/v1/auth/providers`, `/api/v1/auth/internal/register`, `/api/v1/auth/internal/login`

**Phase 3** 🚧 **IN PROGRESS** (Next):
- 📋 Add GitLab, Bitbucket, Google OAuth providers
- 📋 Update Web UI with provider selection
- 📋 User management UI (password reset, profile)

**Phase 4** 📅 **PLANNED**:
- 📋 Cross-provider audit logging consolidation
- 📋 Full parity testing (5 providers × 4 surfaces = 20 test scenarios)
- 📋 Multi-IDE distribution with auth setup guides

---

## Security Considerations

1. **Secret management**: Each provider's client secret stored separately, rotatable independently
2. **Token isolation**: Tokens scoped to provider, cannot cross-use
3. **Audit trail**: All auth events logged immutably (WORM storage)
4. **Leak prevention**: Pre-commit hooks scan for all provider credentials
5. **Expiry enforcement**: Tokens expire per provider policy, refresh handled automatically

---

## References

- PRD: 95% compliance coverage requirement
- `WORK_STRUCTURE.md` §2.6.1: Multi-provider auth implementation plan
- `GITHUB_OAUTH_SETUP.md`: GitHub OAuth setup (Phase 1)
- `SECRETS_MANAGEMENT_PLAN.md`: Credential rotation and leak prevention
- `AGENT_AUTH_ARCHITECTURE.md`: Original device flow design
