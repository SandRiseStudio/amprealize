/**
 * Tests for the redesigned Work Item Drawer "Children" card.
 *
 * Verifies that for a goal with children spanning all three status mappings:
 * - the board-style rollup chip (`work-item-rollup-chip-inline`) shows linked count and completion
 * - each child row carries a `children-status-pill` with Backlog / In progress / Done and the matching status class
 * - in-progress rows render before backlog rows, and done rows render last
 */

import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import {
  bucketForChild,
  compareChildrenByStatus,
  labelForChildBucket,
  WorkItemDrawer,
} from '../components/boards/WorkItemDrawer';
import type { BoardColumn, WorkItem } from '../api/boards';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const goalItem: WorkItem = {
  item_id: 'goal-1',
  item_type: 'goal',
  project_id: 'project-1',
  board_id: 'board-1',
  column_id: 'col-backlog',
  parent_id: null,
  title: 'Example goal for children rollup UI',
  description: '',
  status: 'in_progress',
  priority: 'high',
  position: 1,
  labels: [],
  assignee_id: null,
  assignee_type: null,
  display_number: 2099,
  metadata: {},
  created_at: '2026-04-28T18:00:00Z',
  updated_at: '2026-04-28T19:00:00Z',
  created_by: 'user-1',
};

function makeChild(
  partial: Partial<WorkItem> & Pick<WorkItem, 'item_id' | 'title' | 'column_id' | 'status' | 'position'>,
): WorkItem {
  return {
    item_type: 'feature',
    project_id: 'project-1',
    board_id: 'board-1',
    parent_id: 'goal-1',
    description: '',
    priority: 'medium',
    labels: [],
    assignee_id: null,
    assignee_type: null,
    display_number: 0,
    metadata: {},
    created_at: '2026-04-28T18:00:00Z',
    updated_at: '2026-04-28T19:00:00Z',
    created_by: 'user-1',
    ...partial,
  } as WorkItem;
}

const columns: BoardColumn[] = [
  {
    column_id: 'col-backlog',
    board_id: 'board-1',
    name: 'Backlog',
    position: 1,
    status_mapping: 'backlog',
    wip_limit: null,
    created_at: '2026-04-28T18:00:00Z',
    updated_at: '2026-04-28T18:00:00Z',
    created_by: 'user-1',
  },
  {
    column_id: 'col-doing',
    board_id: 'board-1',
    name: 'Doing',
    position: 2,
    status_mapping: 'in_progress',
    wip_limit: null,
    created_at: '2026-04-28T18:00:00Z',
    updated_at: '2026-04-28T18:00:00Z',
    created_by: 'user-1',
  },
  {
    column_id: 'col-done',
    board_id: 'board-1',
    name: 'Done',
    position: 3,
    status_mapping: 'done',
    wip_limit: null,
    created_at: '2026-04-28T18:00:00Z',
    updated_at: '2026-04-28T18:00:00Z',
    created_by: 'user-1',
  },
];

const childA = makeChild({
  item_id: 'feat-A',
  title: 'A backlog work',
  column_id: 'col-backlog',
  status: 'backlog',
  position: 1,
  display_number: 2101,
});
const childB = makeChild({
  item_id: 'feat-B',
  title: 'B in flight',
  column_id: 'col-doing',
  status: 'in_progress',
  position: 2,
  display_number: 2102,
});
const childC = makeChild({
  item_id: 'feat-C',
  title: 'C shipped',
  column_id: 'col-done',
  status: 'done',
  position: 3,
  display_number: 2103,
});
const childD = makeChild({
  item_id: 'feat-D',
  title: 'D more backlog',
  column_id: 'col-backlog',
  status: 'backlog',
  position: 4,
  display_number: 2104,
});
const childE = makeChild({
  item_id: 'feat-E',
  title: 'E another in flight',
  column_id: 'col-doing',
  status: 'in_progress',
  position: 5,
  display_number: 2105,
});

const allItems: WorkItem[] = [goalItem, childA, childB, childC, childD, childE];

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockMutation = {
  mutate: vi.fn(),
  mutateAsync: vi.fn(),
  isPending: false,
  isError: false,
};

vi.mock('../auth', () => ({
  useAuth: () => ({
    actor: { id: 'user-1', displayName: 'Nick Sanders', role: 'owner' },
  }),
}));

