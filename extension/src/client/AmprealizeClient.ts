/**
 * Amprealize Client
 *
 * Communicates with the amprealize Python CLI to access:
 * - BehaviorService (via MCP tools)
 * - WorkflowService (via MCP tools)
 * - ComplianceService (via MCP tools)
 * - ActionService
 */

import * as vscode from 'vscode';
import { spawn, ChildProcess} from 'child_process';
import { promises as fs } from 'fs';
import * as os from 'os';
import * as path from 'path';

interface BehaviorTelemetryContext {
	source?: string;
	query?: string;
	roleFocus?: string;
}

interface WorkflowTelemetryContext {
	source?: string;
	roleFocus?: string;
}

interface TelemetryEmitOptions {
	runId?: string;
	actionId?: string;
	sessionId?: string;
}

export interface Behavior {
	behavior_id: string;
	name: string;
	description: string;
	tags: string[];
	status: string;
	versions?: BehaviorVersion[];
	// Current version fields (from active version)
	version?: string;
	instruction?: string;
	role_focus?: string;
	trigger_keywords?: string[];
	examples?: any[];
	metadata?: any;
}

export interface BehaviorVersion {
	version: string;
	status: string;
	instruction: string;
	role_focus: string;
	trigger_keywords: string[];
	examples: any[];
	metadata: any;
	created_by: string;
	effective_from?: string;
}

export interface WorkflowTemplate {
	template_id: string;
	name: string;
	description: string;
	role: string;
	role_focus?: string;  // Alias for role
	steps: WorkflowStep[];
}

export interface WorkflowStep {
	step_id: string;
	name: string;
	description: string;
	behavior_ids: string[];
}

export interface BCIBehaviorMatch {
	behavior_id: string;
	name: string;
	version: string;
	instruction: string;
	score: number;
	description?: string;
	role_focus?: string;
	tags?: string[];
	strategy_breakdown?: Record<string, number>;
	citation_label?: string;
	metadata?: Record<string, unknown> | null;
}

export type AgentStatus = 'DRAFT' | 'PUBLISHED' | 'DEPRECATED' | 'ARCHIVED' | 'draft' | 'active' | 'deprecated' | 'archived';
export type AgentVisibility = 'private' | 'public' | 'org';
export type RoleAlignment = 'STRATEGIST' | 'TEACHER' | 'STUDENT' | 'MULTI' | 'strict' | 'flexible';

export interface AgentVersion {
	version: string;
	status: AgentStatus;
	created_at?: string;
	performance_score?: number;
	change_log?: string;
	instruction?: string;
	tags?: string[];
	capabilities?: string[];
	behaviors?: string[];
	role_alignment?: RoleAlignment;
}

export interface Agent {
	agent_id: string;
	name: string;
	description: string;
	status: AgentStatus;
	version: string;
	capabilities: string[];
	behaviors: string[];
	tags: string[];
	mcp_servers: string[];
	visibility: AgentVisibility;
	role_alignment: RoleAlignment;
	versions: AgentVersion[];
	owner?: string;
	owner_id?: string;
	created_at?: string;
	updated_at?: string;
	model?: string;
	temperature?: number;
	max_tokens?: number;
	system_prompt?: string;
}

export interface AgentSearchResult {
	agent: Agent;
	score: number;
	match_reason?: string;
}

export interface TopPerformer {
	agentId: string;
	agentName: string;
	metricValue: number;
	metricName: string;
	changePercent: number;
	rank?: number;
	totalTasks?: number;
	periodDays?: number;
}

export interface PerformanceAlert {
	id: string;
	alertId?: string;
	agentId: string;
	agentName: string;
	metric: string;
	threshold: number;
	thresholdValue?: number;
	value: number;
	actualValue?: number;
	timestamp: string;
	createdAt?: string;
	status: 'active' | 'acknowledged' | 'resolved';
	severity: 'low' | 'medium' | 'high' | 'critical';
	message?: string;
	acknowledgedAt?: string;
	resolvedAt?: string;
}

export interface AgentPerformanceSummary {
	totalSavings: number;
	avgLatency: number;
	successRate: number;
	activeAgents: number;
	totalRuns?: number;
	errorCount?: number;
}

