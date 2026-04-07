"""
Multi-environment configuration abstraction for amprealize platform.

Supports local/staging/production environments with provider-agnostic configuration
for storage, database, cache, secrets, and observability. Follows 12-factor app
principles with environment-based configuration.

Behaviors referenced:
- behavior_externalize_configuration: All environment differences in .env files
- behavior_align_storage_layers: Provider abstraction for local/cloud switching
- behavior_lock_down_security_surface: Secrets abstraction layer
"""

import os
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Load .env file BEFORE any pydantic-settings classes are instantiated.
# This ensures nested configs (DatabaseConfig, CacheConfig, etc.) pick up
# environment variables from .env since they don't inherit env_file from parent.
# Search order: .env in cwd, then .env in project root (amprealize/)
_env_loaded = False
for _env_path in [Path(".env"), Path(__file__).parent.parent.parent / ".env"]:
    if _env_path.exists():
        load_dotenv(_env_path, override=False)  # Don't override existing env vars
        _env_loaded = True
        break


def _mirror_amprealize_to_amprealize_env() -> None:
    """Copy AMPREALIZE_* into AMPREALIZE_* when the legacy name is unset.

    New installs can standardize on AMPREALIZE_* while existing .env files and
    docs that use AMPREALIZE_* keep working without change.
    """
    prefix_new = "AMPREALIZE_"
    prefix_old = "AMPREALIZE_"
    for key, val in list(os.environ.items()):
        if not key.startswith(prefix_new):
            continue
        legacy = prefix_old + key[len(prefix_new) :]
        if legacy not in os.environ:
            os.environ[legacy] = val


class StorageConfig(BaseSettings):
    """Storage provider configuration (local filesystem or cloud object storage)."""

    provider: Literal["local", "s3", "gcs", "azure"] = "local"
    local_path: str = "./data"
    s3_endpoint: Optional[str] = None  # MinIO: http://localhost:9000, AWS: None
    s3_bucket: Optional[str] = None
    s3_region: str = "us-east-1"
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None

    model_config = SettingsConfigDict(
        env_prefix="STORAGE_",
        case_sensitive=False,
        extra="allow"
    )

    @field_validator("s3_bucket")
    @classmethod
    def validate_s3_bucket(cls, v: Optional[str], info) -> Optional[str]:
        """Validate S3 bucket required for cloud providers."""
        provider = info.data.get("provider")
        if provider in ("s3", "gcs", "azure") and not v:
            raise ValueError(f"s3_bucket required for provider={provider}")
        return v


class DatabaseConfig(BaseSettings):
    """Database provider configuration (local Postgres or managed RDS/Cloud SQL)."""

    provider: Literal["local", "rds", "cloud-sql", "azure-db"] = "local"
    postgres_url: str = Field(
        default="postgresql://amprealize:amprealize_dev@localhost:5432/amprealize",
        validation_alias="DATABASE_URL"
    )
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30

    model_config = SettingsConfigDict(
        env_prefix="DATABASE_",
        case_sensitive=False,
        extra="allow"
    )

    @field_validator("postgres_url")
    @classmethod
    def validate_production_url(cls, v: str, info) -> str:
        """Validate production database not using localhost."""
        provider = info.data.get("provider")
        if provider in ("rds", "cloud-sql", "azure-db") and "localhost" in v:
            raise ValueError(f"Production database ({provider}) cannot use localhost")
        return v


class CacheConfig(BaseSettings):
    """Cache provider configuration (local Redis or managed ElastiCache/Memorystore)."""

    provider: Literal["local", "elasticache", "memorystore", "azure-cache"] = "local"
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias="REDIS_URL"
    )

    model_config = SettingsConfigDict(
        env_prefix="CACHE_",
        case_sensitive=False,
        extra="allow"
    )

    @field_validator("redis_url")
    @classmethod
    def validate_production_url(cls, v: str, info) -> str:
        """Validate production cache not using localhost."""
        provider = info.data.get("provider")
        if provider in ("elasticache", "memorystore", "azure-cache") and "localhost" in v:
            raise ValueError(f"Production cache ({provider}) cannot use localhost")
        return v


