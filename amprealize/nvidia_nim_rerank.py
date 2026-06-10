"""NVIDIA NeMo Retrieval rerank NIM client (synchronous HTTP).

Uses the Rank API documented for ``nvidia/llama-3.2-nv-rerankqa-1b-v2``:
POST ``{base}/retrieval/nvidia/llama-3_2-nv-rerankqa-1b-v2/reranking`` with bearer auth.

See https://docs.api.nvidia.com/nim/reference/nvidia-llama-3_2-nv-rerankqa-1b-v2-infer
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://ai.api.nvidia.com/v1"
DEFAULT_INVOKE_PATH = "/retrieval/nvidia/llama-3_2-nv-rerankqa-1b-v2/reranking"
DEFAULT_MODEL_ID = "nvidia/llama-3.2-nv-rerankqa-1b-v2"


@dataclass(frozen=True)
class NvidiaNimRerankResult:
    """Ordered (original_index, logit) pairs, best match first."""

    rankings: List[Tuple[int, float]]


class NvidiaNimRerankClient:
    """Minimal httpx client for passage reranking."""

    def __init__(
        self,
        *,
        api_key: Optional[str],
        base_url: str = DEFAULT_BASE_URL,
        invoke_path: str = DEFAULT_INVOKE_PATH,
        model: str = DEFAULT_MODEL_ID,
        timeout_sec: float = 30.0,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._base_url = base_url.rstrip("/")
        self._invoke_path = invoke_path if invoke_path.startswith("/") else f"/{invoke_path}"
        self._model = model
        self._timeout_sec = float(timeout_sec)

    @classmethod
    def from_env(cls) -> "NvidiaNimRerankClient":
        key = os.getenv("NVIDIA_NIM_API_KEY") or os.getenv("NVIDIA_API_KEY")
        base = os.getenv("NVIDIA_RERANK_BASE_URL", DEFAULT_BASE_URL).strip()
        path = os.getenv("NVIDIA_RERANK_INVOKE_PATH", DEFAULT_INVOKE_PATH).strip()
        model = os.getenv("NVIDIA_RERANK_MODEL_ID", DEFAULT_MODEL_ID).strip()
        timeout = float(os.getenv("BCI_RERANK_TIMEOUT_SEC", "30"))
        return cls(api_key=key, base_url=base, invoke_path=path, model=model, timeout_sec=timeout)

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def rank_passages(self, *, query: str, passages: Sequence[str]) -> NvidiaNimRerankResult:
        """Call the rerank NIM; raises on HTTP/validation errors."""
        import httpx

        if not self._api_key:
            raise RuntimeError("NVIDIA rerank API key missing (NVIDIA_API_KEY or NVIDIA_NIM_API_KEY)")

        url = f"{self._base_url}{self._invoke_path}"
        body = {
            "model": self._model,
            "query": {"text": query},
            "passages": [{"text": t if t.strip() else " "} for t in passages],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        with httpx.Client(timeout=self._timeout_sec) as client:
            resp = client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        raw = data.get("rankings") or []
        rankings: List[Tuple[int, float]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item["index"])
                logit = float(item["logit"])
            except (KeyError, TypeError, ValueError):
                continue
            rankings.append((idx, logit))

        if not rankings:
            raise RuntimeError("NVIDIA rerank response contained no usable rankings")

        # API examples are already best-first; enforce descending logit for safety.
        rankings.sort(key=lambda pair: pair[1], reverse=True)
        return NvidiaNimRerankResult(rankings=rankings)

    def rank_passages_safe(
        self, *, query: str, passages: Sequence[str]
    ) -> Optional[NvidiaNimRerankResult]:
        """Same as :meth:`rank_passages` but returns ``None`` on failure (logged)."""
        if not passages:
            return None
        try:
            return self.rank_passages(query=query, passages=passages)
        except Exception as exc:
            logger.warning("nvidia_nim_rerank.failed err=%s", exc.__class__.__name__, exc_info=True)
            return None
