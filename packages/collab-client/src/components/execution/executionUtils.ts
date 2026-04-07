import type { ExecutionState } from '../../types.js';

const STATE_LABELS: Record<ExecutionState, string> = {
  pending: 'Pending',
  running: 'Running',
  paused: 'Paused',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
  unknown: 'Unknown',
};

export function normalizeExecutionState(state?: string | null): ExecutionState {
  if (!state) return 'unknown';
  const normalized = state.toLowerCase();
  if (
    normalized === 'pending' ||
    normalized === 'running' ||
    normalized === 'paused' ||
    normalized === 'completed' ||
    normalized === 'failed' ||
    normalized === 'cancelled'
  ) {
    return normalized;
  }
  return 'unknown';
}

export function formatExecutionStateLabel(state?: string | null): string {
  const normalized = normalizeExecutionState(state);
  return STATE_LABELS[normalized] ?? 'Unknown';
}

export function formatPhaseLabel(phase?: string | null): string {
  if (!phase) return 'No phase';
  const normalized = phase.replace(/_/g, ' ').trim().toLowerCase();
  if (!normalized) return 'No phase';
  return normalized
    .split(' ')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

export function clampProgress(progress?: number | null): number {
  if (typeof progress !== 'number' || Number.isNaN(progress)) return 0;
  if (progress < 0) return 0;
  if (progress > 100) return 100;
  return progress;
}

export function formatTimestamp(value?: string | null): string {
  if (!value) return 'Unknown';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Unknown';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function formatRelativeTime(value?: string | null): string {
  if (!value) return 'Unknown';
  const date = new Date(value);
  const ts = date.getTime();
  if (Number.isNaN(ts)) return 'Unknown';
  const now = Date.now();
  const diffMs = now - ts;
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 20) return 'just now';
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

export function formatDuration(startedAt?: string | null, completedAt?: string | null): string {
  if (!startedAt || !completedAt) return '';
  const start = new Date(startedAt).getTime();
  const end = new Date(completedAt).getTime();
  if (Number.isNaN(start) || Number.isNaN(end)) return '';
  const durationMs = Math.max(end - start, 0);
  const seconds = Math.floor(durationMs / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h`;
}