export interface ProjectSettings {
	id?: string;
	name: string;
	description?: string;
	github_repo?: string;
	default_branch?: string;
	compliance_tier?: string;
	cost_budget?: number;
	allowed_mcp_servers?: string[];
	members?: any[];
	created_at?: string;
	updated_at?: string;
}

export interface GithubValidationResult {
	valid: boolean;
	repo_name?: string;
	error?: string;
	permissions?: string[];
}

export interface LLMCredential {
	credential_id: string;
	provider: string;
	name: string;
	key_prefix: string;  // First/last 4 chars only, for display
	is_valid: boolean;
	failure_count: number;
	last_used_at?: string;
	created_at: string;
	updated_at: string;
}

export interface CredentialAuditEntry {
	audit_id: string;
	credential_id: string;
	action: string;  // 'created' | 'rotated' | 'disabled' | 'enabled' | 'deleted' | 'used'
	actor_id: string;
	details?: Record<string, unknown>;
	created_at: string;
}

// Per-User GitHub Credential Link interfaces
export interface GitHubLink {
	id: string;
	link_type: 'pat' | 'app';
	github_credential_id?: string;
	installation_link_id?: string;
	priority: number;
	credential_name?: string;
	github_identity?: string;
	created_at?: string;
	last_used_at?: string;
}

export interface GitHubResolution {
	has_credential: boolean;
	source?: string;
	credential_id?: string;
	installation_id?: number;
	github_username?: string;
	token_type?: string;
	has_required_scopes?: boolean;
	scope_warning?: string;
	resolved_for_user_id?: string;
	link_id?: string;
	message?: string;
	resolution_order?: string[];
}

export interface GitHubPreferences {
	default_pat_credential_id?: string;
	default_app_installation_id?: number;
	auto_link_new_projects: boolean;
	prefer_app_over_pat: boolean;
	created_at?: string;
	updated_at?: string;
}

export interface GitHubCredential {
	id: string;
	scope_type: string;
	scope_id: string;
	token_type: string;
	name: string;
	token_prefix: string;
	is_valid: boolean;
	failure_count: number;
	scopes?: string[];
	github_username?: string;
	created_at?: string;
	last_used_at?: string;
}

export interface GitHubAppInstallation {
	installation_id: number;
	account_type: string;
	account_login: string;
	account_id: number;
	permissions?: Record<string, string>;
	is_active: boolean;
}

export interface BCIRetrieveOptions {
	query: string;
	topK?: number;
	strategy?: 'embedding' | 'keyword' | 'hybrid';
	roleFocus?: string;
	tags?: string[];
	includeMetadata?: boolean;
	embeddingWeight?: number;
	keywordWeight?: number;
}

export interface BCIRetrieveResponse {
	query: string;
	results: BCIBehaviorMatch[];
	strategy_used: string;
	latency_ms?: number;
	metadata?: Record<string, unknown> | null;
}

export interface BCIPrependedBehavior {
	behavior_name: string;
	behavior_id?: string;
	version?: string;
}

export interface BCICitation {
	text: string;
	type: string;
	start_index: number;
	end_index: number;
	behavior_name?: string;
	behavior_id?: string;
	confidence?: number;
}

export interface BCIValidateRequest {
	outputText: string;
	prepended: BCIPrependedBehavior[];
	minimumCitations?: number;
	allowUnlisted?: boolean;
}

export interface BCIValidateResponse {
	total_citations: number;
	valid_citations: BCICitation[];
	invalid_citations: BCICitation[];
	compliance_rate: number;
	is_compliant: boolean;
	missing_behaviors: string[];
	warnings: string[];
}

// Cost Analytics interfaces (Customer-Facing)
export interface CostByServiceRow {
	service: string;
	total_cost_usd: number;
	total_runs: number;
	avg_cost_per_run: number;
	pct_of_total: number;
}

export interface CostByServiceResponse {
	period_days: number;
	rows: CostByServiceRow[];
	total_cost_usd: number;
}

export interface CostPerRunRow {
	run_id: string;
	workflow_name: string;
	cost_usd: number;
	tokens_generated: number;
	created_at: string;
	status: string;
}

export interface CostPerRunResponse {
	period_days: number;
	rows: CostPerRunRow[];
	avg_cost_per_run: number;
	total_runs: number;
}

export interface ROISummaryResponse {
	period_days: number;
	total_cost_usd: number;
	total_tokens_saved: number;
	token_savings_value_usd: number;
	net_cost_usd: number;
	roi_ratio: number;
	runs_analyzed: number;
}

