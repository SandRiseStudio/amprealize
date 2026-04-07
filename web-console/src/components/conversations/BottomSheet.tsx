/**
 * BottomSheet — mobile-first drawer that slides up from the bottom.
 *
 * Used by ConversationPanel on narrow viewports (< 768px).
 * Supports drag-to-dismiss and touch-friendly interactions.
 */

import { memo, useCallback, useEffect, useRef, useState } from 'react';
import './BottomSheet.css';

// ── Types ────────────────────────────────────────────────────────────────────

type SheetPhase = 'entering' | 'open' | 'closing';

export interface BottomSheetProps {
  children: React.ReactNode;
  onRequestClose: () => void;
  title?: string;
  maxHeight?: string;
}

// ── Component ────────────────────────────────────────────────────────────────

export const BottomSheet = memo(function BottomSheet({
  children,
  onRequestClose,
  title,
  maxHeight = '70vh',
}: BottomSheetProps) {
  const sheetRef = useRef<HTMLDivElement>(null);
  const prevFocusRef = useRef<HTMLElement | null>(null);
  const [phase, setPhase] = useState<SheetPhase>('entering');
  const dragStartY = useRef<number | null>(null);
  const currentTranslateY = useRef(0);

  // ── Animate in ─────────────────────────────────────────────────────────────
  useEffect(() => {
    prevFocusRef.current = document.activeElement as HTMLElement;
    const id = requestAnimationFrame(() => setPhase('open'));
    return () => cancelAnimationFrame(id);
  }, []);

  // ── Restore focus on unmount ───────────────────────────────────────────────
  useEffect(() => {
    return () => {
      prevFocusRef.current?.focus?.();
    };
  }, []);

  // ── Close handler with exit animation ──────────────────────────────────────
  const requestClose = useCallback(() => {
    if (phase === 'closing') return;
    setPhase('closing');
    setTimeout(() => onRequestClose(), 220);
  }, [onRequestClose, phase]);

  // ── Escape key ─────────────────────────────────────────────────────────────
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.stopPropagation();
        requestClose();
      }
    }
    document.addEventListener('keydown', handleKeyDown, true);
    return () => document.removeEventListener('keydown', handleKeyDown, true);
  }, [requestClose]);

  // ── Scrim click = close ────────────────────────────────────────────────────
  const handleScrimClick = useCallback(
    (e: React.MouseEvent) => {
      if ((e.target as HTMLElement).classList.contains('bottom-sheet-scrim')) {
        requestClose();
      }
    },
    [requestClose],
  );

  // ── Drag to dismiss ────────────────────────────────────────────────────────
  const handleDragStart = useCallback((e: React.TouchEvent | React.MouseEvent) => {
    const clientY = 'touches' in e ? e.touches[0].clientY : e.clientY;
    dragStartY.current = clientY;
    currentTranslateY.current = 0;
  }, []);

  const handleDragMove = useCallback((e: React.TouchEvent | React.MouseEvent) => {
    if (dragStartY.current === null || !sheetRef.current) return;
    const clientY = 'touches' in e ? e.touches[0].clientY : e.clientY;
    const deltaY = clientY - dragStartY.current;

    // Only allow dragging down
    if (deltaY < 0) return;

    currentTranslateY.current = deltaY;
    sheetRef.current.style.transform = `translateY(${deltaY}px)`;
  }, []);

  const handleDragEnd = useCallback(() => {
    if (dragStartY.current === null || !sheetRef.current) return;

    const threshold = 100; // px to trigger dismiss
    if (currentTranslateY.current > threshold) {
      requestClose();
    } else {
      // Snap back
      sheetRef.current.style.transition = 'transform 0.2s ease';
      sheetRef.current.style.transform = 'translateY(0)';
      setTimeout(() => {
        if (sheetRef.current) {
          sheetRef.current.style.transition = '';
        }
      }, 200);
    }

    dragStartY.current = null;
    currentTranslateY.current = 0;
  }, [requestClose]);

  const phaseClass = phase === 'entering' ? '' : phase;

  return (
    <div
      className={`bottom-sheet-scrim ${phaseClass}`}
      onClick={handleScrimClick}
      role="dialog"
      aria-modal="true"
      aria-label={title ?? 'Bottom sheet'}
    >
      <div
        ref={sheetRef}
        className="bottom-sheet"
        style={{ maxHeight }}
      >
        {/* Drag handle */}
        <div
          className="bottom-sheet-handle"
          onTouchStart={handleDragStart}
          onTouchMove={handleDragMove}
          onTouchEnd={handleDragEnd}
          onMouseDown={handleDragStart}
          onMouseMove={handleDragMove}
          onMouseUp={handleDragEnd}
          onMouseLeave={handleDragEnd}
          role="button"
          aria-label="Drag to dismiss"
          tabIndex={0}
        >
          <div className="bottom-sheet-handle-bar" />
        </div>

        {/* Header */}
        {title && (
          <div className="bottom-sheet-header">
            <h2 className="bottom-sheet-title">{title}</h2>
            <button
              type="button"
              className="bottom-sheet-close pressable"
              onClick={requestClose}
              aria-label="Close"
              data-haptic="light"
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
                <path d="M4 4l8 8M12 4l-8 8" />
              </svg>
            </button>
          </div>
        )}

        {/* Content */}
        <div className="bottom-sheet-content">
          {children}
        </div>
      </div>
    </div>
  );
});
