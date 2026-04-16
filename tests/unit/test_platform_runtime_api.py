from __future__ import annotations

import os

import pytest

os.environ.setdefault("AMPREALIZE_EXECUTION_ENABLED", "false")

from amprealize.edition import Edition
from amprealize.platform_runtime import build_platform_runtime_dict

pytestmark = pytest.mark.unit


def test_build_platform_runtime_strips_pg_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "amprealize.platform_runtime.get_context_name",
        lambda: "neon:pg",
    )
    monkeypatch.setattr(
        "amprealize.platform_runtime.detect_edition",
        lambda: Edition.OSS,
    )
    payload = build_platform_runtime_dict()
    assert payload["context_name"] == "neon"
    assert payload["distribution"] == "oss"
    assert payload["edition"] is None


def test_build_platform_runtime_enterprise_edition(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "amprealize.platform_runtime.get_context_name",
        lambda: "local-postgres",
    )
    monkeypatch.setattr(
        "amprealize.platform_runtime.detect_edition",
        lambda: Edition.ENTERPRISE_PREMIUM,
    )
    payload = build_platform_runtime_dict()
    assert payload["distribution"] == "enterprise"
    assert payload["edition"] == "premium"
    assert payload["context_name"] == "local-postgres"
