/**
 * API client for the Amprealize backend
 *
 * Features:
 * - Automatic 401 handling with token refresh
 * - Request queue during refresh to avoid duplicate refreshes
 * - Retry failed requests after successful refresh
 * - Custom headers support for specific requests
 *
 * Following:
 * - behavior_design_api_contract (Teacher)
 * - behavior_lock_down_security_surface (Student)
 */

import { STORAGE_KEYS } from '../config/storageKeys';

const RAW_API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080').replace(/\/+$/, '');

// Base origin of the backend without the "/api" prefix. Useful for fetching non-API endpoints like /openapi.json.
export const API_ORIGIN = RAW_API_BASE_URL.endsWith('/api') ? RAW_API_BASE_URL.slice(0, -4) : RAW_API_BASE_URL;

// `VITE_API_BASE_URL` is allowed to be either:
// - "http://localhost:8080"        (host only, via gateway)
// - "http://localhost:8080/api"    (includes API prefix)
// Normalize to always include a single trailing "/api".
const API_BASE = RAW_API_BASE_URL.endsWith('/api') ? RAW_API_BASE_URL : `${RAW_API_BASE_URL}/api`;

const TOKEN_STORAGE_KEY = STORAGE_KEYS.accessToken;
const REFRESH_TOKEN_STORAGE_KEY = STORAGE_KEYS.refreshToken;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RequestOptions {
  headers?: Record<string, string>;
  skipAuth?: boolean;
  skipRetry?: boolean;
  timeoutMs?: number;
  body?: unknown; // For DELETE requests that need a body
}

const DEFAULT_REQUEST_TIMEOUT_MS = 15_000;

interface QueuedRequest {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  retry: () => Promise<unknown>;
}

// ---------------------------------------------------------------------------
// API Error Class
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  status: number;
  code?: string;
  details?: unknown;

  constructor(status: number, message: string, code?: string, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }

  static fromResponse(status: number, body: string): ApiError {
    try {
      const parsed = JSON.parse(body);
      // Handle FastAPI HTTPException format where detail can be a string or object
      const detail = parsed.detail;
      if (typeof detail === 'object' && detail !== null) {
        // FastAPI HTTPException with dict detail (e.g., OAuth errors)
        return new ApiError(
          status,
          detail.error_description || detail.message || detail.error || body,
          detail.error || detail.code,
          detail
        );
      }
      return new ApiError(
        status,
        detail || parsed.message || parsed.error || body,
        parsed.code,
        parsed.details
      );
    } catch {
      return new ApiError(status, body);
    }
  }
}

// ---------------------------------------------------------------------------
// API Client Class
// ---------------------------------------------------------------------------

class ApiClient {
  private token: string | null = null;
  private refreshToken: string | null = null;
  private isRefreshing = false;
  private refreshQueue: QueuedRequest[] = [];
  private onUnauthorized: (() => void) | null = null;

