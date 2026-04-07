/**
 * Dashboard API hooks
 *
 * React Query hooks for fetching dashboard data with 30s polling.
 * Following COLLAB_SAAS_REQUIREMENTS.md for real-time updates (Phase 2 WebSocket planned).
 *
 * Following:
 * - behavior_design_api_contract (Teacher)
 * - behavior_use_raze_for_logging (Student)
 */

import { useQuery } from '@tanstack/react-query';
import { apiClient, ApiError } from './client';
import { getApiCapabilities } from './capabilities';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Organization {
  id: string;
  name: string;
  slug: string;
  description?: string;
  owner_id: string;
  created_at: string;
  updated_at: string;
  member_count?: number;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  description?: string;
  visibility: 'private' | 'internal' | 'public';
  settings?: Record<string, unknown>;
  org_id?: string;
  owner_id?: string;
  created_at: string;
  updated_at: string;
  agent_count?: number;
  run_count?: number;
}

export type AgentStatus = 'active' | 'busy' | 'idle' | 'paused' | 'disabled' | 'archived';

export interface Agent {
  id: string;
  name: string;
  agent_type: string;
  status: AgentStatus;
  description?: string;
  capabilities?: string[];
  config?: Record<string, unknown>;
  org_id?: string;
  owner_id?: string;
  project_id?: string;
  created_at: string;
  updated_at: string;
  last_active_at?: string;
}

// Status can come from backend as UPPERCASE or lowercase
export type RunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  | 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';

// Run interface matches backend Run dataclass from run_contracts.py
export interface Run {
  run_id: string;
  created_at: string;
  updated_at: string;
  actor: { id: string; role: string; surface: string };
  status: RunStatus;
  workflow_id?: string;
  workflow_name?: string;
  template_id?: string;
  template_name?: string;
  behavior_ids: string[];
  current_step?: string;
  progress_pct: number;
  message?: string;
  started_at?: string;
  completed_at?: string;
  duration_ms?: number;
  outputs: Record<string, unknown>;
  error?: string;
  metadata: Record<string, unknown>;
  steps: Array<{
    step_id: string;
    name: string;
    status: string;
    started_at?: string;
    completed_at?: string;
    duration_ms?: number;
    outputs?: Record<string, unknown>;
    error?: string;
  }>;
}

export interface Behavior {
  id: string;
  name: string;
  slug: string;
  instruction: string;
  status: 'active' | 'deprecated' | 'draft';
  tags?: string[];
  usage_count?: number;
  created_at: string;
  updated_at: string;
}

export interface DashboardStats {
  total_projects: number;
  total_agents: number;
  active_agents: number;
  busy_agents: number;
  total_runs: number;
  running_runs: number;
  completed_runs_today: number;
  failed_runs_today: number;
  total_behaviors: number;
  behavior_coverage_rate?: number;
}

// ---------------------------------------------------------------------------
// Query Keys
// ---------------------------------------------------------------------------

export const dashboardKeys = {
  all: ['dashboard'] as const,
  stats: () => [...dashboardKeys.all, 'stats'] as const,
  organizations: () => [...dashboardKeys.all, 'organizations'] as const,
  projects: (orgId?: string) => [...dashboardKeys.all, 'projects', orgId] as const,
  project: (projectId?: string) => [...dashboardKeys.all, 'project', projectId] as const,
  agents: (orgId?: string) => [...dashboardKeys.all, 'agents', orgId] as const,
  recentRuns: (limit: number) => [...dashboardKeys.all, 'runs', 'recent', limit] as const,
  behaviors: () => [...dashboardKeys.all, 'behaviors'] as const,
};

// ---------------------------------------------------------------------------
// Polling Configuration (30s per COLLAB_SAAS_REQUIREMENTS.md Phase 2)
// ---------------------------------------------------------------------------

const POLLING_INTERVAL = 30_000; // 30 seconds

// ---------------------------------------------------------------------------
// API Hooks
// ---------------------------------------------------------------------------

/**
 * Fetch dashboard statistics (aggregated counts)
 */
