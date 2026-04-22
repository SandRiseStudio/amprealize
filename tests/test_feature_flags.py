"""Tests for FeatureFlagService — T4.4.1 phased rollout feature flags.

Covers:
- FlagType enum
- FeatureFlag dataclass (to_dict / from_dict)
- _hash_bucket determinism and distribution
- FeatureFlagService.is_enabled (boolean, percentage, user_list)
- FeatureFlagService.list_flags / get_flag / set_flag / register_flag
- Default flag catalogue (migrated + E4 flags)
- Unknown flag returns False (fail-closed)
- Edge cases: no context, empty user_list, 0% and 100% rollout
"""

from __future__ import annotations

import pytest

from amprealize.feature_flags import (
    DEFAULT_FLAGS,
    FeatureFlag,
    FeatureFlagService,
    FlagType,
    _hash_bucket,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# FlagType enum
# ---------------------------------------------------------------------------

class TestFlagType:
    def test_values(self):
        assert FlagType.BOOLEAN.value == "boolean"
        assert FlagType.PERCENTAGE.value == "percentage"
        assert FlagType.USER_LIST.value == "user_list"

    def test_from_string(self):
        assert FlagType("boolean") is FlagType.BOOLEAN
        assert FlagType("percentage") is FlagType.PERCENTAGE
        assert FlagType("user_list") is FlagType.USER_LIST


# ---------------------------------------------------------------------------
# FeatureFlag dataclass
# ---------------------------------------------------------------------------

class TestFeatureFlag:
    def test_defaults(self):
        f = FeatureFlag(name="test.flag")
        assert f.flag_type == FlagType.BOOLEAN
        assert f.enabled is False
        assert f.percentage == 0
        assert f.user_list == []
        assert f.description == ""
        assert f.metadata == {}

    def test_to_dict(self):
        f = FeatureFlag(
            name="feature.x",
            flag_type=FlagType.PERCENTAGE,
            enabled=True,
            percentage=50,
            description="Half rollout",
            metadata={"key": "val"},
        )
        d = f.to_dict()
        assert d["name"] == "feature.x"
        assert d["flag_type"] == "percentage"
        assert d["enabled"] is True
        assert d["percentage"] == 50
        assert d["description"] == "Half rollout"
        assert d["metadata"] == {"key": "val"}

    def test_from_dict(self):
        d = {
            "name": "feature.y",
            "flag_type": "user_list",
            "enabled": True,
            "user_list": ["u1", "u2"],
            "description": "Allow list",
        }
        f = FeatureFlag.from_dict(d)
        assert f.name == "feature.y"
        assert f.flag_type == FlagType.USER_LIST
        assert f.enabled is True
        assert f.user_list == ["u1", "u2"]

    def test_from_dict_defaults(self):
        f = FeatureFlag.from_dict({"name": "minflags"})
        assert f.flag_type == FlagType.BOOLEAN
        assert f.enabled is False

    def test_roundtrip(self):
        original = FeatureFlag(
            name="feature.roundtrip",
            flag_type=FlagType.PERCENTAGE,
            enabled=True,
            percentage=77,
            user_list=["u1"],
            description="Test",
            metadata={"a": 1},
        )
        rebuilt = FeatureFlag.from_dict(original.to_dict())
        assert rebuilt.name == original.name
        assert rebuilt.flag_type == original.flag_type
        assert rebuilt.percentage == original.percentage
        assert rebuilt.user_list == original.user_list
        assert rebuilt.metadata == original.metadata


# ---------------------------------------------------------------------------
# _hash_bucket
# ---------------------------------------------------------------------------

class TestHashBucket:
    def test_deterministic(self):
        b1 = _hash_bucket("flag.a", "user-1")
        b2 = _hash_bucket("flag.a", "user-1")
        assert b1 == b2

    def test_range(self):
        for i in range(200):
            b = _hash_bucket("flag.range", f"user-{i}")
            assert 0 <= b < 100

    def test_different_flags_different_buckets(self):
        """Different flag names should often produce different buckets."""
        b1 = _hash_bucket("flag.alpha", "user-1")
        b2 = _hash_bucket("flag.beta", "user-1")
        # Not guaranteed to differ, but with SHA-256 collision is rare
        # We just verify both are valid
        assert 0 <= b1 < 100
        assert 0 <= b2 < 100

    def test_distribution(self):
        """Over many users, buckets should be roughly uniform."""
        buckets = [_hash_bucket("flag.dist", f"user-{i}") for i in range(1000)]
        # Each 10-bucket range should have at least some entries
        for lo in range(0, 100, 10):
            count = sum(1 for b in buckets if lo <= b < lo + 10)
            assert count > 0, f"No users in bucket range [{lo}, {lo+10})"


# ---------------------------------------------------------------------------
# FeatureFlagService — is_enabled (BOOLEAN)
# ---------------------------------------------------------------------------

class TestIsEnabledBoolean:
    def test_enabled_flag(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.on", enabled=True),
        ])
        assert svc.is_enabled("f.on") is True

    def test_disabled_flag(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.off", enabled=False),
        ])
        assert svc.is_enabled("f.off") is False

    def test_unknown_flag_returns_false(self):
        svc = FeatureFlagService(flags=[])
        assert svc.is_enabled("nonexistent") is False

    def test_context_ignored_for_boolean(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.bool", enabled=True),
        ])
        assert svc.is_enabled("f.bool", {"user_id": "u1"}) is True


