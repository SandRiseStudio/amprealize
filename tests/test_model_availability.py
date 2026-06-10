"""Model availability contract tests."""

from __future__ import annotations

import pytest

from amprealize.mcp.handlers.config_handlers import handle_get_model_availability
from amprealize.work_item_execution_contracts import AvailableModel, MODEL_CATALOG

pytestmark = pytest.mark.unit

EXPECTED_NVIDIA_CHAT_MODEL_IDS = [
    "nvidia-deepseek-v4-flash",
    "nvidia-deepseek-v4-pro",
    "nvidia-minimax-m2-7",
    "nvidia-kimi-k2-thinking",
    "nvidia-qwen3-coder-480b-a35b-instruct",
    "nvidia-gpt-oss-120b",
    "nvidia-mistral-large-3-675b-instruct-2512",
    "nvidia-glm-5-1",
    "nvidia-llama-3-1-nemotron-ultra-253b-v1",
    "nvidia-llama-3-3-70b-instruct",
]


class FakeCredentialStore:
    def get_available_models(
        self,
        project_id=None,
        org_id=None,
        user_id=None,
        prefer_user=False,
        provider_filter=None,
        free_open_only=False,
    ):
        available = [
            AvailableModel(
                model=MODEL_CATALOG["claude-opus-4-6"],
                credential_source="platform",
                credential_id="cred-anthropic-platform",
                is_byok=False,
            ),
        ]
        for model_id in EXPECTED_NVIDIA_CHAT_MODEL_IDS + ["nvidia-nemotron-3-content-safety"]:
            available.append(
                AvailableModel(
                    model=MODEL_CATALOG[model_id],
                    credential_source="platform",
                    credential_id="cred-nvidia-platform",
                    is_byok=False,
                )
            )
        return available


def test_free_open_only_filters_personal_chat_models_to_nvidia_defaults():
    result = handle_get_model_availability(
        FakeCredentialStore(),
        {
            "project_id": "_user",
            "user_id": "user-123",
            "prefer_user": True,
            "provider_filter": "nvidia",
            "free_open_only": True,
        },
    )

    model_ids = [model["model_id"] for model in result["models"]]
    assert model_ids == EXPECTED_NVIDIA_CHAT_MODEL_IDS
    assert all(model["provider"] == "nvidia" for model in result["models"])
    assert all(model["is_open_model"] for model in result["models"])
    assert all(model["free_endpoint"] for model in result["models"])
    assert "nvidia-nemotron-3-content-safety" not in model_ids
