import { describe, expect, it } from 'vitest';
import {
  buildExecutionControlModel,
  isActiveExecutionState,
  normalizeExecutionControlState,
} from '../lib/executionControls';

describe('executionControls', () => {
  it('normalizes board and chat execution states consistently', () => {
    expect(normalizeExecutionControlState('queued')).toBe('queued');
    expect(normalizeExecutionControlState('running')).toBe('running');
    expect(normalizeExecutionControlState('paused')).toBe('paused');
    expect(normalizeExecutionControlState('canceled')).toBe('cancelled');
    expect(normalizeExecutionControlState('running', 1)).toBe('needs_clarification');
  });

  it('treats pending, queued, running, paused, and clarification states as active', () => {
    expect(isActiveExecutionState('pending')).toBe(true);
    expect(isActiveExecutionState('queued')).toBe(true);
    expect(isActiveExecutionState('running')).toBe(true);
    expect(isActiveExecutionState('paused')).toBe(true);
    expect(isActiveExecutionState('needs_clarification')).toBe(true);
    expect(isActiveExecutionState('completed')).toBe(false);
  });

  it('gates start and cancel controls from the shared execution model', () => {
    const ready = buildExecutionControlModel({ hasAgentAssignment: true });
    expect(ready.summary).toBe('Ready to run');
    expect(ready.canStart).toBe(true);
    expect(ready.canCancel).toBe(false);

    const running = buildExecutionControlModel({
      rawState: 'running',
      hasExecution: true,
      hasAgentAssignment: true,
    });
    expect(running.summary).toBe('Running now');
    expect(running.canStart).toBe(false);
    expect(running.canCancel).toBe(true);

    const missingAgent = buildExecutionControlModel({
      hasAgentAssignment: true,
      isOrphanedAssignment: true,
    });
    expect(missingAgent.summary).toBe('Assigned agent is missing');
    expect(missingAgent.canStart).toBe(false);
    expect(missingAgent.startTitle).toContain('Assigned agent no longer exists');
  });
});
