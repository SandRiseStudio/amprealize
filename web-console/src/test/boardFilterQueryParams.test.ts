import { describe, expect, it } from 'vitest';
import { filtersToQueryParams } from '../components/boards/useBoardFilters';

describe('filtersToQueryParams', () => {
  it('preserves multi-select board filters for server-backed work-item queries', () => {
    const query = filtersToQueryParams(
      {
        query: 'Urgent',
        types: ['goal', 'task'],
        priorities: ['critical', 'high'],
        assigneeId: '__unassigned__',
        assigneeType: null,
        labels: ['backend', 'latency'],
        dueAfter: '2026-04-01',
        dueBefore: '2026-04-30',
      },
      {
        field: 'updated_at',
        order: 'desc',
      },
    );

    expect(query).toEqual({
      titleSearch: 'Urgent',
      itemTypes: ['goal', 'task'],
      priorities: ['critical', 'high'],
      assigneeId: '__unassigned__',
      labels: ['backend', 'latency'],
      dueAfter: '2026-04-01',
      dueBefore: '2026-04-30',
      sortBy: 'updated_at',
      order: 'desc',
    });
  });

  it('omits default sort and empty filters from the server query payload', () => {
    const query = filtersToQueryParams(
      {
        query: '',
        types: [],
        priorities: [],
        assigneeId: null,
        assigneeType: null,
        labels: [],
        dueAfter: null,
        dueBefore: null,
      },
      {
        field: 'position',
        order: 'asc',
      },
    );

    expect(query).toEqual({});
  });
});
