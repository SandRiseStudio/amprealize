/**
 * Raze telemetry helper (web console)
 *
 * Following `behavior_use_raze_for_logging` (Student):
 * - Use structured logs
 * - Include actor_surface
 * - Fail open (never break UX on telemetry failures)
 */

import { apiClient, ApiError } from '../api/client';

export type RazeLogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';

export interface RazeLogContext {
  [key: string]: unknown;
}

let razeIngestDisabled = false;

/**
 * Client-side perf breadcrumb. Records a `window.__perfMarks` entry and a
 * `performance.mark('perf:<name>')` so the Playwright harness (and devtools)
 * can read milestones without any server round-trip. Completely fire-and-
 * forget, never throws.
 */
interface PerfMarkEntry {
  name: string;
  t: number;
  epoch: number;
  context?: RazeLogContext;
}

declare global {
  interface Window {
    __perfMarks?: PerfMarkEntry[];
  }
}

export function perfMark(name: string, context: RazeLogContext = {}): void {
  try {
    if (typeof window === 'undefined') return;
    const t = typeof performance !== 'undefined' ? performance.now() : 0;
    const epoch = Date.now();
    if (!window.__perfMarks) {
      window.__perfMarks = [];
    }
    window.__perfMarks.push({ name, t, epoch, context });
    if (typeof performance !== 'undefined' && typeof performance.mark === 'function') {
      performance.mark(`perf:${name}`);
    }
  } catch {
    // Never let instrumentation break the page.
  }
}

// Opt-in toggle: set VITE_RAZE_LOG_ENABLED=false at build time OR
// localStorage['amprealize.razeIngest'] = 'off' at runtime to skip the
// /v1/logs/ingest POST and keep only the in-process perfMark path. Observed
// at 10 calls per board load (~4s each) when the ingest endpoint was slow
// under load.
const razeIngestEnvDisabled =
  typeof import.meta !== 'undefined' &&
  (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_RAZE_LOG_ENABLED === 'false';

function razeIngestRuntimeDisabled(): boolean {
  try {
    if (typeof window === 'undefined') return false;
    return window.localStorage?.getItem('amprealize.razeIngest') === 'off';
  } catch {
    return false;
  }
}

export async function razeLog(
  level: RazeLogLevel,
  message: string,
  context: RazeLogContext = {}
): Promise<void> {
  if (razeIngestDisabled || razeIngestEnvDisabled || razeIngestRuntimeDisabled()) return;

  try {
    await apiClient.post(
      '/v1/logs/ingest',
      {
        logs: [
          {
            level,
            message,
            service: 'web-console',
            actor_surface: 'web',
            context,
          },
        ],
      }
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      razeIngestDisabled = true;
      return;
    }
    if (import.meta.env.DEV) {
      // Keep local signal without spamming production console.
      console.debug('[Raze][ingest failed]', message, error);
    }
  }
}
