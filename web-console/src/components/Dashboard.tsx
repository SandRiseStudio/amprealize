/**
 * Dashboard Component
 *
 * Landing page after login showing:
 * - Quick stats row (agents, runs, behaviors)
 * - Projects grid
 * - Active agents with status indicators
 * - Recent activity timeline
 * - Quick actions
 *
 * Uses WorkspaceShell for collaborative features.
 * Follows COLLAB_SAAS_REQUIREMENTS.md for UX: fast, floaty, smooth, animated.
 *
 * Following:
 * - behavior_validate_accessibility (Student)
 * - behavior_update_docs_after_changes (Student)
 */

import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useShellTitle } from './workspace/useShell';
import { useBoardsMultiProject, type Board } from '../api/boards';
import { orgContextStore, useOrgContext } from '../store/orgContextStore';
import {
  useDashboardStats,
  useOrganizations,
  useProjects,
  useRecentRuns,
  type Project,
  type Agent,
  type Run,
  type AgentStatus,
} from '../api/dashboard';
import { useAllProjectAgents, useVisibleProjectAgentPresence } from '../api/agentRegistry';
import { useAgentPresence } from '../hooks/useAgentPresence';
import type { AgentPresence } from '../hooks/useAgentPresence';
import { ActorAvatar } from './actors/ActorAvatar';
import { ActorPresenceScene } from './actors/ActorPresenceScene';
import {
  loadProjectSortPreference,
  saveProjectSortPreference,
  sortProjects,
  type ProjectSortMode,
} from '../utils/projectSort';
import {
  CREATE_PROJECT_CTA,
  CURRENT_SCOPE_LABEL,
  CREATE_ORGANIZATION_CTA,
  NEW_PROJECT_CTA,
  MANAGE_SCOPES_CTA,
  PERSONAL_SCOPE_DESCRIPTION,
  PERSONAL_SCOPE_LABEL,
  PERSONAL_SCOPE_SELECTED_HINT,
  PERSONAL_SCOPE_SHORT_HINT,
} from '../copy/scopeLabels';
import { razeLog } from '../telemetry/raze';
import './Dashboard.css';

// ---------------------------------------------------------------------------
// Icons (inline for performance, GPU-friendly)
// ---------------------------------------------------------------------------

const ProjectIcon = () => (
  <svg className="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M3 7a2 2 0 012-2h14a2 2 0 012 2v10a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
    <path d="M3 7l9 6 9-6" />
  </svg>
);

const AgentIcon = () => (
  <svg className="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <circle cx="12" cy="8" r="4" />
    <path d="M4 20c0-4.418 3.582-8 8-8s8 3.582 8 8" strokeLinecap="round" />
  </svg>
);

const RunIcon = () => (
  <svg className="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M5 3l14 9-14 9V3z" strokeLinejoin="round" />
  </svg>
);

const BehaviorIcon = () => (
  <svg className="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M12 2L2 7l10 5 10-5-10-5z" />
    <path d="M2 17l10 5 10-5" />
    <path d="M2 12l10 5 10-5" />
  </svg>
);

const PlusIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
    <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  </svg>
);

const ArrowRightIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
    <path d="M3 7h8M8 4l3 3-3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const BoardIcon = () => (
  <svg className="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <rect x="3" y="4" width="18" height="16" rx="3" />
    <path d="M9 4v16M15 4v16" />
  </svg>
);

const SettingsIcon = () => (
  <svg className="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M12 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5Z" />
    <path d="M19 12l1.8-1-1.4-2.4-2 .5a7.5 7.5 0 0 0-1.3-.8l-.2-2.1h-2.8l-.2 2.1c-.4.2-.9.5-1.3.8l-2-.5L3.2 11 5 12l-1.8 1 1.4 2.4 2-.5c.4.3.8.6 1.3.8l.2 2.1h2.8l.2-2.1c.5-.2.9-.5 1.3-.8l2 .5 1.4-2.4L19 12Z" strokeLinejoin="round" />
  </svg>
);

// ---------------------------------------------------------------------------
// Stat Card Component
// ---------------------------------------------------------------------------

interface StatCardProps {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  subValue?: string;
  trend?: 'up' | 'down' | 'neutral';
  onClick?: () => void;
  isLoading?: boolean;
}

const StatCard = memo(function StatCard({
  icon,
  label,
  value,
  subValue,
  onClick,
  isLoading,
}: StatCardProps) {
  return (
    <button
      className={`stat-card pressable ${isLoading ? 'loading' : ''}`}
      onClick={onClick}
      disabled={!onClick}
      data-haptic="light"
    >
      <div className="stat-card-icon">{icon}</div>
      <div className="stat-card-content">
        <span className="stat-card-value">
          {isLoading ? <span className="skeleton-text animate-shimmer" /> : value}
        </span>
        <span className="stat-card-label">{label}</span>
        {subValue && <span className="stat-card-subvalue">{subValue}</span>}
      </div>
    </button>
  );
});

