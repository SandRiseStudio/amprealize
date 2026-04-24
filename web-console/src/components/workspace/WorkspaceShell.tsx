/**
 * WorkspaceShell Component
 *
 * Internal application shell for the web console.
 *
 * Note: the name is kept for compatibility, but user-facing copy should prefer
 * Personal / Organization / Scope terminology instead of "workspace".
 *
 * High-performance collaborative shell with:
 * - Smooth sidebar collapse animation
 * - Presence indicators
 * - Command palette ready
 * - Optimized rendering via memo + refs
 */

import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useCollabStore, collabStore, usePresenceList } from '../../store/collabStore';
import { useAuth } from '../../auth';
import { useOrganizations, useProject } from '../../api/dashboard';
import { useProjectAgents } from '../../api/agentRegistry';
import { useExecutionList, useExecutionStream } from '../../api/executions';
import {
  CURRENT_SCOPE_LABEL,
  NEW_PROJECT_CTA,
  PERSONAL_SCOPE_LABEL,
} from '../../copy/scopeLabels';
import { OrgSwitcher } from '../OrgSwitcher';
import { orgContextStore, useOrgContext } from '../../store/orgContextStore';
import { ActorAvatar } from '../actors/ActorAvatar';
import { BrandLogo } from '../branding/BrandLogo';
import { toActorViewModel } from '../../utils/actorViewModel';
import { ProfileMenu } from './ProfileMenu';
import { PRODUCT_DISPLAY_NAME } from '../../config/branding';
import { useApiPlatformRuntime } from '../../api/platformRuntime';
import './WorkspaceShell.css';

function formatVersionLabel(raw: string): string {
  const t = raw.trim();
  if (!t) return 'v0.1.0';
  if (t.startsWith('v') || t.startsWith('V')) return t;
  return `v${t}`;
}

/** Compact semver for the narrow sidebar rail (full value stays in `title`). */
function shortVersionForRail(raw: string): string {
  const v = formatVersionLabel(raw);
  const m = /^v?(\d+\.\d+)(?:\.\d+)?/i.exec(v);
  if (m) return `v${m[1]}`;
  return v;
}

function railDistributionLabel(distribution: 'oss' | 'enterprise' | undefined): string {
  return distribution === 'enterprise' ? 'ENT' : 'OSS';
}

function railEditionAbbrev(edition: 'starter' | 'premium'): string {
  return edition === 'premium' ? 'Pr' : 'St';
}

type ShellPresenceStatus = 'active' | 'idle' | 'away' | 'disconnected';

interface ShellPresenceParticipant {
  user_id: string;
  display_name?: string;
  color?: string;
  status: ShellPresenceStatus;
}

// ---------------------------------------------------------------------------
// Presence Avatar Component
// ---------------------------------------------------------------------------

interface PresenceAvatarProps {
  id: string;
  name: string;
  color: string;
  status: ShellPresenceStatus;
  showStatus?: boolean;
}

const PresenceAvatar = memo(function PresenceAvatar({
  id,
  name,
  color,
  status,
  showStatus = true,
}: PresenceAvatarProps) {
  const participantStatus = status === 'disconnected' ? 'away' : status;
  const actor = toActorViewModel(
    { user_id: id, display_name: name, color, status: participantStatus },
    { presenceState: status === 'active' ? 'working' : status === 'idle' ? 'available' : status === 'away' ? 'paused' : 'offline' },
  );

  return (
    <div className="presence-avatar" style={{ '--avatar-color': color } as React.CSSProperties}>
      <ActorAvatar actor={actor} size="sm" surfaceType="rail" decorative className="presence-avatar-image" />
      {showStatus && (
        <span
          className={`presence-avatar-status presence-status-${status}`}
          aria-label={`Status: ${status}`}
        />
      )}
    </div>
  );
});

// ---------------------------------------------------------------------------
// Sidebar Component
// ---------------------------------------------------------------------------

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  children?: React.ReactNode;
}

