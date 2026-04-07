#!/usr/bin/env python3
"""Quick tests for Phase 4 - Tenant Context & Isolation."""

import sys
sys.path.insert(0, '.')

# Test MCPServiceAdapter
from amprealize.mcp_service_adapter import TenantContext, MCPServiceAdapter, ContextSwitchHandler

# Test 1: TenantContext creation
ctx = TenantContext(
    user_id='user-123',
    org_id='org-456',
    project_id='proj-789',
    auth_method='device_flow',
    roles={'STUDENT'},
    granted_scopes={'behaviors.read', 'runs.create'},
)

assert ctx.user_id == 'user-123'
assert ctx.org_id == 'org-456'
assert ctx.identity == 'user-123'
assert ctx.identity_type == 'user'
print('✓ TenantContext with user passed')

# Test 2: TenantContext without org (optional org_id)
ctx2 = TenantContext(
    user_id='user-123',
    auth_method='device_flow',
)
assert ctx2.org_id is None
assert ctx2.identity == 'user-123'
print('✓ TenantContext without org passed')

# Test 3: Service Principal context
ctx3 = TenantContext(
    service_principal_id='sp-abc',
    org_id='org-456',
    auth_method='client_credentials',
)
assert ctx3.service_principal_id == 'sp-abc'
assert ctx3.identity == 'sp-abc'
assert ctx3.identity_type == 'service_principal'
print('✓ TenantContext with service principal passed')

# Test 4: Headers generation
ctx4 = TenantContext(
    user_id='user-123',
    org_id='org-456',
    auth_method='device_flow',
    roles={'ADMIN', 'STUDENT'},
)
headers = ctx4.to_headers()
assert headers['X-User-ID'] == 'user-123'
assert headers['X-Org-ID'] == 'org-456'
assert 'X-Request-ID' in headers
assert 'X-Roles' in headers
print('✓ TenantContext headers passed')

# Test 5: Headers omit optional fields when not set
ctx5 = TenantContext(user_id='user-123', auth_method='device_flow')
headers5 = ctx5.to_headers()
assert 'X-Org-ID' not in headers5
assert 'X-Project-ID' not in headers5
print('✓ TenantContext headers omit optional passed')

# Test 6: Audit context
audit = ctx.to_audit_context()
assert audit['user_id'] == 'user-123'
assert audit['org_id'] == 'org-456'
assert 'request_id' in audit
assert 'timestamp' in audit
print('✓ TenantContext audit context passed')

# Test 7: MCPServiceAdapter inject params
from unittest.mock import MagicMock

mock_session = MagicMock()
mock_session.user_id = 'user-123'
mock_session.service_principal_id = None
mock_session.org_id = 'org-456'
mock_session.project_id = 'proj-789'
mock_session.auth_method = 'device_flow'
mock_session.roles = ['STUDENT']
mock_session.granted_scopes = {'behaviors.read'}

adapter = MCPServiceAdapter(mock_session)
params = {'name': 'test'}
result = adapter.inject_tenant_params(params)

assert result['name'] == 'test'
assert result['org_id'] == 'org-456'
assert result['project_id'] == 'proj-789'
assert result['user_id'] == 'user-123'
print('✓ MCPServiceAdapter inject_tenant_params passed')

# Test 8: MCPServiceAdapter doesn't override existing params
params2 = {'org_id': 'other-org'}
result2 = adapter.inject_tenant_params(params2)
assert result2['org_id'] == 'other-org'
print('✓ MCPServiceAdapter respects existing params passed')

# Test 9: Verify tool manifests have correct scopes
import json
from pathlib import Path

tools_dir = Path(__file__).parent / 'mcp' / 'tools'

# Check setOrg manifest
set_org_manifest = tools_dir / 'context.setOrg.json'
if set_org_manifest.exists():
    with open(set_org_manifest) as f:
        manifest = json.load(f)
        assert 'context.switch' in manifest.get('required_scopes', [])
        print('✓ context.setOrg has required scope')

# Check setProject manifest
set_project_manifest = tools_dir / 'context.setProject.json'
if set_project_manifest.exists():
    with open(set_project_manifest) as f:
        manifest = json.load(f)
        assert 'context.switch' in manifest.get('required_scopes', [])
        print('✓ context.setProject has required scope')

# Check getContext is public
get_context_manifest = tools_dir / 'context.getContext.json'
if get_context_manifest.exists():
    with open(get_context_manifest) as f:
        manifest = json.load(f)
        assert manifest.get('required_scopes', []) == []
        print('✓ context.getContext is public (no scopes required)')

# Check clearContext has required scope
clear_context_manifest = tools_dir / 'context.clearContext.json'
if clear_context_manifest.exists():
    with open(clear_context_manifest) as f:
        manifest = json.load(f)
        assert 'context.switch' in manifest.get('required_scopes', [])
        print('✓ context.clearContext has required scope')

print('')
print('=' * 60)
print('All Phase 4 tests passed!')
print('=' * 60)
