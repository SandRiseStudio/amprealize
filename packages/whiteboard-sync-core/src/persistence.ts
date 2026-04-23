/**
 * persistence.ts — shared HTTP persistence helpers for whiteboard sync backends.
 *
 * Both the local Node.js sidecar and any future remote backend can import
 * these utilities to load/save tldraw snapshots via the Python FastAPI service.
 *
 * Auth: backends supply a service token via WHITEBOARD_SERVICE_TOKEN.  The
 * Python API's AuthMiddleware validates it like any other Bearer token.
 */

import { RoomSnapshot } from "./types.js";

const MAX_RETRIES = 3;
const BASE_DELAY_MS = 500;

const MAX_CANVAS_SIZE_BYTES = parseInt(
  process.env["WHITEBOARD_MAX_CANVAS_SIZE_BYTES"] ?? "5242880",
  10,
);

export interface PersistenceConfig {
  pythonApiBase: string;
  serviceToken?: string;
}

function makeAuthHeaders(token?: string): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  headers["X-Amprealize-Internal"] = "1";
  return headers;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function log(
  level: "debug" | "info" | "warn" | "error",
  message: string,
  extra?: unknown,
): void {
  const entry: Record<string, unknown> = {
    ts: new Date().toISOString(),
    level,
    service: "whiteboard-sync",
    component: "persistence",
    message,
  };
  if (extra !== undefined) {
    entry["error"] = extra instanceof Error ? extra.message : String(extra);
  }
  console.log(JSON.stringify(entry));
}

/**
 * Load the current canvas snapshot for a room from the Python API.
 *
 * Returns `null` if the room has no saved canvas yet or if all retries fail.
 */
export async function loadSnapshot(
  roomId: string,
  config: PersistenceConfig,
): Promise<RoomSnapshot | null> {
  const { pythonApiBase, serviceToken } = config;
  const url = `${pythonApiBase}/whiteboard/rooms/${encodeURIComponent(roomId)}/canvas`;

  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      const res = await fetch(url, {
        headers: makeAuthHeaders(serviceToken),
      });

      if (res.status === 404) {
        return null;
      }

      if (!res.ok) {
        throw new Error(`HTTP ${res.status} ${res.statusText}`);
      }

      const data = (await res.json()) as {
        canvas_state?: unknown;
        clock?: number;
        updated_at?: string;
      };

      if (!data.canvas_state) {
        return null;
      }

      return {
        roomId,
        savedAt: data.updated_at ?? new Date().toISOString(),
        state: data.canvas_state,
        clock: data.clock ?? 0,
      };
    } catch (err) {
      if (attempt < MAX_RETRIES - 1) {
        const delay = BASE_DELAY_MS * 2 ** attempt;
        log(
          "warn",
          "loadSnapshot retry " + String(attempt + 1) + " for room " + String(roomId),
          err,
        );
        await sleep(delay);
      } else {
        log(
          "error",
          "loadSnapshot failed after " +
            String(MAX_RETRIES) +
            " attempts for room " +
            String(roomId),
          err,
        );
        return null;
      }
    }
  }

  return null;
}

/**
 * Save a tldraw snapshot to the Python API.
 *
 * Silently skips payloads that exceed `WHITEBOARD_MAX_CANVAS_SIZE_BYTES`
 * (default 5 MB) to prevent runaway storage growth.
 *
 * Throws on final failure so callers can decide whether to surface the error.
 */
export async function saveSnapshot(
  snapshot: RoomSnapshot,
  config: PersistenceConfig,
): Promise<void> {
  const { pythonApiBase, serviceToken } = config;
  const { roomId } = snapshot;
  const body = JSON.stringify({
    canvas_state: snapshot.state,
    clock: snapshot.clock,
  });
  const sizeBytes = new TextEncoder().encode(body).byteLength;

  if (sizeBytes > MAX_CANVAS_SIZE_BYTES) {
    log(
      "warn",
      "saveSnapshot skipped for room " +
        String(roomId) +
        ": payload " +
        String(sizeBytes) +
        "B exceeds " +
        String(MAX_CANVAS_SIZE_BYTES) +
        "B limit",
    );
    return;
  }

  const url = `${pythonApiBase}/whiteboard/rooms/${encodeURIComponent(roomId)}/canvas`;

  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      const res = await fetch(url, {
        method: "PUT",
        headers: makeAuthHeaders(serviceToken),
        body,
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status} ${res.statusText}`);
      }
      return;
    } catch (err) {
      if (attempt < MAX_RETRIES - 1) {
        const delay = BASE_DELAY_MS * 2 ** attempt;
        log(
          "warn",
          "saveSnapshot retry " + String(attempt + 1) + " for room " + String(roomId),
          err,
        );
        await sleep(delay);
      } else {
        log(
          "error",
          "saveSnapshot failed after " +
            String(MAX_RETRIES) +
            " attempts for room " +
            String(roomId),
          err,
        );
        throw err;
      }
    }
  }
}
