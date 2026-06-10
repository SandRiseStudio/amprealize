"""Apply inbound WebSocket messages from a paired local daemon to RunService.

Only runs created with ``execution_workspace_kind=local_connector`` and whose
actor matches the device owner may be updated.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .local_execution_connector_hub import get_local_execution_connector_hub
from .run_contracts import RunCompletion, RunProgressUpdate, RunStatus

logger = logging.getLogger(__name__)


def _authorize_connector_run(*, run: Any, device_user_id: str) -> Optional[str]:
    md = getattr(run, "metadata", None) or {}
    if md.get("execution_workspace_kind") != "local_connector":
        return "run_not_local_connector"
    actor = getattr(run, "actor", None)
    if not actor or getattr(actor, "id", None) != device_user_id:
        return "forbidden"
    return None


def apply_connector_daemon_message(
    *,
    device_user_id: str,
    message: Dict[str, Any],
    run_service: RunService,
) -> Dict[str, Any]:
    """Handle one JSON object from the daemon WebSocket.

    Supported ``type`` values:
    - ``run.lease_ack`` — hybrid path: signal hub lease readiness + optional progress.
    - ``run.progress`` — ``RunProgressUpdate`` (``status``, ``message``, ``progress_pct``, step fields).
    - ``run.complete`` — terminal success via ``complete_run``.
    - ``run.fail`` — terminal failure via ``complete_run`` with ``FAILED``.
    - ``run.ack_cancel`` — acknowledge ``run.cancel_requested`` (no-op on RunService for MVP).
    """
    msg_type = message.get("type")
    run_id = message.get("run_id")
    if not run_id or not isinstance(run_id, str):
        return {"ok": False, "error": "missing_run_id"}

    try:
        run = run_service.get_run(run_id)
    except RunNotFoundError:
        return {"ok": False, "error": "run_not_found"}

    err = _authorize_connector_run(run=run, device_user_id=device_user_id)
    if err:
        return {"ok": False, "error": err}

    if msg_type == "run.ack_cancel":
        return {"ok": True}

    try:
        if msg_type == "run.lease_ack":
            get_local_execution_connector_hub().signal_lease_ack(run_id)
            pv = int(message.get("protocol_version") or 1)
            meta = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
            run_service.update_run(
                run_id,
                RunProgressUpdate(
                    status=RunStatus.RUNNING,
                    progress_pct=message.get("progress_pct") if message.get("progress_pct") is not None else 2.0,
                    message=message.get("message") or "Local connector lease acknowledged",
                    metadata={"connector_phase": "lease_ack", "protocol_version": pv, **meta},
                ),
            )
            return {"ok": True}

        if msg_type == "run.progress":
            meta = message.get("metadata")
            if meta is not None and not isinstance(meta, dict):
                meta = {}
            upd = RunProgressUpdate(
                status=message.get("status"),
                progress_pct=message.get("progress_pct"),
                message=message.get("message"),
                step_id=message.get("step_id"),
                step_name=message.get("step_name"),
                step_status=message.get("step_status"),
                metadata=meta or {},
            )
            run_service.update_run(run_id, upd)
            return {"ok": True}

        if msg_type == "run.complete":
            completion = RunCompletion(
                status=RunStatus.COMPLETED,
                outputs=message.get("outputs") or {},
                message=message.get("message"),
                metadata=message.get("metadata") or {},
            )
            run_service.complete_run(run_id, completion)
            return {"ok": True}

        if msg_type == "run.fail":
            completion = RunCompletion(
                status=RunStatus.FAILED,
                message=message.get("message"),
                error=message.get("error") or message.get("message") or "daemon_failed",
                metadata=message.get("metadata") or {},
            )
            run_service.complete_run(run_id, completion)
            return {"ok": True}
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("connector daemon run update failed: %s", exc, exc_info=True)
        return {"ok": False, "error": "update_failed", "detail": str(exc)}

    return {"ok": False, "error": "unknown_type", "detail": msg_type}
