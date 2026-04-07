"use strict";
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
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.RazeClient = void 0;
exports.getRazeClient = getRazeClient;
exports.razeLog = razeLog;
const vscode = __importStar(require("vscode"));
const https = __importStar(require("https"));
const http = __importStar(require("http"));
const url_1 = require("url");
function httpRequest(method, urlString, body) {
    return new Promise((resolve, reject) => {
        const url = new url_1.URL(urlString);
        const isHttps = url.protocol === 'https:';
        const lib = isHttps ? https : http;
        const options = {
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
                    const parsed = data ? JSON.parse(data) : {};
                    resolve({
                        statusCode: res.statusCode ?? 0,
                        data: parsed,
                    });
                }
                catch (e) {
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
class RazeClient {
    constructor(context, options = {}) {
        this.context = context;
        this.buffer = [];
        this.lingerTimer = null;
        this.flushPromise = null;
        this.stats = {
            totalEmitted: 0,
            totalFlushed: 0,
            totalErrors: 0,
            startTime: Date.now(),
        };
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
    log(level, message, context) {
        const entry = {
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
    trace(message, context) {
        this.log('trace', message, context);
    }
    /** Log at DEBUG level */
    debug(message, context) {
        this.log('debug', message, context);
    }
    /** Log at INFO level */
    info(message, context) {
        this.log('info', message, context);
    }
    /** Log at WARNING level */
    warn(message, context) {
        this.log('warning', message, context);
    }
    /** Log at ERROR level */
    error(message, context) {
        this.log('error', message, context);
    }
    /** Log at CRITICAL level */
    critical(message, context) {
        this.log('critical', message, context);
    }
    /**
     * Log with run/behavior context
     */
    logWithContext(level, message, opts) {
        const entry = {
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
    emit(entry) {
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
    async flush() {
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
        let resolveFlush;
        this.flushPromise = new Promise((resolve) => {
            resolveFlush = resolve;
        });
        try {
            const result = await this.ingestBatch(entries);
            this.stats.totalFlushed += result.accepted;
            this.stats.totalErrors += result.rejected;
            return result;
        }
        catch (err) {
            // On failure, fallback to console if enabled
            if (this.fallbackToConsole) {
                for (const entry of entries) {
                    console.log(`[RAZE:${entry.level}] ${entry.message}`, entry.context);
                }
            }
            this.stats.totalErrors += entries.length;
            throw err;
        }
        finally {
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
    async ingestBatch(entries) {
        const url = `${this.baseUrl}/v1/logs/ingest`;
        try {
            const response = await httpRequest('POST', url, { events: entries });
            if (response.statusCode < 200 || response.statusCode >= 300) {
                throw new Error(`Ingest failed: ${response.statusCode}`);
            }
            return response.data;
        }
        catch (err) {
            this.debugLog(`Ingest request failed: ${err}`);
            throw err;
        }
    }
    /**
     * Query logs with filters
     */
    async query(params) {
        const url = new url_1.URL(`${this.baseUrl}/v1/logs/query`);
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
            const response = await httpRequest('GET', url.toString());
            if (response.statusCode < 200 || response.statusCode >= 300) {
                throw new Error(`Query failed: ${response.statusCode}`);
            }
            return response.data;
        }
        catch (err) {
            this.debugLog(`Query request failed: ${err}`);
            throw err;
        }
    }
    /**
     * Aggregate logs by dimensions
     */
    async aggregate(params) {
        const url = new url_1.URL(`${this.baseUrl}/v1/logs/aggregate`);
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
            const response = await httpRequest('GET', url.toString());
            if (response.statusCode < 200 || response.statusCode >= 300) {
                throw new Error(`Aggregate failed: ${response.statusCode}`);
            }
            return response.data;
        }
        catch (err) {
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
    getStatus() {
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
    async dispose() {
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
        }
        catch (err) {
            this.debugLog(`Final flush failed: ${err}`);
        }
    }
    // ─────────────────────────────────────────────────────────────────────────
    // Helpers
    // ─────────────────────────────────────────────────────────────────────────
    debugLog(message) {
        if (this.outputChannel) {
            this.outputChannel.appendLine(`[RazeClient] ${message}`);
        }
    }
}
exports.RazeClient = RazeClient;
// ─────────────────────────────────────────────────────────────────────────────
// Factory Function
// ─────────────────────────────────────────────────────────────────────────────
let sharedClient = null;
/**
 * Get or create a shared RazeClient instance
 */
function getRazeClient(context, options) {
    if (!sharedClient) {
        sharedClient = new RazeClient(context, options);
    }
    return sharedClient;
}
/**
 * Convenience function for quick logging without managing client lifecycle
 */
function razeLog(context, level, message, logContext) {
    getRazeClient(context).log(level, message, logContext);
}
//# sourceMappingURL=RazeClient.js.map
