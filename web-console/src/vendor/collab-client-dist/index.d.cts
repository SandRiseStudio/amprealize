import { CollabClientConfig, DocumentId, Document, ConnectionState, EditOperationType, UserId, UserPresence, EditOperation, CollabApiConfig, CollabApi, ProjectSettings, UpdateProjectSettingsRequest, GitHubRepoValidationRequest, GitHubRepoValidationResponse, GitHubBranchListResponse, ExecutionState, ExecutionStatus, ExecutionStep } from './core.cjs';
export { AgentSettings, BrandingSettings, ClientEditOperation, ClientMessage, CollabApiError, CollabClient, CollabClientEvents, CollaborationRole, CreateDocumentRequest, CreateWorkspaceRequest, DocumentType, ErrorCode, ExecutionListItem, ExecutionListResponse, ExecutionReadyEventPayload, ExecutionSnapshotEventPayload, ExecutionStatusEventPayload, ExecutionStatusSnapshotPayload, ExecutionStepEventPayload, ExecutionStepSnapshotPayload, ExecutionStepsResponse, ExecutionStreamClient, ExecutionStreamConfig, ExecutionStreamEvents, ExecutionStreamTarget, GitHubBranchInfo, OperationId, ServerMessage, SessionId, WorkflowSettings, Workspace, WorkspaceId, createCollabApi, createCollabClient, createExecutionStreamClient } from './core.cjs';
import React from 'react';

/**
 * React hooks for GuideAI Collaboration
 *
 * Provides useCollaboration hook for easy integration with React components.
 * Works in both SaaS (web-console) and VS Code webviews.
 */

interface UseCollaborationOptions {
    /** Client configuration */
    config: CollabClientConfig;
    /** Document to connect to */
    documentId: DocumentId;
    /** Called when document content changes (local or remote) */
    onContentChange?: (content: string, document: Document) => void;
    /** Called on version conflict - return rebased content or null to use server content */
    onConflict?: (serverDocument: Document) => string | null;
}
interface UseCollaborationReturn {
    /** Current document state */
    document: Document | null;
    /** Connection state */
    connectionState: ConnectionState;
    /** Whether connected and ready */
    isConnected: boolean;
    /** Send an edit operation */
    sendEdit: (type: EditOperationType, position: number, content: string, length?: number) => string;
    /** Send insert at position */
    insert: (position: number, content: string) => string;
    /** Send delete at position */
    delete: (position: number, length: number) => string;
    /** Send replace at position */
    replace: (position: number, length: number, content: string) => string;
    /** Update cursor position */
    updateCursor: (position: number, selectionEnd?: number) => void;
    /** Remote user cursors */
    cursors: Map<UserId, {
        position: number;
        selectionEnd?: number;
    }>;
    /** Remote user presence */
    presence: Map<UserId, UserPresence>;
    /** Recent operations (for undo/redo, debugging) */
    operations: EditOperation[];
    /** Last error */
    error: {
        code: string;
        message: string;
    } | null;
    /** Reconnect manually */
    reconnect: () => void;
    /** Disconnect */
    disconnect: () => void;
}
declare function useCollaboration(options: UseCollaborationOptions): UseCollaborationReturn;

declare function useCollabApi(config: CollabApiConfig): CollabApi;
interface UseProjectSettingsOptions {
    api: CollabApi;
    projectId: string;
    /** Auto-fetch on mount (default: true) */
    autoFetch?: boolean;
}
interface UseProjectSettingsReturn {
    settings: ProjectSettings | null;
    isLoading: boolean;
    error: Error | null;
    refetch: () => Promise<void>;
}
/**
 * Hook to fetch project settings.
 */
declare function useProjectSettings(options: UseProjectSettingsOptions): UseProjectSettingsReturn;
interface UseUpdateProjectSettingsOptions {
    api: CollabApi;
    projectId: string;
    /** Callback on successful update */
    onSuccess?: (settings: ProjectSettings) => void;
    /** Callback on error */
    onError?: (error: Error) => void;
}
interface UseUpdateProjectSettingsReturn {
    update: (updates: UpdateProjectSettingsRequest) => Promise<ProjectSettings | null>;
    isUpdating: boolean;
    error: Error | null;
}
/**
 * Hook to update project settings.
 */
declare function useUpdateProjectSettings(options: UseUpdateProjectSettingsOptions): UseUpdateProjectSettingsReturn;
interface UseValidateGitHubRepoOptions {
    api: CollabApi;
    projectId: string;
}
interface UseValidateGitHubRepoReturn {
    validate: (request: GitHubRepoValidationRequest) => Promise<GitHubRepoValidationResponse | null>;
    isValidating: boolean;
    result: GitHubRepoValidationResponse | null;
    error: Error | null;
}
/**
 * Hook to validate a GitHub repository.
 */
