#!/bin/bash
# Get the podman socket path for the current machine (macOS/Windows)
# This is used to set PODMAN_SOCKET_HOST for the local-test-suite blueprint

set -e

# Try to get socket path from podman machine
if command -v podman &> /dev/null; then
    MACHINE_NAME=$(podman machine info --format "{{.Host.CurrentMachine}}" 2>/dev/null || echo "")

    if [ -n "$MACHINE_NAME" ]; then
        SOCKET_PATH=$(podman machine inspect "$MACHINE_NAME" --format "{{.ConnectionInfo.PodmanSocket.Path}}" 2>/dev/null || echo "")

        if [ -n "$SOCKET_PATH" ] && [ -e "$SOCKET_PATH" ]; then
            echo "$SOCKET_PATH"
            exit 0
        fi
    fi
fi

# Linux fallback paths
if [ -e "/run/podman/podman.sock" ]; then
    echo "/run/podman/podman.sock"
    exit 0
fi

if [ -e "/run/user/$(id -u)/podman/podman.sock" ]; then
    echo "/run/user/$(id -u)/podman/podman.sock"
    exit 0
fi

# No socket found
echo ""
exit 1
