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
import { spawn, ChildProcess } from 'child_process';
import { EventEmitter } from 'events';
import { RazeClient, LogLevel } from './RazeClient';

// ============================================
// Types
// ============================================

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

// Device flow types
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

// BreakerAmp types
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

// Action Registry types (behavior_sanitize_action_registry)
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

// ============================================
// Bootstrap Types (AMPREALIZE-276)
// ============================================

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

// ============================================
// Connection States
// ============================================

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'reconnecting';

export interface ConnectionStatus {
    state: ConnectionState;
    lastHeartbeat?: Date;
    reconnectAttempts: number;
    lastError?: string;
}

// ============================================
// MCP Client
// ============================================

export class McpClient extends EventEmitter {
    private process: ChildProcess | null = null;
    private pythonPath: string;
    private outputChannel: vscode.OutputChannel;
    private pendingRequests = new Map<string | number, {
        resolve: (value: unknown) => void;
        reject: (error: Error) => void;
        timeout: NodeJS.Timeout;
    }>();
    private requestId = 0;
    private buffer = '';
    private _isConnected = false;
    private connectionPromise: Promise<void> | null = null;

    // Stability features
    private connectionState: ConnectionState = 'disconnected';
    private heartbeatInterval: NodeJS.Timeout | null = null;
    private reconnectAttempts = 0;
    private lastHeartbeat?: Date;
    private lastError?: string;
    private heartbeatFailures = 0;
    private requestQueue: Array<{
        method: string;
        params?: Record<string, unknown>;
        resolve: (value: unknown) => void;
        reject: (error: Error) => void;
    }> = [];

    // Configuration
    private requestTimeoutMs: number;
    private heartbeatIntervalMs: number;
    private maxReconnectAttempts: number;
    private autoReconnect: boolean;

    // Telemetry (behavior_use_raze_for_logging)
    private razeClient: RazeClient | null = null;
    private telemetryEnabled: boolean;

    constructor(private context: vscode.ExtensionContext) {
        super();
        const config = vscode.workspace.getConfiguration('amprealize');

        // Try to find Python in any workspace .venv, fall back to configured or system python
        const workspaceFolders = vscode.workspace.workspaceFolders;
        let defaultPython = 'python';
        const fs = require('fs');
        if (workspaceFolders && workspaceFolders.length > 0) {
            for (const folder of workspaceFolders) {
                const venvPython = vscode.Uri.joinPath(folder.uri, '.venv', 'bin', 'python').fsPath;
                if (fs.existsSync(venvPython)) {
                    defaultPython = venvPython;
                    break;
                }
            }
        }

        this.pythonPath = config.get('pythonPath', defaultPython);
        this.outputChannel = vscode.window.createOutputChannel('Amprealize MCP');
        this.outputChannel.appendLine(`Using Python: ${this.pythonPath}`);

        // Load stability configuration
        // NOTE: Auto-reconnect disabled by default to prevent resource exhaustion on failed connections
        this.requestTimeoutMs = config.get('mcpRequestTimeout', 30000);
        this.heartbeatIntervalMs = config.get('mcpHeartbeatInterval', 60000); // 60s heartbeat (was 30s)
        this.maxReconnectAttempts = config.get('mcpMaxReconnectAttempts', 3); // Max 3 attempts (was 10)
        this.autoReconnect = config.get('mcpAutoReconnect', false); // Disabled by default

        // Initialize telemetry (behavior_use_raze_for_logging)
        this.telemetryEnabled = config.get('telemetryEnabled', false);
        if (this.telemetryEnabled) {
            this.razeClient = new RazeClient(context, {
                serviceName: 'amprealize-mcp-client',
            });
        }

        // Listen for configuration changes
        vscode.workspace.onDidChangeConfiguration(e => {
            if (e.affectsConfiguration('amprealize')) {
                const newConfig = vscode.workspace.getConfiguration('amprealize');
                this.requestTimeoutMs = newConfig.get('mcpRequestTimeout', 30000);
                this.heartbeatIntervalMs = newConfig.get('mcpHeartbeatInterval', 60000);
                this.maxReconnectAttempts = newConfig.get('mcpMaxReconnectAttempts', 3);
                this.autoReconnect = newConfig.get('mcpAutoReconnect', false);

                // Handle telemetry configuration changes
                const newTelemetryEnabled = newConfig.get('telemetryEnabled', false);
                if (newTelemetryEnabled && !this.razeClient) {
                    this.razeClient = new RazeClient(context, {
                        serviceName: 'amprealize-mcp-client',
                    });
                }
                this.telemetryEnabled = newTelemetryEnabled;
            }
        });
    }

