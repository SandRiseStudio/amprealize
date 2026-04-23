/**
 * LocalSyncBackend — SyncBackend implementation that runs tldraw sync in-process.
 *
 * This is the OSS default: every room is managed by a `TLSocketRoom` running
 * inside the same Node.js process as the WebSocket server.  Snapshots are
 * persisted to the Python FastAPI backend via `loadSnapshot` / `saveSnapshot`.
 *
 * For multi-node deployments (enterprise), swap this for a Cloudflare Durable
 * Object backend or another SyncBackend implementation.
 */

import { TLSocketRoom } from "@tldraw/sync";
import type { UnknownRecord } from "@tldraw/store";
import type { TLSocketRoomOptions } from "@tldraw/sync-core";
import type { SyncBackend, RoomSnapshot } from "./types.js";
import {
  loadSnapshot,
  saveSnapshot,
  type PersistenceConfig,
} from "./persistence.js";

type InitialSnapshot = TLSocketRoomOptions<UnknownRecord, void>["initialSnapshot"];

interface ManagedRoom {
  tlRoom: TLSocketRoom<UnknownRecord>;
  connections: Set<string>;
  idleTimer: ReturnType<typeof setTimeout> | null;
  persistTimer: ReturnType<typeof setInterval> | null;
}

export interface LocalSyncBackendConfig {
  /** Configuration for Python API persistence. */
  persistence: PersistenceConfig;
  /** Milliseconds of inactivity before persisting and closing a room. Default: 5 min. */
  idleTimeoutMs?: number;
  /** Milliseconds between periodic saves while a room is active. Default: 30 s. */
  persistIntervalMs?: number;
  /** Maximum concurrent connections per room. Default: 25. */
  maxRoomCapacity?: number;
}

export class LocalSyncBackend implements SyncBackend {
  private rooms = new Map<string, ManagedRoom>();
  private _isOpen = true;
  private readonly persistence: PersistenceConfig;
  private readonly idleTimeoutMs: number;
  private readonly persistIntervalMs: number;
  private readonly maxRoomCapacity: number;

  constructor(config: LocalSyncBackendConfig) {
    this.persistence = config.persistence;
    this.idleTimeoutMs = config.idleTimeoutMs ?? 5 * 60 * 1_000;
    this.persistIntervalMs = config.persistIntervalMs ?? 30_000;
    this.maxRoomCapacity = config.maxRoomCapacity ?? 25;
  }

  get isOpen(): boolean {
    return this._isOpen;
  }

  // ----------------------------------------------------------
  // SyncBackend — public API
  // ----------------------------------------------------------

  /**
   * Handle a new WebSocket connection for a room.
   *
   * `request` and `socket` must be a Node.js `IncomingMessage` and `WebSocket`
   * respectively (from the `ws` library).  `head` is passed through from the
   * HTTP upgrade event.
   */
  async handleConnection(
    roomId: string,
    _request: unknown,
    socket: unknown,
    _head: Buffer,
  ): Promise<void> {
    if (!this._isOpen) {
      throw new Error("LocalSyncBackend is closed");
    }

    let managed = this.rooms.get(roomId);
    if (!managed) {
      managed = await this._createRoom(roomId);
    }

    if (managed.connections.size >= this.maxRoomCapacity) {
      const ws = socket as { close: (code: number, reason: string) => void };
      ws.close(4003, "Room at capacity");
      return;
    }

    // Generate a per-connection session ID
    const sessionId = `conn-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    managed.connections.add(sessionId);
    this._resetIdleTimer(roomId, managed);

    type SocketArg = Parameters<
      TLSocketRoom<UnknownRecord>["handleSocketConnect"]
    >[0]["socket"];

    managed.tlRoom.handleSocketConnect({
      sessionId,
      socket: socket as unknown as SocketArg,
    });

    const ws = socket as { on: (event: string, cb: () => void) => void };
    ws.on("close", () => {
      managed!.connections.delete(sessionId);
      managed!.tlRoom.handleSocketClose(sessionId);
      if (managed!.connections.size === 0) {
        this._resetIdleTimer(roomId, managed!);
      }
    });
  }

  async persistAllAndClose(): Promise<void> {
    this._isOpen = false;
    const entries = Array.from(this.rooms.entries());
    await Promise.allSettled(
      entries.map(async ([roomId, managed]) => {
        try {
          await this._persistRoom(roomId, managed);
        } catch {
          // already logged in _persistRoom
        }
        this._teardownRoom(roomId, managed);
      }),
    );
  }

  async loadSnapshot(roomId: string): Promise<RoomSnapshot | null> {
    return loadSnapshot(roomId, this.persistence);
  }

  async saveSnapshot(roomId: string, snapshot: RoomSnapshot): Promise<void> {
    return saveSnapshot(snapshot, this.persistence);
  }

  // ----------------------------------------------------------
  // Private helpers
  // ----------------------------------------------------------

  private async _createRoom(roomId: string): Promise<ManagedRoom> {
    const snapshot = await loadSnapshot(roomId, this.persistence);

    const tlRoom = new TLSocketRoom<UnknownRecord>({
      initialSnapshot: (snapshot?.state as InitialSnapshot | undefined) ?? undefined,
    });

    const managed: ManagedRoom = {
      tlRoom,
      connections: new Set(),
      idleTimer: null,
      persistTimer: null,
    };

    managed.persistTimer = setInterval(async () => {
      try {
        await this._persistRoom(roomId, managed);
      } catch {
        // logged
      }
    }, this.persistIntervalMs);

    this.rooms.set(roomId, managed);
    return managed;
  }

  private _resetIdleTimer(roomId: string, managed: ManagedRoom): void {
    if (managed.idleTimer) {
      clearTimeout(managed.idleTimer);
    }
    if (managed.connections.size === 0) {
      managed.idleTimer = setTimeout(async () => {
        try {
          await this._persistRoom(roomId, managed);
        } catch {
          // logged
        }
        this._teardownRoom(roomId, managed);
      }, this.idleTimeoutMs);
    }
  }

  private async _persistRoom(roomId: string, managed: ManagedRoom): Promise<void> {
    const state = managed.tlRoom.getCurrentSnapshot();
    const snapshot: RoomSnapshot = {
      roomId,
      savedAt: new Date().toISOString(),
      state,
      clock: (state as { clock?: number }).clock ?? 0,
    };
    await saveSnapshot(snapshot, this.persistence);
  }

  private _teardownRoom(roomId: string, managed: ManagedRoom): void {
    if (managed.idleTimer) clearTimeout(managed.idleTimer);
    if (managed.persistTimer) clearInterval(managed.persistTimer);
    managed.tlRoom.close();
    this.rooms.delete(roomId);
  }
}
