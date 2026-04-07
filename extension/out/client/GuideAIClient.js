"use strict";
/**
 * Amprealize Client
 *
 * Communicates with the amprealize Python CLI to access:
 * - BehaviorService (via MCP tools)
 * - WorkflowService (via MCP tools)
 * - ComplianceService (via MCP tools)
 * - ActionService
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
exports.AmprealizeClient = void 0;
const vscode = __importStar(require("vscode"));
const child_process_1 = require("child_process");
const fs_1 = require("fs");
const os = __importStar(require("os"));
const path = __importStar(require("path"));
class AmprealizeClient {
    constructor(context) {
        this.context = context;
        this.telemetrySurface = 'MCP'; // IDE-agnostic: works across VS Code, Cursor, Claude Desktop
        const config = vscode.workspace.getConfiguration('amprealize');
        this.pythonPath = config.get('pythonPath', 'python');
        this.cliPath = config.get('cliPath', 'amprealize');
        this.apiBaseUrl = config.get('apiBaseUrl', 'http://localhost:8080');
        this.outputChannel = vscode.window.createOutputChannel('Amprealize');
        this.telemetryEnabled = config.get('telemetryEnabled', true);
        this.telemetryActorId = config.get('telemetryActorId', 'ide-user'); // IDE-agnostic default
        this.telemetryActorRole = config.get('telemetryActorRole', 'STUDENT');
    }
    /**
     * Make an HTTP API call to the amprealize backend
     */
    async callAPI(endpoint, method = 'GET', body) {
        const fullUrl = `${this.apiBaseUrl}${endpoint}`;
        this.outputChannel.appendLine(`API ${method}: ${fullUrl}`);
        return new Promise((resolve, reject) => {
            const url = new URL(fullUrl);
            const isHttps = url.protocol === 'https:';
            const httpModule = isHttps ? require('https') : require('http');
            const requestBody = body && method !== 'GET' ? JSON.stringify(body) : undefined;
            const options = {
                hostname: url.hostname,
                port: url.port || (isHttps ? 443 : 80),
                path: url.pathname + url.search,
                method,
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    ...(requestBody ? { 'Content-Length': Buffer.byteLength(requestBody) } : {}),
                },
            };
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const req = httpModule.request(options, (res) => {
                let data = '';
                res.on('data', (chunk) => {
                    data += chunk.toString();
                });
                res.on('end', () => {
                    if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) {
                        try {
                            resolve(JSON.parse(data));
                        }
                        catch {
                            reject(new Error(`Failed to parse response: ${data}`));
                        }
                    }
                    else {
                        this.outputChannel.appendLine(`API error ${res.statusCode}: ${data}`);
                        reject(new Error(`API error ${res.statusCode}: ${data}`));
                    }
                });
            });
            req.on('error', (error) => {
                this.outputChannel.appendLine(`API call failed: ${error.message}`);
                reject(error);
            });
            if (requestBody) {
                req.write(requestBody);
            }
            req.end();
        });
    }
    /**
     * List all behaviors with optional filters
     */
    async listBehaviors(filters, telemetryContext = {}) {
        const args = ['behaviors', 'list'];
        if (filters?.status) {
            args.push('--status', filters.status);
        }
        if (filters?.role_focus) {
            args.push('--role-focus', filters.role_focus);
        }
        if (filters?.tags && filters.tags.length > 0) {
            args.push('--tags', ...filters.tags);
        }
        const startedAt = Date.now();
        const result = await this.runCLI(args);
        const behaviors = result.map((item) => ({
            ...item.behavior,
            versions: item.active_version ? [item.active_version] : []
        }));
        const latencyMs = Date.now() - startedAt;
        this.sendTelemetry('behavior_retrieved', {
            source: telemetryContext.source ?? 'sidebar.initial_load',
            query: telemetryContext.query,
            role_focus: telemetryContext.roleFocus ?? filters?.role_focus,
            result_count: behaviors.length,
            latency_ms: latencyMs,
            behavior_ids: behaviors.map(b => b.behavior_id),
        });
        return behaviors;
    }
    /**
     * Search behaviors with semantic query
     */
    async searchBehaviors(query, filters, telemetryContext = {}) {
        const args = ['behaviors', 'search', '--query', query];
        if (filters?.role_focus) {
            args.push('--role-focus', filters.role_focus);
        }
        if (filters?.tags && filters.tags.length > 0) {
            args.push('--tags', ...filters.tags);
        }
        const startedAt = Date.now();
        const result = await this.runCLI(args);
        const behaviors = result.map((item) => {
            const behavior = {
                ...item.behavior,
                versions: item.active_version ? [item.active_version] : [],
            };
            const metadata = behavior.metadata ? { ...behavior.metadata } : {};
            behavior.metadata = { ...metadata, relevance_score: item.score };
            return behavior;
        });
        const latencyMs = Date.now() - startedAt;
        this.sendTelemetry('behavior_retrieved', {
            source: telemetryContext.source ?? 'sidebar.search',
            query,
            role_focus: telemetryContext.roleFocus ?? filters?.role_focus,
            result_count: behaviors.length,
            latency_ms: latencyMs,
            behavior_ids: behaviors.map((behavior) => behavior.behavior_id),
        });
        return behaviors;
    }
    /**
     * Get behavior details by ID
     */
    async getBehavior(behaviorId, version) {
        const args = ['behaviors', 'get', behaviorId];
        if (version) {
            args.push('--version', version);
        }
        return await this.runCLI(args);
    }
    /**
     * List workflow templates
     */
    async listWorkflowTemplates(role, telemetryContext = {}) {
        const args = ['workflow', 'list-templates'];
        if (role) {
            args.push('--role', role);
        }
        const startedAt = Date.now();
        const templates = await this.runCLI(args);
        const latencyMs = Date.now() - startedAt;
        this.sendTelemetry('workflow_templates_retrieved', {
            source: telemetryContext.source ?? 'plan_composer.load',
            role_focus: telemetryContext.roleFocus ?? role,
            template_count: templates.length,
            latency_ms: latencyMs,
            template_ids: templates.map(t => t.template_id)
        });
        return templates;
    }
    /**
     * Get workflow template details
     */
    async getWorkflowTemplate(templateId) {
        const args = ['workflow', 'get-template', templateId];
        return await this.runCLI(args);
    }
    /**
     * Run a workflow from template
     */
    async runWorkflow(templateId, context, telemetryContext = {}) {
        const args = ['workflow', 'run', templateId];
        if (context) {
            args.push('--context', JSON.stringify(context));
        }
        const startedAt = Date.now();
        const result = await this.runCLI(args);
        const latencyMs = Date.now() - startedAt;
        const behaviorCount = Array.isArray(context?.behaviors) ? context.behaviors.length : 0;
        const contextKeys = context ? Object.keys(context) : [];
        this.sendTelemetry('workflow_run_submitted', {
            source: telemetryContext.source ?? 'plan_composer.run',
            template_id: templateId,
            behavior_count: behaviorCount,
            context_keys: contextKeys,
            latency_ms: latencyMs
        }, { runId: result?.run_id });
        return result;
    }
    /**
     * Get workflow run status
     */
    async getWorkflowStatus(runId) {
        const args = ['workflow', 'status', runId];
        return await this.runCLI(args);
    }
    // ========================================
    // RunService Methods (Epic 5.4)
    // ========================================
    /**
     * List all workflow runs with optional filters
     */
    async listRuns(filters) {
        const args = ['runs', 'list'];
        if (filters?.status) {
            args.push('--status', filters.status);
        }
        if (filters?.workflow_id) {
            args.push('--workflow-id', filters.workflow_id);
        }
        if (filters?.template_id) {
            args.push('--template-id', filters.template_id);
        }
        if (filters?.limit) {
            args.push('--limit', String(filters.limit));
        }
        const startedAt = Date.now();
        const runs = await this.runCLI(args);
        const latencyMs = Date.now() - startedAt;
        this.sendTelemetry('runs_retrieved', {
            source: 'execution_tracker.load',
            status_filter: filters?.status,
            workflow_id: filters?.workflow_id,
            template_id: filters?.template_id,
            run_count: runs.length,
            latency_ms: latencyMs,
            run_ids: runs.map(r => r.run_id)
        });
        return runs;
    }
    /**
     * Get detailed information about a specific run
     */
    async getRun(runId) {
        const args = ['runs', 'get', runId];
        return await this.runCLI(args);
    }
    /**
     * Update run progress and status
     */
    async updateRun(runId, update) {
        const args = ['runs', 'update', runId];
        if (update.status) {
            args.push('--status', update.status);
        }
        if (update.progress_pct !== undefined) {
            args.push('--progress-pct', String(update.progress_pct));
        }
        if (update.message) {
            args.push('--message', update.message);
        }
        if (update.step_id) {
            args.push('--step-id', update.step_id);
        }
        if (update.step_name) {
            args.push('--step-name', update.step_name);
        }
        if (update.step_status) {
            args.push('--step-status', update.step_status);
        }
        if (update.tokens_generated !== undefined) {
            args.push('--tokens-generated', String(update.tokens_generated));
        }
        if (update.tokens_baseline !== undefined) {
            args.push('--tokens-baseline', String(update.tokens_baseline));
        }
        if (update.metadata) {
            args.push('--metadata', JSON.stringify(update.metadata));
        }
        return await this.runCLI(args);
    }
    // ========================================
    // ComplianceService Methods (Epic 5.5)
    // ========================================
    /**
     * List compliance checklists with optional filters
     */
    async listComplianceChecklists(filters) {
        const args = ['compliance', 'list-checklists'];
        if (filters?.milestone) {
            args.push('--milestone', filters.milestone);
        }
        if (filters?.compliance_category && filters.compliance_category.length > 0) {
            args.push('--category', ...filters.compliance_category);
        }
        if (filters?.status_filter) {
            args.push('--status-filter', filters.status_filter);
        }
        const startedAt = Date.now();
        const checklists = await this.runCLI(args);
        const latencyMs = Date.now() - startedAt;
        this.sendTelemetry('compliance_checklists_retrieved', {
            source: 'compliance_panel.load',
            milestone: filters?.milestone,
            compliance_category: filters?.compliance_category,
            status_filter: filters?.status_filter,
            checklist_count: checklists.length,
            latency_ms: latencyMs,
            checklist_ids: checklists.map(c => c.checklist_id)
        });
        return checklists;
    }
    /**
     * Get detailed information about a specific compliance checklist
     */
    async getComplianceChecklist(checklistId) {
        const args = ['compliance', 'get-checklist', checklistId];
        return await this.runCLI(args);
    }
    /**
     * Create a new compliance checklist
     */
    async createComplianceChecklist(checklist) {
        const args = ['compliance', 'create-checklist', checklist.title, '--description', checklist.description];
        if (checklist.template_id) {
            args.push('--template-id', checklist.template_id);
        }
        if (checklist.milestone) {
            args.push('--milestone', checklist.milestone);
        }
        if (checklist.compliance_category.length > 0) {
            args.push('--category', ...checklist.compliance_category);
        }
        return await this.runCLI(args);
    }
    /**
     * Record a step in a compliance checklist
     */
    async recordComplianceStep(step) {
        const args = ['compliance', 'record-step', step.checklist_id, step.title, '--status', step.status];
        if (step.evidence) {
            args.push('--evidence', JSON.stringify(step.evidence));
        }
        if (step.behaviors_cited && step.behaviors_cited.length > 0) {
            args.push('--behaviors-cited', ...step.behaviors_cited);
        }
        if (step.related_run_id) {
            args.push('--related-run-id', step.related_run_id);
        }
        return await this.runCLI(args);
    }
    /**
     * Validate a compliance checklist
     */
    async validateComplianceChecklist(checklistId, actor) {
        const args = ['compliance', 'validate-checklist', checklistId];
        return await this.runCLI(args);
    }
    async bciRetrieve(options) {
        const args = ['bci', 'retrieve', '--query', options.query];
        if (options.topK !== undefined) {
            args.push('--top-k', String(options.topK));
        }
        if (options.strategy) {
            args.push('--strategy', options.strategy);
        }
        if (options.roleFocus) {
            args.push('--role-focus', options.roleFocus);
        }
        if (options.tags && options.tags.length > 0) {
            for (const tag of options.tags) {
                args.push('--tag', tag);
            }
        }
        if (options.includeMetadata) {
            args.push('--include-metadata');
        }
        if (options.embeddingWeight !== undefined) {
            args.push('--embedding-weight', String(options.embeddingWeight));
        }
        if (options.keywordWeight !== undefined) {
            args.push('--keyword-weight', String(options.keywordWeight));
        }
        const response = await this.runCLI(args);
        return response;
    }
    async bciValidateCitations(request) {
        const tmpDir = await fs_1.promises.mkdtemp(path.join(os.tmpdir(), 'amprealize-bci-'));
        const outputPath = path.join(tmpDir, 'output.txt');
        const prependedPath = path.join(tmpDir, 'prepended.json');
        try {
            await fs_1.promises.writeFile(outputPath, request.outputText, 'utf8');
            await fs_1.promises.writeFile(prependedPath, JSON.stringify(request.prepended, null, 2), 'utf8');
            const args = ['bci', 'validate-citations', '--output-file', outputPath, '--prepended-file', prependedPath];
            if (request.minimumCitations !== undefined) {
                args.push('--minimum', String(request.minimumCitations));
            }
            if (request.allowUnlisted) {
                args.push('--allow-unlisted');
            }
            const response = await this.runCLI(args);
            return response;
        }
        finally {
            await this.cleanupTempDir(tmpDir);
        }
    }
    // ─────────────────────────────────────────────────────────────────────────────
    // Agent Registry & Management
    // ─────────────────────────────────────────────────────────────────────────────
    async getAgent(agentId, version) {
        const args = ['agent-registry', 'get', '--agent-id', agentId];
        if (version)
            args.push('--version', version);
        return await this.runCLI(args);
    }
    async listAgents(filters = {}, _telemetry) {
        const args = ['agent-registry', 'list'];
        if (filters.tag)
            args.push('--tag', filters.tag);
        if (filters.status)
            args.push('--status', filters.status);
        if (filters.limit)
            args.push('--limit', String(filters.limit));
        const result = await this.runCLI(args);
        return result.agents || [];
    }
    async searchAgents(query, options = {}, _telemetry) {
        const args = ['agent-registry', 'search', '--query', query];
        if (options.limit)
            args.push('--limit', String(options.limit));
        const result = await this.runCLI(args);
        return result.results || [];
    }
    async publishAgent(agentId) {
        await this.runCLI(['agent-registry', 'publish', '--agent-id', agentId]);
    }
    async deprecateAgent(agentId, reason) {
        await this.runCLI(['agent-registry', 'deprecate', '--agent-id', agentId, '--reason', reason]);
    }
    async updateAgent(agentId, updates) {
        // Note: CLI update logic might vary; usually takes specific flags
        // Here assuming we pass simple flags or JSON
        const args = ['agent-registry', 'update', '--agent-id', agentId];
        if (updates.name)
            args.push('--name', updates.name);
        if (updates.description)
            args.push('--description', updates.description);
        if (updates.tags)
            args.push('--tags', updates.tags.join(','));
        // ... handled simplified for now
        return await this.runCLI(args);
    }
    // ─────────────────────────────────────────────────────────────────────────────
    // Agent Performance
    // ─────────────────────────────────────────────────────────────────────────────
    async getTopPerformers(metric, limit = 10, periodDays = 30) {
        // Simulated mapped to analytics call
        const args = ['agent-performance', 'top-performers', '--metric', metric, '--limit', String(limit), '--days', String(periodDays)];
        const result = await this.runCLI(args);
        return result.performers || [];
    }
    async getAgentPerformanceAlerts(agentId, metric, activeOnly = true, limit = 20) {
        const args = ['agent-performance', 'alerts'];
        if (agentId)
            args.push('--agent-id', agentId);
        if (metric)
            args.push('--metric', metric);
        if (activeOnly)
            args.push('--active-only');
        args.push('--limit', String(limit));
        const result = await this.runCLI(args);
        return result.alerts || [];
    }
    async getAgentPerformanceSummary(agentId, days = 30) {
        const args = ['agent-performance', 'summary', '--days', String(days)];
        if (agentId)
            args.push('--agent-id', agentId);
        return await this.runCLI(args);
    }
    // ─────────────────────────────────────────────────────────────────────────────
    // Project Settings
    // ─────────────────────────────────────────────────────────────────────────────
    async getProjectSettings(projectId) {
        const args = ['projects', 'get', '--project-id', projectId];
        return await this.runCLI(args);
    }
    async updateProjectSettings(projectId, settings) {
        const args = ['projects', 'update', '--project-id', projectId];
        if (settings.name)
            args.push('--name', settings.name);
        if (settings.description)
            args.push('--description', settings.description);
        // ... simplified mapping
        return await this.runCLI(args);
    }
    async validateGithubRepo(projectId, url) {
        // Mock logic or call a specific CLI tool
        // Currently returning fake OK since no CLI command exists yet
        if (url.includes('github.com')) {
            return { valid: true, repo_name: url.split('/').pop()?.replace('.git', '') };
        }
        return { valid: false, error: 'Invalid GitHub URL' };
    }
    // ─────────────────────────────────────────────────────────────────────────────
    // BYOK Credentials
    // ─────────────────────────────────────────────────────────────────────────────
    /**
     * Get all BYOK credentials for a project (keys returned as prefix only)
     */
    async getProjectCredentials(projectId) {
        const response = await this.callAPI(`/api/v1/projects/${projectId}/credentials`, 'GET');
        return response.credentials || [];
    }
    /**
     * Add or replace a BYOK credential for a project
     */
    async addProjectCredential(projectId, provider, apiKey, name) {
        return await this.callAPI(`/api/v1/projects/${projectId}/credentials?actor_id=${encodeURIComponent(this.telemetryActorId)}`, 'POST', { provider, api_key: apiKey, name });
    }
    /**
     * Delete a BYOK credential from a project
     */
    async deleteProjectCredential(projectId, credentialId) {
        await this.callAPI(`/api/v1/projects/${projectId}/credentials/${credentialId}?actor_id=${encodeURIComponent(this.telemetryActorId)}`, 'DELETE');
    }
    /**
     * Re-enable a disabled credential with a new API key
     */
    async reEnableProjectCredential(projectId, credentialId, apiKey) {
        return await this.callAPI(`/api/v1/projects/${projectId}/credentials/${credentialId}:re-enable?actor_id=${encodeURIComponent(this.telemetryActorId)}`, 'POST', { api_key: apiKey });
    }
    /**
     * Get audit log for a specific credential
     */
    async getProjectCredentialAudit(projectId, credentialId, limit = 50) {
        const response = await this.callAPI(`/api/v1/projects/${projectId}/credentials/${credentialId}/audit?limit=${limit}`, 'GET');
        return response.audit_log || [];
    }
    /**
     * Get all BYOK credentials for an organization
     */
    async getOrgCredentials(orgId) {
        const response = await this.callAPI(`/api/v1/orgs/${orgId}/credentials`, 'GET');
        return response.credentials || [];
    }
    /**
     * Add or replace a BYOK credential for an organization
     */
    async addOrgCredential(orgId, provider, apiKey, name) {
        return await this.callAPI(`/api/v1/orgs/${orgId}/credentials`, 'POST', { provider, api_key: apiKey, name });
    }
    /**
     * Delete a BYOK credential from an organization
     */
    async deleteOrgCredential(orgId, credentialId) {
        await this.callAPI(`/api/v1/orgs/${orgId}/credentials/${credentialId}`, 'DELETE');
    }
    /**
     * Re-enable a disabled org credential with a new API key
     */
    async reEnableOrgCredential(orgId, credentialId, apiKey) {
        return await this.callAPI(`/api/v1/orgs/${orgId}/credentials/${credentialId}:re-enable`, 'POST', { api_key: apiKey });
    }
    /**
     * Get audit log for an org credential
     */
    async getOrgCredentialAudit(orgId, credentialId, limit = 50) {
        const response = await this.callAPI(`/api/v1/orgs/${orgId}/credentials/${credentialId}/audit?limit=${limit}`, 'GET');
        return response.audit_log || [];
    }
    // ─────────────────────────────────────────────────────────────────────────────
    // Per-User GitHub Credential Links
    // ─────────────────────────────────────────────────────────────────────────────
    /**
     * Get the current user's GitHub link for a project
     */
    async getMyGitHubLink(projectId) {
        try {
            const response = await this.callAPI(`/api/v1/projects/${projectId}/github/my-link`, 'GET');
            return response;
        }
        catch (error) {
            // 404 or null response means no link
            return null;
        }
    }
    /**
     * Link the current user's PAT credential to a project
     */
    async linkMyPATToProject(projectId, options) {
        return await this.callAPI(`/api/v1/projects/${projectId}/github/link-pat`, 'POST', options);
    }
    /**
     * Link the current user's GitHub App installation to a project
     */
    async linkMyAppToProject(projectId, options) {
        return await this.callAPI(`/api/v1/projects/${projectId}/github/link-app`, 'POST', options);
    }
    /**
     * Remove the current user's GitHub link from a project
     */
    async unlinkMyGitHubFromProject(projectId, linkType) {
        let url = `/api/v1/projects/${projectId}/github/my-link`;
        if (linkType) {
            url += `?link_type=${linkType}`;
        }
        return await this.callAPI(url, 'DELETE');
    }
    /**
     * Show which GitHub credential would be used for the current user + project
     */
    async getGitHubResolution(projectId) {
        return await this.callAPI(`/api/v1/projects/${projectId}/github/resolution`, 'GET');
    }
    /**
     * Get the current user's GitHub preferences
     */
    async getMyGitHubPreferences() {
        return await this.callAPI(`/api/v1/users/me/github-preferences`, 'GET');
    }
    /**
     * Update the current user's GitHub preferences
     */
    async updateMyGitHubPreferences(prefs) {
        return await this.callAPI(`/api/v1/users/me/github-preferences`, 'PUT', prefs);
    }
    /**
     * List GitHub credentials owned by the current user
     */
    async listMyGitHubCredentials() {
        return await this.callAPI(`/api/v1/users/me/github-credentials`, 'GET');
    }
    /**
     * List GitHub App installations accessible to the current user
     */
    async listMyGitHubAppInstallations() {
        return await this.callAPI(`/api/v1/users/me/github-app-installations`, 'GET');
    }
    // ─────────────────────────────────────────────────────────────────────────────
    // Cost Analytics (Customer-Facing)
    // ─────────────────────────────────────────────────────────────────────────────
    /**
     * Convert days to start/end date strings for CLI
     */
    daysToDateRange(days) {
        const endDate = new Date();
        const startDate = new Date();
        startDate.setDate(startDate.getDate() - days);
        const formatDate = (d) => d.toISOString().split('T')[0];
        return {
            startDate: formatDate(startDate),
            endDate: formatDate(endDate)
        };
    }
    /**
     * Get cost breakdown by service (LLM, storage, compute, etc.)
     */
    async getCostByService(days = 30) {
        const { startDate, endDate } = this.daysToDateRange(days);
        const args = ['analytics', 'cost-by-service', '--start-date', startDate, '--end-date', endDate];
        return await this.runCLI(args);
    }
    /**
     * Get cost per run statistics
     */
    async getCostPerRun(days = 30, limit = 100) {
        const { startDate, endDate } = this.daysToDateRange(days);
        const args = ['analytics', 'cost-per-run', '--start-date', startDate, '--end-date', endDate, '--limit', String(limit)];
        return await this.runCLI(args);
    }
    /**
     * Get ROI summary with token savings value
     */
    async getROISummary(days = 30) {
        const args = ['analytics', 'roi-summary'];
        return await this.runCLI(args);
    }
    /**
     * Get daily cost trend
     */
    async getDailyCosts(days = 30) {
        const { startDate, endDate } = this.daysToDateRange(days);
        const args = ['analytics', 'daily-costs', '--start-date', startDate, '--end-date', endDate, '--limit', String(days)];
        return await this.runCLI(args);
    }
    /**
     * Get top expensive workflows
     */
    async getTopExpensiveWorkflows(days = 30, limit = 10) {
        const args = ['analytics', 'top-expensive', '--limit', String(limit)];
        return await this.runCLI(args);
    }
    /**
     * Execute CLI command and return parsed JSON result
     */
    async runCLI(args, options = {}) {
        const parseJson = options.parseJson !== false;
        const finalArgs = parseJson ? this.withJsonFormat(args) : args;
        return new Promise((resolve, reject) => {
            this.outputChannel.appendLine(`Running: ${this.cliPath} ${finalArgs.join(' ')}`);
            const childProcess = (0, child_process_1.spawn)(this.cliPath, finalArgs, {
                shell: true,
                env: { ...process.env }
            });
            let stdout = '';
            let stderr = '';
            childProcess.stdout?.on('data', (data) => {
                stdout += data.toString();
            });
            childProcess.stderr?.on('data', (data) => {
                stderr += data.toString();
                this.outputChannel.appendLine(`stderr: ${data}`);
            });
            childProcess.on('close', (code) => {
                if (code !== 0) {
                    this.outputChannel.appendLine(`Command failed with code ${code}`);
                    this.outputChannel.appendLine(`stderr: ${stderr}`);
                    reject(new Error(`CLI command failed: ${stderr || `exit code ${code}`}`));
                    return;
                }
                if (!parseJson) {
                    resolve(stdout);
                    return;
                }
                try {
                    const result = JSON.parse(stdout);
                    resolve(result);
                }
                catch (error) {
                    this.outputChannel.appendLine(`Failed to parse JSON: ${stdout}`);
                    reject(new Error(`Failed to parse CLI output: ${error}`));
                }
            });
            childProcess.on('error', (error) => {
                this.outputChannel.appendLine(`Process error: ${error.message}`);
                reject(error);
            });
        });
    }
    sendTelemetry(eventType, payload, options = {}) {
        this.emitTelemetry(eventType, payload, options).catch((error) => {
            const message = error instanceof Error ? error.message : String(error);
            this.outputChannel.appendLine(`Telemetry error: ${message}`);
        });
    }
    async emitTelemetry(eventType, payload, options = {}) {
        if (!this.telemetryEnabled) {
            return;
        }
        const args = ['telemetry', 'emit', '--event-type', eventType, '--actor-id', this.telemetryActorId, '--actor-role', this.telemetryActorRole, '--actor-surface', this.telemetrySurface];
        const serializedPayload = JSON.stringify(payload ?? {});
        args.push('--payload', serializedPayload);
        if (options.runId) {
            args.push('--run-id', options.runId);
        }
        if (options.actionId) {
            args.push('--action-id', options.actionId);
        }
        const sessionId = options.sessionId ?? vscode.env.sessionId;
        if (sessionId) {
            args.push('--session-id', sessionId);
        }
        await this.runCLI(args);
    }
    withJsonFormat(args) {
        if (args.includes('--format')) {
            return args;
        }
        return [...args, '--format', 'json'];
    }
    async cleanupTempDir(tmpDir) {
        try {
            await fs_1.promises.rm(tmpDir, { recursive: true, force: true });
        }
        catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            this.outputChannel.appendLine(`Failed to cleanup temp directory ${tmpDir}: ${message}`);
        }
    }
    dispose() {
        this.outputChannel.dispose();
    }
}
exports.AmprealizeClient = AmprealizeClient;
//# sourceMappingURL=AmprealizeClient.js.map
