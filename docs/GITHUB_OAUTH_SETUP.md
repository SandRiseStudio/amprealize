# GitHub OAuth App Setup for Amprealize Device Flow

This guide walks you through creating a GitHub OAuth App to enable real device authorization flow for Amprealize.

## Prerequisites

- GitHub account with admin access to an organization or personal account
- Amprealize repository access

## Step 1: Create GitHub OAuth App

1. **Navigate to GitHub OAuth Apps**:
   - For organization: `https://github.com/organizations/YOUR_ORG/settings/applications`
   - For personal: `https://github.com/settings/developers`

2. **Create New OAuth App**:
   - Click "Register a new application" button

3. **Fill in Application Details**:
   ```
   Application name: Amprealize Device Flow
   Homepage URL: https://github.com/YOUR_USERNAME/amprealize
   Application description: Amprealize device authorization for CLI, MCP, and IDE surfaces
   Authorization callback URL: http://localhost:8000/auth/callback
   ```

   ⚠️ **IMPORTANT**: During creation, check the box:
   ```
   ☑ Enable Device Flow
   ```
   This is required for device authorization to work. Without this, Amprealize device flow will fail.

4. **Register the Application**:
   - Click "Register application"

5. **Generate Client Secret**:
   - Click "Generate a new client secret"
   - **Copy the secret immediately** (you won't be able to see it again)

6. **Note Your Credentials**:
   - Client ID: Shows on the app page (e.g., `Iv1.a1b2c3d4e5f6g7h8`)
   - Client Secret: The secret you just generated

## Step 2: Configure Amprealize

### Option A: Environment Variables (Recommended)

Create or update `.env` file in the project root:

```bash
# GitHub OAuth Configuration
OAUTH_CLIENT_ID=Iv1.YOUR_CLIENT_ID_HERE
OAUTH_CLIENT_SECRET=your_client_secret_here

# Device Flow URLs (defaults already set)
OAUTH_DEVICE_CODE_URL=https://github.com/login/device/code
OAUTH_TOKEN_URL=https://github.com/login/oauth/access_token
OAUTH_USER_URL=https://api.github.com/user

# Device Flow Settings
AMPREALIZE_DEVICE_VERIFICATION_URI=https://device.amprealize.dev/activate
AMPREALIZE_DEVICE_CODE_TTL_SECONDS=600
AMPREALIZE_DEVICE_POLL_INTERVAL_SECONDS=5
AMPREALIZE_ACCESS_TOKEN_TTL_SECONDS=3600
AMPREALIZE_REFRESH_TOKEN_TTL_SECONDS=604800
```

### Option B: Export in Shell

```bash
export OAUTH_CLIENT_ID=Iv1.YOUR_CLIENT_ID_HERE
export OAUTH_CLIENT_SECRET=your_client_secret_here
```

### Option C: Test Configuration

For testing only, you can use the helper script:

```bash
./scripts/setup_github_oauth.sh
```

This will prompt for your credentials and create `.env.github-oauth` file.

## Step 3: Verify Configuration

Run the verification script:

```bash
python scripts/verify_oauth_config.py
```

Expected output:
```
✓ OAuth Client ID configured (Iv1.a1b2c3d4...)
✓ OAuth Client Secret configured (32 characters)
✓ Device code URL: https://github.com/login/device/code
✓ Token URL: https://github.com/login/oauth/access_token
✓ Verification URI: https://device.amprealize.dev/activate

Configuration is ready for device flow testing.
```

## Step 4: Test Device Flow

### A. Via MCP Server

```bash
# Start MCP server with OAuth configured
export OAUTH_CLIENT_ID=Iv1.YOUR_CLIENT_ID_HERE
export OAUTH_CLIENT_SECRET=your_client_secret_here

# Run device login test
python -c "
from amprealize.mcp_device_flow import MCPDeviceFlow
import asyncio

async def test():
    mcp = MCPDeviceFlow()
    result = await mcp.device_login(
        client_id='amprealize-mcp-test',
        scopes=['read:user']
    )
    print(f'Visit: {result[\"verification_uri_complete\"]}')
    print(f'Code: {result[\"user_code\"]}')

asyncio.run(test())
"
```

### B. Via REST API

```bash
# Start API server
export OAUTH_CLIENT_ID=Iv1.YOUR_CLIENT_ID_HERE
export OAUTH_CLIENT_SECRET=your_client_secret_here
export AMPREALIZE_COMPLIANCE_PG_DSN="postgresql://amprealize_compliance:compliance_test_pass@localhost:6437/amprealize_compliance"

uvicorn amprealize.api:app --host 127.0.0.1 --port 8000 &

# Test device login endpoint
curl -X POST http://localhost:8000/api/v1/auth/device/login \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "amprealize-api-test",
    "scopes": ["read:user"]
  }'
```

### C. Run Integration Tests

```bash
export OAUTH_CLIENT_ID=Iv1.YOUR_CLIENT_ID_HERE
export OAUTH_CLIENT_SECRET=your_client_secret_here

./scripts/run_tests.sh tests/integration/test_staging_device_flow.py::TestStagingDeviceFlow::test_device_login_real_oauth -v
```

## Step 5: Complete Device Authorization

When you run device flow:

1. The system generates a `user_code` (e.g., `BJBG-MZSW`)
2. You'll see a `verification_uri` (https://github.com/login/device)
3. Visit the URL and enter the code
4. Authorize the Amprealize app
5. The system polls GitHub and retrieves the access token

## Troubleshooting

### Error: "Device flow not enabled for this application"

- Go to your GitHub OAuth app settings
- Ensure "Enable Device Flow" is checked
- Save changes and retry

### Error: "Invalid client credentials"

- Verify `OAUTH_CLIENT_ID` starts with `Iv1.`
- Verify `OAUTH_CLIENT_SECRET` is correct (no extra spaces)
- Regenerate secret if needed

### Error: "Verification URI not accessible"

The default `https://device.amprealize.dev/activate` is a placeholder. For testing:

1. Use GitHub's verification URI instead:
   ```bash
   export AMPREALIZE_DEVICE_VERIFICATION_URI=https://github.com/login/device
   ```

2. Or set up a custom verification page (see [DEVICE_VERIFICATION_SETUP.md](./DEVICE_VERIFICATION_SETUP.md))

### Error: "Connection refused" during tests

Ensure test containers are running:

```bash
podman-compose -f docker-compose.test.yml up -d
./scripts/run_tests.sh --check-only
```

## Security Best Practices

1. **Never commit credentials**: Ensure `.env` is in `.gitignore`
2. **Use different apps for environments**: Create separate OAuth apps for dev/staging/prod
3. **Rotate secrets regularly**: GitHub allows multiple client secrets
4. **Limit scopes**: Only request necessary permissions
5. **Monitor usage**: Check OAuth app usage in GitHub settings

## References

- [GitHub Device Flow Documentation](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps#device-flow)
- [RFC 8628: OAuth 2.0 Device Authorization Grant](https://datatracker.ietf.org/doc/html/rfc8628)
- [Amprealize MCP Server Design](contracts/MCP_SERVER_DESIGN.md)
- [Device Flow Implementation](../amprealize/device_flow.py)

## Next Steps

After setting up OAuth:

1. ✅ Test device login flow manually
2. ✅ Run integration tests with real credentials
3. 📋 Set up staging environment with dedicated OAuth app
4. 📋 Configure production OAuth app with proper callback URLs
5. 📋 Implement custom verification page at device.amprealize.dev
6. 📋 Add telemetry for auth success/failure rates
