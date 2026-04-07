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
var ConversationScope = /* @__PURE__ */ ((ConversationScope2) => {
  ConversationScope2["ProjectRoom"] = "project_room";
  ConversationScope2["AgentDm"] = "agent_dm";
  return ConversationScope2;
})(ConversationScope || {});
var ActorType = /* @__PURE__ */ ((ActorType2) => {
  ActorType2["User"] = "user";
  ActorType2["Agent"] = "agent";
  ActorType2["System"] = "system";
  return ActorType2;
})(ActorType || {});
var MessageType = /* @__PURE__ */ ((MessageType2) => {
  MessageType2["Text"] = "text";
  MessageType2["StatusCard"] = "status_card";
  MessageType2["BlockerCard"] = "blocker_card";
  MessageType2["ProgressCard"] = "progress_card";
  MessageType2["CodeBlock"] = "code_block";
  MessageType2["RunSummary"] = "run_summary";
  MessageType2["System"] = "system";
  return MessageType2;
})(MessageType || {});
var ParticipantRole = /* @__PURE__ */ ((ParticipantRole2) => {
  ParticipantRole2["Owner"] = "owner";
  ParticipantRole2["Admin"] = "admin";
  ParticipantRole2["Member"] = "member";
  return ParticipantRole2;
})(ParticipantRole || {});
var NotificationPreference = /* @__PURE__ */ ((NotificationPreference2) => {
  NotificationPreference2["All"] = "all";
  NotificationPreference2["Mentions"] = "mentions";
  NotificationPreference2["None"] = "none";
  return NotificationPreference2;
})(NotificationPreference || {});

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