// ---------------------------------------------------------------------------
// Workspace Card Component
// ---------------------------------------------------------------------------

interface WorkspaceCardProps {
  title: string;
  subtitle: string;
  meta?: string;
  active?: boolean;
  variant?: 'personal' | 'org' | 'create';
  onClick: () => void;
}

const WorkspaceCard = memo(function WorkspaceCard({
  title,
  subtitle,
  meta,
  active,
  variant = 'org',
  onClick,
}: WorkspaceCardProps) {
  return (
    <button
      className={`workspace-card pressable ${active ? 'active' : ''} variant-${variant} animate-fade-in-up`}
      onClick={onClick}
      aria-pressed={active}
      data-haptic="light"
    >
      <div className="workspace-card-header">
        <span className="workspace-card-title">{title}</span>
        <span className="workspace-badge">
          {variant === 'personal' ? 'Personal' : variant === 'create' ? 'Create' : 'Org'}
        </span>
      </div>
      <span className="workspace-card-subtitle">{subtitle}</span>
      {meta && <span className="workspace-card-meta">{meta}</span>}
    </button>
  );
});

// ---------------------------------------------------------------------------
// Project Card Component
// ---------------------------------------------------------------------------

interface ProjectCardProps {
  project: Project;
  boards: Board[];
  onOpenProject: () => void;
  onOpenBoard: (boardId: string) => void;
  agentAvatars?: AgentPresence[];
  agentSummaryLine?: string;
}

const ProjectCard = memo(function ProjectCard({ project, boards, onOpenProject, onOpenBoard, agentAvatars, agentSummaryLine }: ProjectCardProps) {
  const relativeTime = getRelativeTime(project.updated_at);

  // Smart-open: if exactly one board, go there; otherwise project overview
  const handleClick = useCallback(() => {
    if (boards.length === 1) {
      onOpenBoard(boards[0].board_id);
    } else {
      onOpenProject();
    }
  }, [boards, onOpenBoard, onOpenProject]);

  return (
    <button className="project-card pressable animate-fade-in-up" onClick={handleClick} data-haptic="light">
      <div className="project-card-header">
        <h3 className="project-card-title">{project.name}</h3>
        <span className={`project-visibility project-visibility-${project.visibility}`}>
          {project.visibility}
        </span>
      </div>
      {project.description && (
        <p className="project-card-description">{project.description}</p>
      )}
      {agentAvatars && agentAvatars.length > 0 && (
        <div className="project-card-agents">
          <div className="project-card-agent-stack">
            {agentAvatars.map((a, i) => (
              <ActorAvatar
                key={a.agentId}
                className="project-card-agent-avatar"
                actor={a.actor}
                size="sm"
                surfaceType="dashboard"
                decorative
                showPresenceDot={false}
                style={{
                  zIndex: agentAvatars.length - i,
                } as React.CSSProperties}
              />
            ))}
          </div>
          {agentSummaryLine && (
            <span className="project-card-agent-summary">{agentSummaryLine}</span>
          )}
        </div>
      )}
      <div className="project-card-meta">
        <span className="project-meta-item">
          <AgentIcon />
          {project.agent_count ?? 0} agents
        </span>
        <span className="project-meta-item">
          <RunIcon />
          {project.run_count ?? 0} runs
        </span>
        <span className="project-meta-time">Updated {relativeTime}</span>
      </div>
    </button>
  );
});

interface ContinueWorkingCardProps {
  project: Project;
  boards: Board[];
  onOpenProject: () => void;
  onOpenSettings: () => void;
  onOpenBoard: (boardId: string) => void;
}

const ContinueWorkingCard = memo(function ContinueWorkingCard({
  project,
  boards,
  onOpenProject,
  onOpenSettings,
  onOpenBoard,
}: ContinueWorkingCardProps) {
  const primaryBoard = useMemo(
    () => boards.find((board) => board.is_default) ?? boards[0],
    [boards]
  );
  const relativeTime = getRelativeTime(project.updated_at);

  return (
    <section className="dashboard-section dashboard-focus" aria-label="Continue working">
      <div className="section-header">
        <h2 className="section-title">Continue Working</h2>
      </div>
      <div className="dashboard-focus-card animate-fade-in-up">
        <div className="dashboard-focus-copy">
          <span className="dashboard-focus-kicker">Most recently updated project</span>
          <h3 className="dashboard-focus-title">{project.name}</h3>
          <p className="dashboard-focus-description">
            {project.description || 'Pick up where you left off with boards, agents, and runs all in one place.'}
          </p>
          <div className="dashboard-focus-meta">
            <span className="dashboard-focus-pill">
              <BoardIcon />
              {boards.length} board{boards.length === 1 ? '' : 's'}
            </span>
            <span className="dashboard-focus-pill">
              <AgentIcon />
              {project.agent_count ?? 0} agents
            </span>
            <span className="dashboard-focus-pill subtle">Updated {relativeTime}</span>
          </div>
        </div>
        <div className="dashboard-focus-actions">
          <button className="dashboard-focus-primary pressable" onClick={() => primaryBoard ? onOpenBoard(primaryBoard.board_id) : onOpenProject()} data-haptic="medium">
            {primaryBoard ? 'Open Board' : 'Open Project'}
          </button>
          <button className="dashboard-focus-secondary pressable" onClick={onOpenProject} data-haptic="light">
            Project Overview
          </button>
          <button className="dashboard-focus-secondary pressable" onClick={onOpenSettings} data-haptic="light">
            <SettingsIcon />
            Settings
          </button>
        </div>
      </div>
    </section>
  );
});

