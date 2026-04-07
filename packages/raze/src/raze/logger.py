"""RazeLogger - Drop-in structured logging replacement.

This module provides a logger that can replace standard Python logging
with structured JSON output and automatic context enrichment.
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, TextIO, TYPE_CHECKING

from raze.models import LogEvent, LogEventInput, LogLevel, SCHEMA_VERSION

if TYPE_CHECKING:
    from raze.service import RazeService


class RazeLogger:
    """Structured logger with automatic context enrichment.

    RazeLogger provides a familiar logging interface while outputting
    structured JSON logs that can be centralized and queried.

    Example:
        logger = RazeLogger(service="my-service")
        logger.info("User logged in", user_id="123")
        # Outputs: {"level": "INFO", "message": "User logged in", "context": {"user_id": "123"}, ...}

    With context binding:
        logger = logger.bind(request_id="req-123")
        logger.info("Processing request")  # request_id included automatically
    """

    def __init__(
        self,
        service: str,
        *,
        service_instance: Optional["RazeService"] = None,
        default_context: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        action_id: Optional[str] = None,
        session_id: Optional[str] = None,
        actor_surface: Optional[str] = None,
        min_level: LogLevel = LogLevel.DEBUG,
        output: Optional[TextIO] = None,
        json_output: bool = True,
        processors: Optional[List[Callable[[Dict[str, Any]], Dict[str, Any]]]] = None,
    ) -> None:
        """Initialize a RazeLogger.

        Args:
            service: Name of the service/component generating logs.
            service_instance: Optional RazeService for centralized storage.
            default_context: Default context fields added to all logs.
            run_id: Default run ID for correlation.
            action_id: Default action ID for correlation.
            session_id: Default session ID for correlation.
            actor_surface: Default actor surface (api, cli, vscode, web).
            min_level: Minimum log level to output.
            output: Output stream (defaults to stderr).
            json_output: Whether to output JSON (vs human-readable).
            processors: List of functions to transform log data.
        """
        self._service = service
        self._service_instance = service_instance
        self._default_context = default_context or {}
        self._run_id = run_id
        self._action_id = action_id
        self._session_id = session_id
        self._actor_surface = actor_surface
        self._min_level = min_level
        self._output = output or sys.stderr
        self._json_output = json_output
        self._processors = processors or []
        self._lock = threading.Lock()

    def bind(self, **context: Any) -> "RazeLogger":
        """Create a new logger with additional context bound.

        Args:
            **context: Key-value pairs to add to the default context.

        Returns:
            A new RazeLogger with the combined context.
        """
        new_context = {**self._default_context, **context}
        return RazeLogger(
            service=self._service,
            service_instance=self._service_instance,
            default_context=new_context,
            run_id=self._run_id,
            action_id=self._action_id,
            session_id=self._session_id,
            actor_surface=self._actor_surface,
            min_level=self._min_level,
            output=self._output,
            json_output=self._json_output,
            processors=self._processors.copy(),
        )

    def with_run(
        self,
        run_id: Optional[str] = None,
        action_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> "RazeLogger":
        """Create a new logger with correlation IDs set.

        Args:
            run_id: Execution run ID.
            action_id: Action ID within the run.
            session_id: Session ID.

        Returns:
            A new RazeLogger with the correlation IDs.
        """
        return RazeLogger(
            service=self._service,
            service_instance=self._service_instance,
            default_context=self._default_context.copy(),
            run_id=run_id or self._run_id,
            action_id=action_id or self._action_id,
            session_id=session_id or self._session_id,
            actor_surface=self._actor_surface,
            min_level=self._min_level,
            output=self._output,
            json_output=self._json_output,
            processors=self._processors.copy(),
        )

    def _should_log(self, level: LogLevel) -> bool:
        """Check if the given level should be logged."""
        return level >= self._min_level

    def _format_human(self, event: LogEvent) -> str:
        """Format a log event for human-readable output."""
        timestamp = event.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        level_str = f"[{event.level.value:8}]"
        service_str = f"[{event.service}]"

        parts = [timestamp, level_str, service_str, event.message]

        if event.context:
            context_str = " ".join(f"{k}={v}" for k, v in event.context.items())
            parts.append(f"| {context_str}")

        return " ".join(parts)

    def _format_json(self, event: LogEvent) -> str:
        """Format a log event as JSON."""
        return json.dumps(event.to_dict(), ensure_ascii=False, default=str)

    def _log(self, level: LogLevel, message: str, **context: Any) -> Optional[LogEvent]:
        """Internal logging implementation.

        Args:
            level: Log severity level.
            message: Human-readable message.
            **context: Additional context fields.

        Returns:
            The LogEvent if logged, None if filtered.
        """
        if not self._should_log(level):
            return None

        # Merge contexts: default < explicit
        merged_context = {**self._default_context, **context}

        # Apply processors
        log_data = {
            "level": level,
            "service": self._service,
            "message": message,
            "context": merged_context,
            "run_id": self._run_id,
            "action_id": self._action_id,
            "session_id": self._session_id,
            "actor_surface": self._actor_surface,
        }

        for processor in self._processors:
            log_data = processor(log_data)

        # Create the event
        event = LogEvent(
            level=log_data["level"],
            service=log_data["service"],
            message=log_data["message"],
            context=log_data["context"],
            run_id=log_data.get("run_id"),
            action_id=log_data.get("action_id"),
            session_id=log_data.get("session_id"),
            actor_surface=log_data.get("actor_surface"),
        )

        # Output to stream
        with self._lock:
            if self._json_output:
                line = self._format_json(event)
            else:
                line = self._format_human(event)
            self._output.write(line + "\n")
            self._output.flush()

        # Send to service if configured
        if self._service_instance is not None:
            try:
                self._service_instance.ingest_sync([event])
            except Exception:
                # Don't let logging failures break the application
                pass

        return event

    def trace(self, message: str, **context: Any) -> Optional[LogEvent]:
        """Log a TRACE level message."""
        return self._log(LogLevel.TRACE, message, **context)

    def debug(self, message: str, **context: Any) -> Optional[LogEvent]:
        """Log a DEBUG level message."""
        return self._log(LogLevel.DEBUG, message, **context)

    def info(self, message: str, **context: Any) -> Optional[LogEvent]:
        """Log an INFO level message."""
        return self._log(LogLevel.INFO, message, **context)

    def warning(self, message: str, **context: Any) -> Optional[LogEvent]:
        """Log a WARNING level message."""
        return self._log(LogLevel.WARNING, message, **context)

    def warn(self, message: str, **context: Any) -> Optional[LogEvent]:
        """Alias for warning()."""
        return self.warning(message, **context)

    def error(self, message: str, **context: Any) -> Optional[LogEvent]:
        """Log an ERROR level message."""
        return self._log(LogLevel.ERROR, message, **context)

    def critical(self, message: str, **context: Any) -> Optional[LogEvent]:
        """Log a CRITICAL level message."""
        return self._log(LogLevel.CRITICAL, message, **context)

    def exception(self, message: str, exc_info: Optional[BaseException] = None, **context: Any) -> Optional[LogEvent]:
        """Log an ERROR level message with exception info.

        Args:
            message: Human-readable message.
            exc_info: Exception to include (uses current exception if None).
            **context: Additional context fields.
        """
        import traceback

        if exc_info is None:
            exc_info = sys.exc_info()[1]

        if exc_info is not None:
            context["exception_type"] = type(exc_info).__name__
            context["exception_message"] = str(exc_info)
            context["exception_traceback"] = traceback.format_exc()

        return self._log(LogLevel.ERROR, message, **context)

    def log(self, level: LogLevel, message: str, **context: Any) -> Optional[LogEvent]:
        """Log a message at the specified level."""
        return self._log(level, message, **context)


def get_logger(
    service: str,
    **kwargs: Any,
) -> RazeLogger:
    """Get a RazeLogger for the specified service.

    This is a convenience function for creating loggers.

    Args:
        service: Name of the service/component.
        **kwargs: Additional arguments passed to RazeLogger.

    Returns:
        A configured RazeLogger instance.
    """
    return RazeLogger(service=service, **kwargs)


# Module-level default logger
_default_logger: Optional[RazeLogger] = None
_default_lock = threading.Lock()


def configure_default(
    service: str,
    **kwargs: Any,
) -> RazeLogger:
    """Configure the module-level default logger.

    Args:
        service: Name of the service/component.
        **kwargs: Additional arguments passed to RazeLogger.

    Returns:
        The configured default logger.
    """
    global _default_logger
    with _default_lock:
        _default_logger = RazeLogger(service=service, **kwargs)
        return _default_logger


def get_default() -> RazeLogger:
    """Get the module-level default logger.

    Returns:
        The default logger (creates one if not configured).
    """
    global _default_logger
    with _default_lock:
        if _default_logger is None:
            _default_logger = RazeLogger(service="default")
        return _default_logger


# Convenience functions using the default logger
def trace(message: str, **context: Any) -> Optional[LogEvent]:
    """Log a TRACE message using the default logger."""
    return get_default().trace(message, **context)


def debug(message: str, **context: Any) -> Optional[LogEvent]:
    """Log a DEBUG message using the default logger."""
    return get_default().debug(message, **context)


def info(message: str, **context: Any) -> Optional[LogEvent]:
    """Log an INFO message using the default logger."""
    return get_default().info(message, **context)


def warning(message: str, **context: Any) -> Optional[LogEvent]:
    """Log a WARNING message using the default logger."""
    return get_default().warning(message, **context)


def error(message: str, **context: Any) -> Optional[LogEvent]:
    """Log an ERROR message using the default logger."""
    return get_default().error(message, **context)


def critical(message: str, **context: Any) -> Optional[LogEvent]:
    """Log a CRITICAL message using the default logger."""
    return get_default().critical(message, **context)


# ─────────────────────────────────────────────────────────────────────────────
# Python logging Handler adapter
# ─────────────────────────────────────────────────────────────────────────────

import logging


class RazeLoggingHandler(logging.Handler):
    """Python logging.Handler that routes logs to a RazeLogger.

    This allows existing code using `logging.getLogger()` to seamlessly
    route logs through Raze without code changes.

    Example:
        import logging
        from raze.logger import RazeLoggingHandler, RazeLogger

        # Create a Raze logger
        raze_logger = RazeLogger(service="my-service")

        # Add the handler to Python's root logger
        handler = RazeLoggingHandler(raze_logger)
        logging.getLogger().addHandler(handler)

        # Now all Python logging goes through Raze
        logging.info("This goes to Raze!")
    """

    # Map Python logging levels to Raze LogLevel
    LEVEL_MAP = {
        logging.DEBUG: LogLevel.DEBUG,
        logging.INFO: LogLevel.INFO,
        logging.WARNING: LogLevel.WARNING,
        logging.ERROR: LogLevel.ERROR,
        logging.CRITICAL: LogLevel.CRITICAL,
    }

    def __init__(self, raze_logger: RazeLogger) -> None:
        """Initialize the handler with a RazeLogger.

        Args:
            raze_logger: The RazeLogger to route logs to.
        """
        super().__init__()
        self._raze_logger = raze_logger

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record to the RazeLogger.

        Args:
            record: The Python LogRecord to emit.
        """
        try:
            # Map the level
            level = self.LEVEL_MAP.get(record.levelno, LogLevel.INFO)

            # Build context from record extras
            context: Dict[str, Any] = {
                "logger_name": record.name,
                "module": record.module,
                "funcName": record.funcName,
                "lineno": record.lineno,
            }

            # Include exception info if present
            if record.exc_info:
                import traceback
                context["exception_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
                context["exception_message"] = str(record.exc_info[1]) if record.exc_info[1] else None
                context["exception_traceback"] = "".join(traceback.format_exception(*record.exc_info))

            # Include any extra attributes
            for key, value in record.__dict__.items():
                if key not in {
                    "name", "msg", "args", "created", "filename", "funcName",
                    "levelname", "levelno", "lineno", "module", "msecs",
                    "pathname", "process", "processName", "relativeCreated",
                    "thread", "threadName", "exc_info", "exc_text", "stack_info",
                    "message",
                }:
                    context[key] = value

            # Format the message
            message = self.format(record) if self.formatter else record.getMessage()

            # Log through Raze
            self._raze_logger.log(level, message, **context)

        except Exception:
            # Don't let logging failures break the application
            self.handleError(record)


def install_raze_handler(
    service: str,
    logger_name: Optional[str] = None,
    **kwargs: Any,
) -> RazeLoggingHandler:
    """Install a RazeLoggingHandler on a Python logger.

    This is a convenience function to quickly route Python logging to Raze.

    Args:
        service: Name of the service for the Raze logger.
        logger_name: Name of the Python logger (None for root logger).
        **kwargs: Additional arguments passed to RazeLogger.

    Returns:
        The installed RazeLoggingHandler.

    Example:
        from raze.logger import install_raze_handler

        # Route all logging through Raze
        install_raze_handler("my-service")

        # Now Python logging goes through Raze
        import logging
        logging.info("This is structured!")
    """
    raze_logger = RazeLogger(service=service, **kwargs)
    handler = RazeLoggingHandler(raze_logger)

    python_logger = logging.getLogger(logger_name)
    python_logger.addHandler(handler)

    return handler
