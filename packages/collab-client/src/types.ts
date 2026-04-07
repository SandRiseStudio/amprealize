/**
 * Amprealize Collaboration Protocol Types
 *
 * Shared between SaaS (web-console) and VS Code extension for cross-surface parity.
 * Mirrors backend contracts in amprealize/collaboration_contracts.py.
 */

// ---------------------------------------------------------------------------
// Core Identifiers
// ---------------------------------------------------------------------------

export type WorkspaceId = string;
export type DocumentId = string;
export type UserId = string;
export type SessionId = string;
export type OperationId = string;

// ---------------------------------------------------------------------------
// Enums (mirror Python enums)
// ---------------------------------------------------------------------------

export enum EditOperationType {
  Insert = 'insert',
  Delete = 'delete',
  Replace = 'replace',
  Move = 'move',
  Format = 'format',
}

export enum CollaborationRole {
  Owner = 'owner',
  Admin = 'admin',
  Editor = 'editor',
  Commenter = 'commenter',
  Viewer = 'viewer',
}

export enum DocumentType {
  Markdown = 'markdown',
  Plan = 'plan',
  Workflow = 'workflow',
  Agent = 'agent',
  Json = 'json',
}

// ---------------------------------------------------------------------------
// Document Structures
// ---------------------------------------------------------------------------

export interface Workspace {
  id: WorkspaceId;
  name: string;
  description: string;
  owner_id: UserId;
  created_at: string; // ISO 8601
  updated_at: string;
  is_shared: boolean;
  settings?: Record<string, unknown>;
  tags?: string[];
}

