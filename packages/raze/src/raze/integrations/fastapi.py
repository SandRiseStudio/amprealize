"""FastAPI integration for Raze structured logging.

Provides:
- RazeMiddleware: Automatic request/response logging with correlation IDs
- create_log_routes: Factory function to create /v1/logs/* endpoints
- RazeLifespan: Context manager for startup/shutdown integration
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Callable, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..models import (
    LogAggregateRequest,
    LogAggregateResponse,
    LogEvent,
    LogIngestRequest,
    LogIngestResponse,
    LogLevel,
    LogQueryRequest,
    LogQueryResponse,
)
from ..service import RazeService

__all__ = [
    "RazeMiddleware",
    "create_log_routes",
    "RazeLifespan",
]


class RazeMiddleware(BaseHTTPMiddleware):
    """Middleware that logs requests/responses and attaches correlation IDs.

    Automatically logs:
    - Request start (method, path, headers)
    - Request completion (status code, duration)
    - Request errors (exceptions)

    Attaches X-Request-ID header to responses for correlation.
    """

    def __init__(
        self,
        app: FastAPI,
        service: RazeService,
        *,
        service_name: str = "api",
        log_request_body: bool = False,
        log_response_body: bool = False,
        exclude_paths: Optional[set[str]] = None,
    ) -> None:
        """Initialize the middleware.

        Args:
            app: FastAPI application instance
            service: RazeService instance for logging
            service_name: Service name to use in log events
            log_request_body: Whether to include request body in logs
            log_response_body: Whether to include response body in logs
            exclude_paths: Paths to exclude from logging (e.g., /health, /metrics)
        """
        super().__init__(app)
        self.service = service
        self.service_name = service_name
        self.log_request_body = log_request_body
        self.log_response_body = log_response_body
        self.exclude_paths = exclude_paths or {"/health", "/metrics", "/v1/logs/ingest"}

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        """Process the request with logging."""
        # Skip excluded paths
        if request.url.path in self.exclude_paths:
            return await call_next(request)

        # Generate or extract request ID
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        run_id = request.headers.get("X-Run-ID")
        session_id = request.headers.get("X-Session-ID")

        start_time = time.time()

        # Log request start
        request_context: dict[str, Any] = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query_params": dict(request.query_params),
            "client_host": request.client.host if request.client else None,
            "user_agent": request.headers.get("User-Agent"),
        }

        self.service.ingest(LogEvent(
            level=LogLevel.INFO,
            service=self.service_name,
            message=f"{request.method} {request.url.path}",
            run_id=run_id,
            session_id=session_id,
            actor_surface="api",
            context=request_context,
        ))

        try:
            response = await call_next(request)

            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000

            # Determine log level based on status code
            if response.status_code >= 500:
                level = LogLevel.ERROR
            elif response.status_code >= 400:
                level = LogLevel.WARNING
            else:
                level = LogLevel.INFO

            # Log response
            response_context = {
                **request_context,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            }

            self.service.ingest(LogEvent(
                level=level,
                service=self.service_name,
                message=f"{request.method} {request.url.path} -> {response.status_code}",
                run_id=run_id,
                session_id=session_id,
                actor_surface="api",
                context=response_context,
            ))

            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id

            return response

        except Exception as exc:
            # Log error
            duration_ms = (time.time() - start_time) * 1000
            error_context = {
                **request_context,
                "error": str(exc),
                "error_type": type(exc).__name__,
                "duration_ms": round(duration_ms, 2),
            }

            self.service.ingest(LogEvent(
                level=LogLevel.ERROR,
                service=self.service_name,
                message=f"{request.method} {request.url.path} FAILED: {exc}",
                run_id=run_id,
                session_id=session_id,
                actor_surface="api",
                context=error_context,
            ))

            raise


def create_log_routes(
    service: RazeService,
    *,
    prefix: str = "/v1/logs",
    tags: Optional[list[str]] = None,
) -> APIRouter:
    """Create FastAPI router with Raze log endpoints.

    Creates the following endpoints:
    - POST {prefix}/ingest - Batch ingest log events
    - GET {prefix}/query - Query logs with filters
    - GET {prefix}/aggregate - Aggregate logs by dimensions

    Args:
        service: RazeService instance for log operations
        prefix: URL prefix for routes (default: /v1/logs)
        tags: OpenAPI tags for the routes

    Returns:
        APIRouter with log endpoints registered
    """
    router = APIRouter(prefix=prefix, tags=tags or ["logs"])

    @router.post(
        "/ingest",
        response_model=LogIngestResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Ingest log events",
        description="Batch ingest one or more log events. Events are buffered and flushed asynchronously.",
    )
    async def ingest_logs(request: LogIngestRequest) -> LogIngestResponse:
        """Ingest a batch of log events."""
        try:
            log_ids = []
            for event_input in request.logs:
                # Build kwargs, omitting None timestamp to use default
                event_kwargs = {
                    "level": event_input.level,
                    "service": event_input.service,
                    "message": event_input.message,
                    "run_id": event_input.run_id,
                    "action_id": event_input.action_id,
                    "session_id": event_input.session_id,
                    "actor_surface": event_input.actor_surface,
                    "context": event_input.context,
                }
                if event_input.timestamp is not None:
                    event_kwargs["timestamp"] = event_input.timestamp

                event = LogEvent(**event_kwargs)
                service.ingest(event)
                log_ids.append(event.log_id)

            return LogIngestResponse(
                ingested_count=len(log_ids),
                log_ids=log_ids,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to ingest events: {exc}",
            ) from exc

    @router.get(
        "/query",
        response_model=LogQueryResponse,
        summary="Query log events",
        description="Query log events with filters on time range, level, service, and context.",
    )
    async def query_logs(
        start_time: Optional[str] = Query(
            default=None,
            description="Start time (ISO 8601 format)",
            example="2024-01-15T00:00:00Z",
        ),
        end_time: Optional[str] = Query(
            default=None,
            description="End time (ISO 8601 format)",
            example="2024-01-15T23:59:59Z",
        ),
        level: Optional[str] = Query(
            default=None,
            description="Minimum log level (TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL)",
        ),
        service: Optional[str] = Query(
            default=None,
            description="Filter by service name",
        ),
        run_id: Optional[str] = Query(
            default=None,
            description="Filter by run ID",
        ),
        action_id: Optional[str] = Query(
            default=None,
            description="Filter by action ID",
        ),
        session_id: Optional[str] = Query(
            default=None,
            description="Filter by session ID",
        ),
        actor_surface: Optional[str] = Query(
            default=None,
            description="Filter by actor surface (api, cli, vscode, web, mcp)",
        ),
        search: Optional[str] = Query(
            default=None,
            description="Full-text search in message field",
        ),
        limit: int = Query(
            default=100,
            ge=1,
            le=10000,
            description="Maximum number of events to return",
        ),
        offset: int = Query(
            default=0,
            ge=0,
            description="Number of events to skip",
        ),
    ) -> LogQueryResponse:
        """Query log events with filters."""
        try:
            # Parse level if provided
            level_enum = None
            if level:
                try:
                    level_enum = LogLevel(level.upper())
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid log level: {level}",
                    )

            # Build query request
            query_request = LogQueryRequest(
                start_time=start_time,
                end_time=end_time,
                level=level_enum,
                service=service,
                run_id=run_id,
                action_id=action_id,
                session_id=session_id,
                actor_surface=actor_surface,
                search=search,
                limit=limit,
                offset=offset,
            )

            # Execute query
            events, total = service.query(query_request)

            return LogQueryResponse(
                events=events,
                total=total,
                limit=limit,
                offset=offset,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Query failed: {exc}",
            ) from exc

    @router.get(
        "/aggregate",
        response_model=LogAggregateResponse,
        summary="Aggregate log events",
        description="Aggregate log events by time buckets and dimensions.",
    )
    async def aggregate_logs(
        start_time: Optional[str] = Query(
            default=None,
            description="Start time (ISO 8601 format)",
        ),
        end_time: Optional[str] = Query(
            default=None,
            description="End time (ISO 8601 format)",
        ),
        group_by: str = Query(
            default="level",
            description="Field to group by (level, service, actor_surface, time_bucket)",
        ),
        time_bucket: str = Query(
            default="1h",
            description="Time bucket size (1m, 5m, 15m, 1h, 6h, 1d)",
        ),
        level: Optional[str] = Query(
            default=None,
            description="Filter by minimum log level",
        ),
        service: Optional[str] = Query(
            default=None,
            description="Filter by service name",
        ),
    ) -> LogAggregateResponse:
        """Aggregate log events by dimensions."""
        try:
            # Parse level if provided
            level_enum = None
            if level:
                try:
                    level_enum = LogLevel(level.upper())
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid log level: {level}",
                    )

            # Build aggregate request
            agg_request = LogAggregateRequest(
                start_time=start_time,
                end_time=end_time,
                group_by=group_by,
                time_bucket=time_bucket,
                level=level_enum,
                service=service,
            )

            # Execute aggregation
            aggregations = service.aggregate(agg_request)

            return LogAggregateResponse(
                aggregations=aggregations,
                group_by=group_by,
                time_bucket=time_bucket,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Aggregation failed: {exc}",
            ) from exc

    return router


@asynccontextmanager
async def RazeLifespan(
    service: RazeService,
):
    """Async context manager for FastAPI lifespan integration.

    Ensures proper startup and shutdown of the RazeService.

    Usage:
        from contextlib import asynccontextmanager
        from raze.integrations.fastapi import RazeLifespan

        raze_service = RazeService(sink=...)

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            async with RazeLifespan(raze_service):
                yield

        app = FastAPI(lifespan=lifespan)
    """
    try:
        yield
    finally:
        # Shutdown service on app shutdown
        service.shutdown()
