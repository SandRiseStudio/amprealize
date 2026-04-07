"""Pydantic models for Raze structured logging.

This module defines the core data models for log events, queries, and responses.
All models include schema versioning for forward compatibility.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


class LogLevel(str, Enum):
    """Standard log levels with severity ordering."""

    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    @classmethod
    def from_string(cls, value: str) -> "LogLevel":
        """Parse log level from string, case-insensitive."""
        return cls(value.upper())

    def __ge__(self, other: "LogLevel") -> bool:
        order = list(LogLevel)
        return order.index(self) >= order.index(other)

    def __gt__(self, other: "LogLevel") -> bool:
        order = list(LogLevel)
        return order.index(self) > order.index(other)

    def __le__(self, other: "LogLevel") -> bool:
        order = list(LogLevel)
        return order.index(self) <= order.index(other)

    def __lt__(self, other: "LogLevel") -> bool:
        order = list(LogLevel)
        return order.index(self) < order.index(other)


# Current schema version for log events
SCHEMA_VERSION = "v1"


class LogEvent(BaseModel):
    """A structured log event with full context.

    This is the canonical representation of a log entry stored in the database
    and returned from queries. The schema_version field enables forward
    compatibility as the schema evolves.
    """

    log_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this log event",
    )
    schema_version: str = Field(
        default=SCHEMA_VERSION,
        description="Schema version for forward compatibility",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the log event occurred (UTC)",
    )
    level: LogLevel = Field(
        description="Log severity level",
    )
    service: str = Field(
        description="Name of the service/component that generated this log",
    )
    message: str = Field(
        description="Human-readable log message",
    )
    run_id: Optional[str] = Field(
        default=None,
        description="Associated execution run ID for correlation",
    )
    action_id: Optional[str] = Field(
        default=None,
        description="Associated action ID for correlation",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Associated session ID for correlation",
    )
    actor_surface: Optional[str] = Field(
        default=None,
        description="Surface that generated this log (api, cli, vscode, web)",
    )
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional structured context data",
    )

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, v: Any) -> datetime:
        """Parse timestamp from string or datetime."""
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            # Handle ISO format with Z suffix
            if v.endswith("Z"):
                v = v[:-1] + "+00:00"
            return datetime.fromisoformat(v)
        raise ValueError(f"Invalid timestamp: {v}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "log_id": self.log_id,
            "schema_version": self.schema_version,
            "timestamp": self.timestamp.isoformat().replace("+00:00", "Z"),
            "level": self.level.value,
            "service": self.service,
            "message": self.message,
            "run_id": self.run_id,
            "action_id": self.action_id,
            "session_id": self.session_id,
            "actor_surface": self.actor_surface,
            "context": self.context,
        }

    model_config = {"use_enum_values": False}


class LogEventInput(BaseModel):
    """Input model for creating a log event.

    This is used for ingestion endpoints where clients may not provide
    all fields (like log_id and timestamp which are auto-generated).
    """

    level: Union[LogLevel, str] = Field(
        default=LogLevel.INFO,
        description="Log severity level",
    )
    service: str = Field(
        description="Name of the service/component",
    )
    message: str = Field(
        description="Human-readable log message",
    )
    run_id: Optional[str] = Field(
        default=None,
        description="Associated execution run ID",
    )
    action_id: Optional[str] = Field(
        default=None,
        description="Associated action ID",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Associated session ID",
    )
    actor_surface: Optional[str] = Field(
        default=None,
        description="Surface that generated this log",
    )
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional structured context",
    )
    timestamp: Optional[datetime] = Field(
        default=None,
        description="Optional timestamp (defaults to now if not provided)",
    )

    @field_validator("level", mode="before")
    @classmethod
    def parse_level(cls, v: Any) -> LogLevel:
        """Parse log level from string or enum."""
        if isinstance(v, LogLevel):
            return v
        if isinstance(v, str):
            return LogLevel.from_string(v)
        raise ValueError(f"Invalid log level: {v}")

    def to_log_event(self) -> LogEvent:
        """Convert to a full LogEvent with generated fields."""
        return LogEvent(
            log_id=str(uuid.uuid4()),
            schema_version=SCHEMA_VERSION,
            timestamp=self.timestamp or datetime.now(timezone.utc),
            level=self.level if isinstance(self.level, LogLevel) else LogLevel.from_string(str(self.level)),
            service=self.service,
            message=self.message,
            run_id=self.run_id,
            action_id=self.action_id,
            session_id=self.session_id,
            actor_surface=self.actor_surface,
            context=self.context,
        )


class LogIngestRequest(BaseModel):
    """Request model for log ingestion endpoint.

    Supports both single log and batch ingestion for efficiency.
    """

    logs: List[LogEventInput] = Field(
        description="List of log events to ingest",
        min_length=1,
        max_length=10000,  # Prevent abuse
    )

    @classmethod
    def single(
        cls,
        level: Union[LogLevel, str],
        service: str,
        message: str,
        **kwargs: Any,
    ) -> "LogIngestRequest":
        """Create a request with a single log event."""
        return cls(
            logs=[
                LogEventInput(
                    level=level,
                    service=service,
                    message=message,
                    **kwargs,
                )
            ]
        )


class LogIngestResponse(BaseModel):
    """Response model for log ingestion endpoint."""

    ingested_count: int = Field(
        description="Number of logs successfully ingested",
    )
    log_ids: List[str] = Field(
        description="IDs of ingested logs",
    )
    errors: List[str] = Field(
        default_factory=list,
        description="Any errors encountered during ingestion",
    )


class LogQueryRequest(BaseModel):
    """Request model for querying logs."""

    start_time: datetime = Field(
        description="Start of time range (inclusive)",
    )
    end_time: datetime = Field(
        description="End of time range (inclusive)",
    )
    level: Optional[LogLevel] = Field(
        default=None,
        description="Filter by minimum log level",
    )
    levels: Optional[List[LogLevel]] = Field(
        default=None,
        description="Filter by specific log levels",
    )
    service: Optional[str] = Field(
        default=None,
        description="Filter by service name",
    )
    services: Optional[List[str]] = Field(
        default=None,
        description="Filter by multiple service names",
    )
    run_id: Optional[str] = Field(
        default=None,
        description="Filter by run ID",
    )
    action_id: Optional[str] = Field(
        default=None,
        description="Filter by action ID",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Filter by session ID",
    )
    actor_surface: Optional[str] = Field(
        default=None,
        description="Filter by actor surface",
    )
    search: Optional[str] = Field(
        default=None,
        description="Full-text search in message and context",
    )
    context_filters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="JSONB filters for context field",
    )
    limit: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="Maximum number of results",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Offset for pagination",
    )
    order: Literal["asc", "desc"] = Field(
        default="desc",
        description="Sort order by timestamp",
    )


class LogQueryResponse(BaseModel):
    """Response model for log queries."""

    logs: List[LogEvent] = Field(
        description="Matching log events",
    )
    total_count: int = Field(
        description="Total count of matching logs (before limit/offset)",
    )
    has_more: bool = Field(
        description="Whether more results are available",
    )
    query_time_ms: float = Field(
        description="Query execution time in milliseconds",
    )


class LogAggregation(BaseModel):
    """A single aggregation bucket."""

    group_key: Dict[str, str] = Field(
        description="Group-by field values",
    )
    count: int = Field(
        description="Number of logs in this bucket",
    )
    first_timestamp: datetime = Field(
        description="Earliest log timestamp in bucket",
    )
    last_timestamp: datetime = Field(
        description="Latest log timestamp in bucket",
    )


class LogAggregateRequest(BaseModel):
    """Request model for log aggregation."""

    start_time: datetime = Field(
        description="Start of time range",
    )
    end_time: datetime = Field(
        description="End of time range",
    )
    group_by: List[str] = Field(
        default_factory=lambda: ["level"],
        description="Fields to group by (level, service, actor_surface, run_id)",
    )
    level: Optional[LogLevel] = Field(
        default=None,
        description="Filter by minimum log level",
    )
    service: Optional[str] = Field(
        default=None,
        description="Filter by service name",
    )
    interval: Optional[str] = Field(
        default=None,
        description="Time bucket interval (1h, 1d, etc.) for time-series",
    )


class LogAggregateResponse(BaseModel):
    """Response model for log aggregation."""

    aggregations: List[LogAggregation] = Field(
        description="Aggregation buckets",
    )
    total_count: int = Field(
        description="Total logs in time range",
    )
    query_time_ms: float = Field(
        description="Query execution time in milliseconds",
    )