export function useDashboardStats() {
  return useQuery({
    queryKey: dashboardKeys.stats(),
    queryFn: async (): Promise<DashboardStats> => {
      try {
        // Try the dedicated stats endpoint first
        return await apiClient.get('/v1/dashboard/stats');
      } catch {
        // Fallback: construct stats from individual endpoints
        const [projectsRes, agentsRes, runsRes, behaviorsRes] = await Promise.allSettled([
          apiClient.get('/v1/projects'),
          apiClient.get('/v1/agents'),
          apiClient.get('/v1/runs?limit=100'),
          apiClient.get('/v1/behaviors'),
        ]);

        const projects = projectsRes.status === 'fulfilled'
          ? extractItems(projectsRes.value as ListResponse<Project> | Project[])
          : [];
        const agents = agentsRes.status === 'fulfilled'
          ? extractItems(agentsRes.value as ListResponse<Agent> | Agent[])
          : [];
        const runs = runsRes.status === 'fulfilled'
          ? extractItems(runsRes.value as ListResponse<Run> | Run[])
          : [];
        const behaviors = behaviorsRes.status === 'fulfilled'
          ? extractItems(behaviorsRes.value as ListResponse<Behavior> | Behavior[])
          : [];

        const today = new Date().toISOString().split('T')[0];
        const todaysRuns = runs.filter((r: Run) => r.started_at?.startsWith(today));

        return {
          total_projects: projects.length,
          total_agents: agents.length,
          active_agents: agents.filter((a: Agent) => a.status === 'active').length,
          busy_agents: agents.filter((a: Agent) => a.status === 'busy').length,
          total_runs: runs.length,
          running_runs: runs.filter((r: Run) => r.status === 'RUNNING').length,
          completed_runs_today: todaysRuns.filter((r: Run) => r.status === 'COMPLETED').length,
          failed_runs_today: todaysRuns.filter((r: Run) => r.status === 'FAILED').length,
          total_behaviors: behaviors.length,
        };
      }
    },
    refetchInterval: POLLING_INTERVAL,
    staleTime: POLLING_INTERVAL / 2,
  });
}

// Helper type for list API responses
interface ListResponse<T> {
  items?: T[];
}

// Helper to extract items from either array or {items: [...]} response
function extractItems<T>(response: ListResponse<T> | T[]): T[] {
  return Array.isArray(response) ? response : (response?.items ?? []);
}

/**
 * Fetch user's organizations
 */
export function useOrganizations() {
  return useQuery({
    queryKey: dashboardKeys.organizations(),
    queryFn: async (): Promise<Organization[]> => {
      const capabilities = await getApiCapabilities();
      if (!capabilities.routes.orgs) {
        return [];
      }
      const endpoints = ['/v1/orgs', '/v1/organizations'];
      for (const endpoint of endpoints) {
        try {
          // Orgs are optional for user-level login: if the org service is unavailable
          // (404) or protected differently (401/403), treat as "no orgs" without
          // triggering a global logout/refresh cycle.
          const response = await apiClient.get(endpoint, { skipRetry: true }) as
            | ListResponse<Organization>
            | Organization[];
          return extractItems(response);
        } catch (error) {
          if (error instanceof ApiError) {
            if (error.status === 404 || error.status === 401 || error.status === 403) {
              return [];
            }
            return [];
          }
        }
      }
      return [];
    },
    staleTime: 5 * 60 * 1000, // 5 minutes - orgs change rarely
  });
}

/**
 * Fetch projects (optionally filtered by organization)
 */
export function useProjects(orgId?: string) {
  return useQuery({
    queryKey: dashboardKeys.projects(orgId),
    queryFn: async (): Promise<Project[]> => {
      const endpoints = orgId
        ? [`/v1/projects?org_id=${encodeURIComponent(orgId)}`, `/v1/orgs/${orgId}/projects`, `/v1/organizations/${orgId}/projects`]
        : ['/v1/projects'];
      let lastError: unknown = null;
      for (const endpoint of endpoints) {
        try {
          const response = await apiClient.get(endpoint) as ListResponse<Project> | Project[];
          return extractItems(response);
        } catch (error) {
          if (error instanceof ApiError && error.status === 404) {
            continue;
          }
          lastError = error;
        }
      }
      if (lastError) {
        throw lastError;
      }
      return [];
    },
    refetchInterval: POLLING_INTERVAL,
    staleTime: POLLING_INTERVAL / 2,
  });
}

/**
 * Fetch a single project by ID
 */
export function useProject(projectId?: string) {
  return useQuery({
    queryKey: dashboardKeys.project(projectId),
    queryFn: async (): Promise<Project | null> => {
      if (!projectId) return null;
      try {
        const response = await apiClient.get<Project>(`/v1/projects/${projectId}`);
        return response;
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          return null;
        }
        throw error;
      }
    },
    enabled: Boolean(projectId),
    staleTime: POLLING_INTERVAL / 2,
  });
}

/**
 * Fetch recent runs
 */
export function useRecentRuns(limit = 10) {
  return useQuery({
    queryKey: dashboardKeys.recentRuns(limit),
    queryFn: async (): Promise<Run[]> => {
      try {
        const response = await apiClient.get(`/v1/runs?limit=${limit}&sort=-started_at`) as ListResponse<Run> | Run[];
        return extractItems(response);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          return [];
        }
        throw error;
      }
    },
    refetchInterval: POLLING_INTERVAL,
    staleTime: POLLING_INTERVAL / 2,
  });
}

/**
 * Fetch behaviors
 */
export function useBehaviors() {
  return useQuery({
    queryKey: dashboardKeys.behaviors(),
    queryFn: async (): Promise<Behavior[]> => {
      try {
        const response = await apiClient.get('/v1/behaviors') as ListResponse<Behavior> | Behavior[];
        return extractItems(response);
      } catch {
        return [];
      }
    },
    staleTime: 5 * 60 * 1000, // 5 minutes - behaviors change less frequently
  });
}