// ---------------------------------------------------------------------------
// Agent Status Badge
// ---------------------------------------------------------------------------

const agentStatusConfig: Record<AgentStatus, { label: string; className: string }> = {
  active: { label: 'Active', className: 'status-active' },
  busy: { label: 'Busy', className: 'status-busy' },
  idle: { label: 'Idle', className: 'status-idle' },
  paused: { label: 'Paused', className: 'status-paused' },
  disabled: { label: 'Disabled', className: 'status-disabled' },
  archived: { label: 'Archived', className: 'status-archived' },
};

interface AgentRowProps {
  agent: Agent;
  onClick: () => void;
}

const AgentRow = memo(function AgentRow({ agent, onClick }: AgentRowProps) {
  const config = agentStatusConfig[agent.status] ?? agentStatusConfig.idle;
  const lastActive = agent.last_active_at ? getRelativeTime(agent.last_active_at) : 'Never';

  return (
    <button className="agent-row pressable" onClick={onClick} data-haptic="light">
      <div className="agent-row-avatar">
        {agent.name.charAt(0).toUpperCase()}
      </div>
      <div className="agent-row-info">
        <span className="agent-row-name">{agent.name}</span>
        <span className="agent-row-type">{agent.agent_type}</span>
      </div>
      <div className="agent-row-status">
        <span className={`status-badge ${config.className}`}>
          <span className="status-dot" />
          {config.label}
        </span>
      </div>
      <span className="agent-row-last-active">Last active {lastActive}</span>
    </button>
  );
});

// ---------------------------------------------------------------------------
// Run Status Badge
// ---------------------------------------------------------------------------

// Config for both uppercase (backend) and lowercase status values
const runStatusConfig: Record<string, { label: string; className: string }> = {
  PENDING: { label: 'Pending', className: 'run-status-pending' },
  RUNNING: { label: 'Running', className: 'run-status-running' },
  COMPLETED: { label: 'Completed', className: 'run-status-completed' },
  FAILED: { label: 'Failed', className: 'run-status-failed' },
  CANCELLED: { label: 'Cancelled', className: 'run-status-cancelled' },
  // Lowercase fallbacks for compatibility
  pending: { label: 'Pending', className: 'run-status-pending' },
  running: { label: 'Running', className: 'run-status-running' },
  completed: { label: 'Completed', className: 'run-status-completed' },
  failed: { label: 'Failed', className: 'run-status-failed' },
  cancelled: { label: 'Cancelled', className: 'run-status-cancelled' },
};

interface RunRowProps {
  run: Run;
  onClick?: () => void;
  destinationLabel?: string | null;
}

const RunRow = memo(function RunRow({ run, onClick, destinationLabel }: RunRowProps) {
  const config = runStatusConfig[run.status] ?? runStatusConfig.PENDING;
  const startedAt = getRelativeTime(run.started_at);
  const duration = run.duration_ms ? formatDuration(run.duration_ms) : null;

  const content = (
    <>
      <div className={`run-row-status ${config.className}`}>
        <span className="status-indicator" />
      </div>
      <div className="run-row-info">
        <span className="run-row-name">{run.workflow_name ?? run.run_id.slice(0, 8)}</span>
        <span className="run-row-agent">
          {run.actor?.id ?? 'Unknown Actor'}
          {destinationLabel ? ` · ${destinationLabel}` : ''}
        </span>
      </div>
      <div className="run-row-meta">
        <span className="run-row-time">{startedAt}</span>
        {duration && <span className="run-row-duration">{duration}</span>}
      </div>
    </>
  );

  if (!onClick) {
    return <div className="run-row run-row-static animate-fade-in-up">{content}</div>;
  }

  return (
    <button className="run-row pressable" onClick={onClick} data-haptic="light">
      {content}
    </button>
  );
});

// ---------------------------------------------------------------------------
// Quick Action Button
// ---------------------------------------------------------------------------

interface QuickActionProps {
  icon: React.ReactNode;
  label: string;
  description: string;
  onClick: () => void;
  badge?: string;
}

const QuickAction = memo(function QuickAction({ icon, label, description, onClick, badge }: QuickActionProps) {
  return (
    <button className="quick-action pressable animate-fade-in-up" onClick={onClick} data-haptic="medium">
      <div className="quick-action-icon">{icon}</div>
      <div className="quick-action-content">
        <span className="quick-action-heading">
          <span className="quick-action-label">{label}</span>
          {badge && <span className="quick-action-badge">{badge}</span>}
        </span>
        <span className="quick-action-description">{description}</span>
      </div>
      <ArrowRightIcon />
    </button>
  );
});

