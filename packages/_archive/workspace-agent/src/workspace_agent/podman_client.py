"""Podman socket client for container management.

This module provides a low-level client for communicating with podman
via its socket API, allowing container creation and management without
requiring the podman CLI to be installed.
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


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


# Global cached socket path
PODMAN_SOCKET_PATH = discover_podman_socket()


class PodmanSocketClient:
    """Client for communicating with podman via socket API.

    This allows services to create/manage containers without needing
    the podman CLI installed. The socket is typically mounted from
    the host system.

    Example:
        client = PodmanSocketClient()
        if client.is_available():
            container_id = client.create_container(
                name="workspace-123",
                image="python:3.11-slim",
            )
            output, exit_code = client.exec_run("workspace-123", "ls -la")
            client.remove_container("workspace-123")
    """

    def __init__(self, socket_uri: Optional[str] = None) -> None:
        """Initialize podman socket client.

        Args:
            socket_uri: Podman socket URI (e.g., unix:///run/podman/podman.sock)
                       If not provided, auto-discovery is used.
        """
        self._socket_uri = socket_uri or PODMAN_SOCKET_PATH
        self._client = None

    @property
    def socket_uri(self) -> str:
        """Get the socket URI."""
        return self._socket_uri

    def _get_client(self):
        """Get or create podman client (lazy initialization)."""
        if self._client is None:
            try:
                from podman import PodmanClient
                self._client = PodmanClient(base_url=self._socket_uri)
            except ImportError:
                logger.warning("podman package not installed")
                raise RuntimeError("podman package required: pip install podman")
        return self._client

    def is_available(self) -> bool:
        """Check if podman socket is available and responding.

        Returns:
            True if socket is available and podman responds
        """
        try:
            client = self._get_client()
            client.version()
            return True
        except Exception as e:
            logger.debug(f"Podman socket not available: {e}")
            return False

    def version(self) -> Dict[str, Any]:
        """Get podman version information.

        Returns:
            Version info dict with keys like 'Version', 'ApiVersion', etc.
        """
        client = self._get_client()
        return client.version()

    def create_container(
        self,
        name: str,
        image: str = "docker.io/library/python:3.11-slim",
        command: Optional[List[str]] = None,
        environment: Optional[Dict[str, str]] = None,
        labels: Optional[Dict[str, str]] = None,
        memory_limit: str = "2g",
        cpu_limit: float = 2.0,
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

        Returns:
            Container ID (short, 12 chars)

        Raises:
            RuntimeError: If container creation fails
        """
        client = self._get_client()

        # Pull image if not present
        try:
            client.images.get(image)
        except Exception:
            logger.info(f"Pulling image: {image}")
            client.images.pull(image)

        # Convert memory limit to bytes
        mem_bytes = self._parse_memory_limit(memory_limit)

        # Create container
        container = client.containers.create(
            name=name,
            image=image,
            command=command or ["sleep", "infinity"],
            environment=environment or {},
            labels=labels or {},
            mem_limit=mem_bytes,
            nano_cpus=int(cpu_limit * 1e9) if cpu_limit else None,
            detach=True,
        )

        # Start container
        container.start()

        # Return short ID
        container_id = container.id or container.name or name
        return container_id[:12] if container_id else name[:12]

    def _parse_memory_limit(self, limit: str) -> Optional[int]:
        """Parse memory limit string to bytes.

        Args:
            limit: Memory limit string (e.g., "2g", "512m", "1024k")

        Returns:
            Memory in bytes, or None if invalid
        """
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

    def exec_run(
        self,
        container_name: str,
        command: str,
        workdir: Optional[str] = None,
        timeout: int = 60,
    ) -> Tuple[str, int]:
        """Execute a shell command inside a container.

        Args:
            container_name: Container name or ID
            command: Shell command to execute
            workdir: Working directory inside container
            timeout: Command timeout in seconds (not enforced by podman API)

        Returns:
            Tuple of (output, exit_code)
        """
        client = self._get_client()
        container = client.containers.get(container_name)

        # Build exec command with shell
        exec_cmd = ["sh", "-c", command]

        try:
            # exec_run returns (exit_code, output_bytes) tuple
            result = container.exec_run(
                cmd=exec_cmd,
                workdir=workdir or "/",
            )

            # Handle tuple result: (exit_code, output_bytes)
            if isinstance(result, tuple) and len(result) >= 2:
                exit_code = result[0] or 0
                output_bytes = result[1]
            else:
                exit_code = 0
                output_bytes = result

            # Decode output
            output = self._decode_output(output_bytes)
            return output.strip(), int(exit_code)

        except Exception as e:
            logger.error(f"Exec failed in {container_name}: {e}")
            return str(e), 1

    def _decode_output(self, output_bytes: Any) -> str:
        """Decode exec output, handling multiplexed streams.

        Args:
            output_bytes: Raw output from exec_run

        Returns:
            Cleaned string output
        """
        if not output_bytes:
            return ""

        try:
            if isinstance(output_bytes, bytes):
                output = output_bytes.decode("utf-8", errors="replace")
            else:
                output = str(output_bytes)

            # Strip multiplexed stream headers (8-byte prefix per chunk)
            # The format is: 1 byte stream type, 3 bytes padding, 4 bytes size
            cleaned_lines = []
            for line in output.split('\n'):
                if line and ord(line[0]) <= 2:
                    # Strip first 8 bytes (header)
                    line = line[8:] if len(line) > 8 else ""
                cleaned_lines.append(line)
            return '\n'.join(cleaned_lines)

        except Exception:
            return str(output_bytes)

    def remove_container(self, container_name: str, force: bool = True) -> bool:
        """Remove a container.

        Args:
            container_name: Container name or ID
            force: Force removal (kill if running)

        Returns:
            True if removed successfully
        """
        try:
            client = self._get_client()
            container = client.containers.get(container_name)
            container.remove(force=force)
            return True
        except Exception as e:
            logger.warning(f"Failed to remove container {container_name}: {e}")
            return False

    def stop_container(self, container_name: str, timeout: int = 10) -> bool:
        """Stop a running container.

        Args:
            container_name: Container name or ID
            timeout: Seconds to wait before force killing

        Returns:
            True if stopped successfully
        """
        try:
            client = self._get_client()
            container = client.containers.get(container_name)
            container.stop(timeout=timeout)
            return True
        except Exception as e:
            logger.warning(f"Failed to stop container {container_name}: {e}")
            return False

    def get_container(self, container_name: str) -> Optional[Dict[str, Any]]:
        """Get container info.

        Args:
            container_name: Container name or ID

        Returns:
            Container info dict, or None if not found
        """
        try:
            client = self._get_client()
            container = client.containers.get(container_name)
            container_id = container.id or container.name or "unknown"
            return {
                "id": container_id[:12] if container_id else "unknown",
                "name": container.name or "unknown",
                "status": getattr(container, 'status', 'unknown'),
                "labels": container.labels or {},
            }
        except Exception:
            return None

    def list_containers(
        self,
        labels: Optional[Dict[str, str]] = None,
        all: bool = True,
    ) -> List[Dict[str, Any]]:
        """List containers with optional label filter.

        Args:
            labels: Labels to filter by (e.g., {"amprealize.type": "agent-workspace"})
            all: Include stopped containers

        Returns:
            List of container info dicts
        """
        client = self._get_client()

        filters = {}
        if labels:
            filters["label"] = [f"{k}={v}" for k, v in labels.items()]

        containers = client.containers.list(all=all, filters=filters)
        result = []
        for c in containers:
            container_id = c.id or c.name or "unknown"
            result.append({
                "id": container_id[:12] if container_id else "unknown",
                "name": c.name or "unknown",
                "status": getattr(c, 'status', 'unknown'),
                "labels": c.labels or {},
            })
        return result

    def container_exists(self, container_name: str) -> bool:
        """Check if a container exists.

        Args:
            container_name: Container name or ID

        Returns:
            True if container exists
        """
        return self.get_container(container_name) is not None