const Sidebar = memo(function Sidebar({ collapsed, onToggle, children }: SidebarProps) {
  const sidebarRef = useRef<HTMLElement>(null);
  const { data: runtime } = useApiPlatformRuntime();
  const versionFull = formatVersionLabel(runtime?.version ?? '0.1.0');
  const versionShort = shortVersionForRail(runtime?.version ?? '0.1.0');
  const distRail = railDistributionLabel(runtime?.distribution);
  const distFull = runtime?.distribution === 'enterprise' ? 'Enterprise' : 'OSS';
  const edition = runtime?.edition ?? null;
  const contextName = runtime?.context_name ?? 'unknown';

  const runtimePillText = useMemo(() => {
    const segments = [`${distRail} ${versionShort}`];
    if (edition) segments.push(railEditionAbbrev(edition));
    segments.push(contextName);
    return segments.join(' · ');
  }, [contextName, distRail, edition, versionShort]);

  const runtimePillTitle = useMemo(() => {
    const segments = [`${distFull} ${versionFull}`];
    if (edition) segments.push(edition === 'premium' ? 'Premium' : 'Starter');
    segments.push(contextName);
    return segments.join(' · ');
  }, [contextName, distFull, edition, versionFull]);

  return (
    <aside
      ref={sidebarRef}
      className={`workspace-sidebar ${collapsed ? 'collapsed' : ''}`}
      aria-label="Primary navigation"
    >
      <div className="sidebar-header">
        <button
          className="sidebar-toggle pressable"
          onClick={onToggle}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          data-haptic="light"
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            className={`sidebar-toggle-icon ${collapsed ? 'rotated' : ''}`}
          >
            <path
              d="M10.5 3.5L5.5 8L10.5 12.5"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
        {!collapsed && (
          <div className="sidebar-brand animate-fade-in-up">
            <div className="sidebar-lockup-surface">
              <BrandLogo variant="lockup" alt={PRODUCT_DISPLAY_NAME} className="sidebar-brand-lockup" />
            </div>
          </div>
        )}
      </div>

      <nav className="sidebar-nav">{children}</nav>

      <div className="sidebar-footer">
        <div className="sidebar-footer-profile">
          <ProfileMenu compact={collapsed} dropdownPosition="top" />
        </div>
        {!collapsed && (
          <div className="sidebar-footer-meta" aria-label="Runtime environment">
            <span className="sidebar-chip sidebar-chip--runtime" title={runtimePillTitle}>
              {runtimePillText}
            </span>
          </div>
        )}
      </div>
    </aside>
  );
});

// ---------------------------------------------------------------------------
// Header Component
// ---------------------------------------------------------------------------

interface HeaderProps {
  documentTitle?: string;
  connectionState: string;
  presenceList: ShellPresenceParticipant[];
}

