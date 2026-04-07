"""Load, merge, and save ~/.amprealize/config.yaml with environment overrides.

Implements the config resolution order:
1. CLI flags (applied by callers after loading)
2. Environment variables (AMPREALIZE_ prefix)
3. Project config (.amprealize/config.yaml in project root)
4. User config (~/.amprealize/config.yaml)
5. Built-in defaults (from schema.py)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from amprealize.config.schema import AmprealizeConfig

__all__ = ["load_config", "save_config", "get_config", "resolve_config_paths"]

# Module-level singleton — lazily populated by get_config()
_config: Optional[AmprealizeConfig] = None

# Canonical paths
AMPREALIZE_HOME = Path(os.environ.get("AMPREALIZE_HOME", "~/.amprealize")).expanduser()
USER_CONFIG_PATH = AMPREALIZE_HOME / "config.yaml"
PROJECT_CONFIG_NAME = ".amprealize/config.yaml"


def resolve_config_paths() -> list[Path]:
    """Return ordered list of config files to merge (lowest → highest priority).

    Returns paths that exist on disk:
    1. User config (~/.amprealize/config.yaml)
    2. Project config (.amprealize/config.yaml in cwd or ancestors)
    """
    paths: list[Path] = []

    if USER_CONFIG_PATH.exists():
        paths.append(USER_CONFIG_PATH)

    # Walk up from cwd looking for .amprealize/config.yaml
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / PROJECT_CONFIG_NAME
        if candidate.exists() and candidate != USER_CONFIG_PATH:
            paths.append(candidate)
            break

    return paths


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge override into base. Override values win."""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _apply_env_overrides(data: Dict[str, Any]) -> Dict[str, Any]:
    """Apply AMPREALIZE_ environment variable overrides.

    Mapping: AMPREALIZE_STORAGE_BACKEND=sqlite → storage.backend = "sqlite"
    Double underscores navigate nested keys.
    """
    prefix = "AMPREALIZE_"
    env_overrides: Dict[str, str] = {}
    for key, value in os.environ.items():
        if key.startswith(prefix) and key != "AMPREALIZE_HOME":
            env_overrides[key] = value

    for env_key, env_value in env_overrides.items():
        # AMPREALIZE_STORAGE_BACKEND → ["storage", "backend"]
        parts = env_key[len(prefix):].lower().split("_")
        _set_nested(data, parts, env_value)

    return data


def _set_nested(data: Dict[str, Any], parts: list[str], value: str) -> None:
    """Set a nested dict value from a list of key segments.

    Handles ambiguity by trying the longest prefix match first.
    E.g. ["storage", "backend"] tries data["storage"]["backend"] first.
    """
    if not parts:
        return

    # Try exact single-key match first
    if len(parts) == 1:
        data[parts[0]] = _coerce_value(value)
        return

    # Try longest prefix that matches an existing dict key
    for i in range(1, len(parts) + 1):
        candidate = "_".join(parts[:i])
        if candidate in data and isinstance(data[candidate], dict) and i < len(parts):
            _set_nested(data[candidate], parts[i:], value)
            return

    # Fall back to first segment
    key = parts[0]
    if key not in data:
        data[key] = {}
    if isinstance(data[key], dict) and len(parts) > 1:
        _set_nested(data[key], parts[1:], value)
    else:
        data[key] = _coerce_value(value)


def _coerce_value(value: str) -> Any:
    """Coerce string env values to appropriate Python types."""
    lower = value.lower()
    if lower in ("true", "yes", "1"):
        return True
    if lower in ("false", "no", "0"):
        return False
    if lower == "null" or lower == "none":
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def load_config(extra_path: Optional[Path] = None) -> AmprealizeConfig:
    """Load and merge config from all sources.

    Args:
        extra_path: Optional additional config file to layer on top.

    Returns:
        Fully resolved AmprealizeConfig instance.
    """
    # Start with empty dict (defaults come from Pydantic model)
    merged: Dict[str, Any] = {}

    # Layer config files (lowest priority first)
    for path in resolve_config_paths():
        file_data = _load_yaml(path)
        if file_data:
            merged = _deep_merge(merged, file_data)

    # Layer extra path (e.g. from --config flag)
    if extra_path and extra_path.exists():
        file_data = _load_yaml(extra_path)
        if file_data:
            merged = _deep_merge(merged, file_data)

    # Apply environment variable overrides (highest file priority)
    merged = _apply_env_overrides(merged)

    return AmprealizeConfig(**merged)


def _load_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """Safely load a YAML file, returning None on error."""
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            return data
        return None
    except (OSError, yaml.YAMLError):
        return None


def save_config(config: AmprealizeConfig, path: Optional[Path] = None) -> Path:
    """Save config to YAML file.

    Args:
        config: Config to serialize.
        path: Target path. Defaults to ~/.amprealize/config.yaml.

    Returns:
        Path the config was written to.
    """
    target = path or USER_CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(exclude_defaults=False)
    with open(target, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    return target


def get_config() -> AmprealizeConfig:
    """Get the cached config singleton. Loads on first call."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config() -> None:
    """Reset the cached config (useful for testing)."""
    global _config
    _config = None


def set_config_value(key_path: str, value: str) -> AmprealizeConfig:
    """Set a single value in the user config file.

    Args:
        key_path: Dot-separated path, e.g. "storage.backend"
        value: String value (will be coerced to appropriate type)

    Returns:
        Updated config.
    """
    # Load current user config file (not merged — just the user file)
    user_data: Dict[str, Any] = {}
    if USER_CONFIG_PATH.exists():
        user_data = _load_yaml(USER_CONFIG_PATH) or {}

    # Set the value
    parts = key_path.split(".")
    current = user_data
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = _coerce_value(value)

    # Ensure version is set
    if "version" not in user_data:
        user_data["version"] = 1

    # Write back
    USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(USER_CONFIG_PATH, "w") as f:
        yaml.dump(user_data, f, default_flow_style=False, sort_keys=False)

    # Reload and return
    reset_config()
    return get_config()
