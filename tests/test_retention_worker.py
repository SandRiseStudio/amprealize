"""Tests for the conversation retention worker and archive flow (AMPREALIZE-613, Phase 8).

Tests cover:
- RetentionWorker lifecycle (start/stop, periodic scheduling)
- Archive job: archive_messages_older_than delegation and return value
- Cold export job: list eligible → fetch messages → upload → delete
- S3 upload byte serialization (gzip JSONL)
- Per-project retention config CRUD on ConversationService
- Conversation stats aggregation
- Analytics API routes (GET /v1/conversations/stats, GET/PUT /v1/projects/{id}/retention)
- Manual job trigger routes (POST /v1/admin/retention/archive)
"""

from __future__ import annotations

import asyncio
import gzip
import json
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch, call

import httpx
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_retention_config(**kwargs):
    from amprealize.config.settings import MessagingRetentionConfig
    defaults = dict(
        archive_after_days=90,
        cold_after_days=365,
        cold_export_enabled=False,
        cold_export_prefix="conversations/cold/",
        archive_job_interval_seconds=86400,
        cold_export_job_interval_seconds=604800,
        archive_batch_size=500,
        cold_export_batch_size=100,
    )
    defaults.update(kwargs)
    return MessagingRetentionConfig(**defaults)


def _make_conv_service():
    svc = MagicMock()
    svc.archive_messages_older_than.return_value = 42
    svc.list_cold_eligible_conversations.return_value = []
    svc.get_conversation_messages_for_export.return_value = []
    svc.delete_conversation_for_cold_export.return_value = 5
    svc.get_conversation_stats.return_value = {
        "total_conversations": 10,
        "active_conversations": 7,
        "archived_conversations": 3,
        "total_messages": 200,
        "archived_messages": 40,
        "messages_last_7_days": 25,
        "messages_last_24h": 5,
        "agent_messages": 100,
        "user_messages": 80,
        "system_messages": 20,
    }
    svc.get_project_retention_config.return_value = {
        "project_id": "proj-1",
        "retention_days": 90,
    }
    svc.set_project_retention_config.return_value = None
    return svc


def _make_storage():
    storage = MagicMock()
    storage.bucket = "test-bucket"
    storage.s3 = MagicMock()
    storage.s3.put_object = MagicMock()
    return storage


@pytest.fixture
def retention_config():
    return _make_retention_config()


@pytest.fixture
def conv_service():
    return _make_conv_service()


@pytest.fixture
def storage():
    return _make_storage()


@pytest.fixture
def worker(conv_service, retention_config):
    from amprealize.services.retention_worker import RetentionWorker
    return RetentionWorker(
        conversation_service=conv_service,
        retention_config=retention_config,
    )


@pytest.fixture
def worker_with_storage(conv_service, storage):
    from amprealize.services.retention_worker import RetentionWorker
    config = _make_retention_config(
        cold_export_enabled=True,
        cold_after_days=365,
    )
    return RetentionWorker(
        conversation_service=conv_service,
        retention_config=config,
        storage=storage,
    )


# =============================================================================
# 1. RetentionWorker lifecycle
# =============================================================================


class TestRetentionWorkerLifecycle:

    async def test_start_creates_archive_task(self, worker):
        try:
            await worker.start()
            assert worker._archive_task is not None
            assert not worker._archive_task.done()
        finally:
            await worker.stop()

    async def test_start_is_idempotent(self, worker):
        try:
            await worker.start()
            task1 = worker._archive_task
            await worker.start()  # second call should be no-op
            assert worker._archive_task is task1
        finally:
            await worker.stop()

    async def test_stop_cancels_tasks(self, worker):
        await worker.start()
        assert worker._running is True
        await worker.stop()
        assert worker._running is False
        assert worker._archive_task.done()

    async def test_cold_task_created_when_storage_configured(
        self, conv_service, storage
    ):
        from amprealize.services.retention_worker import RetentionWorker
        config = _make_retention_config(cold_export_enabled=True)
        w = RetentionWorker(
            conversation_service=conv_service,
            retention_config=config,
            storage=storage,
        )
        try:
            await w.start()
            assert w._cold_task is not None
        finally:
            await w.stop()

    async def test_cold_task_not_created_without_storage(self, worker):
        try:
            await worker.start()
            assert worker._cold_task is None
        finally:
            await worker.stop()


# =============================================================================
# 2. Archive job
# =============================================================================


