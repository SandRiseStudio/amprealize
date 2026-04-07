"""Executors package for container runtime operations.

This package provides the Executor protocol and implementations for
different container runtimes.

Currently supported:
- PodmanExecutor: Runs containers via Podman CLI

Planned:
- DockerExecutor: Docker CLI/API support
"""

from breakeramp.executors.base import (
    ContainerInfo,
    ContainerRunConfig,
    Executor,
    ExecutorError,
    MachineCapableExecutor,
    MachineInfo,
    ResourceCapableExecutor,
    ResourceInfo,
    ResourceUsage,
)
from breakeramp.executors.podman import PodmanExecutor

__all__ = [
    # Base classes and protocols
    "Executor",
    "MachineCapableExecutor",
    "ResourceCapableExecutor",
    "ExecutorError",
    # Data classes
    "ContainerRunConfig",
    "ContainerInfo",
    "MachineInfo",
    "ResourceInfo",
    "ResourceUsage",
    # Implementations
    "PodmanExecutor",
]
