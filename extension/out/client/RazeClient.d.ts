/**
 * Raze Structured Logging Client for VS Code Extension
 *
 * Provides a TypeScript client for the Raze logging system that:
 * - Buffers log entries locally with configurable batch size and linger time
 * - Posts batches to /v1/logs/ingest REST endpoint
 * - Supports query and aggregation APIs
 * - Automatically flushes on extension deactivation
 *
 * @see packages/raze/ for the backend implementation
 * @see MCP_SERVER_DESIGN.md for service contracts
 */
import * as vscode from 'vscode';
export type LogLevel = 'trace' | 'debug' | 'info' | 'warning' | 'error' | 'critical';
export interface LogEntry {
    level: LogLevel;
    message: string;
    timestamp?: string;
    service_name?: string;
    context?: Record<string, unknown>;
    run_id?: string;
    behavior_id?: string;
    tags?: string[];
    schema_version?: string;
}
export interface LogQueryParams {
    start_time?: string;
    end_time?: string;
    level?: LogLevel | LogLevel[];
    service_name?: string | string[];
    run_id?: string;
    behavior_id?: string;
    search?: string;
    tags?: string[];
    limit?: number;
    offset?: number;
    order?: 'asc' | 'desc';
}
export interface LogQueryResult {
    logs: StoredLogEntry[];
    total: number;
    has_more: boolean;
    query_time_ms: number;
}
export interface StoredLogEntry extends LogEntry {
    log_id: string;
    timestamp: string;
    service_name: string;
}
export interface LogAggregateParams {
    start_time?: string;
    end_time?: string;
    group_by: ('level' | 'service_name' | 'behavior_id' | 'hour' | 'day')[];
    level?: LogLevel | LogLevel[];
    service_name?: string | string[];
}
export interface LogAggregateBucket {
    dimensions: Record<string, string>;
    count: number;
    earliest: string;
    latest: string;
}
export interface LogAggregateResult {
    buckets: LogAggregateBucket[];
    total_count: number;
    query_time_ms: number;
}
export interface IngestResponse {
    accepted: number;
    rejected: number;
    log_ids?: string[];
    errors?: Array<{
        index: number;
        error: string;
    }>;
}
export interface RazeClientOptions {
    /** Base URL for Raze API (default: from settings or http://localhost:8080) */
    baseUrl?: string;
    /** Service name to tag all logs with */
    serviceName?: string;
    /** Maximum entries to buffer before auto-flush (default: 100) */
    maxBufferSize?: number;
    /** Maximum time in ms to wait before flushing (default: 5000) */
    lingerMs?: number;
    /** Whether to enable console fallback on API failure (default: true) */
    fallbackToConsole?: boolean;
    /** Output channel for debug logging */
    outputChannel?: vscode.OutputChannel;
}
interface RazeStats {
    totalEmitted: number;
    totalFlushed: number;
    totalErrors: number;
    startTime: number;
}
export declare class RazeClient {
    private readonly context;
    private readonly baseUrl;
    private readonly serviceName;
    private readonly maxBufferSize;
    private readonly lingerMs;
    private readonly fallbackToConsole;
    private readonly outputChannel?;
    private buffer;
    private lingerTimer;
    private flushPromise;
    private stats;
    constructor(context: vscode.ExtensionContext, options?: RazeClientOptions);
    /**
     * Log a message at the specified level
     */
    log(level: LogLevel, message: string, context?: Record<string, unknown>): void;
    /** Log at TRACE level */
    trace(message: string, context?: Record<string, unknown>): void;
    /** Log at DEBUG level */
    debug(message: string, context?: Record<string, unknown>): void;
    /** Log at INFO level */
    info(message: string, context?: Record<string, unknown>): void;
    /** Log at WARNING level */
    warn(message: string, context?: Record<string, unknown>): void;
    /** Log at ERROR level */
    error(message: string, context?: Record<string, unknown>): void;
    /** Log at CRITICAL level */
    critical(message: string, context?: Record<string, unknown>): void;
    /**
     * Log with run/behavior context
     */
    logWithContext(level: LogLevel, message: string, opts: {
        runId?: string;
        behaviorId?: string;
        tags?: string[];
        context?: Record<string, unknown>;
    }): void;
    private emit;
    /**
     * Force flush all buffered entries to the server
     */
    flush(): Promise<IngestResponse>;
    /**
     * Ingest a batch of log entries via REST API
     */
    ingestBatch(entries: LogEntry[]): Promise<IngestResponse>;
    /**
     * Query logs with filters
     */
    query(params: LogQueryParams): Promise<LogQueryResult>;
    /**
     * Aggregate logs by dimensions
     */
    aggregate(params: LogAggregateParams): Promise<LogAggregateResult>;
    /**
     * Get client status and statistics
     */
    getStatus(): {
        serviceName: string;
        bufferSize: number;
        maxBufferSize: number;
        lingerMs: number;
        stats: RazeStats;
        uptimeSeconds: number;
    };
    /**
     * Dispose the client, flushing any remaining entries
     */
    dispose(): Promise<void>;
    private debugLog;
}
/**
 * Get or create a shared RazeClient instance
 */
export declare function getRazeClient(context: vscode.ExtensionContext, options?: RazeClientOptions): RazeClient;
/**
 * Convenience function for quick logging without managing client lifecycle
 */
export declare function razeLog(context: vscode.ExtensionContext, level: LogLevel, message: string, logContext?: Record<string, unknown>): void;
export {};
//# sourceMappingURL=RazeClient.d.ts.map
