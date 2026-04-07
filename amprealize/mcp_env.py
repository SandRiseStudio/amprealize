"""Helpers for loading Amprealize MCP runtime environment from local env files."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

DEFAULT_MCP_ENV_FILES = (".env", ".env.local", ".env.mcp")
_ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _split_env_file_list(raw: str) -> List[str]:
    normalized = raw.replace("\n", os.pathsep).replace(",", os.pathsep)
    return [part.strip() for part in normalized.split(os.pathsep) if part.strip()]


def _strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double:
            return value[:index].rstrip()
    return value.strip()


def _parse_env_assignment(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()
    if "=" not in stripped:
        return None

    key, value = stripped.split("=", 1)
    key = key.strip()
    if not _ENV_KEY_PATTERN.match(key):
        return None

    value = _strip_inline_comment(value.strip())
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def read_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_assignment(line)
        if parsed is None:
            continue
        key, value = parsed
        values[key] = value
    return values


def resolve_mcp_env_files(
    repo_root: Path,
    env: Mapping[str, str] | None = None,
) -> List[Path]:
    runtime_env = env or os.environ
    requested = runtime_env.get("AMPREALIZE_MCP_ENV_FILES") or runtime_env.get("AMPREALIZE_MCP_ENV_FILE")
    if requested:
        candidates: Iterable[str] = _split_env_file_list(requested)
    else:
        candidates = DEFAULT_MCP_ENV_FILES

    resolved: List[Path] = []
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if not path.is_absolute():
            path = repo_root / path
        resolved.append(path)
    return resolved


def merge_mcp_runtime_env(
    repo_root: Path,
    base_env: Mapping[str, str] | None = None,
) -> Dict[str, str]:
    merged = dict(base_env or os.environ)
    file_values: Dict[str, str] = {}
    for path in resolve_mcp_env_files(repo_root, merged):
        if path.exists():
            file_values.update(read_env_file(path))

    for key, value in file_values.items():
        merged.setdefault(key, value)

    merged.setdefault("PYTHONUNBUFFERED", "1")
    return merged


def collect_mcp_client_env(base_env: Mapping[str, str] | None = None) -> Dict[str, str]:
    runtime_env = base_env or os.environ
    client_env = {"PYTHONUNBUFFERED": runtime_env.get("PYTHONUNBUFFERED", "1")}
    for key in ("AMPREALIZE_MCP_ENV_FILE", "AMPREALIZE_MCP_ENV_FILES"):
        value = runtime_env.get(key)
        if value:
            client_env[key] = value
    return client_env