const Header = memo(function Header({ documentTitle, connectionState, presenceList }: HeaderProps) {
  const { actor, logout, isAuthenticated } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const { data: organizations = [] } = useOrganizations();
  const { currentOrgId } = useOrgContext();
  const sortedOrganizations = useMemo(
    () => [...organizations].sort((a, b) => a.name.localeCompare(b.name)),
    [organizations]
  );
  const [commandPaletteHint, setCommandPaletteHint] = useState(false);
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const profileMenuRef = useRef<HTMLDivElement>(null);
  const profileTriggerRef = useRef<HTMLButtonElement>(null);
  const { projectId } = useParams();
  const surfaceLabel = useMemo(() => {
    if (location.pathname === '/') return 'Home';
    if (location.pathname.startsWith('/projects')) return 'Projects';
    if (location.pathname.startsWith('/agents')) return 'Agents';
    if (location.pathname.startsWith('/orgs')) return 'Organizations';
    if (location.pathname.startsWith('/bci') || location.pathname.startsWith('/whiteboard')) return 'Studio';
    if (location.pathname.startsWith('/settings')) return 'Settings';
    return PRODUCT_DISPLAY_NAME;
  }, [location.pathname]);

  const resolvedDocumentTitle = documentTitle ?? 'Untitled';
  const showDocumentTitle = useMemo(() => {
    return resolvedDocumentTitle.trim().toLocaleLowerCase() !== surfaceLabel.trim().toLocaleLowerCase();
  }, [resolvedDocumentTitle, surfaceLabel]);

  const displayName = actor?.displayName ?? actor?.email ?? actor?.id ?? 'Profile';
  const initials = displayName
    .split(' ')
    .map((segment) => segment[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();

  // Show cmd+K hint on hover
  const handleKeyHint = useCallback(() => {
    setCommandPaletteHint(true);
    const timer = setTimeout(() => setCommandPaletteHint(false), 2000);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (!profileMenuRef.current) return;
      if (!profileMenuRef.current.contains(event.target as Node)) {
        setProfileMenuOpen(false);
      }
    }

    if (profileMenuOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [profileMenuOpen]);

  const focusProfileMenuItem = useCallback((target: 'first' | 'last' | number) => {
    const items = profileMenuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]');
    if (!items?.length) return;

    if (target === 'first') {
      items[0]?.focus();
      return;
    }

    if (target === 'last') {
      items[items.length - 1]?.focus();
      return;
    }

    items[target]?.focus();
  }, []);

  const closeProfileMenu = useCallback((restoreFocus = false) => {
    setProfileMenuOpen(false);
    if (restoreFocus) {
      window.requestAnimationFrame(() => profileTriggerRef.current?.focus());
    }
  }, []);

  useEffect(() => {
    if (!profileMenuOpen) return;
    window.requestAnimationFrame(() => focusProfileMenuItem('first'));
  }, [focusProfileMenuItem, profileMenuOpen]);

  const handleProfileTriggerKeyDown = useCallback((event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setProfileMenuOpen(true);
      window.requestAnimationFrame(() => focusProfileMenuItem('first'));
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setProfileMenuOpen(true);
      window.requestAnimationFrame(() => focusProfileMenuItem('last'));
      return;
    }

    if (event.key === 'Escape' && profileMenuOpen) {
      event.preventDefault();
      closeProfileMenu(true);
    }
  }, [closeProfileMenu, focusProfileMenuItem, profileMenuOpen]);

  const handleProfileMenuKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    const items = profileMenuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]');
    if (!items?.length) return;
    const currentIndex = Array.from(items).indexOf(document.activeElement as HTMLButtonElement);

    if (event.key === 'Escape') {
      event.preventDefault();
      closeProfileMenu(true);
      return;
    }

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      const nextIndex = currentIndex < 0 ? 0 : (currentIndex + 1) % items.length;
      items[nextIndex]?.focus();
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      const nextIndex = currentIndex <= 0 ? items.length - 1 : currentIndex - 1;
      items[nextIndex]?.focus();
      return;
    }

    if (event.key === 'Home') {
      event.preventDefault();
      items[0]?.focus();
      return;
    }

    if (event.key === 'End') {
      event.preventDefault();
      items[items.length - 1]?.focus();
      return;
    }

    if (event.key === 'Tab') {
      closeProfileMenu();
    }
  }, [closeProfileMenu]);

  useEffect(() => {
    if (!currentOrgId) return;
    const orgExists = organizations.some((org) => org.id === currentOrgId);
    if (!orgExists) {
      orgContextStore.setCurrentOrgId(null);
    }
  }, [currentOrgId, organizations]);

  const topAction = useMemo(() => {
    if (location.pathname === '/' || location.pathname === '/projects') {
      return {
        label: 'New Project',
        path: currentOrgId ? `/projects/new?org=${encodeURIComponent(currentOrgId)}` : '/projects/new',
      };
    }

    if (location.pathname.startsWith('/projects/') && !location.pathname.includes('/boards/') && projectId) {
      return {
        label: 'Create Board',
        path: `/projects/${projectId}?newBoard=1`,
      };
    }

    if (location.pathname.startsWith('/agents')) {
      return {
        label: 'New Agent',
        path: '/agents/new',
      };
    }

    if (location.pathname === '/bci') {
      return {
        label: 'Extract Behavior',
        path: '/bci/extraction',
      };
    }

    if (location.pathname === '/bci/extraction') {
      return {
        label: 'Behavior Search',
        path: '/bci',
      };
    }

    if (location.pathname === '/orgs') {
      return {
        label: 'Projects',
        path: '/projects',
      };
    }

    return null;
  }, [currentOrgId, location.pathname, projectId]);

  const showInvite = useMemo(
    () => location.pathname.startsWith('/projects/') || location.pathname.startsWith('/agents/'),
    [location.pathname]
  );

  return (
    <header className="workspace-header">
      <div className="header-left">
        <div className="header-context">
          <div className="header-scope-panel" aria-label={CURRENT_SCOPE_LABEL}>
            <OrgSwitcher
              organizations={sortedOrganizations}
              currentOrgId={currentOrgId}
              onSelect={(orgId) => orgContextStore.setCurrentOrgId(orgId)}
            />
          </div>

          <span className="header-scope-separator" aria-hidden="true">/</span>

          <div className="header-breadcrumb" aria-label="Current location">
            <span className="breadcrumb-surface">{surfaceLabel}</span>
            {showDocumentTitle && (
              <>
                <span className="breadcrumb-separator">/</span>
                <span className="breadcrumb-item current">{resolvedDocumentTitle}</span>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="header-center">
        <button
          className="command-palette-trigger pressable"
          onClick={() => collabStore.toggleCommandPalette()}
          onMouseEnter={handleKeyHint}
          aria-label="Open command palette"
          data-haptic="medium"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.5" />
            <path d="M11 11L14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <span>Jump to scopes, projects, boards, agents, and more…</span>
          {commandPaletteHint && (
            <kbd className="shortcut-hint animate-fade-in-up">⌘K</kbd>
          )}
        </button>
      </div>

      <div className="header-right">
        <div className={`connection-indicator connection-${connectionState}`}>
          <span className="connection-dot" />
          <span className="connection-label">
            {connectionState === 'connected' ? 'Live' : connectionState}
          </span>
        </div>

        <div className="presence-list" role="list" aria-label="Active collaborators">
          {presenceList.slice(0, 5).map((p) => (
            <PresenceAvatar
              key={p.user_id}
              id={p.user_id}
              name={p.display_name ?? p.user_id}
              color={p.color ?? '#3b82f6'}
              status={p.status}
            />
          ))}
          {presenceList.length > 5 && (
            <div className="presence-overflow">+{presenceList.length - 5}</div>
          )}
        </div>

        {topAction && (
          <button
            className="share-button pressable"
            data-haptic="medium"
            onClick={() => navigate(topAction.path)}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            {topAction.label === 'New Project' ? NEW_PROJECT_CTA : topAction.label}
          </button>
        )}

        {showInvite && (
          <button className="share-button share-button-secondary pressable" data-haptic="medium">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path
                d="M12 5.5C13.1046 5.5 14 4.60457 14 3.5C14 2.39543 13.1046 1.5 12 1.5C10.8954 1.5 10 2.39543 10 3.5C10 4.60457 10.8954 5.5 12 5.5Z"
                stroke="currentColor"
                strokeWidth="1.5"
              />
              <path
                d="M4 10C5.10457 10 6 9.10457 6 8C6 6.89543 5.10457 6 4 6C2.89543 6 2 6.89543 2 8C2 9.10457 2.89543 10 4 10Z"
                stroke="currentColor"
                strokeWidth="1.5"
              />
              <path
                d="M12 14.5C13.1046 14.5 14 13.6046 14 12.5C14 11.3954 13.1046 10.5 12 10.5C10.8954 10.5 10 11.3954 10 12.5C10 13.6046 10.8954 14.5 12 14.5Z"
                stroke="currentColor"
                strokeWidth="1.5"
              />
              <path d="M5.7 9.1L10.3 11.9" stroke="currentColor" strokeWidth="1.5" />
              <path d="M10.3 4.1L5.7 6.9" stroke="currentColor" strokeWidth="1.5" />
            </svg>
            Invite
          </button>
        )}

        {isAuthenticated && (
          <div className="profile-menu" ref={profileMenuRef}>
            <button
              ref={profileTriggerRef}
              type="button"
              className="profile-trigger pressable"
              onClick={() => setProfileMenuOpen((prev) => !prev)}
              onKeyDown={handleProfileTriggerKeyDown}
              aria-haspopup="menu"
              aria-expanded={profileMenuOpen}
              data-haptic="light"
            >
              <span className="profile-avatar">
                {actor?.avatarUrl ? (
                  <img
                    src={actor.avatarUrl}
                    alt={displayName}
                    className="profile-avatar-image"
                  />
                ) : (
                  <span className="profile-avatar-initials">{initials}</span>
                )}
              </span>
              <span className="profile-name">{displayName}</span>
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                <path
                  d="M3 4.5L6 7.5L9 4.5"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
            {profileMenuOpen && (
              <div className="profile-dropdown animate-scale-in" role="menu" aria-label="Profile menu" onKeyDown={handleProfileMenuKeyDown}>
                <div className="profile-dropdown-header">
                  <span className="profile-dropdown-name">{displayName}</span>
                  {actor?.email && (
                    <span className="profile-dropdown-subtitle">{actor.email}</span>
                  )}
                </div>
                <button
                  type="button"
                  className="profile-menu-item"
                  role="menuitem"
                  onClick={() => {
                    closeProfileMenu();
                    navigate('/settings');
                  }}
                >
                  Profile
                </button>
                <button
                  type="button"
                  className="profile-menu-item profile-menu-item-logout"
                  role="menuitem"
                  onClick={async () => {
                    closeProfileMenu();
                    await logout();
                  }}
                >
                  Log out
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </header>
  );
});

// ---------------------------------------------------------------------------
// Main Content Area
// ---------------------------------------------------------------------------

interface MainContentProps {
  children?: React.ReactNode;
}

const MainContent = memo(function MainContent({ children }: MainContentProps) {
  return (
    <main className="workspace-main">
      {children ?? (
        <div className="empty-state animate-fade-in-up">
          <div className="empty-state-icon">
            <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
              <rect
                x="6"
                y="10"
                width="36"
                height="28"
                rx="3"
                stroke="currentColor"
                strokeWidth="2"
              />
              <path d="M6 18H42" stroke="currentColor" strokeWidth="2" />
              <path d="M16 14V14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              <path d="M12 14V14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              <path d="M20 14V14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </div>
          <h2 className="empty-state-title">No document open</h2>
          <p className="empty-state-description">
            Create a new plan or select an existing document from the sidebar
          </p>
          <button className="empty-state-cta pressable" data-haptic="medium">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M8 3V13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              <path d="M3 8H13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            New Plan
          </button>
        </div>
      )}
    </main>
  );
});

// ---------------------------------------------------------------------------
// WorkspaceShell Container
// ---------------------------------------------------------------------------

export interface WorkspaceShellProps {
  children?: React.ReactNode;
  sidebarContent?: React.ReactNode;
  documentTitle?: string;
  /** When 'board', the shell header slims down: no breadcrumb, no center search. */
  mode?: 'default' | 'board';
}

export function WorkspaceShell({ children, sidebarContent, documentTitle, mode = 'default' }: WorkspaceShellProps) {
  const { sidebarCollapsed, connectionState, activeDocumentId, documents } = useCollabStore();
  const collabPresence = usePresenceList();
  const activeDocument = activeDocumentId ? documents.get(activeDocumentId) : null;
  const { projectId } = useParams();
  const { currentOrgId } = useOrgContext();
  const { data: project } = useProject(projectId);
  const liveOrgId = currentOrgId ?? project?.org_id ?? null;
  const { data: agents = [] } = useProjectAgents(projectId ?? null, {
    enabled: Boolean(projectId) && mode !== 'board',
  });
  const { data: executionList } = useExecutionList(liveOrgId, projectId, {
    enabled: Boolean(projectId) && mode !== 'board',
    limit: 12,
    refetchInterval: 4000,
  });
  const executionStream = useExecutionStream({
    orgId: liveOrgId,
    projectId,
    enabled: Boolean(projectId && liveOrgId) && mode !== 'board',
  });

  const livePresenceList = useMemo<ShellPresenceParticipant[]>(() => {
    const merged = new Map<string, ShellPresenceParticipant>();

    for (const participant of collabPresence) {
      merged.set(participant.user_id, {
        user_id: participant.user_id,
        display_name: participant.display_name,
        color: participant.color,
        status: participant.status,
      });
    }

    const activeExecutions = (executionList?.executions ?? []).filter((execution) => {
      const state = String(execution.state).toLowerCase();
      return state === 'running' || state === 'pending' || state === 'paused';
    });

    for (const execution of activeExecutions) {
      const agent = agents.find((candidate) => candidate.id === execution.agentId);
      const agentKey = `agent:${execution.agentId}`;
      const agentName = agent?.name ?? execution.agentId;
      merged.set(agentKey, {
        user_id: agentKey,
        display_name: agentName,
        color: '#1098ad',
        status: String(execution.state).toLowerCase() === 'paused' ? 'idle' : 'active',
      });
    }

    return Array.from(merged.values());
  }, [collabPresence, executionList?.executions, agents]);

  const resolvedConnectionState = useMemo(() => {
    if (executionStream.connectionState === 'connected' || executionStream.connectionState === 'reconnecting') {
      return executionStream.connectionState;
    }
    return connectionState;
  }, [connectionState, executionStream.connectionState]);

  const activeScopeLabel = useMemo(() => {
    if (currentOrgId || project?.org_id) {
      return CURRENT_SCOPE_LABEL;
    }
    return PERSONAL_SCOPE_LABEL;
  }, [currentOrgId, project?.org_id]);

  // Keyboard shortcuts
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // ⌘K / Ctrl+K → Command palette
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        collabStore.toggleCommandPalette();
      }
      // ⌘B / Ctrl+B → Toggle sidebar
      if ((e.metaKey || e.ctrlKey) && e.key === 'b') {
        e.preventDefault();
        collabStore.toggleSidebar();
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <div className="workspace-shell">
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => collabStore.toggleSidebar()}
      >
        {sidebarContent}
      </Sidebar>

      <div className={`workspace-content${mode === 'board' ? ' board-mode' : ''}`}>
        {mode !== 'board' && (
          <Header
            documentTitle={documentTitle ?? activeDocument?.title ?? activeScopeLabel}
            connectionState={resolvedConnectionState}
            presenceList={livePresenceList}
          />
        )}
        <MainContent>{children}</MainContent>
      </div>
    </div>
  );
}

export default WorkspaceShell;
