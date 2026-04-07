'use strict';

var react = require('react');
var jsxRuntime = require('react/jsx-runtime');
var Markdown = require('react-markdown');
var remarkGfm = require('remark-gfm');

function _interopDefault (e) { return e && e.__esModule ? e : { default: e }; }

var Markdown__default = /*#__PURE__*/_interopDefault(Markdown);
var remarkGfm__default = /*#__PURE__*/_interopDefault(remarkGfm);

// src/types.ts
var EditOperationType = /* @__PURE__ */ ((EditOperationType2) => {
  EditOperationType2["Insert"] = "insert";
  EditOperationType2["Delete"] = "delete";
  EditOperationType2["Replace"] = "replace";
  EditOperationType2["Move"] = "move";
  EditOperationType2["Format"] = "format";
  return EditOperationType2;
})(EditOperationType || {});
var CollaborationRole = /* @__PURE__ */ ((CollaborationRole2) => {
  CollaborationRole2["Owner"] = "owner";
  CollaborationRole2["Admin"] = "admin";
  CollaborationRole2["Editor"] = "editor";
  CollaborationRole2["Commenter"] = "commenter";
  CollaborationRole2["Viewer"] = "viewer";
  return CollaborationRole2;
})(CollaborationRole || {});
var DocumentType = /* @__PURE__ */ ((DocumentType2) => {
  DocumentType2["Markdown"] = "markdown";
  DocumentType2["Plan"] = "plan";
  DocumentType2["Workflow"] = "workflow";
  DocumentType2["Agent"] = "agent";
  DocumentType2["Json"] = "json";
  return DocumentType2;
})(DocumentType || {});

