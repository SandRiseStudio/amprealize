/**
 * Column Summary Strip — at-a-glance distribution + jump-to-column
 *
 * Bottom-anchored floating pill bar showing column counts with active-viewport
 * highlighting.  Appears only when 5+ columns exist.
 */

import { memo } from 'react';
import type { BoardColumn, WorkItem } from '../../api/boards';

function getColumnAccentIndex(index: number): number {
  const accentCount = 6;
  const next = index % accentCount;
  return next < 0 ? next + accentCount : next;
}

export interface ColumnSummaryStripProps {
  columns: BoardColumn[];
  itemsByColumnId: Record<string, WorkItem[]>;
  filterResult: { isFiltered: boolean; matchingIds: Set<string>; matchCount: number };
  visibleColumnIds: Set<string>;
  onJumpToColumn: (columnId: string) => void;
}

export const ColumnSummaryStrip = memo(function ColumnSummaryStrip({
  columns,
  itemsByColumnId,
  filterResult,
  visibleColumnIds,
  onJumpToColumn,
}: ColumnSummaryStripProps) {
  // Only show when there are 5+ columns
  if (columns.length < 5) return null;

  return (
    <nav className="column-summary-strip column-summary-strip-floating" aria-label="Column summary">
      <div className="column-summary-pills">
        {columns.map((col, index) => {
          const colItems = itemsByColumnId[col.column_id] ?? [];
          const total = colItems.length;
          const matched = filterResult.isFiltered
            ? colItems.filter((item) => filterResult.matchingIds.has(item.item_id)).length
            : total;
          const isVisible = visibleColumnIds.has(col.column_id);
          const accentIdx = getColumnAccentIndex(index);

          return (
            <button
              key={col.column_id}
              type="button"
              className={`column-summary-pill column-summary-accent-${accentIdx}${isVisible ? ' column-summary-pill-active' : ''}`}
              onClick={() => onJumpToColumn(col.column_id)}
              aria-label={`${col.name}: ${filterResult.isFiltered ? `${matched} of ${total}` : total} items — click to scroll`}
              title={`Jump to ${col.name}`}
            >
              <span className="column-summary-pill-name">{col.name}</span>
              <span className="column-summary-pill-count">
                {filterResult.isFiltered ? (
                  <><span className="column-summary-pill-matched">{matched}</span>/{total}</>
                ) : (
                  total
                )}
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
});
