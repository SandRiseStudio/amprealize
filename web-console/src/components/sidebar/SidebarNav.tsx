import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useProjects, type Project } from '../../api/dashboard';
import { useBoards } from '../../api/boards';
import { useOrgContext } from '../../store/orgContextStore';
import { useApiCapabilities } from '../../api/capabilities';
import { useModules } from '../../api/modules';
import { loadProjectSortPreference, sortProjects } from '../../utils/projectSort';
import { STORAGE_KEYS } from '../../config/storageKeys';
import { type WikiDomain } from '../wiki/wikiData';
import { preloadWhiteboardCanvas } from '../whiteboard/whiteboardCanvasLoader';
import './SidebarNav.css';

const STORAGE_KEY_SECTIONS = STORAGE_KEYS.sidebarSections;
const STORAGE_KEY_RECENT_PROJECTS = STORAGE_KEYS.sidebarRecentProjects;
const STORAGE_KEY_PINNED_PROJECTS = STORAGE_KEYS.sidebarPinnedProjects;

type SectionState = {
  projects: boolean;
  tools: boolean;
};

interface SidebarNavProps {
  onNavigate: (path: string) => void;
  selectedId?: string;
}

interface NavItemProps {
  label: string;
  icon: React.ReactNode;
  description?: string;
  ariaLabel?: string;
  active?: boolean;
  nested?: boolean;
  onClick: () => void;
  trailing?: React.ReactNode;
  secondaryAction?: {
    icon: React.ReactNode;
    label: string;
    title?: string;
    onClick: () => void;
  };
  onMouseEnter?: () => void;
  onFocus?: () => void;
  onKeyDown?: (event: React.KeyboardEvent<HTMLButtonElement>) => void;
  role?: string;
  level?: number;
  expanded?: boolean;
  controls?: string;
}

interface SidebarProjectNodeProps {
  project: Project;
  isActive: boolean;
  onNavigate: (path: string) => void;
  pathname: string;
  onMoveFocus: (current: HTMLElement, delta: number) => void;
  variant?: 'pinned' | 'recent' | 'default';
}

const HomeIcon = () => (
  <svg className="sidebar-nav-icon" viewBox="0 0 16 16" fill="none">
    <path d="M2.5 7.2L8 2.8l5.5 4.4v5.3a1 1 0 0 1-1 1h-3v-3.3H6.5V13.5h-3a1 1 0 0 1-1-1V7.2z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
  </svg>
);

