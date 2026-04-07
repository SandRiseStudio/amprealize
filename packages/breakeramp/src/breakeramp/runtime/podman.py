"""Podman client for container management in BreakerAmp.

This module provides a high-level async client for managing containers via
the Podman socket API. It's used by the AmpOrchestrator for provisioning
and managing agent execution workspaces.

Migrated from workspace-agent to consolidate container management in BreakerAmp.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class PodmanError(Exception):
    """Base exception for Podman operations."""
    pass


class ContainerNotFoundError(PodmanError):
    """Container was not found."""
    def __init__(self, container_name: str):
        self.container_name = container_name
        super().__init__(f"Container not found: {container_name}")


class ImagePullError(PodmanError):
    """Failed to pull container image."""
    def __init__(self, image: str, reason: str):
        self.image = image
        self.reason = reason
        super().__init__(f"Failed to pull image {image}: {reason}")


@dataclass
class ContainerInfo:
    """Information about a container."""
    id: str
    name: str
    status: str
    labels: Dict[str, str]
    created_at: Optional[str] = None

    @classmethod
    def from_container(cls, container: Any) -> "ContainerInfo":
        """Create from podman container object."""
        container_id = container.id or container.name or "unknown"
        return cls(
            id=container_id[:12] if container_id else "unknown",
            name=container.name or "unknown",
            status=getattr(container, 'status', 'unknown'),
            labels=container.labels or {},
            created_at=getattr(container, 'created', None),
        )


def discover_podman_socket() -> str:
    """Discover the podman socket path based on platform.

    Discovery order:
    1. PODMAN_HOST environment variable (supports tcp:// for remote)
    2. PODMAN_SOCKET_PATH environment variable (legacy, unix:// path)
    3. Podman machine socket (macOS/Windows via podman machine)
    4. Standard Linux socket paths

    Returns:
        Socket/connection URI (unix:// or tcp://)
    """
    # PODMAN_HOST is the standard env var for remote connections
    podman_host = os.environ.get("PODMAN_HOST")
    if podman_host:
        return podman_host

    # Legacy socket path override
    env_socket = os.environ.get("PODMAN_SOCKET_PATH")
    if env_socket:
        return env_socket

    # Try to get socket path from podman machine (macOS/Windows)
    try:
        # Get machine info to find the current machine name
        result = subprocess.run(
            ["podman", "machine", "info", "--format", "{{.Host.CurrentMachine}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            machine_name = result.stdout.strip()

            # Get socket path from this machine
            result = subprocess.run(
                ["podman", "machine", "inspect", machine_name,
                 "--format", "{{.ConnectionInfo.PodmanSocket.Path}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                socket_path = result.stdout.strip()
                if os.path.exists(socket_path):
                    return f"unix://{socket_path}"
    except Exception as e:
        logger.debug(f"Podman machine discovery failed: {e}")

    # Linux/container: Try standard socket paths
    standard_paths = [
        "/run/podman/podman.sock",  # Root
        f"/run/user/{os.getuid()}/podman/podman.sock",  # User
    ]

    for path in standard_paths:
        if os.path.exists(path):
            return f"unix://{path}"

    # Default fallback
    return "unix:///run/podman/podman.sock"


class PodmanClient:
    """Async-compatible client for Podman container operations.

    This client wraps the synchronous podman library with async-friendly
    execution and provides a clean interface for workspace management.

    Example:
        client = PodmanClient()
        if await client.is_available():
            container_id = await client.create_container(
                name="workspace-123",
                image="python:3.11-slim",
                labels={"amprealize.run_id": "123"},
            )
            output, exit_code = await client.exec_run("workspace-123", "ls -la")
            await client.remove_container("workspace-123")
    """

    def __init__(self, socket_uri: Optional[str] = None) -> None:
        """Initialize podman client.

        Args:
            socket_uri: Podman socket URI (e.g., unix:///run/podman/podman.sock)
                       If not provided, auto-discovery is used.
        """
        self._socket_uri = socket_uri or discover_podman_socket()
        self._client = None
        self._lock = asyncio.Lock()

    @property
    def socket_uri(self) -> str:
        """Get the socket URI."""
        return self._socket_uri

    def _get_sync_client(self):
        """Get or create synchronous podman client (lazy initialization)."""
        if self._client is None:
            try:
                from podman import PodmanClient as SyncPodmanClient
                self._client = SyncPodmanClient(base_url=self._socket_uri)
            except ImportError:
                logger.warning("podman package not installed")
                raise RuntimeError("podman package required: pip install podman")
        return self._client

    async def _run_sync(self, func, *args, **kwargs):
        """Run a synchronous function in an executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    async def is_available(self) -> bool:
        """Check if podman socket is available and responding.

        Returns:
            True if socket is available and podman responds
        """
        try:
            client = self._get_sync_client()
            await self._run_sync(client.version)
            return True
        except Exception as e:
            logger.debug(f"Podman socket not available: {e}")
            return False

    async def version(self) -> Dict[str, Any]:
        """Get podman version information.

        Returns:
            Version info dict with keys like 'Version', 'ApiVersion', etc.
        """
        client = self._get_sync_client()
        return await self._run_sync(client.version)

    async def create_container(
        self,
        name: str,
        image: str = "docker.io/library/python:3.11-slim",
        command: Optional[List[str]] = None,
        environment: Optional[Dict[str, str]] = None,
        labels: Optional[Dict[str, str]] = None,
        memory_limit: str = "2g",
        cpu_limit: float = 2.0,
        workdir: Optional[str] = None,
        volumes: Optional[Dict[str, str]] = None,
    ) -> str:
        """Create and start a new container.

        Args:
            name: Container name (must be unique)
            image: Container image to use
            command: Command to run (default: sleep infinity)
            environment: Environment variables
            labels: Container labels for filtering/tracking
            memory_limit: Memory limit (e.g., "2g", "512m")
            cpu_limit: CPU limit (e.g., 2.0 for 2 CPUs)
            workdir: Working directory inside container (must exist in image, or omit)
            volumes: Volume mounts (host_path: container_path)

        Returns:
            Container ID (short, 12 chars)

        Raises:
            PodmanError: If container creation fails
        """
        client = self._get_sync_client()

        def _create():
            # Pull image if not present
            try:
                client.images.get(image)
            except Exception:
                logger.info(f"Pulling image: {image}")
                try:
                    client.images.pull(image)
                except Exception as e:
                    raise ImagePullError(image, str(e))

            # Convert memory limit to bytes
            mem_bytes = self._parse_memory_limit(memory_limit)

            # Build volume mounts dict for podman-py
            # The podman library expects volumes as dict: {"container_path": {"bind": "host_path", "mode": "rw"}}
            volume_mounts = {}
            if volumes:
                for host_path, container_path in volumes.items():
                    volume_mounts[container_path] = {"bind": host_path, "mode": "rw"}

            # Build kwargs - only include working_dir if specified and exists in image
            create_kwargs = {
                "name": name,
                "image": image,
                "command": command or ["sleep", "infinity"],
                "environment": environment or {},
                "labels": labels or {},
                "mem_limit": mem_bytes,
                "nano_cpus": int(cpu_limit * 1e9) if cpu_limit else None,
                "detach": True,
                "volumes": volume_mounts if volume_mounts else {},
            }

            # Only set working_dir if explicitly provided (caller must ensure dir exists)
            if workdir:
                create_kwargs["working_dir"] = workdir

            # Create container
            container = client.containers.create(**create_kwargs)

            # Start container
            container.start()

            # Return short ID
            container_id = container.id or container.name or name
            return container_id[:12] if container_id else name[:12]

        return await self._run_sync(_create)

    def _parse_memory_limit(self, limit: str) -> Optional[int]:
        """Parse memory limit string to bytes."""
        if not limit:
            return None

        limit = limit.lower().strip()

        if limit.endswith("g"):
            return int(float(limit[:-1]) * 1024 * 1024 * 1024)
        elif limit.endswith("m"):
            return int(float(limit[:-1]) * 1024 * 1024)
        elif limit.endswith("k"):
            return int(float(limit[:-1]) * 1024)
        else:
            try:
                return int(limit)
            except ValueError:
                return None

    async def exec_run(
        self,
        container_name: str,
        command: str,
        workdir: Optional[str] = None,
        timeout: int = 60,
        environment: Optional[Dict[str, str]] = None,
    ) -> Tuple[str, int]:
        """Execute a shell command inside a container.

        Args:
            container_name: Container name or ID
            command: Shell command to execute
            workdir: Working directory inside container
            timeout: Command timeout in seconds
            environment: Additional environment variables

        Returns:
            Tuple of (output, exit_code)

        Raises:
            ContainerNotFoundError: If container doesn't exist
        """
        client = self._get_sync_client()

        def _exec():
            try:
                container = client.containers.get(container_name)
            except Exception:
                raise ContainerNotFoundError(container_name)

            # Build exec command with shell
            exec_cmd = ["sh", "-c", command]

            try:
                result = container.exec_run(
                    cmd=exec_cmd,
                    workdir=workdir or "/workspace",
                    environment=environment or {},
                )

                # Handle tuple result: (exit_code, output_bytes)
                if isinstance(result, tuple) and len(result) >= 2:
                    exit_code = result[0] or 0
                    output_bytes = result[1]
                else:
                    exit_code = 0
                    output_bytes = result

                output = self._decode_output(output_bytes)
                return output.strip(), int(exit_code)

            except Exception as e:
                logger.error(f"Exec failed in {container_name}: {e}")
                return str(e), 1

        return await self._run_sync(_exec)

    def _decode_output(self, output_bytes: Any) -> str:
        """Decode exec output, handling multiplexed streams."""
        if not output_bytes:
            return ""

        try:
            if isinstance(output_bytes, bytes):
                output = output_bytes.decode("utf-8", errors="replace")
            else:
                output = str(output_bytes)

            # Strip multiplexed stream headers (8-byte prefix per chunk)
            cleaned_lines = []
            for line in output.split('\n'):
                if line and ord(line[0]) <= 2:
                    line = line[8:] if len(line) > 8 else ""
                cleaned_lines.append(line)
            return '\n'.join(cleaned_lines)

        except Exception:
            return str(output_bytes)

    async def remove_container(
        self,
        container_name: str,
        force: bool = True,
        volumes: bool = False,
    ) -> bool:
        """Remove a container.

        Args:
            container_name: Container name or ID
            force: Force removal (kill if running)
            volumes: Also remove associated volumes

        Returns:
            True if removed successfully
        """
        client = self._get_sync_client()

        def _remove():
            try:
                container = client.containers.get(container_name)
                container.remove(force=force, v=volumes)
                return True
            except Exception as e:
                logger.warning(f"Failed to remove container {container_name}: {e}")
                return False

        return await self._run_sync(_remove)

    async def stop_container(
        self,
        container_name: str,
        timeout: int = 10,
    ) -> bool:
        """Stop a running container.

        Args:
            container_name: Container name or ID
            timeout: Seconds to wait before force killing

        Returns:
            True if stopped successfully
        """
        client = self._get_sync_client()

        def _stop():
            try:
                container = client.containers.get(container_name)
                container.stop(timeout=timeout)
                return True
            except Exception as e:
                logger.warning(f"Failed to stop container {container_name}: {e}")
                return False

        return await self._run_sync(_stop)

    async def get_container(self, container_name: str) -> Optional[ContainerInfo]:
        """Get container info.

        Args:
            container_name: Container name or ID

        Returns:
            ContainerInfo, or None if not found
        """
        client = self._get_sync_client()

        def _get():
            try:
                container = client.containers.get(container_name)
                return ContainerInfo.from_container(container)
            except Exception:
                return None

        return await self._run_sync(_get)

    async def list_containers(
        self,
        labels: Optional[Dict[str, str]] = None,
        all: bool = True,
    ) -> List[ContainerInfo]:
        """List containers with optional label filter.

        Args:
            labels: Labels to filter by
            all: Include stopped containers

        Returns:
            List of ContainerInfo
        """
        client = self._get_sync_client()

        def _list():
            filters = {}
            if labels:
                filters["label"] = [f"{k}={v}" for k, v in labels.items()]

            containers = client.containers.list(all=all, filters=filters)
            return [ContainerInfo.from_container(c) for c in containers]

        return await self._run_sync(_list)

    async def container_exists(self, container_name: str) -> bool:
        """Check if a container exists."""
        info = await self.get_container(container_name)
        return info is not None

    async def write_file(
        self,
        container_name: str,
        path: str,
        content: str,
        mode: str = "0644",
    ) -> bool:
        """Write content to a file inside a container.

        Args:
            container_name: Container name or ID
            path: File path inside container
            content: File content
            mode: File permissions (octal string)

        Returns:
            True if successful
        """
        # Escape content for shell
        escaped = content.replace("'", "'\"'\"'")
        command = f"mkdir -p $(dirname {path}) && echo '{escaped}' > {path} && chmod {mode} {path}"

        output, exit_code = await self.exec_run(container_name, command)
        if exit_code != 0:
            logger.error(f"Failed to write file {path}: {output}")
            return False
        return True

    async def read_file(
        self,
        container_name: str,
        path: str,
    ) -> Optional[str]:
        """Read content from a file inside a container.

        Args:
            container_name: Container name or ID
            path: File path inside container

        Returns:
            File content, or None if file doesn't exist
        """
        output, exit_code = await self.exec_run(container_name, f"cat {path}")
        if exit_code != 0:
            return None
        return output

    async def list_dir(
        self,
        container_name: str,
        path: str,
    ) -> List[str]:
        """List directory contents inside a container.

        Args:
            container_name: Container name or ID
            path: Directory path inside container

        Returns:
            List of file/directory names
        """
        output, exit_code = await self.exec_run(container_name, f"ls -1 {path}")
        if exit_code != 0:
            return []
        return [line for line in output.split('\n') if line.strip()]

    async def close(self) -> None:
        """Close the client connection."""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
