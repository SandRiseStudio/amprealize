"""Tests for NVIDIA NeMo BCI rerank (feature-flagged) and NIM HTTP client."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from amprealize.bci_contracts import BehaviorMatch, RetrieveRequest, RetrievalStrategy
from amprealize.behavior_retriever import BehaviorRetriever
from amprealize.feature_flags import DEFAULT_FLAGS, FeatureFlagService
from amprealize.nvidia_nim_rerank import NvidiaNimRerankClient, NvidiaNimRerankResult


def test_feature_nvidia_bci_rerank_registered() -> None:
    names = {f.name for f in DEFAULT_FLAGS}
    assert "feature.nvidia_bci_rerank" in names


def test_nvidia_rerank_client_parses_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "rankings": [
                    {"index": 1, "logit": 2.5},
                    {"index": 0, "logit": 1.0},
                ]
            }

    class _FakeClientCtx:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "_FakeClientCtx":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, *args: object, **kwargs: object) -> _FakeResp:
            return _FakeResp()

    monkeypatch.setattr("httpx.Client", _FakeClientCtx)

    client = NvidiaNimRerankClient(api_key="test-key")
    result = client.rank_passages(query="hello", passages=["a", "b"])
    assert [i for i, _ in result.rankings] == [1, 0]


def test_maybe_nvidia_rerank_reorders(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeClient:
        def rank_passages_safe(self, *, query: str, passages: list[str]) -> NvidiaNimRerankResult:
            return NvidiaNimRerankResult(rankings=[(2, 3.0), (0, 2.0), (1, 1.0)])

    r = BehaviorRetriever(behavior_service=None, eager_load_model=False)
    monkeypatch.setattr(r, "_nvidia_bci_rerank_eligible", lambda _req: True)
    monkeypatch.setattr(r, "_get_nvidia_rerank_client", lambda: _FakeClient())

    matches = [
        BehaviorMatch(behavior_id="a", name="a", version="1", instruction="", score=1.0),
        BehaviorMatch(behavior_id="b", name="b", version="1", instruction="", score=2.0),
        BehaviorMatch(behavior_id="c", name="c", version="1", instruction="", score=0.5),
    ]
    req = RetrieveRequest(query="q", top_k=2, strategy=RetrievalStrategy.EMBEDDING)
    out = r._maybe_nvidia_rerank_matches(req, matches, query_text="q")
    assert [m.behavior_id for m in out] == ["c", "a", "b"]
    assert out[0].score == 3.0


def test_maybe_nvidia_rerank_skips_when_ineligible(monkeypatch: pytest.MonkeyPatch) -> None:
    r = BehaviorRetriever(behavior_service=None, eager_load_model=False)
    monkeypatch.setattr(r, "_nvidia_bci_rerank_eligible", lambda _req: False)

    matches = [
        BehaviorMatch(behavior_id="a", name="a", version="1", instruction="", score=1.0),
        BehaviorMatch(behavior_id="b", name="b", version="1", instruction="", score=2.0),
    ]
    req = RetrieveRequest(query="q", top_k=2, strategy=RetrievalStrategy.EMBEDDING)
    out = r._maybe_nvidia_rerank_matches(req, matches, query_text="q")
    assert out == matches


def test_maybe_nvidia_rerank_falls_back_on_none(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeClient:
        def rank_passages_safe(self, *, query: str, passages: list[str]) -> None:
            return None

    r = BehaviorRetriever(behavior_service=None, eager_load_model=False)
    monkeypatch.setattr(r, "_nvidia_bci_rerank_eligible", lambda _req: True)
    monkeypatch.setattr(r, "_get_nvidia_rerank_client", lambda: _FakeClient())

    matches = [
        BehaviorMatch(behavior_id="a", name="a", version="1", instruction="", score=1.0),
        BehaviorMatch(behavior_id="b", name="b", version="1", instruction="", score=2.0),
    ]
    req = RetrieveRequest(query="q", top_k=2, strategy=RetrievalStrategy.EMBEDDING)
    out = r._maybe_nvidia_rerank_matches(req, matches, query_text="q")
    assert out == matches


def test_rerank_cache_signature_changes_with_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    r = BehaviorRetriever(behavior_service=None, eager_load_model=False)
    req = RetrieveRequest(query="x", top_k=3, strategy=RetrievalStrategy.EMBEDDING)

    monkeypatch.setattr(r, "_nvidia_bci_rerank_eligible", lambda _req: False)
    assert r._rerank_cache_signature(req) == "rerank:off"

    monkeypatch.setattr(r, "_nvidia_bci_rerank_eligible", lambda _req: True)
    on_sig = r._rerank_cache_signature(req)
    assert on_sig.startswith("rerank:on:")


def test_feature_flag_runtime_override_for_nvidia_rerank() -> None:
    from amprealize import feature_flag_runtime as ff_rt

    svc = FeatureFlagService()
    ff_rt.set_override("feature.nvidia_bci_rerank", True)
    try:
        assert svc.is_enabled("feature.nvidia_bci_rerank", {"user_id": "u1"}) is True
    finally:
        ff_rt.clear_override("feature.nvidia_bci_rerank")