// src/conversationClient.ts
var DEFAULT_RECONNECT2 = {
  enabled: true,
  maxAttempts: 10,
  baseDelayMs: 1e3,
  maxDelayMs: 3e4
};
var DEFAULT_CONFIG3 = {
  reconnect: DEFAULT_RECONNECT2,
  heartbeatIntervalMs: 25e3,
  debug: false
};
var TypedEventEmitter3 = class {
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
        console.error(`[ConversationStreamClient] Error in ${String(event)} handler:`, err);
      }
    });
  }
  removeAllListeners() {
    this.handlers.clear();
  }
};
var ConversationStreamClient = class extends TypedEventEmitter3 {
  config;
  ws = null;
  conversationId = null;
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
      reconnect: { ...DEFAULT_RECONNECT2, ...config.reconnect },
      heartbeatIntervalMs: config.heartbeatIntervalMs ?? DEFAULT_CONFIG3.heartbeatIntervalMs,
      debug: config.debug ?? DEFAULT_CONFIG3.debug
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
  get activeConversationId() {
    return this.conversationId;
  }
  connect(conversationId) {
    if (!conversationId) {
      this.log("Skipping connect without conversationId");
      return;
    }
    if (this.conversationId === conversationId && this.connectionState === "connected" /* Connected */) {
      this.log("Already connected to conversation", conversationId);
      return;
    }
    this.disconnect();
    this.conversationId = conversationId;
    this.shouldReconnect = true;
    this.connectionState = "connecting" /* Connecting */;
    this.reconnectAttempts = 0;
    void this.openConnection(conversationId);
  }
  disconnect(reason = "manual_disconnect") {
    this.shouldReconnect = false;
    this.clearTimers();
    if (this.ws) {
      this.ws.close();
    }
    this.ws = null;
    this.conversationId = null;
    this.connectionState = "disconnected" /* Disconnected */;
    this.emit("disconnected", reason);
  }
  // ---------------------------------------------------------------------------
  // Client → Server Commands
  // ---------------------------------------------------------------------------
  sendMessage(options) {
    this.send({
      type: "message.send",
      content: options.content,
      message_type: options.message_type,
      structured_payload: options.structured_payload,
      parent_id: options.parent_id
    });
  }
  editMessage(messageId, content) {
    this.send({ type: "message.edit", message_id: messageId, content });
  }
  deleteMessage(messageId) {
    this.send({ type: "message.delete", message_id: messageId });
  }
  addReaction(messageId, emoji) {
    this.send({ type: "reaction.add", message_id: messageId, emoji });
  }
  removeReaction(messageId, emoji) {
    this.send({ type: "reaction.remove", message_id: messageId, emoji });
  }
  startTyping() {
    this.send({ type: "typing.start" });
  }
  stopTyping() {
    this.send({ type: "typing.stop" });
  }
  updateReadPosition(lastReadMessageId) {
    this.send({ type: "read.update", last_read_message_id: lastReadMessageId });
  }
  // ---------------------------------------------------------------------------
  // Connection Flow
  // ---------------------------------------------------------------------------
  async openConnection(requestedConversationId) {
    const targetConversationId = requestedConversationId ?? this.conversationId;
    if (!targetConversationId) {
      this.log("Skipping openConnection without conversationId");
      return;
    }
    const token = await this.resolveAuthToken();
    if (this.conversationId !== targetConversationId || !this.shouldReconnect) {
      this.log("Aborting stale openConnection", targetConversationId, this.conversationId);
      return;
    }
    const url = this.buildWebSocketUrl(targetConversationId, token ?? void 0);
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
      case "conversation.ready":
        this.emit("connected", message.payload);
        break;
      case "message.new":
        this.emit("message.new", message.payload);
        break;
      case "message.updated":
        this.emit("message.updated", message.payload);
        break;
      case "message.deleted":
        this.emit("message.deleted", message.payload);
        break;
      case "reaction.added":
        this.emit("reaction.added", message.payload);
        break;
      case "reaction.removed":
        this.emit("reaction.removed", message.payload);
        break;
      case "typing":
        this.emit("typing.indicator", message.payload);
        break;
      case "read.receipt":
        this.emit("read.receipt", message.payload);
        break;
      case "participant.joined":
        this.emit("participant.joined", message.payload);
        break;
      case "participant.left":
        this.emit("participant.left", message.payload);
        break;
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
  buildWebSocketUrl(conversationId, token) {
    const url = new URL(`/api/v1/conversations/${encodeURIComponent(conversationId)}/ws`, this.config.baseUrl);
    url.searchParams.set("user_id", this.config.userId);
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
    const maxAttempts = this.config.reconnect.maxAttempts ?? DEFAULT_CONFIG3.reconnect.maxAttempts;
    if (this.reconnectAttempts >= maxAttempts) {
      this.log("Max reconnect attempts reached");
      this.connectionState = "disconnected" /* Disconnected */;
      return;
    }
    const attempt = this.reconnectAttempts + 1;
    const baseDelayMs = this.config.reconnect.baseDelayMs ?? DEFAULT_CONFIG3.reconnect.baseDelayMs;
    const maxDelayMs = this.config.reconnect.maxDelayMs ?? DEFAULT_CONFIG3.reconnect.maxDelayMs;
    const delay = Math.min(baseDelayMs * 2 ** (attempt - 1), maxDelayMs);
    this.reconnectAttempts = attempt;
    this.reconnectTimeout = setTimeout(() => {
      if (!this.conversationId) return;
      this.log(`Reconnect attempt ${attempt}`);
      void this.openConnection();
    }, delay);
  }
  startHeartbeat() {
    const heartbeatIntervalMs = this.config.heartbeatIntervalMs ?? DEFAULT_CONFIG3.heartbeatIntervalMs;
    if (heartbeatIntervalMs <= 0) return;
    this.heartbeatInterval = setInterval(() => {
      this.send({ type: "ping" });
    }, heartbeatIntervalMs);
  }
  send(command) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(command));
      this.log("Sent:", command.type);
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
  log(...args) {
    if (this.config.debug) {
      console.log("[ConversationStreamClient]", ...args);
    }
  }
};
function createConversationStreamClient(config) {
  return new ConversationStreamClient(config);
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

export { ActorType, CollabApi, CollabApiError, CollabClient, CollaborationRole, ConnectionState, ConversationScope, ConversationStreamClient, DocumentType, EditOperationType, ExecutionStreamClient, MessageType, NotificationPreference, ParticipantRole, createCollabApi, createCollabClient, createConversationStreamClient, createExecutionStreamClient };
//# sourceMappingURL=core.js.map
//# sourceMappingURL=core.js.map
