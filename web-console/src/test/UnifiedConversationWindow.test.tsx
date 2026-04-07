/**
 * Smoke tests for UnifiedConversationWindow (board floating shell).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { UnifiedConversationWindow } from '../components/conversations/UnifiedConversationWindow';

vi.mock('../api/conversations', () => ({
  useConversations: vi.fn(() => ({
    data: {
      items: [
        {
          id: 'room-1',
          title: 'General',
          created_at: '2026-01-15T10:00:00Z',
          updated_at: '2026-01-15T12:00:00Z',
          last_message_at: '2026-01-15T12:00:00Z',
          scope: 'project_room',
          unread_count: 0,
        },
      ],
    },
    isLoading: false,
    error: null,
  })),
  useConversation: vi.fn(() => ({
    data: {
      id: 'room-1',
      title: 'General',
      scope: 'project_room',
    },
    isLoading: false,
  })),
  useConversationSocket: vi.fn(() => ({
    connectionState: 'disconnected',
    typingUsers: new Map(),
  })),
  useCreateConversation: vi.fn(() => ({
    mutate: vi.fn(),
    isPending: false,
  })),
  useInfiniteMessages: vi.fn(() => ({
    data: { pages: [{ items: [], total: 0 }] },
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
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe('UnifiedConversationWindow', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'innerWidth', { value: 1024, writable: true });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders floating dialog with messages title region', () => {
    render(
      <UnifiedConversationWindow
        projectId="p1"
        initialTarget={{ mode: 'conversation', conversationId: 'room-1' }}
        initialTargetKey={1}
        onClose={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByRole('dialog', { name: /messages/i })).toBeInTheDocument();
  });

  it('renders close control in header', () => {
    render(
      <UnifiedConversationWindow
        projectId="p1"
        initialTarget={{ mode: 'conversation', conversationId: 'room-1' }}
        initialTargetKey={1}
        onClose={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByRole('button', { name: /close messages/i })).toBeInTheDocument();
  });
});
