/**
 * InlineAssigneePopover
 *
 * Compact, glassmorphic inline dropdown for assigning work items directly from
 * the card. Renders inside the card flow (no portal) so it naturally expands
 * the card and scrolls with the column.
 *
 * Visual language matches BoardAgentPresenceRail.
 *
 * Features:
 * - Type-ahead search filtering
 * - Presence-aware agent grouping (Available / Working / Offline)
 * - Keyboard navigation (arrows, Enter, Escape)
 * - All events fully isolated — clicks never propagate to the card
 */

import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActorAvatar } from '../actors/ActorAvatar';
import type { AssigneeProfile } from './WorkItemDrawer';
import './InlineAssigneePopover.css';

// ── Types ──────────────────────────────────────────────────────────────────

export interface InlineAssigneePopoverProps {
  /** All assignable humans */
  assignableHumans: AssigneeProfile[];
  /** All assignable agents */
  assignableAgents: AssigneeProfile[];
  /** Currently assigned profile (null if unassigned) */
  currentAssignee: AssigneeProfile | null;
  /** Called when user picks an assignee */
  onAssign: (profile: AssigneeProfile) => void;
  /** Called when user unassigns */
  onUnassign: () => void;
  /** Called to close the popover */
  onClose: () => void;
  /** Whether an assignment mutation is in flight */
  isPending?: boolean;
}

// ── Helpers ────────────────────────────────────────────────────────────────

interface AssigneeGroup {
  key: string;
  label: string;
  items: AssigneeProfile[];
}

function groupAssignees(
  humans: AssigneeProfile[],
  agents: AssigneeProfile[],
  search: string,
): AssigneeGroup[] {
  const q = search.trim().toLowerCase();
  const match = (p: AssigneeProfile) =>
    !q ||
    p.label.toLowerCase().includes(q) ||
    (p.subtitle ?? '').toLowerCase().includes(q);

  const groups: AssigneeGroup[] = [];

  const filteredHumans = humans.filter(match);
  if (filteredHumans.length > 0) {
    groups.push({ key: 'people', label: 'People', items: filteredHumans });
  }

  const filteredAgents = agents.filter(match);
  if (filteredAgents.length > 0) {
    const available: AssigneeProfile[] = [];
    const working: AssigneeProfile[] = [];
    const offline: AssigneeProfile[] = [];

    for (const agent of filteredAgents) {
      const p = agent.presence;
      if (p === 'working' || p === 'at_capacity') {
        working.push(agent);
      } else if (p === 'available' || p === 'finished_recently') {
        available.push(agent);
      } else {
        offline.push(agent);
      }
    }

    if (available.length > 0) groups.push({ key: 'available', label: 'Available now', items: available });
    if (working.length > 0) groups.push({ key: 'working', label: 'Working', items: working });
    if (offline.length > 0) groups.push({ key: 'offline', label: 'Paused / Offline', items: offline });

    // If no presence data, show flat agent group
    if (available.length === 0 && working.length === 0 && offline.length === 0) {
      groups.push({ key: 'agents', label: 'Agents', items: filteredAgents });
    }
  }

  return groups;
}

function flatProfiles(groups: AssigneeGroup[]): AssigneeProfile[] {
  return groups.flatMap((g) => g.items);
}

/** Swallow every event so nothing reaches the card */
function stopAll(e: React.SyntheticEvent) {
  e.stopPropagation();
}

// ── Component ──────────────────────────────────────────────────────────────

