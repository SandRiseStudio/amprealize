"""Hooks architecture for Midnighter BC-SFT service.

Hooks allow Midnighter to integrate with any external system without
creating hard dependencies. All hooks have sensible no-op defaults.

Example:
    from mdnt import MidnighterHooks

    hooks = MidnighterHooks(
        get_behavior=lambda id: my_behavior_store.get(id),
        retrieve_behaviors=lambda query, k: my_bci.retrieve(query, k),
        on_metric=lambda event, data: my_telemetry.emit(event, data),
    )

    service = MidnighterService(hooks=hooks)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol


class BehaviorRetriever(Protocol):
    """Protocol for behavior retrieval functions."""

    def __call__(self, behavior_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a behavior by ID.

        Args:
            behavior_id: The behavior identifier (e.g., "behavior_code_review")

        Returns:
            Behavior dict with at minimum:
            - behavior_id: str
            - name: str
            - versions: List[Dict] with 'instruction' field

            Returns None if behavior not found.
        """
        ...


class BehaviorSearcher(Protocol):
    """Protocol for behavior search/retrieval functions."""

    def __call__(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search for behaviors matching a query.

        Args:
            query: Natural language query
            top_k: Number of results to return

        Returns:
            List of behavior dicts matching the query
        """
        ...


class ActionCallback(Protocol):
    """Protocol for action callbacks (logging, audit trails)."""

    def __call__(self, action_type: str, payload: Dict[str, Any]) -> None:
        """Called when a training action occurs.

        Args:
            action_type: Type of action (e.g., "corpus_created", "job_started")
            payload: Action-specific data
        """
        ...


class MetricCallback(Protocol):
    """Protocol for metric/telemetry callbacks."""

    def __call__(self, event_type: str, data: Dict[str, Any]) -> None:
        """Called for telemetry events.

        Args:
            event_type: Type of metric event
            data: Metric data
        """
        ...


class ComplianceCallback(Protocol):
    """Protocol for compliance step callbacks."""

    def __call__(self, step: str, result: Dict[str, Any]) -> None:
        """Called during compliance validation steps.

        Args:
            step: Compliance step name
            result: Step result data
        """
        ...


class CostCallback(Protocol):
    """Protocol for cost tracking callbacks."""

    def __call__(
        self,
        job_id: str,
        cost_usd: float,
        trained_tokens: int,
        model: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Called when training costs are incurred.

        Args:
            job_id: Fine-tuning job ID
            cost_usd: Estimated cost in USD
            trained_tokens: Number of tokens trained
            model: Base model used
            metadata: Additional job metadata
        """
        ...


# No-op defaults
def _noop_get_behavior(behavior_id: str) -> Optional[Dict[str, Any]]:
    """No-op behavior retrieval - returns None."""
    return None


def _noop_retrieve_behaviors(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """No-op behavior search - returns empty list."""
    return []


def _noop_action(action_type: str, payload: Dict[str, Any]) -> None:
    """No-op action callback."""
    pass


def _noop_metric(event_type: str, data: Dict[str, Any]) -> None:
    """No-op metric callback."""
    pass


def _noop_compliance(step: str, result: Dict[str, Any]) -> None:
    """No-op compliance callback."""
    pass


def _noop_cost(
    job_id: str,
    cost_usd: float,
    trained_tokens: int,
    model: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """No-op cost callback."""
    pass


@dataclass
class MidnighterHooks:
    """Hooks for integrating Midnighter with external systems.

    All hooks have sensible no-op defaults, so you only need to provide
    the hooks relevant to your integration.

    Attributes:
        get_behavior: Function to retrieve a behavior by ID.
            Required for generate_corpus_from_behaviors().

        retrieve_behaviors: Function to search behaviors by query.
            Used for BCI-style example generation.

        on_action: Callback for training actions (audit trail).
            Called on corpus creation, job start/complete/fail.

        on_metric: Callback for telemetry/metrics.
            Called for training progress, token counts, etc.

        on_compliance_step: Callback for compliance checks.
            Called during validation steps.

        on_cost: Callback for cost tracking.
            Called when training costs are incurred (job start, progress, complete).
            Useful for budget monitoring and alerts.

    Example:
        # Minimal hooks for corpus generation
        hooks = MidnighterHooks(
            get_behavior=lambda id: behaviors_db.find_one({"_id": id}),
        )

        # Full integration with Amprealize services
        hooks = MidnighterHooks(
            get_behavior=behavior_service.get_behavior,
            retrieve_behaviors=bci_service.retrieve,
            on_action=action_service.record_action,
            on_metric=telemetry.emit_event,
            on_compliance_step=compliance_service.record_step,
        )
    """

    get_behavior: Callable[[str], Optional[Dict[str, Any]]] = field(
        default=_noop_get_behavior
    )
    retrieve_behaviors: Callable[[str, int], List[Dict[str, Any]]] = field(
        default=_noop_retrieve_behaviors
    )
    on_action: Callable[[str, Dict[str, Any]], None] = field(
        default=_noop_action
    )
    on_metric: Callable[[str, Dict[str, Any]], None] = field(
        default=_noop_metric
    )
    on_compliance_step: Callable[[str, Dict[str, Any]], None] = field(
        default=_noop_compliance
    )
    on_cost: Callable[
        [str, float, int, str, Optional[Dict[str, Any]]], None
    ] = field(default=_noop_cost)

    def validate(self) -> List[str]:
        """Validate hooks and return list of warnings.

        Returns:
            List of warning messages for misconfigured hooks.
        """
        warnings = []

        if self.get_behavior is _noop_get_behavior:
            warnings.append(
                "get_behavior hook not configured. "
                "generate_corpus_from_behaviors() will not work."
            )

        return warnings
