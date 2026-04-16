/**
 * Whiteboard Sync Sidecar — Main Entry Point
 *
 * Runs a WebSocket server on PORT (default 3040) that manages TLSocketRoom
 * instances for real-time tldraw collaboration.  Python FastAPI handles CRUD,
 * auth, and persistence; this sidecar handles CRDT sync, cursors, and presence.
 */

import { WebSocketServer, type WebSocket } from "ws";
import http from "node:http";
import { config } from "dotenv";
import { RoomManager } from "./room-manager.js";
import { validateToken } from "./auth.js";

config(); // load .env

const PORT = parseInt(process.env.SYNC_PORT ?? "3040", 10);
const PYTHON_API_BASE =
  process.env.PYTHON_API_BASE ?? "http://localhost:8000/api/v1";
const IDLE_TIMEOUT_MS = parseInt(
  process.env.ROOM_IDLE_TIMEOUT_MS ?? String(5 * 60_000),
  10,
);
const PERSIST_INTERVAL_MS = parseInt(
  process.env.PERSIST_INTERVAL_MS ?? "30000",
  10,
);

const roomManager = new RoomManager({
  pythonApiBase: PYTHON_API_BASE,
  idleTimeoutMs: IDLE_TIMEOUT_MS,
  persistIntervalMs: PERSIST_INTERVAL_MS,
});

const server = http.createServer((_req, res) => {
  // Health check endpoint
  if (_req.url === "/healthz") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        status: "ok",
        rooms: roomManager.activeRoomCount(),
        uptime: process.uptime(),
      }),
    );
    return;
  }
  res.writeHead(404);
  res.end();
});

const wss = new WebSocketServer({ noServer: true });

server.on("upgrade", async (req, socket, head) => {
  // Expected path: /ws/whiteboard/{roomId}
  const urlMatch = req.url?.match(/^\/ws\/whiteboard\/([a-zA-Z0-9_-]+)/);
  if (!urlMatch) {
    socket.write("HTTP/1.1 404 Not Found\r\n\r\n");
    socket.destroy();
    return;
  }

  const roomId = urlMatch[1];
  const url = new URL(req.url!, `http://${req.headers.host}`);
  const token = url.searchParams.get("token") ?? "";

  try {
    const user = await validateToken(token, roomId, PYTHON_API_BASE);

    wss.handleUpgrade(req, socket, head, (ws: WebSocket) => {
      wss.emit("connection", ws, req, { roomId, user });
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unauthorized";
    log("warn", `Auth rejected for room=${roomId}: ${msg}`);
    socket.write("HTTP/1.1 401 Unauthorized\r\n\r\n");
    socket.destroy();
  }
});

wss.on(
  "connection",
  async (
    ws: WebSocket,
    _req: http.IncomingMessage,
    meta: { roomId: string; user: { id: string; name: string } },
  ) => {
    try {
      await roomManager.handleConnection(meta.roomId, meta.user, ws);
    } catch (err) {
      log("error", `Failed to handle connection for room=${meta.roomId}`, err);
      ws.close(4002, "Room initialization failed");
    }
  },
);

server.listen(PORT, () => {
  log("info", `Whiteboard sync sidecar listening on :${PORT}`);
});

// Graceful shutdown
const shutdown = async () => {
  log("info", "Shutting down — persisting all active rooms...");
  await roomManager.persistAllAndClose();
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 10_000);
};

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);

// ---------- Structured logging helper ----------

function log(level: string, message: string, error?: unknown) {
  const entry = {
    ts: new Date().toISOString(),
    level,
    service: "whiteboard-sync",
    message,
    ...(error instanceof Error
      ? { error: error.message, stack: error.stack }
      : {}),
  };
  if (level === "error") {
    console.error(JSON.stringify(entry));
  } else {
    console.log(JSON.stringify(entry));
  }
}
