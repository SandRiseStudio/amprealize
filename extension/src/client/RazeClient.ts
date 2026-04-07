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
import * as https from 'https';
import * as http from 'http';
import { URL } from 'url';

// ─────────────────────────────────────────────────────────────────────────────
// Types and Interfaces
// ─────────────────────────────────────────────────────────────────────────────

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
	errors?: Array<{ index: number; error: string }>;
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

// ─────────────────────────────────────────────────────────────────────────────
// HTTP Helper
// ─────────────────────────────────────────────────────────────────────────────

interface HttpResponse<T> {
	statusCode: number;
	data: T;
}

function httpRequest<T>(
	method: 'GET' | 'POST',
	urlString: string,
	body?: unknown
): Promise<HttpResponse<T>> {
	return new Promise((resolve, reject) => {
		const url = new URL(urlString);
		const isHttps = url.protocol === 'https:';
		const lib = isHttps ? https : http;

		const options: http.RequestOptions = {
			method,
			hostname: url.hostname,
			port: url.port || (isHttps ? 443 : 80),
			path: url.pathname + url.search,
			headers: {
				'Accept': 'application/json',
				'Content-Type': 'application/json',
			},
		};

		const req = lib.request(options, (res) => {
			let data = '';
			res.on('data', (chunk) => {
				data += chunk;
			});
			res.on('end', () => {
				try {
					const parsed = data ? JSON.parse(data) as T : ({} as T);
					resolve({
						statusCode: res.statusCode ?? 0,
						data: parsed,
					});
				} catch (e) {
					reject(new Error(`Failed to parse response: ${data}`));
				}
			});
		});

		req.on('error', (e) => {
			reject(e);
		});

		if (body) {
			req.write(JSON.stringify(body));
		}

		req.end();
	});
}

// ─────────────────────────────────────────────────────────────────────────────
// RazeClient Implementation
// ─────────────────────────────────────────────────────────────────────────────

export class RazeClient {
	private readonly baseUrl: string;
	private readonly serviceName: string;
	private readonly maxBufferSize: number;
	private readonly lingerMs: number;
	private readonly fallbackToConsole: boolean;
	private readonly outputChannel?: vscode.OutputChannel;

	private buffer: LogEntry[] = [];
	private lingerTimer: ReturnType<typeof setTimeout> | null = null;
	private flushPromise: Promise<void> | null = null;
	private stats: RazeStats = {
		totalEmitted: 0,
		totalFlushed: 0,
		totalErrors: 0,
		startTime: Date.now(),
	};

	constructor(
		private readonly context: vscode.ExtensionContext,
		options: RazeClientOptions = {}
	) {
		const config = vscode.workspace.getConfiguration('amprealize');

		this.baseUrl = options.baseUrl ?? config.get('apiBaseUrl', 'http://localhost:8080');
		this.serviceName = options.serviceName ?? 'amprealize-vscode-extension';
		this.maxBufferSize = options.maxBufferSize ?? 100;
		this.lingerMs = options.lingerMs ?? 5000;
		this.fallbackToConsole = options.fallbackToConsole ?? true;
		this.outputChannel = options.outputChannel;

		// Register cleanup on extension deactivation
		context.subscriptions.push({
			dispose: () => this.dispose(),
		});
	}

	// ─────────────────────────────────────────────────────────────────────────
	// Logging Methods
	// ─────────────────────────────────────────────────────────────────────────

	/**
	 * Log a message at the specified level
	 */
	log(level: LogLevel, message: string, context?: Record<string, unknown>): void {
		const entry: LogEntry = {
			level,
			message,
			timestamp: new Date().toISOString(),
			service_name: this.serviceName,
			context,
			schema_version: 'v1',
		};
		this.emit(entry);
	}

	/** Log at TRACE level */
	trace(message: string, context?: Record<string, unknown>): void {
		this.log('trace', message, context);
	}

	/** Log at DEBUG level */
	debug(message: string, context?: Record<string, unknown>): void {
		this.log('debug', message, context);
	}

	/** Log at INFO level */
	info(message: string, context?: Record<string, unknown>): void {
		this.log('info', message, context);
	}

	/** Log at WARNING level */
	warn(message: string, context?: Record<string, unknown>): void {
		this.log('warning', message, context);
	}

