/**
 * MessageComposer — Text input with @mentions and typing indicator.
 *
 * Auto-resizing textarea, Enter to send, Shift+Enter newline,
 * @mention picker from conversation participants.
 */

import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  type AvailableLLMModel,
  useConversation,
  useConversationParticipants,
  useInfiniteMessages,
  useModelReadiness,
  useProjectModels,
  useUserModels,
  useSendMessage,
} from '../../api/conversations';
import type { ConversationParticipant } from '../../lib/collab-client';
import { showExecutionConsentFromNewestFirstMessages } from './messageComposerExecutionConsent';
import { getPreferredExecutionWorkspaceKind } from '../../utils/executionWorkspacePreference';
import { hapticSend } from '../../utils/haptics';

/** Stable empty list so hooks never see a fresh `[]` each render. */
const EMPTY_MODELS: AvailableLLMModel[] = [];

function mergeModelCatalog(
  base: readonly AvailableLLMModel[],
  readiness: readonly AvailableLLMModel[],
): AvailableLLMModel[] {
  if (readiness.length === 0) {
    return base.length === 0 ? EMPTY_MODELS : [...base];
  }
  const byId = new Map<string, AvailableLLMModel>();
  for (const m of base) {
    byId.set(m.model_id, m);
  }
  for (const m of readiness) {
    const existing = byId.get(m.model_id);
    byId.set(m.model_id, existing ? { ...existing, ...m } : m);
  }
  return Array.from(byId.values());
}

// ── Types ────────────────────────────────────────────────────────────────────

export interface MessageComposerProps {
  conversationId: string | null;
  currentUserId?: string;
  disabled?: boolean;
  placeholder?: string;
  onTyping?: (isTyping: boolean) => void;
  replyToMessageId?: string | null;
  onCancelReply?: () => void;
  onReplyStreamScheduled?: (streamMessageId: string) => void;
}

function createStreamMessageId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return `msg-${crypto.randomUUID()}`;
  }
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** Deterministic accent for model picker dots */
function dotColorForModelId(modelId: string): string {
  let h = 0;
  for (let i = 0; i < modelId.length; i += 1) {
    h = (h * 31 + modelId.charCodeAt(i)) % 360;
  }
  return `hsl(${h} 62% 44%)`;
}

// ── Component ────────────────────────────────────────────────────────────────

