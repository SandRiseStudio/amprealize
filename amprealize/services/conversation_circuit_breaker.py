"""Agent-to-agent amplification circuit breaker (AMPREALIZE-594).

Detects runaway ping-pong loops where two (or more) agents rapidly exchange
messages in the same conversation and temporarily *opens* the circuit to break
the cycle.

The breaker tracks per-conversation sliding windows of agent-sent messages.
When the window fills beyond the configured threshold the circuit transitions
through three states modelled after the standard pattern:

    CLOSED → OPEN → HALF_OPEN → CLOSED  (or back to OPEN)

While OPEN all agent messages in the affected conversation are rejected.
After a cool-down period the breaker enters HALF_OPEN and allows a single
probe message through; if the probe does not trigger another burst the circuit
resets to CLOSED.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Dict, Optional

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Tunables for the amplification circuit breaker."""

    window_seconds: float = 30.0
    """Sliding window length in seconds."""

    max_agent_messages: int = 20
    """Maximum agent messages allowed in the window before the circuit opens."""

    cooldown_seconds: float = 60.0
    """How long the circuit stays OPEN before transitioning to HALF_OPEN."""

    probe_limit: int = 1
    """Number of messages allowed through in HALF_OPEN before deciding."""

    re_trigger_count: int = 3
    """If ≥ this many agent messages arrive during HALF_OPEN within 10 s, re-open."""


@dataclass
class _CircuitRecord:
    state: CircuitState = CircuitState.CLOSED
    window: Deque[float] = field(default_factory=deque)
    opened_at: float = 0.0
    probe_count: int = 0
    probe_timestamps: Deque[float] = field(default_factory=deque)
    trip_count: int = 0


class AmplificationCircuitBreaker:
    """Per-conversation circuit breaker for agent-to-agent message floods.

    Usage::

        breaker = AmplificationCircuitBreaker()

        # Before allowing an agent to post:
        if not breaker.allow_agent_message("conv-abc", "agent-1"):
            raise CircuitOpen(...)

        # After the message is persisted:
        breaker.record_agent_message("conv-abc", "agent-1")
    """

    def __init__(self, config: Optional[CircuitBreakerConfig] = None) -> None:
        self._config = config or CircuitBreakerConfig()
        self._circuits: Dict[str, _CircuitRecord] = {}

    # --- public API ---

    def allow_agent_message(self, conversation_id: str, agent_id: str) -> bool:
        """Return ``True`` if the agent is currently allowed to post."""
        rec = self._get_or_create(conversation_id)
        now = time.monotonic()
        self._maybe_transition(rec, now)

        if rec.state == CircuitState.CLOSED:
            return True

        if rec.state == CircuitState.OPEN:
            logger.info(
                "Circuit OPEN for conversation %s — blocking agent %s",
                conversation_id,
                agent_id,
            )
            return False

        # HALF_OPEN: let through up to probe_limit messages
        if rec.probe_count < self._config.probe_limit:
            return True

        logger.info(
            "Circuit HALF_OPEN but probe limit reached for conversation %s",
            conversation_id,
        )
        return False

    def record_agent_message(self, conversation_id: str, agent_id: str) -> None:
        """Call *after* an agent message is successfully persisted."""
        rec = self._get_or_create(conversation_id)
        now = time.monotonic()

        if rec.state == CircuitState.HALF_OPEN:
            rec.probe_count += 1
            rec.probe_timestamps.append(now)
            # Check if probes are triggering another burst
            recent = [t for t in rec.probe_timestamps if now - t <= 10.0]
            if len(recent) >= self._config.re_trigger_count:
                self._open(rec, now)
                logger.warning(
                    "Circuit re-opened for conversation %s (probe burst detected)",
                    conversation_id,
                )
            return

        # CLOSED — add to window and check threshold
        rec.window.append(now)
        self._prune_window(rec, now)

        if len(rec.window) >= self._config.max_agent_messages:
            self._open(rec, now)
            logger.warning(
                "Circuit tripped for conversation %s "
                "(%d agent messages in %.0fs window)",
                conversation_id,
                len(rec.window),
                self._config.window_seconds,
            )

    def state(self, conversation_id: str) -> CircuitState:
        rec = self._circuits.get(conversation_id)
        if rec is None:
            return CircuitState.CLOSED
        self._maybe_transition(rec, time.monotonic())
        return rec.state

    def reset(self, conversation_id: str) -> None:
        """Manually reset the circuit for a conversation."""
        self._circuits.pop(conversation_id, None)

    def stats(self, conversation_id: str) -> Dict:
        rec = self._circuits.get(conversation_id)
        if rec is None:
            return {"state": CircuitState.CLOSED.value, "window_size": 0, "trip_count": 0}
        now = time.monotonic()
        self._maybe_transition(rec, now)
        self._prune_window(rec, now)
        return {
            "state": rec.state.value,
            "window_size": len(rec.window),
            "trip_count": rec.trip_count,
            "probe_count": rec.probe_count,
        }

    # --- internals ---

    def _get_or_create(self, conversation_id: str) -> _CircuitRecord:
        rec = self._circuits.get(conversation_id)
        if rec is None:
            rec = _CircuitRecord()
            self._circuits[conversation_id] = rec
        return rec

    def _open(self, rec: _CircuitRecord, now: float) -> None:
        rec.state = CircuitState.OPEN
        rec.opened_at = now
        rec.trip_count += 1
        rec.probe_count = 0
        rec.probe_timestamps.clear()

    def _maybe_transition(self, rec: _CircuitRecord, now: float) -> None:
        if rec.state == CircuitState.OPEN:
            if now - rec.opened_at >= self._config.cooldown_seconds:
                rec.state = CircuitState.HALF_OPEN
                rec.probe_count = 0
                rec.probe_timestamps.clear()
                logger.debug("Circuit → HALF_OPEN after cooldown")

        elif rec.state == CircuitState.HALF_OPEN:
            # If probes have been quiet for cooldown_seconds, close
            if rec.probe_timestamps:
                last_probe = rec.probe_timestamps[-1]
                if now - last_probe >= self._config.cooldown_seconds:
                    rec.state = CircuitState.CLOSED
                    rec.window.clear()
                    logger.debug("Circuit → CLOSED (probe quiet)")
            elif now - rec.opened_at >= self._config.cooldown_seconds * 2:
                rec.state = CircuitState.CLOSED
                rec.window.clear()

    def _prune_window(self, rec: _CircuitRecord, now: float) -> None:
        cutoff = now - self._config.window_seconds
        while rec.window and rec.window[0] < cutoff:
            rec.window.popleft()
