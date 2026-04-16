"""Amprealize-integrated whiteboard hooks — Raze telemetry + audit logging.

Implements :class:`whiteboard.hooks.WhiteboardHooks` to emit structured
telemetry events via Raze and append audit log entries for compliance.
Wired in ``api.py`` and ``mcp_server.py`` when the whiteboard feature
flag is enabled.

Part of GUIDEAI-982 — Instrument telemetry and audit logging for whiteboard.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from whiteboard.hooks import WhiteboardHooks
from whiteboard.models import WhiteboardRoom

logger = logging.getLogger(__name__)


class AmprealizeWhiteboardHooks(WhiteboardHooks):
    """Emit Raze telemetry events and audit log entries for whiteboard lifecycle."""

    def __init__(
        self,
        raze_service: Optional[Any] = None,
        audit_log_service: Optional[Any] = None,
    ) -> None:
        self._raze = raze_service
        self._audit = audit_log_service

    def _emit(self, event: str, **fields: Any) -> None:
        """Send a structured event to Raze (no-op if Raze unavailable)."""
        if self._raze is None:
            return
        try:
            self._raze.emit(
                event=event,
                service="whiteboard",
                **fields,
            )
        except Exception:
            logger.debug("Raze emit failed for %s", event, exc_info=True)

    def _audit_log(self, action: str, actor: str, **details: Any) -> None:
        """Append an audit log entry (no-op if audit service unavailable)."""
        if self._audit is None:
            return
        try:
            self._audit.append(
                event_type="whiteboard",
                action=action,
                actor=actor,
                timestamp=datetime.now(timezone.utc),
                details=details,
            )
        except Exception:
            logger.debug("Audit log append failed for %s", action, exc_info=True)

    # -- Hook implementations ------------------------------------------------

    def on_room_created(self, room: WhiteboardRoom) -> None:
        self._emit(
            "whiteboard.room.created",
            room_id=room.id,
            session_id=room.session_id,
            created_by=room.created_by,
            title=room.title,
        )
        self._audit_log(
            "room.created",
            actor=room.created_by or "system",
            room_id=room.id,
            session_id=room.session_id,
            title=room.title,
        )

    def on_room_closed(self, room: WhiteboardRoom) -> None:
        self._emit(
            "whiteboard.room.closed",
            room_id=room.id,
            session_id=room.session_id,
            participant_count=len(room.participant_ids),
        )
        self._audit_log(
            "room.closed",
            actor=room.created_by or "system",
            room_id=room.id,
            session_id=room.session_id,
            participant_count=len(room.participant_ids),
        )

    def on_room_archived(self, room: WhiteboardRoom) -> None:
        self._emit(
            "whiteboard.room.archived",
            room_id=room.id,
            session_id=room.session_id,
        )
        self._audit_log(
            "room.archived",
            actor=room.created_by or "system",
            room_id=room.id,
            session_id=room.session_id,
        )

    def on_snapshot_exported(
        self,
        room_id: str,
        format: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._emit(
            "whiteboard.snapshot.exported",
            room_id=room_id,
            format=format,
            **(metadata or {}),
        )
        self._audit_log(
            "snapshot.exported",
            actor="system",
            room_id=room_id,
            format=format,
        )

    def on_participant_joined(self, room_id: str, user_id: str) -> None:
        self._emit(
            "whiteboard.participant.joined",
            room_id=room_id,
            user_id=user_id,
        )

    def on_participant_left(self, room_id: str, user_id: str) -> None:
        self._emit(
            "whiteboard.participant.left",
            room_id=room_id,
            user_id=user_id,
        )

    def on_canvas_updated(self, room_id: str, update: Dict[str, Any]) -> None:
        self._emit(
            "whiteboard.canvas.updated",
            room_id=room_id,
        )
