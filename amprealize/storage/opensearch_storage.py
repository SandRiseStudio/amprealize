"""OpenSearch/Elasticsearch adapter for audit log indexing and search.

This module provides real-time indexing of audit events into OpenSearch/Elasticsearch
for efficient querying, dashboards, and compliance reporting. Part of the multi-tier
storage architecture per docs/contracts/AUDIT_LOG_STORAGE.md.

Storage Tier Hierarchy:
- Hot: PostgreSQL (7-day partition, full CRUD)
- Warm: OpenSearch (90-day retention, query-optimized)
- Cold: S3 WORM (7-year archive, immutable)

Following behavior_align_storage_layers: Normalizes audit event schemas across tiers.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from opensearchpy import OpenSearch, helpers
from opensearchpy.exceptions import NotFoundError, RequestError

from amprealize.config.settings import OpenSearchConfig, get_settings

logger = logging.getLogger(__name__)


@dataclass
class AuditEvent:
    """Normalized audit event for indexing.

    Aligns with PostgreSQL audit_log_worm table schema and docs/contracts/AUDIT_LOG_STORAGE.md contract.
    """
    event_id: str
    event_type: str
    actor: str
    actor_type: str  # 'user', 'agent', 'system'
    surface: str  # 'cli', 'api', 'mcp', 'web'
    timestamp: datetime
    payload: dict[str, Any]
    run_id: Optional[str] = None
    action_id: Optional[str] = None
    behavior_id: Optional[str] = None
    compliance_status: Optional[str] = None  # 'approved', 'pending', 'rejected'
    signature: Optional[str] = None  # Ed25519 signature
    previous_hash: Optional[str] = None  # Hash chain link
    content_hash: Optional[str] = None  # SHA-256 of payload

    def to_document(self) -> dict[str, Any]:
        """Convert to OpenSearch document format."""
        doc = {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "actor": self.actor,
            "actor_type": self.actor_type,
            "surface": self.surface,
            "@timestamp": self.timestamp.isoformat(),
            "payload": self.payload,
        }

        # Add optional fields if present
        if self.run_id:
            doc["run_id"] = self.run_id
        if self.action_id:
            doc["action_id"] = self.action_id
        if self.behavior_id:
            doc["behavior_id"] = self.behavior_id
        if self.compliance_status:
            doc["compliance_status"] = self.compliance_status
        if self.signature:
            doc["signature"] = self.signature
        if self.previous_hash:
            doc["previous_hash"] = self.previous_hash
        if self.content_hash:
            doc["content_hash"] = self.content_hash

        return doc

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> AuditEvent:
        """Create from OpenSearch document."""
        return cls(
            event_id=doc["event_id"],
            event_type=doc["event_type"],
            actor=doc["actor"],
            actor_type=doc["actor_type"],
            surface=doc["surface"],
            timestamp=datetime.fromisoformat(doc["@timestamp"].replace("Z", "+00:00")),
            payload=doc.get("payload", {}),
            run_id=doc.get("run_id"),
            action_id=doc.get("action_id"),
            behavior_id=doc.get("behavior_id"),
            compliance_status=doc.get("compliance_status"),
            signature=doc.get("signature"),
            previous_hash=doc.get("previous_hash"),
            content_hash=doc.get("content_hash"),
        )


@dataclass
class SearchResult:
    """Search result with pagination info."""
    events: list[AuditEvent]
    total: int
    took_ms: int
    scroll_id: Optional[str] = None


@dataclass
class AggregationResult:
    """Aggregation result for analytics."""
    buckets: list[dict[str, Any]]
    total: int


class AuditLogIndexer:
    """OpenSearch/Elasticsearch indexer for audit logs.

    Provides:
    - Real-time event indexing
    - Bulk indexing for batch operations
    - Full-text search with filters
    - Aggregations for dashboards
    - Index lifecycle management (ILM)

    Usage:
        indexer = AuditLogIndexer.from_settings()
        await indexer.index_event(event)
        results = await indexer.search_events(query="login", actor="user@example.com")
    """

    def __init__(
        self,
        client: OpenSearch,
        index_prefix: str = "amprealize-audit",
        bulk_size: int = 500,
        ilm_warm_after_days: int = 7,
        ilm_delete_after_days: int = 90,
    ):
        self.client = client
        self.index_prefix = index_prefix
        self.bulk_size = bulk_size
        self.ilm_warm_after_days = ilm_warm_after_days
        self.ilm_delete_after_days = ilm_delete_after_days
        self._pending_bulk: list[dict[str, Any]] = []

    @classmethod
    def from_settings(cls, config: Optional[OpenSearchConfig] = None) -> AuditLogIndexer:
        """Create indexer from application settings."""
        if config is None:
            settings = get_settings()
            config = settings.opensearch

        # Build connection params
        hosts = [config.endpoint]

        client_kwargs: dict[str, Any] = {
            "hosts": hosts,
            "use_ssl": config.endpoint.startswith("https"),
            "verify_certs": True,
            "ssl_show_warn": False,
        }

        # Add authentication if configured
        if config.api_key:
            client_kwargs["api_key"] = config.api_key
        elif config.username and config.password:
            client_kwargs["http_auth"] = (config.username, config.password)

        client = OpenSearch(**client_kwargs)

        return cls(
            client=client,
            index_prefix=config.index_prefix,
            bulk_size=config.bulk_size,
            ilm_warm_after_days=config.ilm_warm_after_days,
            ilm_delete_after_days=config.ilm_delete_after_days,
        )

    def _get_write_index(self) -> str:
        """Get current write index name (date-based rollover)."""
        date_suffix = datetime.now(timezone.utc).strftime("%Y.%m")
        return f"{self.index_prefix}-{date_suffix}"

    def _get_index_pattern(self) -> str:
        """Get index pattern for searches across all indices."""
        return f"{self.index_prefix}-*"

    async def ensure_index_template(self) -> None:
        """Create or update index template with mappings and ILM policy.

        Sets up:
        - Field mappings for audit events
        - ILM policy for hot → warm → delete lifecycle
        - Index settings for optimal search performance
        """
        # Define ILM policy
        ilm_policy = {
            "policy": {
                "phases": {
                    "hot": {
                        "actions": {
                            "rollover": {
                                "max_size": "50gb",
                                "max_age": "7d",
                            }
                        }
                    },
                    "warm": {
                        "min_age": f"{self.ilm_warm_after_days}d",
                        "actions": {
                            "readonly": {},
                            "forcemerge": {"max_num_segments": 1},
                        }
                    },
                    "delete": {
                        "min_age": f"{self.ilm_delete_after_days}d",
                        "actions": {
                            "delete": {}
                        }
                    }
                }
            }
        }

        # Create ILM policy
        try:
            self.client.transport.perform_request(
                "PUT",
                f"/_plugins/_ism/policies/{self.index_prefix}-policy",
                body=ilm_policy,
            )
            logger.info(f"Created ILM policy: {self.index_prefix}-policy")
        except RequestError as e:
            if "version_conflict" not in str(e):
                logger.warning(f"Failed to create ILM policy: {e}")

        # Define index template
        template = {
            "index_patterns": [f"{self.index_prefix}-*"],
            "template": {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 1,
                    "refresh_interval": "5s",
                    "plugins.index_state_management.policy_id": f"{self.index_prefix}-policy",
                },
                "mappings": {
                    "properties": {
                        "event_id": {"type": "keyword"},
                        "event_type": {"type": "keyword"},
                        "actor": {"type": "keyword"},
                        "actor_type": {"type": "keyword"},
                        "surface": {"type": "keyword"},
                        "@timestamp": {"type": "date"},
                        "run_id": {"type": "keyword"},
                        "action_id": {"type": "keyword"},
                        "behavior_id": {"type": "keyword"},
                        "compliance_status": {"type": "keyword"},
                        "signature": {"type": "keyword", "index": False},
                        "previous_hash": {"type": "keyword"},
                        "content_hash": {"type": "keyword"},
                        "payload": {
                            "type": "object",
                            "enabled": True,
                            "properties": {
                                "message": {"type": "text"},
                                "details": {"type": "object", "enabled": False},
                            }
                        },
                    }
                }
            }
        }

        # Create index template
        try:
            self.client.indices.put_index_template(
                name=f"{self.index_prefix}-template",
                body=template,
            )
            logger.info(f"Created index template: {self.index_prefix}-template")
        except RequestError as e:
            logger.warning(f"Failed to create index template: {e}")

    def index_event(self, event: AuditEvent) -> str:
        """Index a single audit event immediately.

        Args:
            event: Audit event to index

        Returns:
            Document ID of indexed event
        """
        index = self._get_write_index()
        doc = event.to_document()

        # Compute content hash if not provided
        if not doc.get("content_hash"):
            payload_json = json.dumps(doc.get("payload", {}), sort_keys=True)
            doc["content_hash"] = hashlib.sha256(payload_json.encode()).hexdigest()

        result = self.client.index(
            index=index,
            id=event.event_id,
            body=doc,
            refresh="wait_for",  # Ensure immediately searchable
        )

        logger.debug(f"Indexed event {event.event_id} to {index}")
        return result["_id"]

    def queue_event(self, event: AuditEvent) -> None:
        """Queue event for bulk indexing.

        Events are batched and indexed when bulk_size is reached
        or flush_bulk() is called.

        Args:
            event: Audit event to queue
        """
        doc = event.to_document()

        # Compute content hash if not provided
        if not doc.get("content_hash"):
            payload_json = json.dumps(doc.get("payload", {}), sort_keys=True)
            doc["content_hash"] = hashlib.sha256(payload_json.encode()).hexdigest()

        self._pending_bulk.append({
            "_index": self._get_write_index(),
            "_id": event.event_id,
            "_source": doc,
        })

        if len(self._pending_bulk) >= self.bulk_size:
            self.flush_bulk()

    def flush_bulk(self) -> int:
        """Flush pending bulk operations.

        Returns:
            Number of documents indexed
        """
        if not self._pending_bulk:
            return 0

        success, failed = helpers.bulk(
            self.client,
            self._pending_bulk,
            raise_on_error=False,
        )

        if failed:
            logger.warning(f"Bulk indexing: {success} succeeded, {len(failed)} failed")
        else:
            logger.debug(f"Bulk indexed {success} events")

        count = len(self._pending_bulk)
        self._pending_bulk = []
        return count

    def search_events(
        self,
        query: Optional[str] = None,
        event_type: Optional[str] = None,
        actor: Optional[str] = None,
        actor_type: Optional[str] = None,
        surface: Optional[str] = None,
        run_id: Optional[str] = None,
        action_id: Optional[str] = None,
        behavior_id: Optional[str] = None,
        compliance_status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        size: int = 100,
        from_: int = 0,
        sort_field: str = "@timestamp",
        sort_order: str = "desc",
    ) -> SearchResult:
        """Search audit events with filters.

        Args:
            query: Full-text search query (searches payload.message)
            event_type: Filter by event type
            actor: Filter by actor
            actor_type: Filter by actor type ('user', 'agent', 'system')
            surface: Filter by surface ('cli', 'api', 'mcp', 'web')
            run_id: Filter by run ID
            action_id: Filter by action ID
            behavior_id: Filter by behavior ID
            compliance_status: Filter by compliance status
            start_time: Filter events after this time
            end_time: Filter events before this time
            size: Number of results to return
            from_: Offset for pagination
            sort_field: Field to sort by
            sort_order: Sort order ('asc' or 'desc')

        Returns:
            SearchResult with matching events and metadata
        """
        # Build query
        must_clauses: list[dict[str, Any]] = []
        filter_clauses: list[dict[str, Any]] = []

        # Full-text search
        if query:
            must_clauses.append({
                "multi_match": {
                    "query": query,
                    "fields": ["payload.message^2", "event_type", "actor"],
                    "type": "best_fields",
                    "fuzziness": "AUTO",
                }
            })

        # Term filters
        if event_type:
            filter_clauses.append({"term": {"event_type": event_type}})
        if actor:
            filter_clauses.append({"term": {"actor": actor}})
        if actor_type:
            filter_clauses.append({"term": {"actor_type": actor_type}})
        if surface:
            filter_clauses.append({"term": {"surface": surface}})
        if run_id:
            filter_clauses.append({"term": {"run_id": run_id}})
        if action_id:
            filter_clauses.append({"term": {"action_id": action_id}})
        if behavior_id:
            filter_clauses.append({"term": {"behavior_id": behavior_id}})
        if compliance_status:
            filter_clauses.append({"term": {"compliance_status": compliance_status}})

        # Time range filter
        if start_time or end_time:
            range_filter: dict[str, Any] = {"@timestamp": {}}
            if start_time:
                range_filter["@timestamp"]["gte"] = start_time.isoformat()
            if end_time:
                range_filter["@timestamp"]["lte"] = end_time.isoformat()
            filter_clauses.append({"range": range_filter})

        # Build final query
        search_body: dict[str, Any] = {
            "query": {
                "bool": {
                    "must": must_clauses if must_clauses else [{"match_all": {}}],
                    "filter": filter_clauses,
                }
            },
            "sort": [{sort_field: {"order": sort_order}}],
            "size": size,
            "from": from_,
        }

        # Execute search
        response = self.client.search(
            index=self._get_index_pattern(),
            body=search_body,
        )

        # Parse results
        events = [
            AuditEvent.from_document(hit["_source"])
            for hit in response["hits"]["hits"]
        ]

        return SearchResult(
            events=events,
            total=response["hits"]["total"]["value"],
            took_ms=response["took"],
        )

    def get_event(self, event_id: str) -> Optional[AuditEvent]:
        """Get a specific audit event by ID.

        Args:
            event_id: Event ID to retrieve

        Returns:
            AuditEvent if found, None otherwise
        """
        try:
            response = self.client.search(
                index=self._get_index_pattern(),
                body={
                    "query": {"term": {"event_id": event_id}},
                    "size": 1,
                },
            )

            if response["hits"]["hits"]:
                return AuditEvent.from_document(response["hits"]["hits"][0]["_source"])
            return None

        except NotFoundError:
            return None

    def aggregate_by_field(
        self,
        field: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        size: int = 20,
    ) -> AggregationResult:
        """Aggregate events by a field (for dashboards).

        Args:
            field: Field to aggregate by (e.g., 'event_type', 'actor', 'surface')
            start_time: Filter events after this time
            end_time: Filter events before this time
            size: Number of buckets to return

        Returns:
            AggregationResult with buckets
        """
        # Build time filter
        filter_clauses = []
        if start_time or end_time:
            range_filter: dict[str, Any] = {"@timestamp": {}}
            if start_time:
                range_filter["@timestamp"]["gte"] = start_time.isoformat()
            if end_time:
                range_filter["@timestamp"]["lte"] = end_time.isoformat()
            filter_clauses.append({"range": range_filter})

        search_body: dict[str, Any] = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": filter_clauses if filter_clauses else [{"match_all": {}}],
                }
            },
            "aggs": {
                "by_field": {
                    "terms": {
                        "field": field,
                        "size": size,
                    }
                }
            }
        }

        response = self.client.search(
            index=self._get_index_pattern(),
            body=search_body,
        )

        buckets = response["aggregations"]["by_field"]["buckets"]
        total = sum(b["doc_count"] for b in buckets)

        return AggregationResult(buckets=buckets, total=total)

    def get_timeline(
        self,
        interval: str = "1h",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        event_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Get event count timeline (for dashboards).

        Args:
            interval: Time bucket interval ('1m', '1h', '1d', etc.)
            start_time: Filter events after this time
            end_time: Filter events before this time
            event_type: Filter by event type

        Returns:
            List of time buckets with counts
        """
        filter_clauses = []

        if start_time or end_time:
            range_filter: dict[str, Any] = {"@timestamp": {}}
            if start_time:
                range_filter["@timestamp"]["gte"] = start_time.isoformat()
            if end_time:
                range_filter["@timestamp"]["lte"] = end_time.isoformat()
            filter_clauses.append({"range": range_filter})

        if event_type:
            filter_clauses.append({"term": {"event_type": event_type}})

        search_body: dict[str, Any] = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": filter_clauses if filter_clauses else [{"match_all": {}}],
                }
            },
            "aggs": {
                "timeline": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "fixed_interval": interval,
                    }
                }
            }
        }

        response = self.client.search(
            index=self._get_index_pattern(),
            body=search_body,
        )

        return response["aggregations"]["timeline"]["buckets"]

    def verify_hash_chain(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 10000,
    ) -> dict[str, Any]:
        """Verify hash chain integrity for audit events.

        Checks that previous_hash fields form a valid chain.
        Used by the verification Cloud Run job.

        Args:
            start_time: Start of verification window
            end_time: End of verification window
            limit: Maximum events to verify

        Returns:
            Verification result with status, gaps, and invalid links
        """
        # Search for events with hash chain data
        filter_clauses = [
            {"exists": {"field": "content_hash"}},
        ]

        if start_time or end_time:
            range_filter: dict[str, Any] = {"@timestamp": {}}
            if start_time:
                range_filter["@timestamp"]["gte"] = start_time.isoformat()
            if end_time:
                range_filter["@timestamp"]["lte"] = end_time.isoformat()
            filter_clauses.append({"range": range_filter})

        response = self.client.search(
            index=self._get_index_pattern(),
            body={
                "query": {"bool": {"filter": filter_clauses}},
                "sort": [{"@timestamp": {"order": "asc"}}],
                "size": limit,
                "_source": ["event_id", "content_hash", "previous_hash", "@timestamp"],
            },
        )

        events = response["hits"]["hits"]

        # Build hash index
        hash_index = {hit["_source"]["content_hash"]: hit["_source"]["event_id"] for hit in events}

        # Verify chain
        gaps = []
        invalid_links = []
        verified_count = 0

        for hit in events:
            source = hit["_source"]
            prev_hash = source.get("previous_hash")

            if prev_hash:
                if prev_hash not in hash_index:
                    # Previous hash not found - could be in PostgreSQL or gap
                    gaps.append({
                        "event_id": source["event_id"],
                        "missing_hash": prev_hash,
                        "timestamp": source["@timestamp"],
                    })
                else:
                    verified_count += 1
            else:
                # First event in chain (no previous_hash)
                verified_count += 1

        return {
            "status": "valid" if not gaps and not invalid_links else "degraded",
            "total_events": len(events),
            "verified_count": verified_count,
            "gaps": gaps,
            "invalid_links": invalid_links,
            "verification_time": datetime.now(timezone.utc).isoformat(),
        }

    def close(self) -> None:
        """Close the OpenSearch client connection."""
        self.flush_bulk()  # Ensure any pending events are indexed
        self.client.close()


# Convenience function for module-level access
def get_audit_indexer() -> AuditLogIndexer:
    """Get a configured AuditLogIndexer instance.

    Returns:
        AuditLogIndexer configured from application settings
    """
    return AuditLogIndexer.from_settings()