# ---------------------------------------------------------------------------
# FeatureFlagService — is_enabled (PERCENTAGE)
# ---------------------------------------------------------------------------

class TestIsEnabledPercentage:
    def test_zero_percent(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.pct", flag_type=FlagType.PERCENTAGE, enabled=True, percentage=0),
        ])
        # No user should match at 0%
        for i in range(50):
            assert svc.is_enabled("f.pct", {"user_id": f"u-{i}"}) is False

    def test_hundred_percent(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.pct100", flag_type=FlagType.PERCENTAGE, enabled=True, percentage=100),
        ])
        # All users should match at 100%
        for i in range(50):
            assert svc.is_enabled("f.pct100", {"user_id": f"u-{i}"}) is True

    def test_fifty_percent_distribution(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.half", flag_type=FlagType.PERCENTAGE, enabled=True, percentage=50),
        ])
        on = sum(1 for i in range(1000) if svc.is_enabled("f.half", {"user_id": f"u-{i}"}))
        # Roughly 50% ± 10% tolerance
        assert 350 < on < 650, f"Expected ~500 enabled, got {on}"

    def test_disabled_percentage_always_false(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.off_pct", flag_type=FlagType.PERCENTAGE, enabled=False, percentage=100),
        ])
        assert svc.is_enabled("f.off_pct", {"user_id": "u1"}) is False

    def test_no_user_id_at_100(self):
        """Without user_id, percentage flag at 100% should return True."""
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.no_ctx", flag_type=FlagType.PERCENTAGE, enabled=True, percentage=100),
        ])
        assert svc.is_enabled("f.no_ctx") is True

    def test_no_user_id_below_100(self):
        """Without user_id, percentage flag below 100% returns False."""
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.no_ctx50", flag_type=FlagType.PERCENTAGE, enabled=True, percentage=50),
        ])
        assert svc.is_enabled("f.no_ctx50") is False

    def test_consistent_for_same_user(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.sticky", flag_type=FlagType.PERCENTAGE, enabled=True, percentage=50),
        ])
        r1 = svc.is_enabled("f.sticky", {"user_id": "sticky-user"})
        r2 = svc.is_enabled("f.sticky", {"user_id": "sticky-user"})
        assert r1 == r2


# ---------------------------------------------------------------------------
# FeatureFlagService — is_enabled (USER_LIST)
# ---------------------------------------------------------------------------

class TestIsEnabledUserList:
    def test_user_in_list(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.ul", flag_type=FlagType.USER_LIST, enabled=True, user_list=["alice", "bob"]),
        ])
        assert svc.is_enabled("f.ul", {"user_id": "alice"}) is True
        assert svc.is_enabled("f.ul", {"user_id": "bob"}) is True

    def test_user_not_in_list(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.ul", flag_type=FlagType.USER_LIST, enabled=True, user_list=["alice"]),
        ])
        assert svc.is_enabled("f.ul", {"user_id": "charlie"}) is False

    def test_disabled_user_list(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.ul_off", flag_type=FlagType.USER_LIST, enabled=False, user_list=["alice"]),
        ])
        assert svc.is_enabled("f.ul_off", {"user_id": "alice"}) is False

    def test_empty_user_list(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.ul_empty", flag_type=FlagType.USER_LIST, enabled=True, user_list=[]),
        ])
        assert svc.is_enabled("f.ul_empty", {"user_id": "anyone"}) is False

    def test_no_context(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.ul_noctx", flag_type=FlagType.USER_LIST, enabled=True, user_list=["alice"]),
        ])
        assert svc.is_enabled("f.ul_noctx") is False


# ---------------------------------------------------------------------------
# FeatureFlagService — list / get / set / register
# ---------------------------------------------------------------------------