const OrgIcon = () => (
  <svg className="sidebar-nav-icon" viewBox="0 0 16 16" fill="none">
    <rect x="2" y="3" width="12" height="10" rx="2" stroke="currentColor" strokeWidth="1.5" />
    <path d="M5 6h2M9 6h2M5 9h2M9 9h2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

const AgentIcon = () => (
  <svg className="sidebar-nav-icon" viewBox="0 0 16 16" fill="none">
    <circle cx="8" cy="5" r="3" stroke="currentColor" strokeWidth="1.5" />
    <path d="M3 14c0-2.761 2.239-5 5-5s5 2.239 5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

const ProjectIcon = () => (
  <svg className="sidebar-nav-icon" viewBox="0 0 16 16" fill="none">
    <rect x="2" y="3" width="12" height="10" rx="2" stroke="currentColor" strokeWidth="1.5" />
    <path d="M2 6.5h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

const BoardIcon = () => (
  <svg className="sidebar-nav-icon" viewBox="0 0 16 16" fill="none">
    <rect x="2" y="2.5" width="12" height="11" rx="2" stroke="currentColor" strokeWidth="1.5" />
    <path d="M6 2.5v11M10 2.5v11" stroke="currentColor" strokeWidth="1.5" />
  </svg>
);

const DefaultBoardIcon = () => (
  <svg className="sidebar-nav-icon" viewBox="0 0 16 16" fill="none">
    <path d="M8 2.5l1.4 2.9 3.1.5-2.2 2.2.5 3.1L8 9.9l-2.8 1.5.5-3.1-2.2-2.2 3.1-.5L8 2.5Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
  </svg>
);

const SearchIcon = () => (
  <svg className="sidebar-nav-icon" viewBox="0 0 16 16" fill="none">
    <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.5" />
    <path d="M10.5 10.5L13.5 13.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

const SparkIcon = () => (
  <svg className="sidebar-nav-icon" viewBox="0 0 16 16" fill="none">
    <path d="M8 2.5l1.2 3.3L12.5 7 9.2 8.2 8 11.5 6.8 8.2 3.5 7l3.3-1.2L8 2.5Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
  </svg>
);

const WikiIcon = () => (
  <svg className="sidebar-nav-icon" viewBox="0 0 16 16" fill="none">
    <path d="M3 3.5h4a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1Z" stroke="currentColor" strokeWidth="1.5" />
    <path d="M8 4.5h5a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H8" stroke="currentColor" strokeWidth="1.5" />
    <path d="M4.5 6.5h2M4.5 8.5h2M10 7h2.5M10 9h2.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" opacity="0.5" />
  </svg>
);

const WhiteboardIcon = () => (
  <svg className="sidebar-nav-icon" viewBox="0 0 16 16" fill="none">
    <rect x="2" y="2" width="12" height="10" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
    <path d="M5 14h6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    <path d="M5 6l2 2-2 2M9 6h2.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" opacity="0.5" />
  </svg>
);

const ChevronIcon = ({ expanded }: { expanded: boolean }) => (
  <svg className={`sidebar-chevron ${expanded ? 'expanded' : ''}`} viewBox="0 0 16 16" fill="none">
    <path d="M6 3.5L10.5 8 6 12.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const PlusIcon = () => (
  <svg className="sidebar-plus-icon" viewBox="0 0 16 16" fill="none">
    <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

function loadSectionState(): SectionState {
  if (typeof window === 'undefined') {
    return { projects: false, tools: true };
  }

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY_SECTIONS);
    if (!raw) return { projects: false, tools: true };
    return { ...{ projects: false, tools: true }, ...(JSON.parse(raw) as Partial<SectionState>) };
  } catch {
    return { projects: false, tools: true };
  }
}

function loadProjectIdList(storageKey: string): string[] {
  if (typeof window === 'undefined') return [];

  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((value): value is string => typeof value === 'string');
  } catch {
    return [];
  }
}

const NavItem = memo(function NavItem({
  label,
  icon,
  description,
  ariaLabel,
  active,
  nested,
  onClick,
  trailing,
  secondaryAction,
  onMouseEnter,
  onFocus,
  onKeyDown,
  role,
  level,
  expanded,
  controls,
}: NavItemProps) {
  const button = (
    <button
      type="button"
      className={`sidebar-nav-item ${active ? 'active' : ''} ${nested ? 'nested' : ''} ${secondaryAction ? 'sidebar-nav-item--with-action' : ''}`}
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      onFocus={onFocus}
      onKeyDown={onKeyDown}
      aria-label={ariaLabel}
      aria-current={active ? 'page' : undefined}
      aria-expanded={expanded}
      aria-controls={controls}
      role={role}
      aria-level={level}
      data-sidebar-focusable="true"
    >
      <span className="sidebar-nav-item-leading">
        <span className="sidebar-nav-icon-wrap">{icon}</span>
        <span className="sidebar-nav-copy">
          <span className="sidebar-nav-label">{label}</span>
          {description && <span className="sidebar-nav-description">{description}</span>}
        </span>
      </span>
      {trailing && <span className="sidebar-nav-trailing">{trailing}</span>}
    </button>
  );

  if (!secondaryAction) {
    return button;
  }

  return (
    <div className={`sidebar-nav-row ${active ? 'active' : ''} ${nested ? 'nested' : ''}`}>
      {button}
      <button
        type="button"
        className="sidebar-nav-inline-action"
        aria-label={secondaryAction.label}
        title={secondaryAction.title ?? secondaryAction.label}
        onClick={secondaryAction.onClick}
      >
        {secondaryAction.icon}
      </button>
    </div>
  );
});

const GearIcon = () => (
  <svg className="sidebar-gear-icon" viewBox="0 0 16 16" fill="none">
    <path d="M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5Z" stroke="currentColor" strokeWidth="1.5" />
    <path d="M13.2 8.8v-1.6l-1.1-.3a4.5 4.5 0 0 0-.4-.9l.6-1-1.1-1.1-1 .6c-.3-.2-.6-.3-.9-.4L8.8 2.8H7.2l-.3 1.1c-.3.1-.6.2-.9.4l-1-.6-1.1 1.1.6 1c-.2.3-.3.6-.4.9l-1.1.3v1.6l1.1.3c.1.3.2.6.4.9l-.6 1 1.1 1.1 1-.6c.3.2.6.3.9.4l.3 1.1h1.6l.3-1.1c.3-.1.6-.2.9-.4l1 .6 1.1-1.1-.6-1c.2-.3.3-.6.4-.9l1.1-.3Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
  </svg>
);

const PinDot = () => (
  <span className="sidebar-pin-dot" aria-label="Pinned" title="Pinned">
    <svg viewBox="0 0 8 8" width="8" height="8" fill="currentColor"><circle cx="4" cy="4" r="3" /></svg>
  </span>
);

const SidebarProjectNode = memo(function SidebarProjectNode({
  project,
  isActive,
  onNavigate,
  pathname,
  onMoveFocus,
  variant = 'default',
}: SidebarProjectNodeProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [shouldLoadBoards, setShouldLoadBoards] = useState(isActive);
  const pickerRef = useRef<HTMLDivElement | null>(null);
  const { data: boards = [] } = useBoards(project.id, {
    enabled: shouldLoadBoards || pickerOpen || isActive,
  });

  const defaultBoard = useMemo(() => boards.find((b) => b.is_default) ?? boards[0], [boards]);
  const hasMultipleBoards = boards.length > 1;

  const activeBoardId = useMemo(() => {
    const match = pathname.match(new RegExp(`^/projects/${project.id}/boards/([^/]+)`));
    return match?.[1] ?? null;
  }, [pathname, project.id]);

  // Close picker on click outside or Escape
  useEffect(() => {
    if (!pickerOpen) return;
    const handleClick = (event: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(event.target as Node)) {
        setPickerOpen(false);
      }
    };
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPickerOpen(false);
    };
    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [pickerOpen]);

  useEffect(() => {
    if (isActive || pickerOpen) {
      queueMicrotask(() => setShouldLoadBoards(true));
    }
  }, [isActive, pickerOpen]);

  const primeBoards = useCallback(() => {
    setShouldLoadBoards(true);
  }, []);

  const handleProjectClick = useCallback(() => {
    if (defaultBoard) {
      onNavigate(`/projects/${project.id}/boards/${defaultBoard.board_id}`);
    } else {
      onNavigate(`/projects/${project.id}`);
    }
  }, [defaultBoard, onNavigate, project.id]);

  const handleKeyDown = useCallback((event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      onMoveFocus(event.currentTarget, 1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      onMoveFocus(event.currentTarget, -1);
    }
  }, [onMoveFocus]);

  return (
    <div className={`sidebar-project-row ${variant === 'default' ? 'sidebar-project-row--dim' : ''}`} ref={pickerRef}>
      <button
        type="button"
        className={`sidebar-nav-item project-item ${isActive ? 'active' : ''}`}
        onClick={handleProjectClick}
        onMouseEnter={primeBoards}
        onFocus={primeBoards}
        onKeyDown={handleKeyDown}
        aria-current={isActive ? 'page' : undefined}
        data-sidebar-focusable="true"
        role="treeitem"
        aria-level={1}
      >
        <span className="sidebar-nav-item-leading">
          <span className="sidebar-nav-icon-wrap"><ProjectIcon /></span>
          <span className="sidebar-nav-copy">
            <span className="sidebar-nav-label project-name">{project.name}</span>
          </span>
          {variant === 'pinned' && <PinDot />}
        </span>
        <span className="sidebar-nav-trailing">
          <span
            role="button"
            tabIndex={0}
            className="sidebar-project-gear"
            aria-label={`${project.name} settings`}
            title="Project settings"
            onClick={(event) => {
              event.stopPropagation();
              onNavigate(`/projects/${project.id}?tab=settings`);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                event.stopPropagation();
                onNavigate(`/projects/${project.id}?tab=settings`);
              }
            }}
          >
            <GearIcon />
          </span>
          {hasMultipleBoards && (
            <span
              role="button"
              tabIndex={0}
              className="sidebar-board-chevron"
              aria-label={`Switch board in ${project.name}`}
              aria-expanded={pickerOpen}
              title="Switch board"
              onClick={(event) => {
                event.stopPropagation();
                setShouldLoadBoards(true);
                setPickerOpen((prev) => !prev);
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  event.stopPropagation();
                  setShouldLoadBoards(true);
                  setPickerOpen((prev) => !prev);
                }
              }}
            >
              <ChevronIcon expanded={pickerOpen} />
            </span>
          )}
        </span>
      </button>

      {pickerOpen && hasMultipleBoards && (
        <div className="sidebar-board-picker" role="listbox" aria-label="Select board">
          {boards.map((board) => (
            <button
              key={board.board_id}
              type="button"
              role="option"
              className={`sidebar-board-picker-item ${activeBoardId === board.board_id ? 'active' : ''}`}
              aria-selected={activeBoardId === board.board_id}
              onClick={() => {
                onNavigate(`/projects/${project.id}/boards/${board.board_id}`);
                setPickerOpen(false);
              }}
            >
              <span className="sidebar-board-picker-icon">
                {board.is_default ? <DefaultBoardIcon /> : <BoardIcon />}
              </span>
              <span className="sidebar-board-picker-name">{board.name}</span>
              {board.is_default && <span className="sidebar-board-picker-badge">Default</span>}
            </button>
          ))}
          <div className="sidebar-board-picker-divider" />
          <button
            type="button"
            className="sidebar-board-picker-item sidebar-board-picker-create"
            onClick={() => {
              onNavigate(`/projects/${project.id}?newBoard=1`);
              setPickerOpen(false);
            }}
          >
            <span className="sidebar-board-picker-icon"><PlusIcon /></span>
            <span className="sidebar-board-picker-name">New board</span>
          </button>
        </div>
      )}
    </div>
  );
});

