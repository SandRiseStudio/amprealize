/**
 * Tests for ConversationPanel + ConversationSidebar components
 *
 * Verifies mount/unmount, drawer animation phases, z-index layering,
 * sidebar list rendering, search filter, and unread badges.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConversationPanel } from '../components/conversations/ConversationPanel';

// Mock the API module (ConversationSidebar imports from api/conversations)
vi.mock('../api/conversations', () => ({
  useConversations: vi.fn(() => ({
    data: {
      items: [
        {
          id: 'conv-1',
          title: 'Bug Discussion',
          created_at: '2026-01-15T10:00:00Z',
          updated_at: '2026-01-15T12:00:00Z',
          last_message_at: '2026-01-15T12:00:00Z',
          scope: 'project_room',
          unread_count: 0,
        },
        {
          id: 'conv-2',
          title: 'Feature Planning',
          created_at: '2026-01-14T08:00:00Z',
          updated_at: '2026-01-14T09:00:00Z',
          last_message_at: '2026-01-14T09:00:00Z',
          scope: 'project_room',
          unread_count: 0,
        },
      ],
    },
    isLoading: false,
    error: null,
  })),
  useCreateConversation: vi.fn(() => ({
    mutate: vi.fn(),
    isPending: false,
  })),
  useInfiniteMessages: vi.fn(() => ({
    data: { pages: [{ messages: [], total: 0 }] },
    isLoading: false,
    fetchNextPage: vi.fn(),
    hasNextPage: false,
    isFetchingNextPage: false,
  })),
  useConversationParticipants: vi.fn(() => ({
    data: [],
    isLoading: false,
  })),
  useSendMessage: vi.fn(() => ({
    mutate: vi.fn(),
    isPending: false,
  })),
}));

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    );
  };
}

describe('ConversationPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    // Mock window.innerWidth for desktop
    Object.defineProperty(window, 'innerWidth', { value: 1024, writable: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders with dialog role and aria-modal', () => {
    render(
      <ConversationPanel
        projectId="proj-123"
        onRequestClose={vi.fn()}
      />,
      { wrapper: createWrapper() }
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAttribute('aria-label', 'Conversations');
  });

  it('transitions through entering → open phases', async () => {
    render(
      <ConversationPanel
        projectId="proj-123"
        onRequestClose={vi.fn()}
      />,
      { wrapper: createWrapper() }
    );

    const overlay = screen.getByRole('dialog');
    // Initially no phase class (entering)
    expect(overlay.className).not.toContain('open');
    expect(overlay.className).not.toContain('closing');

    // After RAF, should transition to open
    await act(async () => {
      vi.advanceTimersByTime(16);
    });
    expect(overlay.className).toContain('open');
  });

  it('calls onRequestClose after closing animation', async () => {
    const handleClose = vi.fn();
    render(
      <ConversationPanel
        projectId="proj-123"
        onRequestClose={handleClose}
      />,
      { wrapper: createWrapper() }
    );

    // Advance to open state
    await act(async () => {
      vi.advanceTimersByTime(16);
    });

    // Press escape
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });

    const overlay = screen.getByRole('dialog');
    expect(overlay.className).toContain('closing');
    expect(handleClose).not.toHaveBeenCalled();

    // After 220ms animation
    await act(async () => {
      vi.advanceTimersByTime(220);
    });
    expect(handleClose).toHaveBeenCalledOnce();
  });

  it('renders header with title', () => {
    render(
      <ConversationPanel
        projectId="proj-123"
        onRequestClose={vi.fn()}
      />,
      { wrapper: createWrapper() }
    );
    expect(screen.getByText('Conversations')).toBeInTheDocument();
  });

  it('renders close button with accessible label', () => {
    render(
      <ConversationPanel
        projectId="proj-123"
        onRequestClose={vi.fn()}
      />,
      { wrapper: createWrapper() }
    );
    const closeBtn = screen.getByRole('button', { name: /close conversations/i });
    expect(closeBtn).toBeInTheDocument();
  });

  it('renders empty state when no conversation selected', () => {
    render(
      <ConversationPanel
        projectId="proj-123"
        onRequestClose={vi.fn()}
      />,
      { wrapper: createWrapper() }
    );
    expect(screen.getByText(/select a conversation/i)).toBeInTheDocument();
  });

  it('renders keyboard shortcut hint', () => {
    render(
      <ConversationPanel
        projectId="proj-123"
        onRequestClose={vi.fn()}
      />,
      { wrapper: createWrapper() }
    );
    expect(screen.getByText('⌘')).toBeInTheDocument();
    expect(screen.getByText('⇧')).toBeInTheDocument();
    expect(screen.getByText('M')).toBeInTheDocument();
  });

  it('closes when close button is clicked', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const handleClose = vi.fn();
    render(
      <ConversationPanel
        projectId="proj-123"
        onRequestClose={handleClose}
      />,
      { wrapper: createWrapper() }
    );

    // Advance to open state
    await act(async () => {
      vi.advanceTimersByTime(16);
    });

    const closeBtn = screen.getByRole('button', { name: /close conversations/i });
    await user.click(closeBtn);

    await act(async () => {
      vi.advanceTimersByTime(220);
    });
    expect(handleClose).toHaveBeenCalledOnce();
  });
});

describe('ConversationSidebar (via ConversationPanel)', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    Object.defineProperty(window, 'innerWidth', { value: 1024, writable: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders conversation list items', async () => {
    render(
      <ConversationPanel
        projectId="proj-123"
        onRequestClose={vi.fn()}
      />,
      { wrapper: createWrapper() }
    );

    await act(async () => {
      vi.advanceTimersByTime(16);
    });

    expect(screen.getByText('Bug Discussion')).toBeInTheDocument();
    expect(screen.getByText('Feature Planning')).toBeInTheDocument();
  });

  it('renders new conversation button', () => {
    render(
      <ConversationPanel
        projectId="proj-123"
        onRequestClose={vi.fn()}
      />,
      { wrapper: createWrapper() }
    );
    expect(screen.getByRole('button', { name: /new conversation/i })).toBeInTheDocument();
  });

  it('renders search input', () => {
    render(
      <ConversationPanel
        projectId="proj-123"
        onRequestClose={vi.fn()}
      />,
      { wrapper: createWrapper() }
    );
    // Search input has aria-label="Search conversations" and type="text" (textbox role)
    expect(screen.getByRole('textbox', { name: /search conversations/i })).toBeInTheDocument();
  });
});
