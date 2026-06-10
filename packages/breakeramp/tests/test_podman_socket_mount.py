"""Tests for Podman socket host path discovery and BreakerAmp blueprint expansion."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from breakeramp.runtime.podman import discover_podman_socket_host_path_for_mount


def test_discover_podman_socket_host_path_prefers_podman_socket_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sock = tmp_path / "fake.sock"
    sock.write_bytes(b"")
    monkeypatch.delenv("PODMAN_HOST", raising=False)
    monkeypatch.setenv("PODMAN_SOCKET_PATH", f"unix://{sock}")
    assert discover_podman_socket_host_path_for_mount() == str(sock)


def test_discover_podman_socket_host_path_tcp_podman_host_uses_uid_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PODMAN_HOST", "tcp://127.0.0.1:8888")
    monkeypatch.delenv("PODMAN_SOCKET_PATH", raising=False)
    expected = f"/run/user/{os.getuid()}/podman/podman.sock"
    assert discover_podman_socket_host_path_for_mount() == expected


def test_discover_darwin_skips_mac_proxy_socket_from_machine_inspect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """macOS gvproxy API socket paths must not be bind-mounted into Podman VM containers."""
    bad_path = "/var/folders/xx/yyy/T/podman/amprealize-dev-api.sock"
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("PODMAN_SOCKET_PATH", raising=False)
    monkeypatch.delenv("PODMAN_HOST", raising=False)

    real_exists = os.path.exists

    def selective_exists(path: str | os.PathLike[str]) -> bool:
        sp = os.fspath(path)
        if sp == bad_path:
            return True
        return real_exists(path)

    monkeypatch.setattr(os.path, "exists", selective_exists)

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        r = MagicMock()
        r.returncode = 0
        if "info" in cmd and "{{.Host.CurrentMachine}}" in cmd:
            r.stdout = "amprealize-dev\n"
        elif "inspect" in cmd and "{{.ConnectionInfo.PodmanSocket.Path}}" in cmd:
            r.stdout = bad_path + "\n"
        else:
            r.stdout = ""
        return r

    monkeypatch.setattr(subprocess, "run", fake_run)

    expected = f"/run/user/{os.getuid()}/podman/podman.sock"
    assert discover_podman_socket_host_path_for_mount() == expected


def test_load_blueprint_injects_podman_sock_host_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AMPREALIZE_PODMAN_SOCK_HOST_PATH", raising=False)
    sock = tmp_path / "discovered.sock"
    sock.write_bytes(b"")

    from breakeramp import BreakerAmpService

    service = BreakerAmpService(executor=MagicMock(), base_dir=tmp_path)

    bp_path = tmp_path / "bp.yaml"
    bp_path.write_text(
        yaml.dump(
            {
                "name": "sock-test",
                "version": "1.0",
                "services": {
                    "podman-socket-proxy": {
                        "image": "alpine",
                        "volumes": [
                            "${AMPREALIZE_PODMAN_SOCK_HOST_PATH:-/run/user/501/podman/podman.sock}:/run/podman/podman.sock"
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "breakeramp.runtime.podman.discover_podman_socket_host_path_for_mount",
        lambda: str(sock),
    )

    bp = service._resolve_blueprint(str(bp_path), variables={})
    mount = bp.services["podman-socket-proxy"].volumes[0]
    assert mount == f"{sock}:/run/podman/podman.sock"
    assert os.environ["AMPREALIZE_PODMAN_SOCK_HOST_PATH"] == str(sock)