export const SidebarNav = memo(function SidebarNav({ onNavigate }: SidebarNavProps) {
  const location = useLocation();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const { currentOrgId } = useOrgContext();
  const [sections, setSections] = useState<SectionState>(() => loadSectionState());

  const { data: capabilities } = useApiCapabilities();
  const hasOrgs = capabilities?.routes.orgs ?? false;

  const { isModuleEnabled } = useModules();
  const hasAgents = isModuleEnabled('agents');
  const hasBehaviors = isModuleEnabled('behaviors');
  const hasWhiteboard = isModuleEnabled('whiteboard');

  const { data: projects = [] } = useProjects(currentOrgId ?? undefined);

  const sortedProjects = useMemo(
    () => sortProjects(projects, loadProjectSortPreference()),
    [projects]
  );

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY_SECTIONS, JSON.stringify(sections));
  }, [sections]);

  const newProjectPath = useMemo(() => {
    return currentOrgId ? `/projects/new?org=${encodeURIComponent(currentOrgId)}` : '/projects/new';
  }, [currentOrgId]);

  const toggleSection = useCallback((section: keyof SectionState) => {
    setSections((prev) => ({ ...prev, [section]: !prev[section] }));
  }, []);

  const handleWhiteboardIntent = useCallback(() => {
    void preloadWhiteboardCanvas();
  }, []);

  const moveFocus = useCallback((current: HTMLElement, delta: number) => {
    const nodes = Array.from(
      containerRef.current?.querySelectorAll<HTMLElement>('[data-sidebar-focusable="true"]') ?? []
    );
    const currentIndex = nodes.indexOf(current);
    if (currentIndex === -1) return;
    const next = nodes[currentIndex + delta];
    next?.focus();
  }, []);

  const pathname = location.pathname;
  const routeProjectId = useMemo(() => {
    const match = pathname.match(/^\/projects\/([^/]+)/);
    if (!match?.[1] || match[1] === 'new') {
      return null;
    }
    return match[1];
  }, [pathname]);

  const visibleSections = useMemo(
    () => ({
      ...sections,
      tools: pathname.startsWith('/bci') || pathname.startsWith('/whiteboard') ? false : sections.tools,
      projects: pathname.startsWith('/projects') ? false : sections.projects,
    }),
    [pathname, sections]
  );

  const projectsById = useMemo(
    () => new Map(sortedProjects.map((project) => [project.id, project])),
    [sortedProjects]
  );

  const pinnedProjectIds = useMemo(() => loadProjectIdList(STORAGE_KEY_PINNED_PROJECTS), []);
  const recentProjectIds = useMemo(() => {
    const stored = loadProjectIdList(STORAGE_KEY_RECENT_PROJECTS);
    if (!routeProjectId) return stored;
    return [routeProjectId, ...stored.filter((id) => id !== routeProjectId)];
  }, [routeProjectId]);

  const pinnedProjects = useMemo(
    () => pinnedProjectIds.map((id) => projectsById.get(id)).filter((p): p is Project => Boolean(p)),
    [pinnedProjectIds, projectsById]
  );
  const recentProjects = useMemo(() => {
    const pinnedIds = new Set(pinnedProjects.map((p) => p.id));
    return recentProjectIds
      .map((id) => projectsById.get(id))
      .filter((p): p is Project => p !== undefined && !pinnedIds.has(p.id))
      .slice(0, 5);
  }, [pinnedProjects, projectsById, recentProjectIds]);

  const remainingProjects = useMemo(() => {
    const shownIds = new Set([
      ...pinnedProjects.map((p) => p.id),
      ...recentProjects.map((p) => p.id),
    ]);
    return sortedProjects.filter((p) => !shownIds.has(p.id));
  }, [pinnedProjects, recentProjects, sortedProjects]);

  useEffect(() => {
    if (!routeProjectId || typeof window === 'undefined') {
      return;
    }

    window.localStorage.setItem(
      STORAGE_KEY_RECENT_PROJECTS,
      JSON.stringify(recentProjectIds.slice(0, 8))
    );
  }, [recentProjectIds, routeProjectId]);

  return (
    <div className="sidebar-nav-panel">
      <div className="sidebar-nav-tree" role="tree" aria-label="Primary navigation" ref={containerRef}>
        <NavItem
          label="Dashboard"
          icon={<HomeIcon />}
          active={pathname === '/'}
          onClick={() => onNavigate('/')}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown') {
              event.preventDefault();
              moveFocus(event.currentTarget, 1);
            } else if (event.key === 'ArrowUp') {
              event.preventDefault();
              moveFocus(event.currentTarget, -1);
            }
          }}
          role="treeitem"
          level={1}
        />

        <div className="sidebar-section sidebar-section-projects">
          <div className="sidebar-section-header sidebar-section-header-with-action">
            <button
              type="button"
              className="sidebar-section-toggle"
              onClick={() => toggleSection('projects')}
              onKeyDown={(event) => {
                if (event.key === 'ArrowDown') {
                  event.preventDefault();
                  moveFocus(event.currentTarget, 1);
                } else if (event.key === 'ArrowUp') {
                  event.preventDefault();
                  moveFocus(event.currentTarget, -1);
                } else if (event.key === 'ArrowLeft' && !visibleSections.projects) {
                  event.preventDefault();
                  toggleSection('projects');
                } else if (event.key === 'ArrowRight' && visibleSections.projects) {
                  event.preventDefault();
                  toggleSection('projects');
                }
              }}
              data-sidebar-focusable="true"
              role="treeitem"
              aria-expanded={!visibleSections.projects}
              aria-level={1}
            >
              <span className="sidebar-section-title-group">
                <span className="sidebar-section-dot" />
                <span>Projects</span>
              </span>
              <ChevronIcon expanded={!visibleSections.projects} />
            </button>
            <button
              type="button"
              className="sidebar-section-action"
              onClick={() => onNavigate(newProjectPath)}
              aria-label="Create project"
              title="Create project"
            >
              <PlusIcon />
            </button>
          </div>
          <div className={`sidebar-section-body ${visibleSections.projects ? 'collapsed' : ''}`}>
            <div className="sidebar-section-body-inner">
              {sortedProjects.length > 1 && (
                <NavItem
                  label="All Projects"
                  icon={<ProjectIcon />}
                  active={pathname === '/projects' || pathname === '/projects/new'}
                  onClick={() => onNavigate('/projects')}
                  onKeyDown={(event) => {
                    if (event.key === 'ArrowDown') {
                      event.preventDefault();
                      moveFocus(event.currentTarget, 1);
                    } else if (event.key === 'ArrowUp') {
                      event.preventDefault();
                      moveFocus(event.currentTarget, -1);
                    }
                  }}
                  role="treeitem"
                  level={1}
                />
              )}

              {pinnedProjects.map((project) => {
                const isProjectRoute = pathname === `/projects/${project.id}` || pathname.startsWith(`/projects/${project.id}/`);
                return (
                  <SidebarProjectNode
                    key={`pinned-${project.id}`}
                    project={project}
                    isActive={isProjectRoute}
                    onNavigate={onNavigate}
                    pathname={pathname}
                    onMoveFocus={moveFocus}
                    variant="pinned"
                  />
                );
              })}
              {recentProjects.map((project) => {
                const isProjectRoute = pathname === `/projects/${project.id}` || pathname.startsWith(`/projects/${project.id}/`);
                return (
                  <SidebarProjectNode
                    key={`recent-${project.id}`}
                    project={project}
                    isActive={isProjectRoute}
                    onNavigate={onNavigate}
                    pathname={pathname}
                    onMoveFocus={moveFocus}
                    variant="recent"
                  />
                );
              })}
              {remainingProjects.map((project) => {
                const isProjectRoute = pathname === `/projects/${project.id}` || pathname.startsWith(`/projects/${project.id}/`);
                return (
                  <SidebarProjectNode
                    key={`other-${project.id}`}
                    project={project}
                    isActive={isProjectRoute}
                    onNavigate={onNavigate}
                    pathname={pathname}
                    onMoveFocus={moveFocus}
                  />
                );
              })}
            </div>
          </div>
        </div>

        {hasOrgs ? (
          <div className="sidebar-section">
            <div className="sidebar-section-label" aria-hidden="true">
              <span className="sidebar-section-title-group">
                <span className="sidebar-section-dot" />
                <span>Manage</span>
              </span>
            </div>
            <div className="sidebar-section-body">
              <div className="sidebar-section-body-inner">
                <NavItem
                  label="Organizations"
                  icon={<OrgIcon />}
                  active={pathname.startsWith('/orgs')}
                  onClick={() => onNavigate('/orgs')}
                  onKeyDown={(event) => {
                    if (event.key === 'ArrowDown') {
                      event.preventDefault();
                      moveFocus(event.currentTarget, 1);
                    } else if (event.key === 'ArrowUp') {
                      event.preventDefault();
                      moveFocus(event.currentTarget, -1);
                    }
                  }}
                  role="treeitem"
                  level={1}
                />
                {hasAgents && (
                <NavItem
                  label="Agents"
                  icon={<AgentIcon />}
                  active={pathname.startsWith('/agents')}
                  onClick={() => onNavigate('/agents')}
                  onKeyDown={(event) => {
                    if (event.key === 'ArrowDown') {
                      event.preventDefault();
                      moveFocus(event.currentTarget, 1);
                    } else if (event.key === 'ArrowUp') {
                      event.preventDefault();
                      moveFocus(event.currentTarget, -1);
                    }
                  }}
                  role="treeitem"
                  level={1}
                />
                )}
              </div>
            </div>
          </div>
        ) : (
          <div className="sidebar-section">
            <div className="sidebar-section-body">
              <div className="sidebar-section-body-inner">
                {hasAgents && (
                  <NavItem
                    label="Agents"
                    icon={<AgentIcon />}
                    active={pathname.startsWith('/agents')}
                    onClick={() => onNavigate('/agents')}
                    onKeyDown={(event) => {
                      if (event.key === 'ArrowDown') {
                        event.preventDefault();
                        moveFocus(event.currentTarget, 1);
                      } else if (event.key === 'ArrowUp') {
                        event.preventDefault();
                        moveFocus(event.currentTarget, -1);
                      }
                    }}
                    role="treeitem"
                    level={1}
                  />
                )}
              </div>
            </div>
          </div>
        )}

        {(hasBehaviors || hasWhiteboard) && (
        <div className="sidebar-section">
          <button
            type="button"
            className="sidebar-section-header"
            onClick={() => toggleSection('tools')}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault();
                moveFocus(event.currentTarget, 1);
              } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                moveFocus(event.currentTarget, -1);
              } else if (event.key === 'ArrowLeft' && !visibleSections.tools) {
                event.preventDefault();
                toggleSection('tools');
              } else if (event.key === 'ArrowRight' && visibleSections.tools) {
                event.preventDefault();
                toggleSection('tools');
              }
            }}
            data-sidebar-focusable="true"
            role="treeitem"
            aria-expanded={!visibleSections.tools}
            aria-level={1}
          >
            <span className="sidebar-section-title-group">
              <span className="sidebar-section-dot" />
              <span>Studio</span>
            </span>
            <ChevronIcon expanded={!visibleSections.tools} />
          </button>
          <div className={`sidebar-section-body ${visibleSections.tools ? 'collapsed' : ''}`}>
            <div className="sidebar-section-body-inner">
              {hasBehaviors && (
              <NavItem
                label="Behavior Search"
                icon={<SearchIcon />}
                active={pathname === '/bci'}
                onClick={() => onNavigate('/bci')}
                onKeyDown={(event) => {
                  if (event.key === 'ArrowDown') {
                    event.preventDefault();
                    moveFocus(event.currentTarget, 1);
                  } else if (event.key === 'ArrowUp') {
                    event.preventDefault();
                    moveFocus(event.currentTarget, -1);
                  }
                }}
                role="treeitem"
                level={1}
              />
              )}
              {hasBehaviors && (
              <NavItem
                label="Behavior Extraction"
                icon={<SparkIcon />}
                active={pathname === '/bci/extraction'}
                onClick={() => onNavigate('/bci/extraction')}
                onKeyDown={(event) => {
                  if (event.key === 'ArrowDown') {
                    event.preventDefault();
                    moveFocus(event.currentTarget, 1);
                  } else if (event.key === 'ArrowUp') {
                    event.preventDefault();
                    moveFocus(event.currentTarget, -1);
                  }
                }}
                role="treeitem"
                level={1}
              />
              )}
              {hasWhiteboard && (
              <NavItem
                label="Whiteboard"
                icon={<WhiteboardIcon />}
                active={pathname.startsWith('/whiteboard')}
                onClick={() => {
                  handleWhiteboardIntent();
                  onNavigate('/whiteboard');
                }}
                onMouseEnter={handleWhiteboardIntent}
                onFocus={handleWhiteboardIntent}
                onKeyDown={(event) => {
                  if (event.key === 'ArrowDown') {
                    event.preventDefault();
                    moveFocus(event.currentTarget, 1);
                  } else if (event.key === 'ArrowUp') {
                    event.preventDefault();
                    moveFocus(event.currentTarget, -1);
                  }
                }}
                role="treeitem"
                level={1}
              />
              )}
            </div>
          </div>
        </div>
        )}
        <WikiSidebarSection pathname={pathname} onNavigate={onNavigate} moveFocus={moveFocus} />
      </div>
    </div>
  );
});

