"""Abstract executor interface for container runtime operations.

The Executor protocol defines the contract for container runtime implementations,
allowing BreakerAmp to support different container engines (Podman, Docker, etc.)
through a unified interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@dataclass
class ContainerRunConfig:
    """Configuration for running a container.

    Attributes:
        image: Container image name (e.g., "postgres:16-alpine")
        name: Container name for identification
        ports: Port mappings in "host:container" format
        environment: Environment variables
        volumes: Volume/bind mount specifications
        command: Optional command to run
        workdir: Optional working directory inside container
        detach: Whether to run in detached mode (default True)
        network: Optional network name to attach container to
        network_aliases: Optional list of DNS aliases for the container on the network
        privileged: Whether to run container in privileged mode (default False)
        extra_hosts: Extra /etc/hosts entries (e.g., "host.containers.internal:host-gateway")
    """
    image: str
    name: str
    ports: List[str] = field(default_factory=list)
    environment: Dict[str, str] = field(default_factory=dict)
    volumes: List[str] = field(default_factory=list)
    command: Optional[List[str]] = None
    workdir: Optional[str] = None
    detach: bool = True
    network: Optional[str] = None
    network_aliases: List[str] = field(default_factory=list)
    privileged: bool = False
    extra_hosts: List[str] = field(default_factory=list)


@dataclass
class ContainerInfo:
    """Information about a running container.

    Attributes:
        container_id: The container's unique identifier
        name: The container's name
        status: Current status (e.g., "running", "stopped", "exited")
        image: The image the container was created from
        created: ISO timestamp of creation
        ports: Port mappings
    """
    container_id: str
    name: str
    status: str
    image: str
    created: Optional[str] = None
    ports: Dict[str, str] = field(default_factory=dict)


@dataclass
class MachineInfo:
    """Information about a container machine/VM (for Podman machine, etc.).

    Attributes:
        name: Machine name
        running: Whether the machine is running
        cpus: Number of CPUs allocated
        memory_mb: Memory allocated in MB
        disk_gb: Disk space allocated in GB
    """
    name: str
    running: bool
    cpus: Optional[int] = None
    memory_mb: Optional[int] = None
    disk_gb: Optional[int] = None


@dataclass
class ResourceUsage:
    """Resource usage metrics for a single resource type.

    Attributes:
        total: Total capacity
        used: Amount currently used
        available: Amount available
        percent_used: Percentage used (0-100)
        unit: Unit of measurement (e.g., "MB", "GB", "cores")
    """
    total: float
    used: float
    available: float
    percent_used: float
    unit: str

    @property
    def is_critical(self) -> bool:
        """Returns True if usage is at critical level (>90%)."""
        return self.percent_used > 90

    @property
    def is_warning(self) -> bool:
        """Returns True if usage is at warning level (>75%)."""
        return self.percent_used > 75


@dataclass
class ResourceInfo:
    """Comprehensive resource information for host or machine.

    Attributes:
        source: Where these resources are from ("host", "machine:name", etc.)
        disk: Disk space usage
        memory: Memory usage
        cpu: CPU usage/allocation
        timestamp: When these metrics were collected (ISO format)
        healthy: Overall health status
        warnings: List of warning messages
    """
    source: str
    disk: Optional[ResourceUsage] = None
    memory: Optional[ResourceUsage] = None
    cpu: Optional[ResourceUsage] = None
    timestamp: Optional[str] = None
    healthy: bool = True
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: Dict[str, Any] = {
            "source": self.source,
            "healthy": self.healthy,
            "timestamp": self.timestamp,
        }
        if self.disk:
            result["disk"] = {
                "total": self.disk.total,
                "used": self.disk.used,
                "available": self.disk.available,
                "percent_used": self.disk.percent_used,
                "unit": self.disk.unit,
                "is_critical": self.disk.is_critical,
                "is_warning": self.disk.is_warning,
            }
        if self.memory:
            result["memory"] = {
                "total": self.memory.total,
                "used": self.memory.used,
                "available": self.memory.available,
                "percent_used": self.memory.percent_used,
                "unit": self.memory.unit,
                "is_critical": self.memory.is_critical,
                "is_warning": self.memory.is_warning,
            }
        if self.cpu:
            result["cpu"] = {
                "total": self.cpu.total,
                "used": self.cpu.used,
                "available": self.cpu.available,
                "percent_used": self.cpu.percent_used,
                "unit": self.cpu.unit,
            }
        if self.warnings:
            result["warnings"] = self.warnings
        return result


@runtime_checkable
class Executor(Protocol):
    """Protocol defining the container executor interface.

    Implementations must provide methods for:
    - Running and managing containers
    - Executing commands in containers
    - Retrieving logs
    - Managing container machines (where applicable)

    Example implementation:
        class PodmanExecutor:
            def run_container(self, config: ContainerRunConfig) -> str:
                # Run via `podman run`
                ...
                return container_id
    """

    def run_container(self, config: ContainerRunConfig) -> str:
        """Create and start a container.

        Args:
            config: Container configuration

        Returns:
            Container ID of the created container

        Raises:
            ExecutorError: If container creation fails
        """
        ...

    def stop_container(self, container_id: str, timeout: int = 10) -> None:
        """Stop a running container.

        Args:
            container_id: Container ID or name
            timeout: Seconds to wait before killing

        Raises:
            ExecutorError: If stop fails (not raised if container already stopped)
        """
        ...

    def remove_container(self, container_id: str, force: bool = False) -> None:
        """Remove a container.

        Args:
            container_id: Container ID or name
            force: Force removal even if running

        Raises:
            ExecutorError: If removal fails (not raised if container doesn't exist)
        """
        ...

    def inspect_container(self, container_id: str) -> ContainerInfo:
        """Get detailed information about a container.

        Args:
            container_id: Container ID or name

        Returns:
            Container information

        Raises:
            ExecutorError: If container doesn't exist
        """
        ...

    def exec_in_container(
        self,
        container_id: str,
        command: List[str],
        workdir: Optional[str] = None
    ) -> str:
        """Execute a command inside a running container.

        Args:
            container_id: Container ID or name
            command: Command and arguments to run
            workdir: Working directory inside container

        Returns:
            Command output (stdout)

        Raises:
            ExecutorError: If execution fails
        """
        ...

    def get_logs(
        self,
        container_id: str,
        tail: Optional[int] = None,
        since: Optional[str] = None
    ) -> str:
        """Retrieve container logs.

        Args:
            container_id: Container ID or name
            tail: Number of lines from end (None for all)
            since: Timestamp to start from (ISO format)

        Returns:
            Log output
        """
        ...

    def get_container_status(self, container_id: str) -> str:
        """Get the current status of a container.

        Args:
            container_id: Container ID or name

        Returns:
            Status string (e.g., "running", "stopped", "exited")
        """
        ...


@runtime_checkable
class MachineCapableExecutor(Executor, Protocol):
    """Extended executor protocol for runtimes with machine management.

    This extends the base Executor with methods for managing container
    machines/VMs, which is needed for Podman on macOS/Windows.
    """

    def list_machines(self) -> List[MachineInfo]:
        """List all container machines.

        Returns:
            List of machine information
        """
        ...

    def get_machine(self, name: str) -> Optional[MachineInfo]:
        """Get information about a specific machine.

        Args:
            name: Machine name

        Returns:
            Machine info or None if not found
        """
        ...

    def start_machine(self, name: str) -> None:
        """Start a container machine.

        Args:
            name: Machine name

        Raises:
            ExecutorError: If start fails
        """
        ...

    def stop_machine(self, name: str) -> None:
        """Stop a container machine.

        Args:
            name: Machine name

        Raises:
            ExecutorError: If stop fails
        """
        ...

    def init_machine(
        self,
        name: str,
        cpus: Optional[int] = None,
        memory_mb: Optional[int] = None,
        disk_gb: Optional[int] = None
    ) -> None:
        """Initialize a new container machine.

        Args:
            name: Machine name
            cpus: Number of CPUs to allocate
            memory_mb: Memory to allocate in MB
            disk_gb: Disk space to allocate in GB

        Raises:
            ExecutorError: If initialization fails
        """
        ...

    def inspect_machine(self, name: str) -> Dict[str, Any]:
        """Get detailed machine configuration.

        Args:
            name: Machine name

        Returns:
            Machine configuration dictionary
        """
        ...


@runtime_checkable
class ResourceCapableExecutor(MachineCapableExecutor, Protocol):
    """Extended executor protocol with resource monitoring capabilities.

    This extends MachineCapableExecutor with methods for monitoring
    resource usage on both the host and container machines/VMs.
    """

    def get_host_resources(self) -> ResourceInfo:
        """Get resource usage for the host machine.

        Returns:
            ResourceInfo with disk, memory, and CPU usage for the host
        """
        ...

    def get_machine_resources(self, name: str) -> ResourceInfo:
        """Get resource usage inside a container machine/VM.

        Args:
            name: Machine name

        Returns:
            ResourceInfo with disk, memory, and CPU usage inside the machine
        """
        ...

    def get_all_resources(self) -> List[ResourceInfo]:
        """Get resource usage for host and all running machines.

        Returns:
            List of ResourceInfo for host and each running machine
        """
        ...

    def check_resource_health(
        self,
        min_disk_gb: float = 5.0,
        min_memory_mb: float = 1024.0,
    ) -> tuple[bool, List[str]]:
        """Check if resources meet minimum requirements.

        Args:
            min_disk_gb: Minimum free disk space in GB
            min_memory_mb: Minimum free memory in MB

        Returns:
            Tuple of (healthy: bool, warnings: List[str])
        """
        ...

    def mitigate_resources(
        self,
        dry_run: bool = False,
        prune_containers: bool = True,
        prune_images: bool = True,
        prune_volumes: bool = False,
        prune_cache: bool = True,
        prune_networks: bool = False,
        prune_pods: bool = False,
        aggressive: bool = False,
    ) -> "CleanupResult":
        """Attempt to free up resources by cleaning unused items.

        This is a SAFE cleanup operation that only removes:
        - Stopped/exited containers (not running ones)
        - Dangling/unused images (not images used by running containers)
        - Build cache
        - Optionally: unused volumes (off by default as may contain data)
        - Optionally: unused networks
        - Optionally: stopped pods

        The `aggressive` flag enables deeper cleanup:
        - Removes ALL unused images (not just dangling)
        - Clears ALL build cache (not just >24h old)
        - Truncates container logs

        Args:
            dry_run: If True, only report what would be cleaned without doing it
            prune_containers: Remove stopped containers
            prune_images: Remove dangling images
            prune_volumes: Remove unused volumes (USE WITH CAUTION)
            prune_cache: Clear build cache
            prune_networks: Remove unused networks
            prune_pods: Remove stopped pods
            aggressive: Enable aggressive cleanup mode

        Returns:
            CleanupResult with details of what was (or would be) removed
        """
        ...


@dataclass
class ResourceHealthResult:
    """Detailed result of a resource health check.

    Attributes:
        healthy: Overall health status
        warnings: All warning messages
        host_healthy: Whether host resources are healthy
        host_warnings: Warnings specific to host resources
        vm_healthy: Whether VM resources are healthy (True if no VMs)
        vm_warnings: Warnings specific to VM resources
        host_disk_available_gb: Available host disk space in GB
        host_memory_available_mb: Available host memory in MB
    """
    healthy: bool = True
    warnings: List[str] = field(default_factory=list)
    host_healthy: bool = True
    host_warnings: List[str] = field(default_factory=list)
    vm_healthy: bool = True
    vm_warnings: List[str] = field(default_factory=list)
    host_disk_available_gb: float = 0.0
    host_memory_available_mb: float = 0.0

    @property
    def only_host_unhealthy(self) -> bool:
        """Returns True if only host resources are unhealthy (VMs are fine)."""
        return not self.host_healthy and self.vm_healthy

    @property
    def only_vm_unhealthy(self) -> bool:
        """Returns True if only VM resources are unhealthy (host is fine)."""
        return self.host_healthy and not self.vm_healthy


@dataclass
class CleanupResult:
    """Result of a resource cleanup/mitigation operation.

    Attributes:
        source: Where cleanup was performed ("host", "vm", "all")
        dry_run: Whether this was a dry run (no actual changes)
        containers_removed: Number of containers removed
        images_removed: Number of images removed
        volumes_removed: Number of volumes removed
        networks_removed: Number of networks removed
        pods_removed: Number of pods removed
        cache_cleared: Whether build cache was cleared
        logs_truncated: Number of container logs truncated
        space_reclaimed_mb: Estimated space reclaimed in MB
        host_space_reclaimed_mb: Space reclaimed on host specifically
        errors: List of errors encountered during cleanup
        details: Detailed breakdown of what was cleaned
    """
    source: str = "vm"  # "host", "vm", or "all"
    dry_run: bool = False
    containers_removed: int = 0
    images_removed: int = 0
    volumes_removed: int = 0
    networks_removed: int = 0
    pods_removed: int = 0
    cache_cleared: bool = False
    logs_truncated: int = 0
    space_reclaimed_mb: float = 0.0
    host_space_reclaimed_mb: float = 0.0
    errors: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Returns True if cleanup completed without errors."""
        return len(self.errors) == 0

    @property
    def items_cleaned(self) -> int:
        """Total number of items cleaned."""
        return (
            self.containers_removed +
            self.images_removed +
            self.volumes_removed +
            self.networks_removed +
            self.pods_removed +
            self.logs_truncated +
            (1 if self.cache_cleared else 0)
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "source": self.source,
            "dry_run": self.dry_run,
            "success": self.success,
            "containers_removed": self.containers_removed,
            "images_removed": self.images_removed,
            "volumes_removed": self.volumes_removed,
            "networks_removed": self.networks_removed,
            "pods_removed": self.pods_removed,
            "cache_cleared": self.cache_cleared,
            "logs_truncated": self.logs_truncated,
            "space_reclaimed_mb": self.space_reclaimed_mb,
            "host_space_reclaimed_mb": self.host_space_reclaimed_mb,
            "items_cleaned": self.items_cleaned,
            "errors": self.errors,
            "details": self.details,
        }


class ExecutorError(Exception):
    """Exception raised when executor operations fail.

    Attributes:
        message: Error description
        command: The command that failed (if applicable)
        stdout: Standard output (if available)
        stderr: Standard error output (if available)
        returncode: Process return code (if applicable)
    """

    def __init__(
        self,
        message: str,
        command: Optional[List[str]] = None,
        stdout: Optional[str] = None,
        stderr: Optional[str] = None,
        returncode: Optional[int] = None
    ):
        super().__init__(message)
        self.message = message
        self.command = command
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode

    def __str__(self) -> str:
        parts = [self.message]
        if self.command:
            parts.append(f"Command: {' '.join(self.command)}")
        if self.stdout:
            parts.append(f"Stdout: {self.stdout}")
        if self.stderr:
            parts.append(f"Stderr: {self.stderr}")
        if self.returncode is not None:
            parts.append(f"Return code: {self.returncode}")
        return " | ".join(parts)
