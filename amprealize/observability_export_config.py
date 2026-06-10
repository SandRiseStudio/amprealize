"""Environment-driven configuration for optional OTLP / vendor telemetry export.

Following ``behavior_externalize_configuration`` (Student). Export is **off**
unless explicitly enabled so OSS installs stay lightweight.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(0.1, float(raw))
    except ValueError:
        return default


def parse_otlp_headers_raw(raw: Optional[str]) -> Dict[str, str]:
    """Parse ``AMPREALIZE_OTLP_HEADERS`` as JSON object or ``k=v,k2=v2``."""

    if not raw or not raw.strip():
        return {}
    stripped = raw.strip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items()}
        except json.JSONDecodeError:
            return {}
    out: Dict[str, str] = {}
    for part in stripped.split(","):
        part = part.strip()
        if "=" in part:
            key, _, val = part.partition("=")
            out[key.strip()] = val.strip()
    return out


def parse_otlp_protocol(raw: Optional[str]) -> str:
    """Return ``http`` or ``grpc`` from ``AMPREALIZE_OTLP_PROTOCOL``. Unknown values → ``http``."""

    if raw is None or not str(raw).strip():
        return "http"
    v = str(raw).strip().lower()
    if v == "grpc":
        return "grpc"
    return "http"


def normalize_otlp_grpc_endpoint(raw: Optional[str]) -> str:
    """Normalize OTLP gRPC endpoint to ``host:port`` (no scheme or URL path).

    Accepts ``localhost:4317``, ``http://127.0.0.1:4317``, or ``grpc://collector:4317``.
    If a URL omits the port, ``4317`` is used (OTLP gRPC default).
    """

    if not raw or not str(raw).strip():
        return ""
    s = str(raw).strip()
    if "://" in s:
        from urllib.parse import urlparse

        parsed = urlparse(s)
        host = parsed.hostname or "localhost"
        port = parsed.port if parsed.port is not None else 4317
        return f"{host}:{port}"
    base = s.split("/", 1)[0].strip()
    return base


@dataclass(frozen=True)
class ObservabilityExportConfig:
    """Resolved export toggles and endpoints."""

    enabled: bool
    otlp_endpoint: Optional[str]
    otlp_headers: Dict[str, str]
    otlp_service_name: str
    # OTLP transport: "http" (default) or "grpc"
    otlp_protocol: str
    # Plaintext gRPC when True (typical for local collectors); set False with TLS
    otlp_grpc_insecure: bool
    batch_max_events: int
    flush_interval_sec: float
    datadog_logs_intake_url: Optional[str]
    datadog_api_key: Optional[str]
    langfuse_host: Optional[str]
    langfuse_public_key: Optional[str]
    langfuse_secret_key: Optional[str]

    @classmethod
    def from_env(cls) -> "ObservabilityExportConfig":
        enabled = _truthy("AMPREALIZE_EXPORT_ENABLED", False)
        otlp_endpoint = os.environ.get("AMPREALIZE_OTLP_ENDPOINT", "").strip() or None
        headers = parse_otlp_headers_raw(os.environ.get("AMPREALIZE_OTLP_HEADERS"))
        service_name = os.environ.get("AMPREALIZE_OTLP_SERVICE_NAME", "amprealize").strip() or "amprealize"
        otlp_protocol = parse_otlp_protocol(os.environ.get("AMPREALIZE_OTLP_PROTOCOL"))
        otlp_grpc_insecure = _truthy("AMPREALIZE_OTLP_GRPC_INSECURE", True)
        batch_max = _int_env("AMPREALIZE_EXPORT_BATCH_MAX", 50)
        flush_interval = _float_env("AMPREALIZE_EXPORT_FLUSH_INTERVAL_SEC", 2.0)
        # Optional direct Datadog logs HTTP (bypasses OTLP); legacy intake URL + API key
        dd_url = os.environ.get("AMPREALIZE_EXPORT_DATADOG_LOGS_URL", "").strip() or None
        dd_key = os.environ.get("AMPREALIZE_DATADOG_API_KEY", "").strip() or None
        lf_host = os.environ.get("AMPREALIZE_LANGFUSE_HOST", "").strip().rstrip("/") or None
        lf_pub = os.environ.get("AMPREALIZE_LANGFUSE_PUBLIC_KEY", "").strip() or None
        lf_sec = os.environ.get("AMPREALIZE_LANGFUSE_SECRET_KEY", "").strip() or None

        return cls(
            enabled=enabled,
            otlp_endpoint=otlp_endpoint,
            otlp_headers=headers,
            otlp_service_name=service_name,
            otlp_protocol=otlp_protocol,
            otlp_grpc_insecure=otlp_grpc_insecure,
            batch_max_events=batch_max,
            flush_interval_sec=flush_interval,
            datadog_logs_intake_url=dd_url,
            datadog_api_key=dd_key,
            langfuse_host=lf_host,
            langfuse_public_key=lf_pub,
            langfuse_secret_key=lf_sec,
        )

    def has_otlp(self) -> bool:
        return bool(self.otlp_endpoint)

    def has_datadog_http(self) -> bool:
        return bool(self.datadog_logs_intake_url and self.datadog_api_key)

    def has_langfuse_http(self) -> bool:
        return bool(self.langfuse_host and self.langfuse_public_key and self.langfuse_secret_key)


def export_targets_summary(cfg: ObservabilityExportConfig) -> Dict[str, Any]:
    """Sanitized summary for logging (no secrets)."""

    return {
        "export_enabled": cfg.enabled,
        "otlp_configured": cfg.has_otlp(),
        "otlp_protocol": cfg.otlp_protocol if cfg.has_otlp() else None,
        "datadog_http_configured": cfg.has_datadog_http(),
        "langfuse_http_configured": cfg.has_langfuse_http(),
    }


__all__ = [
    "ObservabilityExportConfig",
    "export_targets_summary",
    "normalize_otlp_grpc_endpoint",
    "parse_otlp_headers_raw",
    "parse_otlp_protocol",
]
