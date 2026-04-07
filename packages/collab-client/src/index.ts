/**
 * @amprealize/collab-client
 *
 * Cross-surface real-time collaboration client for Amprealize.
 * Works in SaaS (web-console) and VS Code webviews.
 */

// Types
export * from './types.js';

// WebSocket Client
export { CollabClient, ConnectionState, createCollabClient } from './client.js';
export type { CollabClientConfig } from './client.js';
export { ExecutionStreamClient, createExecutionStreamClient } from './executionClient.js';
export type { ExecutionStreamConfig, ExecutionStreamTarget } from './executionClient.js';
export { ConversationStreamClient, createConversationStreamClient } from './conversationClient.js';
export type { ConversationStreamConfig } from './conversationClient.js';

// REST API Client
export { CollabApi, CollabApiError, createCollabApi } from './api.js';
export type { CollabApiConfig } from './api.js';

// React Hooks
export {
  useCollaboration,
  useCollaboration as useCollabDocument, // Alias for convenience
  useCollabApi,
  // Project Settings Hooks
  useProjectSettings,
  useUpdateProjectSettings,
  useValidateGitHubRepo,
  useGitHubBranches,
} from './react.js';
export type {
  UseCollaborationOptions,
  UseCollaborationReturn,
  // Project Settings Hook Types
  UseProjectSettingsOptions,
  UseProjectSettingsReturn,
  UseUpdateProjectSettingsOptions,
  UseUpdateProjectSettingsReturn,
  UseValidateGitHubRepoOptions,
  UseValidateGitHubRepoReturn,
  UseGitHubBranchesOptions,
  UseGitHubBranchesReturn,
} from './react.js';

// Re-export PresenceInfo type alias for convenience (UserPresence status type)
export type { UserPresence as PresenceInfo } from './types.js';

// Shared Execution UI Components
export {
  ClarificationPanel,
  ExecutionStatusBadge,
  ExecutionStatusCard,
  ExecutionTimeline,
} from './components/execution/index.js';
export type {
  ClarificationPanelProps,
  ClarificationQuestion,
  ExecutionStatusBadgeProps,
  ExecutionStatusCardProps,
  ExecutionTimelineProps,
} from './components/execution/index.js';
