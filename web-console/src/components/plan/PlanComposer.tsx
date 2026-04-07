/**
 * PlanComposer Component
 *
 * The first collaborative artifact - real-time plan editing with presence awareness.
 * This is where the "floaty, smooth, delightful" UX vision comes to life.
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useMemo,
  memo,
  type FC,
  type KeyboardEvent,
  type ChangeEvent,
} from 'react';
import { useCollaboration, type CollabClientConfig } from '../../lib/collab-client';
import { collabStore } from '../../store/collabStore';
import './PlanComposer.css';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface PlanStep {
  id: string;
  title: string;
  description: string;
  assignee?: {
    id: string;
    name: string;
    avatar?: string;
  };
  priority: 'high' | 'medium' | 'low';
  completed: boolean;
  order: number;
}

interface PlanContent {
  title: string;
  description?: string;
  steps: PlanStep[];
  metadata?: Record<string, unknown>;
}

interface PlanComposerProps {
  collabConfig: CollabClientConfig;
  documentId: string;
  workspaceId?: string;
  initialContent?: PlanContent;
  onSave?: (content: PlanContent) => void;
  readOnly?: boolean;
}

interface RemoteCursor {
  userId: string;
  userName: string;
  color: string;
  position: { x: number; y: number } | null;
  focusedStepId: string | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Icons
// ─────────────────────────────────────────────────────────────────────────────

const PlusIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
    <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

const TrashIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
    <path d="M3 4h8M5.5 4V3a1 1 0 011-1h1a1 1 0 011 1v1M4 4v7a1 1 0 001 1h4a1 1 0 001-1V4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

const DragHandleIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
    <circle cx="4" cy="3" r="1" fill="currentColor" />
    <circle cx="8" cy="3" r="1" fill="currentColor" />
    <circle cx="4" cy="6" r="1" fill="currentColor" />
    <circle cx="8" cy="6" r="1" fill="currentColor" />
    <circle cx="4" cy="9" r="1" fill="currentColor" />
    <circle cx="8" cy="9" r="1" fill="currentColor" />
  </svg>
);

const CheckIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
    <path d="M2.5 6l2.5 2.5 4.5-5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// ─────────────────────────────────────────────────────────────────────────────
// Utilities
// ─────────────────────────────────────────────────────────────────────────────

const generateId = () => `step_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;

const createEmptyStep = (order: number): PlanStep => ({
  id: generateId(),
  title: '',
  description: '',
  priority: 'medium',
  completed: false,
  order,
});

// Cursor colors for presence
const CURSOR_COLORS = [
  '#3b82f6', // Blue
  '#0ea5e9', // Sky
  '#06b6d4', // Cyan
  '#14b8a6', // Teal
  '#22c55e', // Green
  '#f59e0b', // Amber
  '#ef4444', // Red
  '#10b981', // Emerald
];

const getColorForUser = (userId: string): string => {
  const hash = userId.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
  return CURSOR_COLORS[hash % CURSOR_COLORS.length];
};

// ─────────────────────────────────────────────────────────────────────────────
// Step Component
// ─────────────────────────────────────────────────────────────────────────────

interface StepCardProps {
  step: PlanStep;
  index: number;
  isFocused: boolean;
  remoteCursors: RemoteCursor[];
  onUpdate: (id: string, updates: Partial<PlanStep>) => void;
  onDelete: (id: string) => void;
  onFocus: (id: string) => void;
  onBlur: () => void;
  readOnly?: boolean;
}

const StepCard = memo<StepCardProps>(({
  step,
  index,
  isFocused,
  remoteCursors,
  onUpdate,
  onDelete,
  onFocus,
  onBlur,
  readOnly,
}) => {
  const titleRef = useRef<HTMLTextAreaElement>(null);
  const descRef = useRef<HTMLTextAreaElement>(null);

  const remoteEditors = useMemo(
    () => remoteCursors.filter((c) => c.focusedStepId === step.id),
    [remoteCursors, step.id]
  );

  const hasRemoteCursor = remoteEditors.length > 0;
  const remoteCursorColor = hasRemoteCursor ? remoteEditors[0].color : undefined;

  const handleTitleChange = useCallback(
    (e: ChangeEvent<HTMLTextAreaElement>) => {
      onUpdate(step.id, { title: e.target.value });
    },
    [step.id, onUpdate]
  );

  const handleDescChange = useCallback(
    (e: ChangeEvent<HTMLTextAreaElement>) => {
      onUpdate(step.id, { description: e.target.value });
    },
    [step.id, onUpdate]
  );

  const handleTitleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        descRef.current?.focus();
      }
    },
    []
  );

  const handleFocus = useCallback(() => {
    onFocus(step.id);
  }, [step.id, onFocus]);

  const handleDeleteClick = useCallback(() => {
    onDelete(step.id);
  }, [step.id, onDelete]);

  const toggleComplete = useCallback(() => {
    onUpdate(step.id, { completed: !step.completed });
  }, [step.id, step.completed, onUpdate]);

  // Auto-resize textareas
  useEffect(() => {
    const adjustHeight = (el: HTMLTextAreaElement | null) => {
      if (el) {
        el.style.height = 'auto';
        el.style.height = `${el.scrollHeight}px`;
      }
    };
    adjustHeight(titleRef.current);
    adjustHeight(descRef.current);
  }, [step.title, step.description]);

  return (
    <div
      className={`plan-step ${isFocused ? 'focused' : ''} ${hasRemoteCursor ? 'has-remote-cursor' : ''}`}
      style={{ '--remote-cursor-color': remoteCursorColor } as React.CSSProperties}
      data-step-id={step.id}
    >
      <div className="step-header">
        <button
          className={`step-number ${step.completed ? 'completed' : ''}`}
          onClick={toggleComplete}
          disabled={readOnly}
          title={step.completed ? 'Mark incomplete' : 'Mark complete'}
        >
          {step.completed ? <CheckIcon /> : index + 1}
        </button>

        <div className="step-title-wrapper">
          <textarea
            ref={titleRef}
            className="step-title-input"
            value={step.title}
            onChange={handleTitleChange}
            onFocus={handleFocus}
            onBlur={onBlur}
            onKeyDown={handleTitleKeyDown}
            placeholder="Step title..."
            rows={1}
            disabled={readOnly}
          />
        </div>

        <div className="step-drag-handle" title="Drag to reorder">
          <DragHandleIcon />
        </div>
      </div>

      <div className="step-body">
        <textarea
          ref={descRef}
          className="step-description-input"
          value={step.description}
          onChange={handleDescChange}
          onFocus={handleFocus}
          onBlur={onBlur}
          placeholder="Add details, context, or instructions..."
          rows={2}
          disabled={readOnly}
        />
      </div>

      <div className="step-meta">
        <button className="step-assignee" disabled={readOnly}>
          {step.assignee ? (
            <>
              <span className="step-assignee-avatar">
                {step.assignee.name.charAt(0).toUpperCase()}
              </span>
              <span>{step.assignee.name}</span>
            </>
          ) : (
            <>
              <span className="step-assignee-avatar">+</span>
              <span>Assign</span>
            </>
          )}
        </button>

        <button
          className={`step-priority priority-${step.priority}`}
          disabled={readOnly}
        >
          {step.priority === 'high' && '● High'}
          {step.priority === 'medium' && '● Medium'}
          {step.priority === 'low' && '○ Low'}
        </button>

        {hasRemoteCursor && (
          <div className="step-remote-editors">
            {remoteEditors.map((editor) => (
              <span
                key={editor.userId}
                style={{ color: editor.color }}
                className="remote-editor-name"
              >
                {editor.userName} editing
              </span>
            ))}
          </div>
        )}
      </div>

      {!readOnly && (
        <div className="step-actions">
          <button
            className="step-action-btn delete"
            onClick={handleDeleteClick}
            title="Delete step"
          >
            <TrashIcon />
          </button>
        </div>
      )}
    </div>
  );
});

StepCard.displayName = 'StepCard';

// ─────────────────────────────────────────────────────────────────────────────
// Main Component
// ─────────────────────────────────────────────────────────────────────────────

export const PlanComposer: FC<PlanComposerProps> = ({
  collabConfig,
  documentId,
  workspaceId: _workspaceId,
  initialContent,
  onSave: _onSave,
  readOnly = false,
}) => {
  // Connect to document for real-time collaboration
  const {
    document: collabDoc,
    connectionState,
    isConnected,
    cursors,
    presence,
    operations: _operations,
    replace: sendReplace,
    error: collabError,
  } = useCollaboration({
    config: collabConfig,
    documentId,
  });

  // Helper to broadcast plan updates as JSON
  const broadcastPlanUpdate = useCallback((newPlan: PlanContent) => {
    const content = JSON.stringify(newPlan);
    sendReplace(0, collabDoc?.content?.length ?? 0, content);
    setSyncStatus('syncing');
  }, [sendReplace, collabDoc?.content?.length]);

  // Local state
  const [planContent, setPlanContent] = useState<PlanContent>(
    initialContent ?? {
      title: 'Untitled Plan',
      steps: [createEmptyStep(0)],
    }
  );
  const [focusedStepId, setFocusedStepId] = useState<string | null>(null);
  const [syncStatus, setSyncStatus] = useState<'synced' | 'syncing' | 'error'>('synced');
  const [showConflictModal, setShowConflictModal] = useState(false);

  useEffect(() => {
    collabStore.setActiveDocument(documentId);
    if (_workspaceId) {
      collabStore.setActiveWorkspace(_workspaceId);
    }

    return () => {
      collabStore.setActiveDocument(null);
      collabStore.setActiveWorkspace(null);
      collabStore.clearPresence();
      collabStore.setConnectionState('disconnected');
    };
  }, [documentId, _workspaceId]);

  useEffect(() => {
    collabStore.setConnectionState(connectionState);
  }, [connectionState]);

  useEffect(() => {
    collabStore.replacePresence(presence.values());
  }, [presence]);

  // Build remote cursors from presence data (using cursors from hook)
  const remoteCursors = useMemo<RemoteCursor[]>(() => {
    const cursorList: RemoteCursor[] = [];

    cursors.forEach((_cursorInfo: { position: number; selectionEnd?: number }, userId: string) => {
      cursorList.push({
        userId,
        userName: userId.split('-')[0] ?? 'Unknown', // Extract name from userId
        color: getColorForUser(userId),
        position: null,
        focusedStepId: null, // Will be derived from position
      });
    });

    return cursorList;
  }, [cursors]);

  // Sync content from collab document
  useEffect(() => {
    if (collabDoc?.content) {
      try {
        const parsed = JSON.parse(collabDoc.content) as PlanContent;
        setPlanContent(parsed);
      } catch {
        // Content might not be JSON, use as title
        setPlanContent(prev => ({
          ...prev,
          title: collabDoc.content,
        }));
      }
    }
  }, [collabDoc]);

  // Update sync status based on connection and errors
  useEffect(() => {
    if (collabError) {
      setSyncStatus('error');
    } else if (isConnected) {
      setSyncStatus('synced');
    }
  }, [isConnected, collabError]);

  // Broadcast presence when focus changes
  useEffect(() => {
    if (isConnected && focusedStepId !== undefined) {
      // Presence is automatically managed by the hook, but we can add metadata
      // via the client if needed
    }
  }, [isConnected, focusedStepId]);

  // ─────────────────────────────────────────────────────────────────────────────
  // Handlers
  // ─────────────────────────────────────────────────────────────────────────────

  const handleTitleChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      const newTitle = e.target.value;
      setPlanContent((prev) => {
        const newPlan = { ...prev, title: newTitle };
        broadcastPlanUpdate(newPlan);
        return newPlan;
      });
    },
    [broadcastPlanUpdate]
  );

  const handleStepUpdate = useCallback(
    (stepId: string, updates: Partial<PlanStep>) => {
      setPlanContent((prev) => {
        const newSteps = prev.steps.map((step) =>
          step.id === stepId ? { ...step, ...updates } : step
        );
        const newPlan = { ...prev, steps: newSteps };
        broadcastPlanUpdate(newPlan);
        return newPlan;
      });
    },
    [broadcastPlanUpdate]
  );

  const handleStepDelete = useCallback(
    (stepId: string) => {
      setPlanContent((prev) => {
        const newSteps = prev.steps
          .filter((step) => step.id !== stepId)
          .map((step, idx) => ({ ...step, order: idx }));
        const newPlan = { ...prev, steps: newSteps };
        broadcastPlanUpdate(newPlan);
        return newPlan;
      });
    },
    [broadcastPlanUpdate]
  );

  const handleAddStep = useCallback(() => {
    const newStep = createEmptyStep(planContent.steps.length);

    setPlanContent((prev) => {
      const newPlan = {
        ...prev,
        steps: [...prev.steps, newStep],
      };
      broadcastPlanUpdate(newPlan);
      return newPlan;
    });

    // Focus new step after render
    requestAnimationFrame(() => {
      const stepEl = document.querySelector(`[data-step-id="${newStep.id}"]`);
      const titleInput = stepEl?.querySelector('.step-title-input') as HTMLTextAreaElement;
      titleInput?.focus();
    });
  }, [planContent.steps.length, broadcastPlanUpdate]);

  const handleStepFocus = useCallback((stepId: string) => {
    setFocusedStepId(stepId);
  }, []);

  const handleStepBlur = useCallback(() => {
    // Delay clearing focus to handle click-to-focus transitions
    setTimeout(() => {
      setFocusedStepId(null);
    }, 100);
  }, []);

  const handleResolveConflict = useCallback((useRemote: boolean) => {
    if (useRemote && collabDoc?.content) {
      try {
        const parsed = JSON.parse(collabDoc.content) as PlanContent;
        setPlanContent(parsed);
      } catch {
        // If not JSON, ignore
      }
    }
    setShowConflictModal(false);
    setSyncStatus('synced');
  }, [collabDoc?.content]);

  // Reset sync status after brief delay
  useEffect(() => {
    if (syncStatus === 'syncing') {
      const timer = setTimeout(() => setSyncStatus('synced'), 500);
      return () => clearTimeout(timer);
    }
  }, [syncStatus, collabDoc?.version]);

  // ─────────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────────

  return (
    <div className="plan-composer">
      <div className="plan-composer-header">
        <input
          className="plan-title-input"
          type="text"
          value={planContent.title}
          onChange={handleTitleChange}
          placeholder="Plan title..."
          disabled={readOnly}
        />

        <div className="plan-header-actions">
          <div className="sync-status">
            <div className={`sync-indicator ${syncStatus}`} />
            <span>
              {syncStatus === 'synced' && 'All changes saved'}
              {syncStatus === 'syncing' && 'Saving...'}
              {syncStatus === 'error' && 'Sync error'}
            </span>
          </div>
        </div>
      </div>

      <div className="plan-canvas">
        <div className="plan-content">
          <div className="plan-steps">
            {planContent.steps.map((step, index) => (
              <StepCard
                key={step.id}
                step={step}
                index={index}
                isFocused={focusedStepId === step.id}
                remoteCursors={remoteCursors}
                onUpdate={handleStepUpdate}
                onDelete={handleStepDelete}
                onFocus={handleStepFocus}
                onBlur={handleStepBlur}
                readOnly={readOnly}
              />
            ))}
          </div>

          {!readOnly && (
            <div className="add-step-wrapper">
              <button className="add-step-button" onClick={handleAddStep}>
                <PlusIcon />
                Add step
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Version Conflict Modal */}
      {showConflictModal && (
        <div className="conflict-modal-overlay" onClick={() => setShowConflictModal(false)}>
          <div className="conflict-modal" onClick={(e) => e.stopPropagation()}>
            <h3 className="conflict-modal-title">Version Conflict</h3>
            <p className="conflict-modal-description">
              Someone else has made changes to this plan. Would you like to keep your
              changes or load the latest version?
            </p>
            <div className="conflict-modal-actions">
              <button
                className="conflict-btn conflict-btn-secondary"
                onClick={() => handleResolveConflict(false)}
              >
                Keep mine
              </button>
              <button
                className="conflict-btn conflict-btn-primary"
                onClick={() => handleResolveConflict(true)}
              >
                Load latest
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default PlanComposer;
