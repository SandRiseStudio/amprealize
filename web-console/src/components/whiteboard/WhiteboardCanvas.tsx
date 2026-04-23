/**
 * WhiteboardCanvas — tldraw infinite canvas with optional collaboration.
 *
 * Renders the tldraw editor inside a full-height container. When
 * VITE_WHITEBOARD_SYNC_URL is set the canvas connects via @tldraw/sync
 * for real-time multiplayer; otherwise it runs in local-only mode
 * using a persistenceKey.
 *
 * If the room is closed/archived, a "Session ended" notice is shown
 * instead of the canvas — the snapshot lives in the archive gallery.
 *
 * GUIDEAI-966: Integrate whiteboard canvas into web console
 * GUIDEAI-993: Frontend useSync integration
 */

import { useEffect, useMemo } from 'react';
import { Tldraw, type TLAssetStore } from 'tldraw';
import { useSync } from '@tldraw/sync';
import { Link } from 'react-router-dom';
import { useWhiteboardRoom, useJoinWhiteboardRoom } from '../../api/whiteboard';
import 'tldraw/tldraw.css';

const TLDRAW_LICENSE_KEY = import.meta.env.VITE_TLDRAW_LICENSE_KEY as string | undefined;
const SYNC_URL = import.meta.env.VITE_WHITEBOARD_SYNC_URL as string | undefined;

const noOpAssetStore: TLAssetStore = {
  upload: async () => ({ src: '' }),
  resolve: (asset) => {
    return asset.props.src ?? '';
  },
};

function getAuthToken(): string {
  return localStorage.getItem('amprealize_token') ?? '';
}

interface WhiteboardCanvasProps {
  roomId: string;
}

function SessionEnded({ title }: { title?: string }) {
  return (
    <div className="whiteboard-canvas-wrapper">
      <div className="whiteboard-canvas-topbar">
        <Link to="/whiteboard" className="whiteboard-canvas-back">&larr; Back</Link>
        <span className="whiteboard-canvas-title">{title || 'Whiteboard'}</span>
      </div>
      <div className="whiteboard-canvas-editor whiteboard-canvas-loading">
        <p className="whiteboard-canvas-loading-title">Session ended</p>
        <p className="whiteboard-canvas-loading-copy">
          This brainstorm whiteboard session has been closed. The snapshot has
          been saved to the{' '}
          <Link to="/whiteboard">session archive</Link>.
        </p>
      </div>
    </div>
  );
}

function SessionExpired({ title }: { title?: string }) {
  return (
    <div className="whiteboard-canvas-wrapper">
      <div className="whiteboard-canvas-topbar">
        <Link to="/whiteboard" className="whiteboard-canvas-back">&larr; Back</Link>
        <span className="whiteboard-canvas-title">{title || 'Whiteboard'}</span>
      </div>
      <div className="whiteboard-canvas-editor whiteboard-canvas-loading">
        <p className="whiteboard-canvas-loading-title">Session link expired</p>
        <p className="whiteboard-canvas-loading-copy">
          This live whiteboard URL was unique to its brainstorm session and no longer works now that the session is over.
          The saved snapshot is available in the <Link to="/whiteboard">session archive</Link>.
        </p>
      </div>
    </div>
  );
}

function SyncedCanvas({ roomId }: { roomId: string }) {
  const uri = useMemo(() => {
    const token = getAuthToken();
    const base = SYNC_URL!.replace(/\/$/, '');
    return `${base}/ws/whiteboard/${roomId}?token=${encodeURIComponent(token)}`;
  }, [roomId]);

  const storeWithStatus = useSync({ uri, assets: noOpAssetStore });

  if (storeWithStatus.status === 'loading') {
    return (
      <div className="whiteboard-canvas-editor whiteboard-canvas-loading">
        <p className="whiteboard-canvas-loading-title">Connecting...</p>
      </div>
    );
  }

  if (storeWithStatus.status === 'error') {
    return (
      <div className="whiteboard-canvas-editor whiteboard-canvas-loading">
        <p className="whiteboard-canvas-loading-title">Connection failed</p>
        <p className="whiteboard-canvas-loading-copy">
          Could not connect to the collaboration server. Try refreshing the page.
        </p>
      </div>
    );
  }

  return (
    <div className="whiteboard-canvas-editor">
      <Tldraw
        licenseKey={TLDRAW_LICENSE_KEY}
        store={storeWithStatus}
      />
    </div>
  );
}

function LocalCanvas({ roomId }: { roomId: string }) {
  return (
    <div className="whiteboard-canvas-editor">
      <Tldraw
        licenseKey={TLDRAW_LICENSE_KEY}
        persistenceKey={`whiteboard-${roomId}`}
      />
    </div>
  );
}

export function WhiteboardCanvas({ roomId }: WhiteboardCanvasProps) {
  const { data: room, isLoading } = useWhiteboardRoom(roomId);
  const joinRoom = useJoinWhiteboardRoom();

  const isExpired = room?.status === 'expired';
  const isClosed = room?.status === 'closed' || room?.status === 'archived';

  useEffect(() => {
    if (isClosed || isExpired || !room) return;
    joinRoom.mutate(roomId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, isClosed, isExpired, room]);

  if (!isLoading && isExpired) {
    return <SessionExpired title={room?.title} />;
  }

  if (!isLoading && isClosed) {
    return <SessionEnded title={room?.title} />;
  }

  if (!isLoading && !room) {
    return <SessionExpired title="Whiteboard" />;
  }

  return (
    <div className="whiteboard-canvas-wrapper">
      <div className="whiteboard-canvas-topbar">
        <Link to="/whiteboard" className="whiteboard-canvas-back">&larr; Rooms</Link>
        <span className="whiteboard-canvas-title">{room?.title || 'Whiteboard'}</span>
      </div>
      {SYNC_URL ? (
        <SyncedCanvas roomId={roomId} />
      ) : (
        <LocalCanvas roomId={roomId} />
      )}
    </div>
  );
}