export const InlineAssigneePopover = memo(function InlineAssigneePopover({
  assignableHumans,
  assignableAgents,
  currentAssignee,
  onAssign,
  onUnassign,
  onClose,
  isPending,
}: InlineAssigneePopoverProps) {
  const [search, setSearch] = useState('');
  const [focusIndex, setFocusIndex] = useState(-1);
  const [isClosing, setIsClosing] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const optionRefs = useRef<Map<string, HTMLButtonElement>>(new Map());

  // ── Grouped data ───────────────────────────────────────────────────────

  const groups = useMemo(
    () => groupAssignees(assignableHumans, assignableAgents, search),
    [assignableHumans, assignableAgents, search],
  );
  const flat = useMemo(() => flatProfiles(groups), [groups]);

  // ── Focus search on mount ──────────────────────────────────────────────

  useEffect(() => {
    const timer = requestAnimationFrame(() => searchRef.current?.focus());
    return () => cancelAnimationFrame(timer);
  }, []);

  // ── Click-outside to close (native DOM, not React synthetic) ───────────

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const target = e.target;
      if (!(target instanceof Node)) return;
      // Pill / compact assignee are siblings of this popover, not inside popoverRef — ignore them
      if (target instanceof Element && target.closest('[data-inline-assignee-control]')) return;
      if (popoverRef.current?.contains(target)) return;
      onClose();
    };
    let cancelled = false;
    let raf1 = 0;
    let raf2 = 0;
    // Defer past the opening click + paint so the trigger gesture cannot close us.
    raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => {
        if (cancelled) return;
        document.addEventListener('mousedown', handler, true);
      });
    });
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
      document.removeEventListener('mousedown', handler, true);
    };
  }, [onClose]);

  // ── Selection handler ──────────────────────────────────────────────────

  const handleSelect = useCallback(
    (profile: AssigneeProfile) => {
      if (isPending) return;

      const isCurrentlyAssigned =
        currentAssignee && currentAssignee.type === profile.type && currentAssignee.id === profile.id;

      if (isCurrentlyAssigned) {
        onUnassign();
      } else {
        onAssign(profile);
      }

      // Animate close
      setIsClosing(true);
      setTimeout(() => onClose(), 180);
    },
    [currentAssignee, isPending, onAssign, onClose, onUnassign],
  );

  // ── Keyboard navigation ────────────────────────────────────────────────

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      e.stopPropagation(); // always isolate from card
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setFocusIndex((prev) => Math.min(prev + 1, flat.length - 1));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setFocusIndex((prev) => Math.max(prev - 1, -1));
        return;
      }
      if (e.key === 'Enter' && focusIndex >= 0 && focusIndex < flat.length) {
        e.preventDefault();
        const profile = flat[focusIndex];
        if (profile) handleSelect(profile);
      }
    },
    [flat, focusIndex, handleSelect, onClose],
  );

  // ── Scroll focused option into view ────────────────────────────────────

  useEffect(() => {
    if (focusIndex < 0 || focusIndex >= flat.length) return;
    const profile = flat[focusIndex];
    if (!profile) return;
    const el = optionRefs.current.get(`${profile.type}:${profile.id}`);
    el?.scrollIntoView({ block: 'nearest' });
  }, [focusIndex, flat]);

  // ── Unassign action ────────────────────────────────────────────────────

  const handleUnassign = useCallback(() => {
    if (isPending || !currentAssignee) return;
    onUnassign();
    setIsClosing(true);
    setTimeout(() => onClose(), 180);
  }, [currentAssignee, isPending, onClose, onUnassign]);

  // ── Register option refs ───────────────────────────────────────────────

  const setOptionRef = useCallback((key: string, el: HTMLButtonElement | null) => {
    if (el) {
      optionRefs.current.set(key, el);
    } else {
      optionRefs.current.delete(key);
    }
  }, []);

  const isAssigned = Boolean(currentAssignee);

  return (
    <div
      ref={popoverRef}
      className={`iap-popover ${isClosing ? 'iap-popover-closing' : 'iap-popover-entering'}`}
      role="dialog"
      aria-label="Assign work item"
      onKeyDown={handleKeyDown}
      onClick={stopAll}
      onMouseDown={stopAll}
      onMouseUp={stopAll}
      onPointerDown={stopAll}
      onDragStart={(e) => { e.preventDefault(); e.stopPropagation(); }}
    >
      {/* Search */}
      <div className="iap-search-wrapper">
        <input
          ref={searchRef}
          className="iap-search"
          type="text"
          placeholder="Search people & agents..."
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setFocusIndex(-1);
          }}
          aria-label="Search assignees"
          autoComplete="off"
          spellCheck={false}
        />
      </div>

      {/* Scrollable options */}
      <div className="iap-options-scroll">
        {groups.length === 0 && (
          <div className="iap-empty">No matches</div>
        )}
        {groups.map((group) => (
          <div key={group.key} className="iap-group">
            <div className="iap-group-label">{group.label}</div>
            <div className="iap-group-options">
              {group.items.map((profile) => {
                const key = `${profile.type}:${profile.id}`;
                const globalIdx = flat.indexOf(profile);
                const isFocused = globalIdx === focusIndex;
                const isCurrent =
                  currentAssignee && currentAssignee.type === profile.type && currentAssignee.id === profile.id;

                return (
                  <button
                    key={key}
                    ref={(el) => setOptionRef(key, el)}
                    type="button"
                    className={`iap-option${isFocused ? ' iap-option-focused' : ''}${isCurrent ? ' iap-option-selected' : ''}`}
                    onClick={() => handleSelect(profile)}
                    onMouseEnter={() => setFocusIndex(globalIdx)}
                    aria-pressed={isCurrent ? 'true' : 'false'}
                    data-haptic="light"
                  >
                    <span className="iap-option-avatar">
                      {profile.actor ? (
                        <ActorAvatar actor={profile.actor} size="sm" surfaceType="chip" decorative />
                      ) : (
                        <span className="iap-option-avatar-initials">{profile.avatar ?? '?'}</span>
                      )}
                    </span>
                    <span className="iap-option-text">
                      <span className="iap-option-name">{profile.label}</span>
                      {profile.subtitle && <span className="iap-option-subtitle">{profile.subtitle}</span>}
                    </span>
                    {profile.type === 'agent' && profile.presence && (
                      <span className={`iap-option-presence iap-option-presence-${profile.presence}`} />
                    )}
                    {isCurrent && (
                      <span className="iap-option-check" aria-hidden="true">✓</span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        ))}

        {/* Unassign action */}
        {isAssigned && (
          <div className="iap-unassign-section">
            <button
              type="button"
              className="iap-unassign-btn"
              onClick={handleUnassign}
              data-haptic="light"
            >
              <span className="iap-unassign-icon" aria-hidden="true">×</span>
              Remove assignment
            </button>
          </div>
        )}
      </div>
    </div>
  );
});
