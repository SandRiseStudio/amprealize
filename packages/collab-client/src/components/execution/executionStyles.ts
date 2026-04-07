const EXECUTION_STYLE_ID = 'ga-execution-ui-styles';

const EXECUTION_STYLES = `
.ga-exec-panel {
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(12px);
  border-radius: var(--radius-2xl);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.ga-exec-panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.ga-exec-panel-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.ga-exec-panel-title {
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--color-text-primary);
}

.ga-exec-panel-subtitle {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  margin-top: var(--space-1);
}

.ga-exec-status-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.ga-exec-status-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  border-radius: var(--radius-full);
  padding: 2px var(--space-2);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  border: 1px solid rgba(15, 23, 42, 0.1);
  background: rgba(15, 23, 42, 0.04);
  color: var(--color-text-secondary);
}

.ga-exec-status-dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  background: var(--color-text-tertiary);
}

.ga-exec-status-badge.ga-exec-running {
  border-color: rgba(34, 197, 94, 0.35);
  background: rgba(34, 197, 94, 0.12);
  color: var(--color-text-primary);
}

.ga-exec-status-badge.ga-exec-running .ga-exec-status-dot {
  background: var(--color-success);
  animation: ga-exec-pulse 2s ease-in-out infinite;
}

.ga-exec-status-badge.ga-exec-paused {
  border-color: rgba(245, 158, 11, 0.35);
  background: rgba(245, 158, 11, 0.12);
  color: var(--color-text-primary);
}

.ga-exec-status-badge.ga-exec-paused .ga-exec-status-dot {
  background: var(--color-warning);
}

.ga-exec-status-badge.ga-exec-failed,
.ga-exec-status-badge.ga-exec-cancelled {
  border-color: rgba(239, 68, 68, 0.28);
  background: rgba(239, 68, 68, 0.12);
  color: var(--color-text-primary);
}

.ga-exec-status-badge.ga-exec-failed .ga-exec-status-dot,
.ga-exec-status-badge.ga-exec-cancelled .ga-exec-status-dot {
  background: var(--color-error);
}

.ga-exec-status-badge.ga-exec-completed {
  border-color: rgba(59, 130, 246, 0.25);
  background: rgba(59, 130, 246, 0.12);
  color: var(--color-text-primary);
}

.ga-exec-status-badge.ga-exec-completed .ga-exec-status-dot {
  background: var(--color-accent);
}

.ga-exec-status-badge.ga-exec-pending {
  border-color: rgba(14, 165, 233, 0.28);
  background: rgba(14, 165, 233, 0.12);
  color: var(--color-text-primary);
}

.ga-exec-status-badge.ga-exec-pending .ga-exec-status-dot {
  background: #0ea5e9;
}

.ga-exec-phase-pill {
  display: inline-flex;
  align-items: center;
  border-radius: var(--radius-full);
  padding: 2px var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(255, 255, 255, 0.7);
}

.ga-exec-progress {
  width: 100%;
  height: 6px;
  border-radius: var(--radius-full);
  background: rgba(15, 23, 42, 0.08);
  overflow: hidden;
}

.ga-exec-progress-fill {
  height: 100%;
  border-radius: var(--radius-full);
  background: rgba(59, 130, 246, 0.75);
  transition: transform var(--duration-normal) var(--ease-out-expo);
  transform-origin: left center;
}

.ga-exec-progress-fill.ga-exec-progress-running {
  background: rgba(34, 197, 94, 0.75);
}

.ga-exec-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--space-2);
}

.ga-exec-meta-item {
  border-radius: var(--radius-lg);
  border: 1px solid rgba(15, 23, 42, 0.08);
  padding: var(--space-2) var(--space-3);
  background: rgba(255, 255, 255, 0.7);
}

.ga-exec-meta-label {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.ga-exec-meta-value {
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  font-weight: var(--font-medium);
}

.ga-exec-current-step {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
}

.ga-exec-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.ga-exec-empty {
  border-radius: var(--radius-xl);
  border: 1px dashed rgba(15, 23, 42, 0.12);
  padding: var(--space-4);
  color: var(--color-text-tertiary);
  background: rgba(255, 255, 255, 0.6);
}

.ga-exec-timeline {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.ga-exec-filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.ga-exec-filter-select {
  border-radius: var(--radius-lg);
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: rgba(255, 255, 255, 0.85);
  padding: 4px var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.ga-exec-phase-group {
  border-radius: var(--radius-xl);
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(255, 255, 255, 0.75);
  overflow: hidden;
}

.ga-exec-phase-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-3);
  background: rgba(59, 130, 246, 0.06);
  cursor: pointer;
}

.ga-exec-phase-title {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--color-text-primary);
}

.ga-exec-phase-meta {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.ga-exec-step-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
}

.ga-exec-step {
  display: grid;
  grid-template-columns: 12px 1fr;
  gap: var(--space-2);
}

.ga-exec-step-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: rgba(59, 130, 246, 0.6);
  margin-top: 6px;
}

.ga-exec-step[data-step-type='error'] .ga-exec-step-dot {
  background: var(--color-error);
}

.ga-exec-step[data-step-type='clarification_sent'] .ga-exec-step-dot,
.ga-exec-step[data-step-type='clarification_received'] .ga-exec-step-dot {
  background: var(--color-warning);
}

.ga-exec-step[data-step-type='tool_call'] .ga-exec-step-dot,
.ga-exec-step[data-step-type='tool_result'] .ga-exec-step-dot {
  background: rgba(14, 165, 233, 0.7);
}

.ga-exec-step-card {
  border-radius: var(--radius-lg);
  border: 1px solid rgba(15, 23, 42, 0.08);
  padding: var(--space-2) var(--space-3);
  background: rgba(255, 255, 255, 0.85);
}

.ga-exec-step-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  justify-content: space-between;
}

.ga-exec-step-type {
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--color-text-primary);
}

.ga-exec-step-time {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.ga-exec-step-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  margin-top: 2px;
}

.ga-exec-step-preview {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin-top: var(--space-2);
  line-height: var(--leading-relaxed);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

@keyframes ga-exec-pulse {
  0% { transform: scale(1); opacity: 0.7; }
  50% { transform: scale(1.3); opacity: 0.3; }
  100% { transform: scale(1); opacity: 0.7; }
}

@media (max-width: 900px) {
  .ga-exec-panel {
    padding: var(--space-3);
  }

  .ga-exec-meta {
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  }
}
`;

export function ensureExecutionStyles(): void {
  if (typeof document === 'undefined') return;
  if (document.getElementById(EXECUTION_STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = EXECUTION_STYLE_ID;
  style.textContent = EXECUTION_STYLES;
  document.head.appendChild(style);
}

export { EXECUTION_STYLE_ID };