vi.mock('../api/boards', () => ({
  useWorkItem: () => ({ data: goalItem, isLoading: false, isError: false }),
  useWorkItems: () => ({ data: allItems, isLoading: false }),
  useWorkItemComments: () => ({
    data: [],
    isLoading: false,
    isFetching: false,
    refetch: vi.fn(),
  }),
  useWorkItemProgressRollup: () => ({
    data: {
      item_id: 'goal-1',
      completion_percent: 25,
      buckets: { not_started: 2, in_progress: 2, completed: 1, total: 5 },
      remaining: { items_remaining: 4, estimated_hours_remaining: null, points_remaining: null },
      incomplete_items: [],
    },
  }),
  useUpdateWorkItem: () => mockMutation,
  useAssignWorkItem: () => mockMutation,
  useUnassignWorkItem: () => mockMutation,
  useCompleteWithDescendants: () => mockMutation,
  usePostWorkItemComment: () => mockMutation,
}));

vi.mock('../api/executions', () => ({
  useWorkItemExecutionStatus: () => ({
    data: null,
    isLoading: false,
    isFetching: false,
    refetch: vi.fn(),
  }),
  useExecutionSteps: () => ({ data: { steps: [], total: 0 } }),
  useExecutionStream: () => ({ isConnected: false, connectionState: 'disconnected' }),
  useExecuteWorkItem: () => mockMutation,
  useCancelWorkItemExecution: () => mockMutation,
  useProvideClarification: () => mockMutation,
  useApproveGate: () => mockMutation,
}));

vi.mock('../lib/collab-client', () => ({
  ExecutionStatusCard: () => <div>Execution status</div>,
  ClarificationPanel: () => <div>Clarification panel</div>,
}));

function renderDrawer() {
  return render(
    <WorkItemDrawer
      projectId="project-1"
      projectSlug="GUIDEAI"
      orgId="org-1"
      boardId="board-1"
      itemId="goal-1"
      columns={columns}
      targetPositions={{ 'col-backlog': 1, 'col-doing': 2, 'col-done': 3 }}
      initialItem={goalItem}
      assigneeIndex={new Map()}
      assignableHumans={[]}
      assignableAgents={[]}
      onMove={vi.fn()}
      onCopyWorkItemId={vi.fn()}
      onNotify={vi.fn()}
      onRequestClose={vi.fn()}
      onOpenItem={vi.fn()}
    />,
  );
}

// ---------------------------------------------------------------------------
// Pure helper unit tests
// ---------------------------------------------------------------------------

describe('bucketForChild', () => {
  it('uses the column status mapping when present, even if the column was renamed', () => {
    const renamedDoing = { ...columns[1], name: 'Active' };
    const cols = [columns[0], renamedDoing, columns[2]];
    expect(bucketForChild(childB, cols)).toBe('in_progress');
  });

  it('treats in_review columns as in_progress', () => {
    const reviewColumn: BoardColumn = {
      ...columns[1],
      column_id: 'col-review',
      status_mapping: 'in_review',
    };
    const reviewChild = makeChild({
      item_id: 'feat-R',
      title: 'R review',
      column_id: 'col-review',
      status: 'in_review',
      position: 0,
    });
    expect(bucketForChild(reviewChild, [columns[0], reviewColumn])).toBe('in_progress');
  });

  it('falls back to the child status when the column is missing', () => {
    const orphan = makeChild({
      item_id: 'orphan',
      title: 'orphan',
      column_id: 'missing-col',
      status: 'done',
      position: 0,
    });
    expect(bucketForChild(orphan, columns)).toBe('done');
  });

  it('defaults to not_started for unknown statuses', () => {
    const orphan = makeChild({
      item_id: 'orphan',
      title: 'orphan',
      column_id: 'missing-col',
      status: 'backlog',
      position: 0,
    });
    expect(bucketForChild(orphan, columns)).toBe('not_started');
  });
});

describe('labelForChildBucket', () => {
  it('maps buckets to short progress labels', () => {
    expect(labelForChildBucket('not_started')).toBe('Backlog');
    expect(labelForChildBucket('in_progress')).toBe('In progress');
    expect(labelForChildBucket('done')).toBe('Done');
  });
});

describe('compareChildrenByStatus', () => {
  it('orders in-progress before backlog and done', () => {
    const sorted = [childA, childC, childB, childD, childE].slice().sort((a, b) =>
      compareChildrenByStatus(a, b, columns),
    );
    expect(sorted.map((c) => c.item_id)).toEqual([
      'feat-B',
      'feat-E',
      'feat-A',
      'feat-D',
      'feat-C',
    ]);
  });

  it('breaks ties with board position', () => {
    const a = makeChild({ item_id: 'a', title: 'a', column_id: 'col-doing', status: 'in_progress', position: 5 });
    const b = makeChild({ item_id: 'b', title: 'b', column_id: 'col-doing', status: 'in_progress', position: 1 });
    const sorted = [a, b].sort((x, y) => compareChildrenByStatus(x, y, columns));
    expect(sorted.map((c) => c.item_id)).toEqual(['b', 'a']);
  });
});

// ---------------------------------------------------------------------------
// Drawer rendering tests
// ---------------------------------------------------------------------------

