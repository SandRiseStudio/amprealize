/**
 * AgentAssignmentDrawer
 *
 * Board-level agent management drawer. Lists assigned agents with
 * presence info and allows unassigning; includes a search section
 * to add new agents from the registry.
 *
 * Opens from the "Manage" action in the AgentPresenceDrawer or
 * board toolbar.
 *
 * Same UX bones as AgentPresenceDrawer: glassmorphic, GPU transitions,
 * focus trap, Escape dismissal, focus restoration.
 */

import React, { useCallback, useEffect, useRef, useState, useMemo } from 'react';
import type { AgentPresence } from '../../hooks/useAgentPresence';
import { PRESENCE_COLORS, PRESENCE_LABELS } from '../../hooks/useAgentPresence';
import {
  useAgentRegistry,
  useAssignAgent,
  useUnassignAgent,
  type AgentRegistryEntry,
  type AgentRegistryListItem,
} from '../../api/agentRegistry';
import type { Agent } from '../../api/dashboard';
import './AgentAssignmentDrawer.css';

export interface AgentAssignmentDrawerProps {
  presences: AgentPresence[];
  projectAgents: Agent[];
  projectId: string;
  open: boolean;
  onClose: () => void;
}

export const AgentAssignmentDrawer: React.FC<AgentAssignmentDrawerProps> = ({
  presences,
  projectAgents,
  projectId,
  open,
  onClose,
}) => {
  const drawerRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const [search, setSearch] = useState('');
  const [pendingRemoveId, setPendingRemoveId] = useState<string | null>(null);

  const assignAgent = useAssignAgent();
  const unassignAgent = useUnassignAgent();

  // Registry search for adding agents
  const { data: registryResults } = useAgentRegistry({
    query: search.trim().length >= 2 ? search.trim() : '',
    status: 'ACTIVE',
  });

  // Build presence lookup
  const presenceMap = useMemo(() => {
    const map = new Map<string, AgentPresence>();
    for (const p of presences) {
      map.set(p.agentId, p);
    }
    return map;
  }, [presences]);

  // IDs already assigned
  const assignedIds = useMemo(() => {
    const ids = new Set<string>();
    for (const a of projectAgents) {
      ids.add(a.id);
      // Also track registry reference
      const registryId = (a.config as Record<string, unknown> | undefined)?.registry_agent_id;
      if (typeof registryId === 'string') ids.add(registryId);
    }
    return ids;
  }, [projectAgents]);

  // Filter registry results to exclude already-assigned agents
  const addableAgents = useMemo((): AgentRegistryEntry[] => {
    if (!registryResults) return [];
    const items = registryResults as AgentRegistryListItem[];
    return items
      .map((item) => item.agent)
      .filter((a) => !assignedIds.has(a.agent_id));
  }, [registryResults, assignedIds]);

  const handleClose = useCallback(() => {
    setPendingRemoveId(null);
    setSearch('');
    onClose();
  }, [onClose]);

  // Focus trap
  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;

    requestAnimationFrame(() => {
      const first = drawerRef.current?.querySelector<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      first?.focus();
    });

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        handleClose();
        return;
      }
      if (e.key === 'Tab' && drawerRef.current) {
        const focusable = drawerRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      previousFocusRef.current?.focus();
    };
  }, [open, handleClose]);

  const handleScrimClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === e.currentTarget) handleClose();
    },
    [handleClose],
  );

  const handleRemove = useCallback(
    (agent: Agent) => {
      if (pendingRemoveId === agent.id) {
        // Confirm removal
        unassignAgent.mutate(
          { assignmentId: agent.id },
          { onSettled: () => setPendingRemoveId(null) },
        );
      } else {
        setPendingRemoveId(agent.id);
      }
    },
    [pendingRemoveId, unassignAgent],
  );

  const handleAdd = useCallback(
    (entry: AgentRegistryEntry) => {
      assignAgent.mutate({
        agent: entry,
        projectId,
      });
    },
    [assignAgent, projectId],
  );

  if (!open) return null;

  return (
    <div
      className="agent-assignment-drawer-scrim"
      onClick={handleScrimClick}
      aria-hidden="true"
    >
      <aside
        ref={drawerRef}
        className="agent-assignment-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="assignment-drawer-title"
      >
        <div className="assignment-drawer-header">
          <h2 id="assignment-drawer-title" className="assignment-drawer-title">
            Manage agents
          </h2>
          <button
            type="button"
            className="assignment-drawer-close pressable"
            onClick={handleClose}
            aria-label="Close agent management"
            data-haptic="light"
          >
            ✕
          </button>
        </div>

        <div className="assignment-drawer-body">
          {/* Assigned agents */}
          <section className="assignment-drawer-section">
            <h3 className="assignment-drawer-section-title">
              Assigned ({projectAgents.length})
            </h3>
            {projectAgents.length === 0 && (
              <p className="assignment-drawer-empty">No agents assigned to this project yet.</p>
            )}
            <ul className="assignment-drawer-list" role="list">
              {projectAgents.map((agent) => {
                const presence = presenceMap.get(agent.id);
                const isConfirming = pendingRemoveId === agent.id;
                return (
                  <li key={agent.id} className="assignment-drawer-row">
                    <span className="assignment-drawer-row-avatar">
                      <span className="assignment-drawer-row-initials">
                        {agent.name.slice(0, 2).toUpperCase()}
                      </span>
                      {presence && (
                        <span
                          className="assignment-drawer-row-dot"
                          style={{ backgroundColor: PRESENCE_COLORS[presence.presence] }}
                          aria-hidden="true"
                        />
                      )}
                    </span>
                    <span className="assignment-drawer-row-info">
                      <span className="assignment-drawer-row-name">{agent.name}</span>
                      <span className="assignment-drawer-row-status">
                        {presence
                          ? PRESENCE_LABELS[presence.presence]
                          : agent.status?.toLowerCase() ?? 'Unknown'}
                      </span>
                    </span>
                    <button
                      type="button"
                      className={`assignment-drawer-row-action pressable ${isConfirming ? 'assignment-drawer-row-action-danger' : ''}`}
                      onClick={() => handleRemove(agent)}
                      disabled={unassignAgent.isPending}
                      data-haptic="light"
                    >
                      {isConfirming ? 'Confirm' : 'Remove'}
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>

          {/* Add from registry */}
          <section className="assignment-drawer-section">
            <h3 className="assignment-drawer-section-title">Add from registry</h3>
            <input
              type="text"
              className="assignment-drawer-search"
              placeholder="Search agents…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search agent registry"
            />
            {search.trim().length >= 2 && addableAgents.length === 0 && (
              <p className="assignment-drawer-empty">No matching agents found.</p>
            )}
            {search.trim().length < 2 && (
              <p className="assignment-drawer-hint">Type at least 2 characters to search.</p>
            )}
            <ul className="assignment-drawer-list" role="list">
              {addableAgents.map((entry) => (
                <li key={entry.agent_id} className="assignment-drawer-row">
                  <span className="assignment-drawer-row-avatar">
                    <span className="assignment-drawer-row-initials">
                      {entry.name.slice(0, 2).toUpperCase()}
                    </span>
                  </span>
                  <span className="assignment-drawer-row-info">
                    <span className="assignment-drawer-row-name">{entry.name}</span>
                    <span className="assignment-drawer-row-status">
                      {entry.description || entry.slug}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="assignment-drawer-row-action assignment-drawer-row-action-add pressable"
                    onClick={() => handleAdd(entry)}
                    disabled={assignAgent.isPending}
                    data-haptic="light"
                  >
                    Add
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </aside>
    </div>
  );
};