class SecretsConfig(BaseSettings):
    """Secrets provider configuration (env vars or cloud secret manager)."""

    provider: Literal["env", "aws-secrets", "gcp-secret", "azure-vault"] = "env"
    secret_path_prefix: str = "amprealize"

    model_config = SettingsConfigDict(
        env_prefix="SECRETS_",
        case_sensitive=False,
        extra="allow"
    )


class CacheTTLConfig(BaseSettings):
    """Cache TTL configuration for explicit invalidation strategy.

    Implements longer TTLs with explicit invalidation on write operations.
    This reduces cache misses while ensuring data freshness through
    service-level invalidation hooks.

    Behaviors referenced:
    - behavior_use_raze_for_logging: Cache operations are logged
    - behavior_externalize_configuration: TTLs configurable via env vars
    """

    # Stable data TTLs (invalidated explicitly on write operations)
    # 30 minutes for approved behaviors - they rarely change
    behavior_approved_ttl: int = 1800
    behavior_list_ttl: int = 1800
    behavior_search_ttl: int = 1800

    # 30 minutes for workflow templates - stable after approval
    workflow_template_ttl: int = 1800
    workflow_list_ttl: int = 1800

    # 30 minutes for action history - append-only, safe to cache longer
    action_list_ttl: int = 1800
    action_get_ttl: int = 1800

    # 15 minutes for compliance checklists - moderately stable
    compliance_checklist_ttl: int = 900
    compliance_list_ttl: int = 900

    # Short TTLs for volatile data (not explicitly invalidated)
    # 30 seconds for metrics - frequently updated
    metrics_ttl: int = 30

    # 60 seconds for negative cache (e.g., "not found" results)
    negative_cache_ttl: int = 60

    # Retrieval embeddings cache - stable, can be long
    embedding_ttl: int = 3600  # 1 hour

    model_config = SettingsConfigDict(
        env_prefix="CACHE_TTL_",
        case_sensitive=False,
        extra="allow"
    )


class AuditStorageConfig(BaseSettings):
    """Audit log WORM storage configuration (S3 Object Lock for compliance).

    Implements SOC2/GDPR compliant immutable audit log storage:
    - Hot tier: PostgreSQL for 30-day queryable events
    - Cold tier: S3 with Object Lock COMPLIANCE mode for 7-year retention
    - Glacier transition: After 1095 days (3 years) for cost optimization

    Behaviors referenced:
    - behavior_align_storage_layers: Multi-tier audit storage architecture
    - behavior_lock_down_security_surface: WORM storage for tamper-proof logs
    """

    # S3/MinIO bucket for audit log archival (must have Object Lock enabled)
    audit_bucket: Optional[str] = None

    # S3 endpoint (MinIO: http://localhost:9000, AWS: None for default)
    audit_endpoint: Optional[str] = None

    # Object Lock mode: COMPLIANCE (cannot be overridden) or GOVERNANCE (admin override)
    object_lock_mode: Literal["COMPLIANCE", "GOVERNANCE"] = "COMPLIANCE"

    # Object Lock retention period in days (default: 7 years = 2555 days per SOC2)
    retention_days: int = 2555

    # Days until transition to Glacier for cost optimization (default: 3 years)
    glacier_transition_days: int = 1095

    # PostgreSQL hot storage retention in days (default: 30 days)
    hot_storage_retention_days: int = 30

    # Ed25519 signing key path (relative to data dir or absolute)
    signing_key_path: str = "./data/audit/signing_key.pem"

    # Batch size for S3 archival (events per archive file)
    batch_size: int = 1000

    # Enable hash chain for tamper detection
    hash_chain_enabled: bool = True

    model_config = SettingsConfigDict(
        env_prefix="AUDIT_",
        case_sensitive=False,
        extra="allow"
    )

    @field_validator("audit_bucket")
    @classmethod
    def validate_audit_bucket(cls, v: Optional[str], info) -> Optional[str]:
        """Warn if audit bucket not configured (required for production)."""
        # Allow None for local development without S3
        return v

    @field_validator("retention_days")
    @classmethod
    def validate_retention_days(cls, v: int, info) -> int:
        """Validate minimum retention period for compliance."""
        if v < 365:
            raise ValueError(
                "retention_days must be >= 365 days for SOC2/GDPR compliance"
            )
        return v