    // ============================================
    // Connection Management
    // ============================================

    /**
     * Get current connection status for UI display
     */
    getConnectionStatus(): ConnectionStatus {
        return {
            state: this.connectionState,
            lastHeartbeat: this.lastHeartbeat,
            reconnectAttempts: this.reconnectAttempts,
            lastError: this.lastError
        };
    }

    /**
     * Check if the MCP client is connected
     */
    isConnected(): boolean {
        return this.connectionState === 'connected';
    }

    /**
     * Connect to the MCP server (spawns amprealize.mcp_server as subprocess)
     */
    async connect(): Promise<void> {
        if (this.connectionState === 'connected') {
            return;
        }

        if (this.connectionPromise) {
            return this.connectionPromise;
        }

        this.setConnectionState('connecting');
        this.connectionPromise = this.doConnect();
        try {
            await this.connectionPromise;
            this.reconnectAttempts = 0;
            this.lastError = undefined;
            this.startHeartbeat();
        } catch (error) {
            this.lastError = error instanceof Error ? error.message : String(error);
            throw error;
        } finally {
            this.connectionPromise = null;
        }
    }

    private async doConnect(): Promise<void> {
        return new Promise((resolve, reject) => {
            this.outputChannel.appendLine('Starting MCP server...');

            // Use workspace root if available, fallback to home to avoid temp cleanup
            const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
            const homeDir = process.env.HOME || process.env.USERPROFILE || '/tmp';
            const cwd = workspaceRoot || homeDir;
            this.outputChannel.appendLine(`Starting MCP server with cwd: ${cwd}`);

            this.process = spawn(this.pythonPath, ['-m', 'amprealize.mcp_server'], {
                stdio: ['pipe', 'pipe', 'pipe'],
                cwd,
                // Avoid blocking OS keychain prompts when running in a background
                // stdio subprocess (common cause of "hanging" authStatus/device flow).
                env: {
                    ...process.env,
                    AMPREALIZE_ALLOW_PLAINTEXT_TOKENS: process.env.AMPREALIZE_ALLOW_PLAINTEXT_TOKENS ?? '1'
                }
            });

            // Handle stdout (MCP responses)
            this.process.stdout?.on('data', (data: Buffer) => {
                this.handleData(data.toString());
            });

            // Handle stderr (logs)
            this.process.stderr?.on('data', (data: Buffer) => {
                const text = data.toString();
                this.outputChannel.appendLine(`[stderr] ${text}`);
            });

            // Handle process exit
            this.process.on('close', (code) => {
                this.outputChannel.appendLine(`MCP server exited with code ${code}`);
                this._isConnected = false;
                this.stopHeartbeat();
                this.setConnectionState('disconnected');
                this.rejectAllPending(new Error(`MCP server exited with code ${code}`));
                this.emit('disconnected', code);

                // Attempt auto-reconnect if enabled and not intentionally disconnected
                if (this.autoReconnect && code !== 0) {
                    this.scheduleReconnect();
                }
            });

            this.process.on('error', (err) => {
                this.outputChannel.appendLine(`MCP server error: ${err.message}`);
                this._isConnected = false;
                this.lastError = err.message;
                this.setConnectionState('disconnected');
                reject(err);
            });

            // Send initialize request
            const initTimeoutMs = 30000;
            setTimeout(async () => {
                try {
                    await this.sendRequestWithTimeout('initialize', {
                        protocolVersion: '2024-11-05',
                        capabilities: {},
                        clientInfo: {
                            name: 'amprealize-vscode',
                            version: '1.0.0'
                        }
                    }, initTimeoutMs); // Allow slow startups

                    // Send initialized notification
                    this.sendNotification('notifications/initialized', {});

                    this._isConnected = true;
                    this.setConnectionState('connected');
                    this.outputChannel.appendLine('MCP connection established');
                    this.emit('connected');

                    // Flush queued requests
                    this.flushRequestQueue();

                    resolve();
                } catch (err) {
                    this.lastError = err instanceof Error ? err.message : String(err);
                    reject(err);
                }
            }, 500); // Give process a bit more time to start
        });
    }

