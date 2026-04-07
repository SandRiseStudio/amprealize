"""CLI entry point for workspace-agent.

Note: gRPC server removed in favor of AmpOrchestrator (2026-01-16).
Workspace management is now handled directly via breakeramp.runtime.
"""

import sys


def main() -> None:
    """Main CLI entry point."""
    print("workspace-agent: Workspace management library")
    print("")
    print("This package is now used as a library, not a standalone service.")
    print("Workspace management is handled by AmpOrchestrator in the breakeramp package.")
    print("")
    print("For workspace operations, use:")
    print("  from breakeramp.orchestrator import AmpOrchestrator")
    print("  orchestrator = AmpOrchestrator(...)")
    print("  await orchestrator.provision_workspace(run_id, config)")
    print("")
    print("For container deployments, use:")
    print("  breakeramp plan --blueprint local-test-suite")
    print("  breakeramp apply --blueprint local-test-suite")
    print("")
    sys.exit(0)


if __name__ == "__main__":
    main()