class TestArchiveJob:

    async def test_archive_job_calls_service(self, worker, conv_service):
        count = await worker.run_archive_job()
        conv_service.archive_messages_older_than.assert_called_once_with(
            90,
            batch_size=500,
            org_id=None,
        )
        assert count == 42

    async def test_archive_job_respects_config_days(self, conv_service):
        from amprealize.services.retention_worker import RetentionWorker
        config = _make_retention_config(archive_after_days=30, archive_batch_size=200)
        w = RetentionWorker(conv_service, retention_config=config)
        await w.run_archive_job()
        conv_service.archive_messages_older_than.assert_called_once_with(
            30,
            batch_size=200,
            org_id=None,
        )

    async def test_archive_job_returns_zero_on_empty(self, conv_service, retention_config):
        from amprealize.services.retention_worker import RetentionWorker
        conv_service.archive_messages_older_than.return_value = 0
        w = RetentionWorker(conv_service, retention_config=retention_config)
        count = await w.run_archive_job()
        assert count == 0


# =============================================================================
# 3. Cold export job
# =============================================================================


class TestColdExportJob:

    async def test_cold_export_skipped_without_storage(self, worker):
        count = await worker.run_cold_export_job()
        assert count == 0

    async def test_cold_export_returns_zero_when_no_eligible(
        self, worker_with_storage, conv_service
    ):
        conv_service.list_cold_eligible_conversations.return_value = []
        count = await worker_with_storage.run_cold_export_job()
        assert count == 0

    async def test_cold_export_processes_eligible_conversations(
        self, worker_with_storage, conv_service, storage
    ):
        conv_service.list_cold_eligible_conversations.return_value = [
            {"id": "conv-1", "project_id": "proj-1", "message_count": 5},
            {"id": "conv-2", "project_id": "proj-1", "message_count": 3},
        ]
        conv_service.get_conversation_messages_for_export.return_value = [
            {"id": "msg-1", "content": "hello", "created_at": "2025-01-01T00:00:00"}
        ]

        count = await worker_with_storage.run_cold_export_job()

        assert count == 2
        assert conv_service.delete_conversation_for_cold_export.call_count == 2

    async def test_cold_export_uploads_gzipped_jsonl(
        self, worker_with_storage, conv_service, storage
    ):
        conv_service.list_cold_eligible_conversations.return_value = [
            {"id": "conv-1", "project_id": "proj-1", "message_count": 1},
        ]
        conv_service.get_conversation_messages_for_export.return_value = [
            {"id": "msg-1", "content": "test message"}
        ]

        await worker_with_storage.run_cold_export_job()

        assert storage.s3.put_object.called
        call_kwargs = storage.s3.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"].endswith(".jsonl.gz")
        assert call_kwargs["ContentEncoding"] == "gzip"

        # Verify it's actually valid gzip containing valid JSON
        body = call_kwargs["Body"].read()
        decompressed = gzip.decompress(body).decode("utf-8")
        parsed = json.loads(decompressed.strip())
        assert parsed["conversation"]["id"] == "conv-1"
        assert len(parsed["messages"]) == 1

    async def test_cold_export_continues_after_single_failure(
        self, worker_with_storage, conv_service, storage
    ):
        conv_service.list_cold_eligible_conversations.return_value = [
            {"id": "conv-fail", "project_id": "proj-1", "message_count": 1},
            {"id": "conv-ok", "project_id": "proj-1", "message_count": 1},
        ]

        def _get_messages(conv_id, org_id=None):
            if conv_id == "conv-fail":
                raise RuntimeError("Simulated export failure")
            return [{"id": "msg-1", "content": "ok"}]

        conv_service.get_conversation_messages_for_export.side_effect = _get_messages

        count = await worker_with_storage.run_cold_export_job()
        # Only conv-ok should succeed; conv-fail is swallowed
        assert count == 1

    async def test_cold_export_key_includes_date_and_conv_id(
        self, worker_with_storage, conv_service, storage
    ):
        conv_service.list_cold_eligible_conversations.return_value = [
            {"id": "conv-xyz", "project_id": "proj-1", "message_count": 0},
        ]
        conv_service.get_conversation_messages_for_export.return_value = []

        await worker_with_storage.run_cold_export_job()

        key = storage.s3.put_object.call_args.kwargs["Key"]
        assert "conv-xyz" in key
        assert key.startswith("conversations/cold/")


# =============================================================================
# 4. ConversationService retention methods (unit-level contract tests)
# =============================================================================


