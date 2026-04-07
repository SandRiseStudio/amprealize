"""Base sink protocol for Raze log storage backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from raze.models import (
        LogAggregateRequest,
        LogAggregation,
        LogEvent,
        LogQueryRequest,
    )


class RazeSink(ABC):
    """Abstract base class for log storage sinks.

    Sinks are responsible for persisting log events and supporting
    queries and aggregations. Implementations must be thread-safe.
    """

    @abstractmethod
    def write(self, event: "LogEvent") -> None:
        """Write a single log event.

        Args:
            event: The log event to persist.
        """
        ...

    @abstractmethod
    def write_batch(self, events: List["LogEvent"]) -> None:
        """Write a batch of log events.

        This is the primary write method used by RazeService for
        efficient batched writes.

        Args:
            events: List of log events to persist.
        """
        ...

    @abstractmethod
    def query(
        self,
        request: "LogQueryRequest",
    ) -> Tuple[List["LogEvent"], int]:
        """Query logs with filters.

        Args:
            request: Query parameters.

        Returns:
            Tuple of (matching logs, total count).
        """
        ...

    @abstractmethod
    def aggregate(
        self,
        request: "LogAggregateRequest",
    ) -> Tuple[List["LogAggregation"], int]:
        """Aggregate log statistics.

        Args:
            request: Aggregation parameters.

        Returns:
            Tuple of (aggregation buckets, total count).
        """
        ...

    def flush(self) -> None:
        """Flush any buffered writes.

        Default implementation does nothing. Override for sinks
        with internal buffering.
        """
        pass

    def close(self) -> None:
        """Close the sink and release resources.

        Default implementation does nothing. Override for sinks
        with connections or file handles.
        """
        pass