  constructor() {
    // Load tokens from storage on init
    this.token = localStorage.getItem(TOKEN_STORAGE_KEY);
    this.refreshToken = localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY);
  }

  // ---------------------------------------------------------------------------
  // Token Management
  // ---------------------------------------------------------------------------

  setToken(token: string | null): void {
    this.token = token;
    if (token) {
      localStorage.setItem(TOKEN_STORAGE_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  }

  setRefreshToken(refreshToken: string | null): void {
    this.refreshToken = refreshToken;
    if (refreshToken) {
      localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, refreshToken);
    } else {
      localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
    }
  }

  getToken(): string | null {
    if (this.token) return this.token;
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  }

  hasToken(): boolean {
    return Boolean(this.getToken());
  }

  getRefreshToken(): string | null {
    if (this.refreshToken) return this.refreshToken;
    return localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY);
  }

  clearTokens(): void {
    this.token = null;
    this.refreshToken = null;
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
  }

  /**
   * Register callback for when authentication fails completely
   * (after refresh attempt)
   */
  setOnUnauthorized(callback: (() => void) | null): void {
    this.onUnauthorized = callback;
  }

  // ---------------------------------------------------------------------------
  // Headers
  // ---------------------------------------------------------------------------

  private getHeaders(options?: RequestOptions): HeadersInit {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...options?.headers,
    };

    if (!options?.skipAuth) {
      const token = this.getToken();
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }
    }

    return headers;
  }

  // ---------------------------------------------------------------------------
  // Token Refresh Logic
  // ---------------------------------------------------------------------------

  private async refreshAccessToken(): Promise<boolean> {
    const refresh = this.getRefreshToken();
    if (!refresh) {
      return false;
    }

    try {
      // Prefer modern refresh endpoint; fall back to device-flow refresh for older backends.
      const endpoints = ['/v1/auth/token/refresh', '/v1/auth/device/refresh'];
      for (const endpoint of endpoints) {
        const response = await fetch(`${API_BASE}${endpoint}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refresh }),
        });

        if (response.status === 404) {
          continue;
        }
        if (!response.ok) {
          return false;
        }

        const data = await response.json();
        if (data?.access_token) {
          this.setToken(data.access_token);
        }
        if (data?.refresh_token) {
          this.setRefreshToken(data.refresh_token);
        }
        return true;
      }

      return false;
    } catch (error) {
      console.error('[ApiClient] Token refresh failed:', error);
      return false;
    }
  }

  private async handleUnauthorized<T>(
    retryFn: () => Promise<T>,
    options?: RequestOptions
  ): Promise<T> {
    // If skipRetry is set, don't attempt refresh
    if (options?.skipRetry) {
      throw new ApiError(401, 'Unauthorized');
    }

    // If already refreshing, queue this request
    if (this.isRefreshing) {
      return new Promise((resolve, reject) => {
        this.refreshQueue.push({
          resolve: resolve as (value: unknown) => void,
          reject,
          retry: retryFn,
        });
      });
    }

    this.isRefreshing = true;

    try {
      const refreshed = await this.refreshAccessToken();

      if (refreshed) {
        // Retry the original request
        const result = await retryFn();

        // Process queued requests
        this.refreshQueue.forEach((queued) => {
          queued.retry().then(queued.resolve).catch(queued.reject);
        });
        this.refreshQueue = [];

        return result;
      } else {
        // Refresh failed, clear tokens and notify
        this.clearTokens();
        this.onUnauthorized?.();

        // Reject all queued requests
        const error = new ApiError(401, 'Session expired');
        this.refreshQueue.forEach((queued) => {
          queued.reject(error);
        });
        this.refreshQueue = [];

        throw error;
      }
    } finally {
      this.isRefreshing = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Request Methods
  // ---------------------------------------------------------------------------

  async get<T>(path: string, options?: RequestOptions): Promise<T> {
    const doRequest = async (): Promise<T> => {
      const controller = new AbortController();
      const timeoutMs = options?.timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS;
      const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

      const response = await fetch(`${API_BASE}${path}`, {
        method: 'GET',
        headers: this.getHeaders(options),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (response.status === 401 && !options?.skipAuth) {
        return this.handleUnauthorized(() => this.get<T>(path, { ...options, skipRetry: true }), options);
      }

      if (!response.ok) {
        throw ApiError.fromResponse(response.status, await response.text());
      }

      return response.json();
    };

    try {
      return await doRequest();
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new ApiError(0, 'Request timed out', 'timeout');
      }
      throw error;
    }
  }

  async post<T>(path: string, body: unknown, options?: RequestOptions): Promise<T> {
    const doRequest = async (): Promise<T> => {
      const controller = new AbortController();
      const timeoutMs = options?.timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS;
      const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

      const response = await fetch(`${API_BASE}${path}`, {
        method: 'POST',
        headers: this.getHeaders(options),
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (response.status === 401 && !options?.skipAuth) {
        return this.handleUnauthorized(
          () => this.post<T>(path, body, { ...options, skipRetry: true }),
          options
        );
      }

      if (!response.ok) {
        throw ApiError.fromResponse(response.status, await response.text());
      }

      // Handle empty responses
      const text = await response.text();
      if (!text) {
        return {} as T;
      }
      return JSON.parse(text);
    };

    try {
      return await doRequest();
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new ApiError(0, 'Request timed out', 'timeout');
      }
      throw error;
    }
  }

  async put<T>(path: string, body: unknown, options?: RequestOptions): Promise<T> {
    const doRequest = async (): Promise<T> => {
      const controller = new AbortController();
      const timeoutMs = options?.timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS;
      const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

      const response = await fetch(`${API_BASE}${path}`, {
        method: 'PUT',
        headers: this.getHeaders(options),
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (response.status === 401 && !options?.skipAuth) {
        return this.handleUnauthorized(
          () => this.put<T>(path, body, { ...options, skipRetry: true }),
          options
        );
      }

      if (!response.ok) {
        throw ApiError.fromResponse(response.status, await response.text());
      }

      const text = await response.text();
      if (!text) {
        return {} as T;
      }
      return JSON.parse(text);
    };

    try {
      return await doRequest();
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new ApiError(0, 'Request timed out', 'timeout');
      }
      throw error;
    }
  }

  async patch<T>(path: string, body: unknown, options?: RequestOptions): Promise<T> {
    const doRequest = async (): Promise<T> => {
      const controller = new AbortController();
      const timeoutMs = options?.timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS;
      const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

      const response = await fetch(`${API_BASE}${path}`, {
        method: 'PATCH',
        headers: this.getHeaders(options),
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (response.status === 401 && !options?.skipAuth) {
        return this.handleUnauthorized(
          () => this.patch<T>(path, body, { ...options, skipRetry: true }),
          options
        );
      }

      if (!response.ok) {
        throw ApiError.fromResponse(response.status, await response.text());
      }

      const text = await response.text();
      if (!text) {
        return {} as T;
      }
      return JSON.parse(text);
    };

    try {
      return await doRequest();
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new ApiError(0, 'Request timed out', 'timeout');
      }
      throw error;
    }
  }

  async delete<T = void>(path: string, options?: RequestOptions): Promise<T> {
    const doRequest = async (): Promise<T> => {
      const fetchOptions: RequestInit = {
        method: 'DELETE',
        headers: this.getHeaders(options),
      };

      // Support body in DELETE requests (e.g., for MFA device deletion)
      if (options?.body) {
        fetchOptions.body = JSON.stringify(options.body);
      }

      const response = await fetch(`${API_BASE}${path}`, fetchOptions);

      if (response.status === 401 && !options?.skipAuth) {
        return this.handleUnauthorized(
          () => this.delete<T>(path, { ...options, skipRetry: true }),
          options
        );
      }

      if (!response.ok) {
        throw ApiError.fromResponse(response.status, await response.text());
      }

      const text = await response.text();
      if (!text) {
        return {} as T;
      }
      return JSON.parse(text);
    };

    return doRequest();
  }
}

// ---------------------------------------------------------------------------
// Singleton Export
// ---------------------------------------------------------------------------

export const apiClient = new ApiClient();
