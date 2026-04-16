import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { WhiteboardPage } from '../components/whiteboard/WhiteboardPage';
import { useWhiteboardRooms, useWhiteboardSnapshots } from '../api/whiteboard';
import { preloadWhiteboardCanvas } from '../components/whiteboard/whiteboardCanvasLoader';

vi.mock('../api/whiteboard', () => ({
  useWhiteboardRooms: vi.fn(),
  useWhiteboardSnapshots: vi.fn(),
}));

vi.mock('../components/whiteboard/whiteboardCanvasLoader', () => ({
  LazyWhiteboardCanvas: () => null,
  preloadWhiteboardCanvas: vi.fn(),
}));

function renderPage(path = '/whiteboard') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/whiteboard" element={<WhiteboardPage />} />
        <Route path="/whiteboard/:roomId" element={<WhiteboardPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('WhiteboardPage', () => {
  beforeEach(() => {
    Object.defineProperty(window.navigator, 'connection', {
      configurable: true,
      value: { saveData: true },
    });

    vi.mocked(useWhiteboardRooms).mockReturnValue({
      data: [
        {
          id: 'room-1',
          title: 'Idea Lab',
          status: 'active',
          participant_ids: ['alice'],
          created_at: '2026-04-14T10:00:00.000Z',
        },
      ],
      isLoading: false,
    } as never);

    vi.mocked(useWhiteboardSnapshots).mockReturnValue({
      data: [
        {
          id: 'snap-1',
          room_id: 'room-old',
          title: 'Sprint Planning Ideas',
          format: 'json',
          exported_at: '2026-04-13T15:00:00.000Z',
        },
      ],
      isLoading: false,
    } as never);

    vi.mocked(preloadWhiteboardCanvas).mockClear();
  });

  it('prefetches the canvas on room card hover', () => {
    renderPage();

    fireEvent.mouseEnter(screen.getByRole('link', { name: /idea lab/i }));
    expect(preloadWhiteboardCanvas).toHaveBeenCalledTimes(1);
  });

  it('shows gallery with no creation controls', () => {
    renderPage();

    expect(screen.getByText('Brainstorm Whiteboard')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /new whiteboard/i })).toBeNull();
    expect(screen.queryByPlaceholderText(/title/i)).toBeNull();
  });

  it('shows active rooms in the live sessions section', () => {
    renderPage();

    expect(screen.getByText('Idea Lab')).toBeTruthy();
    expect(screen.getByText('Live Sessions')).toBeTruthy();
    expect(screen.getByText(/^Live$/)).toBeTruthy();
    expect(screen.getByText('1')).toBeTruthy();
  });

  it('shows snapshot archive section', () => {
    renderPage();

    expect(screen.getByText('Session Archive')).toBeTruthy();
    expect(screen.getByText('Sprint Planning Ideas')).toBeTruthy();
    expect(screen.getByText('json')).toBeTruthy();
  });

  it('shows empty state when no active rooms', () => {
    vi.mocked(useWhiteboardRooms).mockReturnValue({
      data: [],
      isLoading: false,
    } as never);

    renderPage();

    expect(screen.getByText(/no live sessions/i)).toBeTruthy();
    expect(
      screen.getByText(/start a brainstorm conversation to open a collaborative canvas/i),
    ).toBeTruthy();
  });

  it('shows empty state when no snapshots', () => {
    vi.mocked(useWhiteboardSnapshots).mockReturnValue({
      data: [],
      isLoading: false,
    } as never);

    renderPage();

    expect(screen.getByText(/no archived sessions yet/i)).toBeTruthy();
  });

  it('shows loading skeletons while data is loading', () => {
    vi.mocked(useWhiteboardRooms).mockReturnValue({
      data: [],
      isLoading: true,
    } as never);
    vi.mocked(useWhiteboardSnapshots).mockReturnValue({
      data: [],
      isLoading: true,
    } as never);

    const { container } = renderPage();

    const skeletons = container.querySelectorAll('.whiteboard-skeleton');
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it('shows section labels for live sessions and archive', () => {
    renderPage();

    expect(screen.getByText('Live Sessions')).toBeTruthy();
    expect(screen.getByText('Session Archive')).toBeTruthy();
  });
});
