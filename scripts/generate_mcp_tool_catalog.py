#!/usr/bin/env python3
"""Generate MCP tool catalog documentation from manifests.

This script reads all tool manifests from mcp/tools/*.json and generates
a comprehensive markdown catalog at docs/MCP_TOOL_CATALOG.md.

Follows behavior_update_docs_after_changes from AGENTS.md.
"""
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from collections import defaultdict


def load_manifests(tools_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Load all tool manifests from tools directory."""
    manifests = {}

    if not tools_dir.exists():
        print(f"❌ Tools directory not found: {tools_dir}")
        sys.exit(1)

    for manifest_file in sorted(tools_dir.glob("*.json")):
        try:
            with open(manifest_file, "r") as f:
                data = json.load(f)
                tool_name = manifest_file.stem
                manifests[tool_name] = data
        except json.JSONDecodeError as e:
            print(f"⚠️  Warning: Could not parse {manifest_file}: {e}")
        except Exception as e:
            print(f"⚠️  Warning: Error loading {manifest_file}: {e}")

    return manifests


def extract_parameters(schema: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract parameter definitions from JSON schema."""
    params = []

    if "properties" not in schema:
        return params

    required = set(schema.get("required", []))
    properties = schema["properties"]

    for param_name, param_def in properties.items():
        param_info = {
            "name": param_name,
            "type": param_def.get("type", "unknown"),
            "required": param_name in required,
            "description": param_def.get("description", ""),
        }

        # Handle enum values
        if "enum" in param_def:
            param_info["enum"] = param_def["enum"]

        # Handle oneOf constraints
        if "oneOf" in param_def:
            param_info["oneOf"] = True

        # Handle array items
        if param_def.get("type") == "array" and "items" in param_def:
            item_type = param_def["items"].get("type", "unknown")
            param_info["type"] = f"array<{item_type}>"

        params.append(param_info)

    return params


def group_tools_by_prefix(manifests: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    """Group tool names by their prefix (service category)."""
    groups = defaultdict(list)

    for tool_name in manifests.keys():
        prefix = tool_name.split(".")[0]
        groups[prefix].append(tool_name)

    return dict(groups)


def format_parameter_row(param: Dict[str, Any]) -> str:
    """Format a parameter as a markdown table row."""
    name = param["name"]
    required_marker = "**required**" if param["required"] else "optional"
    param_type = param["type"]

    # Add enum values if present
    if "enum" in param:
        enum_vals = ", ".join(f"`{v}`" for v in param["enum"][:5])
        if len(param["enum"]) > 5:
            enum_vals += ", ..."
        param_type += f" ({enum_vals})"

    description = param["description"].replace("\n", " ")

    return f"| `{name}` | {param_type} | {required_marker} | {description} |"


def generate_catalog_markdown(manifests: Dict[str, Dict[str, Any]]) -> str:
    """Generate complete catalog markdown."""
    lines = [
        "# MCP Tool Catalog",
        "",
        "This document catalogs all available MCP tools for the amprealize platform.",
        f"**Total tools**: {len(manifests)}",
        "",
        "## Table of Contents",
        "",
    ]

    # Group tools by service prefix
    groups = group_tools_by_prefix(manifests)

    # Generate TOC
    for prefix in sorted(groups.keys()):
        count = len(groups[prefix])
        lines.append(f"- [{prefix.title()} Service](#service-{prefix}) ({count} tools)")

    lines.extend([
        "",
        "---",
        "",
    ])

    # Generate detailed sections for each service
    for prefix in sorted(groups.keys()):
        lines.extend([
            f"## Service: {prefix}",
            "",
            f"**Tool count**: {len(groups[prefix])}",
            "",
        ])

        # List each tool in this service
        for tool_name in sorted(groups[prefix]):
            manifest = manifests[tool_name]
            description = manifest.get("description", "No description")

            lines.extend([
                f"### `{tool_name}`",
                "",
                description,
                "",
            ])

            # Extract and display parameters
            input_schema = manifest.get("inputSchema", {})
            params = extract_parameters(input_schema)

            if params:
                lines.extend([
                    "**Parameters:**",
                    "",
                    "| Name | Type | Required | Description |",
                    "|------|------|----------|-------------|",
                ])

                for param in params:
                    lines.append(format_parameter_row(param))

                lines.append("")
            else:
                lines.extend([
                    "**Parameters:** None",
                    "",
                ])

            # Show required scopes if present
            if "requiredScopes" in manifest:
                scopes = manifest["requiredScopes"]
                scope_list = ", ".join(f"`{s}`" for s in scopes)
                lines.extend([
                    f"**Required scopes:** {scope_list}",
                    "",
                ])

            lines.append("---")
            lines.append("")

    # Footer
    lines.extend([
        "",
        "## Usage",
        "",
        "To call any tool via MCP:",
        "",
        "```json",
        '{',
        '  "jsonrpc": "2.0",',
        '  "id": 1,',
        '  "method": "tools/call",',
        '  "params": {',
        '    "name": "behaviors.list",',
        '    "arguments": {}',
        '  }',
        '}',
        "```",
        "",
        "## Batch Requests",
        "",
        "The MCP server supports batch requests per JSON-RPC 2.0 spec:",
        "",
        "```json",
        '[',
        '  {"jsonrpc":"2.0", "id":1, "method":"tools/call", "params":{"name":"behaviors.list"}},',
        '  {"jsonrpc":"2.0", "id":2, "method":"tools/call", "params":{"name":"runs.list"}}',
        ']',
        "```",
        "",
        "---",
        "",
        f"*Generated from {len(manifests)} tool manifests*",
    ])

    return "\n".join(lines)


def main():
    """Main entry point."""
    # Resolve paths
    repo_root = Path(__file__).parent.parent
    tools_dir = repo_root / "mcp" / "tools"
    output_file = repo_root / "docs" / "MCP_TOOL_CATALOG.md"

    print(f"📂 Loading manifests from: {tools_dir}")
    manifests = load_manifests(tools_dir)
    print(f"✅ Loaded {len(manifests)} tool manifests")

    print("📝 Generating catalog markdown...")
    catalog_md = generate_catalog_markdown(manifests)

    # Ensure docs directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)

    print(f"💾 Writing to: {output_file}")
    with open(output_file, "w") as f:
        f.write(catalog_md)

    print(f"✅ Tool catalog generated successfully")
    print(f"   Total tools: {len(manifests)}")
    print(f"   Output: {output_file}")


if __name__ == "__main__":
    main()