export interface Document {
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

export interface EditOperation {
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

// ---------------------------------------------------------------------------
// WebSocket Protocol Messages
// ---------------------------------------------------------------------------

/**
 * Client → Server messages
 */
export type ClientMessage =
  | { type: 'ping' }
  | { type: 'edit'; operation: ClientEditOperation }
  | { type: 'cursor'; position: number; selection_end?: number }
  | { type: 'presence'; status: 'active' | 'idle' | 'away' };

export interface ClientEditOperation {
  operation_type: EditOperationType;
  position: number;
  content: string;
  length?: number;
  version: number; // Base version client is editing from
  user_id?: UserId;
  session_id?: SessionId;
}

/**
 * Server → Client messages
 */
export type ServerMessage =
  | { type: 'pong' }
  | { type: 'snapshot'; document: Document }
  | { type: 'operation'; operation: EditOperation; document: Document | null }
  | { type: 'cursor'; user_id: UserId; position: number; selection_end?: number }
  | { type: 'presence'; user_id: UserId; status: 'active' | 'idle' | 'away' | 'disconnected' }
  | { type: 'error'; code: ErrorCode; message: string; expected_version?: number; got_version?: number; document?: Document | null };

export type ErrorCode =
  | 'BAD_REQUEST'
  | 'NOT_FOUND'
  | 'VERSION_CONFLICT'
  | 'APPLY_FAILED'
  | 'UNAUTHORIZED';

// ---------------------------------------------------------------------------
// REST API Request/Response Types
// ---------------------------------------------------------------------------

export interface CreateWorkspaceRequest {
  name: string;
  description?: string;
  owner_id: string;
  settings?: Record<string, unknown>;
  tags?: string[];
  is_shared?: boolean;
}

export interface CreateDocumentRequest {
  workspace_id: WorkspaceId;
  title: string;
  content?: string;
  document_type?: DocumentType | string;
  created_by: UserId;
  metadata?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Presence & Cursors
// ---------------------------------------------------------------------------

export interface UserPresence {
  user_id: UserId;
  session_id?: SessionId;
  display_name?: string;
  color?: string; // Assigned cursor color
  status: 'active' | 'idle' | 'away' | 'disconnected';
  cursor_position?: number;
  selection_end?: number;
  last_active: string;
}

// ---------------------------------------------------------------------------
// Project Settings
// ---------------------------------------------------------------------------

export interface WorkflowSettings {
  require_approval_for_deploy: boolean;
  auto_merge_enabled: boolean;
  branch_protection_enabled: boolean;
  ci_required: boolean;
  code_owners_required: boolean;
  min_reviewers: number;
  allowed_merge_methods: string[];
}

export interface AgentSettings {
  max_concurrent_runs: number;
  default_timeout_seconds: number;
  auto_retry_enabled: boolean;
  max_retries: number;
  require_human_approval: boolean;
  allowed_actions: string[];
  blocked_actions: string[];
}

export interface BrandingSettings {
  logo_url?: string;
  favicon_url?: string;
  primary_color?: string;
  accent_color?: string;
  font_family?: string;
}

export interface GitHubBranchInfo {
  name: string;
  sha: string;
  protected: boolean;
}

export interface ProjectSettings {
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

export interface UpdateProjectSettingsRequest {
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

export interface GitHubRepoValidationRequest {
  repository_url: string;
  access_token?: string;
}

export interface GitHubRepoValidationResponse {
  valid: boolean;
  owner?: string;
  repo?: string;
  default_branch?: string;
  branches: GitHubBranchInfo[];
  visibility?: 'public' | 'private';
  description?: string;
  error?: string;
}

export interface GitHubBranchListResponse {
  branches: GitHubBranchInfo[];
  total_count?: number;
  page: number;
  per_page: number;
}

// ---------------------------------------------------------------------------
// Client Events (for UI binding)
// ---------------------------------------------------------------------------

export interface CollabClientEvents {
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

// ---------------------------------------------------------------------------
// Work Item Execution (shared UI + API types)
// ---------------------------------------------------------------------------

export type ExecutionState =
  | 'pending'
  | 'running'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'unknown';

export interface ExecutionStatus {
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

export interface ExecutionListItem {
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

export interface ExecutionListResponse {
  executions: ExecutionListItem[];
  total: number;
  offset: number;
  limit: number;
}

export interface ExecutionStep {
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

export interface ExecutionStepsResponse {
  steps: ExecutionStep[];
  total: number;
}

export interface ExecutionStatusEventPayload {
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

export interface ExecutionStepEventPayload {
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

export interface ExecutionStepSnapshotPayload {
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

export interface ExecutionStatusSnapshotPayload {
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

export interface ExecutionSnapshotEventPayload {
  run_id?: string | null;
  status?: ExecutionStatusEventPayload | ExecutionStatusSnapshotPayload | null;
  steps?: Array<ExecutionStepEventPayload['step'] | ExecutionStepSnapshotPayload>;
  executions?: ExecutionStatusEventPayload[];
}

export interface ExecutionReadyEventPayload {
  run_id?: string | null;
  org_id?: string | null;
  project_id?: string | null;
}

export interface ExecutionStreamEvents {
  connected: (context: ExecutionReadyEventPayload) => void;
  disconnected: (reason: string) => void;
  status: (payload: ExecutionStatusEventPayload) => void;
  step: (payload: ExecutionStepEventPayload) => void;
  snapshot: (payload: ExecutionSnapshotEventPayload) => void;
  ready: (payload: ExecutionReadyEventPayload) => void;
  error: (code: string, message: string) => void;
}

// ---------------------------------------------------------------------------
// Conversation Types (mirror amprealize/conversation_contracts.py)
// ---------------------------------------------------------------------------

export enum ConversationScope {
  ProjectRoom = 'project_room',
  AgentDm = 'agent_dm',
}

export enum ActorType {
  User = 'user',
  Agent = 'agent',
  System = 'system',
}

export enum MessageType {
  Text = 'text',
  StatusCard = 'status_card',
  BlockerCard = 'blocker_card',
  ProgressCard = 'progress_card',
  CodeBlock = 'code_block',
  RunSummary = 'run_summary',
  System = 'system',
}

export enum ParticipantRole {
  Owner = 'owner',
  Admin = 'admin',
  Member = 'member',
}

export enum NotificationPreference {
  All = 'all',
  Mentions = 'mentions',
  None = 'none',
}

export interface Conversation {
  id: string;
  project_id: string;
  org_id?: string | null;
  scope: ConversationScope | string;
  title?: string | null;
  created_by: string;
  pinned_message_id?: string | null;
  is_archived: boolean;
  metadata: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
  participant_count: number;
  unread_count: number;
}

export interface ConversationMessage {
  id: string;
  conversation_id: string;
  sender_id: string;
  sender_type: ActorType | string;
  content?: string | null;
  message_type: MessageType | string;
  structured_payload?: Record<string, unknown> | null;
  parent_id?: string | null;
  run_id?: string | null;
  behavior_id?: string | null;
  work_item_id?: string | null;
  is_edited: boolean;
  edited_at?: string | null;
  is_deleted: boolean;
  deleted_at?: string | null;
  metadata: Record<string, unknown>;
  created_at?: string | null;
  reactions: ConversationReaction[];
  reply_count: number;
}

export interface ConversationReaction {
  id: string;
  message_id: string;
  actor_id: string;
  actor_type: ActorType | string;
  emoji: string;
  created_at?: string | null;
}

export interface ConversationParticipant {
  id: string;
  conversation_id: string;
  actor_id: string;
  actor_type: ActorType | string;
  role: ParticipantRole | string;
  joined_at?: string | null;
  left_at?: string | null;
  last_read_at?: string | null;
  is_muted: boolean;
  notification_preference: NotificationPreference | string;
}

export interface ConversationListResponse {
  items: Conversation[];
  total: number;
}

export interface MessageListResponse {
  items: ConversationMessage[];
  total: number;
  has_more: boolean;
}

export interface SearchResult {
  message: ConversationMessage;
  rank: number;
  headline?: string | null;
}

export interface SearchResultsResponse {
  items: SearchResult[];
  total: number;
  query: string;
}

// ---------------------------------------------------------------------------
// Conversation WebSocket Event Payloads
// ---------------------------------------------------------------------------

export interface ConversationReadyPayload {
  conversation_id: string;
  typing: string[];
  subscriber_count: number;
}

export interface ConversationMessageEventPayload {
  conversation_id: string;
  message: ConversationMessage;
}

export interface ConversationReactionEventPayload {
  conversation_id: string;
  message_id: string;
  reaction: ConversationReaction;
}

export interface ConversationTypingPayload {
  conversation_id: string;
  actor_id: string;
  actor_type: ActorType | string;
  is_typing: boolean;
}

export interface ConversationReadReceiptPayload {
  conversation_id: string;
  actor_id: string;
  last_read_message_id: string;
}

export interface ConversationParticipantEventPayload {
  conversation_id: string;
  participant: ConversationParticipant;
}

// ---------------------------------------------------------------------------
// Conversation Stream Client Events
// ---------------------------------------------------------------------------

export interface ConversationStreamEvents {
  connected: (payload: ConversationReadyPayload) => void;
  disconnected: (reason: string) => void;
  'message.new': (payload: ConversationMessageEventPayload) => void;
  'message.updated': (payload: ConversationMessageEventPayload) => void;
  'message.deleted': (payload: ConversationMessageEventPayload) => void;
  'reaction.added': (payload: ConversationReactionEventPayload) => void;
  'reaction.removed': (payload: ConversationReactionEventPayload) => void;
  'typing.indicator': (payload: ConversationTypingPayload) => void;
  'read.receipt': (payload: ConversationReadReceiptPayload) => void;
  'participant.joined': (payload: ConversationParticipantEventPayload) => void;
  'participant.left': (payload: ConversationParticipantEventPayload) => void;
  error: (code: string, message: string) => void;
}
