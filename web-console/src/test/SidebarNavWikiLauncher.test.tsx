import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { SidebarNav } from '../components/sidebar/SidebarNav';
import { useBoards } from '../api/boards';
import { useProjects } from '../api/dashboard';
import { useApiCapabilities } from '../api/capabilities';
import { useModules } from '../api/modules';
import { preloadWhiteboardCanvas } from '../components/whiteboard/whiteboardCanvasLoader';
import { useOrgContext } from '../store/orgContextStore';

vi.mock('../api/boards', () => ({ useBoards: vi.fn() }));
vi.mock('../api/dashboard', () => ({ useProjects: vi.fn() }));
vi.mock('../api/capabilities', () => ({ useApiCapabilities: vi.fn() }));
vi.mock('../api/modules', () => ({ useModules: vi.fn() }));
vi.mock('../components/whiteboard/whiteboardCanvasLoader', () => ({ preloadWhiteboardCanvas: vi.fn() }));
vi.mock('../store/orgContextStore', () => ({ useOrgContext: vi.fn() }));

describe('SidebarNav wiki launcher', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem(
      'amprealize.wiki.recentPages',
      JSON.stringify([
        {
          domain: 'infra',
          path: 'howto/run-tests.md',
          title: 'Run Tests Locally',
          pageType: 'howto',
          visitedAt: '2026-04-09T12:00:00.000Z',
        },
        {
          domain: 'ai-learning',
          path: 'concepts/attention.md',
          title: 'Attention',
          pageType: 'concept',
          visitedAt: '2026-04-08T12:00:00.000Z',
        },
      ]),
    );

    vi.mocked(useProjects).mockReturnValue({ data: [] } as never);
    vi.mocked(useBoards).mockReturnValue({ data: [] } as never);
    vi.mocked(useApiCapabilities).mockReturnValue({ data: { routes: { orgs: false } } } as never);
    vi.mocked(useModules).mockReturnValue({
      isModuleEnabled: (moduleName: string) => moduleName === 'behaviors' || moduleName === 'whiteboard',
    } as never);
    vi.mocked(useOrgContext).mockReturnValue({ currentOrgId: null } as never);
    vi.mocked(preloadWhiteboardCanvas).mockClear();
  });

  it('shows a consolidated wiki launcher row with an inline search action', async () => {
    const onNavigate = vi.fn();
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={['/wiki/infra']}>
        <SidebarNav onNavigate={onNavigate} />
      </MemoryRouter>,
    );

    expect(screen.getByRole('treeitem', { name: /open wiki/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /open wiki search/i })).toBeInTheDocument();
    expect(screen.queryByRole('treeitem', { name: /^platform\b/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('treeitem', { name: /^infrastructure\b/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('treeitem', { name: /continue reading/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('treeitem', { name: /recent page/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('treeitem', { name: /^Run Tests Locally$/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole('treeitem', { name: /open wiki/i }));
    expect(onNavigate).toHaveBeenCalledWith('/wiki/infra');

    await user.click(screen.getByRole('button', { name: /open wiki search/i }));
    expect(onNavigate).toHaveBeenCalledWith('/wiki/infra?search=1');
  });

  it('prefetches the whiteboard canvas on hover and focus intent', async () => {
    const onNavigate = vi.fn();
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={['/']}>
        <SidebarNav onNavigate={onNavigate} />
      </MemoryRouter>,
    );

    const whiteboardLauncher = screen.getByRole('treeitem', { name: /whiteboard/i });

    await user.hover(whiteboardLauncher);
    expect(preloadWhiteboardCanvas).toHaveBeenCalledTimes(1);

    fireEvent.focus(whiteboardLauncher);
    expect(preloadWhiteboardCanvas).toHaveBeenCalledTimes(2);
  });

  it('renders whiteboard inside the studio section rather than as its own card', () => {
    vi.mocked(useModules).mockReturnValue({
      isModuleEnabled: (moduleName: string) => moduleName === 'behaviors' || moduleName === 'whiteboard',
    } as never);

    render(
      <MemoryRouter initialEntries={['/whiteboard']}>
        <SidebarNav onNavigate={vi.fn()} />
      </MemoryRouter>,
    );

    const studioSection = screen.getByRole('treeitem', { name: /studio/i }).closest('.sidebar-section');
    expect(studioSection).not.toBeNull();
    expect(screen.getByRole('treeitem', { name: /whiteboard/i })).toBeInTheDocument();
    expect(studioSection).toContainElement(screen.getByRole('treeitem', { name: /whiteboard/i }));
  });
});
