/**
 * DocumentList Component
 *
 * High-performance document navigation with presence indicators
 */

import { useCallback, useMemo, memo } from 'react';
import type { Document } from '../../lib/collab-client';
import './DocumentList.css';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface DocumentListProps {
  documents: Document[];
  selectedId?: string;
  onSelect: (id: string) => void;
  onCreateNew?: (type: string) => void;
  activeUsers?: Map<string, { id: string; name: string; color: string }[]>;
  isLoading?: boolean;
}

interface DocumentItemProps {
  document: Document;
  isSelected: boolean;
  onSelect: (id: string) => void;
  presence?: { id: string; name: string; color: string }[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Icons (inline for performance)
// ─────────────────────────────────────────────────────────────────────────────

const PlanIcon = () => (
  <svg className="document-icon" viewBox="0 0 16 16" fill="none">
    <rect x="2" y="2" width="12" height="12" rx="2" stroke="currentColor" strokeWidth="1.5" />
    <path d="M5 5h6M5 8h6M5 11h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

const AgentIcon = () => (
  <svg className="document-icon" viewBox="0 0 16 16" fill="none">
    <circle cx="8" cy="5" r="3" stroke="currentColor" strokeWidth="1.5" />
    <path d="M3 14c0-2.761 2.239-5 5-5s5 2.239 5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

const WorkflowIcon = () => (
  <svg className="document-icon" viewBox="0 0 16 16" fill="none">
    <circle cx="4" cy="8" r="2" stroke="currentColor" strokeWidth="1.5" />
    <circle cx="12" cy="4" r="2" stroke="currentColor" strokeWidth="1.5" />
    <circle cx="12" cy="12" r="2" stroke="currentColor" strokeWidth="1.5" />
    <path d="M6 7l4-2M6 9l4 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

const OrgIcon = () => (
  <svg className="document-icon" viewBox="0 0 16 16" fill="none">
    <rect x="2" y="3" width="12" height="10" rx="2" stroke="currentColor" strokeWidth="1.5" />
    <path d="M5 6h2M9 6h2M5 9h2M9 9h2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

const GenericIcon = () => (
  <svg className="document-icon" viewBox="0 0 16 16" fill="none">
    <path
      d="M3 4.5A1.5 1.5 0 014.5 3h7A1.5 1.5 0 0113 4.5v7a1.5 1.5 0 01-1.5 1.5h-7A1.5 1.5 0 013 11.5v-7z"
      stroke="currentColor"
      strokeWidth="1.5"
    />
  </svg>
);

const PlusIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
    <path d="M7 3v8M3 7h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

const MoreIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
    <circle cx="7" cy="3" r="1" fill="currentColor" />
    <circle cx="7" cy="7" r="1" fill="currentColor" />
    <circle cx="7" cy="11" r="1" fill="currentColor" />
  </svg>
);

// ─────────────────────────────────────────────────────────────────────────────
// Document Icon Selector
// ─────────────────────────────────────────────────────────────────────────────

const getDocumentIcon = (type: string) => {
  switch (type) {
    case 'plan':
      return <PlanIcon />;
    case 'agent':
      return <AgentIcon />;
    case 'workflow':
      return <WorkflowIcon />;
    case 'org':
      return <OrgIcon />;
    default:
      return <GenericIcon />;
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// Document Item (memoized for perf)
// ─────────────────────────────────────────────────────────────────────────────

const DocumentItem = memo<DocumentItemProps>(({ document, isSelected, onSelect, presence = [] }) => {
  const handleClick = useCallback(() => {
    onSelect(document.id);
  }, [document.id, onSelect]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        onSelect(document.id);
      }
    },
    [document.id, onSelect]
  );

  const relativeTime = useMemo(() => {
    const updated = new Date(document.updated_at);
    const now = new Date();
    const diffMs = now.getTime() - updated.getTime();
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;

    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;

    const diffDays = Math.floor(diffHours / 24);
    if (diffDays < 7) return `${diffDays}d ago`;

    return updated.toLocaleDateString();
  }, [document.updated_at]);

  return (
    <div
      className={`document-item ${isSelected ? 'selected' : ''}`}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      tabIndex={0}
      role="button"
      aria-label={`Open ${document.document_type} document ${document.title}`}
      data-document-id={document.id}
    >
      {getDocumentIcon(document.document_type)}

      <div className="document-info">
        <span className="document-name">{document.title}</span>
        <div className="document-meta">
          <span className={`document-type-badge type-${document.document_type}`}>
            {document.document_type}
          </span>
          <span>{relativeTime}</span>
        </div>
      </div>

      {presence.length > 0 && (
        <div className="document-presence-dots" aria-label={`${presence.length} collaborators active`}>
          {presence.slice(0, 3).map((user) => (
            <div
              key={user.id}
              className="document-presence-dot"
              style={{ backgroundColor: user.color }}
              title={user.name}
            />
          ))}
        </div>
      )}

      <div className="document-actions">
        <button
          className="document-action-btn"
          onClick={(e) => {
            e.stopPropagation();
            // TODO: Open context menu
          }}
          aria-label={`More actions for ${document.title}`}
          title={`More actions for ${document.title}`}
        >
          <MoreIcon />
        </button>
      </div>
    </div>
  );
});

DocumentItem.displayName = 'DocumentItem';

// ─────────────────────────────────────────────────────────────────────────────
// Skeleton Loader
// ─────────────────────────────────────────────────────────────────────────────

const DocumentSkeleton = () => (
  <div className="document-skeleton">
    <div className="skeleton-icon" />
    <div className="skeleton-text" />
  </div>
);

// ─────────────────────────────────────────────────────────────────────────────
// Document List
// ─────────────────────────────────────────────────────────────────────────────

export const DocumentList = memo<DocumentListProps>(
  ({ documents, selectedId, onSelect, onCreateNew, activeUsers, isLoading }) => {
    // Group documents by type
    const groupedDocs = useMemo(() => {
      const groups: Record<string, Document[]> = {};

      documents.forEach((doc) => {
        const type = doc.document_type;
        if (!groups[type]) {
          groups[type] = [];
        }
        groups[type].push(doc);
      });

      // Sort each group by updated_at desc
      Object.keys(groups).forEach((type) => {
        groups[type].sort(
          (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
        );
      });

      return groups;
    }, [documents]);

    const handleCreateNew = useCallback(
      (type: string) => {
        onCreateNew?.(type);
      },
      [onCreateNew]
    );

    if (isLoading) {
      return (
        <div className="document-list">
          {[...Array(5)].map((_, i) => (
            <DocumentSkeleton key={i} />
          ))}
        </div>
      );
    }

    if (documents.length === 0) {
      return (
        <div className="document-list">
          <button
            className="new-document-button"
            onClick={() => handleCreateNew('plan')}
            aria-label="Create your first plan"
          >
            <PlusIcon />
            Create your first plan
          </button>
        </div>
      );
    }

    return (
      <div className="document-list">
        {Object.entries(groupedDocs).map(([type, docs]) => (
          <div key={type} className="document-list-section">
            <div className="document-list-header">
              <span>{type}s</span>
              <span>({docs.length})</span>
            </div>

            {docs.map((doc) => (
              <DocumentItem
                key={doc.id}
                document={doc}
                isSelected={selectedId === doc.id}
                onSelect={onSelect}
                presence={activeUsers?.get(doc.id)}
              />
            ))}
          </div>
        ))}

        {onCreateNew && (
          <button
            className="new-document-button"
            onClick={() => handleCreateNew('plan')}
            aria-label="Create a new plan"
          >
            <PlusIcon />
            New plan
          </button>
        )}
      </div>
    );
  }
);

DocumentList.displayName = 'DocumentList';

export default DocumentList;
