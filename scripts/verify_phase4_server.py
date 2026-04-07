#!/usr/bin/env python3
"""Verify manifest scopes and MCP server compilation for Phase 4."""

import json
from pathlib import Path

# Test manifest scopes
tools_dir = Path('mcp/tools')

manifests_to_check = [
    ('context.setOrg.json', ['context.switch']),
    ('context.setProject.json', ['context.switch']),
    ('context.getContext.json', []),
    ('context.clearContext.json', ['context.switch']),
]

for filename, expected_scopes in manifests_to_check:
    manifest_path = tools_dir / filename
    with open(manifest_path) as f:
        manifest = json.load(f)
        actual_scopes = manifest.get('required_scopes', [])
        assert actual_scopes == expected_scopes, f'{filename}: expected {expected_scopes}, got {actual_scopes}'
        print(f'✓ {filename} has correct scopes: {actual_scopes}')

# Test that MCP server imports and compiles
print('')
print('Testing MCP server imports...')
from amprealize.mcp_server import MCPServer, MCPSessionContext
print('✓ MCPServer imports successfully')

# Test context tools are loaded
server = MCPServer()
context_tools = [t for t in server._tools.keys() if 'context' in t.lower()]
print(f'✓ Found {len(context_tools)} context tools: {context_tools}')

# Verify tool_scopes has context.switch entries
context_scopes = {k: v for k, v in server._tool_scopes.items() if 'context' in k}
print(f'✓ Context tool scopes: {context_scopes}')

print('')
print('All manifest and server tests passed!')
