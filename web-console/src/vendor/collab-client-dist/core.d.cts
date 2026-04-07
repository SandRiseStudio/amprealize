/**
 * GuideAI Collaboration Protocol Types
 *
 * Shared between SaaS (web-console) and VS Code extension for cross-surface parity.
 * Mirrors backend contracts in guideai/collaboration_contracts.py.
 */
type WorkspaceId = string;
type DocumentId = string;
type UserId = string;
type SessionId = string;
type OperationId = string;
declare enum EditOperationType {
    Insert = "insert",
    Delete = "delete",
    Replace = "replace",
    Move = "move",
    Format = "format"
}
declare enum CollaborationRole {
    Owner = "owner",
    Admin = "admin",
    Editor = "editor",
    Commenter = "commenter",
    Viewer = "viewer"
}
declare enum DocumentType {
    Markdown = "markdown",
    Plan = "plan",
    Workflow = "workflow",
    Agent = "agent",
    Json = "json"
}
interface Workspace {
    id: WorkspaceId;
    name: string;
    description: string;
    owner_id: UserId;
    created_at: string;
    updated_at: string;
    is_shared: boolean;
    settings?: Record<string, unknown>;
    tags?: string[];
}
interface Document {
    id: DocumentId;
    workspace_id: WorkspaceId;
    title: string;
    content: string;
    document_type: DocumentType | string;
    created_by: UserId;
    created_at: string;
    updated_at: string;
    version: number;
    metadata?: Record<string, unknown>;
}
interface EditOperation {
    id: OperationId;
    document_id: DocumentId;
    user_id: UserId;
    operation_type: EditOperationType;
    position: number;
    content: string;
    length?: number;
    version: number;
    timestamp: string;
    session_id?: SessionId;
    metadata?: Record<string, unknown>;
}
/**
 * Client → Server messages
 */
type ClientMessage = {
    type: 'ping';
} | {
    type: 'edit';
    operation: ClientEditOperation;
} | {
    type: 'cursor';
    position: number;
    selection_end?: number;
} | {
    type: 'presence';
    status: 'active' | 'idle' | 'away';
};
interface ClientEditOperation {
    operation_type: EditOperationType;
    position: number;
    content: string;
    length?: number;
    version: number;
    user_id?: UserId;
    session_id?: SessionId;
}
/**
 * Server → Client messages
 */
