"""
AgentAuth CLI command implementations to add to amprealize/cli.py

Add these functions after the metrics command functions around line 1200.
Add the parser setup after the metrics_parser section around line 980.
Add the dispatch logic in main() after the metrics handling around line 2940.
"""

# =============================================================================
# AgentAuth CLI Command Functions
# =============================================================================

def _command_auth_ensure_grant(args: argparse.Namespace) -> int:
    """Handle 'amprealize auth ensure-grant' command."""
    adapter = _get_agent_auth_adapter()

    result = adapter.ensure_grant(
        agent_id=args.agent_id,
        tool_name=args.tool_name,
        scopes=args.scopes,
        user_id=args.user_id,
        context={k: v for k, v in (ctx.split("=", 1) for ctx in args.context)} if args.context else None,
    )

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"Decision: {result['decision']}")
        if "reason" in result:
            print(f"Reason: {result['reason']}")
        if "consent_url" in result:
            print(f"Consent URL: {result['consent_url']}")
            print(f"Consent Request ID: {result['consent_request_id']}")
        if "grant" in result:
            grant = result["grant"]
            print(f"\nGrant ID: {grant['grant_id']}")
            print(f"Expires: {grant['expires_at']}")
            print(f"Scopes: {', '.join(grant['scopes'])}")

    return 0


def _command_auth_list_grants(args: argparse.Namespace) -> int:
    """Handle 'amprealize auth list-grants' command."""
    adapter = _get_agent_auth_adapter()

    grants = adapter.list_grants(
        agent_id=args.agent_id,
        user_id=args.user_id,
        tool_name=args.tool_name,
        include_expired=args.include_expired,
    )

    if args.format == "json":
        print(json.dumps(grants, indent=2))
    else:
        if not grants:
            print("No grants found.")
            return 0

        print(f"Found {len(grants)} grant(s):\n")
        for grant in grants:
            print(f"Grant ID: {grant['grant_id']}")
            print(f"  Agent: {grant['agent_id']}")
            print(f"  Tool: {grant['tool_name']}")
            print(f"  Scopes: {', '.join(grant['scopes'])}")
            print(f"  Expires: {grant['expires_at']}")
            print()

    return 0


def _command_auth_policy_preview(args: argparse.Namespace) -> int:
    """Handle 'amprealize auth policy-preview' command."""
    adapter = _get_agent_auth_adapter()

    result = adapter.policy_preview(
        agent_id=args.agent_id,
        tool_name=args.tool_name,
        scopes=args.scopes,
        user_id=args.user_id,
        context={k: v for k, v in (ctx.split("=", 1) for ctx in args.context)} if args.context else None,
    )

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"Decision: {result['decision']}")
        if "reason" in result:
            print(f"Reason: {result['reason']}")
        if "bundle_version" in result:
            print(f"Bundle Version: {result['bundle_version']}")
        if "obligations" in result and result["obligations"]:
            print("\nObligations:")
            for obl in result["obligations"]:
                print(f"  - {obl['type']}: {obl['attributes']}")

    return 0


def _command_auth_revoke(args: argparse.Namespace) -> int:
    """Handle 'amprealize auth revoke' command."""
    adapter = _get_agent_auth_adapter()

    result = adapter.revoke_grant(
        grant_id=args.grant_id,
        revoked_by=args.revoked_by,
        reason=args.reason,
    )

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        if result["success"]:
            print(f"✓ Grant {result['grant_id']} revoked successfully.")
        else:
            print(f"✗ Failed to revoke grant {result['grant_id']}")
            if "reason" in result:
                print(f"  Reason: {result['reason']}")

    return 0


# =============================================================================
# AgentAuth Parser Setup (add after metrics_parser around line 980)
# =============================================================================

AUTH_PARSER_SETUP = '''
# AgentAuth subcommands
auth_parser = subparsers.add_parser(
    "auth",
    help="Agent authentication and authorization operations"
)
auth_subparsers = auth_parser.add_subparsers(dest="auth_command", required=True)

# auth ensure-grant
ensure_grant_parser = auth_subparsers.add_parser(
    "ensure-grant",
    help="Request authorization for a tool invocation"
)
ensure_grant_parser.add_argument("--agent-id", required=True, help="Agent identifier")
ensure_grant_parser.add_argument("--tool-name", required=True, help="Tool to authorize")
ensure_grant_parser.add_argument("--scopes", nargs="+", required=True, help="Required scopes")
ensure_grant_parser.add_argument("--user-id", help="User ID (optional)")
ensure_grant_parser.add_argument("--context", nargs="*", help="Context key=value pairs")
ensure_grant_parser.add_argument("--format", choices=["table", "json"], default="table")

# auth list-grants
list_grants_parser = auth_subparsers.add_parser(
    "list-grants",
    help="List grants for an agent"
)
list_grants_parser.add_argument("--agent-id", required=True, help="Agent identifier")
list_grants_parser.add_argument("--user-id", help="Filter by user ID")
list_grants_parser.add_argument("--tool-name", help="Filter by tool name")
list_grants_parser.add_argument("--include-expired", action="store_true", help="Include expired grants")
list_grants_parser.add_argument("--format", choices=["table", "json"], default="table")

# auth policy-preview
policy_preview_parser = auth_subparsers.add_parser(
    "policy-preview",
    help="Preview policy decision without creating a grant"
)
policy_preview_parser.add_argument("--agent-id", required=True, help="Agent identifier")
policy_preview_parser.add_argument("--tool-name", required=True, help="Tool to preview")
policy_preview_parser.add_argument("--scopes", nargs="+", required=True, help="Scopes to preview")
policy_preview_parser.add_argument("--user-id", help="User ID (optional)")
policy_preview_parser.add_argument("--context", nargs="*", help="Context key=value pairs")
policy_preview_parser.add_argument("--format", choices=["table", "json"], default="table")

# auth revoke
revoke_parser = auth_subparsers.add_parser(
    "revoke",
    help="Revoke an existing grant"
)
revoke_parser.add_argument("--grant-id", required=True, help="Grant ID to revoke")
revoke_parser.add_argument("--revoked-by", required=True, help="Who is revoking the grant")
revoke_parser.add_argument("--reason", help="Revocation reason")
revoke_parser.add_argument("--format", choices=["table", "json"], default="table")
'''

# =============================================================================
# Main() Dispatch Logic (add after metrics handling around line 2940)
# =============================================================================

MAIN_DISPATCH_CODE = '''
    elif args.command == "auth":
        if args.auth_command == "ensure-grant":
            return _command_auth_ensure_grant(args)
        elif args.auth_command == "list-grants":
            return _command_auth_list_grants(args)
        elif args.auth_command == "policy-preview":
            return _command_auth_policy_preview(args)
        elif args.auth_command == "revoke":
            return _command_auth_revoke(args)
'''