declare function useValidateGitHubRepo(options: UseValidateGitHubRepoOptions): UseValidateGitHubRepoReturn;
interface UseGitHubBranchesOptions {
    api: CollabApi;
    projectId: string;
    /** Auto-fetch on mount (default: false) */
    autoFetch?: boolean;
}
interface UseGitHubBranchesReturn {
    branches: GitHubBranchListResponse | null;
    isLoading: boolean;
    error: Error | null;
    refetch: (page?: number, perPage?: number) => Promise<void>;
}
/**
 * Hook to list GitHub branches for a project's repository.
 */
declare function useGitHubBranches(options: UseGitHubBranchesOptions): UseGitHubBranchesReturn;

interface ExecutionStatusBadgeProps {
    state?: ExecutionState | string | null;
    phase?: string | null;
    statusLabel?: string;
    phaseLabel?: string;
    progressPct?: number | null;
    showPhase?: boolean;
    showProgress?: boolean;
    className?: string;
}
declare function ExecutionStatusBadge({ state, phase, statusLabel, phaseLabel, progressPct, showPhase, showProgress, className, }: ExecutionStatusBadgeProps): React.JSX.Element;

interface ExecutionStatusCardProps {
    status?: ExecutionStatus | null;
    isLoading?: boolean;
    title?: string;
    subtitle?: string;
    actions?: React.ReactNode;
    emptyLabel?: string;
    className?: string;
}
declare function ExecutionStatusCard({ status, isLoading, title, subtitle, actions, emptyLabel, className, }: ExecutionStatusCardProps): React.JSX.Element;

interface ExecutionTimelineProps {
    steps?: ExecutionStep[];
    activePhase?: string | null;
    isLoading?: boolean;
    emptyLabel?: string;
    className?: string;
}
declare function ExecutionTimeline({ steps, activePhase, isLoading, emptyLabel, className, }: ExecutionTimelineProps): React.JSX.Element;

/**
 * ClarificationPanel - First-class UX for agent clarification requests
 *
 * Following COLLAB_SAAS_REQUIREMENTS.md:
 * - 60fps animations via GPU-accelerated transforms
 * - Floaty spring animations on state changes
 * - Accessible keyboard interactions
 * - Shared across web-console and VS Code webview
 */

interface ClarificationQuestion {
    /** Unique identifier for the question */
    id: string;
    /** The question prompt from the agent */
    question: string;
    /** Optional context about why this is being asked */
    context?: string | null;
    /** Whether a response is required to continue */
    required?: boolean;
}
interface ClarificationPanelProps {
    /** List of clarification questions from the agent */
    questions: ClarificationQuestion[];
    /** Callback when user submits a response */
    onSubmit: (questionId: string, response: string) => void;
    /** Whether submission is in progress */
    isSubmitting?: boolean;
    /** Optional className for styling overrides */
    className?: string;
    /** Title shown above questions */
    title?: string;
    /** Empty state message when no questions */
    emptyMessage?: string;
    /** Whether to show the panel in an expanded state */
    expanded?: boolean;
}
declare const ClarificationPanel: React.NamedExoticComponent<ClarificationPanelProps>;

export { ClarificationPanel, type ClarificationPanelProps, type ClarificationQuestion, CollabApi, CollabApiConfig, CollabClientConfig, ConnectionState, Document, DocumentId, EditOperation, EditOperationType, ExecutionState, ExecutionStatus, ExecutionStatusBadge, type ExecutionStatusBadgeProps, ExecutionStatusCard, type ExecutionStatusCardProps, ExecutionStep, ExecutionTimeline, type ExecutionTimelineProps, GitHubBranchListResponse, GitHubRepoValidationRequest, GitHubRepoValidationResponse, UserPresence as PresenceInfo, ProjectSettings, UpdateProjectSettingsRequest, type UseCollaborationOptions, type UseCollaborationReturn, type UseGitHubBranchesOptions, type UseGitHubBranchesReturn, type UseProjectSettingsOptions, type UseProjectSettingsReturn, type UseUpdateProjectSettingsOptions, type UseUpdateProjectSettingsReturn, type UseValidateGitHubRepoOptions, type UseValidateGitHubRepoReturn, UserId, UserPresence, useCollabApi, useCollaboration as useCollabDocument, useCollaboration, useGitHubBranches, useProjectSettings, useUpdateProjectSettings, useValidateGitHubRepo };