type ServerMessage = {
    type: 'pong';
} | {
    type: 'snapshot';
    document: Document;
} | {
    type: 'operation';
    operation: EditOperation;
    document: Document | null;
} | {
    type: 'cursor';
    user_id: UserId;
    position: number;
    selection_end?: number;
} | {
    type: 'presence';
    user_id: UserId;
    status: 'active' | 'idle' | 'away' | 'disconnected';
} | {
    type: 'error';
    code: ErrorCode;
    message: string;
    expected_version?: number;
    got_version?: number;
    document?: Document | null;
};
type ErrorCode = 'BAD_REQUEST' | 'NOT_FOUND' | 'VERSION_CONFLICT' | 'APPLY_FAILED' | 'UNAUTHORIZED';
interface CreateWorkspaceRequest {
    name: string;
    description?: string;
    owner_id: string;
    settings?: Record<string, unknown>;
    tags?: string[];
    is_shared?: boolean;
}
interface CreateDocumentRequest {
    workspace_id: WorkspaceId;
    title: string;
    content?: string;
    document_type?: DocumentType | string;
    created_by: UserId;
    metadata?: Record<string, unknown>;
}
interface UserPresence {
    user_id: UserId;
    session_id?: SessionId;
    display_name?: string;
    color?: string;
    status: 'active' | 'idle' | 'away' | 'disconnected';
    cursor_position?: number;
    selection_end?: number;
    last_active: string;
}
interface WorkflowSettings {
    require_approval_for_deploy: boolean;
    auto_merge_enabled: boolean;
    branch_protection_enabled: boolean;
    ci_required: boolean;
    code_owners_required: boolean;
    min_reviewers: number;
    allowed_merge_methods: string[];
}
interface AgentSettings {
    max_concurrent_runs: number;
    default_timeout_seconds: number;
    auto_retry_enabled: boolean;
    max_retries: number;
    require_human_approval: boolean;
    allowed_actions: string[];
    blocked_actions: string[];
}
interface BrandingSettings {
    logo_url?: string;
    favicon_url?: string;
    primary_color?: string;
    accent_color?: string;
    font_family?: string;
}
interface GitHubBranchInfo {
    name: string;
    sha: string;
    protected: boolean;
}
interface ProjectSettings {
    project_id: string;
    inherit_org_settings: boolean;
    branding?: BrandingSettings;
    workflow: WorkflowSettings;
    agents: AgentSettings;
    repository_url?: string;
    default_branch: string;
    protected_branches: string[];
    local_project_path?: string;
    environments: string[];
    active_environment: string;
    features: Record<string, boolean>;
    custom: Record<string, unknown>;
}
interface UpdateProjectSettingsRequest {
    inherit_org_settings?: boolean;
    branding?: Partial<BrandingSettings>;
    workflow?: Partial<WorkflowSettings>;
    repository_url?: string;
    default_branch?: string;
    protected_branches?: string[];
    local_project_path?: string;
    environments?: string[];
    active_environment?: string;
    features?: Record<string, boolean>;
    custom?: Record<string, unknown>;
}
interface GitHubRepoValidationRequest {
    repository_url: string;
    access_token?: string;
}
interface GitHubRepoValidationResponse {
    valid: boolean;
    owner?: string;
    repo?: string;
    default_branch?: string;
    branches: GitHubBranchInfo[];
    visibility?: 'public' | 'private';
    description?: string;
    error?: string;
}
interface GitHubBranchListResponse {
    branches: GitHubBranchInfo[];
    total_count?: number;
    page: number;
    per_page: number;
}
interface CollabClientEvents {
    /** Connection established, initial snapshot received */
    connected: (document: Document) => void;
    /** Connection lost */
    disconnected: (reason: string) => void;
    /** Remote operation applied */
    operation: (operation: EditOperation, document: Document | null) => void;
    /** Version conflict - client should rebase */
    conflict: (expected: number, got: number, serverDocument: Document | null) => void;
    /** Remote cursor update */
    cursor: (userId: UserId, position: number, selectionEnd?: number) => void;
    /** Presence change */
    presence: (userId: UserId, status: UserPresence['status']) => void;
    /** Generic error */
    error: (code: ErrorCode, message: string) => void;
}
type ExecutionState = 'pending' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled' | 'unknown';
interface ExecutionStatus {
    hasExecution: boolean;
    runId?: string | null;
    taskCycleId?: string | null;
    state?: ExecutionState | null;
    phase?: string | null;
    startedAt?: string | null;
    progressPct?: number | null;
    currentStep?: string | null;
    totalTokens?: number | null;
    totalCostUsd?: number | null;
    pendingClarifications?: Array<Record<string, unknown>> | null;
}
interface ExecutionListItem {
    runId: string;
    workItemId: string;
    workItemTitle?: string | null;
    agentId: string;
    state: ExecutionState | string;
    phase?: string | null;
    startedAt: string;
    completedAt?: string | null;
    progressPct: number;
}
interface ExecutionListResponse {
    executions: ExecutionListItem[];
    total: number;
    offset: number;
    limit: number;
}
interface ExecutionStep {
    stepId: string;
    phase: string;
    stepType: string;
    startedAt: string;
    completedAt?: string | null;
    inputTokens?: number | null;
    outputTokens?: number | null;
    toolCalls?: number | null;
    contentPreview?: string | null;
    contentFull?: string | null;
    toolNames?: string[] | null;
    modelId?: string | null;
}
interface ExecutionStepsResponse {
    steps: ExecutionStep[];
    total: number;
}
interface ExecutionStatusEventPayload {
    run_id: string;
    work_item_id?: string | null;
    org_id?: string | null;
    project_id?: string | null;
    agent_id?: string | null;
    model_id?: string | null;
    cycle_id?: string | null;
    task_cycle_id?: string | null;
    status: string;
    phase?: string | null;
    progress_pct?: number | null;
    current_step?: string | null;
    started_at?: string | null;
    completed_at?: string | null;
    error?: string | null;
    step_count?: number | null;
    updated_at?: string | null;
}
interface ExecutionStepEventPayload {
    run_id: string;
    work_item_id?: string | null;
    org_id?: string | null;
    project_id?: string | null;
    step: {
        step_id: string;
        name: string;
        status: string;
        started_at?: string | null;
        completed_at?: string | null;
        progress_pct?: number | null;
        metadata?: Record<string, unknown>;
    };
}
interface ExecutionStepSnapshotPayload {
    step_id: string;
    phase?: string | null;
    step_type?: string | null;
    started_at?: string | null;
    completed_at?: string | null;
    input_tokens?: number | null;
    output_tokens?: number | null;
    tool_calls?: number | null;
    content_preview?: string | null;
    name?: string | null;
    status?: string | null;
    progress_pct?: number | null;
    metadata?: Record<string, unknown>;
}
interface ExecutionStatusSnapshotPayload {
    run_id: string;
    cycle_id?: string | null;
    task_cycle_id?: string | null;
    work_item_id?: string | null;
    status?: string | null;
    phase?: string | null;
    progress_pct?: number | null;
    current_step?: string | null;
    started_at?: string | null;
    completed_at?: string | null;
    error?: string | null;
    model_id?: string | null;
    step_count?: number | null;
}
interface ExecutionSnapshotEventPayload {
    run_id?: string | null;
    status?: ExecutionStatusEventPayload | ExecutionStatusSnapshotPayload | null;
    steps?: Array<ExecutionStepEventPayload['step'] | ExecutionStepSnapshotPayload>;
    executions?: ExecutionStatusEventPayload[];
}
interface ExecutionReadyEventPayload {
    run_id?: string | null;
    org_id?: string | null;
    project_id?: string | null;
}
interface ExecutionStreamEvents {
    connected: (context: ExecutionReadyEventPayload) => void;
    disconnected: (reason: string) => void;
    status: (payload: ExecutionStatusEventPayload) => void;
    step: (payload: ExecutionStepEventPayload) => void;
    snapshot: (payload: ExecutionSnapshotEventPayload) => void;
    ready: (payload: ExecutionReadyEventPayload) => void;
    error: (code: string, message: string) => void;
}