class TestConversationServiceRetentionContract:
    """Verify the ConversationService retention methods have the correct signatures."""

    def test_archive_messages_method_exists(self):
        from amprealize.services.conversation_service import ConversationService
        assert hasattr(ConversationService, "archive_messages_older_than")

    def test_list_cold_eligible_method_exists(self):
        from amprealize.services.conversation_service import ConversationService
        assert hasattr(ConversationService, "list_cold_eligible_conversations")

    def test_get_messages_for_export_method_exists(self):
        from amprealize.services.conversation_service import ConversationService
        assert hasattr(ConversationService, "get_conversation_messages_for_export")

    def test_delete_cold_conversation_method_exists(self):
        from amprealize.services.conversation_service import ConversationService
        assert hasattr(ConversationService, "delete_conversation_for_cold_export")

    def test_get_stats_method_exists(self):
        from amprealize.services.conversation_service import ConversationService
        assert hasattr(ConversationService, "get_conversation_stats")

    def test_get_project_retention_method_exists(self):
        from amprealize.services.conversation_service import ConversationService
        assert hasattr(ConversationService, "get_project_retention_config")

    def test_set_project_retention_method_exists(self):
        from amprealize.services.conversation_service import ConversationService
        assert hasattr(ConversationService, "set_project_retention_config")


# =============================================================================
# 5. MessagingRetentionConfig
# =============================================================================


class TestMessagingRetentionConfig:

    def test_default_values(self):
        config = _make_retention_config()
        assert config.archive_after_days == 90
        assert config.cold_after_days == 365
        assert config.cold_export_enabled is False

    def test_cold_export_not_configured_without_bucket(self):
        config = _make_retention_config(cold_export_enabled=True)
        assert config.is_cold_export_configured(None) is False

    def test_cold_export_configured_with_bucket(self):
        config = _make_retention_config(cold_export_enabled=True)
        assert config.is_cold_export_configured("my-bucket") is True

    def test_cold_export_not_configured_when_disabled(self):
        config = _make_retention_config(cold_export_enabled=False)
        assert config.is_cold_export_configured("my-bucket") is False


# =============================================================================
# 6. Analytics API routes
# =============================================================================


class TestConversationAnalyticsAPI:

    @pytest.fixture
    def app(self, conv_service):
        from fastapi import FastAPI
        from amprealize.services.conversation_analytics_api import (
            create_conversation_analytics_routes,
        )
        test_app = FastAPI()
        router = create_conversation_analytics_routes(
            conversation_service=conv_service,
            tags=["analytics"],
        )
        test_app.include_router(router)
        return test_app

    async def test_get_stats_returns_200(self, app, conv_service):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/conversations/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_conversations"] == 10
        assert data["active_conversations"] == 7
        assert data["total_messages"] == 200
        assert data["archive_rate_percent"] == 20.0

    async def test_get_stats_with_project_filter(self, app, conv_service):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/conversations/stats?project_id=proj-1")

        assert resp.status_code == 200
        conv_service.get_conversation_stats.assert_called_once_with(project_id="proj-1")

    async def test_get_project_retention_returns_config(self, app, conv_service):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/projects/proj-1/retention")

        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == "proj-1"
        assert data["retention_days"] == 90

    async def test_get_project_retention_404_when_not_found(self, app, conv_service):
        conv_service.get_project_retention_config.return_value = None
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/projects/no-such-proj/retention")
        assert resp.status_code == 404

    async def test_put_project_retention_updates_config(self, app, conv_service):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                "/v1/projects/proj-1/retention",
                json={"retention_days": 180},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["retention_days"] == 180
        conv_service.set_project_retention_config.assert_called_once_with(
            "proj-1", 180
        )

    async def test_archive_trigger_returns_503_without_worker(self, app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/v1/admin/retention/archive")
        assert resp.status_code == 503

    async def test_archive_trigger_with_worker(self, conv_service):
        from fastapi import FastAPI
        from amprealize.services.conversation_analytics_api import (
            create_conversation_analytics_routes,
        )
        from amprealize.services.retention_worker import RetentionWorker

        config = _make_retention_config()
        worker = RetentionWorker(conv_service, retention_config=config)

        test_app = FastAPI()
        router = create_conversation_analytics_routes(
            conversation_service=conv_service,
            retention_worker=worker,
        )
        test_app.include_router(router)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            resp = await client.post("/v1/admin/retention/archive")

        assert resp.status_code == 200
        data = resp.json()
        assert data["job"] == "archive"
        assert data["count"] == 42