class TestServiceCRUD:
    def test_list_flags_sorted(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="z.flag"),
            FeatureFlag(name="a.flag"),
            FeatureFlag(name="m.flag"),
        ])
        names = [f.name for f in svc.list_flags()]
        assert names == ["a.flag", "m.flag", "z.flag"]

    def test_list_flags_empty(self):
        svc = FeatureFlagService(flags=[])
        assert svc.list_flags() == []

    def test_get_existing_flag(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.get", description="test"),
        ])
        f = svc.get_flag("f.get")
        assert f is not None
        assert f.description == "test"

    def test_get_missing_flag(self):
        svc = FeatureFlagService(flags=[])
        assert svc.get_flag("missing") is None

    def test_set_existing_flag(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.set", enabled=False),
        ])
        updated = svc.set_flag("f.set", enabled=True)
        assert updated.enabled is True
        assert svc.is_enabled("f.set") is True

    def test_set_creates_new_flag(self):
        svc = FeatureFlagService(flags=[])
        f = svc.set_flag("f.new", enabled=True)
        assert f.name == "f.new"
        assert svc.is_enabled("f.new") is True

    def test_set_percentage_upgrades_type(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.upgrade"),
        ])
        f = svc.set_flag("f.upgrade", percentage=50, enabled=True)
        assert f.flag_type == FlagType.PERCENTAGE
        assert f.percentage == 50

    def test_set_user_list_upgrades_type(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.upul"),
        ])
        f = svc.set_flag("f.upul", user_list=["u1"], enabled=True)
        assert f.flag_type == FlagType.USER_LIST
        assert f.user_list == ["u1"]

    def test_set_clamps_percentage(self):
        svc = FeatureFlagService(flags=[])
        f = svc.set_flag("f.clamp", percentage=150)
        assert f.percentage == 100
        f2 = svc.set_flag("f.clamp2", percentage=-10)
        assert f2.percentage == 0

    def test_register_flag(self):
        svc = FeatureFlagService(flags=[])
        flag = FeatureFlag(name="f.reg", enabled=True, description="registered")
        svc.register_flag(flag)
        assert svc.get_flag("f.reg") is not None
        assert svc.is_enabled("f.reg") is True

    def test_register_replaces(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="f.rep", enabled=False),
        ])
        svc.register_flag(FeatureFlag(name="f.rep", enabled=True))
        assert svc.is_enabled("f.rep") is True


# ---------------------------------------------------------------------------
# Default flag catalogue
# ---------------------------------------------------------------------------

class TestDefaultCatalogue:
    def test_migrated_flags_present(self):
        svc = FeatureFlagService()
        assert svc.get_flag("feature.early_knowledge_alignment") is not None
        assert svc.get_flag("feature.embedding_v2_rollout") is not None
        assert svc.get_flag("feature.device_flow_auth") is not None

    def test_e4_flags_present(self):
        svc = FeatureFlagService()
        assert svc.get_flag("feature.auto_reflection") is not None
        assert svc.get_flag("feature.pack_generation") is not None
        assert svc.get_flag("feature.adaptive_bootstrap") is not None
        assert svc.get_flag("feature.quality_gates") is not None

    def test_default_count(self):
        assert len(DEFAULT_FLAGS) == 9

    def test_legacy_env_metadata(self):
        svc = FeatureFlagService()
        eka = svc.get_flag("feature.early_knowledge_alignment")
        assert eka is not None
        assert eka.metadata.get("legacy_env") == "AMPREALIZE_ENABLE_EARLY_RETRIEVAL"

    def test_e4_metadata(self):
        svc = FeatureFlagService()
        ar = svc.get_flag("feature.auto_reflection")
        assert ar is not None
        assert ar.metadata.get("epic") == "E4"


# ---------------------------------------------------------------------------
# Integration: agent_execution_loop replacement scenario
# ---------------------------------------------------------------------------

class TestIntegrationScenario:
    """Simulate the replacement of env-var flags in agent_execution_loop."""

    def test_early_retrieval_boolean_on(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="feature.early_knowledge_alignment", enabled=True),
        ])
        assert svc.is_enabled("feature.early_knowledge_alignment") is True

    def test_auto_reflection_toggled_on(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(name="feature.auto_reflection", enabled=False),
        ])
        assert svc.is_enabled("feature.auto_reflection") is False
        svc.set_flag("feature.auto_reflection", enabled=True)
        assert svc.is_enabled("feature.auto_reflection") is True

    def test_embedding_rollout_gradual(self):
        svc = FeatureFlagService(flags=[
            FeatureFlag(
                name="feature.embedding_v2_rollout",
                flag_type=FlagType.PERCENTAGE,
                enabled=True,
                percentage=10,
            ),
        ])
        # At 10%, only ~10% of users should get the new model
        on = sum(
            1 for i in range(1000)
            if svc.is_enabled("feature.embedding_v2_rollout", {"user_id": f"u-{i}"})
        )
        assert on < 200, f"Expected ~100 at 10%, got {on}"


# ---------------------------------------------------------------------------
# Runtime Postgres-backed overrides (feature_flag_runtime)
# ---------------------------------------------------------------------------


class TestRuntimeBooleanOverride:
    def setup_method(self) -> None:
        from amprealize.feature_flag_runtime import replace_overrides

        replace_overrides({})

    def teardown_method(self) -> None:
        from amprealize.feature_flag_runtime import replace_overrides

        replace_overrides({})

    def test_override_false_beats_registry_true(self) -> None:
        from amprealize.feature_flag_runtime import set_override

        svc = FeatureFlagService(
            flags=[FeatureFlag(name="feature.auto_reflection", enabled=True)],
        )
        set_override("feature.auto_reflection", False)
        assert svc.is_enabled("feature.auto_reflection") is False

    def test_override_true_beats_registry_false(self) -> None:
        from amprealize.feature_flag_runtime import set_override

        svc = FeatureFlagService(
            flags=[FeatureFlag(name="feature.auto_reflection", enabled=False)],
        )
        set_override("feature.auto_reflection", True)
        assert svc.is_enabled("feature.auto_reflection") is True
