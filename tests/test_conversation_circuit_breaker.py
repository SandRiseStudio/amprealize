"""Tests for conversation_circuit_breaker – agent amplification detection."""

from __future__ import annotations

import time

import pytest

from amprealize.services.conversation_circuit_breaker import (
    AmplificationCircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
)

pytestmark = [pytest.mark.unit]


# ── Basic state transitions ───────────────────────────────────────────────────


class TestCircuitStateTransitions:
    """CLOSED → OPEN → HALF_OPEN → CLOSED lifecycle."""

    def test_starts_closed(self):
        cb = AmplificationCircuitBreaker()
        assert cb.state("conv-1") == CircuitState.CLOSED

    def test_allows_messages_when_closed(self):
        cb = AmplificationCircuitBreaker()
        assert cb.allow_agent_message("conv-1", "agent-A") is True

    def test_trips_open_after_threshold(self):
        config = CircuitBreakerConfig(
            window_seconds=30.0,
            max_agent_messages=5,
            cooldown_seconds=60.0,
        )
        cb = AmplificationCircuitBreaker(config=config)

        # Send exactly max_agent_messages
        for _ in range(5):
            assert cb.allow_agent_message("conv-1", "agent-A") is True
            cb.record_agent_message("conv-1", "agent-A")

        # Circuit should now be OPEN
        assert cb.state("conv-1") == CircuitState.OPEN
        assert cb.allow_agent_message("conv-1", "agent-A") is False

    def test_transitions_to_half_open_after_cooldown(self):
        config = CircuitBreakerConfig(
            max_agent_messages=3,
            cooldown_seconds=1.0,  # very short for testing
        )
        cb = AmplificationCircuitBreaker(config=config)

        # Trip the circuit
        for _ in range(3):
            cb.allow_agent_message("conv-1", "agent-A")
            cb.record_agent_message("conv-1", "agent-A")

        assert cb.state("conv-1") == CircuitState.OPEN

        # Simulate cooldown passing by manipulating opened_at
        rec = cb._circuits["conv-1"]
        rec.opened_at = time.monotonic() - 2.0  # 2s ago > 1s cooldown

        assert cb.state("conv-1") == CircuitState.HALF_OPEN
        # Should allow a probe message
        assert cb.allow_agent_message("conv-1", "agent-A") is True

    def test_half_open_to_closed_when_probe_quiet(self):
        config = CircuitBreakerConfig(
            max_agent_messages=3,
            cooldown_seconds=60.0,  # long enough that state() won't auto-close
            probe_limit=2,
            re_trigger_count=10,  # high so probes don't re-trigger
        )
        cb = AmplificationCircuitBreaker(config=config)

        # Trip → OPEN
        for _ in range(3):
            cb.allow_agent_message("c1", "a1")
            cb.record_agent_message("c1", "a1")
        assert cb.state("c1") == CircuitState.OPEN

        # Force HALF_OPEN by aging opened_at past cooldown
        rec = cb._circuits["c1"]
        rec.opened_at = time.monotonic() - 61.0
        assert cb.state("c1") == CircuitState.HALF_OPEN

        # Send one probe
        cb.allow_agent_message("c1", "a1")
        cb.record_agent_message("c1", "a1")

        # Verify still HALF_OPEN (cooldown hasn't elapsed since last probe)
        assert cb.state("c1") == CircuitState.HALF_OPEN

        # Age the last probe timestamp past cooldown_seconds
        rec.probe_timestamps[-1] = time.monotonic() - 61.0
        assert cb.state("c1") == CircuitState.CLOSED


# ── Probe burst re-triggering ─────────────────────────────────────────────────