	/** Log at ERROR level */
	error(message: string, context?: Record<string, unknown>): void {
		this.log('error', message, context);
	}

	/** Log at CRITICAL level */
	critical(message: string, context?: Record<string, unknown>): void {
		this.log('critical', message, context);
	}

	/**
	 * Log with run/behavior context
	 */
	logWithContext(
		level: LogLevel,
		message: string,
		opts: {
			runId?: string;
			behaviorId?: string;
			tags?: string[];
			context?: Record<string, unknown>;
		}
	): void {
		const entry: LogEntry = {
			level,
			message,
			timestamp: new Date().toISOString(),
			service_name: this.serviceName,
			run_id: opts.runId,
			behavior_id: opts.behaviorId,
			tags: opts.tags,
			context: opts.context,
			schema_version: 'v1',
		};
		this.emit(entry);
	}

	// ─────────────────────────────────────────────────────────────────────────
	// Buffer Management
	// ─────────────────────────────────────────────────────────────────────────

	private emit(entry: LogEntry): void {
		this.buffer.push(entry);
		this.stats.totalEmitted++;

		// Start linger timer if not running
		if (!this.lingerTimer) {
			this.lingerTimer = setTimeout(() => {
				this.lingerTimer = null;
				this.flush().catch((err) => {
					this.debugLog(`Linger flush failed: ${err}`);
				});
			}, this.lingerMs);
		}

		// Flush if buffer is full
		if (this.buffer.length >= this.maxBufferSize) {
			this.flush().catch((err) => {
				this.debugLog(`Buffer full flush failed: ${err}`);
			});
		}
	}

	/**
	 * Force flush all buffered entries to the server
	 */
	async flush(): Promise<IngestResponse> {
		// Wait for any in-progress flush
		if (this.flushPromise) {
			await this.flushPromise;
		}

		// Clear linger timer
		if (this.lingerTimer) {
			clearTimeout(this.lingerTimer);
			this.lingerTimer = null;
		}

		// Swap buffer
		const entries = this.buffer;
		this.buffer = [];

		if (entries.length === 0) {
			return { accepted: 0, rejected: 0 };
		}

		// Create flush promise
		let resolveFlush: (() => void) | undefined;
		this.flushPromise = new Promise<void>((resolve) => {
			resolveFlush = resolve;
		});

		try {
			const result = await this.ingestBatch(entries);
			this.stats.totalFlushed += result.accepted;
			this.stats.totalErrors += result.rejected;
			return result;
		} catch (err) {
			// On failure, fallback to console if enabled
			if (this.fallbackToConsole) {
				for (const entry of entries) {
					console.log(`[RAZE:${entry.level}] ${entry.message}`, entry.context);
				}
			}
			this.stats.totalErrors += entries.length;
			throw err;
		} finally {
			if (resolveFlush) {
				resolveFlush();
			}
			this.flushPromise = null;
		}
	}

	// ─────────────────────────────────────────────────────────────────────────
	// REST API Methods
	// ─────────────────────────────────────────────────────────────────────────

	/**
	 * Ingest a batch of log entries via REST API
	 */
	async ingestBatch(entries: LogEntry[]): Promise<IngestResponse> {
		const url = `${this.baseUrl}/v1/logs/ingest`;

		try {
			const response = await httpRequest<IngestResponse>('POST', url, { events: entries });

			if (response.statusCode < 200 || response.statusCode >= 300) {
				throw new Error(`Ingest failed: ${response.statusCode}`);
			}

			return response.data;
		} catch (err) {
			this.debugLog(`Ingest request failed: ${err}`);
			throw err;
		}
	}

