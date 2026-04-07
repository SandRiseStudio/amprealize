import React, { useEffect, useMemo, useState } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ExecutionStep } from '../../types.js';
import { ensureExecutionStyles } from './executionStyles.js';
import { formatDuration, formatPhaseLabel, formatTimestamp } from './executionUtils.js';

const STEP_LABELS: Record<string, string> = {
  phase_start: 'Phase start',
  phase_end: 'Phase end',
  phase_transition: 'Phase transition',
  llm_request: 'LLM request',
  llm_response: 'LLM response',
  tool_call: 'Tool call',
  tool_result: 'Tool result',
  clarification_sent: 'Clarification sent',
  clarification_received: 'Clarification received',
  file_change: 'File change',
  pr_created: 'PR created',
  error: 'Error',
  gate_waiting: 'Gate waiting',
  gate_approved: 'Gate approved',
  model_switch: 'Model switch',
};

function formatStepLabel(stepType: string): string {
  if (!stepType) return 'Step';
  return STEP_LABELS[stepType] ?? stepType.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Detect whether text contains markdown formatting worth rendering.
 * Checks for markdown headers, tables, or a density of markdown syntax.
 */
function isMarkdownContent(text: string): boolean {
  // Quick checks for common markdown indicators
  const hasHeaders = /^#{1,3}\s/m.test(text);
  const hasTables = /\|.+\|.+\|/m.test(text);
  const hasBold = /\*\*.+\*\*/m.test(text);
  const hasLists = /^[-*]\s/m.test(text);
  const indicators = [hasHeaders, hasTables, hasBold, hasLists].filter(Boolean).length;
  return indicators >= 2 || hasHeaders;
}

interface ParsedStepContent {
  text?: string;
  toolName?: string;
  inputs?: Record<string, unknown>;
  output?: unknown;
  success?: boolean;
  error?: string;
  raw: string;
}

function parseStepContent(contentFull?: string | null): ParsedStepContent | null {
  if (!contentFull) return null;
  try {
    const parsed = JSON.parse(contentFull) as Record<string, unknown>;
    return {
      text: typeof parsed.text === 'string' ? parsed.text : undefined,
      toolName: typeof parsed.tool_name === 'string' ? parsed.tool_name : undefined,
      inputs: typeof parsed.inputs === 'object' && parsed.inputs !== null ? parsed.inputs as Record<string, unknown> : undefined,
      output: parsed.output,
      success: typeof parsed.success === 'boolean' ? parsed.success : undefined,
      error: typeof parsed.error === 'string' ? parsed.error : undefined,
      raw: contentFull,
    };
  } catch {
    return { raw: contentFull };
  }
}

interface PhaseGroup {
  phase: string;
  steps: ExecutionStep[];
}

export interface ExecutionTimelineProps {
  steps?: ExecutionStep[];
  activePhase?: string | null;
  isLoading?: boolean;
  emptyLabel?: string;
  className?: string;
}

export function ExecutionTimeline({
  steps = [],
  activePhase,
  isLoading = false,
  emptyLabel = 'No execution steps yet.',
  className,
}: ExecutionTimelineProps): React.JSX.Element {
  useEffect(() => {
    ensureExecutionStyles();
  }, []);

  const phases = useMemo<PhaseGroup[]>(() => {
    const order: string[] = [];
    const buckets = new Map<string, ExecutionStep[]>();
    steps.forEach((step) => {
      const phase = step.phase || 'Unknown';
      if (!buckets.has(phase)) {
        buckets.set(phase, []);
        order.push(phase);
      }
      buckets.get(phase)?.push(step);
    });
    return order.map((phase) => ({ phase, steps: buckets.get(phase) ?? [] }));
  }, [steps]);

  const phaseOptions = useMemo(() => ['all', ...new Set(phases.map((group) => group.phase))], [phases]);
  const stepTypeOptions = useMemo(() => {
    const unique = new Set(steps.map((step) => step.stepType).filter(Boolean));
    return ['all', ...Array.from(unique)];
  }, [steps]);

  const [phaseFilter, setPhaseFilter] = useState('all');
  const [stepTypeFilter, setStepTypeFilter] = useState('all');
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [expandedSteps, setExpandedSteps] = useState<Record<string, boolean>>({});

  const toggleStepExpand = (stepId: string) => {
    setExpandedSteps((prev) => ({
      ...prev,
      [stepId]: !prev[stepId],
    }));
  };

  const filteredPhases = useMemo(() => {
    return phases
      .filter((group) => phaseFilter === 'all' || group.phase === phaseFilter)
      .map((group) => ({
        ...group,
        steps: group.steps.filter(
          (step) => stepTypeFilter === 'all' || step.stepType === stepTypeFilter
        ),
      }))
      .filter((group) => group.steps.length > 0);
  }, [phaseFilter, phases, stepTypeFilter]);

  const togglePhase = (phase: string) => {
    setCollapsed((prev) => ({
      ...prev,
      [phase]: !prev[phase],
    }));
  };

  if (isLoading) {
    return (
      <div className={`ga-exec-panel ${className ?? ''}`.trim()} aria-label="Loading execution timeline">
        <div className="ga-exec-empty">Loading execution timeline...</div>
      </div>
    );
  }

  if (!steps.length) {
    return (
      <div className={`ga-exec-panel ${className ?? ''}`.trim()} aria-label="Execution timeline">
        <div className="ga-exec-empty">{emptyLabel}</div>
      </div>
    );
  }

  return (
    <div className={`ga-exec-timeline ${className ?? ''}`.trim()}>
      <div className="ga-exec-filter-row">
        <select
          className="ga-exec-filter-select"
          value={phaseFilter}
          onChange={(event) => setPhaseFilter(event.target.value)}
          aria-label="Filter by phase"
        >
          {phaseOptions.map((phase) => (
            <option key={phase} value={phase}>
              {phase === 'all' ? 'All phases' : formatPhaseLabel(phase)}
            </option>
          ))}
        </select>
        <select
          className="ga-exec-filter-select"
          value={stepTypeFilter}
          onChange={(event) => setStepTypeFilter(event.target.value)}
          aria-label="Filter by step type"
        >
          {stepTypeOptions.map((stepType) => (
            <option key={stepType} value={stepType}>
              {stepType === 'all' ? 'All step types' : formatStepLabel(stepType)}
            </option>
          ))}
        </select>
      </div>

      {filteredPhases.map((group) => {
        const isCollapsed = collapsed[group.phase] && group.phase !== activePhase;
        const phaseId = `phase-${group.phase.replace(/[^a-z0-9-]/gi, '-')}`;
        return (
          <div key={group.phase} className="ga-exec-phase-group">
            <button
              type="button"
              className="ga-exec-phase-header"
              onClick={() => togglePhase(group.phase)}
              aria-expanded={!isCollapsed}
              aria-controls={phaseId}
            >
              <span className="ga-exec-phase-title">{formatPhaseLabel(group.phase)}</span>
              <span className="ga-exec-phase-meta">
                {group.steps.length} steps
                {group.phase === activePhase ? ' (active)' : ''}
              </span>
            </button>
            {!isCollapsed && (
              <div id={phaseId} className="ga-exec-step-list">
                {group.steps.map((step) => {
                  const isExpanded = expandedSteps[step.stepId];
                  const parsedContent = parseStepContent(step.contentFull);
                  const hasDetail = !!step.contentFull;

                  return (
                    <div key={step.stepId} className="ga-exec-step" data-step-type={step.stepType}>
                      <span className="ga-exec-step-dot" aria-hidden="true" />
                      <div className="ga-exec-step-card">
                        <button
                          type="button"
                          className="ga-exec-step-header"
                          onClick={() => hasDetail && toggleStepExpand(step.stepId)}
                          style={{ cursor: hasDetail ? 'pointer' : 'default', width: '100%', background: 'none', border: 'none', textAlign: 'left', padding: 0 }}
                          aria-expanded={isExpanded}
                          disabled={!hasDetail}
                        >
                          <span className="ga-exec-step-type">
                            {formatStepLabel(step.stepType)}
                            {hasDetail && <span style={{ marginLeft: '4px', opacity: 0.6 }}>{isExpanded ? '▼' : '▶'}</span>}
                          </span>
                          <span className="ga-exec-step-time">
                            {formatTimestamp(step.startedAt)}
                            {formatDuration(step.startedAt, step.completedAt)
                              ? ` · ${formatDuration(step.startedAt, step.completedAt)}`
                              : ''}
                          </span>
                        </button>
                        <div className="ga-exec-step-meta">
                          <span>Input {step.inputTokens ?? 0} tokens</span>
                          <span>Output {step.outputTokens ?? 0} tokens</span>
                          {step.toolCalls ? <span>Tool calls {step.toolCalls}</span> : null}
                          {step.modelId && <span>Model: {step.modelId}</span>}
                        </div>

                        {/* Show preview when collapsed */}
                        {!isExpanded && step.contentPreview && (
                          <div className="ga-exec-step-preview">{step.contentPreview}</div>
                        )}

                        {/* Show full detail when expanded */}
                        {isExpanded && parsedContent && (
                          <div className="ga-exec-step-detail" style={{ marginTop: '8px', fontSize: '13px' }}>
                            {/* LLM Response text / Research report */}
                            {parsedContent.text && (
                              <div style={{ marginBottom: '8px' }}>
                                <strong>Agent Response:</strong>
                                {isMarkdownContent(parsedContent.text) ? (
                                  <div style={{ background: 'var(--vscode-editor-background, #1e1e1e)', padding: '8px', borderRadius: '4px', maxHeight: '400px', overflow: 'auto', marginTop: '4px', lineHeight: 1.5 }} className="ga-exec-markdown">
                                    <Markdown remarkPlugins={[remarkGfm]}>{parsedContent.text}</Markdown>
                                  </div>
                                ) : (
                                  <pre style={{ whiteSpace: 'pre-wrap', background: 'var(--vscode-editor-background, #1e1e1e)', padding: '8px', borderRadius: '4px', maxHeight: '300px', overflow: 'auto', marginTop: '4px' }}>
                                    {parsedContent.text}
                                  </pre>
                                )}
                              </div>
                            )}

                            {/* Tool call details */}
                            {parsedContent.toolName && (
                              <div style={{ marginBottom: '8px' }}>
                                <strong>Tool:</strong> <code>{parsedContent.toolName}</code>
                                {parsedContent.success !== undefined && (
                                  <span style={{ marginLeft: '8px', color: parsedContent.success ? '#4caf50' : '#f44336' }}>
                                    {parsedContent.success ? '✓ Success' : '✗ Failed'}
                                  </span>
                                )}
                              </div>
                            )}

                            {/* Tool inputs */}
                            {parsedContent.inputs && Object.keys(parsedContent.inputs).length > 0 && (
                              <div style={{ marginBottom: '8px' }}>
                                <strong>Inputs:</strong>
                                <pre style={{ whiteSpace: 'pre-wrap', background: 'var(--vscode-editor-background, #1e1e1e)', padding: '8px', borderRadius: '4px', maxHeight: '200px', overflow: 'auto', marginTop: '4px' }}>
                                  {JSON.stringify(parsedContent.inputs, null, 2)}
                                </pre>
                              </div>
                            )}

                            {/* Tool output */}
                            {parsedContent.output !== undefined && parsedContent.output !== null && (
                              <div style={{ marginBottom: '8px' }}>
                                <strong>Output:</strong>
                                <pre style={{ whiteSpace: 'pre-wrap', background: 'var(--vscode-editor-background, #1e1e1e)', padding: '8px', borderRadius: '4px', maxHeight: '200px', overflow: 'auto', marginTop: '4px' }}>
                                  {String(typeof parsedContent.output === 'string' ? parsedContent.output : JSON.stringify(parsedContent.output, null, 2))}
                                </pre>
                              </div>
                            )}

                            {/* Error message */}
                            {parsedContent.error && (
                              <div style={{ marginBottom: '8px', color: '#f44336' }}>
                                <strong>Error:</strong> {parsedContent.error}
                              </div>
                            )}

                            {/* Tool names list */}
                            {step.toolNames && step.toolNames.length > 0 && (
                              <div style={{ marginBottom: '8px' }}>
                                <strong>Tools used:</strong> {step.toolNames.join(', ')}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
