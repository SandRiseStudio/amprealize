/**
 * Tests for MessageBubble and StreamingMessage components
 *
 * Verifies markdown rendering, structured cards, reactions, thinking indicator,
 * and token accumulation.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MessageBubble } from '../components/conversations/MessageBubble';
import { StreamingMessage } from '../components/conversations/StreamingMessage';
import type { ConversationMessage } from '../lib/collab-client';
import { MessageType, ActorType } from '../lib/collab-client';

// Mock the conversation hooks used by components
vi.mock('../api/conversations', () => ({
  useDeleteMessage: vi.fn(() => ({ mutate: vi.fn() })),
  useAddReaction: vi.fn(() => ({ mutate: vi.fn() })),
  useRemoveReaction: vi.fn(() => ({ mutate: vi.fn() })),
  useMessageStream: vi.fn(() => ({
    tokens: [],
    fullText: '',
    isStreaming: true,
    error: null,
  })),
}));

// Import the mock to control return values in tests
import { useMessageStream } from '../api/conversations';
const mockUseMessageStream = vi.mocked(useMessageStream);

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

function makeMessage(overrides: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: 'msg-1',
    conversation_id: 'conv-1',
    sender_id: 'user-1',
    sender_type: ActorType.User,
    content: 'Hello, world!',
    message_type: MessageType.Text,
    structured_payload: null,
    parent_id: null,
    run_id: null,
    behavior_id: null,
    work_item_id: null,
    is_edited: false,
    edited_at: null,
    is_deleted: false,
    deleted_at: null,
    metadata: {},
    created_at: '2026-01-15T10:00:00Z',
    reactions: [],
    reply_count: 0,
    ...overrides,
  };
}

// Default props to pass with message
const defaultBubbleProps = {
  isFirstInGroup: true,
  isOwn: false,
  conversationId: 'conv-1',
  currentUserId: 'user-1',
};

describe('MessageBubble', () => {
  it('renders message content', () => {
    render(
      <MessageBubble
        message={makeMessage({ content: 'Test message' })}
        {...defaultBubbleProps}
      />,
      { wrapper: createWrapper() }
    );
    expect(screen.getByText('Test message')).toBeInTheDocument();
  });

  it('applies own class for current user messages', () => {
    const { container } = render(
      <MessageBubble
        message={makeMessage({ sender_type: ActorType.User })}
        {...defaultBubbleProps}
        isOwn={true}
      />,
      { wrapper: createWrapper() }
    );
    // The component uses 'msg-bubble--own' class for own messages
    expect(container.querySelector('.msg-bubble--own')).toBeInTheDocument();
  });

  it('applies agent class for agent messages', () => {
    const { container } = render(
      <MessageBubble
        message={makeMessage({ sender_type: ActorType.Agent })}
        {...defaultBubbleProps}
        isOwn={false}
      />,
      { wrapper: createWrapper() }
    );
    // Agent messages should not have --own class
    expect(container.querySelector('.msg-bubble--own')).not.toBeInTheDocument();
  });

  it('renders timestamp', () => {
    const { container } = render(
      <MessageBubble
        message={makeMessage({ created_at: '2026-01-15T10:30:00Z' })}
        {...defaultBubbleProps}
      />,
      { wrapper: createWrapper() }
    );
    // Should render timestamp in msg-timestamp span
    const timestamp = container.querySelector('.msg-timestamp');
    expect(timestamp).toBeInTheDocument();
    // The exact format depends on locale/timezone, just verify it exists
    expect(timestamp?.textContent).not.toBe('');
  });

  it('renders markdown bold text', () => {
    render(
      <MessageBubble
        message={makeMessage({ content: '**bold text**' })}
        {...defaultBubbleProps}
      />,
      { wrapper: createWrapper() }
    );
    const strong = screen.getByText('bold text');
    expect(strong.tagName).toBe('STRONG');
  });

  it('renders reactions when present', () => {
    const reactions = [
      { id: 'r1', message_id: 'msg-1', actor_id: 'user-1', actor_type: ActorType.User, emoji: '👍', created_at: null },
      { id: 'r2', message_id: 'msg-1', actor_id: 'user-2', actor_type: ActorType.User, emoji: '👍', created_at: null },
      { id: 'r3', message_id: 'msg-1', actor_id: 'user-3', actor_type: ActorType.User, emoji: '❤️', created_at: null },
    ];
    render(
      <MessageBubble
        message={makeMessage({ reactions })}
        {...defaultBubbleProps}
      />,
      { wrapper: createWrapper() }
    );
    expect(screen.getByText('👍')).toBeInTheDocument();
    expect(screen.getByText('❤️')).toBeInTheDocument();
  });

  it('renders structured card for status_card message type', () => {
    const { container } = render(
      <MessageBubble
        message={makeMessage({
          message_type: MessageType.StatusCard,
          structured_payload: {
            title: 'Build completed',
            summary: 'All tests passed',
            status: 'success',
          },
        })}
        {...defaultBubbleProps}
      />,
      { wrapper: createWrapper() }
    );
    // StatusCard should render with title
    expect(screen.getByText('Build completed')).toBeInTheDocument();
    // Should have card class
    expect(container.querySelector('.msg-card--status')).toBeInTheDocument();
  });

  it('has accessible class for message bubble', () => {
    const { container } = render(
      <MessageBubble message={makeMessage()} {...defaultBubbleProps} />,
      { wrapper: createWrapper() }
    );
    // Component uses className msg-bubble not role="article"
    const bubble = container.querySelector('.msg-bubble');
    expect(bubble).toBeInTheDocument();
  });

  it('shows hover actions on mouse enter', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <MessageBubble message={makeMessage()} {...defaultBubbleProps} />,
      { wrapper: createWrapper() }
    );

    const bubble = container.querySelector('.msg-bubble');
    expect(bubble).toBeInTheDocument();

    // Actions should not be visible initially
    expect(container.querySelector('.msg-actions')).not.toBeInTheDocument();

    // Hover over the bubble
    await user.hover(bubble!);

    // Actions container should appear (className is msg-actions, not msg-bubble-actions)
    expect(container.querySelector('.msg-actions')).toBeInTheDocument();
  });
});

describe('StreamingMessage', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Reset mock to default state
    mockUseMessageStream.mockReturnValue({
      tokens: [],
      fullText: '',
      isStreaming: true,
      error: null,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders thinking indicator when no content', () => {
    mockUseMessageStream.mockReturnValue({
      tokens: [],
      fullText: '',
      isStreaming: true,
      error: null,
    });

    render(
      <StreamingMessage conversationId="conv-1" messageId="msg-1" />,
      { wrapper: createWrapper() }
    );
    expect(screen.getByText(/thinking/i)).toBeInTheDocument();
  });

  it('renders animated thinking dots', () => {
    mockUseMessageStream.mockReturnValue({
      tokens: [],
      fullText: '',
      isStreaming: true,
      error: null,
    });

    const { container } = render(
      <StreamingMessage conversationId="conv-1" messageId="msg-2" />,
      { wrapper: createWrapper() }
    );
    // Check for thinking indicator elements
    expect(container.querySelector('.streaming-msg--thinking')).toBeInTheDocument();
  });

  it('renders streamed content when available', () => {
    mockUseMessageStream.mockReturnValue({
      tokens: ['Hello', ', ', 'world', '!'],
      fullText: 'Hello, world!',
      isStreaming: true,
      error: null,
    });

    render(
      <StreamingMessage conversationId="conv-1" messageId="msg-3" />,
      { wrapper: createWrapper() }
    );
    expect(screen.getByText('Hello, world!')).toBeInTheDocument();
  });

  it('shows complete state when streaming finishes', () => {
    mockUseMessageStream.mockReturnValue({
      tokens: ['Done', ' ', 'streaming'],
      fullText: 'Done streaming',
      isStreaming: false,
      error: null,
    });

    const { container } = render(
      <StreamingMessage conversationId="conv-1" messageId="msg-4" />,
      { wrapper: createWrapper() }
    );
    expect(container.querySelector('.streaming-msg--complete')).toBeInTheDocument();
  });

  it('shows error state on connection failure', () => {
    mockUseMessageStream.mockReturnValue({
      tokens: [],
      fullText: '',
      isStreaming: false,
      error: 'Connection lost',
    });

    const { container } = render(
      <StreamingMessage conversationId="conv-1" messageId="msg-5" />,
      { wrapper: createWrapper() }
    );
    expect(container.querySelector('.streaming-msg--error')).toBeInTheDocument();
    expect(screen.getByText(/connection lost/i)).toBeInTheDocument();
  });

  it('renders markdown in streamed content', () => {
    mockUseMessageStream.mockReturnValue({
      tokens: ['**bold**', ' ', 'text'],
      fullText: '**bold** text',
      isStreaming: true,
      error: null,
    });

    render(
      <StreamingMessage conversationId="conv-1" messageId="msg-6" />,
      { wrapper: createWrapper() }
    );
    const strong = screen.getByText('bold');
    expect(strong.tagName).toBe('STRONG');
  });
});