describe('WorkItemDrawer children card', () => {
  it('renders the board-style rollup chip with linked count and percent for a mixed-status goal', () => {
    const { container } = renderDrawer();
    const chip = container.querySelector('.work-item-rollup-chip-inline.work-item-rollup-chip-inline-progress');
    expect(chip).not.toBeNull();
    expect(chip).toHaveTextContent('5 linked');
    expect(chip).toHaveTextContent('25%');
    expect(container.querySelector('.children-rollup-remaining')).toHaveTextContent('4 left');
  });

  it('renders one row per child with a status pill matching its bucket', () => {
    const { container } = renderDrawer();
    const rowsContainer = container.querySelector('.children-rows');
    expect(rowsContainer).not.toBeNull();
    const rows = rowsContainer!.querySelectorAll('.children-row');
    expect(rows.length).toBe(5);

    // Each row carries the correct status class
    const findRow = (title: string) =>
      Array.from(rows).find((row) => within(row as HTMLElement).queryByText(title)) as HTMLElement;

    expect(findRow('A backlog work').className).toContain('children-row-not-started');
    expect(findRow('B in flight').className).toContain('children-row-in-progress');
    expect(findRow('C shipped').className).toContain('children-row-done');

    expect(within(findRow('B in flight')).getByText('In progress')).toHaveClass('children-status-in-progress');
    expect(within(findRow('A backlog work')).getByText('Backlog')).toHaveClass('children-status-not-started');
    expect(within(findRow('C shipped')).getByText('Done')).toHaveClass('children-status-done');
    expect(within(findRow('B in flight')).getByText('Doing')).toHaveClass('children-row-column');
  });

  it('orders rows in-progress first, then backlog, then done', () => {
    const { container } = renderDrawer();
    const rows = container.querySelectorAll('.children-rows .children-row');
    const titles = Array.from(rows).map(
      (row) => row.querySelector('.children-row-title-text')?.textContent?.trim() ?? '',
    );
    expect(titles).toEqual([
      'B in flight',
      'E another in flight',
      'A backlog work',
      'D more backlog',
      'C shipped',
    ]);
  });

  it('orders main column: sticky hero, children card, then activity', () => {
    const { container } = renderDrawer();
    const main = container.querySelector('.work-item-studio-main');
    expect(main).not.toBeNull();
    const sections = main!.querySelectorAll(':scope > section');
    expect(sections.length).toBeGreaterThanOrEqual(3);
    expect(sections[0].className).toContain('work-item-hero-surface');
    expect(sections[1].className).toContain('work-item-card-children');
    expect(within(sections[2] as HTMLElement).getByText('Activity')).toBeTruthy();
  });

  it('opens the child item when the row title button is clicked', () => {
    const onOpenItem = vi.fn();
    render(
      <WorkItemDrawer
        projectId="project-1"
        projectSlug="GUIDEAI"
        orgId="org-1"
        boardId="board-1"
        itemId="goal-1"
        columns={columns}
        targetPositions={{ 'col-backlog': 1, 'col-doing': 2, 'col-done': 3 }}
        initialItem={goalItem}
        assigneeIndex={new Map()}
        assignableHumans={[]}
        assignableAgents={[]}
        onMove={vi.fn()}
        onCopyWorkItemId={vi.fn()}
        onNotify={vi.fn()}
        onRequestClose={vi.fn()}
        onOpenItem={onOpenItem}
      />,
    );
    const titleBtn = screen.getByRole('button', { name: /Open linked item GUIDEAI-2102: B in flight/i });
    titleBtn.click();
    expect(onOpenItem).toHaveBeenCalledWith('feat-B');
  });

  it('copies child display id when the display id chip is clicked', () => {
    const onCopyWorkItemId = vi.fn();
    render(
      <WorkItemDrawer
        projectId="project-1"
        projectSlug="GUIDEAI"
        orgId="org-1"
        boardId="board-1"
        itemId="goal-1"
        columns={columns}
        targetPositions={{ 'col-backlog': 1, 'col-doing': 2, 'col-done': 3 }}
        initialItem={goalItem}
        assigneeIndex={new Map()}
        assignableHumans={[]}
        assignableAgents={[]}
        onMove={vi.fn()}
        onCopyWorkItemId={onCopyWorkItemId}
        onNotify={vi.fn()}
        onRequestClose={vi.fn()}
        onOpenItem={vi.fn()}
      />,
    );
    const idChip = within(screen.getByText('B in flight').closest('.children-row')!).getByRole('button', {
      name: /Copy display ID GUIDEAI-2102/i,
    });
    idChip.click();
    expect(onCopyWorkItemId).toHaveBeenCalledWith('feat-B', 'GUIDEAI-2102');
  });
});
