"""Tests for the modular installation system — GUIDEAI-619 / GUIDEAI-748.

Covers:
- Config models (ModulesConfig, DeploymentConfig, DeploymentServicesConfig)
- Module registry (definitions, presets, helpers, dependency validation)
- Edition resolver (detect_edition, get_caps, EditionCapabilities)
- Deployment resolver (resolve_service_endpoints, validate_deployment)
- Caps enforcer (OSS no-op stub)
- Cloud client (OSS Pattern 3 stub)
- Deploy migrate (OSS Pattern 3 stub)

Phase 3 additions (GUIDEAI-751):
- CLI command gating (_check_cli_module_enabled)
- MCP tool gating (MCPLazyToolLoader.set_module_filter / _is_tool_allowed_by_module)
- API route gating middleware
- /api/v1/modules endpoint
- is_module_enabled_for_migration helper
- env.py _get_enabled_schemas filtering

Phase 4 additions (GUIDEAI-752):
- Edition caps enforcer (EditionCapsEnforcer, CapsExceededError)
- Edition gating helpers (edition_at_least, edition_rank)
- Edition gating decorators (requires_edition, requires_capability, EditionGateError)
- Tier transitions (TierTransition, get_transition, validate_transition)
- Module edition gating (min_edition field, collaboration module, is_module_edition_allowed)
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# Mock heavy optional deps so cli.py / api.py can be imported in test env
# without the full breakeramp / raze packages installed.
for _mod in ("amprealize.breakeramp", "amprealize.breakeramp.service"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from amprealize.caps_enforcer import (
    CapsEnforcer,
    CapsExceededError,
    EditionCapsEnforcer,
    get_caps_enforcer,
    reset_caps_enforcer,
)
from amprealize.cloud_client import CloudClient, get_cloud_client
from amprealize.config.schema import (
    AmprealizeConfig,
    DeploymentConfig,
    DeploymentServicesConfig,
    ModulesConfig,
)
from amprealize.deployment import (
    ServiceEndpoints,
    resolve_service_endpoints,
    validate_deployment,
)
from amprealize.edition import (
    Edition,
    EditionCapabilities,
    EditionGateError,
    TierTransition,
    _EDITION_RANK,
    _VALID_TRANSITIONS,
    detect_edition,
    edition_at_least,
    edition_rank,
    get_caps,
    get_transition,
    requires_capability,
    requires_edition,
    validate_transition,
)
from amprealize.module_registry import (
    MODULE_REGISTRY,
    PRESETS,
    ModuleDefinition,
    get_enabled_capability_flags,
    get_enabled_cli_groups,
    get_enabled_modules,
    get_enabled_mcp_tool_prefixes,
    is_module_edition_allowed,
    is_module_enabled_for_migration,
    resolve_preset,
    validate_module_dependencies,
)

pytestmark = pytest.mark.unit


# ===========================================================================
# Config Models
# ===========================================================================


class TestModulesConfig:
    """ModulesConfig — module selection Pydantic model."""

    def test_defaults(self) -> None:
        cfg = ModulesConfig()
        assert cfg.goals is True
        assert cfg.agents is False
        assert cfg.behaviors is False

    def test_goals_always_true(self) -> None:
        with pytest.raises(ValueError, match="goals module cannot be disabled"):
            ModulesConfig(goals=False)

    def test_enable_agents(self) -> None:
        cfg = ModulesConfig(agents=True)
        assert cfg.agents is True
        assert cfg.behaviors is False

    def test_enable_all(self) -> None:
        cfg = ModulesConfig(agents=True, behaviors=True)
        assert cfg.goals is True
        assert cfg.agents is True
        assert cfg.behaviors is True

    def test_goals_none_coerced(self) -> None:
        """goals=None should be coerced to True by the validator."""
        cfg = ModulesConfig(goals=None)
        assert cfg.goals is True


class TestDeploymentServicesConfig:
    """DeploymentServicesConfig — per-service hybrid overrides."""

    def test_defaults(self) -> None:
        cfg = DeploymentServicesConfig()
        assert cfg.storage == "local"
        assert cfg.compute == "local"

    def test_cloud_overrides(self) -> None:
        cfg = DeploymentServicesConfig(storage="cloud", compute="cloud")
        assert cfg.storage == "cloud"
        assert cfg.compute == "cloud"

    def test_invalid_value(self) -> None:
        with pytest.raises(ValueError):
            DeploymentServicesConfig(storage="invalid")


class TestDeploymentConfig:
    """DeploymentConfig — deployment mode model."""

    def test_defaults(self) -> None:
        cfg = DeploymentConfig()
        assert cfg.mode == "local"
        assert cfg.services.storage == "local"
        assert cfg.cloud_url == "https://api.amprealize.io"

    def test_cloud_mode(self) -> None:
        cfg = DeploymentConfig(mode="cloud")
        assert cfg.mode == "cloud"

    def test_hybrid_with_services(self) -> None:
        cfg = DeploymentConfig(
            mode="hybrid",
            services=DeploymentServicesConfig(storage="cloud", compute="local"),
        )
        assert cfg.mode == "hybrid"
        assert cfg.services.storage == "cloud"
        assert cfg.services.compute == "local"

    def test_invalid_mode(self) -> None:
        with pytest.raises(ValueError):
            DeploymentConfig(mode="invalid")

    def test_custom_cloud_url(self) -> None:
        cfg = DeploymentConfig(cloud_url="https://custom.example.com")
        assert cfg.cloud_url == "https://custom.example.com"


class TestAmprealizeConfigIntegration:
    """AmprealizeConfig includes modules and deployment fields."""

    def test_default_config_has_modules_and_deployment(self) -> None:
        cfg = AmprealizeConfig()
        assert isinstance(cfg.modules, ModulesConfig)
        assert isinstance(cfg.deployment, DeploymentConfig)
        assert cfg.modules.goals is True
        assert cfg.deployment.mode == "local"

    def test_backward_compat_no_modules_key(self) -> None:
        """Existing configs without modules/deployment → defaults."""
        cfg = AmprealizeConfig.model_validate({"version": 1})
        assert cfg.modules.goals is True
        assert cfg.modules.agents is False
        assert cfg.deployment.mode == "local"


# ===========================================================================
# Module Registry
# ===========================================================================


class TestModuleDefinition:
    """ModuleDefinition dataclass and registry contents."""

    def test_goals_always_enabled(self) -> None:
        goals = MODULE_REGISTRY["goals"]
        assert goals.always_enabled is True
        assert goals.name == "goals"

    def test_agents_depends_on_goals(self) -> None:
        agents = MODULE_REGISTRY["agents"]
        assert "goals" in agents.depends_on
        assert agents.always_enabled is False

    def test_behaviors_depends_on_goals(self) -> None:
        behaviors = MODULE_REGISTRY["behaviors"]
        assert "goals" in behaviors.depends_on

    def test_self_improving_enterprise_only(self) -> None:
        si = MODULE_REGISTRY["self_improving"]
        assert si.enterprise_only is True
        assert "behaviors" in si.depends_on

    def test_all_modules_have_required_fields(self) -> None:
        for name, mod in MODULE_REGISTRY.items():
            assert mod.name == name
            assert mod.display_name
            assert mod.description
            assert isinstance(mod.db_schemas, tuple)
            assert isinstance(mod.mcp_tool_prefixes, tuple)

    def test_frozen(self) -> None:
        goals = MODULE_REGISTRY["goals"]
        with pytest.raises(AttributeError):
            goals.name = "changed"  # type: ignore[misc]


class TestPresets:
    """PRESETS — named module combinations."""

    def test_goals_preset(self) -> None:
        assert resolve_preset("goals") == ("goals",)

    def test_full_preset(self) -> None:
        full = resolve_preset("full")
        assert "goals" in full
        assert "agents" in full
        assert "behaviors" in full

    def test_unknown_preset_raises(self) -> None:
        with pytest.raises(KeyError):
            resolve_preset("nonexistent")

    def test_all_presets_include_goals(self) -> None:
        for name, modules in PRESETS.items():
            assert "goals" in modules, f"Preset {name!r} missing goals"


class TestModuleHelpers:
    """Helper functions: get_enabled_modules, tool prefixes, etc."""

    def test_goals_only(self) -> None:
        cfg = ModulesConfig()
        enabled = get_enabled_modules(cfg)
        names = [m.name for m in enabled]
        assert names == ["goals"]

    def test_full_modules(self) -> None:
        cfg = ModulesConfig(agents=True, behaviors=True)
        enabled = get_enabled_modules(cfg)
        names = {m.name for m in enabled}
        assert names == {"goals", "agents", "behaviors"}

    def test_enabled_mcp_prefixes_goals_only(self) -> None:
        cfg = ModulesConfig()
        prefixes = get_enabled_mcp_tool_prefixes(cfg)
        assert "projects" in prefixes
        assert "agents" not in prefixes

    def test_enabled_mcp_prefixes_full(self) -> None:
        cfg = ModulesConfig(agents=True, behaviors=True)
        prefixes = get_enabled_mcp_tool_prefixes(cfg)
        assert "projects" in prefixes
        assert "agents" in prefixes
        assert "behaviors" in prefixes

    def test_enabled_cli_groups(self) -> None:
        cfg = ModulesConfig(agents=True)
        groups = get_enabled_cli_groups(cfg)
        assert "project" in groups
        assert "agent" in groups
        assert "behavior" not in groups

    def test_enabled_capability_flags(self) -> None:
        cfg = ModulesConfig(behaviors=True)
        flags = get_enabled_capability_flags(cfg)
        assert "projects" in flags
        assert "behaviors" in flags
        assert "agents" not in flags

    def test_enterprise_only_excluded(self) -> None:
        """self_improving module is enterprise-only, not returned."""
        cfg = ModulesConfig(agents=True, behaviors=True)
        enabled = get_enabled_modules(cfg)
        names = {m.name for m in enabled}
        assert "self_improving" not in names


class TestDependencyValidation:
    """validate_module_dependencies — check dependency graph."""

    def test_valid_full(self) -> None:
        errors = validate_module_dependencies(("goals", "agents", "behaviors"))
        assert errors == []

    def test_agents_without_goals(self) -> None:
        errors = validate_module_dependencies(("agents",))
        assert any("goals" in e for e in errors)

    def test_self_improving_without_behaviors(self) -> None:
        errors = validate_module_dependencies(("goals", "self_improving"))
        assert any("behaviors" in e for e in errors)

    def test_unknown_module(self) -> None:
        errors = validate_module_dependencies(("goals", "nonexistent"))
        assert any("Unknown module" in e for e in errors)

    def test_goals_standalone(self) -> None:
        errors = validate_module_dependencies(("goals",))
        assert errors == []


# ===========================================================================
# Edition
# ===========================================================================


class TestEdition:
    """Edition enum and detect_edition."""

    def test_oss_enum(self) -> None:
        assert Edition.OSS.value == "oss"

    def test_enterprise_enums(self) -> None:
        assert Edition.ENTERPRISE_STARTER.value == "enterprise_starter"
        assert Edition.ENTERPRISE_PREMIUM.value == "enterprise_premium"

    @patch("amprealize.edition.HAS_ENTERPRISE", False)
    def test_detect_oss(self) -> None:
        assert detect_edition() == Edition.OSS

    @patch("amprealize.edition.HAS_ENTERPRISE", True)
    @patch("amprealize.edition.resolve_tier", None)
    def test_detect_enterprise_default_starter(self) -> None:
        assert detect_edition() == Edition.ENTERPRISE_STARTER

    @patch("amprealize.edition.HAS_ENTERPRISE", True)
    @patch("amprealize.edition.resolve_tier", lambda: "premium")
    def test_detect_enterprise_premium(self) -> None:
        assert detect_edition() == Edition.ENTERPRISE_PREMIUM

    @patch("amprealize.edition.HAS_ENTERPRISE", True)
    @patch("amprealize.edition.resolve_tier", lambda: "starter")
    def test_detect_enterprise_starter_explicit(self) -> None:
        assert detect_edition() == Edition.ENTERPRISE_STARTER


class TestEditionCapabilities:
    """EditionCapabilities and get_caps."""

    def test_oss_caps_uncapped(self) -> None:
        caps = get_caps(Edition.OSS)
        assert caps.edition == Edition.OSS
        assert caps.max_projects == -1
        assert caps.max_agents == -1
        assert caps.orgs is False
        assert caps.sso is False

    def test_starter_caps(self) -> None:
        caps = get_caps(Edition.ENTERPRISE_STARTER)
        assert caps.edition == Edition.ENTERPRISE_STARTER
        assert caps.max_projects == 10
        assert caps.max_agents == 3
        assert caps.orgs is True
        assert caps.sso is False
        assert caps.conversations is True

    def test_premium_caps_uncapped(self) -> None:
        caps = get_caps(Edition.ENTERPRISE_PREMIUM)
        assert caps.edition == Edition.ENTERPRISE_PREMIUM
        assert caps.max_projects == -1
        assert caps.sso is True
        assert caps.self_improving is True
        assert caps.custom_branding is True

    @patch("amprealize.edition.HAS_ENTERPRISE", False)
    def test_get_caps_auto_detect(self) -> None:
        caps = get_caps()
        assert caps.edition == Edition.OSS


# ===========================================================================
# Deployment
# ===========================================================================


class TestResolveServiceEndpoints:
    """resolve_service_endpoints — map config to endpoints."""

    def test_local(self) -> None:
        cfg = DeploymentConfig(mode="local")
        endpoints = resolve_service_endpoints(cfg)
        assert endpoints.storage == "local"
        assert endpoints.compute == "local"
        assert endpoints.auth == "local"

    def test_cloud(self) -> None:
        cfg = DeploymentConfig(mode="cloud")
        endpoints = resolve_service_endpoints(cfg)
        assert "api.amprealize.io" in endpoints.storage
        assert "api.amprealize.io" in endpoints.compute
        assert "api.amprealize.io" in endpoints.auth

    def test_hybrid_storage_cloud(self) -> None:
        cfg = DeploymentConfig(
            mode="hybrid",
            services=DeploymentServicesConfig(storage="cloud", compute="local"),
        )
        endpoints = resolve_service_endpoints(cfg)
        assert "api.amprealize.io" in endpoints.storage
        assert endpoints.compute == "local"
        assert endpoints.auth == "local"  # auth always local in hybrid

    def test_custom_cloud_url(self) -> None:
        cfg = DeploymentConfig(mode="cloud", cloud_url="https://custom.example.com")
        endpoints = resolve_service_endpoints(cfg)
        assert "custom.example.com" in endpoints.storage


class TestValidateDeployment:
    """validate_deployment — config validation."""

    @patch("amprealize.deployment.HAS_ENTERPRISE", False)
    def test_cloud_without_enterprise(self) -> None:
        cfg = DeploymentConfig(mode="cloud")
        errors = validate_deployment(cfg)
        assert any("amprealize-enterprise" in e for e in errors)

    @patch("amprealize.deployment.HAS_ENTERPRISE", True)
    def test_cloud_with_enterprise(self) -> None:
        cfg = DeploymentConfig(mode="cloud")
        errors = validate_deployment(cfg)
        assert not any("amprealize-enterprise" in e for e in errors)

    @patch("amprealize.deployment.HAS_ENTERPRISE", False)
    def test_local_always_valid(self) -> None:
        cfg = DeploymentConfig(mode="local")
        errors = validate_deployment(cfg)
        assert not any("amprealize-enterprise" in e for e in errors)

    @patch("amprealize.deployment.HAS_ENTERPRISE", True)
    def test_services_override_outside_hybrid(self) -> None:
        cfg = DeploymentConfig(
            mode="local",
            services=DeploymentServicesConfig(storage="cloud"),
        )
        errors = validate_deployment(cfg)
        assert any("hybrid" in e for e in errors)

    def test_invalid_cloud_url(self) -> None:
        cfg = DeploymentConfig(cloud_url="http://insecure.example.com")
        errors = validate_deployment(cfg)
        assert any("https://" in e for e in errors)


# ===========================================================================
# Caps Enforcer (OSS stub)
# ===========================================================================


class TestCapsEnforcer:
    """CapsEnforcer — OSS no-op Pattern 2 stub."""

    def test_check_always_true(self) -> None:
        enforcer = CapsEnforcer()
        assert enforcer.check("projects", current_count=999) is True
        assert enforcer.check("agents", current_count=0) is True

    def test_get_limit_always_unlimited(self) -> None:
        enforcer = CapsEnforcer()
        assert enforcer.get_limit("projects") == -1
        assert enforcer.get_limit("anything") == -1

    def test_usage_summary_empty(self) -> None:
        enforcer = CapsEnforcer()
        assert enforcer.get_usage_summary() == {}

    def test_factory_returns_oss_stub(self) -> None:
        """Without amprealize-enterprise, factory returns OSS stub."""
        reset_caps_enforcer()
        enforcer = get_caps_enforcer()
        assert isinstance(enforcer, CapsEnforcer)
        assert enforcer.check("projects", current_count=100) is True
        reset_caps_enforcer()


# ===========================================================================
# Cloud Client (OSS stub)
# ===========================================================================


class TestCloudClient:
    """CloudClient — OSS Pattern 3 stub (raise on call)."""

    def test_upload_raises(self) -> None:
        client = CloudClient()
        with pytest.raises(ImportError, match="amprealize-enterprise"):
            client.upload()

    def test_download_raises(self) -> None:
        client = CloudClient()
        with pytest.raises(ImportError, match="amprealize-enterprise"):
            client.download()

    def test_submit_job_raises(self) -> None:
        client = CloudClient()
        with pytest.raises(ImportError, match="amprealize-enterprise"):
            client.submit_job()

    def test_authenticate_raises(self) -> None:
        client = CloudClient()
        with pytest.raises(ImportError, match="amprealize-enterprise"):
            client.authenticate()

    def test_request_raises(self) -> None:
        client = CloudClient()
        with pytest.raises(ImportError, match="amprealize-enterprise"):
            client.request()

    def test_factory_returns_oss_stub(self) -> None:
        """Without amprealize-enterprise, factory returns OSS stub."""
        client = get_cloud_client()
        assert isinstance(client, CloudClient)
        with pytest.raises(ImportError):
            client.upload()


# ===========================================================================
# Deploy Migrate (OSS stub)
# ===========================================================================


class TestDeployMigrate:
    """deploy_migrate — OSS Pattern 3 stubs."""

    def test_export_data_raises(self) -> None:
        from amprealize.deploy_migrate import export_data
        with pytest.raises(ImportError, match="amprealize-enterprise"):
            export_data()

    def test_import_data_raises(self) -> None:
        from amprealize.deploy_migrate import import_data
        with pytest.raises(ImportError, match="amprealize-enterprise"):
            import_data()

    def test_sync_to_cloud_raises(self) -> None:
        from amprealize.deploy_migrate import sync_to_cloud
        with pytest.raises(ImportError, match="amprealize-enterprise"):
            sync_to_cloud()

    def test_sync_from_cloud_raises(self) -> None:
        from amprealize.deploy_migrate import sync_from_cloud
        with pytest.raises(ImportError, match="amprealize-enterprise"):
            sync_from_cloud()

    def test_migrate_deployment_raises(self) -> None:
        from amprealize.deploy_migrate import migrate_deployment
        with pytest.raises(ImportError, match="amprealize-enterprise"):
            migrate_deployment()


# ═════════════════════════════════════════════════════════════════════════════
# PHASE 2 — Init flow helpers (GUIDEAI-750)
# ═════════════════════════════════════════════════════════════════════════════


class TestResolveModulesFlag:
    """Test _resolve_modules_flag parsing."""

    def test_preset_goals(self) -> None:
        from amprealize.cli import _resolve_modules_flag
        result = _resolve_modules_flag("goals")
        assert result == ("goals",)

    def test_preset_full(self) -> None:
        from amprealize.cli import _resolve_modules_flag
        result = _resolve_modules_flag("full")
        assert "goals" in result
        assert "agents" in result
        assert "behaviors" in result

    def test_preset_goals_agents(self) -> None:
        from amprealize.cli import _resolve_modules_flag
        result = _resolve_modules_flag("goals-agents")
        assert "goals" in result
        assert "agents" in result

    def test_csv_modules(self) -> None:
        from amprealize.cli import _resolve_modules_flag
        result = _resolve_modules_flag("goals,agents")
        assert "goals" in result
        assert "agents" in result

    def test_csv_auto_adds_goals(self) -> None:
        from amprealize.cli import _resolve_modules_flag
        result = _resolve_modules_flag("agents,behaviors")
        assert result[0] == "goals"

    def test_unknown_module_exits(self) -> None:
        from amprealize.cli import _resolve_modules_flag
        with pytest.raises(SystemExit, match="Unknown modules"):
            _resolve_modules_flag("nonexistent")

    def test_whitespace_handling(self) -> None:
        from amprealize.cli import _resolve_modules_flag
        result = _resolve_modules_flag("  goals , agents  ")
        assert "goals" in result
        assert "agents" in result


class TestPromptModules:
    """Test _prompt_modules interactive picker."""

    def test_prompt_modules_returns_preset(self) -> None:
        from amprealize.cli import _prompt_modules
        with patch("amprealize.cli._prompt", return_value="full"):
            result = _prompt_modules()
        assert "goals" in result
        assert "agents" in result
        assert "behaviors" in result

    def test_prompt_modules_returns_csv(self) -> None:
        from amprealize.cli import _prompt_modules
        with patch("amprealize.cli._prompt", return_value="goals,agents"):
            result = _prompt_modules()
        assert "goals" in result
        assert "agents" in result
        assert "behaviors" not in result

    def test_prompt_modules_default(self) -> None:
        from amprealize.cli import _prompt_modules
        with patch("amprealize.cli._prompt", return_value="goals"):
            result = _prompt_modules()
        assert result == ("goals",)


class TestRenderConfigYamlModules:
    """Test _render_config_yaml includes modules and deployment sections."""

    def test_default_modules_in_yaml(self) -> None:
        import yaml
        from amprealize.cli import _render_config_yaml
        rendered = _render_config_yaml("test-proj", "sqlite", "none")
        config = yaml.safe_load(rendered)
        assert config["modules"]["goals"] is True
        assert config["modules"]["agents"] is False
        assert config["modules"]["behaviors"] is False
        assert config["deployment"]["mode"] == "local"

    def test_full_modules_in_yaml(self) -> None:
        import yaml
        from amprealize.cli import _render_config_yaml
        rendered = _render_config_yaml(
            "test-proj", "sqlite", "none",
            enabled_modules=("goals", "agents", "behaviors"),
            deployment_mode="cloud",
        )
        config = yaml.safe_load(rendered)
        assert config["modules"]["goals"] is True
        assert config["modules"]["agents"] is True
        assert config["modules"]["behaviors"] is True
        assert config["deployment"]["mode"] == "cloud"

    def test_agents_only_in_yaml(self) -> None:
        import yaml
        from amprealize.cli import _render_config_yaml
        rendered = _render_config_yaml(
            "test-proj", "sqlite", "none",
            enabled_modules=("goals", "agents"),
            deployment_mode="hybrid",
        )
        config = yaml.safe_load(rendered)
        assert config["modules"]["agents"] is True
        assert config["modules"]["behaviors"] is False
        assert config["deployment"]["mode"] == "hybrid"


class TestCommandInitModulesIntegration:
    """Integration tests for _command_init with --modules/--deployment."""

    def test_init_non_interactive_with_modules_flag(self, tmp_path, monkeypatch) -> None:
        """Non-interactive init with --modules=full --deployment=cloud."""
        import types
        from amprealize.cli import _command_init

        monkeypatch.chdir(tmp_path)
        args = types.SimpleNamespace(
            project_name="test-proj",
            storage_backend="sqlite",
            auth_mode="none",
            postgres_dsn="",
            skip_pack=True,
            modules="full",
            deployment="cloud",
            workspace_profile=None,
        )
        with patch("amprealize.cli._prompt", wraps=lambda l, d, c=None: d) as mock_prompt, \
             patch("builtins.input", return_value=""):
            rc = _command_init(args)
        # _prompt should NOT be called for modules since --modules was provided
        for call in mock_prompt.call_args_list:
            assert "Modules" not in str(call), "Should not prompt for modules when flag given"
        assert rc == 0
        # Verify config was written with modules
        import yaml
        config_path = tmp_path / ".amprealize" / "config.yaml"
        assert config_path.exists()
        config = yaml.safe_load(config_path.read_text())
        assert config["modules"]["agents"] is True
        assert config["modules"]["behaviors"] is True
        assert config["deployment"]["mode"] == "cloud"

    def test_init_non_interactive_with_deployment_flag(self, tmp_path, monkeypatch) -> None:
        """Non-interactive init with --deployment=hybrid."""
        import types
        from amprealize.cli import _command_init

        monkeypatch.chdir(tmp_path)
        args = types.SimpleNamespace(
            project_name="test-proj",
            storage_backend="sqlite",
            auth_mode="none",
            postgres_dsn="",
            skip_pack=True,
            modules=None,
            deployment="hybrid",
            workspace_profile=None,
        )
        with patch("amprealize.cli._prompt", wraps=lambda l, d, c=None: d) as mock_prompt, \
             patch("builtins.input", return_value=""):
            rc = _command_init(args)
        # deployment prompt should be skipped
        for call in mock_prompt.call_args_list:
            assert "Deployment" not in str(call), "Should not prompt for deployment when flag given"
        assert rc == 0
        import yaml
        config_path = tmp_path / ".amprealize" / "config.yaml"
        config = yaml.safe_load(config_path.read_text())
        assert config["deployment"]["mode"] == "hybrid"


# ===========================================================================
# Phase 3 — Module gating across surfaces (GUIDEAI-751)
# ===========================================================================


# ---------------------------------------------------------------------------
# CLI Command Gating
# ---------------------------------------------------------------------------


class TestCLICommandGating:
    """_check_cli_module_enabled and _CLI_COMMAND_MODULE_MAP."""

    def test_ungated_command_returns_none(self) -> None:
        """Commands not in _CLI_COMMAND_MODULE_MAP are always allowed."""
        from amprealize.cli import _check_cli_module_enabled

        assert _check_cli_module_enabled("init") is None
        assert _check_cli_module_enabled("status") is None
        assert _check_cli_module_enabled("") is None

    def test_gated_command_enabled_returns_none(self) -> None:
        """When module is enabled, command should be allowed."""
        from amprealize.cli import _check_cli_module_enabled

        full_config = ModulesConfig(agents=True, behaviors=True)
        with patch("amprealize.config.loader.get_config") as mock_cfg:
            mock_cfg.return_value = AmprealizeConfig(modules=full_config)
            assert _check_cli_module_enabled("behaviors") is None
            assert _check_cli_module_enabled("agents") is None
            assert _check_cli_module_enabled("bci") is None
            assert _check_cli_module_enabled("run") is None

    def test_gated_command_disabled_returns_message(self) -> None:
        """When module is disabled, command should return error message."""
        from amprealize.cli import _check_cli_module_enabled

        goals_only = ModulesConfig(agents=False, behaviors=False)
        with patch("amprealize.config.loader.get_config") as mock_cfg:
            mock_cfg.return_value = AmprealizeConfig(modules=goals_only)
            msg = _check_cli_module_enabled("behaviors")
            assert msg is not None
            assert "not enabled" in msg

            msg2 = _check_cli_module_enabled("agents")
            assert msg2 is not None
            assert "not enabled" in msg2

    def test_no_config_allows_everything(self) -> None:
        """When config is not available, all commands should be allowed."""
        from amprealize.cli import _check_cli_module_enabled

        with patch("amprealize.config.loader.get_config", side_effect=Exception("no config")):
            assert _check_cli_module_enabled("behaviors") is None
            assert _check_cli_module_enabled("agents") is None

    def test_command_module_map_covers_all_module_commands(self) -> None:
        """_CLI_COMMAND_MODULE_MAP covers agent+behavior commands."""
        from amprealize.cli import _CLI_COMMAND_MODULE_MAP

        assert "behaviors" in _CLI_COMMAND_MODULE_MAP
        assert "bci" in _CLI_COMMAND_MODULE_MAP
        assert "agents" in _CLI_COMMAND_MODULE_MAP
        assert "run" in _CLI_COMMAND_MODULE_MAP
        assert "reflection" in _CLI_COMMAND_MODULE_MAP
        # Core commands should NOT be in the map
        assert "init" not in _CLI_COMMAND_MODULE_MAP
        assert "status" not in _CLI_COMMAND_MODULE_MAP


# ---------------------------------------------------------------------------
# MCP Tool Gating
# ---------------------------------------------------------------------------


class TestMCPToolGating:
    """MCPLazyToolLoader module filtering (_is_tool_allowed_by_module)."""

    def _make_loader(self):
        from amprealize.mcp_lazy_loader import MCPLazyToolLoader

        return MCPLazyToolLoader()

    def test_no_filter_allows_all(self) -> None:
        """Without set_module_filter, all tools pass."""
        loader = self._make_loader()
        assert loader._is_tool_allowed_by_module("behaviors.list") is True
        assert loader._is_tool_allowed_by_module("agents.create") is True
        assert loader._is_tool_allowed_by_module("anything") is True

    def test_filter_allows_enabled_prefixes(self) -> None:
        """Tools whose prefix is enabled should pass."""
        loader = self._make_loader()
        enabled = {"projects", "boards", "behaviors", "bci"}
        all_mod = {"projects", "boards", "behaviors", "bci", "agents", "runs"}
        loader.set_module_filter(enabled, all_mod)

        assert loader._is_tool_allowed_by_module("behaviors.list") is True
        assert loader._is_tool_allowed_by_module("bci.generate") is True
        assert loader._is_tool_allowed_by_module("projects.get") is True

    def test_filter_blocks_disabled_prefixes(self) -> None:
        """Tools whose prefix is disabled should be blocked."""
        loader = self._make_loader()
        enabled = {"projects", "boards"}
        all_mod = {"projects", "boards", "behaviors", "bci", "agents", "runs"}
        loader.set_module_filter(enabled, all_mod)

        assert loader._is_tool_allowed_by_module("behaviors.list") is False
        assert loader._is_tool_allowed_by_module("agents.create") is False
        assert loader._is_tool_allowed_by_module("runs.status") is False

    def test_non_module_tools_always_pass(self) -> None:
        """Tools not owned by any module (platform/infra) always pass."""
        loader = self._make_loader()
        enabled = {"projects"}
        all_mod = {"projects", "agents"}
        loader.set_module_filter(enabled, all_mod)

        # 'system.health' prefix not in any module
        assert loader._is_tool_allowed_by_module("system.health") is True
        assert loader._is_tool_allowed_by_module("platform_info") is True

    def test_underscore_prefix_matching(self) -> None:
        """Tools with underscore separator (agents_list) should match."""
        loader = self._make_loader()
        enabled = {"projects"}
        all_mod = {"projects", "agents"}
        loader.set_module_filter(enabled, all_mod)

        assert loader._is_tool_allowed_by_module("agents_list") is False
        assert loader._is_tool_allowed_by_module("projects_list") is True


# ---------------------------------------------------------------------------
# API Route Gating
# ---------------------------------------------------------------------------


class TestAPIModuleGating:
    """API module gating — tests the registry functions behind /api/v1/modules.

    Full create_app() cannot be called in this test environment because
    breakeramp types (PlanResponse, etc.) are MagicMock'd and FastAPI cannot
    build OpenAPI schemas from them.  Instead we directly invoke the registry
    helpers that the endpoint delegates to, and verify the middleware's
    disabled-router calculation.
    """

    def test_modules_response_full_config(self) -> None:
        """Full config produces complete enabled_modules list."""
        from amprealize.module_registry import (
            get_enabled_modules,
            get_enabled_capability_flags,
            MODULE_REGISTRY,
        )

        full_cfg = ModulesConfig(agents=True, behaviors=True)
        enabled = get_enabled_modules(full_cfg)
        flags = get_enabled_capability_flags(full_cfg)
        result = {
            "enabled_modules": sorted(m.name for m in enabled),
            "capability_flags": sorted(flags),
            "all_modules": sorted(MODULE_REGISTRY.keys()),
        }
        assert "goals" in result["all_modules"]
        assert "agents" in result["enabled_modules"]
        assert "behaviors" in result["enabled_modules"]

    def test_modules_response_goals_only(self) -> None:
        """Goals-only config still lists all modules in all_modules."""
        from amprealize.module_registry import (
            get_enabled_modules,
            get_enabled_capability_flags,
            get_enabled_api_routers,
            get_all_module_api_routers,
            MODULE_REGISTRY,
        )

        goals_only = ModulesConfig(agents=False, behaviors=False)
        enabled = get_enabled_modules(goals_only)
        enabled_names = sorted(m.name for m in enabled)
        all_names = sorted(MODULE_REGISTRY.keys())

        # All modules still listed
        assert len(all_names) >= 4
        # But agents/behaviors not enabled
        assert "agents" not in enabled_names
        assert "behaviors" not in enabled_names
        assert "goals" in enabled_names

        # Disabled API routers should be the difference
        enabled_routers = get_enabled_api_routers(goals_only)
        all_routers = get_all_module_api_routers()
        disabled = all_routers - enabled_routers
        assert len(disabled) > 0


# ---------------------------------------------------------------------------
# is_module_enabled_for_migration
# ---------------------------------------------------------------------------


class TestModuleMigrationHelper:
    """is_module_enabled_for_migration — safe migration-time check."""

    def test_enabled_module_returns_true(self) -> None:
        full_config = AmprealizeConfig(
            modules=ModulesConfig(agents=True, behaviors=True)
        )
        with patch(
            "amprealize.config.loader.get_config", return_value=full_config
        ):
            assert is_module_enabled_for_migration("agents") is True
            assert is_module_enabled_for_migration("behaviors") is True
            assert is_module_enabled_for_migration("goals") is True

    def test_disabled_module_returns_false(self) -> None:
        goals_only = AmprealizeConfig(
            modules=ModulesConfig(agents=False, behaviors=False)
        )
        with patch(
            "amprealize.config.loader.get_config", return_value=goals_only
        ):
            assert is_module_enabled_for_migration("agents") is False
            assert is_module_enabled_for_migration("behaviors") is False
            # goals is always-enabled
            assert is_module_enabled_for_migration("goals") is True

    def test_no_config_returns_true(self) -> None:
        """Defaults to True when config is missing (first run)."""
        with patch(
            "amprealize.config.loader.get_config",
            side_effect=Exception("no config"),
        ):
            assert is_module_enabled_for_migration("agents") is True
            assert is_module_enabled_for_migration("behaviors") is True

    def test_migrate_all_env_returns_true(self, monkeypatch) -> None:
        """AMPREALIZE_MIGRATE_ALL=1 forces True for all modules."""
        monkeypatch.setenv("AMPREALIZE_MIGRATE_ALL", "1")
        # Even with disabled config, should return True
        goals_only = AmprealizeConfig(
            modules=ModulesConfig(agents=False, behaviors=False)
        )
        with patch(
            "amprealize.config.loader.get_config", return_value=goals_only
        ):
            assert is_module_enabled_for_migration("agents") is True
            assert is_module_enabled_for_migration("behaviors") is True


# ---------------------------------------------------------------------------
# env.py _get_enabled_schemas
# ---------------------------------------------------------------------------


class TestEnvSchemaFiltering:
    """migrations/env.py _get_enabled_schemas filtering.

    The ``migrations.env`` module runs ``context.config`` at import time (normal
    when Alembic drives the process).  We pre-populate ``sys.modules`` with a
    mock so the import succeeds in a plain pytest session.
    """

    @staticmethod
    def _import_env():
        """Import migrations.env with Alembic context mocked."""
        import importlib

        mock_ctx = MagicMock()
        mock_ctx.config = MagicMock()
        mock_ctx.config.config_file_name = None
        with patch.dict(sys.modules, {"alembic.context": mock_ctx}):
            # Force reimport so the patched context is used
            if "migrations.env" in sys.modules:
                mod = importlib.reload(sys.modules["migrations.env"])
            else:
                mod = importlib.import_module("migrations.env")
        return mod

    def test_full_modules_returns_all_schemas(self) -> None:
        """When all modules enabled, all schemas returned."""
        env_mod = self._import_env()

        full_config = AmprealizeConfig(
            modules=ModulesConfig(agents=True, behaviors=True)
        )
        with patch("amprealize.config.loader.get_config", return_value=full_config):
            schemas = env_mod._get_enabled_schemas()

        assert set(schemas) == set(env_mod.MANAGED_SCHEMAS)

    def test_goals_only_excludes_module_schemas(self) -> None:
        """When only goals enabled, behavior and execution schemas excluded."""
        env_mod = self._import_env()

        goals_only = AmprealizeConfig(
            modules=ModulesConfig(agents=False, behaviors=False)
        )
        with patch("amprealize.config.loader.get_config", return_value=goals_only):
            schemas = env_mod._get_enabled_schemas()

        # Module-owned schemas should be excluded
        assert "behavior" not in schemas
        assert "execution" not in schemas
        # Core schemas always present
        assert "auth" in schemas
        assert "board" in schemas
        assert "audit" in schemas

    def test_no_config_returns_all(self) -> None:
        """When config unavailable, all schemas returned."""
        env_mod = self._import_env()

        with patch("amprealize.config.loader.get_config", side_effect=Exception("no config")):
            schemas = env_mod._get_enabled_schemas()

        assert set(schemas) == set(env_mod.MANAGED_SCHEMAS)

    def test_migrate_all_env_returns_all(self, monkeypatch) -> None:
        """AMPREALIZE_MIGRATE_ALL=1 returns all schemas."""
        env_mod = self._import_env()

        monkeypatch.setenv("AMPREALIZE_MIGRATE_ALL", "1")
        schemas = env_mod._get_enabled_schemas()
        assert set(schemas) == set(env_mod.MANAGED_SCHEMAS)


# ---------------------------------------------------------------------------
# Registry helper: get_enabled_db_schemas / get_all_module_api_routers
# ---------------------------------------------------------------------------


class TestRegistryPhase3Helpers:
    """Phase 3 registry helpers added for gating surfaces."""

    def test_get_enabled_db_schemas_full(self) -> None:
        from amprealize.module_registry import get_enabled_db_schemas

        full = ModulesConfig(agents=True, behaviors=True)
        schemas = get_enabled_db_schemas(full)
        assert "agents" in schemas
        assert "behaviors" in schemas
        assert "bci" in schemas
        assert "projects" in schemas  # goals always-on

    def test_get_enabled_db_schemas_goals_only(self) -> None:
        from amprealize.module_registry import get_enabled_db_schemas

        goals = ModulesConfig(agents=False, behaviors=False)
        schemas = get_enabled_db_schemas(goals)
        assert "projects" in schemas
        assert "boards" in schemas
        assert "agents" not in schemas
        assert "behaviors" not in schemas

    def test_get_all_module_api_routers(self) -> None:
        from amprealize.module_registry import get_all_module_api_routers

        all_routers = get_all_module_api_routers()
        # Should include routers from ALL modules
        assert "agents" in all_routers
        assert "behaviors" in all_routers
        assert "projects" in all_routers
        assert "reflection" in all_routers

    def test_get_all_module_mcp_prefixes(self) -> None:
        from amprealize.module_registry import get_all_module_mcp_prefixes

        all_prefixes = get_all_module_mcp_prefixes()
        assert "agents" in all_prefixes
        assert "behaviors" in all_prefixes
        assert "projects" in all_prefixes
        assert "reflection" in all_prefixes


# ===========================================================================
# Phase 4 — Edition Gating & Caps Enforcement  (GUIDEAI-752)
# ===========================================================================


class TestEditionCapsEnforcer:
    """EditionCapsEnforcer — resource limit checking against EditionCapabilities."""

    def test_starter_under_cap(self) -> None:
        caps = get_caps(Edition.ENTERPRISE_STARTER)
        enforcer = EditionCapsEnforcer(caps=caps)
        assert enforcer.check("projects", current_count=5) is True

    def test_starter_at_cap(self) -> None:
        caps = get_caps(Edition.ENTERPRISE_STARTER)
        enforcer = EditionCapsEnforcer(caps=caps)
        # max_projects == 10 → current=10 means AT limit → False
        assert enforcer.check("projects", current_count=10) is False

    def test_starter_over_cap(self) -> None:
        caps = get_caps(Edition.ENTERPRISE_STARTER)
        enforcer = EditionCapsEnforcer(caps=caps)
        assert enforcer.check("projects", current_count=15) is False

    def test_premium_uncapped(self) -> None:
        caps = get_caps(Edition.ENTERPRISE_PREMIUM)
        enforcer = EditionCapsEnforcer(caps=caps)
        assert enforcer.check("projects", current_count=999) is True
        assert enforcer.check("agents", current_count=999) is True

    def test_oss_uncapped(self) -> None:
        caps = get_caps(Edition.OSS)
        enforcer = EditionCapsEnforcer(caps=caps)
        assert enforcer.check("projects", current_count=999) is True

    def test_unknown_resource_uncapped(self) -> None:
        caps = get_caps(Edition.ENTERPRISE_STARTER)
        enforcer = EditionCapsEnforcer(caps=caps)
        assert enforcer.check("unknown_thing", current_count=999) is True
        assert enforcer.get_limit("unknown_thing") == -1

    def test_get_limit_starter(self) -> None:
        caps = get_caps(Edition.ENTERPRISE_STARTER)
        enforcer = EditionCapsEnforcer(caps=caps)
        assert enforcer.get_limit("projects") == 10
        assert enforcer.get_limit("agents") == 3
        assert enforcer.get_limit("behaviors") == 100
        assert enforcer.get_limit("members") == 15

    def test_enforce_under_cap(self) -> None:
        caps = get_caps(Edition.ENTERPRISE_STARTER)
        enforcer = EditionCapsEnforcer(caps=caps)
        enforcer.enforce("projects", current_count=5)  # no error

    def test_enforce_over_cap_raises(self) -> None:
        caps = get_caps(Edition.ENTERPRISE_STARTER)
        enforcer = EditionCapsEnforcer(caps=caps)
        with pytest.raises(CapsExceededError) as exc_info:
            enforcer.enforce("projects", current_count=10)
        assert exc_info.value.resource == "projects"
        assert exc_info.value.limit == 10
        assert exc_info.value.current == 10

    def test_get_usage_summary_starter(self) -> None:
        caps = get_caps(Edition.ENTERPRISE_STARTER)
        enforcer = EditionCapsEnforcer(caps=caps)
        summary = enforcer.get_usage_summary()
        assert "projects" in summary
        assert summary["projects"]["limit"] == 10
        assert "agents" in summary
        assert summary["agents"]["limit"] == 3

    def test_get_usage_summary_premium_empty(self) -> None:
        caps = get_caps(Edition.ENTERPRISE_PREMIUM)
        enforcer = EditionCapsEnforcer(caps=caps)
        summary = enforcer.get_usage_summary()
        assert summary == {}

    def test_lazy_caps_resolution(self) -> None:
        """EditionCapsEnforcer resolves caps lazily on first access."""
        enforcer = EditionCapsEnforcer(caps=None)
        with patch("amprealize.edition.HAS_ENTERPRISE", False):
            # Should auto-detect OSS caps
            assert enforcer.check("projects", current_count=999) is True


class TestCapsExceededError:
    """CapsExceededError exception properties."""

    def test_error_attributes(self) -> None:
        err = CapsExceededError("projects", 10, 12)
        assert err.resource == "projects"
        assert err.limit == 10
        assert err.current == 12
        assert "projects" in str(err)
        assert "10" in str(err)

    def test_is_exception(self) -> None:
        assert issubclass(CapsExceededError, Exception)


class TestCapsEnforcerFactory:
    """get_caps_enforcer factory with edition awareness."""

    @patch("amprealize.edition.HAS_ENTERPRISE", False)
    def test_oss_returns_noop(self) -> None:
        reset_caps_enforcer()
        enforcer = get_caps_enforcer()
        assert type(enforcer) is CapsEnforcer
        reset_caps_enforcer()

    @patch("amprealize.edition.HAS_ENTERPRISE", True)
    @patch("amprealize.edition.resolve_tier", None)
    def test_starter_returns_edition_enforcer(self) -> None:
        reset_caps_enforcer()
        enforcer = get_caps_enforcer()
        assert isinstance(enforcer, EditionCapsEnforcer)
        reset_caps_enforcer()

    @patch("amprealize.edition.HAS_ENTERPRISE", True)
    @patch("amprealize.edition.resolve_tier", lambda: "premium")
    def test_premium_returns_noop(self) -> None:
        reset_caps_enforcer()
        enforcer = get_caps_enforcer()
        assert type(enforcer) is CapsEnforcer
        reset_caps_enforcer()


# ---------------------------------------------------------------------------
# Edition comparison & gating  (GUIDEAI-766)
# ---------------------------------------------------------------------------


class TestEditionRank:
    """edition_rank and rank mapping."""

    def test_oss_rank_zero(self) -> None:
        assert edition_rank(Edition.OSS) == 0

    def test_starter_rank_one(self) -> None:
        assert edition_rank(Edition.ENTERPRISE_STARTER) == 1

    def test_premium_rank_two(self) -> None:
        assert edition_rank(Edition.ENTERPRISE_PREMIUM) == 2

    def test_rank_ordering(self) -> None:
        assert (
            edition_rank(Edition.OSS)
            < edition_rank(Edition.ENTERPRISE_STARTER)
            < edition_rank(Edition.ENTERPRISE_PREMIUM)
        )


class TestEditionAtLeast:
    """edition_at_least helper."""

    @patch("amprealize.edition.HAS_ENTERPRISE", False)
    def test_oss_meets_oss(self) -> None:
        assert edition_at_least(Edition.OSS) is True

    @patch("amprealize.edition.HAS_ENTERPRISE", False)
    def test_oss_fails_starter(self) -> None:
        assert edition_at_least(Edition.ENTERPRISE_STARTER) is False

    def test_explicit_current_meets(self) -> None:
        assert (
            edition_at_least(
                Edition.ENTERPRISE_STARTER,
                current=Edition.ENTERPRISE_PREMIUM,
            )
            is True
        )

    def test_explicit_current_fails(self) -> None:
        assert (
            edition_at_least(
                Edition.ENTERPRISE_PREMIUM,
                current=Edition.ENTERPRISE_STARTER,
            )
            is False
        )

    def test_same_edition(self) -> None:
        assert (
            edition_at_least(
                Edition.ENTERPRISE_STARTER,
                current=Edition.ENTERPRISE_STARTER,
            )
            is True
        )


class TestEditionGateError:
    """EditionGateError exception properties."""

    def test_attributes(self) -> None:
        err = EditionGateError(
            Edition.ENTERPRISE_STARTER, Edition.OSS, "collaboration"
        )
        assert err.required == Edition.ENTERPRISE_STARTER
        assert err.current == Edition.OSS
        assert err.feature == "collaboration"
        assert "enterprise_starter" in str(err)
        assert "oss" in str(err)

    def test_is_exception(self) -> None:
        assert issubclass(EditionGateError, Exception)


class TestRequiresEditionDecorator:
    """@requires_edition decorator."""

    def test_passes_when_edition_met(self) -> None:
        @requires_edition(Edition.OSS)
        def my_func() -> str:
            return "ok"

        with patch("amprealize.edition.HAS_ENTERPRISE", False):
            assert my_func() == "ok"

    @patch(
        "amprealize.edition.HAS_ENTERPRISE", False,
    )
    def test_raises_when_edition_not_met(self) -> None:
        @requires_edition(Edition.ENTERPRISE_STARTER, feature="collab")
        def my_func() -> str:
            return "ok"

        with pytest.raises(EditionGateError) as exc_info:
            my_func()
        assert exc_info.value.feature == "collab"

    def test_preserves_function_name(self) -> None:
        @requires_edition(Edition.OSS)
        def named_function() -> None:
            pass

        assert named_function.__name__ == "named_function"


class TestRequiresCapabilityDecorator:
    """@requires_capability decorator."""

    @patch("amprealize.edition.HAS_ENTERPRISE", False)
    def test_oss_lacks_collaboration(self) -> None:
        @requires_capability("collaboration")
        def collab_fn() -> str:
            return "ok"

        with pytest.raises(EditionGateError):
            collab_fn()

    @patch("amprealize.edition.HAS_ENTERPRISE", True)
    @patch("amprealize.edition.resolve_tier", None)
    def test_starter_has_collaboration(self) -> None:
        @requires_capability("collaboration")
        def collab_fn() -> str:
            return "ok"

        assert collab_fn() == "ok"

    @patch("amprealize.edition.HAS_ENTERPRISE", True)
    @patch("amprealize.edition.resolve_tier", None)
    def test_starter_lacks_self_improving(self) -> None:
        @requires_capability("self_improving")
        def si_fn() -> str:
            return "ok"

        with pytest.raises(EditionGateError):
            si_fn()

    @patch("amprealize.edition.HAS_ENTERPRISE", True)
    @patch("amprealize.edition.resolve_tier", lambda: "premium")
    def test_premium_has_self_improving(self) -> None:
        @requires_capability("self_improving")
        def si_fn() -> str:
            return "ok"

        assert si_fn() == "ok"


# ---------------------------------------------------------------------------
# Tier Transitions  (GUIDEAI-767)
# ---------------------------------------------------------------------------


class TestTierTransition:
    """TierTransition dataclass and helpers."""

    def test_all_six_transitions_exist(self) -> None:
        assert len(_VALID_TRANSITIONS) == 6

    def test_oss_to_starter(self) -> None:
        t = get_transition(Edition.OSS, Edition.ENTERPRISE_STARTER)
        assert t is not None
        assert t.from_edition == Edition.OSS
        assert t.to_edition == Edition.ENTERPRISE_STARTER
        assert "orgs" in t.features_gained
        assert len(t.features_lost) == 0

    def test_starter_to_premium(self) -> None:
        t = get_transition(Edition.ENTERPRISE_STARTER, Edition.ENTERPRISE_PREMIUM)
        assert t is not None
        assert "sso" in t.features_gained
        assert "self_improving" in t.features_gained

    def test_premium_to_starter_features_lost(self) -> None:
        t = get_transition(Edition.ENTERPRISE_PREMIUM, Edition.ENTERPRISE_STARTER)
        assert t is not None
        assert "sso" in t.features_lost
        assert "self_improving" in t.features_lost
        assert t.data_preserved is True

    def test_same_edition_returns_none(self) -> None:
        assert get_transition(Edition.OSS, Edition.OSS) is None
        assert get_transition(Edition.ENTERPRISE_STARTER, Edition.ENTERPRISE_STARTER) is None

    def test_oss_to_premium_direct(self) -> None:
        t = get_transition(Edition.OSS, Edition.ENTERPRISE_PREMIUM)
        assert t is not None
        assert "self_improving" in t.features_gained

    def test_premium_to_oss_max_loss(self) -> None:
        t = get_transition(Edition.ENTERPRISE_PREMIUM, Edition.OSS)
        assert t is not None
        assert len(t.features_lost) > len(
            get_transition(Edition.ENTERPRISE_PREMIUM, Edition.ENTERPRISE_STARTER).features_lost  # type: ignore[union-attr]
        )


class TestValidateTransition:
    """validate_transition — warnings for downgrades."""

    def test_upgrade_no_warnings(self) -> None:
        warnings = validate_transition(Edition.OSS, Edition.ENTERPRISE_STARTER)
        assert warnings == []

    def test_same_edition_no_warnings(self) -> None:
        assert validate_transition(Edition.OSS, Edition.OSS) == []

    def test_downgrade_has_warnings(self) -> None:
        warnings = validate_transition(Edition.ENTERPRISE_PREMIUM, Edition.OSS)
        assert len(warnings) == 1
        assert "Downgrade" in warnings[0]
        assert "sso" in warnings[0]

    def test_starter_to_oss_warns(self) -> None:
        warnings = validate_transition(Edition.ENTERPRISE_STARTER, Edition.OSS)
        assert any("collaboration" in w for w in warnings)


# ---------------------------------------------------------------------------
# Module Edition Gating  (GUIDEAI-768 / GUIDEAI-769)
# ---------------------------------------------------------------------------


class TestCollaborationModule:
    """Collaboration module definition and gating."""

    def test_collaboration_in_registry(self) -> None:
        assert "collaboration" in MODULE_REGISTRY

    def test_collaboration_enterprise_only(self) -> None:
        mod = MODULE_REGISTRY["collaboration"]
        assert mod.enterprise_only is True

    def test_collaboration_min_edition_starter(self) -> None:
        mod = MODULE_REGISTRY["collaboration"]
        assert mod.min_edition == "enterprise_starter"

    def test_collaboration_depends_on_goals(self) -> None:
        mod = MODULE_REGISTRY["collaboration"]
        assert "goals" in mod.depends_on

    def test_collaboration_capability_flags(self) -> None:
        mod = MODULE_REGISTRY["collaboration"]
        assert "collaboration" in mod.capability_flags
        assert "conversations" in mod.capability_flags

    def test_collaboration_excluded_from_oss_modules(self) -> None:
        cfg = ModulesConfig(agents=True, behaviors=True, collaboration=True)
        enabled = get_enabled_modules(cfg)
        names = [m.name for m in enabled]
        assert "collaboration" not in names

    def test_collaboration_config_field(self) -> None:
        cfg = ModulesConfig(collaboration=True)
        assert cfg.collaboration is True
        cfg2 = ModulesConfig()
        assert cfg2.collaboration is False


class TestSelfImprovingPremiumGating:
    """Self-improving module requires Enterprise Premium."""

    def test_self_improving_min_edition_premium(self) -> None:
        mod = MODULE_REGISTRY["self_improving"]
        assert mod.min_edition == "enterprise_premium"

    def test_self_improving_enterprise_only(self) -> None:
        mod = MODULE_REGISTRY["self_improving"]
        assert mod.enterprise_only is True


class TestIsModuleEditionAllowed:
    """is_module_edition_allowed — check module vs current edition."""

    @patch("amprealize.edition.HAS_ENTERPRISE", False)
    def test_goals_always_allowed(self) -> None:
        assert is_module_edition_allowed("goals") is True

    @patch("amprealize.edition.HAS_ENTERPRISE", False)
    def test_agents_allowed_in_oss(self) -> None:
        assert is_module_edition_allowed("agents") is True

    @patch("amprealize.edition.HAS_ENTERPRISE", False)
    def test_collaboration_blocked_in_oss(self) -> None:
        assert is_module_edition_allowed("collaboration") is False

    @patch("amprealize.edition.HAS_ENTERPRISE", True)
    @patch("amprealize.edition.resolve_tier", None)
    def test_collaboration_allowed_in_starter(self) -> None:
        assert is_module_edition_allowed("collaboration") is True

    @patch("amprealize.edition.HAS_ENTERPRISE", False)
    def test_self_improving_blocked_in_oss(self) -> None:
        assert is_module_edition_allowed("self_improving") is False

    @patch("amprealize.edition.HAS_ENTERPRISE", True)
    @patch("amprealize.edition.resolve_tier", None)
    def test_self_improving_blocked_in_starter(self) -> None:
        assert is_module_edition_allowed("self_improving") is False

    @patch("amprealize.edition.HAS_ENTERPRISE", True)
    @patch("amprealize.edition.resolve_tier", lambda: "premium")
    def test_self_improving_allowed_in_premium(self) -> None:
        assert is_module_edition_allowed("self_improving") is True

    def test_unknown_module_allowed(self) -> None:
        assert is_module_edition_allowed("nonexistent_module") is True

    @patch("amprealize.edition.HAS_ENTERPRISE", True)
    @patch("amprealize.edition.resolve_tier", lambda: "premium")
    def test_collaboration_allowed_in_premium(self) -> None:
        assert is_module_edition_allowed("collaboration") is True


class TestModuleMinEditionField:
    """min_edition field on ModuleDefinition."""

    def test_default_none(self) -> None:
        mod = ModuleDefinition(
            name="test", display_name="Test", description="desc"
        )
        assert mod.min_edition is None

    def test_goals_no_min_edition(self) -> None:
        assert MODULE_REGISTRY["goals"].min_edition is None

    def test_agents_no_min_edition(self) -> None:
        assert MODULE_REGISTRY["agents"].min_edition is None

    def test_behaviors_no_min_edition(self) -> None:
        assert MODULE_REGISTRY["behaviors"].min_edition is None