class TestProbeRetrigger:
    def test_re_opens_on_probe_burst(self):
        config = CircuitBreakerConfig(
            max_agent_messages=3,
            cooldown_seconds=0.5,
            probe_limit=5,
            re_trigger_count=3,
        )
        cb = AmplificationCircuitBreaker(config=config)

        # Trip the circuit
        for _ in range(3):
            cb.allow_agent_message("c1", "a1")
            cb.record_agent_message("c1", "a1")

        # Force HALF_OPEN
        rec = cb._circuits["c1"]
        rec.opened_at = time.monotonic() - 100.0
        assert cb.state("c1") == CircuitState.HALF_OPEN

        # Rapid probe burst: 3 messages within 10s → re-trigger
        for _ in range(3):
            cb.allow_agent_message("c1", "a1")
            cb.record_agent_message("c1", "a1")

        # record_agent_message detects probe burst and re-opens
        assert rec.state == CircuitState.OPEN
        assert rec.trip_count == 2  # tripped twice


# ── Per-conversation isolation ────────────────────────────────────────────────


class TestConversationIsolation:
    def test_different_conversations_independent(self):
        config = CircuitBreakerConfig(max_agent_messages=3)
        cb = AmplificationCircuitBreaker(config=config)

        # Trip conv-1
        for _ in range(3):
            cb.allow_agent_message("conv-1", "a1")
            cb.record_agent_message("conv-1", "a1")

        assert cb.state("conv-1") == CircuitState.OPEN
        # conv-2 should still be CLOSED
        assert cb.state("conv-2") == CircuitState.CLOSED
        assert cb.allow_agent_message("conv-2", "a1") is True


# ── Reset and stats ───────────────────────────────────────────────────────────


class TestResetAndStats:
    def test_reset_clears_circuit(self):
        config = CircuitBreakerConfig(max_agent_messages=2)
        cb = AmplificationCircuitBreaker(config=config)

        for _ in range(2):
            cb.allow_agent_message("c1", "a1")
            cb.record_agent_message("c1", "a1")
        assert cb.state("c1") == CircuitState.OPEN

        cb.reset("c1")
        assert cb.state("c1") == CircuitState.CLOSED

    def test_stats_unknown_conversation(self):
        cb = AmplificationCircuitBreaker()
        stats = cb.stats("nonexistent")
        assert stats["state"] == "closed"
        assert stats["window_size"] == 0
        assert stats["trip_count"] == 0

    def test_stats_after_trip(self):
        config = CircuitBreakerConfig(max_agent_messages=2)
        cb = AmplificationCircuitBreaker(config=config)

        for _ in range(2):
            cb.allow_agent_message("c1", "a1")
            cb.record_agent_message("c1", "a1")

        stats = cb.stats("c1")
        assert stats["state"] == "open"
        assert stats["trip_count"] == 1


# ── Window pruning ────────────────────────────────────────────────────────────


class TestWindowPruning:
    def test_old_messages_pruned_from_window(self):
        config = CircuitBreakerConfig(
            window_seconds=1.0,
            max_agent_messages=100,  # high so we don't trip
        )
        cb = AmplificationCircuitBreaker(config=config)

        # Record a message, then age it out
        cb.record_agent_message("c1", "a1")
        rec = cb._circuits["c1"]
        assert len(rec.window) == 1

        # Make it older than the window
        rec.window[0] = time.monotonic() - 5.0
        # Record another triggers pruning
        cb.record_agent_message("c1", "a1")
        assert len(rec.window) == 1  # old one pruned


# ── Probe limit ───────────────────────────────────────────────────────────────


class TestProbeLimit:
    def test_blocks_after_probe_limit(self):
        config = CircuitBreakerConfig(
            max_agent_messages=2,
            cooldown_seconds=60.0,  # long cooldown so state stays stable
            probe_limit=1,
        )
        cb = AmplificationCircuitBreaker(config=config)

        # Trip it
        for _ in range(2):
            cb.allow_agent_message("c1", "a1")
            cb.record_agent_message("c1", "a1")

        # Force HALF_OPEN by aging opened_at past cooldown
        rec = cb._circuits["c1"]
        rec.opened_at = time.monotonic() - 61.0

        # First probe allowed
        assert cb.allow_agent_message("c1", "a1") is True
        cb.record_agent_message("c1", "a1")

        # Second probe blocked (limit=1)
        assert cb.allow_agent_message("c1", "a1") is False
