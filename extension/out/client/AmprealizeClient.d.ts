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
    role_focus?: string;
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
    key_prefix: string;
    is_valid: boolean;
    failure_count: number;
    last_used_at?: string;
    created_at: string;
    updated_at: string;
}
export interface CredentialAuditEntry {
    audit_id: string;
    credential_id: string;
    action: string;
    actor_id: string;
    details?: Record<string, unknown>;
    created_at: string;
}
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
export declare class AmprealizeClient {
    private context;
    private pythonPath;
    private cliPath;
    private apiBaseUrl;
    private outputChannel;
    private telemetryEnabled;
    private telemetryActorId;
    private telemetryActorRole;
    private readonly telemetrySurface;
    constructor(context: vscode.ExtensionContext);
    /**
     * Make an HTTP API call to the amprealize backend
     */
    private callAPI;
    /**
     * List all behaviors with optional filters
     */
    listBehaviors(filters?: {
        status?: string;
        tags?: string[];
        role_focus?: string;
    }, telemetryContext?: BehaviorTelemetryContext): Promise<Behavior[]>;
    /**
     * Search behaviors with semantic query
     */
    searchBehaviors(query: string, filters?: {
        role_focus?: string;
        tags?: string[];
    }, telemetryContext?: BehaviorTelemetryContext): Promise<Behavior[]>;
    /**
     * Get behavior details by ID
     */
    getBehavior(behaviorId: string, version?: string): Promise<{
        behavior: Behavior;
        versions: BehaviorVersion[];
    }>;
    /**
     * List workflow templates
     */
    listWorkflowTemplates(role?: string, telemetryContext?: WorkflowTelemetryContext): Promise<WorkflowTemplate[]>;
    /**
     * Get workflow template details
     */
    getWorkflowTemplate(templateId: string): Promise<WorkflowTemplate>;
    /**
     * Run a workflow from template
     */
    runWorkflow(templateId: string, context?: any, telemetryContext?: WorkflowTelemetryContext): Promise<{
        run_id: string;
    }>;
    /**
     * Get workflow run status
     */
    getWorkflowStatus(runId: string): Promise<any>;
    /**
     * List all workflow runs with optional filters
     */
    listRuns(filters?: {
        status?: string;
        workflow_id?: string;
        template_id?: string;
        limit?: number;
    }): Promise<Run[]>;
    /**
     * Get detailed information about a specific run
     */
    getRun(runId: string): Promise<Run>;
    /**
     * Update run progress and status
     */
    updateRun(runId: string, update: {
        status?: string;
        progress_pct?: number;
        message?: string;
        step_id?: string;
        step_name?: string;
        step_status?: string;
        tokens_generated?: number;
        tokens_baseline?: number;
        metadata?: Record<string, any>;
    }): Promise<Run>;
    /**
     * List compliance checklists with optional filters
     */
    listComplianceChecklists(filters?: {
        milestone?: string;
        compliance_category?: string[];
        status_filter?: string;
    }): Promise<ComplianceChecklist[]>;
    /**
     * Get detailed information about a specific compliance checklist
     */
    getComplianceChecklist(checklistId: string): Promise<ComplianceChecklist>;
    /**
     * Create a new compliance checklist
     */
    createComplianceChecklist(checklist: {
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
    }): Promise<ComplianceChecklist>;
    /**
     * Record a step in a compliance checklist
     */
    recordComplianceStep(step: {
        checklist_id: string;
        title: string;
        status: string;
        evidence?: Record<string, any>;
        behaviors_cited?: string[];
        related_run_id?: string;
        actor: {
            id: string;
            role: string;
            surface: string;
        };
    }): Promise<ComplianceStep>;
    /**
     * Validate a compliance checklist
     */
    validateComplianceChecklist(checklistId: string, actor: {
        id: string;
        role: string;
        surface: string;
    }): Promise<any>;
    bciRetrieve(options: BCIRetrieveOptions): Promise<BCIRetrieveResponse>;
    bciValidateCitations(request: BCIValidateRequest): Promise<BCIValidateResponse>;
    getAgent(agentId: string, version?: string): Promise<Agent>;
    listAgents(filters?: {
        tag?: string;
        status?: AgentStatus;
        visibility?: string;
        limit?: number;
    }, _telemetry?: {
        source?: string;
    }): Promise<Agent[]>;
    searchAgents(query: string, options?: {
        limit?: number;
        minScore?: number;
        status?: AgentStatus;
        visibility?: string;
    }, _telemetry?: {
        source?: string;
        query?: string;
    }): Promise<AgentSearchResult[]>;
    publishAgent(agentId: string): Promise<void>;
    deprecateAgent(agentId: string, reason: string): Promise<void>;
    updateAgent(agentId: string, updates: Partial<Agent>): Promise<Agent>;
    getTopPerformers(metric: string, limit?: number, periodDays?: number): Promise<TopPerformer[]>;
    getAgentPerformanceAlerts(agentId?: string, metric?: string, activeOnly?: boolean, limit?: number): Promise<PerformanceAlert[]>;
    getAgentPerformanceSummary(agentId?: string, days?: number): Promise<AgentPerformanceSummary>;
    getProjectSettings(projectId: string): Promise<ProjectSettings>;
    updateProjectSettings(projectId: string, settings: Partial<ProjectSettings>): Promise<ProjectSettings>;
    validateGithubRepo(projectId: string, url: string): Promise<GithubValidationResult>;
    /**
     * Get all BYOK credentials for a project (keys returned as prefix only)
     */
    getProjectCredentials(projectId: string): Promise<LLMCredential[]>;
    /**
     * Add or replace a BYOK credential for a project
     */
    addProjectCredential(projectId: string, provider: string, apiKey: string, name?: string): Promise<LLMCredential>;
    /**
     * Delete a BYOK credential from a project
     */
    deleteProjectCredential(projectId: string, credentialId: string): Promise<void>;
    /**
     * Re-enable a disabled credential with a new API key
     */
    reEnableProjectCredential(projectId: string, credentialId: string, apiKey: string): Promise<LLMCredential>;
    /**
     * Get audit log for a specific credential
     */
    getProjectCredentialAudit(projectId: string, credentialId: string, limit?: number): Promise<CredentialAuditEntry[]>;
    /**
     * Get all BYOK credentials for an organization
     */
    getOrgCredentials(orgId: string): Promise<LLMCredential[]>;
    /**
     * Add or replace a BYOK credential for an organization
     */
    addOrgCredential(orgId: string, provider: string, apiKey: string, name?: string): Promise<LLMCredential>;
    /**
     * Delete a BYOK credential from an organization
     */
    deleteOrgCredential(orgId: string, credentialId: string): Promise<void>;
    /**
     * Re-enable a disabled org credential with a new API key
     */
    reEnableOrgCredential(orgId: string, credentialId: string, apiKey: string): Promise<LLMCredential>;
    /**
     * Get audit log for an org credential
     */
    getOrgCredentialAudit(orgId: string, credentialId: string, limit?: number): Promise<CredentialAuditEntry[]>;
    /**
     * Get the current user's GitHub link for a project
     */
    getMyGitHubLink(projectId: string): Promise<GitHubLink | null>;
    /**
     * Link the current user's PAT credential to a project
     */
    linkMyPATToProject(projectId: string, options: {
        github_credential_id?: string;
        token?: string;
        name?: string;
    }): Promise<GitHubLink>;
    /**
     * Link the current user's GitHub App installation to a project
     */
    linkMyAppToProject(projectId: string, options: {
        installation_link_id?: string;
        installation_id?: number;
    }): Promise<GitHubLink>;
    /**
     * Remove the current user's GitHub link from a project
     */
    unlinkMyGitHubFromProject(projectId: string, linkType?: 'pat' | 'app'): Promise<{
        unlinked: boolean;
        deleted_count: number;
    }>;
    /**
     * Show which GitHub credential would be used for the current user + project
     */
    getGitHubResolution(projectId: string): Promise<GitHubResolution>;
    /**
     * Get the current user's GitHub preferences
     */
    getMyGitHubPreferences(): Promise<GitHubPreferences>;
    /**
     * Update the current user's GitHub preferences
     */
    updateMyGitHubPreferences(prefs: Partial<GitHubPreferences>): Promise<GitHubPreferences>;
    /**
     * List GitHub credentials owned by the current user
     */
    listMyGitHubCredentials(): Promise<GitHubCredential[]>;
    /**
     * List GitHub App installations accessible to the current user
     */
    listMyGitHubAppInstallations(): Promise<GitHubAppInstallation[]>;
    /**
     * Convert days to start/end date strings for CLI
     */
    private daysToDateRange;
    /**
     * Get cost breakdown by service (LLM, storage, compute, etc.)
     */
    getCostByService(days?: number): Promise<CostByServiceResponse>;
    /**
     * Get cost per run statistics
     */
    getCostPerRun(days?: number, limit?: number): Promise<CostPerRunResponse>;
    /**
     * Get ROI summary with token savings value
     */
    getROISummary(days?: number): Promise<ROISummaryResponse>;
    /**
     * Get daily cost trend
     */
    getDailyCosts(days?: number): Promise<DailyCostResponse>;
    /**
     * Get top expensive workflows
     */
    getTopExpensiveWorkflows(days?: number, limit?: number): Promise<TopExpensiveResponse>;
    /**
     * Execute CLI command and return parsed JSON result
     */
    runCLI(args: string[], options?: {
        parseJson?: boolean;
    }): Promise<any>;
    private sendTelemetry;
    emitTelemetry(eventType: string, payload: Record<string, unknown>, options?: TelemetryEmitOptions): Promise<void>;
    private withJsonFormat;
    private cleanupTempDir;
    dispose(): void;
}
export {};
//# sourceMappingURL=AmprealizeClient.d.ts.map
