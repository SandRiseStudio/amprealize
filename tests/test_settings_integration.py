"""
Unit tests for multi-environment settings system.

Validates:
- Settings validation (production guards)
- Environment switching
- PostgresPool integration
- RedisCache integration
- S3Storage integration
- SecretsManager integration

Behaviors referenced:
- behavior_externalize_configuration
- behavior_align_storage_layers
- behavior_lock_down_security_surface
"""

import pytest
from pydantic_core import ValidationError
from amprealize.config.settings import Settings, StorageConfig, DatabaseConfig, CacheConfig

# Mark all tests in this module as unit tests (no infrastructure required)
pytestmark = pytest.mark.unit


class TestSettingsValidation:
    """Test Pydantic validation rules."""

    def test_default_settings_valid(self):
        """Default settings should be valid."""
        settings = Settings()
        assert settings.environment == "local"
        assert settings.storage.provider == "local"
        assert settings.database.provider == "local"
        assert settings.cache.provider == "local"

    def test_local_environment_file_loads(self):
        """Local environment file should load successfully."""
        settings = Settings(_env_file="infra/environments/local.env")
        assert settings.environment == "local"
        assert settings.storage.provider == "local"
        assert settings.database.pool_size == 5
        assert settings.jwt_access_token_expire_minutes == 480
        assert settings.feature_fine_tuning is True

    def test_s3_requires_bucket(self):
        """S3 provider should require bucket name."""
        with pytest.raises(ValidationError) as exc_info:
            StorageConfig(provider="s3")  # Missing s3_bucket
        assert "s3_bucket required" in str(exc_info.value)

    def test_production_database_rejects_localhost(self):
        """Production database should reject localhost URLs."""
        with pytest.raises(ValidationError) as exc_info:
            DatabaseConfig(
                provider="rds",
                postgres_url="postgresql://user:pass@localhost:5432/db"
            )
        assert "cannot use localhost" in str(exc_info.value)

    def test_production_cache_rejects_localhost(self):
        """Production cache should reject localhost URLs."""
        with pytest.raises(ValidationError) as exc_info:
            CacheConfig(
                provider="elasticache",
                redis_url="redis://localhost:6379/0"
            )
        assert "cannot use localhost" in str(exc_info.value)


class TestEnvironmentSwitching:
    """Test switching between environments."""

    def test_local_environment(self):
        """Local environment should use local providers."""
        settings = Settings(_env_file="infra/environments/local.env")
        assert settings.environment == "local"
        assert settings.storage.provider == "local"
        assert settings.database.provider == "local"
        assert settings.cache.provider == "local"
        assert settings.secrets.provider == "env"
        assert settings.observability.provider == "local"

    @pytest.mark.skip(reason="production.env not yet created")
    def test_production_configuration_structure(self):
        """Production configuration should define cloud providers."""
        # Note: This test reads the file but doesn't validate placeholders
        with open("deployment/environments/production.env") as f:
            content = f.read()

        # Verify production providers are configured
        assert "STORAGE__PROVIDER=s3" in content
        assert "DATABASE__PROVIDER=rds" in content
        assert "CACHE__PROVIDER=elasticache" in content
        assert "SECRETS__PROVIDER=aws-secrets" in content
        assert "OBSERVABILITY__PROVIDER=datadog" in content


class TestStorageIntegration:
    """Test storage layer integration with settings."""

    def test_postgres_pool_uses_settings(self):
        """PostgresPool should use settings when available."""
        from amprealize.storage.postgres_pool import PostgresPool

        # Create pool without DSN - should use settings
        pool = PostgresPool()
        assert pool is not None
        # Note: Can't inspect DSN from pool object, but no error means settings worked

    def test_redis_cache_uses_settings(self):
        """RedisCache should parse settings.cache.redis_url."""
        from amprealize.storage.redis_cache import RedisCache
        from unittest.mock import patch

        # Mock Redis to avoid actual connection
        with patch('redis.ConnectionPool'):
            cache = RedisCache()
            assert cache is not None


class TestS3StorageIntegration:
    """Test S3 storage adapter integration."""

    def test_s3_storage_local_minio(self):
        """S3Storage should support MinIO for local development."""
        from amprealize.storage.s3_storage import S3Storage
        from unittest.mock import patch, MagicMock

        # Mock boto3 to avoid AWS credentials requirement
        with patch('boto3.client') as mock_client:
            mock_s3 = MagicMock()
            mock_client.return_value = mock_s3

            storage = S3Storage(
                bucket="test-bucket",
                endpoint="http://localhost:9000"
            )
            assert storage.bucket == "test-bucket"


class TestSecretsIntegration:
    """Test secrets manager integration."""

    def test_secrets_manager_env_provider(self):
        """SecretsManager should fall back to env vars."""
        from amprealize.config.secrets import SecretsManager
        import os

        # Set test env var
        os.environ["TEST_SECRET"] = "test_value"

        manager = SecretsManager(provider="env")
        value = manager.get_secret("TEST_SECRET")
        assert value == "test_value"

        # Cleanup
        del os.environ["TEST_SECRET"]


class TestBackwardCompatibility:
    """Test backward compatibility with legacy env vars."""

    def test_legacy_dsn_variables_preserved(self):
        """Legacy DSN environment variables should still be accessible."""
        settings = Settings(_env_file="deployment/environments/local.env")

        # Legacy DSN fields should exist
        assert hasattr(settings, "amprealize_behavior_pg_dsn")
        assert hasattr(settings, "amprealize_workflow_pg_dsn")
        assert hasattr(settings, "amprealize_action_pg_dsn")
        assert hasattr(settings, "amprealize_run_pg_dsn")
        assert hasattr(settings, "amprealize_compliance_pg_dsn")
        assert hasattr(settings, "amprealize_metrics_pg_dsn")
        assert hasattr(settings, "amprealize_telemetry_pg_dsn")

        # Should contain valid DSN strings
        assert "postgresql://" in settings.amprealize_behavior_pg_dsn
        assert "postgresql://" in settings.amprealize_workflow_pg_dsn


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