class LLMConfig(BaseSettings):
    """LLM provider configuration for Behavior-Conditioned Inference (BCI).

    Supports OpenAI models with configurable per-request token budgets.
    Follows behavior_externalize_configuration for all credentials.
    """

    # Provider selection (currently OpenAI-focused, extensible to others)
    provider: Literal["openai", "anthropic", "openrouter", "ollama", "together", "groq", "fireworks", "test"] = "openai"

    # API credentials (loaded from env)
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    organization_id: Optional[str] = None

    # Model selection - comprehensive OpenAI model support
    model: str = "gpt-4o"

    # Token budgeting (per-request limits)
    max_tokens: int = 4096  # Max output tokens per request
    max_input_tokens: int = 128000  # Max input context (model dependent)
    token_budget_enabled: bool = True  # Enable per-request token budget enforcement
    token_budget_per_request: int = 50000  # Total token budget (input + output) per request
    token_budget_warning_threshold: float = 0.8  # Warn when budget usage exceeds this percentage

    # Generation parameters
    temperature: float = 0.7
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0

    # Request handling
    timeout: float = 120.0  # Seconds
    max_retries: int = 3
    retry_delay: float = 1.0  # Initial retry delay (exponential backoff)

    # Fallback behavior
    fallback_to_test_provider: bool = False  # Fall back to TestProvider if API fails

    model_config = SettingsConfigDict(
        # Reads AMPREALIZE_LLM_*; set AMPREALIZE_LLM_* in .env and it is mirrored at startup.
        env_prefix="AMPREALIZE_LLM_",
        case_sensitive=False,
        extra="allow"
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def resolve_api_key(cls, v: Optional[str]) -> Optional[str]:
        """Resolve API key from provider-specific env vars if not set."""
        if v:
            return v
        import os
        # Try OPENAI_API_KEY as fallback for OpenAI provider
        return os.environ.get("OPENAI_API_KEY")

    @field_validator("token_budget_per_request")
    @classmethod
    def validate_token_budget(cls, v: int, info) -> int:
        """Validate token budget is reasonable."""
        if v < 100:
            raise ValueError("token_budget_per_request must be >= 100 tokens")
        if v > 1000000:
            raise ValueError("token_budget_per_request must be <= 1,000,000 tokens")
        return v


# OpenAI Model Catalog with context limits and pricing (USD per 1M tokens)
# Pricing as of January 2025: https://openai.com/pricing
OPENAI_MODELS = {
    # GPT-4o series (flagship multimodal)
    "gpt-4o": {"max_context": 128000, "max_output": 16384, "input_price": 2.50, "output_price": 10.00, "description": "Most capable GPT-4o model"},
    "gpt-4o-2024-11-20": {"max_context": 128000, "max_output": 16384, "input_price": 2.50, "output_price": 10.00, "description": "GPT-4o November 2024"},
    "gpt-4o-2024-08-06": {"max_context": 128000, "max_output": 16384, "input_price": 2.50, "output_price": 10.00, "description": "GPT-4o August 2024"},
    "gpt-4o-2024-05-13": {"max_context": 128000, "max_output": 4096, "input_price": 5.00, "output_price": 15.00, "description": "GPT-4o May 2024"},
    "gpt-4o-mini": {"max_context": 128000, "max_output": 16384, "input_price": 0.15, "output_price": 0.60, "description": "Fast, affordable GPT-4o"},
    "gpt-4o-mini-2024-07-18": {"max_context": 128000, "max_output": 16384, "input_price": 0.15, "output_price": 0.60, "description": "GPT-4o mini July 2024"},

    # o1 reasoning models (higher pricing for reasoning tokens)
    "o1": {"max_context": 200000, "max_output": 100000, "input_price": 15.00, "output_price": 60.00, "description": "Advanced reasoning model"},
    "o1-2024-12-17": {"max_context": 200000, "max_output": 100000, "input_price": 15.00, "output_price": 60.00, "description": "o1 December 2024"},
    "o1-preview": {"max_context": 128000, "max_output": 32768, "input_price": 15.00, "output_price": 60.00, "description": "o1 preview model"},
    "o1-preview-2024-09-12": {"max_context": 128000, "max_output": 32768, "input_price": 15.00, "output_price": 60.00, "description": "o1 preview September 2024"},
    "o1-mini": {"max_context": 128000, "max_output": 65536, "input_price": 3.00, "output_price": 12.00, "description": "Fast o1 reasoning model"},
    "o1-mini-2024-09-12": {"max_context": 128000, "max_output": 65536, "input_price": 3.00, "output_price": 12.00, "description": "o1 mini September 2024"},

    # o3-mini reasoning model
    "o3-mini": {"max_context": 200000, "max_output": 100000, "input_price": 1.10, "output_price": 4.40, "description": "Newest small reasoning model"},
    "o3-mini-2025-01-31": {"max_context": 200000, "max_output": 100000, "input_price": 1.10, "output_price": 4.40, "description": "o3-mini January 2025"},

    # GPT-4 Turbo
    "gpt-4-turbo": {"max_context": 128000, "max_output": 4096, "input_price": 10.00, "output_price": 30.00, "description": "GPT-4 Turbo with vision"},
    "gpt-4-turbo-2024-04-09": {"max_context": 128000, "max_output": 4096, "input_price": 10.00, "output_price": 30.00, "description": "GPT-4 Turbo April 2024"},
    "gpt-4-turbo-preview": {"max_context": 128000, "max_output": 4096, "input_price": 10.00, "output_price": 30.00, "description": "GPT-4 Turbo preview"},
    "gpt-4-0125-preview": {"max_context": 128000, "max_output": 4096, "input_price": 10.00, "output_price": 30.00, "description": "GPT-4 Turbo January 2024"},
    "gpt-4-1106-preview": {"max_context": 128000, "max_output": 4096, "input_price": 10.00, "output_price": 30.00, "description": "GPT-4 Turbo November 2023"},

    # GPT-4 original
    "gpt-4": {"max_context": 8192, "max_output": 8192, "input_price": 30.00, "output_price": 60.00, "description": "Original GPT-4"},
    "gpt-4-0613": {"max_context": 8192, "max_output": 8192, "input_price": 30.00, "output_price": 60.00, "description": "GPT-4 June 2023"},
    "gpt-4-32k": {"max_context": 32768, "max_output": 32768, "input_price": 60.00, "output_price": 120.00, "description": "GPT-4 32k context"},
    "gpt-4-32k-0613": {"max_context": 32768, "max_output": 32768, "input_price": 60.00, "output_price": 120.00, "description": "GPT-4 32k June 2023"},

    # GPT-3.5 Turbo
    "gpt-3.5-turbo": {"max_context": 16385, "max_output": 4096, "input_price": 0.50, "output_price": 1.50, "description": "GPT-3.5 Turbo"},
    "gpt-3.5-turbo-0125": {"max_context": 16385, "max_output": 4096, "input_price": 0.50, "output_price": 1.50, "description": "GPT-3.5 Turbo January 2024"},
    "gpt-3.5-turbo-1106": {"max_context": 16385, "max_output": 4096, "input_price": 1.00, "output_price": 2.00, "description": "GPT-3.5 Turbo November 2023"},
    "gpt-3.5-turbo-16k": {"max_context": 16385, "max_output": 4096, "input_price": 3.00, "output_price": 4.00, "description": "GPT-3.5 Turbo 16k"},
}


class ObservabilityConfig(BaseSettings):
    """Observability provider configuration (local Prometheus/Grafana or cloud)."""

    provider: Literal["local", "datadog", "cloudwatch", "stackdriver"] = "local"
    prometheus_enabled: bool = True
    grafana_enabled: bool = True
    datadog_api_key: Optional[str] = None
    cloudwatch_log_group: Optional[str] = None

    model_config = SettingsConfigDict(
        env_prefix="OBSERVABILITY_",
        case_sensitive=False,
        extra="allow"
    )

    @field_validator("datadog_api_key")
    @classmethod
    def validate_datadog_key(cls, v: Optional[str], info) -> Optional[str]:
        """Validate Datadog API key required when provider=datadog."""
        provider = info.data.get("provider")
        if provider == "datadog" and not v:
            raise ValueError("datadog_api_key required for provider=datadog")
        return v


class OpenSearchConfig(BaseSettings):
    """OpenSearch/Elasticsearch configuration for audit log search and analytics.

    Supports both AWS OpenSearch Service and self-hosted Elasticsearch clusters.
    Implements real-time indexing for compliance audit queries.

    Behaviors referenced:
    - behavior_align_storage_layers: Search index tier for audit logs
    - behavior_lock_down_security_surface: Secure cluster connections
    - behavior_externalize_configuration: Environment-based configuration
    """

    # OpenSearch/Elasticsearch endpoint URL
    endpoint: Optional[str] = None

    # Index name prefix for audit logs
    index_prefix: str = "amprealize-audit"

    # Authentication
    use_aws_auth: bool = False  # Use AWS IAM for OpenSearch Service
    username: Optional[str] = None
    password: Optional[str] = None
    api_key: Optional[str] = None  # Elastic Cloud API key

    # Connection settings
    timeout: int = 30
    max_retries: int = 3
    verify_ssl: bool = True
    ca_certs: Optional[str] = None  # Path to CA certificate bundle

    # Index settings
    number_of_shards: int = 2
    number_of_replicas: int = 1
    refresh_interval: str = "1s"  # Index refresh interval

    # Bulk indexing settings
    bulk_size: int = 500
    bulk_timeout: str = "30s"

    # Index lifecycle management
    ilm_enabled: bool = True
    hot_phase_days: int = 7
    warm_phase_days: int = 30
    cold_phase_days: int = 90
    delete_phase_days: int = 365  # Auto-delete from search index (WORM retained)

    # Query settings
    max_results: int = 10000
    scroll_timeout: str = "5m"

    model_config = SettingsConfigDict(
        env_prefix="OPENSEARCH_",
        case_sensitive=False,
        extra="allow"
    )


class CostOptimizationConfig(BaseSettings):
    """Cost optimization and budget alert configuration.

    Configurable thresholds for cost monitoring and alerting:
    - Daily budget threshold for spend alerts
    - Token usage spike detection (hour-over-hour)
    - Cost anomaly detection (standard deviations from mean)

    Behaviors referenced:
    - behavior_validate_financial_impact: Budget tracking and ROI analysis
    - behavior_instrument_metrics_pipeline: Cost telemetry integration
    """

    # Daily budget threshold in USD (alert when exceeded)
    daily_budget_usd: float = 80.0

    # Token usage spike threshold (percentage increase hour-over-hour)
    token_spike_threshold_pct: float = 20.0

    # Cost anomaly detection (number of standard deviations above 7-day mean)
    cost_anomaly_sigma: float = 2.0

    # Alert cooldown period in minutes (avoid alert fatigue)
    alert_cooldown_minutes: int = 60

    # Cost per 1K input tokens (USD) - default GPT-4o pricing
    default_cost_per_1k_input: float = 0.0025

    # Cost per 1K output tokens (USD) - default GPT-4o pricing
    default_cost_per_1k_output: float = 0.01

    # Enable cost tracking
    cost_tracking_enabled: bool = True

    # Enable budget alerts
    budget_alerts_enabled: bool = True

    # Slack/Teams webhook for cost alerts (optional)
    alert_webhook_url: Optional[str] = None

    # Email recipients for cost alerts (comma-separated)
    alert_email_recipients: Optional[str] = None

    # SMTP configuration for email alerts
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_from_address: str = "alerts@amprealize.local"
    smtp_from_name: str = "Amprealize Cost Alerts"

    # Alert preferences URL for unsubscribe/manage links
    alert_preferences_url: str = "http://localhost:8080/settings/alerts"

    model_config = SettingsConfigDict(
        env_prefix="COST_",
        case_sensitive=False,
        extra="allow"
    )


class MessagingRetentionConfig(BaseSettings):
    """Message retention policy configuration (AMPREALIZE-567, Phase 8).

    Tiered retention:
      Active  (0 – archive_days):          Postgres hot storage, full API access
      Archive (archive_days – cold_days):  Postgres warm storage, read-only
      Cold    (cold_days+, enterprise):    S3/GCS export + delete from Postgres
    """

    # Days before messages are moved to archive phase (default: 90 days)
    archive_after_days: int = 90
    # Days before archived conversations are exported to cold storage (default: 365)
    cold_after_days: int = 365
    # Whether cold export is enabled (enterprise only)
    cold_export_enabled: bool = False
    # S3 key prefix for cold exports (e.g. "conversations/cold/")
    cold_export_prefix: str = "conversations/cold/"
    # Cron schedule for nightly archive job (UTC) — seconds between runs
    archive_job_interval_seconds: int = 86400  # 24 hours
    # Seconds between cold export job runs
    cold_export_job_interval_seconds: int = 604800  # 7 days
    # Maximum conversations to process per archive run (prevents long-running locks)
    archive_batch_size: int = 500
    # Maximum conversations to export per cold run
    cold_export_batch_size: int = 100

    model_config = SettingsConfigDict(
        env_prefix="MESSAGING_RETENTION_",
        case_sensitive=False,
        extra="allow",
    )

    def is_cold_export_configured(self, storage_bucket: Optional[str]) -> bool:
        return self.cold_export_enabled and bool(storage_bucket)


class SlackConfig(BaseSettings):
    """Slack integration configuration for the conversation bridge.

    Requires a Slack app with:
    - Bot Token Scopes: chat:write, reactions:write, channels:read, users:read
    - Event Subscriptions: message.channels, reaction_added, reaction_removed
    - Slash Commands: /amprealize
    """

    # Bot OAuth token (xoxb-...)
    bot_token: Optional[str] = None

    # Signing secret for verifying webhook requests
    signing_secret: Optional[str] = None

    # App-level token for Socket Mode (optional, for development)
    app_token: Optional[str] = None

    # Default bot display name (overridden per-agent)
    default_bot_name: str = "Amprealize"

    # Default bot icon emoji (overridden per-agent)
    default_bot_icon: str = ":robot_face:"

    model_config = SettingsConfigDict(
        env_prefix="SLACK_",
        case_sensitive=False,
        extra="allow"
    )

    def is_configured(self) -> bool:
        """Check if Slack integration has required credentials."""
        return bool(self.bot_token and self.signing_secret)


class Settings(BaseSettings):
    """Unified application settings with nested provider configurations."""

    # Environment
    environment: Literal["local", "staging", "production"] = "local"
    deploy_version: str = "dev"

    # Nested provider configurations
    storage: StorageConfig = Field(default_factory=StorageConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    cache_ttl: CacheTTLConfig = Field(default_factory=CacheTTLConfig)
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    audit: AuditStorageConfig = Field(default_factory=AuditStorageConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    cost: CostOptimizationConfig = Field(default_factory=CostOptimizationConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    opensearch: OpenSearchConfig = Field(default_factory=OpenSearchConfig)
    messaging_retention: MessagingRetentionConfig = Field(default_factory=MessagingRetentionConfig)

    # Legacy database DSN strings (backward compatibility)
    # These all use the consolidated amprealize-db on port 5432 with schema-based routing
    # Credentials: amprealize:amprealize_dev (matching BreakerAmp default blueprint)
    amprealize_behavior_pg_dsn: str = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize?options=-csearch_path%3Dbehavior"
    amprealize_workflow_pg_dsn: str = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize?options=-csearch_path%3Dworkflow"
    amprealize_action_pg_dsn: str = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize?options=-csearch_path%3Dexecution"
    amprealize_run_pg_dsn: str = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize?options=-csearch_path%3Dexecution"
    amprealize_compliance_pg_dsn: str = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize?options=-csearch_path%3Dcompliance"
    amprealize_metrics_pg_dsn: str = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize?options=-csearch_path%3Dmetrics"
    amprealize_telemetry_pg_dsn: str = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize?options=-csearch_path%3Dtelemetry"

    # API Service
    api_host: str = "0.0.0.0"
    api_port: int = 8000  # Internal API port (gateway proxies 8080 -> 8000)
    api_workers: int = 1
    api_log_level: str = "info"
    api_reload: bool = False
    # Gateway URL - all clients should connect via gateway for auth/rate-limiting
    gateway_url: str = "http://localhost:8080"

    # CORS
    cors_origins: str = "http://localhost:3000"
    cors_allow_credentials: bool = True

    # MCP Server
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 3000
    mcp_log_level: str = "info"
    mcp_transport: str = "stdio"

    # Authentication & Security
    jwt_secret_key: str = "dev-jwt-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 7

    # Device Flow OAuth
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    oauth_device_code_url: str = "https://github.com/login/device/code"
    oauth_token_url: str = "https://github.com/login/oauth/access_token"
    oauth_user_url: str = "https://api.github.com/user"

    # Session Management
    session_secret: str = "dev-session-secret-change-in-production"
    session_cookie_secure: bool = False
    session_cookie_httponly: bool = True
    session_cookie_samesite: str = "lax"

    # Embedding configuration (for BCI behavior retrieval)
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_rollout_percentage: int = 100

    # LLM generation settings (shorthand for common overrides)
    llm_provider: str = "openai"  # Override via AMPREALIZE_LLM_PROVIDER or AMPREALIZE_LLM_PROVIDER
    llm_model: str = "gpt-4o"  # Override via AMPREALIZE_LLM_MODEL or AMPREALIZE_LLM_MODEL
    llm_token_budget: int = 50000  # Per-request token budget

    # Feature Flags
    feature_multi_tenant: bool = False
    feature_fine_tuning: bool = False
    feature_advanced_retrieval: bool = False
    feature_collaboration: bool = False
    feature_trace_analysis: bool = False

    # Telemetry & Analytics
    telemetry_enabled: bool = True
    telemetry_export_path: str = "./data/telemetry"
    analytics_warehouse_path: str = "./data/analytics.duckdb"

    # Rate Limiting
    rate_limit_device_flow: str = "100/min"
    rate_limit_api: str = "1000/min"
    rate_limit_mcp: str = "1000/min"

    # Logging
    log_level: str = "info"
    log_format: str = "json"
    log_file: str = "./logs/amprealize.log"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_nested_delimiter="__",  # Allows STORAGE__PROVIDER=s3 syntax
        extra="allow"  # Allow additional fields from environment
    )


# Singleton instance loaded from environment
_mirror_amprealize_to_amprealize_env()
settings = Settings()


def get_settings() -> Settings:
    """Get the global settings singleton.

    Returns the module-level Settings instance that was loaded from environment
    variables and .env file at import time.

    Usage:
        from amprealize.config.settings import get_settings
        config = get_settings()
        print(config.opensearch.endpoint)
    """
    return settings
