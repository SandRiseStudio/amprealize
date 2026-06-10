export function formatDurationMs(durationMs?: number | null): string | null {
  if (durationMs == null || !Number.isFinite(durationMs)) return null;
  if (durationMs < 1000) return `${Math.round(durationMs)}ms`;
  return `${(durationMs / 1000).toFixed(1)}s`;
}

export function formatTokenTotal(inputTokens?: number | null, outputTokens?: number | null): string | null {
  const total = (inputTokens ?? 0) + (outputTokens ?? 0);
  return total > 0 ? `${total.toLocaleString()} tokens` : null;
}
