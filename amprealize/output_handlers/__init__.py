"""Output Handlers — Pluggable delivery for agent execution results.

Provides a unified OutputHandler protocol and concrete implementations
for delivering agent file changes to various targets:

- GitHubPRHandler: Commit changes and create a GitHub pull request
- GitLabMRHandler: Commit changes and create a GitLab merge request
- PatchFileHandler: Generate a downloadable .patch file
- LocalSyncHandler: Write changes directly to local filesystem

Part of E3 — Agent Execution Loop Rearchitecture (Phase 4 / S3.8).
"""

from .base import (
    OutputContext,
    OutputHandler,
    OutputResult,
    OutputStatus,
)
from .github_pr import GitHubPRHandler
from .gitlab_mr import GitLabMRHandler
from .local_sync import LocalSyncHandler
from .patch_file import PatchFileHandler

__all__ = [
    # Protocol + types
    "OutputContext",
    "OutputHandler",
    "OutputResult",
    "OutputStatus",
    # Implementations
    "GitHubPRHandler",
    "GitLabMRHandler",
    "LocalSyncHandler",
    "PatchFileHandler",
]


# ---------------------------------------------------------------------------
# Handler registry — maps OutputTarget enum values to handler classes
# ---------------------------------------------------------------------------

_HANDLER_REGISTRY: dict[str, type[OutputHandler]] = {
    "pull_request": GitHubPRHandler,
    "patch_file": PatchFileHandler,
    "local_sync": LocalSyncHandler,
    # "archive" could be added later
}


def get_handler_class(output_target: str) -> type[OutputHandler] | None:
    """Look up the handler class for an OutputTarget value."""
    return _HANDLER_REGISTRY.get(output_target)
