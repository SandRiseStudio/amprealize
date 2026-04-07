"""Tests for Phase 2 gradual rollout mechanism (behavior_wire_cli_to_orchestrator).

Tests hash-based cohort routing, environment variable configuration, and metrics labeling.
"""

import hashlib
import os
import pytest
from unittest.mock import Mock, patch

from amprealize.behavior_retriever import BehaviorRetriever
from amprealize.bci_contracts import RetrieveRequest


@pytest.mark.unit
class TestRolloutMechanism:
    """Test gradual rollout A/B cohort routing."""

    def test_rollout_percentage_0_always_uses_baseline(self):
        """EMBEDDING_ROLLOUT_PERCENTAGE=0 should route all traffic to baseline model."""
        with patch.dict(os.environ, {"EMBEDDING_ROLLOUT_PERCENTAGE": "0"}):
            retriever = BehaviorRetriever(behavior_service=Mock())

            # Test multiple user_ids to ensure consistency
            for user_id in ["user1", "user2", "user3", "user4", "user5"]:
                cohort_model = retriever._determine_model_for_cohort(user_id)
                assert cohort_model == retriever._baseline_model_name, \
                    f"0% rollout should always use baseline, got {cohort_model}"

    def test_rollout_percentage_100_always_uses_new_model(self):
        """EMBEDDING_ROLLOUT_PERCENTAGE=100 should route all traffic to new model."""
        with patch.dict(os.environ, {"EMBEDDING_ROLLOUT_PERCENTAGE": "100"}):
            retriever = BehaviorRetriever(behavior_service=Mock())

            # Test multiple user_ids to ensure consistency
            for user_id in ["user1", "user2", "user3", "user4", "user5"]:
                cohort_model = retriever._determine_model_for_cohort(user_id)
                assert cohort_model == retriever._model_name, \
                    f"100% rollout should always use new model, got {cohort_model}"

    def test_rollout_percentage_50_splits_traffic(self):
        """EMBEDDING_ROLLOUT_PERCENTAGE=50 should split traffic roughly 50/50."""
        with patch.dict(os.environ, {"EMBEDDING_ROLLOUT_PERCENTAGE": "50"}):
            retriever = BehaviorRetriever(behavior_service=Mock())

            # Test 100 users to verify distribution
            new_model_count = 0
            baseline_count = 0

            for i in range(100):
                user_id = f"user{i}"
                cohort_model = retriever._determine_model_for_cohort(user_id)
                if cohort_model == retriever._model_name:
                    new_model_count += 1
                else:
                    baseline_count += 1

            # Allow 10% deviation from perfect 50/50 split (40-60% range)
            assert 40 <= new_model_count <= 60, \
                f"50% rollout should be ~50/50, got {new_model_count}% new model"

    def test_deterministic_routing_same_user(self):
        """Same user_id should always route to same model (deterministic hashing)."""
        with patch.dict(os.environ, {"EMBEDDING_ROLLOUT_PERCENTAGE": "50"}):
            retriever = BehaviorRetriever(behavior_service=Mock())

            # Request same user_id 10 times
            user_id = "consistent_user"
            first_cohort = retriever._determine_model_for_cohort(user_id)

            for _ in range(10):
                cohort = retriever._determine_model_for_cohort(user_id)
                assert cohort == first_cohort, \
                    "Same user_id should always route to same cohort (deterministic)"

    def test_hash_distribution_uniformity(self):
        """Verify hash function distributes users uniformly across buckets."""
        with patch.dict(os.environ, {"EMBEDDING_ROLLOUT_PERCENTAGE": "50"}):
            retriever = BehaviorRetriever(behavior_service=Mock())

            # Generate 1000 users and check bucket distribution
            bucket_counts = [0] * 100  # 100 buckets (0-99)

            for i in range(1000):
                user_id = f"test_user_{i}"
                # Replicate bucket calculation from _determine_model_for_cohort
                hash_bytes = hashlib.sha256(user_id.encode("utf-8")).digest()
                bucket = int.from_bytes(hash_bytes[:4], byteorder="big") % 100
                bucket_counts[bucket] += 1

            # Each bucket should have ~10 users (1000/100), allow 2-20 range for statistical variance
            for bucket, count in enumerate(bucket_counts):
                assert 2 <= count <= 20, \
                    f"Bucket {bucket} has {count} users, expected ~10 (hash distribution issue)"

    def test_invalid_rollout_percentage_defaults_to_100(self):
        """Invalid EMBEDDING_ROLLOUT_PERCENTAGE should default to 100."""
        test_cases = ["abc", "-10", "150", ""]

        for invalid_value in test_cases:
            with patch.dict(os.environ, {"EMBEDDING_ROLLOUT_PERCENTAGE": invalid_value}):
                retriever = BehaviorRetriever(behavior_service=Mock())
                assert retriever._rollout_percentage == 100, \
                    f"Invalid rollout percentage '{invalid_value}' should default to 100"

    def test_rollout_percentage_boundary_values(self):
        """Test boundary values (0, 1, 99, 100) work correctly."""
        test_cases = [
            ("0", 0, "BAAI/bge-m3"),
            ("1", 1, None),  # 1% should mostly route to baseline
            ("99", 99, None),  # 99% should mostly route to new model
            ("100", 100, "sentence-transformers/all-MiniLM-L6-v2"),
        ]

        for env_val, expected_pct, expected_model in test_cases:
            with patch.dict(os.environ, {"EMBEDDING_ROLLOUT_PERCENTAGE": env_val}):
                retriever = BehaviorRetriever(behavior_service=Mock())
                assert retriever._rollout_percentage == expected_pct, \
                    f"Rollout percentage should be {expected_pct}, got {retriever._rollout_percentage}"

                if expected_model:
                    # For 0% and 100%, all users should route to specific model
                    for i in range(10):
                        cohort = retriever._determine_model_for_cohort(f"user{i}")
                        assert cohort == expected_model, \
                            f"{env_val}% rollout failed, expected {expected_model}, got {cohort}"

    def test_user_id_none_fallback_to_thread_id(self):
        """When user_id is None, should fall back to thread ID for routing."""
        with patch.dict(os.environ, {"EMBEDDING_ROLLOUT_PERCENTAGE": "50"}):
            retriever = BehaviorRetriever(behavior_service=Mock())

            # Call with user_id=None multiple times in same thread
            first_cohort = retriever._determine_model_for_cohort(None)

            # Should be deterministic within same thread
            for _ in range(5):
                cohort = retriever._determine_model_for_cohort(None)
                assert cohort == first_cohort, \
                    "Thread-based routing should be deterministic within same thread"

    def test_retrieve_request_accepts_user_id(self):
        """RetrieveRequest should accept user_id field (Phase 2 contract)."""
        request = RetrieveRequest(
            query="test query",
            top_k=5,
            user_id="test_user_123"
        )

        assert request.user_id == "test_user_123", \
            "RetrieveRequest should accept and store user_id"

    def test_retrieve_request_user_id_optional(self):
        """RetrieveRequest user_id should be optional (backward compatibility)."""
        request = RetrieveRequest(
            query="test query",
            top_k=5
        )

        assert request.user_id is None, \
            "RetrieveRequest user_id should default to None"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
