/**
 * Persistence — Load and save tldraw snapshots via the Python FastAPI REST API.
 *
 * The Python backend owns the canonical snapshot storage (Postgres / in-memory).
 * The sidecar calls into it for initial load and periodic saves.
 *
 * Auth: The sidecar authenticates as a service principal using a Bearer token
 * configured via WHITEBOARD_SERVICE_TOKEN. The Python API's AuthMiddleware
 * validates this like any other token.
 */

const MAX_RETRIES = 3;
const BASE_DELAY_MS = 500;

const SERVICE_TOKEN = process.env.WHITEBOARD_SERVICE_TOKEN ?? "";

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (SERVICE_TOKEN) {
    headers["Authorization"] = `Bearer ${SERVICE_TOKEN}`;
  }
  headers["X-Amprealize-Internal"] = "1";
  return headers;
}

/**
 * Load the current canvas snapshot for a room from the Python API.
 * Returns null if the room has no saved canvas yet.
 */
export async function loadSnapshot(
  roomId: string,
  pythonApiBase: string,
): Promise<unknown | null> {
  const url = `${pythonApiBase}/whiteboard/rooms/${roomId}/canvas`;

  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      const res = await fetch(url, { headers: authHeaders() });

      if (res.status === 404) {
        return null;
      }

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const data = (await res.json()) as { canvas_state?: unknown };
      return data.canvas_state ?? null;
    } catch (err) {
      if (attempt < MAX_RETRIES - 1) {
        const delay = BASE_DELAY_MS * 2 ** attempt;
        log("warn", `loadSnapshot retry ${attempt + 1} for room=${roomId}`, err);
        await sleep(delay);
      } else {
        log("error", `loadSnapshot failed after ${MAX_RETRIES} attempts for room=${roomId}`, err);
        return null;
      }
    }
  }

  return null;
}

const MAX_CANVAS_SIZE_BYTES = parseInt(
  process.env.WHITEBOARD_MAX_CANVAS_SIZE_BYTES ?? "5242880",
  10,
);

/**
 * Save a tldraw snapshot to the Python API.
 * Rejects payloads exceeding MAX_CANVAS_SIZE_BYTES.
 */
export async function saveSnapshot(
  roomId: string,
  snapshot: unknown,
  pythonApiBase: string,
): Promise<void> {
  const body = JSON.stringify({ canvas_state: snapshot });
  const sizeBytes = new TextEncoder().encode(body).byteLength;

  if (sizeBytes > MAX_CANVAS_SIZE_BYTES) {
    log(
      "warn",
      `saveSnapshot skipped for room=${roomId}: payload ${sizeBytes} bytes exceeds ${MAX_CANVAS_SIZE_BYTES} limit`,
    );
    return;
  }

  const url = `${pythonApiBase}/whiteboard/rooms/${roomId}/canvas`;

  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      const res = await fetch(url, {
        method: "PUT",
        headers: authHeaders(),
        body,
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      return;
    } catch (err) {
      if (attempt < MAX_RETRIES - 1) {
        const delay = BASE_DELAY_MS * 2 ** attempt;
        log("warn", `saveSnapshot retry ${attempt + 1} for room=${roomId}`, err);
        await sleep(delay);
      } else {
        log("error", `saveSnapshot failed after ${MAX_RETRIES} attempts for room=${roomId}`, err);
        throw err;
      }
    }
  }
}

// ---------- Helpers ----------

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function log(level: string, message: string, error?: unknown) {
  const entry = {
    ts: new Date().toISOString(),
    level,
    service: "whiteboard-sync",
    component: "persistence",
    message,
    ...(error instanceof Error ? { error: error.message } : {}),
  };
  if (level === "error") {
    console.error(JSON.stringify(entry));
  } else {
    console.log(JSON.stringify(entry));
  }
}
