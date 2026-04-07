# OAuth Configuration Quick Reference

## Current Status
✗ OAuth Client ID: **NOT SET**
✗ OAuth Client Secret: **NOT SET**
✓ GitHub URLs: Configured correctly

## Setup Options

### Option 1: Interactive Script (Recommended)
```bash
./scripts/setup_github_oauth.sh
```
- Prompts for credentials
- Creates `.env.github-oauth` file
- Adds to `.gitignore` automatically

### Option 2: Manual Environment Variables
```bash
export OAUTH_CLIENT_ID=Iv1.YOUR_CLIENT_ID_HERE
export OAUTH_CLIENT_SECRET=your_client_secret_here
```

### Option 3: Update settings.py Directly
```python
# amprealize/config/settings.py lines 185-186
oauth_client_id: str = "Iv1.YOUR_CLIENT_ID_HERE"
oauth_client_secret: str = "your_client_secret_here"
```
⚠️ **Not recommended** - settings.py is version controlled

## Create GitHub OAuth App

1. **Go to GitHub**:
   - Personal: https://github.com/settings/developers
   - Organization: https://github.com/organizations/YOUR_ORG/settings/applications

2. **Click "New OAuth App"**

3. **Fill in details**:
   ```
   Application name: Amprealize Device Flow (Dev)
   Homepage URL: https://github.com/SandRiseStudio/amprealize
   Authorization callback URL: http://localhost:8000/auth/callback
   ```

4. **After creation**:
   - ✅ Enable "Device Flow" (if option exists)
   - ✅ Generate client secret
   - ✅ Copy Client ID (starts with `Iv1.` or `Iv23`)
   - ✅ Copy Client Secret (you won't see it again!)

## Verify Configuration

```bash
python scripts/verify_oauth_config.py
```

Expected output when configured:
```
✓ OAuth Client ID: Iv1.a1b2c3d4... (18 characters)
✓ OAuth Client Secret: abc123... (40 characters)
✓ Device Code URL: https://github.com/login/device/code
✓ Configuration is ready for device flow testing
```

## Test OAuth Flow

### 1. Start API Server
```bash
source .env.github-oauth  # If using Option 1
uvicorn amprealize.api:app --host 127.0.0.1 --port 8000
```

### 2. Run Integration Test
```bash
pytest tests/integration/test_staging_device_flow.py::TestStagingDeviceFlow::test_device_login_real_oauth -v -s
```

### 3. Manual Test via cURL
```bash
curl -X POST http://localhost:8000/api/v1/auth/device/login \
  -H "Content-Type: application/json" \
  -d '{"client_id": "amprealize-test", "scopes": ["read:user"]}'
```

Expected response:
```json
{
  "device_code": "abc123...",
  "user_code": "BJBG-MZSW",
  "verification_uri": "https://github.com/login/device",
  "verification_uri_complete": "https://github.com/login/device?user_code=BJBG-MZSW",
  "expires_in": 600,
  "interval": 5
}
```

## Complete Authorization

1. Visit the `verification_uri_complete` URL
2. Authorize the Amprealize app on GitHub
3. Integration test will poll and receive access token
4. Test passes ✅

## Expected Test Results After Configuration

### Before OAuth Setup (Current):
- ✅ 3/9 tests passing
- ⚠️ 1 test failing (needs OAuth authorization)
- ⏭️ 5 tests skipped (need tokens/CLI/telemetry)

### After OAuth Setup:
- ✅ 6/9 tests passing (3 existing + 3 token-dependent)
- ⏭️ 2 tests skipped (CLI not available)
- ⏭️ 1 test skipped (telemetry backend placeholder)

## Security Checklist

- [ ] `.env.github-oauth` is in `.gitignore`
- [ ] Never commit credentials to git
- [ ] Use separate OAuth apps for dev/staging/prod
- [ ] Rotate secrets if exposed
- [ ] Run pre-commit hooks before pushing

## Troubleshooting

### "Device flow not enabled"
→ Check GitHub OAuth app settings, enable Device Flow

### "Invalid client credentials"
→ Verify no extra spaces, Client ID starts with `Iv`, regenerate secret if needed

### "Connection refused" during tests
→ Ensure test containers running: `podman compose -f infra/docker-compose.test.yml up -d`

### "Verification URI not accessible"
→ Use GitHub's URL for now: `export AMPREALIZE_DEVICE_VERIFICATION_URI=https://github.com/login/device`

## Resources

- 📖 Full Guide: [docs/GITHUB_OAUTH_SETUP.md](./GITHUB_OAUTH_SETUP.md)
- 🔧 Setup Script: [scripts/setup_github_oauth.sh](../scripts/setup_github_oauth.sh)
- ✅ Verification: [scripts/verify_oauth_config.py](../scripts/verify_oauth_config.py)
- 📋 GitHub Docs: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps#device-flow
