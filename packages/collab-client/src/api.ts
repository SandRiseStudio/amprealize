/**
 * Amprealize Collaboration REST API Client
 *
 * For CRUD operations on workspaces and documents (non-realtime).
 * Use CollabClient for real-time WebSocket collaboration.
 */

import type {
  CreateDocumentRequest,
  CreateWorkspaceRequest,
  Document,
  DocumentId,
  EditOperation,
  GitHubBranchListResponse,
  GitHubRepoValidationRequest,
  GitHubRepoValidationResponse,
  ProjectSettings,
  UpdateProjectSettingsRequest,
  Workspace,
  WorkspaceId,
} from './types.js';

export interface CollabApiConfig {
  /** REST API base URL (e.g., http://localhost:8080) */
  baseUrl: string;
  /** Optional auth token */
  authToken?: string;
  /** Custom fetch implementation (for testing or environments without native fetch) */
  fetch?: typeof fetch;
}

export class CollabApi {
  private config: CollabApiConfig;
  private fetch: typeof fetch;

  constructor(config: CollabApiConfig) {
    this.config = config;
    this.fetch = config.fetch ?? globalThis.fetch.bind(globalThis);
  }

  // ---------------------------------------------------------------------------
  // Workspaces
  // ---------------------------------------------------------------------------

  async createWorkspace(request: CreateWorkspaceRequest): Promise<Workspace> {
    return this.post<Workspace>('/v1/collaboration/workspaces', request);
  }

  async getWorkspace(workspaceId: WorkspaceId): Promise<Workspace> {
    return this.get<Workspace>(`/v1/collaboration/workspaces/${workspaceId}`);
  }

  async listDocuments(workspaceId: WorkspaceId): Promise<Document[]> {
    return this.get<Document[]>(`/v1/collaboration/workspaces/${workspaceId}/documents`);
  }

  // ---------------------------------------------------------------------------
  // Documents
  // ---------------------------------------------------------------------------

  async createDocument(request: CreateDocumentRequest): Promise<Document> {
    return this.post<Document>('/v1/collaboration/documents', request);
  }

  async getDocument(documentId: DocumentId): Promise<Document> {
    return this.get<Document>(`/v1/collaboration/documents/${documentId}`);
  }

  async getDocumentOperations(documentId: DocumentId, limit = 100): Promise<EditOperation[]> {
    return this.get<EditOperation[]>(`/v1/collaboration/documents/${documentId}/operations?limit=${limit}`);
  }

  // ---------------------------------------------------------------------------
  // Project Settings
  // ---------------------------------------------------------------------------

  async getProjectSettings(projectId: string): Promise<ProjectSettings> {
    return this.get<ProjectSettings>(`/v1/projects/${projectId}/settings`);
  }

  async updateProjectSettings(
    projectId: string,
    settings: UpdateProjectSettingsRequest
  ): Promise<ProjectSettings> {
    return this.patch<ProjectSettings>(`/v1/projects/${projectId}/settings`, settings);
  }

  async setProjectRepository(
    projectId: string,
    repositoryUrl: string,
    defaultBranch = 'main'
  ): Promise<ProjectSettings> {
    return this.put<ProjectSettings>(`/v1/projects/${projectId}/settings/repository`, {
      repository_url: repositoryUrl,
      default_branch: defaultBranch,
    });
  }

  // ---------------------------------------------------------------------------
  // GitHub Integration
  // ---------------------------------------------------------------------------

  async validateGitHubRepository(
    projectId: string,
    request: GitHubRepoValidationRequest
  ): Promise<GitHubRepoValidationResponse> {
    return this.post<GitHubRepoValidationResponse>(
      `/v1/projects/${projectId}/settings/repository/validate`,
      request
    );
  }

  async listGitHubBranches(
    projectId: string,
    page = 1,
    perPage = 30
  ): Promise<GitHubBranchListResponse> {
    return this.get<GitHubBranchListResponse>(
      `/v1/projects/${projectId}/settings/repository/branches?page=${page}&per_page=${perPage}`
    );
  }

  // ---------------------------------------------------------------------------
  // HTTP Helpers
  // ---------------------------------------------------------------------------

  private async get<T>(path: string): Promise<T> {
    const response = await this.fetch(`${this.config.baseUrl}${path}`, {
      method: 'GET',
      headers: this.headers(),
    });
    return this.handleResponse<T>(response);
  }

  private async post<T>(path: string, body: unknown): Promise<T> {
    const response = await this.fetch(`${this.config.baseUrl}${path}`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify(body),
    });
    return this.handleResponse<T>(response);
  }

  private async patch<T>(path: string, body: unknown): Promise<T> {
    const response = await this.fetch(`${this.config.baseUrl}${path}`, {
      method: 'PATCH',
      headers: this.headers(),
      body: JSON.stringify(body),
    });
    return this.handleResponse<T>(response);
  }

  private async put<T>(path: string, body: unknown): Promise<T> {
    const response = await this.fetch(`${this.config.baseUrl}${path}`, {
      method: 'PUT',
      headers: this.headers(),
      body: JSON.stringify(body),
    });
    return this.handleResponse<T>(response);
  }

  private headers(): HeadersInit {
    const h: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    };
    if (this.config.authToken) {
      h['Authorization'] = `Bearer ${this.config.authToken}`;
    }
    return h;
  }

  private async handleResponse<T>(response: Response): Promise<T> {
    if (!response.ok) {
      const text = await response.text();
      let detail = text;
      try {
        const json = JSON.parse(text);
        detail = json.detail ?? json.message ?? text;
      } catch {
        // Use raw text
      }
      throw new CollabApiError(response.status, detail);
    }
    return response.json() as Promise<T>;
  }
}

export class CollabApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string
  ) {
    super(`CollabApi error ${status}: ${detail}`);
    this.name = 'CollabApiError';
  }
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export function createCollabApi(config: CollabApiConfig): CollabApi {
  return new CollabApi(config);
}