export interface DailyCostRow {
	date: string;
	cost_usd: number;
	runs: number;
	tokens: number;
}

export interface DailyCostResponse {
	period_days: number;
	rows: DailyCostRow[];
	avg_daily_cost: number;
	max_daily_cost: number;
}

export interface TopExpensiveRow {
	workflow_id: string;
	workflow_name: string;
	total_cost_usd: number;
	run_count: number;
	avg_cost_per_run: number;
}

export interface TopExpensiveResponse {
	period_days: number;
	rows: TopExpensiveRow[];
}

// Run-related interfaces
export interface Run {
	run_id: string;
	status: string;
	progress_pct: number;
	actor: {
		id: string;
		role: string;
		surface: string;
	};
	workflow_id?: string;
	workflow_name?: string;
	template_id?: string;
	template_name?: string;
	behavior_ids: string[];
	initial_message?: string;
	total_steps?: number;
	created_at: string;
	updated_at: string;
	completed_at?: string;
	metadata: Record<string, any>;
	step_current?: {
		step_id: string;
		name: string;
		status: string;
	};
	step_progress?: {
		current: number;
		total: number;
	};
	tokens_generated?: number;
	tokens_baseline?: number;
	error?: string;
	outputs?: Record<string, any>;
}

// Compliance-related interfaces
export interface ComplianceChecklist {
	checklist_id: string;
	title: string;
	description: string;
	template_id?: string;
	milestone?: string;
	compliance_category: string[];
	actor: {
		id: string;
		role: string;
		surface: string;
	};
	created_at: string;
	updated_at: string;
	status: 'DRAFT' | 'IN_PROGRESS' | 'COMPLETED' | 'APPROVED' | 'REJECTED';
	progress: {
		total_steps: number;
		completed_steps: number;
		coverage_score: number;
	};
	steps: ComplianceStep[];
}

export interface ComplianceStep {
	step_id: string;
	checklist_id: string;
	title: string;
	status: 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'BLOCKED' | 'SKIPPED';
	actor: {
		id: string;
		role: string;
		surface: string;
	};
	created_at: string;
	updated_at: string;
	completed_at?: string;
	evidence: Record<string, any>;
	behaviors_cited: string[];
	related_run_id?: string;
	comments: ComplianceComment[];
}

export interface ComplianceComment {
	comment_id: string;
	step_id: string;
	actor: {
		id: string;
		role: string;
		surface: string;
	};
	content: string;
	created_at: string;
}

export class AmprealizeClient {
	private pythonPath: string;
	private cliPath: string;
	private apiBaseUrl: string;
	private outputChannel: vscode.OutputChannel;
	private telemetryEnabled: boolean;
	private telemetryActorId: string;
	private telemetryActorRole: string;
	private readonly telemetrySurface = 'MCP';  // IDE-agnostic: works across VS Code, Cursor, Claude Desktop

	constructor(private context: vscode.ExtensionContext) {
		const config = vscode.workspace.getConfiguration('amprealize');
		this.pythonPath = config.get('pythonPath', 'python');
		this.cliPath = config.get('cliPath', 'amprealize');
		this.apiBaseUrl = config.get('apiBaseUrl', 'http://localhost:8080');
		this.outputChannel = vscode.window.createOutputChannel('Amprealize');
		this.telemetryEnabled = config.get('telemetryEnabled', true);
		this.telemetryActorId = config.get('telemetryActorId', 'ide-user');  // IDE-agnostic default
		this.telemetryActorRole = config.get('telemetryActorRole', 'STUDENT');
	}

	/**
	 * Make an HTTP API call to the amprealize backend
	 */
	private async callAPI<T>(
		endpoint: string,
		method: 'GET' | 'POST' | 'DELETE' | 'PUT' | 'PATCH' = 'GET',
		body?: Record<string, unknown>
	): Promise<T> {
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
			const req = httpModule.request(options, (res: any) => {
				let data = '';

				res.on('data', (chunk: string | Buffer) => {
					data += chunk.toString();
				});

				res.on('end', () => {
					if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) {
						try {
							resolve(JSON.parse(data) as T);
						} catch {
							reject(new Error(`Failed to parse response: ${data}`));
						}
					} else {
						this.outputChannel.appendLine(`API error ${res.statusCode}: ${data}`);
						reject(new Error(`API error ${res.statusCode}: ${data}`));
					}
				});
			});