	/**
	 * Query logs with filters
	 */
	async query(params: LogQueryParams): Promise<LogQueryResult> {
		const url = new URL(`${this.baseUrl}/v1/logs/query`);

		// Add query parameters
		if (params.start_time) {
			url.searchParams.set('start_time', params.start_time);
		}
		if (params.end_time) {
			url.searchParams.set('end_time', params.end_time);
		}
		if (params.level) {
			const levels = Array.isArray(params.level) ? params.level : [params.level];
			levels.forEach(l => url.searchParams.append('level', l));
		}
		if (params.service_name) {
			const services = Array.isArray(params.service_name) ? params.service_name : [params.service_name];
			services.forEach(s => url.searchParams.append('service_name', s));
		}
		if (params.run_id) {
			url.searchParams.set('run_id', params.run_id);
		}
		if (params.behavior_id) {
			url.searchParams.set('behavior_id', params.behavior_id);
		}
		if (params.search) {
			url.searchParams.set('search', params.search);
		}
		if (params.tags) {
			params.tags.forEach(t => url.searchParams.append('tags', t));
		}
		if (params.limit !== undefined) {
			url.searchParams.set('limit', String(params.limit));
		}
		if (params.offset !== undefined) {
			url.searchParams.set('offset', String(params.offset));
		}
		if (params.order) {
			url.searchParams.set('order', params.order);
		}

		try {
			const response = await httpRequest<LogQueryResult>('GET', url.toString());

			if (response.statusCode < 200 || response.statusCode >= 300) {
				throw new Error(`Query failed: ${response.statusCode}`);
			}

			return response.data;
		} catch (err) {
			this.debugLog(`Query request failed: ${err}`);
			throw err;
		}
	}

	/**
	 * Aggregate logs by dimensions
	 */
	async aggregate(params: LogAggregateParams): Promise<LogAggregateResult> {
		const url = new URL(`${this.baseUrl}/v1/logs/aggregate`);

		// Add query parameters
		if (params.start_time) {
			url.searchParams.set('start_time', params.start_time);
		}
		if (params.end_time) {
			url.searchParams.set('end_time', params.end_time);
		}
		params.group_by.forEach(g => url.searchParams.append('group_by', g));
		if (params.level) {
			const levels = Array.isArray(params.level) ? params.level : [params.level];
			levels.forEach(l => url.searchParams.append('level', l));
		}
		if (params.service_name) {
			const services = Array.isArray(params.service_name) ? params.service_name : [params.service_name];
			services.forEach(s => url.searchParams.append('service_name', s));
		}

		try {
			const response = await httpRequest<LogAggregateResult>('GET', url.toString());

			if (response.statusCode < 200 || response.statusCode >= 300) {
				throw new Error(`Aggregate failed: ${response.statusCode}`);
			}

			return response.data;
		} catch (err) {
			this.debugLog(`Aggregate request failed: ${err}`);
			throw err;
		}
	}

	// ─────────────────────────────────────────────────────────────────────────
	// Status and Lifecycle
	// ─────────────────────────────────────────────────────────────────────────

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
	} {
		return {
			serviceName: this.serviceName,
			bufferSize: this.buffer.length,
			maxBufferSize: this.maxBufferSize,
			lingerMs: this.lingerMs,
			stats: { ...this.stats },
			uptimeSeconds: (Date.now() - this.stats.startTime) / 1000,
		};
	}

	/**
	 * Dispose the client, flushing any remaining entries
	 */
	async dispose(): Promise<void> {
		this.debugLog('Disposing RazeClient, flushing buffer...');

		// Clear linger timer
		if (this.lingerTimer) {
			clearTimeout(this.lingerTimer);
			this.lingerTimer = null;
		}

		// Final flush
		try {
			await this.flush();
			this.debugLog('Final flush completed');
		} catch (err) {
			this.debugLog(`Final flush failed: ${err}`);
		}
	}

	// ─────────────────────────────────────────────────────────────────────────
	// Helpers
	// ─────────────────────────────────────────────────────────────────────────

	private debugLog(message: string): void {
		if (this.outputChannel) {
			this.outputChannel.appendLine(`[RazeClient] ${message}`);
		}
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// Factory Function
// ─────────────────────────────────────────────────────────────────────────────

let sharedClient: RazeClient | null = null;

/**
 * Get or create a shared RazeClient instance
 */
export function getRazeClient(
	context: vscode.ExtensionContext,
	options?: RazeClientOptions
): RazeClient {
	if (!sharedClient) {
		sharedClient = new RazeClient(context, options);
	}
	return sharedClient;
}

/**
 * Convenience function for quick logging without managing client lifecycle
 */
export function razeLog(
	context: vscode.ExtensionContext,
	level: LogLevel,
	message: string,
	logContext?: Record<string, unknown>
): void {
	getRazeClient(context).log(level, message, logContext);
}
