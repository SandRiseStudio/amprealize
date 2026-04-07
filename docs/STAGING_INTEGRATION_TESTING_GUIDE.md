# Staging Integration Testing Guide

## Overview

This document guides you through **Phase 2: Staging Integration Testing** for MCP Device Flow, validating real OAuth flows with staging infrastructure.

## Status

- **Phase 1 Complete** ✅: All 27 unit tests passing (100%)
- **Phase 2 In Progress** ⏳: Staging integration testing
- **Staging Environment**: Running and healthy (3 containers, 2 days uptime)

## Prerequisites

### 1. Staging Environment Running

```bash
# Check staging containers
podman ps --filter "name=staging"

# Expected output:
# amprealize-nginx-staging  Up 2 days  0.0.0.0:8080->80/tcp
# amprealize-redis-staging  Up 2 days  0.0.0.0:6380->6379/tcp
# amprealize-api-staging    Up 2 days  0.0.0.0:8000->8000/tcp
```

If not running:
```bash
cd deployment
podman-compose -f podman-compose-staging.yml up -d
```

### 2. OAuth Configuration

**CRITICAL**: Verify GitHub OAuth app credentials in `deployment/staging.env`:

```bash
grep "OAUTH_" deployment/staging.env
```

Current values (lines 87-91):
- `OAUTH_CLIENT_ID=staging_github_client_id` ⚠️ **PLACEHOLDER**
- `OAUTH_CLIENT_SECRET=staging_github_client_secret` ⚠️ **PLACEHOLDER**
- `OAUTH_DEVICE_CODE_URL=https://github.com/login/device/code` ✅
- `OAUTH_TOKEN_URL=https://github.com/login/oauth/access_token` ✅
- `OAUTH_USER_URL=https://api.github.com/user` ✅

**If using placeholders**, create a real GitHub OAuth App:
1. Go to https://github.com/settings/developers
2. Create new OAuth App
3. Enable Device Flow
4. Update `deployment/staging.env` with real credentials
5. Restart staging: `podman-compose -f deployment/podman-compose-staging.yml restart api`

### 3. Feature Flags Enabled

Verify in `deployment/staging.env` (line 140):
```bash
grep "FEATURE_DEVICE_FLOW_AUTH" deployment/staging.env
# Should show: FEATURE_DEVICE_FLOW_AUTH=true ✅
```

### 4. Python Environment

```bash
# Activate virtual environment
source venv/bin/activate  # or your virtualenv path

# Install test dependencies
pip install pytest requests
```

## Test Suite Structure

### File: `tests/integration/test_staging_device_flow.py`

**Test Classes:**

1. **TestStagingDeviceFlow** - Core device flow integration tests
   - `test_staging_api_health` - API connectivity ✅ Automated
   - `test_device_login_real_oauth` - Real OAuth flow ⚠️ Manual
   - `test_auth_status_with_staging_tokens` - Token validation ✅ Automated
   - `test_token_persistence_across_surfaces` - CLI/MCP interop ✅ Automated
   - `test_telemetry_events_in_staging` - Observability ✅ Automated (if telemetry enabled)
   - `test_token_refresh_with_staging_oauth` - Refresh flow ✅ Automated
   - `test_logout_clears_staging_tokens` - Cleanup ✅ Automated

2. **TestStagingCLIMCPParity** - Cross-surface validation
   - `test_cli_login_visible_to_mcp` - CLI→MCP token sharing (TODO)
   - `test_mcp_login_visible_to_cli` - MCP→CLI token sharing (TODO)

## Running Tests

### Quick Health Check

```bash
# Validate staging connectivity
python tests/integration/test_staging_device_flow.py

# Expected output:
# ✓ Staging API: http://localhost:8000
#   Status: healthy
#   Version: unknown
#   Environment: unknown
```

### Automated Tests

Run all automated tests (skips manual OAuth flow):

```bash
pytest tests/integration/test_staging_device_flow.py -v
```

Expected results:
- ✅ `test_staging_api_health` - PASS
- ⚠️ `test_device_login_real_oauth` - SKIPPED (manual test)
- ✅ `test_auth_status_with_staging_tokens` - PASS or SKIP (if no tokens)
- ✅ `test_token_persistence_across_surfaces` - PASS or SKIP (if no tokens)
- ✅ `test_telemetry_events_in_staging` - PASS or SKIP (if telemetry disabled)
- ✅ `test_token_refresh_with_staging_oauth` - PASS or SKIP (if no tokens)
- ✅ `test_logout_clears_staging_tokens` - PASS or SKIP (if no tokens)

### Manual OAuth Flow Test

