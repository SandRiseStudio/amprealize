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

export async function razeLog(
  level: RazeLogLevel,
  message: string,
  context: RazeLogContext = {}
): Promise<void> {
  if (razeIngestDisabled) return;

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
