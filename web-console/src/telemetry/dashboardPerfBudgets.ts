/**
 * Console performance budgets (guideai-1145).
 *
 * Values are targets for warning-level telemetry, not hard SLAs — local dev
 * and cold caches may exceed them.
 */

export const DASHBOARD_PERF_BUDGETS_MS = {
  /** Route/navigation start → project grid ready (`dashboard.chrome_ready`) */
  chromeReady: 2_500,
  /** Same scope: bootstrap finished → secondary queries enabled */
  bootstrapSettled: 2_000,
  /** Agent strip interactive (`dashboard.agent_panel_ready`) */
  agentPanel: 4_000,
} as const;

export type DashboardPerfBudgetKey = keyof typeof DASHBOARD_PERF_BUDGETS_MS;

export function budgetCheck(
  key: DashboardPerfBudgetKey,
  elapsedMs: number
): { ok: boolean; budget_ms: number; over_by_ms: number } {
  const budget_ms = DASHBOARD_PERF_BUDGETS_MS[key];
  const over_by_ms = Math.max(0, elapsedMs - budget_ms);
  return { ok: over_by_ms === 0, budget_ms, over_by_ms };
}