function getProjectPriorityScore(project: Project): number {
  const updatedAt = project.updated_at ? new Date(project.updated_at).getTime() : 0;
  return updatedAt + ((project.agent_count ?? 0) * 250_000) + ((project.run_count ?? 0) * 100_000);
}

function getNestedString(source: unknown, paths: string[]): string | undefined {
  for (const path of paths) {
    const value = path.split('.').reduce<unknown>((current, key) => {
      if (!current || typeof current !== 'object') return undefined;
      return (current as Record<string, unknown>)[key];
    }, source);

    if (typeof value === 'string' && value.length > 0) {
      return value;
    }
  }

  return undefined;
}

function extractRunTarget(run: Run): { projectId?: string; boardId?: string; itemId?: string; destinationLabel?: string } | null {
  const sources = [run.metadata ?? {}, run.outputs ?? {}];
  const projectId = getNestedString(sources, [
    '0.project_id',
    '0.projectId',
    '0.context.project_id',
    '0.context.projectId',
    '0.target.project_id',
    '0.target.projectId',
    '1.project_id',
    '1.projectId',
    '1.context.project_id',
    '1.context.projectId',
    '1.target.project_id',
    '1.target.projectId',
  ]);
  const boardId = getNestedString(sources, [
    '0.board_id',
    '0.boardId',
    '0.context.board_id',
    '0.context.boardId',
    '0.target.board_id',
    '0.target.boardId',
    '1.board_id',
    '1.boardId',
    '1.context.board_id',
    '1.context.boardId',
    '1.target.board_id',
    '1.target.boardId',
  ]);
  const itemId = getNestedString(sources, [
    '0.item_id',
    '0.itemId',
    '0.work_item_id',
    '0.workItemId',
    '0.target.item_id',
    '0.target.itemId',
    '1.item_id',
    '1.itemId',
    '1.work_item_id',
    '1.workItemId',
    '1.target.item_id',
    '1.target.itemId',
  ]);

  if (!projectId && !boardId && !itemId) return null;

  return {
    projectId,
    boardId,
    itemId,
    destinationLabel: itemId ? 'Recent item' : boardId ? 'Recent board' : 'Recent project',
  };
}

function getRunDestination(run: Run): { path: string; label: string } | null {
  const target = extractRunTarget(run);
  if (!target?.projectId) return null;

  if (target.boardId && target.itemId) {
    return {
      path: `/projects/${target.projectId}/boards/${target.boardId}/items/${target.itemId}`,
      label: target.destinationLabel ?? 'Recent item',
    };
  }

  if (target.boardId) {
    return {
      path: `/projects/${target.projectId}/boards/${target.boardId}`,
      label: target.destinationLabel ?? 'Recent board',
    };
  }

  return {
    path: `/projects/${target.projectId}`,
    label: target.destinationLabel ?? 'Recent project',
  };
}

interface PersonalizedActionsProps {
  featuredProject?: Project;
  featuredBoards: Board[];
  recentRuns: Run[];
  runningRuns: number;
  hasAgents: boolean;
  newProjectPath: string;
  onNavigate: (path: string) => void;
}

