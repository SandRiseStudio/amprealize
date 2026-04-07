"""Storage adapters for amprealize multi-tier architecture.

This package provides storage adapters for:
- PostgreSQL: Primary database with connection pooling
- SQLite: Local/OSS single-file database for offline use
- OpenSearch/Elasticsearch: Audit log indexing and search
- S3: WORM-compliant archive storage
- Redis: Caching layer

Storage Tier Hierarchy (per docs/contracts/AUDIT_LOG_STORAGE.md):
- Hot: PostgreSQL (7-day partition, full CRUD)
- Warm: OpenSearch (90-day retention, query-optimized)
- Cold: S3 WORM (7-year archive, immutable)

Use :func:`create_storage_pool` or :func:`amprealize.storage.factory.create_storage_pool`
to get a config-driven pool instance.
"""

# PostgreSQL - always available
from amprealize.storage.postgres_pool import PostgresPool

# SQLite - always available (stdlib)
from amprealize.storage.sqlite_pool import SQLitePool

# Storage factory
from amprealize.storage.factory import create_storage_pool

# OpenSearch - optional dependency
try:
    from amprealize.storage.opensearch_storage import (
        AuditEvent,
        AuditLogIndexer,
        AggregationResult,
        SearchResult,
        get_audit_indexer,
    )
    OPENSEARCH_AVAILABLE = True
except ImportError:
    OPENSEARCH_AVAILABLE = False
    AuditEvent = None  # type: ignore[assignment, misc]
    AuditLogIndexer = None  # type: ignore[assignment, misc]
    AggregationResult = None  # type: ignore[assignment, misc]
    SearchResult = None  # type: ignore[assignment, misc]
    get_audit_indexer = None  # type: ignore[assignment, misc]

# S3 - optional dependency
try:
    from amprealize.storage.s3_worm_storage import S3WORMStorage
    S3_AVAILABLE = True
except ImportError:
    S3_AVAILABLE = False
    S3WORMStorage = None  # type: ignore[assignment, misc]

__all__ = [
    # PostgreSQL
    "PostgresPool",
    # SQLite
    "SQLitePool",
    # Factory
    "create_storage_pool",
    # OpenSearch (optional)
    "OPENSEARCH_AVAILABLE",
    "AuditEvent",
    "AuditLogIndexer",
    "AggregationResult",
    "SearchResult",
    "get_audit_indexer",
    # S3 (optional)
    "S3_AVAILABLE",
    "S3WORMStorage",
]
