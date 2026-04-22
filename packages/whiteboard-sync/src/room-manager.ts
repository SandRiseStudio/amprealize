/**
 * Room Manager — Manages TLSocketRoom instances for real-time tldraw sync.
 *
 * Each active room maps to a TLSocketRoom that handles CRDT merge, cursor
 * sharing, selection sync, and undo/redo coordination.  Snapshots are loaded
 * from and persisted to the Python FastAPI backend via REST.
 */

import { TLSocketRoom } from "@tldraw/sync";
import type { UnknownRecord } from "@tldraw/store";
import type { TLSocketRoomOptions } from "@tldraw/sync-core";
import type { WebSocket } from "ws";
import { loadSnapshot, saveSnapshot } from "./persistence.js";

type InitialSnapshot = TLSocketRoomOptions<UnknownRecord, void>["initialSnapshot"];

export interface RoomManagerConfig {
  pythonApiBase: string;
  /** Milliseconds of inactivity before persisting and closing a room. */
  idleTimeoutMs: number;
  /** Milliseconds between periodic snapshot saves while room is active. */
  persistIntervalMs: number;
}

interface ManagedRoom {
  tlRoom: TLSocketRoom<UnknownRecord>;
  connections: Set<string>;
  idleTimer: ReturnType<typeof setTimeout> | null;
  persistTimer: ReturnType<typeof setInterval> | null;
}

const MAX_ROOM_CAPACITY = 25;

export class RoomManager {
  private rooms = new Map<string, ManagedRoom>();
  private config: RoomManagerConfig;

  constructor(config: RoomManagerConfig) {
    this.config = config;
  }

  activeRoomCount(): number {
    return this.rooms.size;
  }

  /**
   * Handle a new WebSocket connection for a room.  Creates the TLSocketRoom
   * on first connection, loads the initial snapshot, and wires up the socket.
   */
  async handleConnection(
    roomId: string,
    user: { id: string; name: string },
    ws: WebSocket,
  ): Promise<void> {
    let managed = this.rooms.get(roomId);

    if (!managed) {
      managed = await this.createRoom(roomId);
    }

    if (managed.connections.size >= MAX_ROOM_CAPACITY) {
      ws.close(4003, "Room at capacity");
      return;
    }

    managed.connections.add(user.id);
    this.resetIdleTimer(roomId, managed);

    // Let the TLSocketRoom handle the WebSocket protocol
    type SocketArg = Parameters<TLSocketRoom<UnknownRecord>["handleSocketConnect"]>[0]["socket"];
    managed.tlRoom.handleSocketConnect({
      sessionId: user.id,
      socket: ws as unknown as SocketArg,
    });

    ws.on("close", () => {
      managed!.connections.delete(user.id);
      managed!.tlRoom.handleSocketClose(user.id);

      if (managed!.connections.size === 0) {
        this.resetIdleTimer(roomId, managed!);
      }
    });
  }

  /**
   * Persist snapshots for ALL active rooms and close them. Used on shutdown.
   */
  async persistAllAndClose(): Promise<void> {
    const promises = Array.from(this.rooms.entries()).map(
      async ([roomId, managed]) => {
        try {
          await this.persistRoom(roomId, managed);
        } catch (err) {
          console.error(
            JSON.stringify({
              ts: new Date().toISOString(),
              level: "error",
              service: "whiteboard-sync",
              message: `Failed to persist room ${roomId} on shutdown`,
              error: err instanceof Error ? err.message : String(err),
            }),
          );
        }
        this.teardownRoom(roomId, managed);
      },
    );
    await Promise.allSettled(promises);
  }

  // ---- Private helpers ----

  private async createRoom(roomId: string): Promise<ManagedRoom> {
    // Load existing snapshot from Python API (returns empty canvas if none)
    const snapshot = await loadSnapshot(roomId, this.config.pythonApiBase);

    const tlRoom = new TLSocketRoom<UnknownRecord>({
      initialSnapshot: (snapshot as InitialSnapshot | null | undefined) ?? undefined,
    });

    const managed: ManagedRoom = {
      tlRoom,
      connections: new Set(),
      idleTimer: null,
      persistTimer: null,
    };

    // Periodic snapshot persistence while room is active
    managed.persistTimer = setInterval(async () => {
      try {
        await this.persistRoom(roomId, managed);
      } catch {
        // logged in persistRoom
      }
    }, this.config.persistIntervalMs);

    this.rooms.set(roomId, managed);
    return managed;
  }

  private resetIdleTimer(roomId: string, managed: ManagedRoom): void {
    if (managed.idleTimer) {
      clearTimeout(managed.idleTimer);
    }

    if (managed.connections.size === 0) {
      managed.idleTimer = setTimeout(async () => {
        try {
          await this.persistRoom(roomId, managed);
        } catch {
          // logged
        }
        this.teardownRoom(roomId, managed);
      }, this.config.idleTimeoutMs);
    }
  }

  private async persistRoom(
    roomId: string,
    managed: ManagedRoom,
  ): Promise<void> {
    const snapshot = managed.tlRoom.getCurrentSnapshot();
    await saveSnapshot(roomId, snapshot, this.config.pythonApiBase);
  }

  private teardownRoom(roomId: string, managed: ManagedRoom): void {
    if (managed.idleTimer) clearTimeout(managed.idleTimer);
    if (managed.persistTimer) clearInterval(managed.persistTimer);
    managed.tlRoom.close();
    this.rooms.delete(roomId);
  }
}
