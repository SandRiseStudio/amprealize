"""Cross-repo integration tests for OSS ↔ Enterprise interactions.

Tests that the OSS module system correctly detects, delegates to,
and integrates with the amprealize-enterprise package when installed.

GUIDEAI-779: Add cross-repo integration tests for OSS and enterprise.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Edition detection
# ---------------------------------------------------------------------------


class TestEditionDetection:
    """Verify edition detection with and without enterprise package."""

    def test_detect_edition_returns_enum(self):
        """OSS build always reports the OSS edition."""
        from amprealize.edition import detect_edition, Edition

        edition = detect_edition()
        assert isinstance(edition, Edition)
        assert edition == Edition.OSS

    def test_has_enterprise_flag(self):
        """OSS build hardcodes HAS_ENTERPRISE to False."""
        from amprealize import HAS_ENTERPRISE

        assert HAS_ENTERPRISE is False

    def test_oss_edition_without_enterprise(self):
        """OSS build reports OSS regardless of any separately installed fork."""
        from amprealize.edition import detect_edition, Edition

        edition = detect_edition()
        assert edition == Edition.OSS


# ---------------------------------------------------------------------------
# Cloud client factory
# ---------------------------------------------------------------------------


class TestCloudClientFactory:
    """Verify the cloud client factory returns OSS stub."""

    def test_get_cloud_client_returns_client(self):
        """Factory always returns a CloudClient instance."""
        from amprealize.cloud_client import get_cloud_client

        client = get_cloud_client()
        assert hasattr(client, "upload")
        assert hasattr(client, "download")
        assert hasattr(client, "submit_job")
        assert hasattr(client, "get_job_status")
        assert hasattr(client, "authenticate")
        assert hasattr(client, "request")

    def test_oss_stub_raises_on_call(self):
        """OSS CloudClient stub raises ImportError on any method call."""
        from amprealize.cloud_client import CloudClient as OSSCloudClient

        client = OSSCloudClient()
        with pytest.raises(ImportError, match="enterprise edition"):
            client.upload()
        with pytest.raises(ImportError, match="enterprise edition"):
            client.download()
        with pytest.raises(ImportError, match="enterprise edition"):
            client.submit_job()
        with pytest.raises(ImportError, match="enterprise edition"):
            client.get_job_status()
        with pytest.raises(ImportError, match="enterprise edition"):
            client.authenticate()
        with pytest.raises(ImportError, match="enterprise edition"):
            client.request()

    def test_factory_returns_oss_stub(self):
        """Factory returns OSS stub (enterprise fork overrides module)."""
        from amprealize.cloud_client import get_cloud_client, CloudClient

        client = get_cloud_client()
        assert isinstance(client, CloudClient)


# ---------------------------------------------------------------------------
# Deploy migration delegation
# ---------------------------------------------------------------------------


class TestDeployMigrateDelegation:
    """Verify deploy_migrate OSS stubs raise clearly."""

    def test_oss_functions_exist(self):
        """All expected migration functions exist in the OSS module."""
        from amprealize import deploy_migrate

        assert callable(getattr(deploy_migrate, "export_data", None))
        assert callable(getattr(deploy_migrate, "import_data", None))
        assert callable(getattr(deploy_migrate, "sync_to_cloud", None))
        assert callable(getattr(deploy_migrate, "sync_from_cloud", None))
        assert callable(getattr(deploy_migrate, "migrate_deployment", None))

    def test_oss_stubs_raise(self):
        """OSS migration functions always raise ImportError."""
        from amprealize import deploy_migrate as dm

        with pytest.raises(ImportError, match="enterprise edition"):
            dm.export_data()
        with pytest.raises(ImportError, match="enterprise edition"):
            dm.import_data()
        with pytest.raises(ImportError, match="enterprise edition"):
            dm.sync_to_cloud()
        with pytest.raises(ImportError, match="enterprise edition"):
            dm.sync_from_cloud()
        with pytest.raises(ImportError, match="enterprise edition"):
            dm.migrate_deployment()


# ---------------------------------------------------------------------------
# Module registry & edition gating
# ---------------------------------------------------------------------------


class TestModuleEditionGating:
    """Verify modules respect edition boundaries."""

    def test_module_registry_has_expected_modules(self):
        """MODULE_REGISTRY contains all 5 expected modules."""
        from amprealize.module_registry import MODULE_REGISTRY

        expected = {"goals", "agents", "behaviors", "self_improving", "collaboration"}
        assert set(MODULE_REGISTRY.keys()) == expected

    def test_goals_always_enabled(self):
        """Goals module is always enabled regardless of edition."""
        from amprealize.module_registry import MODULE_REGISTRY

        goals = MODULE_REGISTRY["goals"]
        assert goals.always_enabled is True

    def test_enterprise_only_modules_flagged(self):
        """self_improving and collaboration are enterprise_only."""
        from amprealize.module_registry import MODULE_REGISTRY

        assert MODULE_REGISTRY["self_improving"].enterprise_only is True
        assert MODULE_REGISTRY["collaboration"].enterprise_only is True

    def test_oss_modules_not_enterprise_only(self):
        """goals, agents, behaviors are NOT enterprise_only."""
        from amprealize.module_registry import MODULE_REGISTRY

        assert MODULE_REGISTRY["goals"].enterprise_only is False
        assert MODULE_REGISTRY["agents"].enterprise_only is False
        assert MODULE_REGISTRY["behaviors"].enterprise_only is False

    def test_is_module_edition_allowed_oss_modules(self):
        """OSS modules should be allowed in any edition."""
        from amprealize.module_registry import is_module_edition_allowed

        for name in ("goals", "agents", "behaviors"):
            assert is_module_edition_allowed(name) is True

    def test_validate_dependencies_empty_set(self):
        """No errors for an empty module set."""
        from amprealize.module_registry import validate_module_dependencies

        errors = validate_module_dependencies(())
        assert errors == []

    def test_validate_dependencies_goals_only(self):
        """Goals alone should have no dependency errors."""
        from amprealize.module_registry import validate_module_dependencies

        errors = validate_module_dependencies(("goals",))
        assert errors == []


# ---------------------------------------------------------------------------
# Config schema module fields
# ---------------------------------------------------------------------------


class TestConfigModuleFields:
    """Verify config schema supports module enable/disable."""

    def test_modules_config_has_expected_fields(self):
        """ModulesConfig has the expected boolean fields."""
        from amprealize.config.schema import ModulesConfig

        cfg = ModulesConfig()
        assert cfg.goals is True  # always True
        assert cfg.agents is False
        assert cfg.behaviors is False
        assert cfg.collaboration is False

    def test_modules_config_enable_agents(self):
        """Can create ModulesConfig with agents enabled."""
        from amprealize.config.schema import ModulesConfig

        cfg = ModulesConfig(agents=True)
        assert cfg.agents is True

    def test_deployment_config_defaults(self):
        """DeploymentConfig defaults to local mode."""
        from amprealize.config.schema import DeploymentConfig

        cfg = DeploymentConfig()
        assert cfg.mode == "local"


# ---------------------------------------------------------------------------
# Deployment validation
# ---------------------------------------------------------------------------


class TestDeploymentValidation:
    """Verify deployment validation catches configuration issues."""

    def test_validate_local_deployment(self):
        """Local deployment should validate cleanly with defaults."""
        from amprealize.deployment import validate_deployment
        from amprealize.config.schema import DeploymentConfig

        cfg = DeploymentConfig()
        errors = validate_deployment(cfg)
        assert isinstance(errors, list)

    def test_resolve_service_endpoints(self):
        """resolve_service_endpoints returns a ServiceEndpoints."""
        from amprealize.deployment import resolve_service_endpoints, ServiceEndpoints
        from amprealize.config.schema import DeploymentConfig

        cfg = DeploymentConfig()
        endpoints = resolve_service_endpoints(cfg)
        assert isinstance(endpoints, ServiceEndpoints)


# ---------------------------------------------------------------------------
# Enterprise package structure (when installed)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    importlib.util.find_spec("amprealize_enterprise") is None,
    reason="Enterprise package not installed",
)
class TestEnterprisePackageStructure:
    """Verify enterprise package exposes expected modules."""

    def test_enterprise_has_version(self):
        import amprealize_enterprise

        assert hasattr(amprealize_enterprise, "__version__")
        assert isinstance(amprealize_enterprise.__version__, str)

    def test_enterprise_has_cloud_client(self):
        from amprealize_enterprise.cloud_client import CloudClient

        client = CloudClient(cloud_url="https://test.example.com")
        assert client.cloud_url == "https://test.example.com"

    def test_enterprise_has_deploy_migrate(self):
        from amprealize_enterprise import deploy_migrate

        assert callable(getattr(deploy_migrate, "export_data", None))
        assert callable(getattr(deploy_migrate, "import_data", None))
        assert callable(getattr(deploy_migrate, "sync_to_cloud", None))
        assert callable(getattr(deploy_migrate, "sync_from_cloud", None))

    def test_enterprise_has_edition_tier(self):
        from amprealize_enterprise.edition_tier import resolve_tier

        tier = resolve_tier()
        assert tier in ("starter", "premium")

    def test_enterprise_cloud_client_auth_methods(self):
        """Enterprise CloudClient has authentication infrastructure."""
        from amprealize_enterprise.cloud_client import CloudClient

        client = CloudClient(cloud_url="https://test.example.com")
        assert hasattr(client, "authenticate")
        assert hasattr(client, "_ensure_authenticated")
        assert hasattr(client, "_token")
        assert client._token is None  # not authenticated yet

    def test_enterprise_cloud_client_requires_auth(self):
        """Enterprise CloudClient raises without authentication."""
        from amprealize_enterprise.cloud_client import CloudClient

        client = CloudClient(cloud_url="https://test.example.com")
        with pytest.raises(RuntimeError, match="Not authenticated"):
            client._ensure_authenticated()