/**
 * GuideAI Collaboration Client
 *
 * High-performance, cross-surface WebSocket client for real-time collaboration.
 * Features:
 * - Automatic reconnection with exponential backoff
 * - Optimistic updates with conflict resolution
 * - Event-driven API for easy UI binding
 * - Works in both browser (SaaS) and VS Code webviews
 */

interface CollabClientConfig {
    /** WebSocket endpoint base URL (e.g., ws://localhost:8080) */
    baseUrl: string;
    /** User identifier */
    userId: UserId;
    /** Optional session identifier for multi-tab/window support */
    sessionId?: SessionId;
    /**
     * Authentication token (Bearer token).
     * Required for authenticated WebSocket connections.
     * Can be updated via setAuthToken() for token refresh scenarios.
     */
    authToken?: string;
    /**
     * Callback to get a fresh auth token before reconnecting.
     * Useful for handling token refresh during long-lived connections.
     */
    getAuthToken?: () => Promise<string | null>;
    /** Reconnection settings */
    reconnect?: {
        enabled?: boolean;
        maxAttempts?: number;
        baseDelayMs?: number;
        maxDelayMs?: number;
    };
    /** Heartbeat interval in ms (default: 25000) */
    heartbeatIntervalMs?: number;
    /** Debug logging */
    debug?: boolean;
}
declare class TypedEventEmitter$1<Events> {
    private handlers;
    on<K extends keyof Events>(event: K, handler: Events[K]): () => void;
    off<K extends keyof Events>(event: K, handler: Events[K]): void;
    protected emit<K extends keyof Events>(event: K, ...args: Events[K] extends (...a: infer P) => void ? P : never): void;
    removeAllListeners(): void;
}
declare enum ConnectionState {
    Disconnected = "disconnected",
    Connecting = "connecting",
    Connected = "connected",
    Reconnecting = "reconnecting"
}
declare class CollabClient extends TypedEventEmitter$1<CollabClientEvents> {
    private config;
    private ws;
    private documentId;
    private document;
    private connectionState;
    private reconnectAttempts;
    private reconnectTimeout;
    private heartbeatInterval;
    /** Current auth token (can be updated via setAuthToken) */
    private authToken;
    private pendingOps;
    private opCounter;
    constructor(config: CollabClientConfig);
    /**
     * Update the auth token. Use this when tokens are refreshed.
     * If currently connected, the new token will be used on next reconnect.
     */
    setAuthToken(token: string | null): void;
    /**
     * Get the current auth token.
     */
    getAuthToken(): string | null;
    get state(): ConnectionState;
    get currentDocument(): Document | null;
    get currentVersion(): number;
    /**
     * Connect to a document for real-time collaboration.
     */
    connect(documentId: DocumentId): void;
    /**
     * Disconnect from the current document.
     */
    disconnect(): void;
    /**
     * Send an edit operation. Returns a local operation ID for tracking.
     */
    sendEdit(operation: Omit<ClientEditOperation, 'version' | 'user_id' | 'session_id'>): string;
    /**
     * Send cursor position update.
     */
    sendCursor(position: number, selectionEnd?: number): void;
    /**
     * Send presence status update.
     */
    sendPresence(status: 'active' | 'idle' | 'away'): void;
    private createWebSocket;
    private handleOpen;
    private handleMessage;
    private handleServerError;
    private handleClose;
    private handleError;
    private scheduleReconnect;
    private startHeartbeat;
    private send;
    private clearTimers;
    private clearConfirmedOps;
    private log;
}
declare function createCollabClient(config: CollabClientConfig): CollabClient;