			req.on('error', (error: Error) => {
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
	async listBehaviors(
		filters?: { status?: string; tags?: string[]; role_focus?: string },
		telemetryContext: BehaviorTelemetryContext = {}
	): Promise<Behavior[]> {
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
		const behaviors: Behavior[] = result.map((item: any) => ({
			...item.behavior,
			versions: item.active_version ? [item.active_version] : []
		})) as Behavior[];

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
	async searchBehaviors(
		query: string,
		filters?: { role_focus?: string; tags?: string[] },
		telemetryContext: BehaviorTelemetryContext = {}
	): Promise<Behavior[]> {
		const args = ['behaviors', 'search', '--query', query];
		if (filters?.role_focus) {
			args.push('--role-focus', filters.role_focus);
		}
		if (filters?.tags && filters.tags.length > 0) {
			args.push('--tags', ...filters.tags);
		}

		const startedAt = Date.now();
		const result = await this.runCLI(args);
		const behaviors: Behavior[] = result.map((item: any) => {
			const behavior: Behavior = {
				...item.behavior,
				versions: item.active_version ? [item.active_version] : [],
			};
			const metadata = behavior.metadata ? { ...behavior.metadata } : {};
			behavior.metadata = { ...metadata, relevance_score: item.score };
			return behavior;
		}) as Behavior[];

		const latencyMs = Date.now() - startedAt;
		this.sendTelemetry('behavior_retrieved', {
			source: telemetryContext.source ?? 'sidebar.search',
			query,
			role_focus: telemetryContext.roleFocus ?? filters?.role_focus,
			result_count: behaviors.length,
			latency_ms: latencyMs,
			behavior_ids: behaviors.map((behavior: Behavior) => behavior.behavior_id),
		});

		return behaviors;
	}

	/**
	 * Get behavior details by ID
	 */
	async getBehavior(behaviorId: string, version?: string): Promise<{ behavior: Behavior; versions: BehaviorVersion[] }> {
		const args = ['behaviors', 'get', behaviorId];
		if (version) {
			args.push('--version', version);
		}

		return await this.runCLI(args);
	}

	/**
	 * List workflow templates
	 */
	async listWorkflowTemplates(role?: string, telemetryContext: WorkflowTelemetryContext = {}): Promise<WorkflowTemplate[]> {
		const args = ['workflow', 'list-templates'];
		if (role) {
			args.push('--role', role);
		}

		const startedAt = Date.now();
		const templates: WorkflowTemplate[] = await this.runCLI(args);
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
	async getWorkflowTemplate(templateId: string): Promise<WorkflowTemplate> {
		const args = ['workflow', 'get-template', templateId];
		return await this.runCLI(args);
	}

	/**
	 * Run a workflow from template
	 */
	async runWorkflow(templateId: string, context?: any, telemetryContext: WorkflowTelemetryContext = {}): Promise<{ run_id: string }> {
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
	async getWorkflowStatus(runId: string): Promise<any> {
		const args = ['workflow', 'status', runId];
		return await this.runCLI(args);
	}

	// ========================================
	// RunService Methods (Epic 5.4)
	// ========================================

	/**
	 * List all workflow runs with optional filters
	 */
	async listRuns(filters?: { status?: string; workflow_id?: string; template_id?: string; limit?: number }): Promise<Run[]> {
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
		const runs: Run[] = await this.runCLI(args);
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
	async getRun(runId: string): Promise<Run> {
		const args = ['runs', 'get', runId];
		return await this.runCLI(args);
	}

	/**
	 * Update run progress and status
	 */
	async updateRun(runId: string, update: {
		status?: string;
		progress_pct?: number;
		message?: string;
		step_id?: string;
		step_name?: string;
		step_status?: string;
		tokens_generated?: number;
		tokens_baseline?: number;
		metadata?: Record<string, any>;
	}): Promise<Run> {
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
	async listComplianceChecklists(filters?: {
		milestone?: string;
		compliance_category?: string[];
		status_filter?: string;
	}): Promise<ComplianceChecklist[]> {
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
		const checklists: ComplianceChecklist[] = await this.runCLI(args);
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
	async getComplianceChecklist(checklistId: string): Promise<ComplianceChecklist> {
		const args = ['compliance', 'get-checklist', checklistId];
		return await this.runCLI(args);
	}

	/**
	 * Create a new compliance checklist
	 */
	async createComplianceChecklist(checklist: {
		title: string;
		description: string;
		template_id?: string;
		milestone?: string;
		compliance_category: string[];
		actor: { id: string; role: string; surface: string };
	}): Promise<ComplianceChecklist> {
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
	async recordComplianceStep(step: {
		checklist_id: string;
		title: string;
		status: string;
		evidence?: Record<string, any>;
		behaviors_cited?: string[];
		related_run_id?: string;
		actor: { id: string; role: string; surface: string };
	}): Promise<ComplianceStep> {
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
	async validateComplianceChecklist(checklistId: string, actor: { id: string; role: string; surface: string }): Promise<any> {
		const args = ['compliance', 'validate-checklist', checklistId];
		return await this.runCLI(args);
	}

	async bciRetrieve(options: BCIRetrieveOptions): Promise<BCIRetrieveResponse> {
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
		return response as BCIRetrieveResponse;
	}

	async bciValidateCitations(request: BCIValidateRequest): Promise<BCIValidateResponse> {
		const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'amprealize-bci-'));
		const outputPath = path.join(tmpDir, 'output.txt');
		const prependedPath = path.join(tmpDir, 'prepended.json');
		try {
			await fs.writeFile(outputPath, request.outputText, 'utf8');
			await fs.writeFile(prependedPath, JSON.stringify(request.prepended, null, 2), 'utf8');

			const args = ['bci', 'validate-citations', '--output-file', outputPath, '--prepended-file', prependedPath];
			if (request.minimumCitations !== undefined) {
				args.push('--minimum', String(request.minimumCitations));
			}
			if (request.allowUnlisted) {
				args.push('--allow-unlisted');
			}

			const response = await this.runCLI(args);
			return response as BCIValidateResponse;
		} finally {
			await this.cleanupTempDir(tmpDir);
		}
	}

	// ─────────────────────────────────────────────────────────────────────────────
	// Agent Registry & Management
	// ─────────────────────────────────────────────────────────────────────────────

	async getAgent(agentId: string, version?: string): Promise<Agent> {
		const args = ['agent-registry', 'get', '--agent-id', agentId];
		if (version) args.push('--version', version);
		return await this.runCLI(args);
	}

	async listAgents(
		filters: { tag?: string; status?: AgentStatus; visibility?: string; limit?: number } = {},
		_telemetry?: { source?: string }
	): Promise<Agent[]> {
		const args = ['agent-registry', 'list'];
		if (filters.tag) args.push('--tag', filters.tag);
		if (filters.status) args.push('--status', filters.status);
		if (filters.limit) args.push('--limit', String(filters.limit));

		const result = await this.runCLI(args);
		return result.agents || [];
	}

	async searchAgents(
		query: string,
		options: { limit?: number; minScore?: number; status?: AgentStatus; visibility?: string } = {},
		_telemetry?: { source?: string; query?: string }
	): Promise<AgentSearchResult[]> {
		const args = ['agent-registry', 'search', '--query', query];
		if (options.limit) args.push('--limit', String(options.limit));

		const result = await this.runCLI(args);
		return result.results || [];
	}

	async publishAgent(agentId: string): Promise<void> {
		await this.runCLI(['agent-registry', 'publish', '--agent-id', agentId]);
	}

	async deprecateAgent(agentId: string, reason: string): Promise<void> {
		await this.runCLI(['agent-registry', 'deprecate', '--agent-id', agentId, '--reason', reason]);
	}

	async updateAgent(agentId: string, updates: Partial<Agent>): Promise<Agent> {
		// Note: CLI update logic might vary; usually takes specific flags
		// Here assuming we pass simple flags or JSON
		const args = ['agent-registry', 'update', '--agent-id', agentId];
		if (updates.name) args.push('--name', updates.name);
		if (updates.description) args.push('--description', updates.description);
		if (updates.tags) args.push('--tags', updates.tags.join(','));
		// ... handled simplified for now
		return await this.runCLI(args);
	}

	// ─────────────────────────────────────────────────────────────────────────────
	// Agent Performance
	// ─────────────────────────────────────────────────────────────────────────────

	async getTopPerformers(metric: string, limit: number = 10, periodDays: number = 30): Promise<TopPerformer[]> {
		// Simulated mapped to analytics call
		const args = ['agent-performance', 'top-performers', '--metric', metric, '--limit', String(limit), '--days', String(periodDays)];
		const result = await this.runCLI(args);
		return result.performers || [];
	}

	async getAgentPerformanceAlerts(agentId?: string, metric?: string, activeOnly: boolean = true, limit: number = 20): Promise<PerformanceAlert[]> {
		const args = ['agent-performance', 'alerts'];
		if (agentId) args.push('--agent-id', agentId);
		if (metric) args.push('--metric', metric);
		if (activeOnly) args.push('--active-only');
		args.push('--limit', String(limit));

		const result = await this.runCLI(args);
		return result.alerts || [];
	}

	async getAgentPerformanceSummary(agentId?: string, days: number = 30): Promise<AgentPerformanceSummary> {
		const args = ['agent-performance', 'summary', '--days', String(days)];
		if (agentId) args.push('--agent-id', agentId);
		return await this.runCLI(args);
	}

	// ─────────────────────────────────────────────────────────────────────────────
	// Project Settings
	// ─────────────────────────────────────────────────────────────────────────────

	async getProjectSettings(projectId: string): Promise<ProjectSettings> {
		const args = ['projects', 'get', '--project-id', projectId];
		return await this.runCLI(args);
	}

	async updateProjectSettings(projectId: string, settings: Partial<ProjectSettings>): Promise<ProjectSettings> {
		const args = ['projects', 'update', '--project-id', projectId];
		if (settings.name) args.push('--name', settings.name);
		if (settings.description) args.push('--description', settings.description);
		// ... simplified mapping
		return await this.runCLI(args);
	}

	async validateGithubRepo(projectId: string, url: string): Promise<GithubValidationResult> {
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
	async getProjectCredentials(projectId: string): Promise<LLMCredential[]> {
		const response = await this.callAPI<{ credentials: LLMCredential[] }>(
			`/api/v1/projects/${projectId}/credentials`,
			'GET'
		);
		return response.credentials || [];
	}

	/**
	 * Add or replace a BYOK credential for a project
	 */
	async addProjectCredential(
		projectId: string,
		provider: string,
		apiKey: string,
		name?: string
	): Promise<LLMCredential> {
		return await this.callAPI<LLMCredential>(
			`/api/v1/projects/${projectId}/credentials?actor_id=${encodeURIComponent(this.telemetryActorId)}`,
			'POST',
			{ provider, api_key: apiKey, name }
		);
	}

	/**
	 * Delete a BYOK credential from a project
	 */
	async deleteProjectCredential(projectId: string, credentialId: string): Promise<void> {
		await this.callAPI<{ success: boolean }>(
			`/api/v1/projects/${projectId}/credentials/${credentialId}?actor_id=${encodeURIComponent(this.telemetryActorId)}`,
			'DELETE'
		);
	}

	/**
	 * Re-enable a disabled credential with a new API key
	 */
	async reEnableProjectCredential(
		projectId: string,
		credentialId: string,
		apiKey: string
	): Promise<LLMCredential> {
		return await this.callAPI<LLMCredential>(
			`/api/v1/projects/${projectId}/credentials/${credentialId}:re-enable?actor_id=${encodeURIComponent(this.telemetryActorId)}`,
			'POST',
			{ api_key: apiKey }
		);
	}

	/**
	 * Get audit log for a specific credential
	 */
	async getProjectCredentialAudit(
		projectId: string,
		credentialId: string,
		limit: number = 50
	): Promise<CredentialAuditEntry[]> {
		const response = await this.callAPI<{ audit_log: CredentialAuditEntry[] }>(
			`/api/v1/projects/${projectId}/credentials/${credentialId}/audit?limit=${limit}`,
			'GET'
		);
		return response.audit_log || [];
	}

	/**
	 * Get all BYOK credentials for an organization
	 */
	async getOrgCredentials(orgId: string): Promise<LLMCredential[]> {
		const response = await this.callAPI<{ credentials: LLMCredential[] }>(
			`/api/v1/orgs/${orgId}/credentials`,
			'GET'
		);
		return response.credentials || [];
	}

	/**
	 * Add or replace a BYOK credential for an organization
	 */
	async addOrgCredential(
		orgId: string,
		provider: string,
		apiKey: string,
		name?: string
	): Promise<LLMCredential> {
		return await this.callAPI<LLMCredential>(
			`/api/v1/orgs/${orgId}/credentials`,
			'POST',
			{ provider, api_key: apiKey, name }
		);
	}

	/**
	 * Delete a BYOK credential from an organization
	 */
	async deleteOrgCredential(orgId: string, credentialId: string): Promise<void> {
		await this.callAPI<{ success: boolean }>(
			`/api/v1/orgs/${orgId}/credentials/${credentialId}`,
			'DELETE'
		);
	}

	/**
	 * Re-enable a disabled org credential with a new API key
	 */
	async reEnableOrgCredential(
		orgId: string,
		credentialId: string,
		apiKey: string
	): Promise<LLMCredential> {
		return await this.callAPI<LLMCredential>(
			`/api/v1/orgs/${orgId}/credentials/${credentialId}:re-enable`,
			'POST',
			{ api_key: apiKey }
		);
	}

	/**
	 * Get audit log for an org credential
	 */
	async getOrgCredentialAudit(
		orgId: string,
		credentialId: string,
		limit: number = 50
	): Promise<CredentialAuditEntry[]> {
		const response = await this.callAPI<{ audit_log: CredentialAuditEntry[] }>(
			`/api/v1/orgs/${orgId}/credentials/${credentialId}/audit?limit=${limit}`,
			'GET'
		);
		return response.audit_log || [];
	}

	// ─────────────────────────────────────────────────────────────────────────────
	// Per-User GitHub Credential Links
	// ─────────────────────────────────────────────────────────────────────────────

	/**
	 * Get the current user's GitHub link for a project
	 */
	async getMyGitHubLink(projectId: string): Promise<GitHubLink | null> {
		try {
			const response = await this.callAPI<GitHubLink | null>(
				`/api/v1/projects/${projectId}/github/my-link`,
				'GET'
			);
			return response;
		} catch (error) {
			// 404 or null response means no link
			return null;
		}
	}

	/**
	 * Link the current user's PAT credential to a project
	 */
	async linkMyPATToProject(
		projectId: string,
		options: { github_credential_id?: string; token?: string; name?: string }
	): Promise<GitHubLink> {
		return await this.callAPI<GitHubLink>(
			`/api/v1/projects/${projectId}/github/link-pat`,
			'POST',
			options
		);
	}

	/**
	 * Link the current user's GitHub App installation to a project
	 */
	async linkMyAppToProject(
		projectId: string,
		options: { installation_link_id?: string; installation_id?: number }
	): Promise<GitHubLink> {
		return await this.callAPI<GitHubLink>(
			`/api/v1/projects/${projectId}/github/link-app`,
			'POST',
			options
		);
	}

	/**
	 * Remove the current user's GitHub link from a project
	 */
	async unlinkMyGitHubFromProject(
		projectId: string,
		linkType?: 'pat' | 'app'
	): Promise<{ unlinked: boolean; deleted_count: number }> {
		let url = `/api/v1/projects/${projectId}/github/my-link`;
		if (linkType) {
			url += `?link_type=${linkType}`;
		}
		return await this.callAPI<{ unlinked: boolean; deleted_count: number }>(url, 'DELETE');
	}

	/**
	 * Show which GitHub credential would be used for the current user + project
	 */
	async getGitHubResolution(projectId: string): Promise<GitHubResolution> {
		return await this.callAPI<GitHubResolution>(
			`/api/v1/projects/${projectId}/github/resolution`,
			'GET'
		);
	}

	/**
	 * Get the current user's GitHub preferences
	 */
	async getMyGitHubPreferences(): Promise<GitHubPreferences> {
		return await this.callAPI<GitHubPreferences>(
			`/api/v1/users/me/github-preferences`,
			'GET'
		);
	}

	/**
	 * Update the current user's GitHub preferences
	 */
	async updateMyGitHubPreferences(prefs: Partial<GitHubPreferences>): Promise<GitHubPreferences> {
		return await this.callAPI<GitHubPreferences>(
			`/api/v1/users/me/github-preferences`,
			'PUT',
			prefs
		);
	}

	/**
	 * List GitHub credentials owned by the current user
	 */
	async listMyGitHubCredentials(): Promise<GitHubCredential[]> {
		return await this.callAPI<GitHubCredential[]>(
			`/api/v1/users/me/github-credentials`,
			'GET'
		);
	}

	/**
	 * List GitHub App installations accessible to the current user
	 */
	async listMyGitHubAppInstallations(): Promise<GitHubAppInstallation[]> {
		return await this.callAPI<GitHubAppInstallation[]>(
			`/api/v1/users/me/github-app-installations`,
			'GET'
		);
	}

	// ─────────────────────────────────────────────────────────────────────────────
	// Cost Analytics (Customer-Facing)
	// ─────────────────────────────────────────────────────────────────────────────

	/**
	 * Convert days to start/end date strings for CLI
	 */
	private daysToDateRange(days: number): { startDate: string; endDate: string } {
		const endDate = new Date();
		const startDate = new Date();
		startDate.setDate(startDate.getDate() - days);

		const formatDate = (d: Date) => d.toISOString().split('T')[0];
		return {
			startDate: formatDate(startDate),
			endDate: formatDate(endDate)
		};
	}

	/**
	 * Get cost breakdown by service (LLM, storage, compute, etc.)
	 */
	async getCostByService(days: number = 30): Promise<CostByServiceResponse> {
		const { startDate, endDate } = this.daysToDateRange(days);
		const args = ['analytics', 'cost-by-service', '--start-date', startDate, '--end-date', endDate];
		return await this.runCLI(args);
	}

	/**
	 * Get cost per run statistics
	 */
	async getCostPerRun(days: number = 30, limit: number = 100): Promise<CostPerRunResponse> {
		const { startDate, endDate } = this.daysToDateRange(days);
		const args = ['analytics', 'cost-per-run', '--start-date', startDate, '--end-date', endDate, '--limit', String(limit)];
		return await this.runCLI(args);
	}

	/**
	 * Get ROI summary with token savings value
	 */
	async getROISummary(days: number = 30): Promise<ROISummaryResponse> {
		const args = ['analytics', 'roi-summary'];
		return await this.runCLI(args);
	}

	/**
	 * Get daily cost trend
	 */
	async getDailyCosts(days: number = 30): Promise<DailyCostResponse> {
		const { startDate, endDate } = this.daysToDateRange(days);
		const args = ['analytics', 'daily-costs', '--start-date', startDate, '--end-date', endDate, '--limit', String(days)];
		return await this.runCLI(args);
	}

	/**
	 * Get top expensive workflows
	 */
	async getTopExpensiveWorkflows(days: number = 30, limit: number = 10): Promise<TopExpensiveResponse> {
		const args = ['analytics', 'top-expensive', '--limit', String(limit)];
		return await this.runCLI(args);
	}

	/**
	 * Execute CLI command and return parsed JSON result
	 */
	async runCLI(args: string[], options: { parseJson?: boolean } = {}): Promise<any> {
		const parseJson = options.parseJson !== false;
		const finalArgs = parseJson ? this.withJsonFormat(args) : args;

		return new Promise((resolve, reject) => {
			this.outputChannel.appendLine(`Running: ${this.cliPath} ${finalArgs.join(' ')}`);

			const childProcess: ChildProcess = spawn(this.cliPath, finalArgs, {
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
				} catch (error) {
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

	private sendTelemetry(eventType: string, payload: Record<string, unknown>, options: TelemetryEmitOptions = {}): void {
		this.emitTelemetry(eventType, payload, options).catch((error) => {
			const message = error instanceof Error ? error.message : String(error);
			this.outputChannel.appendLine(`Telemetry error: ${message}`);
		});
	}

	async emitTelemetry(eventType: string, payload: Record<string, unknown>, options: TelemetryEmitOptions = {}): Promise<void> {
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

	private withJsonFormat(args: string[]): string[] {
		if (args.includes('--format')) {
			return args;
		}
		return [...args, '--format', 'json'];
	}

	private async cleanupTempDir(tmpDir: string): Promise<void> {
		try {
			await fs.rm(tmpDir, { recursive: true, force: true });
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			this.outputChannel.appendLine(`Failed to cleanup temp directory ${tmpDir}: ${message}`);
		}
	}

	dispose() {
		this.outputChannel.dispose();
	}
}