    /**
     * Disconnect from the MCP server
     */
    disconnect(): void {
        // Disable auto-reconnect when explicitly disconnecting
        const savedAutoReconnect = this.autoReconnect;
        this.autoReconnect = false;

        this.stopHeartbeat();

        if (this.process) {
            this.process.kill();
            this.process = null;
        }
        this._isConnected = false;
        this.setConnectionState('disconnected');
        this.rejectAllPending(new Error('Client disconnected'));

        // Restore auto-reconnect setting
        this.autoReconnect = savedAutoReconnect;
    }

    /**
     * Check if connected
     */
    get connected(): boolean {
        return this._isConnected;
    }

    // ============================================
    // Heartbeat & Reconnection
    // ============================================

    private setConnectionState(state: ConnectionState): void {
        const previousState = this.connectionState;
        this.connectionState = state;
        if (previousState !== state) {
            this.emit('connectionStateChanged', { previousState, currentState: state });

            // Log telemetry for state changes (behavior_use_raze_for_logging)
            this.logTelemetry('info', `MCP connection state changed: ${previousState} -> ${state}`, {
                previousState,
                currentState: state,
                reconnectAttempts: this.reconnectAttempts,
            });
        }
    }

    /**
     * Log telemetry event using Raze (behavior_use_raze_for_logging)
     */
    private logTelemetry(level: LogLevel, message: string, context?: Record<string, unknown>): void {
        if (this.telemetryEnabled && this.razeClient) {
            this.razeClient.log(level, message, {
                ...context,
                component: 'McpClient',
                actor_surface: 'MCP',  // IDE-agnostic: works across VS Code, Cursor, Claude Desktop
            });
        }
    }

    private startHeartbeat(): void {
        this.stopHeartbeat();
        this.heartbeatInterval = setInterval(async () => {
            if (!this.isConnected()) {
                return;
            }
            try {
                await this.ping();
                this.lastHeartbeat = new Date();
                this.heartbeatFailures = 0;
                this.emit('heartbeat', { timestamp: this.lastHeartbeat });

                // Log heartbeat telemetry (behavior_use_raze_for_logging)
                this.logTelemetry('debug', 'MCP heartbeat successful', {
                    timestamp: this.lastHeartbeat.toISOString(),
                });
            } catch (error) {
                const errorMessage = error instanceof Error ? error.message : String(error);
                this.outputChannel.appendLine(`Heartbeat failed: ${errorMessage}`);
                this.emit('heartbeatFailed', { error });

                // Log heartbeat failure telemetry (behavior_use_raze_for_logging)
                this.logTelemetry('warning', 'MCP heartbeat failed', {
                    error: errorMessage,
                    autoReconnect: this.autoReconnect,
                });

                // Heartbeat failure - allow a few misses before reconnecting
                this.heartbeatFailures += 1;
                if (this.autoReconnect && this.heartbeatFailures >= 3) {
                    this.outputChannel.appendLine('Heartbeat failed 3 times, initiating reconnect...');
                    this.disconnect();
                }
            }
        }, this.heartbeatIntervalMs);
    }