**This is the PRIMARY test for Phase 2 objective 1: "Test real device flow with OAuth server"**

```bash
# Run with output enabled to see instructions
pytest tests/integration/test_staging_device_flow.py::TestStagingDeviceFlow::test_device_login_real_oauth -v -s -m manual
```

**Test Flow:**
1. Script initiates device authorization with GitHub
2. Displays verification URL and user code:
   ```
   URL: https://github.com/login/device
   Code: ABCD-1234
   ```
3. **Human action required**: Visit URL and enter code
4. Script polls staging API (server-side polling to GitHub)
5. After approval, tokens returned and validated

**Expected Output:**
```
MANUAL TEST: Real OAuth Device Authorization Flow
================================================================================

1. Starting device login flow...

2. User authorization required:
   URL: https://github.com/login/device
   Code: XXXX-YYYY

   Please visit the URL above and enter the code to authorize.
   Waiting for approval (timeout in 300s)...

✓ Authorization successful!
   Access token: ey...
   Refresh token: ghu_...
   Scopes: ['behaviors.read', 'runs.create']
   Expires at: 2025-01-17T10:30:00Z
```

### Run All Tests Including Manual

```bash
pytest tests/integration/test_staging_device_flow.py -v -s
```

This will:
1. Run automated tests first
2. Prompt for manual OAuth approval
3. Use obtained tokens for subsequent tests (persistence, refresh, logout)

## Validation Checklist

### ✅ Objective 1: Test Real Device Flow with OAuth Server

- [ ] Run `test_device_login_real_oauth` with `-m manual`
- [ ] Verify user code displayed correctly
- [ ] Approve device code at GitHub URL
- [ ] Confirm tokens returned
- [ ] Validate token structure (access, refresh, scopes, expiry)

**Success Criteria:**
- Device authorization completes successfully
- Access token and refresh token both present
- Token expiry > 0 seconds
- Scopes match requested scopes

### ✅ Objective 2: Validate Token Persistence Across CLI/MCP Surfaces

After obtaining tokens via manual test:

```bash
# Run persistence test
pytest tests/integration/test_staging_device_flow.py::TestStagingDeviceFlow::test_token_persistence_across_surfaces -v -s

# Verify tokens accessible
pytest tests/integration/test_staging_device_flow.py::TestStagingDeviceFlow::test_auth_status_with_staging_tokens -v -s
```

**Manual CLI Validation** (if amprealize CLI installed):

```bash
# Check tokens stored by MCP test are visible to CLI
amprealize auth status --client-id amprealize-staging-test

# Expected output:
# ✓ Authenticated
# Client: amprealize-staging-test
# Scopes: behaviors.read, runs.create
# Access expires in: XXXs
```

**Success Criteria:**
- `test_token_persistence_across_surfaces` passes
- Tokens stored in consistent location (FileTokenStore)
- Both CLI and MCP surfaces can read same tokens
- Token bundle includes all required fields

### ✅ Objective 3: Verify Telemetry Events in Staging Observability Stack

**Check Telemetry Enabled:**
```bash
grep "TELEMETRY_ENABLED" deployment/staging.env
# Should show: TELEMETRY_ENABLED=true
```

**Run Telemetry Test:**
```bash
pytest tests/integration/test_staging_device_flow.py::TestStagingDeviceFlow::test_telemetry_events_in_staging -v -s
```

**Expected Output:**
```
✓ Found 5 device flow events today

Latest event:
  Type: device_flow.mcp.login_started
  Timestamp: 2025-01-17T09:45:23.123Z
  Client ID: amprealize-staging-test
```

**Manual Telemetry Verification** (if observability UI accessible):

1. Check OpenTelemetry Collector logs:
   ```bash
   podman logs amprealize-otel-collector-staging
   ```

2. Query telemetry API directly:
   ```bash
   curl -s "http://localhost:8000/api/v1/telemetry/events?event_type=device_flow.mcp.login_started&limit=10" | jq
   ```

3. Access observability dashboard (if available):
   - Jaeger UI: http://localhost:16686
   - Prometheus: http://localhost:9090

**Success Criteria:**
- Telemetry events captured for device flow operations
- Event types include: `login_started`, `login_completed`, `token_refreshed`, `logout`
- Events queryable via telemetry API
- Event schema includes: `event_id`, `timestamp`, `event_type`, `payload`

## Troubleshooting

### Issue: "Staging environment not available"

**Symptoms:**
```
pytest.skip: Staging environment not available: Connection refused
```