/**
 * GuideAI Execution Stream Client
 *
 * Real-time WebSocket client for execution status + steps.
 */

interface ExecutionStreamConfig {
    /** WebSocket base URL origin (e.g., http://localhost:8080) */
    baseUrl: string;
    /** Optional auth token passed as a query param */
    authToken?: string;
    /** Callback to fetch a fresh auth token before connecting/reconnecting */
    getAuthToken?: () => Promise<string | null>;
    /** Reconnection settings */
    reconnect?: {
        enabled?: boolean;
        maxAttempts?: number;
        baseDelayMs?: number;
        maxDelayMs?: number;
    };
    /** Heartbeat interval in ms (default: 25000) */
    heartbeatIntervalMs?: number;
    /** Debug logging */
    debug?: boolean;
}
interface ExecutionStreamTarget {
    runId?: string | null;
    orgId?: string | null;
    projectId?: string | null;
}
declare class TypedEventEmitter<Events> {
    private handlers;
    on<K extends keyof Events>(event: K, handler: Events[K]): () => void;
    off<K extends keyof Events>(event: K, handler: Events[K]): void;
    protected emit<K extends keyof Events>(event: K, ...args: Events[K] extends (...a: infer P) => void ? P : never): void;
    removeAllListeners(): void;
}
declare class ExecutionStreamClient extends TypedEventEmitter<ExecutionStreamEvents> {
    private config;
    private ws;
    private target;
    private connectionState;
    private reconnectAttempts;
    private reconnectTimeout;
    private heartbeatInterval;
    private authToken;
    private shouldReconnect;
    constructor(config: ExecutionStreamConfig);
    setAuthToken(token: string | null): void;
    getAuthToken(): string | null;
    get state(): ConnectionState;
    connect(target: ExecutionStreamTarget): void;
    disconnect(reason?: string): void;
    private openConnection;
    private handleMessage;
    private snapshotContext;
    private resolveAuthToken;
    private buildWebSocketUrl;
    private scheduleReconnect;
    private startHeartbeat;
    private send;
    private clearTimers;
    private isSameTarget;
    private log;
}
declare function createExecutionStreamClient(config: ExecutionStreamConfig): ExecutionStreamClient;

