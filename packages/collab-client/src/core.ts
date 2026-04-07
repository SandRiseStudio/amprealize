/**
 * @amprealize/collab-client/core
 *
 * Core collaboration client without React dependencies.
 * Use this in non-React environments (e.g., vanilla JS, VS Code extension host).
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
