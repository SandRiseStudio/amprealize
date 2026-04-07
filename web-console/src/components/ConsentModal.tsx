/**
 * ConsentModal Component
 *
 * Modal for JIT consent approval when agents request tool access.
 * Implements CONSENT_UX_PROTOTYPE.md specs:
 * - Provider icon + agent identity header
 * - Scope list with plain-language descriptions
 * - Expiration + obligations summary
 * - Behavior context card
 * - Approve / Deny / Snooze actions
 * - Telemetry instrumentation
 * - Accessibility: WCAG AA, keyboard navigation, screen-reader labels
 *
 * Following:
 * - behavior_prototype_consent_ux (Teacher)
 * - behavior_validate_accessibility (Student)
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import type { ConsentScope, ConsentDecision } from '../types/auth';
import './ConsentModal.css';

// ---------------------------------------------------------------------------
// Helper Components
// ---------------------------------------------------------------------------

interface ScopeItemProps {
  scope: ConsentScope;
  isExpanded: boolean;
  onToggle: () => void;
}

function ScopeItem({ scope, isExpanded, onToggle }: ScopeItemProps): React.JSX.Element {
  const id = `scope-${scope.name.replace(/\./g, '-')}`;

  return (
    <div className={`consent-scope-item ${scope.highRisk ? 'high-risk' : ''}`}>
      <button
        type="button"
        className="consent-scope-header"
        onClick={onToggle}
        aria-expanded={isExpanded}
        aria-controls={`${id}-details`}
      >
        <span className="consent-scope-icon" aria-hidden="true">
          {scope.highRisk ? '⚠️' : '🔑'}
        </span>
        <span className="consent-scope-name">{scope.displayName}</span>
        <span className="consent-scope-chevron" aria-hidden="true">
          {isExpanded ? '▼' : '▶'}
        </span>
      </button>
      {isExpanded && (
        <div id={`${id}-details`} className="consent-scope-details">
          <p>{scope.description}</p>
          {scope.highRisk && (
            <div className="consent-scope-warning" role="alert">
              <strong>High-risk permission:</strong> This scope requires additional verification.
            </div>
          )}
          {scope.provider && (
            <div className="consent-scope-provider">
              Provider: <span className="consent-provider-badge">{scope.provider}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function ConsentModal(): React.JSX.Element | null {
  const { respondToConsent, nextConsentRequest } = useAuth();
  const request = nextConsentRequest;

  const modalRef = useRef<HTMLDivElement>(null);
  const approveButtonRef = useRef<HTMLButtonElement>(null);
  const [expandedScopes, setExpandedScopes] = useState<Set<string>>(new Set());
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showDenyConfirm, setShowDenyConfirm] = useState(false);

  // Handle closing the modal - snooze the request
  const onClose = useCallback(() => {
    if (request) {
      respondToConsent(request.id, 'snooze');
    }
  }, [request, respondToConsent]);

  // Focus management - trap focus within modal
  useEffect(() => {
    // Only set up focus trap when we have a request
    if (!request) return;

    const previousActiveElement = document.activeElement as HTMLElement;
    approveButtonRef.current?.focus();

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
      if (e.key === 'Tab') {
        const modal = modalRef.current;
        if (!modal) return;

        const focusableElements = modal.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        if (e.shiftKey && document.activeElement === firstElement) {
          e.preventDefault();
          lastElement.focus();
        } else if (!e.shiftKey && document.activeElement === lastElement) {
          e.preventDefault();
          firstElement.focus();
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      previousActiveElement?.focus();
    };
  }, [onClose, request]);

  // Emit telemetry on mount
  useEffect(() => {
    if (!request) return;
    console.debug('[Consent Telemetry] auth_consent_prompt_shown', {
      consent_request_id: request.id,
      agent_id: request.agentId,
      scopes: request.scopes.map(s => s.name),
      surface: 'WEB',
    });
  }, [request]);

  const toggleScope = useCallback((scopeName: string) => {
    if (!request) return;
    setExpandedScopes(prev => {
      const next = new Set(prev);
      if (next.has(scopeName)) {
        next.delete(scopeName);
      } else {
        next.add(scopeName);
        // Telemetry: user viewed details
        console.debug('[Consent Telemetry] auth_consent_details_viewed', {
          consent_request_id: request.id,
          scope_viewed: scopeName,
        });
      }
      return next;
    });
  }, [request]);

  const handleDecision = useCallback(async (decision: ConsentDecision) => {
    if (!request) return;

    setIsSubmitting(true);
    const startTime = Date.now();

    try {
      await respondToConsent(request.id, decision);

      // Telemetry with latency
      const eventMap: Record<ConsentDecision, string> = {
        approve: 'auth_consent_approved',
        deny: 'auth_consent_denied',
        snooze: 'auth_consent_snoozed',
      };
      console.debug(`[Consent Telemetry] ${eventMap[decision]}`, {
        consent_request_id: request.id,
        agent_id: request.agentId,
        scopes: request.scopes.map(s => s.name),
        decision_latency_ms: Date.now() - startTime,
        surface: 'WEB',
      });

      onClose();
    } catch (error) {
      console.error('[ConsentModal] Decision failed:', error);
      setIsSubmitting(false);
    }
  }, [request, respondToConsent, onClose]);

  // Don't render if no consent request is pending
  if (!request) {
    return null;
  }

  const handleApprove = () => handleDecision('approve');
  const handleDeny = () => {
    if (!showDenyConfirm) {
      setShowDenyConfirm(true);
      return;
    }
    handleDecision('deny');
  };
  const handleSnooze = () => {
    if (request.snoozeCount >= request.maxSnoozes) {
      // Can't snooze anymore, show deny confirm instead
      setShowDenyConfirm(true);
      return;
    }
    handleDecision('snooze');
  };

  const hasHighRiskScopes = request.scopes.some(s => s.highRisk);
  const snoozesRemaining = request.maxSnoozes - request.snoozeCount;

  return (
    <div
      className="consent-modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="consent-modal-title"
      aria-describedby="consent-modal-description"
    >
      <div
        ref={modalRef}
        className="consent-modal"
        role="document"
      >
        {/* Header */}
        <div className="consent-modal-header">
          <div className="consent-agent-icon" aria-hidden="true">
            🤖
          </div>
          <div className="consent-header-text">
            <h2 id="consent-modal-title">
              Agent <strong>{request.agentName}</strong> needs your approval
            </h2>
            <p id="consent-modal-description" className="consent-purpose">
              {request.purpose}
            </p>
          </div>
          <button
            type="button"
            className="consent-close-button"
            onClick={onClose}
            aria-label="Close dialog"
            disabled={isSubmitting}
          >
            ✕
          </button>
        </div>

        {/* Tool info */}
        <div className="consent-tool-info">
          <span className="consent-tool-label">Requested tool:</span>
          <span className="consent-tool-name">{request.toolName}</span>
        </div>

        {/* Scope list */}
        <div className="consent-scopes">
          <h3 className="consent-section-title">Permissions requested</h3>
          <div className="consent-scope-list" role="list">
            {request.scopes.map(scope => (
              <ScopeItem
                key={scope.name}
                scope={scope}
                isExpanded={expandedScopes.has(scope.name)}
                onToggle={() => toggleScope(scope.name)}
              />
            ))}
          </div>
        </div>

        {/* Expiration & obligations */}
        <div className="consent-meta">
          <div className="consent-meta-item">
            <span className="consent-meta-icon" aria-hidden="true">⏱️</span>
            <span>
              Grant expires in <strong>{request.expirationDays} days</strong>
            </span>
          </div>
          {hasHighRiskScopes && (
            <div className="consent-meta-item consent-meta-warning">
              <span className="consent-meta-icon" aria-hidden="true">🔐</span>
              <span>
                <strong>MFA required:</strong> High-risk permissions require additional verification
              </span>
            </div>
          )}
        </div>

        {/* Deny confirmation */}
        {showDenyConfirm && (
          <div className="consent-deny-confirm" role="alert">
            <p>
              Are you sure you want to deny this request?
              <br />
              <strong>Action "{request.toolName}" will be cancelled.</strong>
            </p>
          </div>
        )}

        {/* Actions */}
        <div className="consent-actions">
          {!showDenyConfirm ? (
            <>
              <button
                ref={approveButtonRef}
                type="button"
                className="consent-button consent-button-primary"
                onClick={handleApprove}
                disabled={isSubmitting}
              >
                {isSubmitting ? 'Processing...' : 'Approve and continue'}
              </button>
              <button
                type="button"
                className="consent-button consent-button-secondary"
                onClick={handleDeny}
                disabled={isSubmitting}
              >
                Deny request
              </button>
              {snoozesRemaining > 0 && (
                <button
                  type="button"
                  className="consent-button consent-button-tertiary"
                  onClick={handleSnooze}
                  disabled={isSubmitting}
                >
                  Remind me later ({snoozesRemaining} remaining)
                </button>
              )}
            </>
          ) : (
            <>
              <button
                type="button"
                className="consent-button consent-button-danger"
                onClick={handleDeny}
                disabled={isSubmitting}
              >
                {isSubmitting ? 'Processing...' : `Deny and cancel ${request.toolName}`}
              </button>
              <button
                type="button"
                className="consent-button consent-button-secondary"
                onClick={() => setShowDenyConfirm(false)}
                disabled={isSubmitting}
              >
                Go back
              </button>
            </>
          )}
        </div>

        {/* Snooze limit warning */}
        {request.snoozeCount > 0 && snoozesRemaining === 1 && (
          <p className="consent-snooze-warning" role="status">
            ⚠️ Last snooze available. Next time you'll need to approve or deny.
          </p>
        )}
      </div>
    </div>
  );
}

export default ConsentModal;
