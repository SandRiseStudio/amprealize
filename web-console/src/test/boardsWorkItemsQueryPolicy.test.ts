/**
 * Contract checks for board work-items React Query policy (GuideAI-1256).
 */

import { keepPreviousData } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import { WORK_ITEMS_LIST_PLACEHOLDER_DATA } from '../api/boards';

describe('useWorkItems query policy', () => {
  it('uses keepPreviousData for stable filter transitions', () => {
    expect(WORK_ITEMS_LIST_PLACEHOLDER_DATA).toBe(keepPreviousData);
  });
});