export const MessageComposer = memo(function MessageComposer({
  conversationId,
  currentUserId,
  disabled = false,
  placeholder = 'Send a message...',
  onTyping,
  replyToMessageId,
  onCancelReply,
  onReplyStreamScheduled,
}: MessageComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [value, setValue] = useState('');
  const [mentionSearch, setMentionSearch] = useState<string | null>(null);
  const [mentionAnchor, setMentionAnchor] = useState<number | null>(null);
  const [selectedModelId, setSelectedModelId] = useState('');
  const [confirmChatExecution, setConfirmChatExecution] = useState(false);
  const [confirmChatExecutionCancel, setConfirmChatExecutionCancel] = useState(false);
  const [executionWorkItemId, setExecutionWorkItemId] = useState('');
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [sendBurst, setSendBurst] = useState(false);
  const typingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const modelDropdownRef = useRef<HTMLDivElement>(null);

  const sendMessage = useSendMessage();
  const { data: conversation } = useConversation(conversationId ?? undefined);
  const { data: participantsData } = useConversationParticipants(conversationId ?? undefined);
  const { data: messagePages } = useInfiniteMessages({
    conversationId: conversationId ?? '',
    enabled: !!conversationId,
    limit: 50,
  });
  const newestFirstMessages = useMemo(
    () => messagePages?.pages.flatMap((p) => p.items) ?? [],
    [messagePages?.pages],
  );
  const showExecutionConsent = useMemo(
    () => showExecutionConsentFromNewestFirstMessages(newestFirstMessages),
    [newestFirstMessages],
  );
  const projectId = conversation?.project_id ?? undefined;
  const conversationWorkItemId =
    (conversation as { work_item_id?: string } | undefined)?.work_item_id ?? '';

  /** Used for BYOK + personal NVIDIA open-tier catalog; must match server user_id for credentials. */
  const effectiveUserId = currentUserId ?? conversation?.created_by ?? undefined;
  const {
    data: projectModelAvailability,
    isError: projectModelsError,
    isLoading: projectModelsLoading,
  } = useProjectModels(projectId, {
    orgId: conversation?.org_id,
    userId: effectiveUserId,
  });
  const {
    data: userModelAvailability,
    isError: userModelsError,
    isLoading: userModelsLoading,
  } = useUserModels(effectiveUserId);
  const useReadinessGate = !!(conversationId && effectiveUserId);
  const availabilityModels = useMemo(() => {
    const userModels = userModelAvailability?.models ?? EMPTY_MODELS;
    if (!projectId) {
      return userModels;
    }
    const projectModels = projectModelAvailability?.models ?? EMPTY_MODELS;
    return mergeModelCatalog(projectModels, userModels);
  }, [projectId, projectModelAvailability, userModelAvailability]);
  const readinessProbeId = useMemo(() => {
    if (availabilityModels.length === 0) return '';
    if (selectedModelId && availabilityModels.some((m) => m.model_id === selectedModelId)) {
      return selectedModelId;
    }
    return (availabilityModels.find((m) => m.is_default) ?? availabilityModels[0]).model_id;
  }, [availabilityModels, selectedModelId]);
  const {
    data: readiness,
    isLoading: readinessLoading,
    isError: readinessError,
  } = useModelReadiness({
    conversationId: conversationId ?? undefined,
    projectId,
    orgId: conversation?.org_id,
    userId: effectiveUserId,
    preferUser: !!effectiveUserId,
    selectedModelId: readinessProbeId || undefined,
    enabled: useReadinessGate,
  });
  const participants = participantsData?.items ?? [];
  const readinessModels = readiness?.models ?? EMPTY_MODELS;
  const availableModels = useMemo(
    () => mergeModelCatalog(availabilityModels, readinessModels),
    [availabilityModels, readinessModels],
  );
  const resolvedModelId = useMemo(() => {
    if (availableModels.length === 0) return '';
    if (selectedModelId && availableModels.some((m) => m.model_id === selectedModelId)) {
      return selectedModelId;
    }
    return (availableModels.find((m) => m.is_default) ?? availableModels[0]).model_id;
  }, [availableModels, selectedModelId]);
  const modelsLoading = projectId ? projectModelsLoading || userModelsLoading : userModelsLoading;
  const modelsError = projectId ? projectModelsError || userModelsError : userModelsError;
  const selectedModel = availableModels.find((model) => model.model_id === resolvedModelId);

  // ── Auto-resize textarea ─────────────────────────────────────────────────

  useEffect(() => {
    if (!conversationId) return;
    const id = requestAnimationFrame(() => textareaRef.current?.focus());
    return () => cancelAnimationFrame(id);
  }, [conversationId]);

  const adjustHeight = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 180)}px`;
  }, []);

  useEffect(() => {
    adjustHeight();
  }, [value, adjustHeight]);

  useEffect(() => {
    if (!showExecutionConsent) {
      setConfirmChatExecution(false);
      setConfirmChatExecutionCancel(false);
      setExecutionWorkItemId('');
    }
  }, [showExecutionConsent]);

  useEffect(() => {
    setModelMenuOpen(false);
  }, [conversationId]);

  useLayoutEffect(() => {
    if (!modelMenuOpen) return undefined;
    const onDoc = (e: MouseEvent) => {
      const root = modelDropdownRef.current;
      if (root && !root.contains(e.target as Node)) {
        setModelMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', onDoc, true);
    return () => document.removeEventListener('mousedown', onDoc, true);
  }, [modelMenuOpen]);

  useEffect(() => {
    if (!modelMenuOpen) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setModelMenuOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [modelMenuOpen]);

  useEffect(() => {
    if (showExecutionConsent && conversationWorkItemId) {
      setExecutionWorkItemId((prev) => (prev.trim() === '' ? conversationWorkItemId : prev));
    }
  }, [conversationWorkItemId, showExecutionConsent]);

  // ── Typing indicator ─────────────────────────────────────────────────────

  const emitTyping = useCallback((isTyping: boolean) => {
    onTyping?.(isTyping);
  }, [onTyping]);

  const handleTypingDebounce = useCallback(() => {
    emitTyping(true);
    if (typingTimeoutRef.current) {
      clearTimeout(typingTimeoutRef.current);
    }
    typingTimeoutRef.current = setTimeout(() => {
      emitTyping(false);
    }, 2000);
  }, [emitTyping]);

  // ── Mention handling ─────────────────────────────────────────────────────

  const checkForMention = useCallback((text: string, cursorPos: number) => {
    // Find @ before cursor position
    const beforeCursor = text.slice(0, cursorPos);
    const lastAtIndex = beforeCursor.lastIndexOf('@');

    if (lastAtIndex === -1) {
      setMentionSearch(null);
      setMentionAnchor(null);
      return;
    }

    // Check if @ is at start or after whitespace
    if (lastAtIndex > 0 && !/\s/.test(beforeCursor[lastAtIndex - 1])) {
      setMentionSearch(null);
      setMentionAnchor(null);
      return;
    }

    const searchText = beforeCursor.slice(lastAtIndex + 1);
    // No whitespace in mention search
    if (/\s/.test(searchText)) {
      setMentionSearch(null);
      setMentionAnchor(null);
      return;
    }

    setMentionSearch(searchText.toLowerCase());
    setMentionAnchor(lastAtIndex);
  }, []);

  const filteredParticipants = participants.filter((p) => {
    if (mentionSearch === null) return false;
    return p.actor_id.toLowerCase().includes(mentionSearch);
  }).slice(0, 6);

  const insertMention = useCallback((participant: ConversationParticipant) => {
    if (mentionAnchor === null) return;
    const before = value.slice(0, mentionAnchor);
    const after = value.slice(textareaRef.current?.selectionStart ?? value.length);
    setValue(`${before}@${participant.actor_id} ${after}`);
    setMentionSearch(null);
    setMentionAnchor(null);
    textareaRef.current?.focus();
  }, [mentionAnchor, value]);

  // ── Input handling ───────────────────────────────────────────────────────

  const handleChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newValue = e.target.value;
    setValue(newValue);
    handleTypingDebounce();
    checkForMention(newValue, e.target.selectionStart);
  }, [handleTypingDebounce, checkForMention]);

  const sendBlockedByReadiness =
    useReadinessGate && (readinessLoading || (readiness && !readiness.can_send));

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || !conversationId || disabled || sendMessage.isPending || sendBlockedByReadiness) return;

    // Clear typing indicator
    if (typingTimeoutRef.current) {
      clearTimeout(typingTimeoutRef.current);
    }
    emitTyping(false);

    if (!selectedModel) {
      return;
    }

    const streamMessageId = createStreamMessageId();
    onReplyStreamScheduled?.(streamMessageId);

    const trimmedWorkItem = executionWorkItemId.trim();
    const meta: Record<string, unknown> = {
      stream_message_id: streamMessageId,
      llm_model_id: selectedModel.model_id,
      llm_provider: selectedModel.provider,
      credential_scope: selectedModel.credential_source,
    };
    if (confirmChatExecution) {
      meta.confirm_chat_execution = true;
      if (projectId) {
        meta.project_id = projectId;
      }
      if (trimmedWorkItem) {
        meta.work_item_id = trimmedWorkItem;
      }
    }
    if (confirmChatExecutionCancel) {
      meta.confirm_chat_execution_cancel = true;
      if (trimmedWorkItem) {
        meta.work_item_id = trimmedWorkItem;
      }
      if (projectId) {
        meta.project_id = projectId;
      }
    }
    if (
      getPreferredExecutionWorkspaceKind() === 'local_connector' &&
      (confirmChatExecution || confirmChatExecutionCancel || trimmedWorkItem)
    ) {
      meta.execution_workspace_kind = 'local_connector';
    }

    hapticSend();
    setSendBurst(true);
    window.setTimeout(() => setSendBurst(false), 420);

    sendMessage.mutate(
      {
        conversationId,
        content: trimmed,
        senderId: currentUserId,
        parentId: replyToMessageId ?? undefined,
        workItemId: trimmedWorkItem || undefined,
        metadata: meta,
      },
      {
        onError: () => {
          onReplyStreamScheduled?.('');
        },
      },
    );

    setValue('');
    onCancelReply?.();
    textareaRef.current?.focus();
  }, [
    value,
    conversationId,
    disabled,
    sendMessage,
    emitTyping,
    currentUserId,
    replyToMessageId,
    onCancelReply,
    selectedModel,
    sendBlockedByReadiness,
    onReplyStreamScheduled,
    confirmChatExecution,
    confirmChatExecutionCancel,
    executionWorkItemId,
    projectId,
  ]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Handle mention picker navigation
    if (mentionSearch !== null && filteredParticipants.length > 0) {
      if (e.key === 'Escape') {
        e.preventDefault();
        setMentionSearch(null);
        setMentionAnchor(null);
        return;
      }
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) {
        e.preventDefault();
        insertMention(filteredParticipants[0]);
        return;
      }
    }

    // Enter to send, Shift+Enter for newline
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
      return;
    }

    // Cmd/Ctrl+Enter always sends
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleSend();
    }
  }, [mentionSearch, filteredParticipants, insertMention, handleSend]);

  // ── Render ───────────────────────────────────────────────────────────────

  const isDisabled = disabled || !conversationId;

  const readinessStatusText = (() => {
    if (!useReadinessGate) return null;
    if (readinessLoading) return 'Checking model readiness…';
    if (readinessError) return 'Could not verify model readiness.';
    if (readiness && !readiness.can_send) {
      return readiness.detail || `Chat setup required (${readiness.state}).`;
    }
    return null;
  })();

  return (
    <div className="msg-composer">
      {/* Reply banner */}
      {replyToMessageId && (
        <div className="msg-composer-reply-banner">
          <span className="msg-composer-reply-label">Replying to message</span>
          <button
            type="button"
            className="msg-composer-reply-cancel"
            onClick={onCancelReply}
            aria-label="Cancel reply"
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" />
            </svg>
          </button>
        </div>
      )}

      {showExecutionConsent && (
        <div className="msg-composer-exec-consent" aria-label="Chat execution consent">
          <label>
            <input
              type="checkbox"
              checked={confirmChatExecution}
              onChange={(e) => setConfirmChatExecution(e.target.checked)}
            />
            Confirm start execution
          </label>
          <label>
            <input
              type="checkbox"
              checked={confirmChatExecutionCancel}
              onChange={(e) => setConfirmChatExecutionCancel(e.target.checked)}
            />
            Confirm cancel execution
          </label>
          <label className="msg-composer-exec-wi-label">
            Work item ID
            <input
              type="text"
              className="msg-composer-exec-wi"
              value={executionWorkItemId}
              onChange={(e) => setExecutionWorkItemId(e.target.value)}
              placeholder="Optional if linked on conversation"
              aria-label="Work item id for execution actions"
            />
          </label>
        </div>
      )}

      <div className="msg-composer-input-row">
        <textarea
          ref={textareaRef}
          className="msg-composer-textarea"
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={isDisabled}
          rows={1}
          aria-label="Message input"
        />
        <button
          type="button"
          className={`msg-composer-send-btn pressable${sendBurst ? ' msg-composer-send-btn--burst' : ''}`}
          onClick={handleSend}
          disabled={
            isDisabled || !value.trim() || sendMessage.isPending || sendBlockedByReadiness
          }
          aria-label="Send message"
          data-haptic="light"
        >
          {sendMessage.isPending ? (
            <span className="msg-composer-sending-spinner" />
          ) : (
            <SendIcon />
          )}
        </button>
      </div>

      {(availableModels.length > 0 ||
        modelsLoading ||
        modelsError ||
        projectModelAvailability ||
        userModelAvailability ||
        readinessLoading ||
        readinessError ||
        readinessStatusText) && (
        <div className="msg-composer-model-row">
          <span className="msg-composer-model-label" id="msg-composer-model-label">
            Model
          </span>
          {availableModels.length > 0 ? (
            <div
              className="msg-composer-model-dropdown"
              ref={modelDropdownRef}
              data-chat-dropdown
            >
              <button
                type="button"
                className="msg-composer-model-trigger pressable"
                id="msg-composer-model-trigger"
                aria-labelledby="msg-composer-model-label"
                aria-label="Choose chat model"
                aria-haspopup="listbox"
                aria-expanded={modelMenuOpen}
                disabled={isDisabled || sendMessage.isPending || readinessLoading}
                onClick={() => setModelMenuOpen((o) => !o)}
              >
                <span
                  className="msg-composer-model-dot"
                  style={{ background: dotColorForModelId(resolvedModelId) }}
                  aria-hidden
                />
                <span className="msg-composer-model-trigger-text">
                  {selectedModel
                    ? `${selectedModel.display_name} (${selectedModel.provider}/${selectedModel.credential_source})`
                    : resolvedModelId}
                </span>
                <span className="msg-composer-model-chevron" aria-hidden>
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
                    <path d="M3 4.5l3 3 3-3" />
                  </svg>
                </span>
              </button>
              {modelMenuOpen && (
                <ul className="msg-composer-model-panel" role="listbox" aria-label="Choose chat model">
                  {availableModels.map((model) => {
                    const active = model.model_id === resolvedModelId;
                    return (
                      <li key={model.model_id} role="none">
                        <button
                          type="button"
                          role="option"
                          aria-selected={active}
                          className={`msg-composer-model-option${active ? ' msg-composer-model-option--active' : ''}`}
                          onClick={() => {
                            setSelectedModelId(model.model_id);
                            setModelMenuOpen(false);
                          }}
                        >
                          <span
                            className="msg-composer-model-dot"
                            style={{ background: dotColorForModelId(model.model_id) }}
                            aria-hidden
                          />
                          <span className="msg-composer-model-option-text">
                            {model.display_name}{' '}
                            <span className="msg-composer-model-option-meta">
                              ({model.provider}/{model.credential_source})
                            </span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          ) : (
            <span className="msg-composer-model-status">
              {readinessStatusText
                ? readinessStatusText
                : modelsLoading || readinessLoading
                  ? 'Loading available models…'
                  : modelsError || readinessError
                    ? 'Could not load models for this chat.'
                    : 'No models available. Configure a platform API key or BYOK for this scope.'}
            </span>
          )}
        </div>
      )}

      {/* Mention picker */}
      {mentionSearch !== null && filteredParticipants.length > 0 && (
        <div className="msg-mention-picker" role="listbox" aria-label="Mention suggestions">
          {filteredParticipants.map((p, idx) => (
            <button
              key={p.actor_id}
              type="button"
              className={`msg-mention-option ${idx === 0 ? 'msg-mention-option--highlighted' : ''}`}
              onClick={() => insertMention(p)}
              role="option"
              aria-selected={idx === 0}
            >
              <span className="msg-mention-avatar">
                {p.actor_id.slice(0, 2).toUpperCase()}
              </span>
              <span className="msg-mention-name">{p.actor_id}</span>
            </button>
          ))}
        </div>
      )}

      {/* Keyboard hint */}
      {!isDisabled && (
        <div className="msg-composer-hint">
          <kbd>Enter</kbd> to send, <kbd>Shift</kbd>+<kbd>Enter</kbd> for newline
        </div>
      )}
    </div>
  );
});

// ── Send Icon ────────────────────────────────────────────────────────────────

function SendIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true" className="msg-send-icon">
      <path d="M14 2L7 9" />
      <path d="M14 2L9 14l-2-5-5-2z" />
    </svg>
  );
}