// src/client.ts
var DEFAULT_CONFIG = {
  reconnect: {
    enabled: true,
    maxAttempts: 10,
    baseDelayMs: 1e3,
    maxDelayMs: 3e4
  },
  heartbeatIntervalMs: 25e3,
  debug: false
};
var TypedEventEmitter = class {
  handlers = /* @__PURE__ */ new Map();
  on(event, handler) {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, /* @__PURE__ */ new Set());
    }
    this.handlers.get(event).add(handler);
    return () => this.off(event, handler);
  }
  off(event, handler) {
    this.handlers.get(event)?.delete(handler);
  }
  emit(event, ...args) {
    this.handlers.get(event)?.forEach((handler) => {
      try {
        handler(...args);
      } catch (err) {
        console.error(`[CollabClient] Error in ${String(event)} handler:`, err);
      }
    });
  }
  removeAllListeners() {
    this.handlers.clear();
  }
};
var ConnectionState = /* @__PURE__ */ ((ConnectionState2) => {
  ConnectionState2["Disconnected"] = "disconnected";
  ConnectionState2["Connecting"] = "connecting";
  ConnectionState2["Connected"] = "connected";
  ConnectionState2["Reconnecting"] = "reconnecting";
  return ConnectionState2;
})(ConnectionState || {});
var CollabClient = class extends TypedEventEmitter {
  config;
  ws = null;
  documentId = null;
  document = null;
  connectionState = "disconnected" /* Disconnected */;
  reconnectAttempts = 0;
  reconnectTimeout = null;
  heartbeatInterval = null;
  /** Current auth token (can be updated via setAuthToken) */
  authToken = null;
  // Pending operations awaiting server ACK (for optimistic updates)
  pendingOps = /* @__PURE__ */ new Map();
  opCounter = 0;
  constructor(config) {
    super();
    this.config = {
      ...config,
      reconnect: { ...DEFAULT_CONFIG.reconnect, ...config.reconnect },
      heartbeatIntervalMs: config.heartbeatIntervalMs ?? DEFAULT_CONFIG.heartbeatIntervalMs,
      debug: config.debug ?? DEFAULT_CONFIG.debug
    };
    this.authToken = config.authToken ?? null;
  }
  // ---------------------------------------------------------------------------
  // Auth Token Management
  // ---------------------------------------------------------------------------
  /**
   * Update the auth token. Use this when tokens are refreshed.
   * If currently connected, the new token will be used on next reconnect.
   */
  setAuthToken(token) {
    this.authToken = token;
    this.log("Auth token updated");
  }
  /**
   * Get the current auth token.
   */
  getAuthToken() {
    return this.authToken;
  }
  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------
  get state() {
    return this.connectionState;
  }
  get currentDocument() {
    return this.document;
  }
  get currentVersion() {
    return this.document?.version ?? 0;
  }
  /**
   * Connect to a document for real-time collaboration.
   */
  connect(documentId) {
    if (this.ws && this.documentId === documentId && this.connectionState === "connected" /* Connected */) {
      this.log("Already connected to document", documentId);
      return;
    }
    this.disconnect();
    this.documentId = documentId;
    this.connectionState = "connecting" /* Connecting */;
    void this.createWebSocket();
  }
  /**
   * Disconnect from the current document.
   */
  disconnect() {
    this.clearTimers();
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close(1e3, "Client disconnect");
      this.ws = null;
    }
    this.connectionState = "disconnected" /* Disconnected */;
    this.document = null;
    this.pendingOps.clear();
    this.reconnectAttempts = 0;
  }
  /**
   * Send an edit operation. Returns a local operation ID for tracking.
   */
  sendEdit(operation) {
    const localOpId = `op_${++this.opCounter}_${Date.now()}`;
    const fullOp = {
      ...operation,
      version: this.currentVersion,
      user_id: this.config.userId,
      session_id: this.config.sessionId
    };
    this.pendingOps.set(localOpId, fullOp);
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.send({ type: "edit", operation: fullOp });
    }
    return localOpId;
  }
  /**
   * Send cursor position update.
   */
  sendCursor(position, selectionEnd) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.send({ type: "cursor", position, selection_end: selectionEnd });
    }
  }
  /**
   * Send presence status update.
   */
  sendPresence(status) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.send({ type: "presence", status });
    }
  }
  // ---------------------------------------------------------------------------
  // WebSocket Management
  // ---------------------------------------------------------------------------
  async createWebSocket() {
    if (!this.documentId) return;
    if (this.config.getAuthToken) {
      const freshToken = await this.config.getAuthToken();
      if (freshToken) {
        this.authToken = freshToken;
      }
    }
    const url = new URL(`/v1/collaboration/ws/${this.documentId}`, this.config.baseUrl);
    url.searchParams.set("user_id", this.config.userId);
    if (this.config.sessionId) {
      url.searchParams.set("session_id", this.config.sessionId);
    }
    if (this.authToken) {
      url.searchParams.set("token", this.authToken);
    }
    url.protocol = url.protocol.replace("http", "ws");
    this.log("Connecting to", url.toString().replace(/token=[^&]+/, "token=***"));
    this.ws = new WebSocket(url.toString());
    this.ws.onopen = this.handleOpen.bind(this);
    this.ws.onmessage = this.handleMessage.bind(this);
    this.ws.onclose = this.handleClose.bind(this);
    this.ws.onerror = this.handleError.bind(this);
  }
  handleOpen() {
    this.log("WebSocket connected");
    this.reconnectAttempts = 0;
    this.startHeartbeat();
  }
  handleMessage(event) {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      this.log("Invalid message received:", event.data);
      return;
    }
    this.log("Received:", message.type, message);
    switch (message.type) {
      case "pong":
        break;
      case "snapshot":
        this.document = message.document;
        this.connectionState = "connected" /* Connected */;
        this.emit("connected", message.document);
        break;
      case "operation":
        this.document = message.document ?? this.document;
        if (message.document) {
          this.emit("operation", message.operation, message.document);
        }
        this.clearConfirmedOps(message.operation.version);
        break;
      case "cursor":
        this.emit("cursor", message.user_id, message.position, message.selection_end);
        break;
      case "presence":
        this.emit("presence", message.user_id, message.status);
        break;
      case "error":
        this.handleServerError(message);
        break;
    }
  }
  handleServerError(message) {
    this.log("Server error:", message.code, message.message);
    if (message.code === "VERSION_CONFLICT") {
      if (message.document) {
        this.document = message.document;
      }
      this.emit(
        "conflict",
        message.expected_version ?? 0,
        message.got_version ?? 0,
        message.document ?? null
      );
      this.pendingOps.clear();
    } else if (message.code === "NOT_FOUND") {
      this.emit("error", message.code, message.message);
      this.disconnect();
    } else {
      this.emit("error", message.code, message.message);
    }
  }
  handleClose(event) {
    this.log("WebSocket closed:", event.code, event.reason);
    this.clearTimers();
    this.ws = null;
    const wasConnected = this.connectionState === "connected" /* Connected */;
    if (this.config.reconnect.enabled && this.reconnectAttempts < this.config.reconnect.maxAttempts) {
      this.connectionState = "reconnecting" /* Reconnecting */;
      this.scheduleReconnect();
    } else {
      this.connectionState = "disconnected" /* Disconnected */;
      if (wasConnected) {
        this.emit("disconnected", event.reason || "Connection closed");
      }
    }
  }
  handleError(event) {
    this.log("WebSocket error:", event);
  }
  // ---------------------------------------------------------------------------
  // Reconnection
  // ---------------------------------------------------------------------------
  scheduleReconnect() {
    const delay = Math.min(
      this.config.reconnect.baseDelayMs * Math.pow(2, this.reconnectAttempts),
      this.config.reconnect.maxDelayMs
    );
    this.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts + 1})`);
    this.reconnectTimeout = setTimeout(() => {
      this.reconnectAttempts++;
      void this.createWebSocket();
    }, delay);
  }
  // ---------------------------------------------------------------------------
  // Heartbeat
  // ---------------------------------------------------------------------------
  startHeartbeat() {
    this.heartbeatInterval = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.send({ type: "ping" });
      }
    }, this.config.heartbeatIntervalMs);
  }
  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------
  send(message) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
      this.log("Sent:", message.type, message);
    }
  }
  clearTimers() {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }
  clearConfirmedOps(confirmedVersion) {
    for (const [opId, op] of this.pendingOps) {
      if (op.version < confirmedVersion) {
        this.pendingOps.delete(opId);
      }
    }
  }
  log(...args) {
    if (this.config.debug) {
      console.log("[CollabClient]", ...args);
    }
  }
};
function createCollabClient(config) {
  return new CollabClient(config);
}

// src/executionClient.ts
var DEFAULT_RECONNECT = {
  enabled: true,
  maxAttempts: 10,
  baseDelayMs: 1e3,
  maxDelayMs: 3e4
};
var DEFAULT_CONFIG2 = {
  reconnect: DEFAULT_RECONNECT,
  heartbeatIntervalMs: 25e3,
  debug: false
};
var TypedEventEmitter2 = class {
  handlers = /* @__PURE__ */ new Map();
  on(event, handler) {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, /* @__PURE__ */ new Set());
    }
    this.handlers.get(event).add(handler);
    return () => this.off(event, handler);
  }
  off(event, handler) {
    this.handlers.get(event)?.delete(handler);
  }
  emit(event, ...args) {
    this.handlers.get(event)?.forEach((handler) => {
      try {
        handler(...args);
      } catch (err) {
        console.error(`[ExecutionStreamClient] Error in ${String(event)} handler:`, err);
      }
    });
  }
  removeAllListeners() {
    this.handlers.clear();
  }
};
var ExecutionStreamClient = class extends TypedEventEmitter2 {
  config;
  ws = null;
  target = null;
  connectionState = "disconnected" /* Disconnected */;
  reconnectAttempts = 0;
  reconnectTimeout = null;
  heartbeatInterval = null;
  authToken = null;
  shouldReconnect = true;
  constructor(config) {
    super();
    this.config = {
      ...config,
      reconnect: { ...DEFAULT_RECONNECT, ...config.reconnect },
      heartbeatIntervalMs: config.heartbeatIntervalMs ?? DEFAULT_CONFIG2.heartbeatIntervalMs,
      debug: config.debug ?? DEFAULT_CONFIG2.debug
    };
    this.authToken = config.authToken ?? null;
  }
  // ---------------------------------------------------------------------------
  // Auth Token Management
  // ---------------------------------------------------------------------------
  setAuthToken(token) {
    this.authToken = token;
    this.log("Auth token updated");
  }
  getAuthToken() {
    return this.authToken;
  }
  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------
  get state() {
    return this.connectionState;
  }
  connect(target) {
    if (!target.runId && !(target.orgId && target.projectId)) {
      throw new Error("ExecutionStreamClient.connect requires runId or orgId + projectId");
    }
    const normalizedTarget = {
      runId: target.runId ?? null,
      orgId: target.orgId ?? null,
      projectId: target.projectId ?? null
    };
    if (this.isSameTarget(normalizedTarget) && this.connectionState === "connected" /* Connected */) {
      this.log("Already connected to execution target", normalizedTarget);
      return;
    }
    this.disconnect();
    this.target = normalizedTarget;
    this.shouldReconnect = true;
    this.connectionState = "connecting" /* Connecting */;
    this.reconnectAttempts = 0;
    void this.openConnection();
  }
  disconnect(reason = "manual_disconnect") {
    this.shouldReconnect = false;
    this.clearTimers();
    if (this.ws) {
      this.ws.close();
    }
    this.ws = null;
    this.target = null;
    this.connectionState = "disconnected" /* Disconnected */;
    this.emit("disconnected", reason);
  }
  // ---------------------------------------------------------------------------
  // Connection Flow
  // ---------------------------------------------------------------------------
  async openConnection() {
    if (!this.target) return;
    const token = await this.resolveAuthToken();
    const url = this.buildWebSocketUrl(this.target, token ?? void 0);
    this.log("Connecting to", url);
    this.ws = new WebSocket(url);
    this.ws.onopen = () => {
      this.log("WebSocket connected");
      this.connectionState = "connected" /* Connected */;
      this.reconnectAttempts = 0;
      this.startHeartbeat();
    };
    this.ws.onmessage = (event) => {
      this.handleMessage(event.data);
    };
    this.ws.onerror = () => {
      this.log("WebSocket error");
    };
    this.ws.onclose = (event) => {
      this.log("WebSocket closed", event.code, event.reason);
      this.clearTimers();
      this.ws = null;
      const reason = event.reason || "connection_closed";
      if (this.shouldReconnect && this.config.reconnect.enabled) {
        this.scheduleReconnect(reason);
      } else {
        this.connectionState = "disconnected" /* Disconnected */;
        this.emit("disconnected", reason);
      }
    };
  }
  handleMessage(rawMessage) {
    let message;
    try {
      message = JSON.parse(rawMessage);
    } catch {
      this.log("Invalid JSON message", rawMessage);
      return;
    }
    switch (message.type) {
      case "execution.status":
        this.emit("status", message.payload);
        break;
      case "execution.step":
        this.emit("step", message.payload);
        break;
      case "execution.snapshot": {
        const payload = message.payload;
        this.emit("snapshot", payload);
        this.emit("connected", this.snapshotContext(payload));
        break;
      }
      case "execution.ready": {
        const payload = message.payload;
        this.emit("ready", payload);
        this.emit("connected", payload);
        break;
      }
      case "pong":
        break;
      case "error":
        this.emit("error", message.code ?? "UNKNOWN", message.message ?? "Unknown error");
        break;
      default:
        this.log("Unhandled message", message);
    }
  }
  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------
  snapshotContext(payload) {
    return {
      run_id: payload.run_id ?? this.target?.runId ?? null,
      org_id: this.target?.orgId ?? null,
      project_id: this.target?.projectId ?? null
    };
  }
  async resolveAuthToken() {
    if (this.config.getAuthToken) {
      try {
        const fresh = await this.config.getAuthToken();
        if (fresh) {
          this.authToken = fresh;
        }
      } catch {
      }
    }
    return this.authToken;
  }
  buildWebSocketUrl(target, token) {
    const url = new URL("/api/v1/executions/ws", this.config.baseUrl);
    if (target.runId) url.searchParams.set("run_id", target.runId);
    if (target.orgId) url.searchParams.set("org_id", target.orgId);
    if (target.projectId) url.searchParams.set("project_id", target.projectId);
    if (token) url.searchParams.set("token", token);
    if (url.protocol === "https:" || url.protocol === "wss:") {
      url.protocol = "wss:";
    } else {
      url.protocol = "ws:";
    }
    return url.toString();
  }
  scheduleReconnect(reason) {
    this.connectionState = "reconnecting" /* Reconnecting */;
    this.emit("disconnected", reason);
    const maxAttempts = this.config.reconnect.maxAttempts ?? DEFAULT_CONFIG2.reconnect.maxAttempts;
    if (this.reconnectAttempts >= maxAttempts) {
      this.log("Max reconnect attempts reached");
      this.connectionState = "disconnected" /* Disconnected */;
      return;
    }
    const attempt = this.reconnectAttempts + 1;
    const baseDelayMs = this.config.reconnect.baseDelayMs ?? DEFAULT_CONFIG2.reconnect.baseDelayMs;
    const maxDelayMs = this.config.reconnect.maxDelayMs ?? DEFAULT_CONFIG2.reconnect.maxDelayMs;
    const delay = Math.min(baseDelayMs * 2 ** (attempt - 1), maxDelayMs);
    this.reconnectAttempts = attempt;
    this.reconnectTimeout = setTimeout(() => {
      if (!this.target) return;
      this.log(`Reconnect attempt ${attempt}`);
      void this.openConnection();
    }, delay);
  }
  startHeartbeat() {
    const heartbeatIntervalMs = this.config.heartbeatIntervalMs ?? DEFAULT_CONFIG2.heartbeatIntervalMs;
    if (heartbeatIntervalMs <= 0) return;
    this.heartbeatInterval = setInterval(() => {
      this.send({ type: "ping" });
    }, heartbeatIntervalMs);
  }
  send(message) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
      this.log("Sent:", message.type);
    }
  }
  clearTimers() {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }
  isSameTarget(target) {
    return this.target?.runId === (target.runId ?? null) && this.target?.orgId === (target.orgId ?? null) && this.target?.projectId === (target.projectId ?? null);
  }
  log(...args) {
    if (this.config.debug) {
      console.log("[ExecutionStreamClient]", ...args);
    }
  }
};
function createExecutionStreamClient(config) {
  return new ExecutionStreamClient(config);
}

// src/api.ts
var CollabApi = class {
  config;
  fetch;
  constructor(config) {
    this.config = config;
    this.fetch = config.fetch ?? globalThis.fetch.bind(globalThis);
  }
  // ---------------------------------------------------------------------------
  // Workspaces
  // ---------------------------------------------------------------------------
  async createWorkspace(request) {
    return this.post("/v1/collaboration/workspaces", request);
  }
  async getWorkspace(workspaceId) {
    return this.get(`/v1/collaboration/workspaces/${workspaceId}`);
  }
  async listDocuments(workspaceId) {
    return this.get(`/v1/collaboration/workspaces/${workspaceId}/documents`);
  }
  // ---------------------------------------------------------------------------
  // Documents
  // ---------------------------------------------------------------------------
  async createDocument(request) {
    return this.post("/v1/collaboration/documents", request);
  }
  async getDocument(documentId) {
    return this.get(`/v1/collaboration/documents/${documentId}`);
  }
  async getDocumentOperations(documentId, limit = 100) {
    return this.get(`/v1/collaboration/documents/${documentId}/operations?limit=${limit}`);
  }
  // ---------------------------------------------------------------------------
  // Project Settings
  // ---------------------------------------------------------------------------
  async getProjectSettings(projectId) {
    return this.get(`/v1/projects/${projectId}/settings`);
  }
  async updateProjectSettings(projectId, settings) {
    return this.patch(`/v1/projects/${projectId}/settings`, settings);
  }
  async setProjectRepository(projectId, repositoryUrl, defaultBranch = "main") {
    return this.put(`/v1/projects/${projectId}/settings/repository`, {
      repository_url: repositoryUrl,
      default_branch: defaultBranch
    });
  }
  // ---------------------------------------------------------------------------
  // GitHub Integration
  // ---------------------------------------------------------------------------
  async validateGitHubRepository(projectId, request) {
    return this.post(
      `/v1/projects/${projectId}/settings/repository/validate`,
      request
    );
  }
  async listGitHubBranches(projectId, page = 1, perPage = 30) {
    return this.get(
      `/v1/projects/${projectId}/settings/repository/branches?page=${page}&per_page=${perPage}`
    );
  }
  // ---------------------------------------------------------------------------
  // HTTP Helpers
  // ---------------------------------------------------------------------------
  async get(path) {
    const response = await this.fetch(`${this.config.baseUrl}${path}`, {
      method: "GET",
      headers: this.headers()
    });
    return this.handleResponse(response);
  }
  async post(path, body) {
    const response = await this.fetch(`${this.config.baseUrl}${path}`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify(body)
    });
    return this.handleResponse(response);
  }
  async patch(path, body) {
    const response = await this.fetch(`${this.config.baseUrl}${path}`, {
      method: "PATCH",
      headers: this.headers(),
      body: JSON.stringify(body)
    });
    return this.handleResponse(response);
  }
  async put(path, body) {
    const response = await this.fetch(`${this.config.baseUrl}${path}`, {
      method: "PUT",
      headers: this.headers(),
      body: JSON.stringify(body)
    });
    return this.handleResponse(response);
  }
  headers() {
    const h = {
      "Content-Type": "application/json",
      Accept: "application/json"
    };
    if (this.config.authToken) {
      h["Authorization"] = `Bearer ${this.config.authToken}`;
    }
    return h;
  }
  async handleResponse(response) {
    if (!response.ok) {
      const text = await response.text();
      let detail = text;
      try {
        const json = JSON.parse(text);
        detail = json.detail ?? json.message ?? text;
      } catch {
      }
      throw new CollabApiError(response.status, detail);
    }
    return response.json();
  }
};
var CollabApiError = class extends Error {
  constructor(status, detail) {
    super(`CollabApi error ${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
    this.name = "CollabApiError";
  }
};
function createCollabApi(config) {
  return new CollabApi(config);
}
function useCollaboration(options) {
  const { config, documentId, onContentChange, onConflict } = options;
  const onContentChangeRef = react.useRef(onContentChange);
  const onConflictRef = react.useRef(onConflict);
  onContentChangeRef.current = onContentChange;
  onConflictRef.current = onConflict;
  const clientRef = react.useRef(null);
  const [clientVersion, setClientVersion] = react.useState(0);
  const [document2, setDocument] = react.useState(null);
  const [connectionState, setConnectionState] = react.useState("disconnected" /* Disconnected */);
  const [cursors, setCursors] = react.useState(/* @__PURE__ */ new Map());
  const [presence, setPresence] = react.useState(/* @__PURE__ */ new Map());
  const [operations, setOperations] = react.useState([]);
  const [error, setError] = react.useState(null);
  react.useEffect(() => {
    const client = createCollabClient(config);
    clientRef.current = client;
    setClientVersion((v) => v + 1);
    const handleConnected = (doc) => {
      setDocument(doc);
      setConnectionState("connected" /* Connected */);
      setError(null);
      onContentChangeRef.current?.(doc.content, doc);
    };
    const handleDisconnected = (reason) => {
      setConnectionState("disconnected" /* Disconnected */);
      setPresence(/* @__PURE__ */ new Map());
      setCursors(/* @__PURE__ */ new Map());
      setError({ code: "DISCONNECTED", message: reason });
    };
    const handleOperation = (op, doc) => {
      if (doc) {
        setDocument(doc);
        onContentChangeRef.current?.(doc.content, doc);
      }
      setOperations((prev) => [...prev.slice(-99), op]);
    };
    const handleConflict = (_expected, _got, serverDoc) => {
      if (serverDoc) {
        const rebased = onConflictRef.current?.(serverDoc);
        if (rebased !== null && rebased !== void 0) {
          client.sendEdit({
            operation_type: "replace",
            position: 0,
            content: rebased,
            length: serverDoc.content.length
          });
        } else {
          setDocument(serverDoc);
          onContentChangeRef.current?.(serverDoc.content, serverDoc);
        }
      }
    };
    const handleCursor = (userId, position, selectionEnd) => {
      setCursors((prev) => {
        const next = new Map(prev);
        next.set(userId, { position, selectionEnd });
        return next;
      });
      setPresence((prev) => {
        const next = new Map(prev);
        const existing = next.get(userId);
        next.set(userId, {
          user_id: userId,
          session_id: existing?.session_id,
          display_name: existing?.display_name,
          color: existing?.color,
          status: existing?.status ?? "active",
          cursor_position: position,
          selection_end: selectionEnd,
          last_active: (/* @__PURE__ */ new Date()).toISOString()
        });
        return next;
      });
    };
    const handlePresence = (userId, status) => {
      setPresence((prev) => {
        const next = new Map(prev);
        if (status === "disconnected") {
          next.delete(userId);
          return next;
        }
        const existing = next.get(userId);
        next.set(userId, {
          user_id: userId,
          session_id: existing?.session_id,
          display_name: existing?.display_name,
          color: existing?.color,
          status,
          cursor_position: existing?.cursor_position,
          selection_end: existing?.selection_end,
          last_active: (/* @__PURE__ */ new Date()).toISOString()
        });
        return next;
      });
      if (status === "disconnected") {
        setCursors((prev) => {
          const next = new Map(prev);
          next.delete(userId);
          return next;
        });
      }
    };
    const handleError = (code, message) => {
      setError({ code, message });
    };
    client.on("connected", handleConnected);
    client.on("disconnected", handleDisconnected);
    client.on("operation", handleOperation);
    client.on("conflict", handleConflict);
    client.on("cursor", handleCursor);
    client.on("presence", handlePresence);
    client.on("error", handleError);
    return () => {
      client.disconnect();
      client.removeAllListeners();
      clientRef.current = null;
    };
  }, [config.baseUrl, config.userId, config.sessionId]);
  react.useEffect(() => {
    if (clientRef.current && documentId) {
      setConnectionState("connecting" /* Connecting */);
      clientRef.current.connect(documentId);
    }
  }, [documentId, clientVersion]);
  const sendEdit = react.useCallback(
    (type, position, content, length) => {
      if (!clientRef.current) return "";
      return clientRef.current.sendEdit({
        operation_type: type,
        position,
        content,
        length
      });
    },
    []
  );
  const insert = react.useCallback(
    (position, content) => {
      return sendEdit("insert", position, content);
    },
    [sendEdit]
  );
  const deleteOp = react.useCallback(
    (position, length) => {
      return sendEdit("delete", position, "", length);
    },
    [sendEdit]
  );
  const replace = react.useCallback(
    (position, length, content) => {
      return sendEdit("replace", position, content, length);
    },
    [sendEdit]
  );
  const updateCursor = react.useCallback((position, selectionEnd) => {
    clientRef.current?.sendCursor(position, selectionEnd);
  }, []);
  const reconnect = react.useCallback(() => {
    if (clientRef.current && documentId) {
      clientRef.current.connect(documentId);
    }
  }, [documentId]);
  const disconnect = react.useCallback(() => {
    clientRef.current?.disconnect();
  }, []);
  return {
    document: document2,
    connectionState,
    isConnected: connectionState === "connected" /* Connected */,
    sendEdit,
    insert,
    delete: deleteOp,
    replace,
    updateCursor,
    cursors,
    presence,
    operations,
    error,
    reconnect,
    disconnect
  };
}
function useCollabApi(config) {
  const apiRef = react.useRef(null);
  if (!apiRef.current) {
    apiRef.current = createCollabApi(config);
  }
  return apiRef.current;
}
function useProjectSettings(options) {
  const { api, projectId, autoFetch = true } = options;
  const [settings, setSettings] = react.useState(null);
  const [isLoading, setIsLoading] = react.useState(false);
  const [error, setError] = react.useState(null);
  const refetch = react.useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const result = await api.getProjectSettings(projectId);
      setSettings(result);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setIsLoading(false);
    }
  }, [api, projectId]);
  react.useEffect(() => {
    if (autoFetch && projectId) {
      refetch();
    }
  }, [autoFetch, projectId, refetch]);
  return { settings, isLoading, error, refetch };
}
function useUpdateProjectSettings(options) {
  const { api, projectId, onSuccess, onError } = options;
  const [isUpdating, setIsUpdating] = react.useState(false);
  const [error, setError] = react.useState(null);
  const update = react.useCallback(
    async (updates) => {
      setIsUpdating(true);
      setError(null);
      try {
        const result = await api.updateProjectSettings(projectId, updates);
        onSuccess?.(result);
        return result;
      } catch (err) {
        const error2 = err instanceof Error ? err : new Error(String(err));
        setError(error2);
        onError?.(error2);
        return null;
      } finally {
        setIsUpdating(false);
      }
    },
    [api, projectId, onSuccess, onError]
  );
  return { update, isUpdating, error };
}
function useValidateGitHubRepo(options) {
  const { api, projectId } = options;
  const [isValidating, setIsValidating] = react.useState(false);
  const [result, setResult] = react.useState(null);
  const [error, setError] = react.useState(null);
  const validate = react.useCallback(
    async (request) => {
      setIsValidating(true);
      setError(null);
      try {
        const response = await api.validateGitHubRepository(projectId, request);
        setResult(response);
        return response;
      } catch (err) {
        const error2 = err instanceof Error ? err : new Error(String(err));
        setError(error2);
        return null;
      } finally {
        setIsValidating(false);
      }
    },
    [api, projectId]
  );
  return { validate, isValidating, result, error };
}
function useGitHubBranches(options) {
  const { api, projectId, autoFetch = false } = options;
  const [branches, setBranches] = react.useState(null);
  const [isLoading, setIsLoading] = react.useState(false);
  const [error, setError] = react.useState(null);
  const refetch = react.useCallback(
    async (page = 1, perPage = 30) => {
      setIsLoading(true);
      setError(null);
      try {
        const result = await api.listGitHubBranches(projectId, page, perPage);
        setBranches(result);
      } catch (err) {
        setError(err instanceof Error ? err : new Error(String(err)));
      } finally {
        setIsLoading(false);
      }
    },
    [api, projectId]
  );
  react.useEffect(() => {
    if (autoFetch && projectId) {
      refetch();
    }
  }, [autoFetch, projectId, refetch]);
  return { branches, isLoading, error, refetch };
}

