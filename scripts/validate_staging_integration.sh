#!/usr/bin/env bash
# Quick validation script for staging integration testing
# Usage: ./scripts/validate_staging_integration.sh

set -euo pipefail

echo "======================================================================"
echo "Amprealize Staging Integration Testing - Quick Validation"
echo "======================================================================"
echo

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Step 1: Check staging environment
echo "1. Checking staging environment..."
if podman ps --filter "name=staging" --format "{{.Names}}" | grep -q "amprealize-api-staging"; then
    echo -e "${GREEN}✓${NC} Staging containers running"
    podman ps --filter "name=staging" --format "table {{.Names}}\t{{.Status}}"
else
    echo -e "${RED}✗${NC} Staging containers not running"
    echo "   Start with: cd deployment && podman-compose -f podman-compose-staging.yml up -d"
    exit 1
fi
echo

# Step 2: Check Gateway connectivity
echo "2. Checking staging gateway connectivity..."
if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Staging gateway responding at http://localhost:8080"
    curl -s http://localhost:8080/health | python -m json.tool 2>/dev/null || echo "{}"
else
    echo -e "${RED}✗${NC} Staging gateway not responding"
    echo "   Check logs: podman logs amprealize-nginx-staging"
    exit 1
fi
echo

# Step 3: Check OAuth configuration
echo "3. Checking OAuth configuration..."
if grep -q "OAUTH_CLIENT_ID=staging_github_client_id" deployment/staging.env; then
    echo -e "${YELLOW}⚠${NC}  OAuth credentials are PLACEHOLDERS"
    echo "   Create real GitHub OAuth App and update deployment/staging.env"
    echo "   Guide: https://github.com/settings/developers"
    echo "   Required: OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET"
    echo
    echo "   ⚠ Manual OAuth test will fail without real credentials"
else
    echo -e "${GREEN}✓${NC} OAuth credentials configured"
fi
echo

# Step 4: Check feature flags
echo "4. Checking feature flags..."
if grep -q "FEATURE_DEVICE_FLOW_AUTH=true" deployment/staging.env; then
    echo -e "${GREEN}✓${NC} Device flow auth enabled"
else
    echo -e "${RED}✗${NC} Device flow auth disabled"
    echo "   Enable in deployment/staging.env: FEATURE_DEVICE_FLOW_AUTH=true"
fi
echo

# Step 5: Check telemetry
echo "5. Checking telemetry configuration..."
if grep -q "TELEMETRY_ENABLED=true" deployment/staging.env; then
    echo -e "${GREEN}✓${NC} Telemetry enabled"
    echo "   Endpoint: $(grep OTEL_EXPORTER_OTLP_ENDPOINT deployment/staging.env | cut -d= -f2)"
else
    echo -e "${YELLOW}⚠${NC}  Telemetry disabled"
    echo "   Enable in deployment/staging.env: TELEMETRY_ENABLED=true"
fi
echo

# Step 6: Run quick validation
echo "6. Running quick integration test validation..."
if python tests/integration/test_staging_device_flow.py; then
    echo -e "${GREEN}✓${NC} Integration test script validated"
else
    echo -e "${RED}✗${NC} Integration test script failed validation"
    exit 1
fi
echo

# Summary
echo "======================================================================"
echo "Environment Status Summary"
echo "======================================================================"
echo
echo "Next steps:"
echo
echo "1. Run automated tests:"
echo "   pytest tests/integration/test_staging_device_flow.py -v"
echo
echo "2. Run MANUAL OAuth device flow test (REQUIRED for Phase 2 Objective 1):"
echo "   pytest -v -s -m manual tests/integration/test_staging_device_flow.py::TestStagingDeviceFlow::test_device_login_real_oauth"
echo
echo "3. After manual test, run token persistence validation:"
echo "   pytest -v -s tests/integration/test_staging_device_flow.py::TestStagingDeviceFlow::test_token_persistence_across_surfaces"
echo
echo "4. Verify telemetry events:"
echo "   pytest -v -s tests/integration/test_staging_device_flow.py::TestStagingDeviceFlow::test_telemetry_events_in_staging"
echo
echo "5. Document results in PRD_ALIGNMENT_LOG.md"
echo
echo "Full guide: docs/STAGING_INTEGRATION_TESTING_GUIDE.md"
echo
