"""BreakerAmp runtime module for container orchestration.

This module provides the container runtime abstractions used by
the AmpOrchestrator for workspace management.

Modules:
    podman: Podman socket client for container lifecycle
    state: State store abstractions (InMemory, Redis)
"""

from breakeramp.runtime.podman import (
    PodmanClient,
    PodmanError,
    ContainerNotFoundError,
    discover_podman_socket,
)
from breakeramp.runtime.state import (
    StateStore,
    InMemoryStateStore,
    RedisStateStore,
    WorkspaceState,
)

__all__ = [
    # Podman
    "PodmanClient",
    "PodmanError",
    "ContainerNotFoundError",
    "discover_podman_socket",
    # State
    "StateStore",
    "InMemoryStateStore",
    "RedisStateStore",
    "WorkspaceState",
]
