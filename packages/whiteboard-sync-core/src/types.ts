/**
 * SyncBackend — the shared interface implemented by every whiteboard sync
 * provider (local Node.js sidecar, Cloudflare Durable Objects, etc.).
 *
 * All methods are async so that network-backed backends (CF DO, remote
 * Postgres) can await naturally without blocking the event loop.
 */
export interface SyncBackend {
  /**
   * Open or return an existing sync room for the given room ID.
   * The backend is responsible for resuming from a persisted snapshot.
   *
   * @param roomId  Globally unique room identifier.
   * @param request WebSocket upgrade request (used for auth headers etc.)
   * @param socket  The raw WebSocket to hand over to tldraw sync.
   * @param head    Any extra head bytes from the HTTP upgrade.
   */
  handleConnection(
    roomId: string,
    request: unknown,
    socket: unknown,
    head: Buffer
  ): Promise<void>;

  /**
   * Gracefully flush all in-flight room state to persistent storage and
   * close all active WebSocket connections.
   *
   * Called during SIGTERM / SIGINT shutdown.
   */
  persistAllAndClose(): Promise<void>;

  /**
   * Load the most-recently persisted snapshot for a room, or null if none
   * exists yet.
   */
  loadSnapshot(roomId: string): Promise<RoomSnapshot | null>;

  /**
   * Persist the current canvas snapshot for a room.
   */
  saveSnapshot(roomId: string, snapshot: RoomSnapshot): Promise<void>;

  /**
   * Whether this backend is still open and can accept new connections.
   */
  readonly isOpen: boolean;
}

/**
 * Lightweight wire format for a room snapshot persisted between sessions.
 *
 * `state` is the raw tldraw store snapshot (JSON-serialisable object returned
 * by `TLSocketRoom.getCurrentDocumentClock` / `getSnapshot`).  All other
 * fields are metadata for observability and conflict detection.
 */
export interface RoomSnapshot {
  /** Room identifier. */
  roomId: string;
  /** ISO-8601 timestamp of when this snapshot was captured. */
  savedAt: string;
  /** tldraw store snapshot — opaque JSON blob passed straight to tldraw. */
  state: unknown;
  /** Monotonically increasing logical clock from tldraw. */
  clock: number;
}