// src/components/execution/executionStyles.ts
var EXECUTION_STYLE_ID = "ga-execution-ui-styles";
var EXECUTION_STYLES = `
.ga-exec-panel {
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(12px);
  border-radius: var(--radius-2xl);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.ga-exec-panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.ga-exec-panel-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.ga-exec-panel-title {
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--color-text-primary);
}

.ga-exec-panel-subtitle {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  margin-top: var(--space-1);
}

.ga-exec-status-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.ga-exec-status-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  border-radius: var(--radius-full);
  padding: 2px var(--space-2);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  border: 1px solid rgba(15, 23, 42, 0.1);
  background: rgba(15, 23, 42, 0.04);
  color: var(--color-text-secondary);
}

.ga-exec-status-dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  background: var(--color-text-tertiary);
}

.ga-exec-status-badge.ga-exec-running {
  border-color: rgba(34, 197, 94, 0.35);
  background: rgba(34, 197, 94, 0.12);
  color: var(--color-text-primary);
}

.ga-exec-status-badge.ga-exec-running .ga-exec-status-dot {
  background: var(--color-success);
  animation: ga-exec-pulse 2s ease-in-out infinite;
}

.ga-exec-status-badge.ga-exec-paused {
  border-color: rgba(245, 158, 11, 0.35);
  background: rgba(245, 158, 11, 0.12);
  color: var(--color-text-primary);
}

.ga-exec-status-badge.ga-exec-paused .ga-exec-status-dot {
  background: var(--color-warning);
}

.ga-exec-status-badge.ga-exec-failed,
.ga-exec-status-badge.ga-exec-cancelled {
  border-color: rgba(239, 68, 68, 0.28);
  background: rgba(239, 68, 68, 0.12);
  color: var(--color-text-primary);
}

.ga-exec-status-badge.ga-exec-failed .ga-exec-status-dot,
.ga-exec-status-badge.ga-exec-cancelled .ga-exec-status-dot {
  background: var(--color-error);
}

.ga-exec-status-badge.ga-exec-completed {
  border-color: rgba(59, 130, 246, 0.25);
  background: rgba(59, 130, 246, 0.12);
  color: var(--color-text-primary);
}

.ga-exec-status-badge.ga-exec-completed .ga-exec-status-dot {
  background: var(--color-accent);
}

.ga-exec-status-badge.ga-exec-pending {
  border-color: rgba(14, 165, 233, 0.28);
  background: rgba(14, 165, 233, 0.12);
  color: var(--color-text-primary);
}

.ga-exec-status-badge.ga-exec-pending .ga-exec-status-dot {
  background: #0ea5e9;
}

.ga-exec-phase-pill {
  display: inline-flex;
  align-items: center;
  border-radius: var(--radius-full);
  padding: 2px var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(255, 255, 255, 0.7);
}

.ga-exec-progress {
  width: 100%;
  height: 6px;
  border-radius: var(--radius-full);
  background: rgba(15, 23, 42, 0.08);
  overflow: hidden;
}

.ga-exec-progress-fill {
  height: 100%;
  border-radius: var(--radius-full);
  background: rgba(59, 130, 246, 0.75);
  transition: transform var(--duration-normal) var(--ease-out-expo);
  transform-origin: left center;
}

.ga-exec-progress-fill.ga-exec-progress-running {
  background: rgba(34, 197, 94, 0.75);
}

.ga-exec-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--space-2);
}

.ga-exec-meta-item {
  border-radius: var(--radius-lg);
  border: 1px solid rgba(15, 23, 42, 0.08);
  padding: var(--space-2) var(--space-3);
  background: rgba(255, 255, 255, 0.7);
}

.ga-exec-meta-label {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.ga-exec-meta-value {
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  font-weight: var(--font-medium);
}

.ga-exec-current-step {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
}

.ga-exec-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.ga-exec-empty {
  border-radius: var(--radius-xl);
  border: 1px dashed rgba(15, 23, 42, 0.12);
  padding: var(--space-4);
  color: var(--color-text-tertiary);
  background: rgba(255, 255, 255, 0.6);
}

.ga-exec-timeline {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.ga-exec-filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.ga-exec-filter-select {
  border-radius: var(--radius-lg);
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: rgba(255, 255, 255, 0.85);
  padding: 4px var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.ga-exec-phase-group {
  border-radius: var(--radius-xl);
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(255, 255, 255, 0.75);
  overflow: hidden;
}

.ga-exec-phase-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-3);
  background: rgba(59, 130, 246, 0.06);
  cursor: pointer;
}

.ga-exec-phase-title {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--color-text-primary);
}

.ga-exec-phase-meta {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.ga-exec-step-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
}

.ga-exec-step {
  display: grid;
  grid-template-columns: 12px 1fr;
  gap: var(--space-2);
}

.ga-exec-step-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: rgba(59, 130, 246, 0.6);
  margin-top: 6px;
}

.ga-exec-step[data-step-type='error'] .ga-exec-step-dot {
  background: var(--color-error);
}

.ga-exec-step[data-step-type='clarification_sent'] .ga-exec-step-dot,
.ga-exec-step[data-step-type='clarification_received'] .ga-exec-step-dot {
  background: var(--color-warning);
}

.ga-exec-step[data-step-type='tool_call'] .ga-exec-step-dot,
.ga-exec-step[data-step-type='tool_result'] .ga-exec-step-dot {
  background: rgba(14, 165, 233, 0.7);
}

.ga-exec-step-card {
  border-radius: var(--radius-lg);
  border: 1px solid rgba(15, 23, 42, 0.08);
  padding: var(--space-2) var(--space-3);
  background: rgba(255, 255, 255, 0.85);
}

.ga-exec-step-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  justify-content: space-between;
}

.ga-exec-step-type {
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--color-text-primary);
}

.ga-exec-step-time {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.ga-exec-step-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  margin-top: 2px;
}

.ga-exec-step-preview {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin-top: var(--space-2);
  line-height: var(--leading-relaxed);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

@keyframes ga-exec-pulse {
  0% { transform: scale(1); opacity: 0.7; }
  50% { transform: scale(1.3); opacity: 0.3; }
  100% { transform: scale(1); opacity: 0.7; }
}

@media (max-width: 900px) {
  .ga-exec-panel {
    padding: var(--space-3);
  }

  .ga-exec-meta {
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  }
}
`;
function ensureExecutionStyles() {
  if (typeof document === "undefined") return;
  if (document.getElementById(EXECUTION_STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = EXECUTION_STYLE_ID;
  style.textContent = EXECUTION_STYLES;
  document.head.appendChild(style);
}

// src/components/execution/executionUtils.ts
var STATE_LABELS = {
  pending: "Pending",
  running: "Running",
  paused: "Paused",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
  unknown: "Unknown"
};
function normalizeExecutionState(state) {
  if (!state) return "unknown";
  const normalized = state.toLowerCase();
  if (normalized === "pending" || normalized === "running" || normalized === "paused" || normalized === "completed" || normalized === "failed" || normalized === "cancelled") {
    return normalized;
  }
  return "unknown";
}
function formatExecutionStateLabel(state) {
  const normalized = normalizeExecutionState(state);
  return STATE_LABELS[normalized] ?? "Unknown";
}
function formatPhaseLabel(phase) {
  if (!phase) return "No phase";
  const normalized = phase.replace(/_/g, " ").trim().toLowerCase();
  if (!normalized) return "No phase";
  return normalized.split(" ").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
}
function clampProgress(progress) {
  if (typeof progress !== "number" || Number.isNaN(progress)) return 0;
  if (progress < 0) return 0;
  if (progress > 100) return 100;
  return progress;
}
function formatTimestamp(value) {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function formatRelativeTime(value) {
  if (!value) return "Unknown";
  const date = new Date(value);
  const ts = date.getTime();
  if (Number.isNaN(ts)) return "Unknown";
  const now = Date.now();
  const diffMs = now - ts;
  const diffSec = Math.floor(diffMs / 1e3);
  if (diffSec < 20) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}
function formatDuration(startedAt, completedAt) {
  if (!startedAt || !completedAt) return "";
  const start = new Date(startedAt).getTime();
  const end = new Date(completedAt).getTime();
  if (Number.isNaN(start) || Number.isNaN(end)) return "";
  const durationMs = Math.max(end - start, 0);
  const seconds = Math.floor(durationMs / 1e3);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h`;
}
function ExecutionStatusBadge({
  state,
  phase,
  statusLabel,
  phaseLabel,
  progressPct,
  showPhase = true,
  showProgress = true,
  className
}) {
  react.useEffect(() => {
    ensureExecutionStyles();
  }, []);
  const normalizedState = react.useMemo(() => normalizeExecutionState(state ?? void 0), [state]);
  const progress = react.useMemo(() => clampProgress(progressPct), [progressPct]);
  const stateLabel = react.useMemo(
    () => statusLabel ?? formatExecutionStateLabel(normalizedState),
    [normalizedState, statusLabel]
  );
  const resolvedPhaseLabel = react.useMemo(() => {
    if (phaseLabel) return phaseLabel;
    if (!phase) return null;
    return formatPhaseLabel(phase);
  }, [phase, phaseLabel]);
  return /* @__PURE__ */ jsxRuntime.jsxs(
    "div",
    {
      className: `ga-exec-status-badge ga-exec-${normalizedState} ${className ?? ""}`.trim(),
      "aria-label": `Execution status ${stateLabel}`,
      children: [
        /* @__PURE__ */ jsxRuntime.jsx("span", { className: "ga-exec-status-dot", "aria-hidden": "true" }),
        /* @__PURE__ */ jsxRuntime.jsx("span", { children: stateLabel }),
        showPhase && resolvedPhaseLabel && /* @__PURE__ */ jsxRuntime.jsx("span", { className: "ga-exec-phase-pill", "aria-label": `Phase ${resolvedPhaseLabel}`, children: resolvedPhaseLabel }),
        showProgress && /* @__PURE__ */ jsxRuntime.jsx("span", { className: "ga-exec-progress", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": progress, children: /* @__PURE__ */ jsxRuntime.jsx(
          "span",
          {
            className: `ga-exec-progress-fill ${normalizedState === "running" ? "ga-exec-progress-running" : ""}`,
            style: { transform: `scaleX(${progress / 100})` }
          }
        ) })
      ]
    }
  );
}
function ExecutionStatusCard({
  status,
  isLoading = false,
  title = "Execution",
  subtitle,
  actions,
  emptyLabel = "No execution has started yet.",
  className
}) {
  react.useEffect(() => {
    ensureExecutionStyles();
  }, []);
  const hasExecution = Boolean(status?.hasExecution);
  const normalizedState = react.useMemo(() => normalizeExecutionState(status?.state ?? void 0), [status?.state]);
  const stateLabel = react.useMemo(() => formatExecutionStateLabel(normalizedState), [normalizedState]);
  const progress = react.useMemo(() => clampProgress(status?.progressPct ?? 0), [status?.progressPct]);
  const startedLabel = react.useMemo(() => formatRelativeTime(status?.startedAt ?? void 0), [status?.startedAt]);
  const tokenLabel = react.useMemo(() => {
    if (typeof status?.totalTokens === "number") return status.totalTokens.toLocaleString();
    return "--";
  }, [status?.totalTokens]);
  const costLabel = react.useMemo(() => {
    if (typeof status?.totalCostUsd === "number") return `$${status.totalCostUsd.toFixed(3)}`;
    return "--";
  }, [status?.totalCostUsd]);
  return /* @__PURE__ */ jsxRuntime.jsxs("section", { className: `ga-exec-panel ${className ?? ""}`.trim(), "aria-live": "polite", children: [
    /* @__PURE__ */ jsxRuntime.jsxs("header", { className: "ga-exec-panel-header", children: [
      /* @__PURE__ */ jsxRuntime.jsxs("div", { children: [
        /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-exec-panel-title", children: title }),
        subtitle && /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-exec-panel-subtitle", children: subtitle })
      ] }),
      actions && /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-exec-actions", children: actions })
    ] }),
    isLoading && /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-exec-empty", "aria-label": "Loading execution status", children: "Loading execution status..." }),
    !isLoading && !hasExecution && /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-exec-empty", "aria-label": "No execution", children: emptyLabel }),
    !isLoading && hasExecution && /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-exec-panel-body", children: [
      /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-exec-status-row", children: /* @__PURE__ */ jsxRuntime.jsx(
        ExecutionStatusBadge,
        {
          state: normalizedState,
          phase: status?.phase ?? null,
          progressPct: progress,
          showPhase: true,
          showProgress: false
        }
      ) }),
      /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-exec-progress", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": progress, children: /* @__PURE__ */ jsxRuntime.jsx(
        "span",
        {
          className: `ga-exec-progress-fill ${normalizedState === "running" ? "ga-exec-progress-running" : ""}`,
          style: { transform: `scaleX(${progress / 100})` }
        }
      ) }),
      status?.currentStep && /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-exec-current-step", children: [
        /* @__PURE__ */ jsxRuntime.jsxs("strong", { children: [
          stateLabel,
          ":"
        ] }),
        " ",
        status.currentStep
      ] }),
      /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-exec-meta", children: [
        /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-exec-meta-item", children: [
          /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-exec-meta-label", children: "Started" }),
          /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-exec-meta-value", children: startedLabel })
        ] }),
        /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-exec-meta-item", children: [
          /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-exec-meta-label", children: "Progress" }),
          /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-exec-meta-value", children: [
            progress.toFixed(0),
            "%"
          ] })
        ] }),
        /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-exec-meta-item", children: [
          /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-exec-meta-label", children: "Tokens" }),
          /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-exec-meta-value", children: tokenLabel })
        ] }),
        /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-exec-meta-item", children: [
          /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-exec-meta-label", children: "Cost" }),
          /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-exec-meta-value", children: costLabel })
        ] })
      ] })
    ] })
  ] });
}
var STEP_LABELS = {
  phase_start: "Phase start",
  phase_end: "Phase end",
  phase_transition: "Phase transition",
  llm_request: "LLM request",
  llm_response: "LLM response",
  tool_call: "Tool call",
  tool_result: "Tool result",
  clarification_sent: "Clarification sent",
  clarification_received: "Clarification received",
  file_change: "File change",
  pr_created: "PR created",
  error: "Error",
  gate_waiting: "Gate waiting",
  gate_approved: "Gate approved",
  model_switch: "Model switch"
};
function formatStepLabel(stepType) {
  if (!stepType) return "Step";
  return STEP_LABELS[stepType] ?? stepType.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
function isMarkdownContent(text) {
  const hasHeaders = /^#{1,3}\s/m.test(text);
  const hasTables = /\|.+\|.+\|/m.test(text);
  const hasBold = /\*\*.+\*\*/m.test(text);
  const hasLists = /^[-*]\s/m.test(text);
  const indicators = [hasHeaders, hasTables, hasBold, hasLists].filter(Boolean).length;
  return indicators >= 2 || hasHeaders;
}
function parseStepContent(contentFull) {
  if (!contentFull) return null;
  try {
    const parsed = JSON.parse(contentFull);
    return {
      text: typeof parsed.text === "string" ? parsed.text : void 0,
      toolName: typeof parsed.tool_name === "string" ? parsed.tool_name : void 0,
      inputs: typeof parsed.inputs === "object" && parsed.inputs !== null ? parsed.inputs : void 0,
      output: parsed.output,
      success: typeof parsed.success === "boolean" ? parsed.success : void 0,
      error: typeof parsed.error === "string" ? parsed.error : void 0,
      raw: contentFull
    };
  } catch {
    return { raw: contentFull };
  }
}
function ExecutionTimeline({
  steps = [],
  activePhase,
  isLoading = false,
  emptyLabel = "No execution steps yet.",
  className
}) {
  react.useEffect(() => {
    ensureExecutionStyles();
  }, []);
  const phases = react.useMemo(() => {
    const order = [];
    const buckets = /* @__PURE__ */ new Map();
    steps.forEach((step) => {
      const phase = step.phase || "Unknown";
      if (!buckets.has(phase)) {
        buckets.set(phase, []);
        order.push(phase);
      }
      buckets.get(phase)?.push(step);
    });
    return order.map((phase) => ({ phase, steps: buckets.get(phase) ?? [] }));
  }, [steps]);
  const phaseOptions = react.useMemo(() => ["all", ...new Set(phases.map((group) => group.phase))], [phases]);
  const stepTypeOptions = react.useMemo(() => {
    const unique = new Set(steps.map((step) => step.stepType).filter(Boolean));
    return ["all", ...Array.from(unique)];
  }, [steps]);
  const [phaseFilter, setPhaseFilter] = react.useState("all");
  const [stepTypeFilter, setStepTypeFilter] = react.useState("all");
  const [collapsed, setCollapsed] = react.useState({});
  const [expandedSteps, setExpandedSteps] = react.useState({});
  const toggleStepExpand = (stepId) => {
    setExpandedSteps((prev) => ({
      ...prev,
      [stepId]: !prev[stepId]
    }));
  };
  const filteredPhases = react.useMemo(() => {
    return phases.filter((group) => phaseFilter === "all" || group.phase === phaseFilter).map((group) => ({
      ...group,
      steps: group.steps.filter(
        (step) => stepTypeFilter === "all" || step.stepType === stepTypeFilter
      )
    })).filter((group) => group.steps.length > 0);
  }, [phaseFilter, phases, stepTypeFilter]);
  const togglePhase = (phase) => {
    setCollapsed((prev) => ({
      ...prev,
      [phase]: !prev[phase]
    }));
  };
  if (isLoading) {
    return /* @__PURE__ */ jsxRuntime.jsx("div", { className: `ga-exec-panel ${className ?? ""}`.trim(), "aria-label": "Loading execution timeline", children: /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-exec-empty", children: "Loading execution timeline..." }) });
  }
  if (!steps.length) {
    return /* @__PURE__ */ jsxRuntime.jsx("div", { className: `ga-exec-panel ${className ?? ""}`.trim(), "aria-label": "Execution timeline", children: /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-exec-empty", children: emptyLabel }) });
  }
  return /* @__PURE__ */ jsxRuntime.jsxs("div", { className: `ga-exec-timeline ${className ?? ""}`.trim(), children: [
    /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-exec-filter-row", children: [
      /* @__PURE__ */ jsxRuntime.jsx(
        "select",
        {
          className: "ga-exec-filter-select",
          value: phaseFilter,
          onChange: (event) => setPhaseFilter(event.target.value),
          "aria-label": "Filter by phase",
          children: phaseOptions.map((phase) => /* @__PURE__ */ jsxRuntime.jsx("option", { value: phase, children: phase === "all" ? "All phases" : formatPhaseLabel(phase) }, phase))
        }
      ),
      /* @__PURE__ */ jsxRuntime.jsx(
        "select",
        {
          className: "ga-exec-filter-select",
          value: stepTypeFilter,
          onChange: (event) => setStepTypeFilter(event.target.value),
          "aria-label": "Filter by step type",
          children: stepTypeOptions.map((stepType) => /* @__PURE__ */ jsxRuntime.jsx("option", { value: stepType, children: stepType === "all" ? "All step types" : formatStepLabel(stepType) }, stepType))
        }
      )
    ] }),
    filteredPhases.map((group) => {
      const isCollapsed = collapsed[group.phase] && group.phase !== activePhase;
      const phaseId = `phase-${group.phase.replace(/[^a-z0-9-]/gi, "-")}`;
      return /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-exec-phase-group", children: [
        /* @__PURE__ */ jsxRuntime.jsxs(
          "button",
          {
            type: "button",
            className: "ga-exec-phase-header",
            onClick: () => togglePhase(group.phase),
            "aria-expanded": !isCollapsed,
            "aria-controls": phaseId,
            children: [
              /* @__PURE__ */ jsxRuntime.jsx("span", { className: "ga-exec-phase-title", children: formatPhaseLabel(group.phase) }),
              /* @__PURE__ */ jsxRuntime.jsxs("span", { className: "ga-exec-phase-meta", children: [
                group.steps.length,
                " steps",
                group.phase === activePhase ? " (active)" : ""
              ] })
            ]
          }
        ),
        !isCollapsed && /* @__PURE__ */ jsxRuntime.jsx("div", { id: phaseId, className: "ga-exec-step-list", children: group.steps.map((step) => {
          const isExpanded = expandedSteps[step.stepId];
          const parsedContent = parseStepContent(step.contentFull);
          const hasDetail = !!step.contentFull;
          return /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-exec-step", "data-step-type": step.stepType, children: [
            /* @__PURE__ */ jsxRuntime.jsx("span", { className: "ga-exec-step-dot", "aria-hidden": "true" }),
            /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-exec-step-card", children: [
              /* @__PURE__ */ jsxRuntime.jsxs(
                "button",
                {
                  type: "button",
                  className: "ga-exec-step-header",
                  onClick: () => hasDetail && toggleStepExpand(step.stepId),
                  style: { cursor: hasDetail ? "pointer" : "default", width: "100%", background: "none", border: "none", textAlign: "left", padding: 0 },
                  "aria-expanded": isExpanded,
                  disabled: !hasDetail,
                  children: [
                    /* @__PURE__ */ jsxRuntime.jsxs("span", { className: "ga-exec-step-type", children: [
                      formatStepLabel(step.stepType),
                      hasDetail && /* @__PURE__ */ jsxRuntime.jsx("span", { style: { marginLeft: "4px", opacity: 0.6 }, children: isExpanded ? "\u25BC" : "\u25B6" })
                    ] }),
                    /* @__PURE__ */ jsxRuntime.jsxs("span", { className: "ga-exec-step-time", children: [
                      formatTimestamp(step.startedAt),
                      formatDuration(step.startedAt, step.completedAt) ? ` \xB7 ${formatDuration(step.startedAt, step.completedAt)}` : ""
                    ] })
                  ]
                }
              ),
              /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-exec-step-meta", children: [
                /* @__PURE__ */ jsxRuntime.jsxs("span", { children: [
                  "Input ",
                  step.inputTokens ?? 0,
                  " tokens"
                ] }),
                /* @__PURE__ */ jsxRuntime.jsxs("span", { children: [
                  "Output ",
                  step.outputTokens ?? 0,
                  " tokens"
                ] }),
                step.toolCalls ? /* @__PURE__ */ jsxRuntime.jsxs("span", { children: [
                  "Tool calls ",
                  step.toolCalls
                ] }) : null,
                step.modelId && /* @__PURE__ */ jsxRuntime.jsxs("span", { children: [
                  "Model: ",
                  step.modelId
                ] })
              ] }),
              !isExpanded && step.contentPreview && /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-exec-step-preview", children: step.contentPreview }),
              isExpanded && parsedContent && /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-exec-step-detail", style: { marginTop: "8px", fontSize: "13px" }, children: [
                parsedContent.text && /* @__PURE__ */ jsxRuntime.jsxs("div", { style: { marginBottom: "8px" }, children: [
                  /* @__PURE__ */ jsxRuntime.jsx("strong", { children: "Agent Response:" }),
                  isMarkdownContent(parsedContent.text) ? /* @__PURE__ */ jsxRuntime.jsx("div", { style: { background: "var(--vscode-editor-background, #1e1e1e)", padding: "8px", borderRadius: "4px", maxHeight: "400px", overflow: "auto", marginTop: "4px", lineHeight: 1.5 }, className: "ga-exec-markdown", children: /* @__PURE__ */ jsxRuntime.jsx(Markdown__default.default, { remarkPlugins: [remarkGfm__default.default], children: parsedContent.text }) }) : /* @__PURE__ */ jsxRuntime.jsx("pre", { style: { whiteSpace: "pre-wrap", background: "var(--vscode-editor-background, #1e1e1e)", padding: "8px", borderRadius: "4px", maxHeight: "300px", overflow: "auto", marginTop: "4px" }, children: parsedContent.text })
                ] }),
                parsedContent.toolName && /* @__PURE__ */ jsxRuntime.jsxs("div", { style: { marginBottom: "8px" }, children: [
                  /* @__PURE__ */ jsxRuntime.jsx("strong", { children: "Tool:" }),
                  " ",
                  /* @__PURE__ */ jsxRuntime.jsx("code", { children: parsedContent.toolName }),
                  parsedContent.success !== void 0 && /* @__PURE__ */ jsxRuntime.jsx("span", { style: { marginLeft: "8px", color: parsedContent.success ? "#4caf50" : "#f44336" }, children: parsedContent.success ? "\u2713 Success" : "\u2717 Failed" })
                ] }),
                parsedContent.inputs && Object.keys(parsedContent.inputs).length > 0 && /* @__PURE__ */ jsxRuntime.jsxs("div", { style: { marginBottom: "8px" }, children: [
                  /* @__PURE__ */ jsxRuntime.jsx("strong", { children: "Inputs:" }),
                  /* @__PURE__ */ jsxRuntime.jsx("pre", { style: { whiteSpace: "pre-wrap", background: "var(--vscode-editor-background, #1e1e1e)", padding: "8px", borderRadius: "4px", maxHeight: "200px", overflow: "auto", marginTop: "4px" }, children: JSON.stringify(parsedContent.inputs, null, 2) })
                ] }),
                parsedContent.output !== void 0 && parsedContent.output !== null && /* @__PURE__ */ jsxRuntime.jsxs("div", { style: { marginBottom: "8px" }, children: [
                  /* @__PURE__ */ jsxRuntime.jsx("strong", { children: "Output:" }),
                  /* @__PURE__ */ jsxRuntime.jsx("pre", { style: { whiteSpace: "pre-wrap", background: "var(--vscode-editor-background, #1e1e1e)", padding: "8px", borderRadius: "4px", maxHeight: "200px", overflow: "auto", marginTop: "4px" }, children: String(typeof parsedContent.output === "string" ? parsedContent.output : JSON.stringify(parsedContent.output, null, 2)) })
                ] }),
                parsedContent.error && /* @__PURE__ */ jsxRuntime.jsxs("div", { style: { marginBottom: "8px", color: "#f44336" }, children: [
                  /* @__PURE__ */ jsxRuntime.jsx("strong", { children: "Error:" }),
                  " ",
                  parsedContent.error
                ] }),
                step.toolNames && step.toolNames.length > 0 && /* @__PURE__ */ jsxRuntime.jsxs("div", { style: { marginBottom: "8px" }, children: [
                  /* @__PURE__ */ jsxRuntime.jsx("strong", { children: "Tools used:" }),
                  " ",
                  step.toolNames.join(", ")
                ] })
              ] })
            ] })
          ] }, step.stepId);
        }) })
      ] }, group.phase);
    })
  ] });
}
var CLARIFICATION_STYLE_ID = "ga-clarification-ui-styles";
var CLARIFICATION_STYLES = `
.ga-clar-panel {
  border-radius: var(--radius-xl, 12px);
  border: 1px solid rgba(245, 158, 11, 0.25);
  background: linear-gradient(
    135deg,
    rgba(255, 251, 235, 0.95) 0%,
    rgba(254, 243, 199, 0.85) 100%
  );
  backdrop-filter: blur(12px);
  padding: var(--space-4, 16px);
  display: flex;
  flex-direction: column;
  gap: var(--space-3, 12px);
  opacity: 0;
  transform: translateY(8px);
  animation: ga-clar-fade-in 0.3s var(--ease-out-expo, cubic-bezier(0.16, 1, 0.3, 1)) forwards;
}

@keyframes ga-clar-fade-in {
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.ga-clar-header {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
}

.ga-clar-icon {
  width: 24px;
  height: 24px;
  border-radius: var(--radius-full, 9999px);
  background: rgba(245, 158, 11, 0.2);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  flex-shrink: 0;
}

.ga-clar-title {
  font-size: var(--text-sm, 0.8125rem);
  font-weight: var(--font-semibold, 600);
  color: var(--color-text-primary, #0f172a);
}

.ga-clar-subtitle {
  font-size: var(--text-xs, 0.75rem);
  color: var(--color-text-tertiary, #64748b);
  margin-left: auto;
}

.ga-clar-questions {
  display: flex;
  flex-direction: column;
  gap: var(--space-3, 12px);
}

.ga-clar-card {
  border-radius: var(--radius-lg, 8px);
  border: 1px solid rgba(15, 23, 42, 0.1);
  background: rgba(255, 255, 255, 0.9);
  padding: var(--space-4, 16px);
  display: flex;
  flex-direction: column;
  gap: var(--space-3, 12px);
  opacity: 0;
  transform: translateY(6px);
  animation: ga-clar-card-in 0.25s var(--ease-out-expo, cubic-bezier(0.16, 1, 0.3, 1)) forwards;
}

.ga-clar-card:nth-child(1) { animation-delay: 0.05s; }
.ga-clar-card:nth-child(2) { animation-delay: 0.1s; }
.ga-clar-card:nth-child(3) { animation-delay: 0.15s; }
.ga-clar-card:nth-child(4) { animation-delay: 0.2s; }

@keyframes ga-clar-card-in {
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.ga-clar-question-header {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2, 8px);
}

.ga-clar-question-number {
  width: 22px;
  height: 22px;
  border-radius: var(--radius-full, 9999px);
  background: rgba(59, 130, 246, 0.15);
  color: var(--color-accent, #3b82f6);
  font-size: 11px;
  font-weight: var(--font-semibold, 600);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.ga-clar-question-text {
  font-size: var(--text-sm, 0.8125rem);
  color: var(--color-text-primary, #0f172a);
  line-height: var(--leading-relaxed, 1.625);
  flex: 1;
}

.ga-clar-question-text strong {
  font-weight: var(--font-semibold, 600);
}

.ga-clar-context {
  font-size: var(--text-xs, 0.75rem);
  color: var(--color-text-tertiary, #64748b);
  padding: var(--space-2, 8px) var(--space-3, 12px);
  border-radius: var(--radius-md, 6px);
  background: rgba(15, 23, 42, 0.04);
  border-left: 2px solid rgba(59, 130, 246, 0.4);
}

.ga-clar-input-wrapper {
  position: relative;
}

.ga-clar-input {
  width: 100%;
  border-radius: var(--radius-lg, 8px);
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: rgba(255, 255, 255, 0.95);
  padding: var(--space-3, 12px);
  padding-right: 100px;
  color: var(--color-text-primary, #0f172a);
  font-size: var(--text-sm, 0.8125rem);
  line-height: var(--leading-relaxed, 1.625);
  resize: vertical;
  min-height: 80px;
  transition:
    border-color 0.15s cubic-bezier(0.16, 1, 0.3, 1),
    box-shadow 0.15s cubic-bezier(0.16, 1, 0.3, 1);
}

.ga-clar-input::placeholder {
  color: var(--color-text-disabled, #94a3b8);
}

.ga-clar-input:hover {
  border-color: rgba(15, 23, 42, 0.2);
}

.ga-clar-input:focus {
  outline: none;
  border-color: var(--color-accent, #3b82f6);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
}

.ga-clar-actions {
  position: absolute;
  bottom: var(--space-2, 8px);
  right: var(--space-2, 8px);
  display: flex;
  gap: var(--space-2, 8px);
}

.ga-clar-submit {
  border-radius: var(--radius-lg, 8px);
  border: none;
  background: var(--color-accent, #3b82f6);
  color: white;
  padding: var(--space-2, 8px) var(--space-3, 12px);
  font-size: var(--text-xs, 0.75rem);
  font-weight: var(--font-medium, 500);
  cursor: pointer;
  transition:
    background-color 0.1s cubic-bezier(0.16, 1, 0.3, 1),
    transform 0.15s cubic-bezier(0.34, 1.56, 0.64, 1),
    opacity 0.1s;
  will-change: transform;
}

.ga-clar-submit:hover:not(:disabled) {
  background: var(--color-accent-hover, #60a5fa);
  transform: translateY(-1px);
}

.ga-clar-submit:active:not(:disabled) {
  transform: translateY(0) scale(0.98);
}

.ga-clar-submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ga-clar-submit.ga-clar-submitting {
  position: relative;
  color: transparent;
}

.ga-clar-submit.ga-clar-submitting::after {
  content: '';
  position: absolute;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: ga-clar-spin 0.6s linear infinite;
  left: 50%;
  top: 50%;
  margin-left: -7px;
  margin-top: -7px;
}

@keyframes ga-clar-spin {
  to { transform: rotate(360deg); }
}

.ga-clar-hint {
  font-size: var(--text-xs, 0.75rem);
  color: var(--color-text-tertiary, #64748b);
  display: flex;
  align-items: center;
  gap: var(--space-1, 4px);
}

.ga-clar-hint kbd {
  border-radius: var(--radius-sm, 4px);
  border: 1px solid rgba(15, 23, 42, 0.15);
  background: rgba(15, 23, 42, 0.04);
  padding: 1px 4px;
  font-family: var(--font-mono, monospace);
  font-size: 10px;
}

.ga-clar-empty {
  border-radius: var(--radius-xl, 12px);
  border: 1px dashed rgba(15, 23, 42, 0.15);
  background: rgba(255, 255, 255, 0.6);
  padding: var(--space-4, 16px);
  color: var(--color-text-tertiary, #64748b);
  font-size: var(--text-sm, 0.8125rem);
  text-align: center;
}

.ga-clar-success {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
  padding: var(--space-2, 8px) var(--space-3, 12px);
  border-radius: var(--radius-lg, 8px);
  background: rgba(34, 197, 94, 0.12);
  border: 1px solid rgba(34, 197, 94, 0.25);
  color: var(--color-text-primary, #0f172a);
  font-size: var(--text-sm, 0.8125rem);
  opacity: 0;
  transform: translateY(-4px);
  animation: ga-clar-success-in 0.3s var(--ease-spring, cubic-bezier(0.34, 1.56, 0.64, 1)) forwards;
}

@keyframes ga-clar-success-in {
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.ga-clar-success-icon {
  width: 18px;
  height: 18px;
  border-radius: var(--radius-full, 9999px);
  background: rgba(34, 197, 94, 0.2);
  color: var(--color-success, #22c55e);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
}
`;
function ensureClarificationStyles() {
  if (typeof document === "undefined") return;
  if (document.getElementById(CLARIFICATION_STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = CLARIFICATION_STYLE_ID;
  style.textContent = CLARIFICATION_STYLES;
  document.head.appendChild(style);
}
function extractConciseQuestion(text) {
  const numberedPattern = /\d+\.\s*\*\*([^*]+)\*\*:?\s*([^\n]+)/g;
  const numberedMatches = [...text.matchAll(numberedPattern)];
  if (numberedMatches.length > 0) {
    const questions = numberedMatches.map((m) => `**${m[1].trim()}**: ${m[2].trim()}`).join("\n");
    return { summary: questions, details: null };
  }
  const clarSection = text.match(/##\s*Clarifications? Needed\s*([\s\S]*?)(?:\n##|$)/i);
  if (clarSection) {
    const content = clarSection[1].trim();
    const lines = content.split("\n").filter((l) => l.trim().startsWith("-") || l.trim().match(/^\d+\./));
    if (lines.length > 0) {
      return { summary: lines.join("\n"), details: null };
    }
    return { summary: content.slice(0, 500), details: content.length > 500 ? content : null };
  }
  if (text.length <= 300) {
    return { summary: text, details: null };
  }
  return { summary: text.slice(0, 280) + "\u2026", details: text };
}
function formatQuestionText(text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return /* @__PURE__ */ jsxRuntime.jsx("strong", { children: part.slice(2, -2) }, i);
    }
    return part;
  });
}
var ClarificationCard = react.memo(function ClarificationCard2({
  question,
  index,
  draft,
  onChange,
  onSubmit,
  isSubmitting
}) {
  const textareaRef = react.useRef(null);
  const [showDetails, setShowDetails] = react.useState(false);
  const { summary, details } = react.useMemo(
    () => extractConciseQuestion(question.question),
    [question.question]
  );
  const handleKeyDown = react.useCallback(
    (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        if (draft.trim()) {
          onSubmit();
        }
      }
    },
    [draft, onSubmit]
  );
  const canSubmit = draft.trim().length > 0 && !isSubmitting;
  return /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-clar-card", children: [
    /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-clar-question-header", children: [
      /* @__PURE__ */ jsxRuntime.jsx("span", { className: "ga-clar-question-number", children: index + 1 }),
      /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-clar-question-text", children: [
        formatQuestionText(summary),
        details && /* @__PURE__ */ jsxRuntime.jsx(
          "button",
          {
            type: "button",
            onClick: () => setShowDetails(!showDetails),
            style: {
              marginLeft: 4,
              background: "none",
              border: "none",
              color: "var(--color-accent, #3b82f6)",
              fontSize: "var(--text-xs, 0.75rem)",
              cursor: "pointer",
              textDecoration: "underline"
            },
            children: showDetails ? "Show less" : "Show more"
          }
        )
      ] })
    ] }),
    showDetails && details && /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-clar-context", style: { whiteSpace: "pre-wrap" }, children: details }),
    question.context && !showDetails && /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-clar-context", children: question.context }),
    /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-clar-input-wrapper", children: [
      /* @__PURE__ */ jsxRuntime.jsx(
        "textarea",
        {
          ref: textareaRef,
          className: "ga-clar-input",
          value: draft,
          onChange: (e) => onChange(e.target.value),
          onKeyDown: handleKeyDown,
          placeholder: "Type your response\u2026",
          rows: 3,
          disabled: isSubmitting,
          "aria-label": `Response to question ${index + 1}`
        }
      ),
      /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-clar-actions", children: /* @__PURE__ */ jsxRuntime.jsx(
        "button",
        {
          type: "button",
          className: `ga-clar-submit ${isSubmitting ? "ga-clar-submitting" : ""}`,
          onClick: onSubmit,
          disabled: !canSubmit,
          "data-haptic": "medium",
          children: isSubmitting ? "Sending\u2026" : "Send"
        }
      ) })
    ] }),
    /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-clar-hint", children: [
      /* @__PURE__ */ jsxRuntime.jsx("kbd", { children: "\u2318" }),
      "+",
      /* @__PURE__ */ jsxRuntime.jsx("kbd", { children: "Enter" }),
      " to send"
    ] })
  ] });
});
var ClarificationPanel = react.memo(function ClarificationPanel2({
  questions,
  onSubmit,
  isSubmitting = false,
  className,
  title = "Agent needs your input",
  emptyMessage = "No clarifications pending."
}) {
  react.useEffect(() => {
    ensureExecutionStyles();
    ensureClarificationStyles();
  }, []);
  const [drafts, setDrafts] = react.useState({});
  const [submitted, setSubmitted] = react.useState(/* @__PURE__ */ new Set());
  const handleChange = react.useCallback((questionId, value) => {
    setDrafts((prev) => ({ ...prev, [questionId]: value }));
  }, []);
  const handleSubmit = react.useCallback(
    (questionId) => {
      const response = drafts[questionId]?.trim();
      if (!response) return;
      onSubmit(questionId, response);
      setSubmitted((prev) => new Set(prev).add(questionId));
    },
    [drafts, onSubmit]
  );
  const pendingQuestions = react.useMemo(
    () => questions.filter((q) => !submitted.has(q.id)),
    [questions, submitted]
  );
  if (pendingQuestions.length === 0 && questions.length === 0) {
    return null;
  }
  const panelClassName = ["ga-clar-panel", className].filter(Boolean).join(" ");
  return /* @__PURE__ */ jsxRuntime.jsxs("div", { className: panelClassName, role: "region", "aria-label": "Clarification requests", children: [
    /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-clar-header", children: [
      /* @__PURE__ */ jsxRuntime.jsx("span", { className: "ga-clar-icon", "aria-hidden": "true", children: "\u{1F4AC}" }),
      /* @__PURE__ */ jsxRuntime.jsx("span", { className: "ga-clar-title", children: title }),
      pendingQuestions.length > 0 && /* @__PURE__ */ jsxRuntime.jsxs("span", { className: "ga-clar-subtitle", children: [
        pendingQuestions.length,
        " ",
        pendingQuestions.length === 1 ? "question" : "questions"
      ] })
    ] }),
    pendingQuestions.length === 0 && questions.length > 0 && /* @__PURE__ */ jsxRuntime.jsxs("div", { className: "ga-clar-success", children: [
      /* @__PURE__ */ jsxRuntime.jsx("span", { className: "ga-clar-success-icon", children: "\u2713" }),
      /* @__PURE__ */ jsxRuntime.jsx("span", { children: "Responses sent! The agent will continue shortly." })
    ] }),
    pendingQuestions.length > 0 && /* @__PURE__ */ jsxRuntime.jsx("div", { className: "ga-clar-questions", children: pendingQuestions.map((question, index) => /* @__PURE__ */ jsxRuntime.jsx(
      ClarificationCard,
      {
        question,
        index,
        draft: drafts[question.id] ?? "",
        onChange: (value) => handleChange(question.id, value),
        onSubmit: () => handleSubmit(question.id),
        isSubmitting
      },
      question.id
    )) })
  ] });
});

exports.ClarificationPanel = ClarificationPanel;
exports.CollabApi = CollabApi;
exports.CollabApiError = CollabApiError;
exports.CollabClient = CollabClient;
exports.CollaborationRole = CollaborationRole;
exports.ConnectionState = ConnectionState;
exports.DocumentType = DocumentType;
exports.EditOperationType = EditOperationType;
exports.ExecutionStatusBadge = ExecutionStatusBadge;
exports.ExecutionStatusCard = ExecutionStatusCard;
exports.ExecutionStreamClient = ExecutionStreamClient;
exports.ExecutionTimeline = ExecutionTimeline;
exports.createCollabApi = createCollabApi;
exports.createCollabClient = createCollabClient;
exports.createExecutionStreamClient = createExecutionStreamClient;
exports.useCollabApi = useCollabApi;
exports.useCollabDocument = useCollaboration;
exports.useCollaboration = useCollaboration;
exports.useGitHubBranches = useGitHubBranches;
exports.useProjectSettings = useProjectSettings;
exports.useUpdateProjectSettings = useUpdateProjectSettings;
exports.useValidateGitHubRepo = useValidateGitHubRepo;
//# sourceMappingURL=index.cjs.map
//# sourceMappingURL=index.cjs.map
