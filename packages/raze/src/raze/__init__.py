"""Raze - Structured logging with centralized storage and queryable APIs.

Raze replaces ad-hoc print() statements and basic logging calls with
structured, queryable logs backed by TimescaleDB hypertables.

Basic usage:
    from raze import RazeLogger

    logger = RazeLogger(service="my-service")
    logger.info("Hello world", user_id="123")

With TimescaleDB:
    from raze import RazeService
    from raze.sinks import TimescaleDBSink

    sink = TimescaleDBSink(dsn="postgresql://...")
    service = RazeService(sink=sink)
    logger = RazeLogger(service=service)
"""

from raze.models import (
    LogLevel,
    LogEvent,
    LogIngestRequest,
    LogIngestResponse,
    LogQueryRequest,
    LogQueryResponse,
    LogAggregateRequest,
    LogAggregateResponse,
    LogAggregation,
)
from raze.logger import RazeLogger, RazeLoggingHandler, install_raze_handler, get_logger
from raze.service import RazeService

__version__ = "0.1.0"
__all__ = [
    # Core logger
    "RazeLogger",
    "RazeLoggingHandler",
    "install_raze_handler",
    "get_logger",
    # Service for queries
    "RazeService",
    # Models
    "LogLevel",
    "LogEvent",
    "LogIngestRequest",
    "LogIngestResponse",
    "LogQueryRequest",
    "LogQueryResponse",
    "LogAggregateRequest",
    "LogAggregateResponse",
    "LogAggregation",
]
