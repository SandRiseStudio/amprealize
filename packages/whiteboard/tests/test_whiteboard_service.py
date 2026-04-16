"""Tests for WhiteboardService core lifecycle."""

from whiteboard import (
    InMemoryStorage,
    RoomCreateRequest,
    RoomStatus,
    SnapshotExportRequest,
    SnapshotFormat,
    WhiteboardHooks,
    WhiteboardService,
)


class TrackingHooks(WhiteboardHooks):
    """Hooks implementation that records calls for assertion."""

    def __init__(self):
        self.events = []

    def on_room_created(self, room):
        self.events.append(("room_created", room.id))

    def on_room_closed(self, room):
        self.events.append(("room_closed", room.id))

    def on_room_archived(self, room):
        self.events.append(("room_archived", room.id))

    def on_snapshot_exported(self, room_id, format, metadata=None):
        self.events.append(("snapshot_exported", room_id, format))

    def on_participant_joined(self, room_id, user_id):
        self.events.append(("participant_joined", room_id, user_id))

    def on_participant_left(self, room_id, user_id):
        self.events.append(("participant_left", room_id, user_id))

    def on_canvas_updated(self, room_id, update):
        self.events.append(("canvas_updated", room_id))


def _make_service():
    hooks = TrackingHooks()
    service = WhiteboardService(storage=InMemoryStorage(), hooks=hooks)
    return service, hooks


def test_create_room():
    service, hooks = _make_service()
    resp = service.create_room(RoomCreateRequest(
        session_id="sess-1",
        title="Test Board",
        created_by="user-a",
    ))
    assert resp.room.status == RoomStatus.ACTIVE
    assert resp.room.session_id == "sess-1"
    assert "user-a" in resp.room.participant_ids
    assert ("room_created", resp.room.id) in hooks.events


def test_close_and_archive_room():
    service, hooks = _make_service()
    resp = service.create_room(RoomCreateRequest(session_id="sess-2"))
    room_id = resp.room.id

    closed = service.close_room(room_id)
    assert closed is not None
    assert closed.status == RoomStatus.CLOSED
    assert closed.closed_at is not None

    archived = service.archive_room(room_id)
    assert archived is not None
    assert archived.status == RoomStatus.ARCHIVED

    assert ("room_closed", room_id) in hooks.events
    assert ("room_archived", room_id) in hooks.events


def test_join_and_leave():
    service, hooks = _make_service()
    resp = service.create_room(RoomCreateRequest(session_id="sess-3"))
    room_id = resp.room.id

    service.join_room(room_id, "bob")
    room = service.get_room(room_id)
    assert "bob" in room.participant_ids
    assert ("participant_joined", room_id, "bob") in hooks.events

    service.leave_room(room_id, "bob")
    room = service.get_room(room_id)
    assert "bob" not in room.participant_ids
    assert ("participant_left", room_id, "bob") in hooks.events


def test_save_canvas_state():
    service, hooks = _make_service()
    resp = service.create_room(RoomCreateRequest(session_id="sess-4"))
    room_id = resp.room.id

    state = {"shapes": [{"id": "s1", "type": "draw"}]}
    service.save_canvas_state(room_id, state)

    room = service.get_room(room_id)
    assert room.canvas_state == state
    assert ("canvas_updated", room_id) in hooks.events


def test_export_snapshot_json():
    service, hooks = _make_service()
    resp = service.create_room(RoomCreateRequest(session_id="sess-5"))
    room_id = resp.room.id

    state = {"shapes": [{"id": "s1"}]}
    service.save_canvas_state(room_id, state)

    snap = service.export_snapshot(SnapshotExportRequest(
        room_id=room_id,
        format=SnapshotFormat.JSON,
    ))
    assert snap is not None
    assert snap.data == state
    assert ("snapshot_exported", room_id, "json") in hooks.events


def test_list_rooms_filter():
    service, _ = _make_service()
    service.create_room(RoomCreateRequest(session_id="s1"))
    service.create_room(RoomCreateRequest(session_id="s1"))
    service.create_room(RoomCreateRequest(session_id="s2"))

    rooms_s1 = service.list_rooms(session_id="s1")
    assert len(rooms_s1) == 2

    rooms_s2 = service.list_rooms(session_id="s2")
    assert len(rooms_s2) == 1


def test_get_room_state():
    service, _ = _make_service()
    resp = service.create_room(RoomCreateRequest(
        session_id="sess-6",
        created_by="alice",
    ))
    state = service.get_room_state(resp.room.id)
    assert state is not None
    assert state.participant_count == 1
    assert state.status == RoomStatus.ACTIVE


def test_close_idempotent():
    service, _ = _make_service()
    resp = service.create_room(RoomCreateRequest(session_id="sess-7"))
    service.close_room(resp.room.id)
    closed_again = service.close_room(resp.room.id)
    assert closed_again.status == RoomStatus.CLOSED


def test_join_closed_room_returns_none():
    service, _ = _make_service()
    resp = service.create_room(RoomCreateRequest(session_id="sess-8"))
    service.close_room(resp.room.id)
    result = service.join_room(resp.room.id, "latecomer")
    assert result is None


def test_nonexistent_room():
    service, _ = _make_service()
    assert service.get_room("nonexistent") is None
    assert service.close_room("nonexistent") is None
    assert service.get_room_state("nonexistent") is None
    assert service.join_room("nonexistent", "user") is None
