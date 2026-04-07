# Internal Authentication Guide

**Version:** 1.0
**Last Updated:** November 14, 2025
**Status:** Production Ready ✅

## Overview

Amprealize's internal authentication system provides username/password authentication as an alternative to OAuth providers like GitHub. This guide covers API usage, CLI commands, multi-provider token storage, and security considerations.

### Key Features

- **Username/Password Authentication**: Traditional credentials-based auth with secure password hashing (bcrypt)
- **JWT Tokens**: Industry-standard JSON Web Tokens for stateless authentication
- **Multi-Provider Support**: Seamless coexistence with GitHub OAuth and other providers
- **Provider Isolation**: Each auth provider maintains separate token storage
- **REST API**: Full programmatic access to registration and login flows
- **CLI Integration**: Interactive commands for easy user onboarding

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [API Reference](#api-reference)
3. [CLI Usage](#cli-usage)
4. [Multi-Provider Storage](#multi-provider-storage)
5. [Architecture](#architecture)
6. [Security](#security)
7. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Register a New User (CLI)

```bash
amprealize auth register
```

You'll be prompted for:
- Username (min 3 characters)
- Password (min 8 characters)
- Password confirmation
- Email (optional)

### Login (CLI)

```bash
amprealize auth login --provider internal
```

You'll be prompted for username and password. Tokens are stored in `~/.amprealize/auth_tokens_internal.json`.

### Register via API

```bash
curl -X POST http://localhost:8000/api/v1/auth/internal/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "alice",
    "password": "SecurePass123!",
    "email": "alice@example.com"
  }'
```

**Response (201 Created):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "scopes": ["user:read", "user:write"]
}
```

---

## API Reference

### Base URL

```
http://localhost:8000/api/v1/auth
```

### Endpoints

#### 1. List Available Providers

**GET** `/api/v1/auth/providers`

Returns all configured authentication providers.

**Response (200 OK):**
```json
{
  "providers": ["github", "internal"]
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/auth/providers
```

---

#### 2. Register New User

**POST** `/api/v1/auth/internal/register`

Creates a new user account with username/password credentials.

**Request Body:**
```json
{
  "username": "string",     // Required, min 3 chars
  "password": "string",     // Required, min 8 chars
  "email": "string"         // Optional
}
```

**Response (201 Created):**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "scopes": ["user:read", "user:write"],
  "user_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Error Responses:**

| Status | Error | Description |
|--------|-------|-------------|
| 400 | `validation_error` | Username too short (< 3 chars) |
| 400 | `validation_error` | Password too short (< 8 chars) |
| 409 | `registration_failed` | Username already exists |
| 500 | `internal_error` | Server error during registration |

**Examples:**

**Success:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/internal/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "alice",
    "password": "MySecurePassword123",
    "email": "alice@example.com"
  }'
```

**Validation Error (short username):**
```bash
curl -X POST http://localhost:8000/api/v1/auth/internal/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "ab",
    "password": "MySecurePassword123"
  }'
```

**Response (400 Bad Request):**
```json
{
  "detail": "Username must be at least 3 characters long"
}
```

**Duplicate Username:**
```bash
# Register same username twice
curl -X POST http://localhost:8000/api/v1/auth/internal/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "Pass12345678"}'
```

**Response (409 Conflict):**
```json
{
  "detail": "Username 'alice' already exists"
}
```

---

#### 3. Login

**POST** `/api/v1/auth/internal/login`

Authenticates a user and returns JWT tokens.

**Request Body:**
```json
{
  "username": "string",
  "password": "string"
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "scopes": ["user:read", "user:write"]
}
```

**Error Responses:**

| Status | Error | Description |
|--------|-------|-------------|
| 400 | `validation_error` | Missing username or password |
| 401 | `invalid_credentials` | Username or password incorrect |
| 500 | `internal_error` | Server error during login |

**Examples:**

**Success:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/internal/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "alice",
    "password": "MySecurePassword123"
  }'
```

**Invalid Credentials:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/internal/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "alice",
    "password": "WrongPassword"
  }'
```

**Response (401 Unauthorized):**
```json
{
  "detail": "Invalid username or password"
}
```

**Missing Fields:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/internal/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "alice"
  }'
```

**Response (400 Bad Request):**
```json
{
  "detail": "Missing required field: password"
}
```

---

## CLI Usage

### Installation

Internal auth is included in Amprealize by default. No additional setup required.

### Register Command

**Interactive registration:**

```bash
amprealize auth register
```

**Prompts:**
```
Username: alice
Password: ********
Confirm password: ********
Email (optional): alice@example.com

✓ Registration successful!
Access token saved to ~/.amprealize/auth_tokens_internal.json
```

**Notes:**
- Username must be 3+ characters
- Password must be 8+ characters
- Password confirmation must match
- Email is optional but recommended for account recovery

**Exit Codes:**
- `0`: Success
- `1`: Error (validation, duplicate user, network failure)
- `130`: User cancelled (Ctrl+C)

---

### Login Command

**Interactive login:**

```bash
amprealize auth login --provider internal
```

**Prompts:**
```
Username: alice
Password: ********

✓ Login successful!
Tokens saved to ~/.amprealize/auth_tokens_internal.json
```

**Options:**
- `--provider internal`: Specifies internal auth (required if multiple providers configured)

**Exit Codes:**
- `0`: Success
- `1`: Error (invalid credentials, network failure)
- `130`: User cancelled (Ctrl+C)

---

### Status Command

**Check authentication status:**

```bash
amprealize auth status
```

**Output:**
```
Provider: internal
Username: alice
Token: Valid (expires in 45 minutes)
```

---

### Logout Command

**Remove stored tokens:**

```bash
amprealize auth logout --provider internal
```

This removes `~/.amprealize/auth_tokens_internal.json`.

---

## Multi-Provider Storage

### File Structure

Each authentication provider maintains separate token storage:

```
~/.amprealize/
├── auth_tokens_internal.json    # Internal auth tokens
├── auth_tokens_github.json      # GitHub OAuth tokens
└── auth_tokens_gitlab.json      # GitLab OAuth tokens (future)
```

### Token File Format

**File:** `~/.amprealize/auth_tokens_internal.json`

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

### Provider Isolation

- **Separate token files** prevent credential mixing
- **Provider-specific scopes** enable fine-grained permissions
- **Independent expiration** allows different TTLs per provider
- **Concurrent usage** supports multiple active sessions

### List Providers (Programmatic)

**Python:**
```python
from amprealize.auth.token_storage import FileTokenStore

store = FileTokenStore()
providers = store.list_providers()
print(f"Active providers: {providers}")
# Output: ['internal', 'github']
```

**API:**
```bash
curl http://localhost:8000/api/v1/auth/providers
```

---

## Architecture

### Components

```
┌─────────────────────────────────────────────────┐
│           DeviceFlowManager                      │
│  (Orchestrates multi-provider auth flows)       │
└───────────┬─────────────────────┬───────────────┘
            │                     │
            ▼                     ▼
┌─────────────────────┐  ┌─────────────────────┐
│ InternalAuthProvider│  │  GitHubOAuthProvider│
│  (Username/Password)│  │   (OAuth 2.0 Flow)  │
└──────────┬──────────┘  └──────────┬──────────┘
           │                        │
           ▼                        ▼
┌─────────────────────────────────────────────────┐
│              FileTokenStore                      │
│  (Provider-isolated token persistence)          │
└─────────────────────────────────────────────────┘
```

### InternalAuthProvider

**Location:** `amprealize/auth/providers/internal.py`

**Responsibilities:**
- User registration with password hashing (bcrypt, cost=12)
- Credential validation against PostgreSQL user store
- JWT token generation (HS256 algorithm)
- Token refresh flows

**Dependencies:**
- `UserService`: PostgreSQL user CRUD operations
- `JWTService`: Token signing and validation
- `bcrypt`: Password hashing library

**Key Methods:**

```python
class InternalAuthProvider:
    def register(
        self,
        username: str,
        password: str,
        email: Optional[str] = None
    ) -> TokenResponse:
        """
        Register new user and return JWT tokens.

        Raises:
            OAuthError: If username exists or validation fails
        """

    def login(
        self,
        username: str,
        password: str
    ) -> TokenResponse:
        """
        Authenticate user and return JWT tokens.

        Raises:
            OAuthError: If credentials invalid
        """
```

---

### JWT Token Structure

**Header:**
```json
{
  "alg": "HS256",
  "typ": "JWT"
}
```

**Payload (Access Token):**
```json
{
  "sub": "550e8400-e29b-41d4-a716-446655440000",  // User ID
  "username": "alice",
  "scopes": ["user:read", "user:write"],
  "iat": 1700000000,  // Issued at (Unix timestamp)
  "exp": 1700003600,  // Expires at (1 hour later)
  "type": "access"
}
```

**Payload (Refresh Token):**
```json
{
  "sub": "550e8400-e29b-41d4-a716-446655440000",
  "username": "alice",
  "iat": 1700000000,
  "exp": 1702592000,  // Expires at (30 days later)
  "type": "refresh"
}
```

**Signature:**
```
HMACSHA256(
  base64UrlEncode(header) + "." + base64UrlEncode(payload),
  secret_key
)
```

### Token Lifetimes

| Token Type | Default TTL | Configurable | Use Case |
|------------|-------------|--------------|----------|
| Access     | 1 hour      | Yes (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`) | API requests |
| Refresh    | 30 days     | Yes (`JWT_REFRESH_TOKEN_EXPIRE_DAYS`) | Token renewal |

---

## Security

### Password Security

**Hashing Algorithm:** bcrypt with cost factor 12

```python
# Password is hashed before storage
hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))
```

**Best Practices:**
- ✅ Minimum 8 characters enforced
- ✅ Salt generated per-password (bcrypt default)
- ✅ Passwords never logged or stored in plaintext
- ✅ Cost factor 12 balances security and performance (~250ms hash time)

**Recommendations for Production:**
- Enforce password complexity (uppercase, lowercase, numbers, symbols)
- Implement rate limiting on login attempts (5 attempts per 15 minutes)
- Add account lockout after repeated failures (10 attempts → 1 hour lockout)
- Consider integrating password breach databases (HaveIBeenPwned API)

---

### Token Security

**Storage:**
- Tokens stored in `~/.amprealize/auth_tokens_*.json` with `0600` permissions (owner read/write only)
- Files created with restrictive umask to prevent world-readable tokens

**Transmission:**
- API endpoints require HTTPS in production
- Tokens transmitted in `Authorization: Bearer <token>` header
- Never include tokens in URLs or query parameters

**Validation:**
- Signature verified on every API request
- Expiration checked (`exp` claim)
- Scope validation ensures least-privilege access

**Best Practices:**
- ✅ Short-lived access tokens (1 hour)
- ✅ Long-lived refresh tokens (30 days) for better UX
- ✅ Token rotation on refresh
- ⚠️ **TODO:** Implement token revocation list for logout/compromise scenarios

---

### API Security

**CORS Configuration:**
```python
# Production: Restrict to known origins
CORS_ORIGINS = ["https://amprealize.example.com"]

# Development: Localhost only
CORS_ORIGINS = ["http://localhost:3000", "http://localhost:8000"]
```

**Rate Limiting (Recommended):**
```python
# Add to api.py for production deployment
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/api/v1/auth/internal/login")
@limiter.limit("5/minute")  # 5 login attempts per minute per IP
async def login_endpoint(...):
    ...
```

**Input Validation:**
- All inputs sanitized via Pydantic models
- SQL injection prevented by parameterized queries (SQLAlchemy ORM)
- XSS prevented by JSON-only API (no HTML rendering)

---

### Environment Variables

**Required for Production:**

```bash
# JWT secret key (generate with: openssl rand -hex 32)
export JWT_SECRET_KEY="your-secret-key-here"

# PostgreSQL connection (user database)
export AMPREALIZE_COMPLIANCE_PG_DSN="postgresql://user:pass@host:5432/amprealize"

# Optional: Token lifetimes
export JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60       # Default: 60
export JWT_REFRESH_TOKEN_EXPIRE_DAYS=30         # Default: 30
```

**Security Checklist:**
- [ ] Use strong random secret key (256-bit minimum)
- [ ] Rotate `JWT_SECRET_KEY` every 90 days
- [ ] Store secrets in secure vault (AWS Secrets Manager, HashiCorp Vault)
- [ ] Never commit secrets to version control
- [ ] Use different keys for dev/staging/production environments

**Behaviors:** `behavior_externalize_configuration`, `behavior_prevent_secret_leaks`, `behavior_rotate_leaked_credentials`

---

## Troubleshooting

### Registration Fails with "Username already exists"

**Symptom:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/internal/register ...
# 409 Conflict: "Username 'alice' already exists"
```

**Cause:** Username is already registered in the database.

**Solutions:**
1. Choose a different username
2. If testing, clear the database:
   ```bash
   psql $AMPREALIZE_COMPLIANCE_PG_DSN -c "DELETE FROM users WHERE username='alice';"
   ```
3. Implement username uniqueness check before registration (UI improvement)

---

### Login Returns 401 "Invalid credentials"

**Symptom:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/internal/login ...
# 401 Unauthorized: "Invalid username or password"
```

**Debugging Steps:**

1. **Verify username exists:**
   ```bash
   psql $AMPREALIZE_COMPLIANCE_PG_DSN -c "SELECT username FROM users WHERE username='alice';"
   ```

2. **Check password (re-register if needed):**
   ```bash
   amprealize auth register  # Re-register with known password
   ```

3. **Verify API server configuration:**
   ```bash
   curl http://localhost:8000/api/v1/auth/providers
   # Should include "internal"
   ```

4. **Check API logs:**
   ```bash
   tail -f /tmp/amprealize_api.log | grep "internal/login"
   ```

---

### Token File Not Created

**Symptom:**
```bash
amprealize auth login --provider internal
# Success message shown, but no file at ~/.amprealize/auth_tokens_internal.json
```

**Debugging Steps:**

1. **Check directory permissions:**
   ```bash
   ls -la ~/.amprealize/
   # Should be drwx------ (0700)
   ```

2. **Manually create directory:**
   ```bash
   mkdir -p ~/.amprealize
   chmod 700 ~/.amprealize
   ```

3. **Check disk space:**
   ```bash
   df -h ~
   ```

4. **Enable debug logging:**
   ```bash
   export AMPREALIZE_LOG_LEVEL=DEBUG
   amprealize auth login --provider internal
   ```

---

### CLI Password Prompt Not Appearing

**Symptom:**
```bash
amprealize auth register
# Username: alice
# [Hangs, no password prompt]
```

**Cause:** Terminal not attached or TTY issues.

**Solutions:**

1. **Verify TTY:**
   ```bash
   tty
   # Should output: /dev/ttys000 (or similar)
   ```

2. **Run in interactive shell:**
   ```bash
   python -c "import sys; print(sys.stdin.isatty())"
   # Should output: True
   ```

3. **Use API instead:**
   ```bash
   curl -X POST http://localhost:8000/api/v1/auth/internal/register \
     -H "Content-Type: application/json" \
     -d '{"username": "alice", "password": "SecurePass123"}'
   ```

---

### API Returns 500 "Internal Server Error"

**Symptom:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/internal/register ...
# 500 Internal Server Error
```

**Debugging Steps:**

1. **Check API logs:**
   ```bash
   tail -50 /tmp/amprealize_api.log
   ```

2. **Verify database connection:**
   ```bash
   psql $AMPREALIZE_COMPLIANCE_PG_DSN -c "SELECT 1;"
   ```

3. **Check environment variables:**
   ```bash
   env | grep AMPREALIZE
   # Should include AMPREALIZE_COMPLIANCE_PG_DSN
   ```

4. **Restart API server:**
   ```bash
   pkill -f "uvicorn amprealize.api"
   python -m amprealize.api
   ```

5. **Check database schema:**
   ```bash
   psql $AMPREALIZE_COMPLIANCE_PG_DSN -c "\dt"
   # Should include 'users' table
   ```

---

### Multiple Provider Tokens Conflict

**Symptom:**
```bash
amprealize auth status
# Shows GitHub token when expecting internal token
```

**Solution:**

Explicitly specify provider:

```bash
amprealize auth status --provider internal
```

Or check token files directly:

```bash
ls -1 ~/.amprealize/auth_tokens_*.json
cat ~/.amprealize/auth_tokens_internal.json
```

---

### Token Expired Error

**Symptom:**
```bash
amprealize run workflow --workflow-id abc123
# Error: Token expired
```

**Solutions:**

1. **Refresh token (automatic):**
   ```bash
   amprealize auth refresh --provider internal
   ```

2. **Re-login:**
   ```bash
   amprealize auth login --provider internal
   ```

3. **Check token expiration:**
   ```bash
   python -c "
   import json, jwt
   token = json.load(open('~/.amprealize/auth_tokens_internal.json'))['access_token']
   payload = jwt.decode(token, options={'verify_signature': False})
   print(f'Expires: {payload[\"exp\"]}')
   "
   ```

---

## Migration from GitHub OAuth

### Step 1: Register Internal Account

```bash
amprealize auth register
# Username: your-github-username
# Password: ********
# Email: your-github-email@example.com
```

### Step 2: Migrate Workflows (Optional)

Internal and GitHub auth can coexist. No migration required unless you want to consolidate.

### Step 3: Update CI/CD (If Applicable)

**Before (GitHub OAuth):**
```bash
export GITHUB_TOKEN=ghp_...
amprealize auth login --provider github
```

**After (Internal Auth):**
```bash
export AMPREALIZE_USERNAME=alice
export AMPREALIZE_PASSWORD=SecurePass123
amprealize auth login --provider internal << EOF
$AMPREALIZE_USERNAME
$AMPREALIZE_PASSWORD
EOF
```

Or use API tokens:

```bash
curl -X POST http://localhost:8000/api/v1/auth/internal/login \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$AMPREALIZE_USERNAME\",\"password\":\"$AMPREALIZE_PASSWORD\"}" \
  | jq -r '.access_token' > /tmp/amprealize_token.txt

export AMPREALIZE_TOKEN=$(cat /tmp/amprealize_token.txt)
```

---

## Related Documentation

- **[`MULTI_PROVIDER_AUTH_ARCHITECTURE.md`](MULTI_PROVIDER_AUTH_ARCHITECTURE.md)**: Overall auth system design
- **[`MCP_SERVER_DESIGN.md`](MCP_SERVER_DESIGN.md)**: Control-plane architecture
- **[`SECRETS_MANAGEMENT_PLAN.md`](SECRETS_MANAGEMENT_PLAN.md)**: Credential rotation and storage
- **[`ACTION_REGISTRY_SPEC.md`](ACTION_REGISTRY_SPEC.md)**: Action logging for auth events
- **[`AGENTS.md`](AGENTS.md)**: Reusable behaviors for auth workflows

**Behaviors Referenced:**
- `behavior_externalize_configuration`: Environment variable management
- `behavior_prevent_secret_leaks`: Pre-commit hooks and secret scanning
- `behavior_rotate_leaked_credentials`: Credential rotation procedures
- `behavior_lock_down_security_surface`: CORS, auth middleware, token validation
- `behavior_update_docs_after_changes`: Documentation maintenance

---

## Support

**Issues:** https://github.com/SandRiseStudio/amprealize/issues
**Discussions:** https://github.com/SandRiseStudio/amprealize/discussions
**Security:** security@amprealize.example.com (for vulnerability reports)

---

**Last Updated:** November 14, 2025
**Document Version:** 1.0
**Maintained By:** Amprealize Engineering Team