function PersonalizedActions({
  featuredProject,
  featuredBoards,
  recentRuns,
  runningRuns,
  hasAgents,
  newProjectPath,
  onNavigate,
}: PersonalizedActionsProps) {
  const primaryBoard = useMemo(
    () => featuredBoards.find((board) => board.is_default) ?? featuredBoards[0],
    [featuredBoards]
  );
  const recentRunTarget = useMemo(
    () => recentRuns.map((run) => getRunDestination(run)).find((target): target is { path: string; label: string } => Boolean(target)) ?? null,
    [recentRuns]
  );

  const actions = useMemo(() => {
    const nextActions: QuickActionProps[] = [];

    if (!featuredProject) {
      nextActions.push({
        icon: <ProjectIcon />,
        label: 'Create Your First Project',
        description: 'Set up the first project where humans and agents will collaborate.',
        onClick: () => onNavigate(newProjectPath),
        badge: 'Start here',
      });
    }

    if (featuredProject && primaryBoard) {
      nextActions.push({
        icon: <BoardIcon />,
        label: 'Resume Board',
        description: `Open ${primaryBoard.name} and continue the latest project work.`,
        onClick: () => onNavigate(`/projects/${featuredProject.id}/boards/${primaryBoard.board_id}`),
        badge: 'Continue',
      });
    } else if (featuredProject) {
      nextActions.push({
        icon: <ProjectIcon />,
        label: 'Create First Board',
        description: `Add a board inside ${featuredProject.name} to coordinate execution.`,
        onClick: () => onNavigate(`/projects/${featuredProject.id}?newBoard=1`),
        badge: 'Setup',
      });
    }

    if (recentRunTarget) {
      nextActions.push({
        icon: <RunIcon />,
        label: 'Continue Recent Run',
        description: `Jump back into the ${recentRunTarget.label.toLowerCase()} tied to your latest execution activity.`,
        onClick: () => onNavigate(recentRunTarget.path),
        badge: 'Resume',
      });
    } else if (runningRuns > 0 && featuredProject && primaryBoard) {
      nextActions.push({
        icon: <RunIcon />,
        label: 'Monitor Live Work',
        description: 'Open the active working board to follow current execution.',
        onClick: () => onNavigate(`/projects/${featuredProject.id}/boards/${primaryBoard.board_id}`),
        badge: `${runningRuns} live`,
      });
    }

    if (!hasAgents) {
      nextActions.push({
        icon: <AgentIcon />,
        label: 'Create Agent',
        description: 'Configure your first AI agent for orchestration and execution.',
        onClick: () => onNavigate('/agents/new'),
        badge: 'Recommended',
      });
    }

    nextActions.push({
      icon: <BehaviorIcon />,
      label: 'Behavior Search',
      description: 'Find the right reusable behavior before starting a task.',
      onClick: () => onNavigate('/bci'),
    });

    nextActions.push({
      icon: <PlusIcon />,
      label: 'Behavior Extraction',
      description: 'Turn successful traces into handbook-ready behavior candidates.',
      onClick: () => onNavigate('/bci/extraction'),
    });

    return nextActions.slice(0, 4);
  }, [featuredProject, hasAgents, newProjectPath, onNavigate, primaryBoard, recentRunTarget, runningRuns]);

  return (
    <>
      {actions.map((action) => (
        <QuickAction key={action.label} {...action} />
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------
// Empty State Component
// ---------------------------------------------------------------------------

interface EmptyStateProps {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
}

const EmptyState = memo(function EmptyState({
  title,
  description,
  actionLabel,
  onAction,
}: EmptyStateProps) {
  return (
    <div className="empty-state animate-fade-in-up">
      <h3 className="empty-state-title">{title}</h3>
      <p className="empty-state-description">{description}</p>
      {actionLabel && onAction && (
        <button className="empty-state-action pressable" onClick={onAction} data-haptic="medium">
          <PlusIcon />
          {actionLabel}
        </button>
      )}
    </div>
  );
});

// ---------------------------------------------------------------------------
// Skeleton Loading Components
// ---------------------------------------------------------------------------

const StatCardSkeleton = () => (
  <div className="stat-card skeleton">
    <div className="skeleton-icon animate-shimmer" />
    <div className="stat-card-content">
      <span className="skeleton-text skeleton-value animate-shimmer" />
      <span className="skeleton-text skeleton-label animate-shimmer" />
    </div>
  </div>
);

const ProjectCardSkeleton = () => (
  <div className="project-card skeleton">
    <div className="project-card-header">
      <span className="skeleton-text skeleton-title animate-shimmer" />
    </div>
    <span className="skeleton-text skeleton-description animate-shimmer" />
    <span className="skeleton-text skeleton-meta animate-shimmer" />
  </div>
);

// ---------------------------------------------------------------------------
// Utility Functions
// ---------------------------------------------------------------------------

function getRelativeTime(dateString?: string): string {
  if (!dateString) return 'Unknown';
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSecs < 60) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

function formatDuration(ms: number): string {
  const secs = Math.floor(ms / 1000);
  const mins = Math.floor(secs / 60);
  const hours = Math.floor(mins / 60);

  if (hours > 0) return `${hours}h ${mins % 60}m`;
  if (mins > 0) return `${mins}m ${secs % 60}s`;
  return `${secs}s`;
}

// ---------------------------------------------------------------------------
// Dashboard Sidebar Content
// ---------------------------------------------------------------------------



// ---------------------------------------------------------------------------
// Main Dashboard Component
// ---------------------------------------------------------------------------

export function Dashboard() {
  const navigate = useNavigate();
  const { currentOrgId } = useOrgContext();
  const [projectSortMode, setProjectSortMode] = useState<ProjectSortMode>(() => loadProjectSortPreference());
  const [agentPanelEnabled, setAgentPanelEnabled] = useState(false);
  const dashboardPerfStartedAtRef = useRef(typeof performance !== 'undefined' ? performance.now() : Date.now());
  const dashboardPerfFlagsRef = useRef<{ chrome?: string; agentPanel?: string }>({});
  const scopePerfKey = currentOrgId ?? 'personal';

  useEffect(() => {
    saveProjectSortPreference(projectSortMode);
  }, [projectSortMode]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setAgentPanelEnabled(true);
    }, 250);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    dashboardPerfStartedAtRef.current = typeof performance !== 'undefined' ? performance.now() : Date.now();
    dashboardPerfFlagsRef.current = {};
  }, [scopePerfKey]);

  // API hooks
  const { data: stats, isLoading: statsLoading } = useDashboardStats();
  const { data: organizations = [] } = useOrganizations();
  const {
    data: projects = [],
    isLoading: projectsLoading,
    isFetching: projectsFetching,
    isError: projectsError,
    refetch: refetchProjects,
  } = useProjects(currentOrgId ?? undefined);
  const {
    data: agents = [],
    isLoading: agentsLoading,
    isFetching: agentsFetching,
    isError: agentsError,
  } = useAllProjectAgents({ enabled: agentPanelEnabled });
  const {
    data: recentRuns = [],
    isLoading: runsLoading,
    isFetching: runsFetching,
    isError: runsError,
  } = useRecentRuns(5);
  const sortedOrganizations = useMemo(
    () => [...organizations].sort((a, b) => a.name.localeCompare(b.name)),
    [organizations]
  );

  // Navigation handlers
  const handleNavigate = useCallback((path: string) => {
    navigate(path);
  }, [navigate]);

  const newProjectPath = useMemo(() => {
    return currentOrgId ? `/projects/new?org=${encodeURIComponent(currentOrgId)}` : '/projects/new';
  }, [currentOrgId]);

  const scopedAgents = agents;
  const { presences: allPresences } = useAgentPresence(agents);

  const scopedStats = useMemo(() => {
    if (!stats) return undefined;
    const activeAgents = agentPanelEnabled
      ? scopedAgents.filter((agent) => agent.status === 'active').length
      : stats.active_agents;
    const busyAgents = agentPanelEnabled
      ? scopedAgents.filter((agent) => agent.status === 'busy').length
      : stats.busy_agents;
    return {
      ...stats,
      total_projects: projects.length,
      total_agents: agentPanelEnabled ? scopedAgents.length : stats.total_agents,
      active_agents: activeAgents,
      busy_agents: busyAgents,
    };
  }, [agentPanelEnabled, projects, scopedAgents, stats]);

  const prioritizedProjects = useMemo(() => {
    if (projectSortMode === 'activity') {
      return [...projects].sort((a, b) => getProjectPriorityScore(b) - getProjectPriorityScore(a));
    }
    return sortProjects(projects, projectSortMode);
  }, [projectSortMode, projects]);

  const handleProjectClick = useCallback((project: Project) => {
    navigate(`/projects/${project.id}`);
  }, [navigate]);

  const handleAgentClick = useCallback((agent: Agent) => {
    const config = (agent.config ?? {}) as Record<string, unknown>;
    const registryAgentId = typeof config.registry_agent_id === 'string' ? config.registry_agent_id : null;
    navigate(registryAgentId ? `/agents/${registryAgentId}` : '/agents');
  }, [navigate]);

  // Limit displayed items
  const displayedProjects = prioritizedProjects.slice(0, 6);
  const featuredProject = useMemo(
    () => prioritizedProjects[0],
    [prioritizedProjects]
  );
  const visibleProjectIds = useMemo(() => {
    const ids = new Set(displayedProjects.map((project) => project.id));
    if (featuredProject) {
      ids.add(featuredProject.id);
    }
    return [...ids];
  }, [displayedProjects, featuredProject]);
  const {
    data: visibleProjectPresence,
  } = useVisibleProjectAgentPresence(visibleProjectIds, {
    enabled: visibleProjectIds.length > 0,
  });
  const { data: boardsByProject } = useBoardsMultiProject(visibleProjectIds);
  const displayedAgents = scopedAgents.slice(0, 5);
  const showProjectsLoading = projectsLoading
    || (projectsFetching && projects.length === 0)
    || (projectsError && projects.length === 0);
  const showAgentsLoading = agentsLoading
    || (agentsFetching && scopedAgents.length === 0)
    || (agentsError && scopedAgents.length === 0)
    || !agentPanelEnabled;
  const showRunsLoading = runsLoading
    || (runsFetching && recentRuns.length === 0)
    || (runsError && recentRuns.length === 0);
  const projectsBannerTitle = projectsError ? 'Reconnecting to projects' : 'Syncing current scope';
  const projectsBannerDescription = projectsError
    ? 'We hit a bump loading projects. Retrying now.'
    : 'Pulling your projects into focus.';
  const projectsBannerClassName = projectsError
    ? 'projects-loading-banner is-error animate-fade-in-up'
    : 'projects-loading-banner animate-fade-in-up';

  const handleProjectsRetry = useCallback(() => {
    refetchProjects();
  }, [refetchProjects]);

  useEffect(() => {
    if (showProjectsLoading || !scopedStats) return;
    if (dashboardPerfFlagsRef.current.chrome === scopePerfKey) return;
    dashboardPerfFlagsRef.current.chrome = scopePerfKey;
    const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
    void razeLog('INFO', 'dashboard.chrome_ready', {
      scope: currentOrgId ? 'org' : 'personal',
      org_id: currentOrgId ?? null,
      project_count: projects.length,
      visible_project_count: visibleProjectIds.length,
      elapsed_ms: Math.round(now - dashboardPerfStartedAtRef.current),
    });
  }, [currentOrgId, projects.length, scopedStats, scopePerfKey, showProjectsLoading, visibleProjectIds.length]);

  useEffect(() => {
    if (!agentPanelEnabled || showAgentsLoading) return;
    if (dashboardPerfFlagsRef.current.agentPanel === scopePerfKey) return;
    dashboardPerfFlagsRef.current.agentPanel = scopePerfKey;
    const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
    void razeLog('INFO', 'dashboard.agent_panel_ready', {
      scope: currentOrgId ? 'org' : 'personal',
      org_id: currentOrgId ?? null,
      total_agents: scopedAgents.length,
      displayed_agents: displayedAgents.length,
      elapsed_ms: Math.round(now - dashboardPerfStartedAtRef.current),
    });
  }, [agentPanelEnabled, currentOrgId, displayedAgents.length, scopedAgents.length, scopePerfKey, showAgentsLoading]);

  useShellTitle('Home');

  return (
      <div className="dashboard">
        {/* Header */}
        <header className="dashboard-header">
          <div className="dashboard-header-left">
            <div className="dashboard-header-copy">
              <h1 className="dashboard-title animate-fade-in-up">Home</h1>
              <p className="dashboard-description animate-fade-in-up">
                Continue work across projects, monitor agents, and launch tools from one place.
              </p>
            </div>
          </div>
        </header>

        {/* Current scope */}
        <section className="dashboard-section dashboard-workspaces" aria-label="Current scope">
          <div className="section-header">
            <h2 className="section-title">{CURRENT_SCOPE_LABEL}</h2>
            <button
              className="section-action pressable"
              onClick={() => handleNavigate('/orgs')}
              data-haptic="light"
            >
              {MANAGE_SCOPES_CTA}
              <ArrowRightIcon />
            </button>
          </div>
          <div className="workspace-cards">
            <WorkspaceCard
              title={PERSONAL_SCOPE_LABEL}
              subtitle={PERSONAL_SCOPE_DESCRIPTION}
              meta={currentOrgId ? PERSONAL_SCOPE_SHORT_HINT : PERSONAL_SCOPE_SELECTED_HINT}
              active={!currentOrgId}
              variant="personal"
              onClick={() => orgContextStore.setCurrentOrgId(null)}
            />
            {sortedOrganizations.length === 0 ? (
              <WorkspaceCard
                title={CREATE_ORGANIZATION_CTA}
                subtitle="Invite teammates and manage shared projects."
                meta="Start collaborating"
                variant="create"
                onClick={() => handleNavigate('/orgs')}
              />
            ) : (
              sortedOrganizations.map((org) => (
                <WorkspaceCard
                  key={org.id}
                  title={org.name}
                  subtitle={org.slug}
                  meta={
                    org.member_count == null
                      ? 'Members unknown'
                      : `${org.member_count} member${org.member_count === 1 ? '' : 's'}`
                  }
                  active={currentOrgId === org.id}
                  variant="org"
                  onClick={() => orgContextStore.setCurrentOrgId(org.id)}
                />
              ))
            )}
          </div>
        </section>

        {featuredProject && (
          <ContinueWorkingCard
            project={featuredProject}
            boards={boardsByProject.get(featuredProject.id) ?? []}
            onOpenProject={() => handleProjectClick(featuredProject)}
            onOpenSettings={() => navigate(`/projects/${featuredProject.id}/settings`)}
            onOpenBoard={(boardId) => navigate(`/projects/${featuredProject.id}/boards/${boardId}`)}
          />
        )}

        <ActorPresenceScene
          actors={allPresences.map((presence) => presence.actor)}
          onActorClick={(actor) => {
            const match = agents.find((candidate) => ((candidate.config?.registry_agent_id as string | undefined) || candidate.id) === actor.id);
            if (match) handleAgentClick(match);
          }}
        />

        {/* Stats Row */}
        <section className="dashboard-stats" aria-label="Key metrics">
          {statsLoading ? (
            <>
              <StatCardSkeleton />
              <StatCardSkeleton />
              <StatCardSkeleton />
              <StatCardSkeleton />
            </>
          ) : (
            <>
              <StatCard
                icon={<ProjectIcon />}
                label="Projects"
                value={scopedStats?.total_projects ?? 0}
                onClick={() => handleNavigate('/projects')}
              />
              <StatCard
                icon={<AgentIcon />}
                label="Agents"
                value={scopedStats?.total_agents ?? 0}
                subValue={`${scopedStats?.active_agents ?? 0} active`}
                onClick={() => handleNavigate('/agents')}
              />
              <StatCard
                icon={<RunIcon />}
                label="Runs Today"
                value={stats?.completed_runs_today ?? 0}
                subValue={`${stats?.running_runs ?? 0} running`}
              />
              <StatCard
                icon={<BehaviorIcon />}
                label="Handbook Behaviors"
                value={stats?.total_behaviors ?? 0}
              />
            </>
          )}
        </section>

        {/* Main Content Grid */}
        <div className="dashboard-grid">
          {/* Projects Section */}
          <section className="dashboard-section dashboard-projects" aria-label="Projects">
            <div className="section-header">
              <h2 className="section-title">Projects</h2>
              <span className="section-supporting-copy">Prioritized by recent activity and active agents</span>
              <label className="section-sort-control">
                <span className="section-sort-label">Sort</span>
                <select
                  className="section-sort-select"
                  value={projectSortMode}
                  onChange={(event) => setProjectSortMode(event.target.value as ProjectSortMode)}
                  aria-label="Sort projects"
                >
                  <option value="activity">Activity</option>
                  <option value="updated">Last updated</option>
                  <option value="name">Name</option>
                </select>
              </label>
              <button
                className="section-action pressable"
                onClick={() => handleNavigate(newProjectPath)}
                data-haptic="light"
              >
                <PlusIcon />
                {NEW_PROJECT_CTA}
              </button>
            </div>
            <div className="projects-grid">
              {showProjectsLoading ? (
                <>
                  <div className={projectsBannerClassName} role="status" aria-live="polite">
                    <span className="projects-loading-dot animate-pulse" />
                    <div className="projects-loading-text">
                      <span className="projects-loading-title">{projectsBannerTitle}</span>
                      <span className="projects-loading-description">{projectsBannerDescription}</span>
                    </div>
                    {projectsError && (
                      <button
                        type="button"
                        className="projects-loading-action pressable"
                        onClick={handleProjectsRetry}
                        data-haptic="light"
                      >
                        Retry
                      </button>
                    )}
                  </div>
                  <ProjectCardSkeleton />
                  <ProjectCardSkeleton />
                  <ProjectCardSkeleton />
                </>
              ) : displayedProjects.length > 0 ? (
                displayedProjects.map((project) => {
                      const presence = visibleProjectPresence.get(project.id);
                      return (
                        <ProjectCard
                          key={project.id}
                          project={project}
                          boards={boardsByProject.get(project.id) ?? []}
                          onOpenProject={() => handleProjectClick(project)}
                          onOpenBoard={(boardId) => navigate(`/projects/${project.id}/boards/${boardId}`)}
                          agentAvatars={presence?.agents.slice(0, 3)}
                          agentSummaryLine={presence?.summaryLine}
                        />
                      );
                })
              ) : (
                <EmptyState
                  title="No projects yet"
                  description="Create your first project to get started"
                    actionLabel={CREATE_PROJECT_CTA}
                  onAction={() => handleNavigate(newProjectPath)}
                />
              )}
            </div>
          </section>

          {/* Active Agents Section */}
          <section className="dashboard-section dashboard-agents" aria-label="Active agents">
            <div className="section-header">
              <h2 className="section-title">Agents</h2>
              <button
                className="section-action pressable"
                onClick={() => handleNavigate('/agents')}
                data-haptic="light"
              >
                View All
                <ArrowRightIcon />
              </button>
            </div>
            <div className="agents-list">
              {showAgentsLoading ? (
                <div className="loading-placeholder animate-shimmer" />
              ) : displayedAgents.length > 0 ? (
                displayedAgents.map((agent) => (
                  <AgentRow
                    key={agent.id}
                    agent={agent}
                    onClick={() => handleAgentClick(agent)}
                  />
                ))
              ) : (
                <EmptyState
                  title="No agents configured"
                  description="Set up agents to automate your workflows"
                  actionLabel="Create Agent"
                  onAction={() => handleNavigate('/agents/new')}
                />
              )}
            </div>
          </section>

          {/* Recent Activity Section */}
          <section className="dashboard-section dashboard-activity" aria-label="Recent activity">
            <div className="section-header">
              <h2 className="section-title">Recent Activity</h2>
            </div>
            <div className="runs-list">
              {showRunsLoading ? (
                <div className="loading-placeholder animate-shimmer" />
              ) : recentRuns.length > 0 ? (
                recentRuns.map((run) => {
                  const destination = getRunDestination(run);
                  return (
                    <RunRow
                      key={run.run_id}
                      run={run}
                      onClick={destination ? () => handleNavigate(destination.path) : undefined}
                      destinationLabel={destination?.label}
                    />
                  );
                })
              ) : (
                <EmptyState
                  title="No recent runs"
                  description="Runs will appear here once agents start executing"
                />
              )}
            </div>
          </section>

          {/* Quick Actions Section */}
          <section className="dashboard-section dashboard-quick-actions" aria-label="Recommended next steps">
            <div className="section-header">
              <h2 className="section-title">Recommended Next Steps</h2>
            </div>
            <div className="quick-actions-list">
              <PersonalizedActions
                featuredProject={featuredProject}
                featuredBoards={featuredProject ? boardsByProject.get(featuredProject.id) ?? [] : []}
                recentRuns={recentRuns}
                runningRuns={stats?.running_runs ?? 0}
                hasAgents={scopedAgents.length > 0}
                newProjectPath={newProjectPath}
                onNavigate={handleNavigate}
              />
            </div>
          </section>
        </div>
      </div>
  );
}

export default Dashboard;
