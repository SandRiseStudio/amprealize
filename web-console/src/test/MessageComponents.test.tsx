/**
 * Tests for MessageBubble and StreamingMessage components
 *
 * Verifies markdown rendering, structured cards, reactions, thinking indicator,
 * and token accumulation.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { MessageBubble } from '../components/conversations/MessageBubble';
import { isPersistedAssistantStreamMessage, MessageList } from '../components/conversations/MessageList';
import { StreamingMessage } from '../components/conversations/StreamingMessage';
import type { ConversationMessage } from '../lib/collab-client';
import { MessageType, ActorType } from '../lib/collab-client';

vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 60,
    getVirtualItems: () =>
      Array.from({ length: count }, (_value, index) => ({
        index,
        key: index,
        start: index * 60,
      })),
    measureElement: () => undefined,
    scrollToIndex: () => undefined,
  }),
}));

// Mock the conversation hooks used by components
vi.mock('../api/conversations', () => ({
  useDeleteMessage: vi.fn(() => ({ mutate: vi.fn() })),
  useAddReaction: vi.fn(() => ({ mutate: vi.fn() })),
  useRemoveReaction: vi.fn(() => ({ mutate: vi.fn() })),
  isChatLoadBenchEnabled: vi.fn(() => false),
  chatLoadBenchPhase: vi.fn(),
  chatLoadBenchThreadFirstPaint: vi.fn(),
  useInfiniteMessages: vi.fn(() => ({
    data: { pages: [{ items: [], total: 0, has_more: false }] },
    isLoading: false,
    fetchNextPage: vi.fn(),
    hasNextPage: false,
    isFetchingNextPage: false,
  })),
  useMessageStream: vi.fn(() => ({
    tokens: [],
    fullText: '',
    isStreaming: true,
    phase: 'scheduled',
    statusLabel: 'Thinking...',
    sourceCounts: null,
    traceSteps: [],
    sourceRows: [],
    badge: null,
    error: null,
  })),
}));

// Import the mock to control return values in tests
import { useMessageStream } from '../api/conversations';
const mockUseMessageStream = vi.mocked(useMessageStream);

function streamState(overrides: Partial<ReturnType<typeof useMessageStream>> = {}) {
  return {
    tokens: [],
    fullText: '',
    isStreaming: true,
    phase: 'scheduled',
    statusLabel: 'Thinking...',
    sourceCounts: null,
    traceSteps: [],
    sourceRows: [],
    badge: null,
    error: null,
    ...overrides,
  };
}

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          {children}
        </QueryClientProvider>
      </MemoryRouter>
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
    // Trailing clock: .msg-timestamp on semantic <time>
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

  it('renders work item as inline chip with board deep link when ids are present', () => {
    render(
      <MessageBubble
        message={makeMessage({
          message_type: MessageType.StatusCard,
          content: 'Status update for the governed work item.',
          structured_payload: {
            card_kind: 'work_item',
            title: 'Implement governed chat cards',
            work_item_id: 'wi-abc',
            project_id: 'proj-1',
            board_id: 'brd-1',
            status: 'In progress',
          },
        })}
        {...defaultBubbleProps}
      />,
      { wrapper: createWrapper() }
    );

    expect(screen.getByText('Status update for the governed work item.')).toBeInTheDocument();
    expect(screen.getByTestId('artifact-inline-flow')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open Work item: Implement governed chat cards/i })).toHaveAttribute(
      'href',
      '/projects/proj-1/boards/brd-1/items/wi-abc',
    );
    expect(screen.getByRole('link', { name: /Open Work item id: wi-abc/i })).toHaveAttribute(
      'href',
      '/projects/proj-1/boards/brd-1/items/wi-abc',
    );
  });

  it('renders run as chip linking to work item drawer when work item context exists', () => {
    render(
      <MessageBubble
        message={makeMessage({
          message_type: MessageType.StatusCard,
          content: 'Execution is queued.',
          structured_payload: {
            card_kind: 'run',
            title: 'Governed execution run',
            run_id: 'run-1',
            work_item_id: 'wi-1',
            project_id: 'proj-9',
            board_id: 'brd-9',
            queue_state: 'queued',
            phase: 'policy review',
          },
        })}
        {...defaultBubbleProps}
      />,
      { wrapper: createWrapper() }
    );

    expect(screen.getByText('Execution is queued.')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /Open Run: Governed execution run/i });
    expect(link).toHaveAttribute('href', '/projects/proj-9/boards/brd-9/items/wi-1');
  });

  it('renders run chip as disabled when no work item navigation target', () => {
    render(
      <MessageBubble
        message={makeMessage({
          message_type: MessageType.StatusCard,
          content: 'Run update.',
          structured_payload: {
            card_kind: 'run',
            title: 'Governed execution run',
            run_id: 'run-orphan',
            queue_state: 'queued',
          },
        })}
        {...defaultBubbleProps}
      />,
      { wrapper: createWrapper() }
    );

    expect(screen.getByText('Run update.')).toBeInTheDocument();
    expect(screen.getByRole('listitem', { name: /Run \(not linkable\)/i })).toBeInTheDocument();
  });

  it('renders plan and recovery artifact cards', () => {
    render(
      <>
        <MessageBubble
          message={makeMessage({
            id: 'msg-plan',
            message_type: MessageType.StatusCard,
            structured_payload: {
              card_kind: 'plan',
              title: 'Execution plan',
              status: 'awaiting approval',
              plan_artifact_id: 'plan-123',
              summary: 'A durable plan is ready for review.',
            },
          })}
          {...defaultBubbleProps}
        />
        <MessageBubble
          message={makeMessage({
            id: 'msg-recovery',
            message_type: MessageType.StatusCard,
            structured_payload: {
              card_kind: 'recovery',
              title: 'Run needs recovery',
              summary: 'The agent failed a tool permission check.',
            },
          })}
          {...defaultBubbleProps}
        />
      </>,
      { wrapper: createWrapper() }
    );

    expect(screen.getByRole('article', { name: /Plan plan-123/i })).toBeInTheDocument();
    expect(screen.getByText('Review plan')).toBeInTheDocument();
    expect(screen.getByRole('article', { name: /Recovery action Run needs recovery/i })).toBeInTheDocument();
    expect(screen.getByText('Show details')).toBeInTheDocument();
  });

  it('renders workspace inventory as plain text plus project chips', () => {
    const { container } = render(
      <MessageBubble
        message={makeMessage({
          message_type: MessageType.StatusCard,
          content: 'Based on workspace inventory, Alpha is available.',
          structured_payload: {
            card_kind: 'project_list',
            title: 'Accessible projects',
            summary: '2 projects found.',
            rows: [
              { id: 'proj-1', name: 'Alpha', status: 'endorsed' },
              { id: 'proj-2', name: 'Beta' },
            ],
          },
        })}
        {...defaultBubbleProps}
      />,
      { wrapper: createWrapper() }
    );

    expect(container.querySelector('.msg-artifact-card')).not.toBeInTheDocument();
    expect(screen.getByText(/Based on workspace inventory/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open Project: Alpha/i })).toHaveAttribute('href', '/projects/proj-1');
    expect(screen.getByRole('link', { name: /Open Project: Beta/i })).toHaveAttribute('href', '/projects/proj-2');
  });

  it('renders inline backtick project name as chip when it matches project_list row', () => {
    const { container } = render(
      <MessageBubble
        message={makeMessage({
          message_type: MessageType.StatusCard,
          content: 'See `Alpha` in the workspace.',
          structured_payload: {
            card_kind: 'project_list',
            title: 'Accessible projects',
            summary: '1 project found.',
            rows: [{ id: 'proj-1', name: 'Alpha', status: 'endorsed' }],
          },
        })}
        {...defaultBubbleProps}
      />,
      { wrapper: createWrapper() },
    );

    const md = container.querySelector('.msg-markdown--artifact-inline');
    expect(md).toBeTruthy();
    expect(within(md as HTMLElement).getByRole('link', { name: /Open Project: Alpha/i })).toHaveAttribute(
      'href',
      '/projects/proj-1',
    );
    expect(screen.queryByText('`Alpha`')).not.toBeInTheDocument();
  });

  it('renders 8-char hex inline code as project chip when label is full uuid', () => {
    const uuid = 'fedcba98-0000-4000-8000-000000000099';
    const { container } = render(
      <MessageBubble
        message={makeMessage({
          message_type: MessageType.StatusCard,
          content: `Open \`fedcba98\` from inventory.`,
          structured_payload: {
            card_kind: 'project_list',
            title: 'Projects',
            summary: '1 project found.',
            rows: [{ id: uuid }],
          },
        })}
        {...defaultBubbleProps}
      />,
      { wrapper: createWrapper() },
    );

    const md = container.querySelector('.msg-markdown--artifact-inline');
    expect(md).toBeTruthy();
    expect(within(md as HTMLElement).getByRole('link', { name: /Open Project:/i })).toHaveAttribute(
      'href',
      `/projects/${uuid}`,
    );
  });

  it('renders resource analysis as inline text with work item chips (not legacy analyst card)', () => {
    const { container } = render(
      <MessageBubble
        message={makeMessage({
          message_type: MessageType.Text,
          content: 'You have 2 work items on this board.',
          structured_payload: {
            card_kind: 'resource_analysis',
            title: 'Resource analysis',
            summary: '2 work items in scope.',
            analysis_mode: 'deterministic',
            query_plan: {
              intent: 'count',
              resource_type: 'work_items',
            },
            rows: [
              {
                resource_type: 'work_item',
                item_id: 'wi-1',
                title: 'Fix chat routing',
                status: 'blocked',
                project_id: 'proj-1',
                board_id: 'brd-1',
              },
              {
                resource_type: 'work_item',
                item_id: 'wi-2',
                title: 'Improve analytics',
                status: 'todo',
                project_id: 'proj-1',
                board_id: 'brd-1',
              },
            ],
          },
        })}
        {...defaultBubbleProps}
      />,
      { wrapper: createWrapper() }
    );

    expect(container.querySelector('.msg-artifact-card')).not.toBeInTheDocument();
    expect(screen.queryByText('Analyst answer')).not.toBeInTheDocument();
    expect(screen.getByText(/You have 2 work items on this board/i)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Open Work item: Fix chat routing/i })).not.toBeInTheDocument();
  });

  it('renders resource analysis project count with project artifact chips', () => {
    const { container } = render(
      <MessageBubble
        message={makeMessage({
          message_type: MessageType.Text,
          content: 'You have 2 projects.\n\n- Alpha (alpha) — `proj-1`\n- Beta (beta) — `proj-2`',
          structured_payload: {
            card_kind: 'resource_analysis',
            title: 'Resource analysis',
            summary: '2 projects in scope.',
            analysis_mode: 'deterministic',
            query_plan: {
              intent: 'count',
              resource_type: 'projects',
            },
            rows: [
              { resource_type: 'project', id: 'proj-1', name: 'Alpha', slug: 'alpha' },
              { resource_type: 'project', id: 'proj-2', name: 'Beta', slug: 'beta' },
            ],
          },
        })}
        {...defaultBubbleProps}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText(/You have 2 projects/i)).toBeInTheDocument();
    expect(container.querySelectorAll('a.msg-artifact-chip--project').length).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByRole('link', { name: /Open Project: Alpha/i }),
    ).toHaveAttribute('href', '/projects/proj-1');
  });

  it('renders single resource-analysis work item as inline dual chips in sentence flow', () => {
    render(
      <MessageBubble
        message={makeMessage({
          message_type: MessageType.Text,
          content: 'I found 1 work item in this scope: Fix routing [wi-99] - done in project proj-1',
          structured_payload: {
            card_kind: 'resource_analysis',
            title: 'Resource analysis',
            summary: '1 work item found.',
            analysis_mode: 'deterministic',
            query_plan: { intent: 'list', resource_type: 'work_items' },
            rows: [
              {
                resource_type: 'work_item',
                item_id: 'wi-99',
                title: 'Fix routing',
                status: 'todo',
                project_id: 'proj-1',
                board_id: 'brd-1',
              },
            ],
          },
        })}
        {...defaultBubbleProps}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByTestId('artifact-inline-flow')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open Work item: Fix routing/i })).toHaveAttribute(
      'href',
      '/projects/proj-1/boards/brd-1/items/wi-99',
    );
    expect(screen.getByRole('link', { name: /Open Work item id: wi-99/i })).toHaveAttribute(
      'href',
      '/projects/proj-1/boards/brd-1/items/wi-99',
    );
  });

  it('renders resource analysis type breakdown when insights are present', () => {
    render(
      <MessageBubble
        message={makeMessage({
          message_type: MessageType.Text,
          content: 'You have 2 features on this board.',
          structured_payload: {
            card_kind: 'resource_analysis',
            title: 'Resource analysis',
            summary: '2 features in scope.',
            analysis_mode: 'deterministic',
            query_plan: { intent: 'count', resource_type: 'work_items' },
            rows: [],
            insights: {
              by_item_type: [
                { item_type: 'feature', count: 2, item_type_label: 'Features' },
                { item_type: 'bug', count: 1, item_type_label: 'Bugs' },
              ],
              scoped_total: 3,
            },
          },
        })}
        {...defaultBubbleProps}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText(/Types in this scope/i)).toBeInTheDocument();
    expect(screen.getByText('Features')).toBeInTheDocument();
    expect(screen.getByText('Bugs')).toBeInTheDocument();
  });

  it('renders analysis run steps when analysis_run.cells is present', () => {
    render(
      <MessageBubble
        message={makeMessage({
          message_type: MessageType.Text,
          content: 'You have 2 work items in this scope.',
          structured_payload: {
            card_kind: 'resource_analysis',
            summary: 'ok',
            analysis_run: {
              cells: [
                { id: 'c1', kind: 'query', input: 'count bugs', status: 'miss' },
                { id: 'c2', kind: 'query', input: 'count features', status: 'ok' },
              ],
            },
          },
        })}
        {...defaultBubbleProps}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText(/Analysis steps/i)).toBeInTheDocument();
    expect(screen.getByText('count bugs')).toBeInTheDocument();
    expect(screen.getByText(/\(miss\)/i)).toBeInTheDocument();
    expect(screen.getByText(/\(ok\)/i)).toBeInTheDocument();
  });

  it('renders single work_item_list row as inline dual chips', () => {
    render(
      <MessageBubble
        message={makeMessage({
          message_type: MessageType.StatusCard,
          content: 'Latest item: Implement MCP [abc-000] - done in project proj-board',
          structured_payload: {
            card_kind: 'work_item_list',
            title: 'Recent work items',
            summary: '1 work item found.',
            rows: [
              {
                id: 'abc-000',
                title: 'Implement MCP',
                status: 'done',
                project_id: 'proj-board',
                board_id: 'brd-board',
              },
            ],
          },
        })}
        {...defaultBubbleProps}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByTestId('artifact-inline-flow')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open Work item: Implement MCP/i })).toHaveAttribute(
      'href',
      '/projects/proj-board/boards/brd-board/items/abc-000',
    );
    expect(screen.getByRole('link', { name: /Open Work item id: abc-000/i })).toHaveAttribute(
      'href',
      '/projects/proj-board/boards/brd-board/items/abc-000',
    );
  });

  it('renders platform action result with work item chip and deep link', () => {
    render(
      <MessageBubble
        message={makeMessage({
          message_type: MessageType.Text,
          content: 'Created goal work item: Ephemeral agents.',
          structured_payload: {
            type: 'platform_action_result',
            title: 'Work item created',
            summary: 'Created goal work item: Ephemeral agents.',
            data: {
              success: true,
              result: {
                item_id: 'wi-new',
                title: 'Ephemeral agents',
                board_id: 'brd-x',
                project_id: 'proj-x',
              },
            },
          },
        })}
        {...defaultBubbleProps}
      />,
      { wrapper: createWrapper() }
    );

    expect(screen.getByTestId('artifact-inline-flow')).toBeInTheDocument();
    expect(screen.getByText(/^Created goal$/)).toBeInTheDocument();
    expect(screen.queryByText(/Created goal work item: Ephemeral agents/i)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open Work item: Ephemeral agents/i })).toHaveAttribute(
      'href',
      '/projects/proj-x/boards/brd-x/items/wi-new',
    );
    expect(screen.getByRole('link', { name: /Open Work item id: wi-new/i })).toHaveAttribute(
      'href',
      '/projects/proj-x/boards/brd-x/items/wi-new',
    );
  });

  it('strips echoed project title for platform action with single project chip', () => {
    render(
      <MessageBubble
        message={makeMessage({
          message_type: MessageType.Text,
          content: 'Created project GuideAI: GuideAI.',
          structured_payload: {
            type: 'platform_action_result',
            title: 'Project created',
            summary: 'Created project GuideAI: GuideAI.',
            data: {
              success: true,
              resource_type: 'project',
              result: {
                id: 'proj-new',
                name: 'GuideAI',
              },
            },
          },
        })}
        {...defaultBubbleProps}
      />,
      { wrapper: createWrapper() }
    );

    expect(screen.getByText(/^Created project$/)).toBeInTheDocument();
    expect(screen.queryByText(/Created project GuideAI: GuideAI/i)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open Project: GuideAI/i })).toHaveAttribute('href', '/projects/proj-new');
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
    mockUseMessageStream.mockReturnValue(streamState());
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders thinking indicator when no content', () => {
    mockUseMessageStream.mockReturnValue(streamState({
      phase: 'context',
      statusLabel: 'Gathering workspace context',
    }));

    render(
      <StreamingMessage conversationId="conv-1" messageId="msg-1" />,
      { wrapper: createWrapper() }
    );
    expect(screen.getByText(/gathering workspace context/i)).toBeInTheDocument();
  });

  it('renders animated thinking dots', () => {
    mockUseMessageStream.mockReturnValue(streamState());

    const { container } = render(
      <StreamingMessage conversationId="conv-1" messageId="msg-2" />,
      { wrapper: createWrapper() }
    );
    // Check for thinking indicator elements
    expect(container.querySelector('.streaming-msg--thinking')).toBeInTheDocument();
  });

  it('renders streamed content when available', () => {
    mockUseMessageStream.mockReturnValue(streamState({
      tokens: ['Hello', ', ', 'world', '!'],
      fullText: 'Hello, world!',
      phase: 'generation',
      statusLabel: 'Generating answer',
    }));

    render(
      <StreamingMessage conversationId="conv-1" messageId="msg-3" />,
      { wrapper: createWrapper() }
    );
    expect(screen.getByText('Hello, world!')).toBeInTheDocument();
  });

  it('shows complete state when streaming finishes', () => {
    mockUseMessageStream.mockReturnValue(streamState({
      tokens: ['Done', ' ', 'streaming'],
      fullText: 'Done streaming',
      isStreaming: false,
      phase: 'complete',
      statusLabel: 'Answer ready',
    }));

    const { container } = render(
      <StreamingMessage conversationId="conv-1" messageId="msg-4" />,
      { wrapper: createWrapper() }
    );
    expect(container.querySelector('.streaming-msg--complete')).toBeInTheDocument();
  });

  it('shows error state on connection failure', () => {
    mockUseMessageStream.mockReturnValue(streamState({
      isStreaming: false,
      phase: 'error',
      statusLabel: 'Reply failed',
      error: 'Connection lost',
    }));

    const { container } = render(
      <StreamingMessage conversationId="conv-1" messageId="msg-5" />,
      { wrapper: createWrapper() }
    );
    expect(container.querySelector('.streaming-msg--error')).toBeInTheDocument();
    expect(screen.getByText(/connection lost/i)).toBeInTheDocument();
  });

  it('renders markdown in streamed content', () => {
    mockUseMessageStream.mockReturnValue(streamState({
      tokens: ['**bold**', ' ', 'text'],
      fullText: '**bold** text',
      phase: 'generation',
      statusLabel: 'Generating answer',
    }));

    render(
      <StreamingMessage conversationId="conv-1" messageId="msg-6" />,
      { wrapper: createWrapper() }
    );
    const strong = screen.getByText('bold');
    expect(strong.tagName).toBe('STRONG');
  });

  it('notifies when streaming completes', () => {
    const onComplete = vi.fn();
    mockUseMessageStream.mockReturnValue(streamState({
      tokens: ['Done'],
      fullText: 'Done',
      isStreaming: false,
      phase: 'complete',
      statusLabel: 'Answer ready',
      sourceCounts: { projects: 1 },
    }));

    render(
      <StreamingMessage conversationId="conv-1" messageId="msg-7" onComplete={onComplete} />,
      { wrapper: createWrapper() }
    );
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/answer ready/i)).toBeInTheDocument();
  });

  it('renders collapsed live trace and expands source rows', () => {
    mockUseMessageStream.mockReturnValue(streamState({
      tokens: ['Done'],
      fullText: 'Done',
      isStreaming: false,
      phase: 'complete',
      statusLabel: 'Answer ready',
      sourceCounts: { projects: 1, 'workspace.agent_assignments': 2 },
      traceSteps: [{ phase: 'direct_answer', label: 'Matched project-agent assignment question', row_count: 2 }],
      sourceRows: [{ id: 'agent-1', name: 'Engineering Agent', role: 'contributor' }],
      badge: 'Workspace inventory',
    }));

    render(
      <StreamingMessage conversationId="conv-1" messageId="msg-8" />,
      { wrapper: createWrapper() }
    );

    expect(screen.getAllByText(/workspace inventory/i).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: /show work/i }));
    expect(screen.getByText('Matched project-agent assignment question')).toBeInTheDocument();
    expect(screen.getByText('Engineering Agent')).toBeInTheDocument();
  });
});

describe('MessageList stream persistence matching', () => {
  beforeEach(() => {
    mockUseMessageStream.mockReturnValue(streamState());
  });

  it('does not treat a user message carrying stream_message_id as persisted assistant reply', () => {
    const userMessage = makeMessage({
      id: 'user-msg-1',
      sender_type: ActorType.User,
      metadata: { stream_message_id: 'stream-1' },
    });

    expect(isPersistedAssistantStreamMessage(userMessage, 'stream-1')).toBe(false);
  });

  it('matches an assistant message carrying the active stream id', () => {
    const assistantMessage = makeMessage({
      id: 'assistant-msg-1',
      sender_type: ActorType.Agent,
      metadata: { stream_message_id: 'stream-1' },
    });

    expect(isPersistedAssistantStreamMessage(assistantMessage, 'stream-1')).toBe(true);
  });

  it('matches an assistant message whose id is the active stream id', () => {
    const assistantMessage = makeMessage({
      id: 'stream-1',
      sender_type: ActorType.Agent,
      metadata: {},
    });

    expect(isPersistedAssistantStreamMessage(assistantMessage, 'stream-1')).toBe(true);
  });

  it('keeps the completed stream visible until the persisted assistant message arrives', () => {
    const onStreamingComplete = vi.fn();
    mockUseMessageStream.mockReturnValue(streamState({
      tokens: ['Stable reply'],
      fullText: 'Stable reply',
      isStreaming: false,
      phase: 'complete',
      statusLabel: 'Answer ready',
    }));

    render(
      <MessageList
        conversationId="conv-1"
        currentUserId="user-1"
        streamingMessageId="stream-1"
        onStreamingComplete={onStreamingComplete}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByText('Stable reply')).toBeInTheDocument();
    expect(onStreamingComplete).not.toHaveBeenCalled();
  });
});
