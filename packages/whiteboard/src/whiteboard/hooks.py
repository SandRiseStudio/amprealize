"""Hook points for WhiteboardService integration.

Consumers implement WhiteboardHooks to wire in ActionService,
ComplianceService, telemetry, or any external system—without the
whiteboard package importing amprealize core.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from whiteboard.models import WhiteboardRoom


class WhiteboardHooks:
    """Base hook class — override methods to inject side-effects."""

    def on_room_created(self, room: WhiteboardRoom) -> None:
        """Called after a room is successfully created."""

    def on_room_closed(self, room: WhiteboardRoom) -> None:
        """Called after a room transitions to closed."""

    def on_room_archived(self, room: WhiteboardRoom) -> None:
        """Called after a room is archived."""

    def on_snapshot_exported(
        self,
        room_id: str,
        format: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Called after a snapshot export completes."""

    def on_participant_joined(self, room_id: str, user_id: str) -> None:
        """Called when a participant joins a room."""

    def on_participant_left(self, room_id: str, user_id: str) -> None:
        """Called when a participant leaves a room."""

    def on_canvas_updated(
        self,
        room_id: str,
        update: Dict[str, Any],
    ) -> None:
        """Called when canvas state is mutated (debounced)."""