// ---------------------------------------------------------------------------
// Wiki sidebar section — launcher, not full tree
// ---------------------------------------------------------------------------

const WikiSidebarSection = memo(function WikiSidebarSection({
  pathname,
  onNavigate,
  moveFocus,
}: {
  pathname: string;
  onNavigate: (path: string) => void;
  moveFocus: (current: HTMLElement, delta: number) => void;
}) {
  const isWikiActive = pathname.startsWith('/wiki');
  const activeDomain = useMemo((): WikiDomain | null => {
    const match = pathname.match(/^\/wiki\/([^/]+)/);
    if (!match) return null;
    return match[1] as WikiDomain;
  }, [pathname]);
  const defaultDomain = activeDomain ?? 'infra';

  return (
    <div className="sidebar-section">
      <div className="sidebar-section-body">
        <div className="sidebar-section-body-inner">
          <NavItem
            label="Wiki"
            description=""
            icon={<WikiIcon />}
            ariaLabel="Open wiki"
            active={isWikiActive}
            onClick={() => onNavigate(`/wiki/${defaultDomain}`)}
            secondaryAction={{
              icon: <SearchIcon />,
              label: 'Open wiki search',
              title: 'Open wiki search',
              onClick: () => onNavigate(`/wiki/${defaultDomain}?search=1`),
            }}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') { event.preventDefault(); moveFocus(event.currentTarget, 1); }
              else if (event.key === 'ArrowUp') { event.preventDefault(); moveFocus(event.currentTarget, -1); }
            }}
            role="treeitem"
            level={1}
          />
        </div>
      </div>
    </div>
  );
});
