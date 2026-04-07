/**
 * MCP Client for Amprealize Extension
 *
 * Provides direct MCP protocol communication with the amprealize MCP server.
 * Used for real-time operations like device flow auth, consent management,
 * and streaming progress updates.
 *
 * Advantages over CLI:
 * - Persistent connection (lower latency after connect)
 * - Streaming responses for long operations
 * - Bidirectional communication
 * - Native MCP protocol (consistent with Claude Desktop, Cursor, etc.)
 */
import * as vscode from 'vscode';
import { EventEmitter } from 'events';
export interface McpRequest {
    jsonrpc: '2.0';
    id: string | number;
    method: string;
    params?: Record<string, unknown>;
}
export interface McpResponse {
    jsonrpc: '2.0';
    id: string | number;
    result?: unknown;
    error?: McpError;
}
export interface McpError {
    code: number;
    message: string;
    data?: unknown;
}
export interface McpToolResult {
    content: Array<{
        type: string;
        text: string;
    }>;
    isError?: boolean;
}
export interface DeviceInitResult {
    device_code: string;
    user_code: string;
    verification_uri: string;
    verification_uri_complete?: string;
    expires_in: number;
    interval: number;
}
export interface DevicePollResult {
    status: 'pending' | 'authorized' | 'denied' | 'expired' | 'error';
    access_token?: string;
    refresh_token?: string;
    token_type?: string;
    expires_in?: number;
    scopes?: string[];
    error?: string;
    error_description?: string;
}
export interface ConsentStatus {
    user_code: string;
    status: 'pending' | 'approved' | 'denied' | 'expired';
    scopes?: string[];
    granted_at?: string;
    expires_at?: string;
}
export interface AuthRefreshResult {
    status: 'refreshed' | 'no_refresh_token' | 'invalid_token' | 'error';
    access_token?: string;
    refresh_token?: string;
    expires_in?: number;
    error?: string;
}
export interface BreakerAmpPlanResult {
    amp_run_id: string;
    blueprint_id: string;
    valid: boolean;
    environment?: string;
    compliance_tier?: string;
    lifetime?: string;
    estimates?: {
        cpu_cores: number;
        memory_mb: number;
        estimated_duration_seconds: number;
    };
    steps?: Array<{
        id: string;
        name: string;
        type: string;
        dependencies?: string[];
    }>;
    errors?: string[];
    warnings?: string[];
}
export interface BreakerAmpApplyResult {
    amp_run_id: string;
    status: 'pending' | 'running' | 'completed' | 'failed';
    started_at?: string;
    completed_at?: string;
    resources_created?: string[];
    errors?: string[];
}
export interface BreakerAmpStatusResult {
    amp_run_id: string;
    status: 'pending' | 'running' | 'completed' | 'failed' | 'destroyed';
    progress: number;
    current_step?: string;
    steps?: Array<{
        id: string;
        name: string;
        status: 'pending' | 'running' | 'completed' | 'failed';
    }>;
    health_checks?: Array<{
        service: string;
        healthy: boolean;
        message?: string;
    }>;
    telemetry?: {
        cpu_usage_percent?: number;
        memory_usage_mb?: number;
        network_bytes_in?: number;
        network_bytes_out?: number;
    };
    started_at?: string;
    updated_at?: string;
    completed_at?: string;
    error?: string;
}
export interface BreakerAmpDestroyResult {
    amp_run_id: string;
    status: 'destroyed' | 'destroying' | 'failed';
    resources_destroyed?: string[];
    reason?: string;
    destroyed_at?: string;
    errors?: string[];
}
export interface BreakerAmpListBlueprintsResult {
    blueprints: Array<{
        id: string;
        path: string;
        source: 'package' | 'user';
    }>;
    count: number;
    _links?: {
        plan?: string;
    };
}
export interface BreakerAmpListEnvironmentsResult {
    environments: Array<{
        amp_run_id: string;
        environment?: string;
        phase: 'planned' | 'applying' | 'running' | 'stopping' | 'stopped' | 'failed' | 'destroyed';
        blueprint_id?: string;
        created_at?: string;
    }>;
    count: number;
    _links?: {
        status?: string;
        destroy?: string;
    };
}
export interface BreakerAmpConfigureResult {
    environment_file: string;
    environment_status: 'created' | 'overwritten' | 'skipped';
    blueprints_dir?: string;
    blueprints?: Array<{
        blueprint: string;
        status: 'copied' | 'overwritten' | 'skipped' | 'missing';
        path?: string;
        reason?: string;
    }>;
    _links?: {
        list_blueprints?: string;
        plan?: string;
    };
}
export interface ActionCreateResult {
    action_id: string;
    artifact_path: string;
    summary: string;
    behaviors_cited: string[];
    timestamp: string;
    checksum: string;
    audit_log_event_id?: string;
    replay_status: 'NOT_STARTED' | 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED';
}
export interface ActionItem {
    action_id: string;
    artifact_path: string;
    summary: string;
    behaviors_cited: string[];
    timestamp: string;
    checksum?: string;
    actor?: {
        id: string;
        role: 'STRATEGIST' | 'TEACHER' | 'STUDENT' | 'ADMIN';
        surface: 'CLI' | 'REST_API' | 'MCP' | 'WEB' | 'VSCODE';
    };
    replay_status: 'NOT_STARTED' | 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED';
    related_run_id?: string;
    metadata?: Record<string, unknown>;
}
export interface ActionListResult {
    actions: ActionItem[];
    total: number;
    limit: number;
    offset?: number;
}
export interface ActionGetResult extends ActionItem {
    metadata?: {
        commands?: string[];
        validation_output?: string;
        related_links?: string[];
    };
}
export interface ActionReplayResult {
    replay_id: string;
    action_ids: string[];
    strategy: 'SEQUENTIAL' | 'PARALLEL';
    status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED';
    started_at?: string;
}
export interface ActionReplayStatusResult {
    replay_id: string;
    status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED' | 'PARTIAL';
    progress: number;
    current_action_id?: string;
    completed_actions: string[];
    failed_actions: string[];
    started_at?: string;
    completed_at?: string;
    error?: string;
}
export type WorkspaceProfile = 'solo-dev' | 'amprealize-platform' | 'team-collab' | 'extension-dev' | 'api-backend' | 'compliance-sensitive';
export interface BootstrapSignal {
    signal_name: string;
    detected: boolean;
    confidence: number;
    evidence: string;
}
export interface BootstrapDetectResult {
    profile: WorkspaceProfile;
    confidence: number;
    is_ambiguous: boolean;
    runner_up: WorkspaceProfile | null;
    signals: BootstrapSignal[];
}
export interface BootstrapStatusResult {
    is_bootstrapped: boolean;
    profile: WorkspaceProfile | null;
    pack_id: string | null;
    pack_version: string | null;
    agents_md_exists: boolean;
    amprealize_dir_exists: boolean;
    last_updated: string | null;
}
export interface BootstrapInitResult {
    success: boolean;
    profile: WorkspaceProfile;
    detection: BootstrapDetectResult;
    pack_id: string;
    pack_version: string;
    files_written: string[];
    notes: string[];
}
export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'reconnecting';
export interface ConnectionStatus {
    state: ConnectionState;
    lastHeartbeat?: Date;
    reconnectAttempts: number;
    lastError?: string;
}
export declare class McpClient extends EventEmitter {
    private context;
    private process;
    private pythonPath;
    private outputChannel;
    private pendingRequests;
    private requestId;
    private buffer;
    private _isConnected;
    private connectionPromise;
    private connectionState;
    private heartbeatInterval;
    private reconnectAttempts;
    private lastHeartbeat?;
    private lastError?;
    private heartbeatFailures;
    private requestQueue;
    private requestTimeoutMs;
    private heartbeatIntervalMs;
    private maxReconnectAttempts;
    private autoReconnect;
    private razeClient;
    private telemetryEnabled;
    constructor(context: vscode.ExtensionContext);
    /**
     * Get current connection status for UI display
     */
    getConnectionStatus(): ConnectionStatus;
    /**
     * Check if the MCP client is connected
     */
    isConnected(): boolean;
    /**
     * Connect to the MCP server (spawns amprealize.mcp_server as subprocess)
     */
    connect(): Promise<void>;
    private doConnect;
    /**
     * Disconnect from the MCP server
     */
    disconnect(): void;
    /**
     * Check if connected
     */
    get connected(): boolean;
    private setConnectionState;
    /**
     * Log telemetry event using Raze (behavior_use_raze_for_logging)
     */
    private logTelemetry;
    private startHeartbeat;
    private stopHeartbeat;
    private scheduleReconnect;
    /**
     * Send a ping to check server health
     */
    ping(): Promise<{
        status: string;
    }>;
    private flushRequestQueue;
    private handleData;
    private sendRequest;
    private sendRequestWithTimeout;
    private sendNotification;
    private rejectAllPending;
    /**
     * Call an MCP tool by name
     */
    callTool<T = unknown>(toolName: string, args?: Record<string, unknown>): Promise<T>;
    /**
     * List available tools
     */
    listTools(): Promise<Array<{
        name: string;
        description?: string;
    }>>;
    /**
     * Initialize device authorization flow
     */
    deviceInit(params?: {
        clientId?: string;
        scopes?: string[];
    }): Promise<DeviceInitResult>;
    /**
     * Poll device authorization status
     */
    devicePoll(params: {
        deviceCode: string;
        clientId?: string;
    }): Promise<DevicePollResult>;
    /**
     * Refresh access token
     */
    authRefresh(params: {
        refreshToken: string;
        clientId?: string;
    }): Promise<AuthRefreshResult>;
    /**
     * Look up consent status by user code
     */
    consentLookup(userCode: string): Promise<ConsentStatus>;
    /**
     * Approve consent request
     */
    consentApprove(params: {
        userCode: string;
        scopes?: string[];
    }): Promise<{
        success: boolean;
        granted_scopes?: string[];
    }>;
    /**
     * Deny consent request
     */
    consentDeny(params: {
        userCode: string;
        reason?: string;
    }): Promise<{
        success: boolean;
    }>;
    /**
     * Retrieve behaviors using BCI
     */
    bciRetrieve(params: {
        query: string;
        topK?: number;
        strategy?: 'embedding' | 'keyword' | 'hybrid';
        roleFocus?: string;
        tags?: string[];
    }): Promise<unknown>;
    /**
     * Full runtime injection: resolve context, retrieve behaviors, compose enriched prompt.
     * E3 S3.3 (T3.3.2): Inject context blocks into extension chat.
     */
    bciInject(params: {
        task: string;
        surface?: string;
        role?: string;
        workspacePath?: string;
        topK?: number;
        strategy?: 'embedding' | 'keyword' | 'hybrid';
        format?: 'list' | 'prose' | 'structured';
        citationMode?: 'explicit' | 'implicit' | 'inline';
        tags?: string[];
        phase?: string;
    }): Promise<{
        composed_prompt: string;
        behaviors_injected: string[];
        overlays_included: string[];
        context: Record<string, unknown>;
        token_estimate: number;
        latency_ms: number;
    }>;
    /**
     * Plan an breakeramp environment from a blueprint
     */
    breakerampPlan(params: {
        blueprintId: string;
        environment?: string;
        checklistId?: string;
        lifetime?: string;
        complianceTier?: 'dev' | 'prod-sim' | 'pci-sandbox';
        behaviors?: string[];
        variables?: Record<string, string>;
    }): Promise<BreakerAmpPlanResult>;
    /**
     * Apply an breakeramp plan to create resources
     */
    breakerampApply(params: {
        planId?: string;
        manifestFile?: string;
        watch?: boolean;
        resume?: boolean;
    }): Promise<BreakerAmpApplyResult>;
    /**
     * Get status of an breakeramp run
     */
    breakerampStatus(runId: string): Promise<BreakerAmpStatusResult>;
    /**
     * Destroy resources from an breakeramp run
     */
    breakerampDestroy(params: {
        runId: string;
        cascade?: boolean;
        reason?: 'POST_TEST' | 'FAILED' | 'ABANDONED' | 'MANUAL';
    }): Promise<BreakerAmpDestroyResult>;
    /**
     * List available blueprints
     */
    breakerampListBlueprints(params?: {
        source?: 'all' | 'package' | 'user';
    }): Promise<BreakerAmpListBlueprintsResult>;
    /**
     * List active environments
     */
    breakerampListEnvironments(params?: {
        phase?: 'planned' | 'applying' | 'running' | 'stopping' | 'stopped' | 'failed' | 'destroyed' | 'all';
    }): Promise<BreakerAmpListEnvironmentsResult>;
    /**
     * Configure breakeramp in a directory
     */
    breakerampConfigure(params?: {
        configDir?: string;
        includeBlueprints?: boolean;
        blueprints?: string[];
        force?: boolean;
    }): Promise<BreakerAmpConfigureResult>;
    /**
     * Record a new build action for reproducibility tracking
     */
    actionCreate(params: {
        artifactPath: string;
        summary: string;
        behaviorsCited: string[];
        metadata?: {
            commands?: string[];
            validationOutput?: string;
            relatedLinks?: string[];
        };
        relatedRunId?: string;
        checksum?: string;
        actor?: {
            id: string;
            role: 'STRATEGIST' | 'TEACHER' | 'STUDENT' | 'ADMIN';
        };
        tier?: 'hot' | 'warm' | 'cold';
    }): Promise<ActionCreateResult>;
    /**
     * List recorded build actions with optional filtering
     */
    actionList(params?: {
        artifactPathFilter?: string;
        behaviorId?: string;
        relatedRunId?: string;
        limit?: number;
        actor?: {
            id: string;
            role: 'STRATEGIST' | 'TEACHER' | 'STUDENT' | 'ADMIN';
        };
    }): Promise<ActionListResult>;
    /**
     * Get details of a specific action
     */
    actionGet(actionId: string): Promise<ActionGetResult>;
    /**
     * Launch a replay job to reproduce one or more actions
     */
    actionReplay(params: {
        actionIds: string[];
        strategy?: 'SEQUENTIAL' | 'PARALLEL';
        options?: {
            skipExisting?: boolean;
            dryRun?: boolean;
        };
        tier?: 'hot' | 'warm' | 'cold';
    }): Promise<ActionReplayResult>;
    /**
     * Get status of a replay job
     */
    actionReplayStatus(replayId: string): Promise<ActionReplayStatusResult>;
    bootstrapDetect(params?: {
        workspace_path?: string;
    }): Promise<BootstrapDetectResult>;
    bootstrapStatus(params?: {
        workspace_path?: string;
    }): Promise<BootstrapStatusResult>;
    bootstrapInit(params: {
        workspace_path?: string;
        profile?: string;
        skip_primer?: boolean;
        skip_pack?: boolean;
        force?: boolean;
    }): Promise<BootstrapInitResult>;
    dispose(): void;
}
//# sourceMappingURL=McpClient.d.ts.map