/**
 * GuideAI Collaboration REST API Client
 *
 * For CRUD operations on workspaces and documents (non-realtime).
 * Use CollabClient for real-time WebSocket collaboration.
 */

interface CollabApiConfig {
    /** REST API base URL (e.g., http://localhost:8080) */
    baseUrl: string;
    /** Optional auth token */
    authToken?: string;
    /** Custom fetch implementation (for testing or environments without native fetch) */
    fetch?: typeof fetch;
}
declare class CollabApi {
    private config;
    private fetch;
    constructor(config: CollabApiConfig);
    createWorkspace(request: CreateWorkspaceRequest): Promise<Workspace>;
    getWorkspace(workspaceId: WorkspaceId): Promise<Workspace>;
    listDocuments(workspaceId: WorkspaceId): Promise<Document[]>;
    createDocument(request: CreateDocumentRequest): Promise<Document>;
    getDocument(documentId: DocumentId): Promise<Document>;
    getDocumentOperations(documentId: DocumentId, limit?: number): Promise<EditOperation[]>;
    getProjectSettings(projectId: string): Promise<ProjectSettings>;
    updateProjectSettings(projectId: string, settings: UpdateProjectSettingsRequest): Promise<ProjectSettings>;
    setProjectRepository(projectId: string, repositoryUrl: string, defaultBranch?: string): Promise<ProjectSettings>;
    validateGitHubRepository(projectId: string, request: GitHubRepoValidationRequest): Promise<GitHubRepoValidationResponse>;
    listGitHubBranches(projectId: string, page?: number, perPage?: number): Promise<GitHubBranchListResponse>;
    private get;
    private post;
    private patch;
    private put;
    private headers;
    private handleResponse;
}
declare class CollabApiError extends Error {
    readonly status: number;
    readonly detail: string;
    constructor(status: number, detail: string);
}
declare function createCollabApi(config: CollabApiConfig): CollabApi;

export { type AgentSettings, type BrandingSettings, type ClientEditOperation, type ClientMessage, CollabApi, type CollabApiConfig, CollabApiError, CollabClient, type CollabClientConfig, type CollabClientEvents, CollaborationRole, ConnectionState, type CreateDocumentRequest, type CreateWorkspaceRequest, type Document, type DocumentId, DocumentType, type EditOperation, EditOperationType, type ErrorCode, type ExecutionListItem, type ExecutionListResponse, type ExecutionReadyEventPayload, type ExecutionSnapshotEventPayload, type ExecutionState, type ExecutionStatus, type ExecutionStatusEventPayload, type ExecutionStatusSnapshotPayload, type ExecutionStep, type ExecutionStepEventPayload, type ExecutionStepSnapshotPayload, type ExecutionStepsResponse, ExecutionStreamClient, type ExecutionStreamConfig, type ExecutionStreamEvents, type ExecutionStreamTarget, type GitHubBranchInfo, type GitHubBranchListResponse, type GitHubRepoValidationRequest, type GitHubRepoValidationResponse, type OperationId, type ProjectSettings, type ServerMessage, type SessionId, type UpdateProjectSettingsRequest, type UserId, type UserPresence, type WorkflowSettings, type Workspace, type WorkspaceId, createCollabApi, createCollabClient, createExecutionStreamClient };