**Solution:**
```bash
# Check if containers running
podman ps --filter "name=staging"

# Start staging if not running
cd deployment
podman-compose -f podman-compose-staging.yml up -d

# Check logs
podman logs amprealize-api-staging
```

### Issue: "OAuth client credentials are placeholders"

**Symptoms:**
```
✗ Authorization failed: invalid_client
```

**Solution:**
1. Create real GitHub OAuth App (see Prerequisites §2)
2. Update `deployment/staging.env`:
   ```bash
   OAUTH_CLIENT_ID=your_real_client_id
   OAUTH_CLIENT_SECRET=your_real_client_secret
   ```
3. Restart API:
   ```bash
   podman-compose -f deployment/podman-compose-staging.yml restart api
   ```

### Issue: "No stored tokens - run manual login test first"

**Symptoms:**
```
pytest.skip: No stored tokens - run manual login test first
```

**Solution:**
This is expected if running tests out of order. Run the manual OAuth test first:
```bash
pytest tests/integration/test_staging_device_flow.py::TestStagingDeviceFlow::test_device_login_real_oauth -v -s -m manual
```

### Issue: Telemetry test fails or skips

**Symptoms:**
```
pytest.skip: Telemetry not enabled in staging
```

**Solution:**
```bash
# Enable telemetry in staging.env
echo "TELEMETRY_ENABLED=true" >> deployment/staging.env

# Restart services
podman-compose -f deployment/podman-compose-staging.yml restart
```

### Issue: Token refresh fails

**Symptoms:**
```
pytest.fail: Token refresh failed: invalid_grant
```

**Possible Causes:**
1. Refresh token expired (default: 7 days)
2. OAuth server rejected refresh
3. Token was manually revoked

**Solution:**
Run manual login test again to obtain fresh tokens.

## Test Results Documentation

After completing validation, document results in `PRD_ALIGNMENT_LOG.md`:

```markdown
## 2025-01-17: Staging Integration Testing Complete

### Phase 2: Staging Integration Testing ✅

**Objective 1: Test Real Device Flow with OAuth Server**
- Status: ✅ Complete
- Test: test_device_login_real_oauth
- Result: Device authorization successful with real GitHub OAuth
- Tokens: Access + refresh tokens obtained and validated
- Evidence: [link to test output or screenshot]

**Objective 2: Validate Token Persistence Across CLI/MCP Surfaces**
- Status: ✅ Complete
- Tests: test_token_persistence_across_surfaces, test_auth_status_with_staging_tokens
- Result: Tokens shared correctly between MCP API and FileTokenStore
- CLI validation: [manual CLI commands tested]
- Evidence: [test output showing token interoperability]

**Objective 3: Verify Telemetry Events in Staging Observability Stack**
- Status: ✅ Complete
- Test: test_telemetry_events_in_staging
- Result: Device flow events captured in OpenTelemetry
- Events found: login_started, login_completed, token_refreshed, logout
- Evidence: [telemetry query results or dashboard screenshot]

**Additional Tests:**
- Token refresh: ✅ Passed
- Logout cleanup: ✅ Passed
- API health: ✅ Passed

**Staging Environment:**
- API: http://localhost:8000 (healthy)
- Containers: nginx, redis, api (all healthy, 2+ days uptime)
- OAuth: GitHub device flow configured
- Telemetry: OpenTelemetry OTLP on localhost:4317

**Behaviors Referenced:**
- behavior_instrument_metrics_pipeline (telemetry validation)
- behavior_lock_down_security_surface (OAuth security)
- behavior_update_docs_after_changes (this guide)
```

## Next Steps

After completing Phase 2:

1. **Document Results**: Update `PRD_ALIGNMENT_LOG.md` with validation evidence
2. **Update Progress**: Mark Phase 2 complete in `PROGRESS_TRACKER.md`
3. **CLI Parity Tests**: Implement CLI→MCP and MCP→CLI token sharing tests
4. **Production Readiness**: Review staging results and plan production deployment
5. **Metrics Dashboard**: Configure analytics to track device flow adoption

## References

- **PRD**: `PRD.md` - Product requirements and success metrics
- **MCP Design**: `MCP_SERVER_DESIGN.md` - Device flow architecture
- **Action Registry**: `ACTION_REGISTRY_SPEC.md` - Reproducibility contracts
- **Telemetry Schema**: `TELEMETRY_SCHEMA.md` - Event model
- **Secrets Management**: `SECRETS_MANAGEMENT_PLAN.md` - OAuth credential handling
- **Staging Config**: `deployment/staging.env` - Environment variables
- **Unit Tests**: `tests/test_mcp_device_flow.py` - 27/27 passing (Phase 1 complete)