    private stopHeartbeat(): void {
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
            this.heartbeatInterval = null;
        }
    }

    private scheduleReconnect(): void {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            this.outputChannel.appendLine(`Max reconnect attempts (${this.maxReconnectAttempts}) reached, giving up`);
            this.emit('reconnectFailed', { attempts: this.reconnectAttempts });

            // Log reconnection failure telemetry (behavior_use_raze_for_logging)
            this.logTelemetry('error', 'MCP reconnection failed - max attempts reached', {
                maxAttempts: this.maxReconnectAttempts,
                totalAttempts: this.reconnectAttempts,
            });
            return;
        }

        // Exponential backoff: 1s, 2s, 4s, 8s, 16s, max 30s
        const backoffMs = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
        this.reconnectAttempts++;

        this.outputChannel.appendLine(`Scheduling reconnect attempt ${this.reconnectAttempts} in ${backoffMs}ms`);
        this.setConnectionState('reconnecting');
        this.emit('reconnecting', { attempt: this.reconnectAttempts, backoffMs });

        // Log reconnection attempt telemetry (behavior_use_raze_for_logging)
        this.logTelemetry('info', 'MCP scheduling reconnection attempt', {
            attempt: this.reconnectAttempts,
            backoffMs,
            maxAttempts: this.maxReconnectAttempts,
        });

        setTimeout(async () => {
            try {
                this.outputChannel.appendLine(`Reconnect attempt ${this.reconnectAttempts}...`);
                await this.connect();
                this.outputChannel.appendLine('Reconnect successful');
                this.emit('reconnected', { attempts: this.reconnectAttempts });

                // Log successful reconnection telemetry (behavior_use_raze_for_logging)
                this.logTelemetry('info', 'MCP reconnection successful', {
                    totalAttempts: this.reconnectAttempts,
                });
            } catch (error) {
                const errorMessage = error instanceof Error ? error.message : String(error);
                this.outputChannel.appendLine(`Reconnect attempt ${this.reconnectAttempts} failed: ${errorMessage}`);

                // Log reconnection failure telemetry (behavior_use_raze_for_logging)
                this.logTelemetry('warning', 'MCP reconnection attempt failed', {
                    attempt: this.reconnectAttempts,
                    error: errorMessage,
                });
                // Next reconnect will be scheduled by the 'close' event handler
            }
        }, backoffMs);
    }

    /**
     * Send a ping to check server health
     */
    async ping(): Promise<{ status: string }> {
        const result = await this.sendRequestWithTimeout('ping', {}, 15000);
        return result as { status: string };
    }

    private async flushRequestQueue(): Promise<void> {
        const queue = [...this.requestQueue];
        this.requestQueue = [];

        for (const queuedRequest of queue) {
            try {
                const result = await this.sendRequest(queuedRequest.method, queuedRequest.params);
                queuedRequest.resolve(result);
            } catch (error) {
                queuedRequest.reject(error instanceof Error ? error : new Error(String(error)));
            }
        }
    }

    // ============================================
    // Low-level MCP Protocol
    // ============================================

    private handleData(data: string): void {
        this.buffer += data;

        // Parse line-delimited JSON
        const lines = this.buffer.split('\n');
        this.buffer = lines.pop() || '';

        for (const line of lines) {
            if (!line.trim()) {
                continue;
            }

            try {
                const response = JSON.parse(line) as McpResponse;
                this.outputChannel.appendLine(`[recv] ${line.substring(0, 200)}...`);

                if (response.id !== undefined) {
                    const pending = this.pendingRequests.get(response.id);
                    if (pending) {
                        clearTimeout(pending.timeout);
                        this.pendingRequests.delete(response.id);
                        if (response.error) {
                            pending.reject(new Error(response.error.message));
                        } else {
                            pending.resolve(response.result);
                        }
                    }
                }
            } catch (err) {
                this.outputChannel.appendLine(`Failed to parse: ${line}`);
            }
        }
    }

    private sendRequest(method: string, params?: Record<string, unknown>): Promise<unknown> {
        return this.sendRequestWithTimeout(method, params, this.requestTimeoutMs);
    }

    private sendRequestWithTimeout(method: string, params: Record<string, unknown> | undefined, timeoutMs: number): Promise<unknown> {
        return new Promise((resolve, reject) => {
            // If process isn't available, fail fast
            if (!this.process?.stdin) {
                reject(new Error('MCP server not connected'));
                return;
            }

            // Allow initialize during connecting before isConnected flips true
            if (!this.isConnected()) {
                if (this.connectionState === 'reconnecting') {
                    this.outputChannel.appendLine(`Queuing request during reconnect: ${method}`);
                    this.requestQueue.push({ method, params, resolve, reject });
                    return;
                }

                if (this.connectionState === 'connecting' && method === 'initialize') {
                    this.outputChannel.appendLine('Sending initialize while connecting');
                } else {
                    reject(new Error('MCP server not connected'));
                    return;
                }
            }

            const id = ++this.requestId;
            const request: McpRequest = {
                jsonrpc: '2.0',
                id,
                method,
                params
            };

            // Setup timeout
            const timeout = setTimeout(() => {
                const pending = this.pendingRequests.get(id);
                if (pending) {
                    this.pendingRequests.delete(id);
                    pending.reject(new Error(`Request timeout after ${timeoutMs}ms: ${method}`));
                }
            }, timeoutMs);

            this.pendingRequests.set(id, { resolve, reject, timeout });

            const json = JSON.stringify(request);
            this.outputChannel.appendLine(`[send] ${json.substring(0, 200)}...`);
            this.process.stdin.write(json + '\n');
        });
    }

    private sendNotification(method: string, params?: Record<string, unknown>): void {
        if (!this.process?.stdin) {
            return;
        }

        const notification = {
            jsonrpc: '2.0',
            method,
            params
        };

        const json = JSON.stringify(notification);
        this.process.stdin.write(json + '\n');
    }

    private rejectAllPending(error: Error): void {
        for (const [, pending] of this.pendingRequests) {
            clearTimeout(pending.timeout);
            pending.reject(error);
        }
        this.pendingRequests.clear();

        // Also reject queued requests
        for (const queuedRequest of this.requestQueue) {
            queuedRequest.reject(error);
        }
        this.requestQueue = [];
    }

    // ============================================
    // Tool Invocation
    // ============================================

    /**
     * Call an MCP tool by name
     */
    async callTool<T = unknown>(toolName: string, args: Record<string, unknown> = {}): Promise<T> {
        if (!this.isConnected()) {
            await this.connect();
        }

        const result = await this.sendRequest('tools/call', {
            name: toolName,
            arguments: args
        }) as McpToolResult;

        // Parse the text content
        if (result.content && result.content.length > 0) {
            const textContent = result.content.find(c => c.type === 'text');
            if (textContent) {
                try {
                    return JSON.parse(textContent.text) as T;
                } catch {
                    return textContent.text as unknown as T;
                }
            }
        }

        if (result.isError) {
            throw new Error('Tool returned an error');
        }

        return result as unknown as T;
    }

    /**
     * List available tools
     */
    async listTools(): Promise<Array<{ name: string; description?: string }>> {
        if (!this.isConnected()) {
            await this.connect();
        }

        const result = await this.sendRequest('tools/list', {}) as { tools: Array<{ name: string; description?: string }> };
        return result.tools;
    }

    // ============================================
    // Device Flow Authentication
    // ============================================

    /**
     * Initialize device authorization flow
     */
    async deviceInit(params: {
        clientId?: string;
        scopes?: string[];
    } = {}): Promise<DeviceInitResult> {
        return this.callTool<DeviceInitResult>('auth.deviceInit', {
            client_id: params.clientId || 'amprealize-vscode',
            scopes: params.scopes || ['actions:read', 'actions:write', 'behaviors:read']
        });
    }

    /**
     * Poll device authorization status
     */
    async devicePoll(params: {
        deviceCode: string;
        clientId?: string;
    }): Promise<DevicePollResult> {
        return this.callTool<DevicePollResult>('auth.devicePoll', {
            device_code: params.deviceCode,
            client_id: params.clientId || 'amprealize-vscode'
        });
    }

    /**
     * Refresh access token
     */
    async authRefresh(params: {
        refreshToken: string;
        clientId?: string;
    }): Promise<AuthRefreshResult> {
        return this.callTool<AuthRefreshResult>('auth.refresh', {
            refresh_token: params.refreshToken,
            client_id: params.clientId || 'amprealize-vscode'
        });
    }

    // ============================================
    // Consent Management
    // ============================================

    /**
     * Look up consent status by user code
     */
    async consentLookup(userCode: string): Promise<ConsentStatus> {
        return this.callTool<ConsentStatus>('consent.lookup', {
            user_code: userCode
        });
    }

    /**
     * Approve consent request
     */
    async consentApprove(params: {
        userCode: string;
        scopes?: string[];
    }): Promise<{ success: boolean; granted_scopes?: string[] }> {
        return this.callTool('consent.approve', {
            user_code: params.userCode,
            scopes: params.scopes
        });
    }

    /**
     * Deny consent request
     */
    async consentDeny(params: {
        userCode: string;
        reason?: string;
    }): Promise<{ success: boolean }> {
        return this.callTool('consent.deny', {
            user_code: params.userCode,
            reason: params.reason
        });
    }

    // ============================================
    // Behaviors (example of migrating from CLI)
    // ============================================

    /**
     * Retrieve behaviors using BCI
     */
    async bciRetrieve(params: {
        query: string;
        topK?: number;
        strategy?: 'embedding' | 'keyword' | 'hybrid';
        roleFocus?: string;
        tags?: string[];
    }): Promise<unknown> {
        return this.callTool('bci.retrieve', {
            query: params.query,
            top_k: params.topK || 5,
            strategy: params.strategy || 'hybrid',
            role_focus: params.roleFocus,
            tags: params.tags
        });
    }

    /**
     * Full runtime injection: resolve context, retrieve behaviors, compose enriched prompt.
     * E3 S3.3 (T3.3.2): Inject context blocks into extension chat.
     */
    async bciInject(params: {
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
    }> {
        return this.callTool('bci.inject', {
            task: params.task,
            surface: params.surface || 'vscode',
            role: params.role,
            workspace_path: params.workspacePath,
            top_k: params.topK || 5,
            strategy: params.strategy || 'hybrid',
            format: params.format || 'list',
            citation_mode: params.citationMode || 'explicit',
            tags: params.tags,
            phase: params.phase
        });
    }

    // ============================================
    // BreakerAmp Environment Orchestration
    // ============================================

    /**
     * Plan an breakeramp environment from a blueprint
     */
    async breakerampPlan(params: {
        blueprintId: string;
        environment?: string;
        checklistId?: string;
        lifetime?: string;
        complianceTier?: 'dev' | 'prod-sim' | 'pci-sandbox';
        behaviors?: string[];
        variables?: Record<string, string>;
    }): Promise<BreakerAmpPlanResult> {
        return this.callTool<BreakerAmpPlanResult>('breakeramp.plan', {
            blueprint_id: params.blueprintId,
            environment: params.environment || 'development',
            checklist_id: params.checklistId,
            lifetime: params.lifetime || '90m',
            compliance_tier: params.complianceTier || 'dev',
            behaviors: params.behaviors,
            variables: params.variables
        });
    }

    /**
     * Apply an breakeramp plan to create resources
     */
    async breakerampApply(params: {
        planId?: string;
        manifestFile?: string;
        watch?: boolean;
        resume?: boolean;
    }): Promise<BreakerAmpApplyResult> {
        return this.callTool<BreakerAmpApplyResult>('breakeramp.apply', {
            plan_id: params.planId,
            manifest_file: params.manifestFile,
            watch: params.watch ?? false,
            resume: params.resume ?? false
        });
    }

    /**
     * Get status of an breakeramp run
     */
    async breakerampStatus(runId: string): Promise<BreakerAmpStatusResult> {
        return this.callTool<BreakerAmpStatusResult>('breakeramp.status', {
            run_id: runId
        });
    }

    /**
     * Destroy resources from an breakeramp run
     */
    async breakerampDestroy(params: {
        runId: string;
        cascade?: boolean;
        reason?: 'POST_TEST' | 'FAILED' | 'ABANDONED' | 'MANUAL';
    }): Promise<BreakerAmpDestroyResult> {
        return this.callTool<BreakerAmpDestroyResult>('breakeramp.destroy', {
            run_id: params.runId,
            cascade: params.cascade ?? true,
            reason: params.reason || 'MANUAL'
        });
    }

    /**
     * List available blueprints
     */
    async breakerampListBlueprints(params?: {
        source?: 'all' | 'package' | 'user';
    }): Promise<BreakerAmpListBlueprintsResult> {
        return this.callTool<BreakerAmpListBlueprintsResult>('breakeramp.listBlueprints', {
            source: params?.source || 'all'
        });
    }

    /**
     * List active environments
     */
    async breakerampListEnvironments(params?: {
        phase?: 'planned' | 'applying' | 'running' | 'stopping' | 'stopped' | 'failed' | 'destroyed' | 'all';
    }): Promise<BreakerAmpListEnvironmentsResult> {
        return this.callTool<BreakerAmpListEnvironmentsResult>('breakeramp.listEnvironments', {
            phase: params?.phase || 'all'
        });
    }

    /**
     * Configure breakeramp in a directory
     */
    async breakerampConfigure(params?: {
        configDir?: string;
        includeBlueprints?: boolean;
        blueprints?: string[];
        force?: boolean;
    }): Promise<BreakerAmpConfigureResult> {
        return this.callTool<BreakerAmpConfigureResult>('breakeramp.configure', {
            config_dir: params?.configDir,
            include_blueprints: params?.includeBlueprints ?? false,
            blueprints: params?.blueprints,
            force: params?.force ?? false
        });
    }

    // ============================================
    // Action Registry (behavior_sanitize_action_registry)
    // ============================================

    /**
     * Record a new build action for reproducibility tracking
     */
    async actionCreate(params: {
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
    }): Promise<ActionCreateResult> {
        const config = vscode.workspace.getConfiguration('amprealize');
        const actorId = config.get<string>('telemetryActorId', 'vscode-user');
        const actorRole = config.get<string>('telemetryActorRole', 'STUDENT') as 'STRATEGIST' | 'TEACHER' | 'STUDENT' | 'ADMIN';

        return this.callTool<ActionCreateResult>('actions.create', {
            artifact_path: params.artifactPath,
            summary: params.summary,
            behaviors_cited: params.behaviorsCited,
            metadata: params.metadata ? {
                commands: params.metadata.commands,
                validation_output: params.metadata.validationOutput,
                related_links: params.metadata.relatedLinks
            } : undefined,
            related_run_id: params.relatedRunId,
            checksum: params.checksum,
            tier: params.tier,
            actor: {
                id: params.actor?.id || actorId,
                role: params.actor?.role || actorRole,
                surface: 'MCP'
            }
        });
    }

    /**
     * List recorded build actions with optional filtering
     */
    async actionList(params?: {
        artifactPathFilter?: string;
        behaviorId?: string;
        relatedRunId?: string;
        limit?: number;
        actor?: {
            id: string;
            role: 'STRATEGIST' | 'TEACHER' | 'STUDENT' | 'ADMIN';
        };
    }): Promise<ActionListResult> {
        const config = vscode.workspace.getConfiguration('amprealize');
        const actorId = config.get<string>('telemetryActorId', 'vscode-user');
        const actorRole = config.get<string>('telemetryActorRole', 'STUDENT') as 'STRATEGIST' | 'TEACHER' | 'STUDENT' | 'ADMIN';

        return this.callTool<ActionListResult>('actions.list', {
            artifact_path_filter: params?.artifactPathFilter,
            behavior_id: params?.behaviorId,
            related_run_id: params?.relatedRunId,
            limit: params?.limit || 20,
            actor: {
                id: params?.actor?.id || actorId,
                role: params?.actor?.role || actorRole,
                surface: 'MCP'
            }
        });
    }

    /**
     * Get details of a specific action
     */
    async actionGet(actionId: string): Promise<ActionGetResult> {
        const config = vscode.workspace.getConfiguration('amprealize');
        const actorId = config.get<string>('telemetryActorId', 'vscode-user');
        const actorRole = config.get<string>('telemetryActorRole', 'STUDENT') as 'STRATEGIST' | 'TEACHER' | 'STUDENT' | 'ADMIN';

        return this.callTool<ActionGetResult>('actions.get', {
            action_id: actionId,
            actor: {
                id: actorId,
                role: actorRole,
                surface: 'MCP'
            }
        });
    }

    /**
     * Launch a replay job to reproduce one or more actions
     */
    async actionReplay(params: {
        actionIds: string[];
        strategy?: 'SEQUENTIAL' | 'PARALLEL';
        options?: {
            skipExisting?: boolean;
            dryRun?: boolean;
        };
        tier?: 'hot' | 'warm' | 'cold';
    }): Promise<ActionReplayResult> {
        const config = vscode.workspace.getConfiguration('amprealize');
        const actorId = config.get<string>('telemetryActorId', 'vscode-user');

        return this.callTool<ActionReplayResult>('actions.replay', {
            action_ids: params.actionIds,
            strategy: params.strategy || 'SEQUENTIAL',
            options: params.options ? {
                skip_existing: params.options.skipExisting ?? false,
                dry_run: params.options.dryRun ?? false
            } : undefined,
            tier: params.tier,
            actor: {
                id: actorId,
                role: 'STRATEGIST',  // Replay requires STRATEGIST or ADMIN
                surface: 'MCP'
            }
        });
    }

    /**
     * Get status of a replay job
     */
    async actionReplayStatus(replayId: string): Promise<ActionReplayStatusResult> {
        const config = vscode.workspace.getConfiguration('amprealize');
        const actorId = config.get<string>('telemetryActorId', 'vscode-user');
        const actorRole = config.get<string>('telemetryActorRole', 'STUDENT') as 'STRATEGIST' | 'TEACHER' | 'STUDENT' | 'ADMIN';

        return this.callTool<ActionReplayStatusResult>('actions.replayStatus', {
            replay_id: replayId,
            actor: {
                id: actorId,
                role: actorRole,
                surface: 'MCP'
            }
        });
    }

    // ============================================
    // Bootstrap Tools (AMPREALIZE-276)
    // ============================================

    async bootstrapDetect(params?: { workspace_path?: string }): Promise<BootstrapDetectResult> {
        return this.callTool<BootstrapDetectResult>('bootstrap.detect', params || {});
    }

    async bootstrapStatus(params?: { workspace_path?: string }): Promise<BootstrapStatusResult> {
        return this.callTool<BootstrapStatusResult>('bootstrap.status', params || {});
    }

    async bootstrapInit(params: {
        workspace_path?: string;
        profile?: string;
        skip_primer?: boolean;
        skip_pack?: boolean;
        force?: boolean;
    }): Promise<BootstrapInitResult> {
        return this.callTool<BootstrapInitResult>('bootstrap.init', params);
    }

    // ============================================
    // Lifecycle
    // ============================================

    dispose(): void {
        this.stopHeartbeat();
        this.disconnect();
        this.outputChannel.dispose();
    }
}
