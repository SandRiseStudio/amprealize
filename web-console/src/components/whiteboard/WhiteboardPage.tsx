/**
 * WhiteboardPage — brainstorm whiteboard gallery and live session viewer.
 *
 * Routes:
 *   /whiteboard        — live sessions + session archive (no creation UI)
 *   /whiteboard/:roomId — open live canvas (closed rooms show "session ended")
 *
 * Rooms are created exclusively via brainstorm.openWhiteboard MCP flow.
 *
 * GUIDEAI-966: Integrate whiteboard canvas into web console
 */

import { Suspense, useCallback, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  useWhiteboardRooms,
  useWhiteboardSnapshots,
  type WhiteboardRoom,
  type WhiteboardSnapshot,
} from '../../api/whiteboard';
import { LazyWhiteboardCanvas, preloadWhiteboardCanvas } from './whiteboardCanvasLoader';
import './WhiteboardPage.css';

interface NetworkInformationHint {
  saveData?: boolean;
  effectiveType?: string;
}

function shouldBackgroundPrefetchCanvas() {
  if (typeof navigator === 'undefined') return false;
  const connection = (navigator as Navigator & { connection?: NetworkInformationHint }).connection;
  if (connection?.saveData) return false;
  return connection?.effectiveType !== 'slow-2g' && connection?.effectiveType !== '2g';
}

function timeAgo(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(dateStr).toLocaleDateString();
}

function RoomCard({ room, onIntent, index }: { room: WhiteboardRoom; onIntent: () => void; index: number }) {
  return (
    <Link
      to={`/whiteboard/${room.id}`}
      className="whiteboard-room-card"
      onMouseEnter={onIntent}
      onFocus={onIntent}
      style={{ animationDelay: `${index * 60}ms` }}
    >
      <div className="whiteboard-room-card-header">
        <span className="whiteboard-room-card-title">{room.title || 'Untitled'}</span>
        <span className="whiteboard-room-card-badge">
          <span className="whiteboard-live-dot" />
          Live
        </span>
      </div>
      <div className="whiteboard-room-card-meta">
        {room.participant_ids.length > 0 && (
          <span className="whiteboard-room-participants">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
            {room.participant_ids.length}
          </span>
        )}
        {room.created_at && (
          <span>{timeAgo(room.created_at)}</span>
        )}
      </div>
    </Link>
  );
}

function SnapshotCard({ snapshot, index }: { snapshot: WhiteboardSnapshot; index: number }) {
  const exportedAt = snapshot.exported_at
    ? timeAgo(snapshot.exported_at)
    : null;
  return (
    <div
      className="whiteboard-snapshot-card"
      style={{ animationDelay: `${index * 60}ms` }}
    >
      <div className="whiteboard-snapshot-card-icon" aria-hidden="true">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
      </div>
      <span className="whiteboard-snapshot-card-title">{snapshot.title || 'Untitled session'}</span>
      <div className="whiteboard-snapshot-card-meta">
        {exportedAt && <span>{exportedAt}</span>}
        <span className="whiteboard-snapshot-format">{snapshot.format}</span>
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="whiteboard-skeleton-grid">
      {[0, 1, 2].map((i) => (
        <div key={i} className="whiteboard-skeleton" style={{ animationDelay: `${i * 150}ms` }} />
      ))}
    </div>
  );
}

function EmptyLive() {
  return (
    <div className="whiteboard-empty">
      <div className="whiteboard-empty-icon" aria-hidden="true">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M12 19l7-7 3 3-7 7-3-3z"/><path d="M18 13l-1.5-7.5L2 2l3.5 14.5L13 18l5-5z"/><path d="M2 2l7.586 7.586"/><circle cx="11" cy="11" r="2"/></svg>
      </div>
      <p className="whiteboard-empty-title">No live sessions</p>
      <p className="whiteboard-empty-copy">
        Start a brainstorm conversation to open a collaborative canvas.
      </p>
    </div>
  );
}

function EmptyArchive() {
  return (
    <div className="whiteboard-empty">
      <div className="whiteboard-empty-icon" aria-hidden="true">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 8v13H3V8"/><path d="M1 3h22v5H1z"/><path d="M10 12h4"/></svg>
      </div>
      <p className="whiteboard-empty-title">No archived sessions yet</p>
      <p className="whiteboard-empty-copy">
        Completed brainstorm whiteboards will appear here as snapshots.
      </p>
    </div>
  );
}

function WhiteboardCanvasFallback({ roomId }: { roomId: string }) {
  return (
    <div className="whiteboard-canvas-wrapper">
      <div className="whiteboard-canvas-topbar">
        <Link to="/whiteboard" className="whiteboard-canvas-back">&larr; Back</Link>
        <span className="whiteboard-canvas-title">Opening whiteboard {roomId.slice(0, 8)}…</span>
      </div>
      <div className="whiteboard-canvas-editor whiteboard-canvas-loading" role="status" aria-live="polite">
        <p className="whiteboard-canvas-loading-title">Loading collaborative canvas…</p>
        <p className="whiteboard-canvas-loading-copy">
          The editor loads on demand to keep the gallery fast.
        </p>
      </div>
    </div>
  );
}

export function WhiteboardPage() {
  const { roomId } = useParams<{ roomId: string }>();

  const { data: rooms = [], isLoading } = useWhiteboardRooms('active', {
    refetchInterval: 10_000,
  });
  const activeRooms = rooms.filter((r) => r.status === 'active');

  const { data: snapshots = [], isLoading: snapshotsLoading } = useWhiteboardSnapshots();

  const handleCanvasIntent = useCallback(() => {
    void preloadWhiteboardCanvas();
  }, []);

  useEffect(() => {
    if (roomId || typeof window === 'undefined' || !shouldBackgroundPrefetchCanvas()) return;
    const timerId = window.setTimeout(() => { void preloadWhiteboardCanvas(); }, 350);
    return () => { window.clearTimeout(timerId); };
  }, [roomId]);

  if (roomId) {
    return (
      <Suspense fallback={<WhiteboardCanvasFallback roomId={roomId} />}>
        <LazyWhiteboardCanvas roomId={roomId} />
      </Suspense>
    );
  }

  return (
    <div className="whiteboard-lobby">
      <header className="whiteboard-lobby-header">
        <h1>Brainstorm Whiteboard</h1>
        <p>
          Whiteboard sessions are created through brainstorm conversations.
          Start a brainstorm with an AI assistant to open a collaborative
          canvas — you'll get a link to join here.
        </p>
      </header>

      <div className="whiteboard-lobby-rooms">
        <div className="whiteboard-section-label">
          <span className="whiteboard-live-dot" />
          <span>Live Sessions</span>
        </div>

        {isLoading ? (
          <LoadingSkeleton />
        ) : activeRooms.length === 0 ? (
          <EmptyLive />
        ) : (
          <div className="whiteboard-room-grid">
            {activeRooms.map((room, i) => (
              <RoomCard key={room.id} room={room} onIntent={handleCanvasIntent} index={i} />
            ))}
          </div>
        )}
      </div>

      <section className="whiteboard-lobby-archive">
        <div className="whiteboard-section-label">
          <span>Session Archive</span>
        </div>

        {snapshotsLoading ? (
          <LoadingSkeleton />
        ) : snapshots.length === 0 ? (
          <EmptyArchive />
        ) : (
          <div className="whiteboard-snapshot-grid">
            {snapshots.map((snap, i) => (
              <SnapshotCard key={snap.id} snapshot={snap} index={i} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
