/**
 * Inline workspace artifact chips + markdown renderer that swaps matching
 * inline `code` / **strong** tokens for the same chips as structured cards.
 */

import { memo, useMemo } from 'react';
import { Link } from 'react-router-dom';
import Markdown from 'react-markdown';
import type { Components } from 'react-markdown';
import {
  chatMarkdownComponents,
  chatMarkdownRehypePlugins,
  chatMarkdownRemarkPlugins,
} from './chatMarkdown';
import type { ChatArtifactKind, ChatArtifactRef } from './chatArtifactRefsFromRows';
import {
  buildArtifactMarkdownLookup,
  resolveChatArtifactMarkdownToken,
  stringifyMdChildren,
} from './chatArtifactRefsFromRows';

function kindNoun(kind: ChatArtifactKind): string {
  switch (kind) {
    case 'work_item':
      return 'Work item';
    case 'project':
      return 'Project';
    case 'board':
      return 'Board';
    case 'agent':
      return 'Agent';
    case 'run':
      return 'Run';
    case 'behavior':
      return 'Behavior';
    case 'wiki':
      return 'Wiki page';
    case 'org':
      return 'Organization';
    case 'resource':
      return 'Resource';
    default:
      return 'Resource';
  }
}

/** Two work item refs pointing at the same board item (title + id chips). */
export function getDualWorkItemTitleIdRefs(refs: ChatArtifactRef[]): [ChatArtifactRef, ChatArtifactRef] | null {
  if (refs.length < 2) return null;
  for (let i = 0; i < refs.length - 1; i += 1) {
    const a = refs[i];
    const b = refs[i + 1];
    if (
      a.kind === 'work_item' &&
      b.kind === 'work_item' &&
      a.to &&
      b.to &&
      a.to === b.to &&
      a.refRole === 'title' &&
      b.refRole === 'id'
    ) {
      return [a, b];
    }
  }
  return null;
}

export const ArtifactChipLink = memo(function ArtifactChipLink({
  artifact,
  listItem,
}: {
  artifact: ChatArtifactRef;
  listItem: boolean;
}) {
  const kindClass = `msg-artifact-chip msg-artifact-chip--${artifact.kind}`;
  const isIdRole = artifact.refRole === 'id';
  const chip = (
    <>
      {!isIdRole && <span className="msg-artifact-chip-kind">{kindNoun(artifact.kind)}</span>}
      {isIdRole && <span className="msg-artifact-chip-kind msg-artifact-chip-kind--muted">ID</span>}
      <span
        className={`msg-artifact-chip-label${isIdRole ? ' msg-artifact-chip-label--mono' : ''}`}
      >
        {artifact.label}
      </span>
    </>
  );
  const ariaOpen = `${kindNoun(artifact.kind)}${isIdRole ? ' id' : ''}: ${artifact.label}`;
  const inner =
    artifact.to != null ? (
      <Link
        to={artifact.to}
        className={`${kindClass} pressable`}
        aria-label={`Open ${ariaOpen}`}
      >
        {chip}
      </Link>
    ) : (
      <span
        className={`${kindClass} msg-artifact-chip--disabled`}
        title={artifact.disabledReason ?? 'Cannot navigate to this resource from chat.'}
        aria-label={`${kindNoun(artifact.kind)} (not linkable): ${artifact.label}`}
      >
        {chip}
      </span>
    );
  if (listItem) {
    return (
      <div
        key={artifact.key}
        role="listitem"
        className={`msg-artifact-chip-li${artifact.to ? '' : ' msg-artifact-chip-li--disabled'}`}
        aria-label={
          artifact.to
            ? undefined
            : `${kindNoun(artifact.kind)} (not linkable): ${artifact.label}`
        }
      >
        {inner}
      </div>
    );
  }
  return (
    <span key={artifact.key} className="msg-artifact-chip-inline-li">
      {inner}
    </span>
  );
});

export const ArtifactChipRow = memo(function ArtifactChipRow({ refs }: { refs: ChatArtifactRef[] }) {
  if (refs.length === 0) return null;
  const dual = getDualWorkItemTitleIdRefs(refs);
  const filtered =
    dual != null ? refs.filter((r) => r.key !== dual[0].key && r.key !== dual[1].key) : refs;
  if (filtered.length === 0) return null;
  return (
    <div className="msg-artifact-chip-row" role="list" aria-label="Referenced workspace artifacts">
      {filtered.map((a) => (
        <ArtifactChipLink key={a.key} artifact={a} listItem />
      ))}
    </div>
  );
});

export const ChatMarkdownWithArtifacts = memo(function ChatMarkdownWithArtifacts({
  markdown,
  refs,
}: {
  markdown: string;
  refs: ChatArtifactRef[];
}) {
  const artifactLookup = useMemo(() => buildArtifactMarkdownLookup(refs), [refs]);

  const components = useMemo<Partial<Components>>(() => {
    const resolveRef = (raw: string): ChatArtifactRef | undefined =>
      resolveChatArtifactMarkdownToken(artifactLookup, refs, raw);

    return {
      ...chatMarkdownComponents,
      code: ({ className, children, ...rest }) => {
        if (
          typeof className === 'string' &&
          (className.includes('hljs') || className.includes('language-'))
        ) {
          return (
            <code className={className} {...rest}>
              {children}
            </code>
          );
        }
        const text = stringifyMdChildren(children);
        const ref = resolveRef(text);
        if (ref) {
          return <ArtifactChipLink artifact={ref} listItem={false} />;
        }
        return (
          <code className={className} {...rest}>
            {children}
          </code>
        );
      },
      strong: ({ children, ...rest }) => {
        const text = stringifyMdChildren(children);
        const ref = resolveRef(text);
        if (ref) {
          return <ArtifactChipLink artifact={ref} listItem={false} />;
        }
        return <strong {...rest}>{children}</strong>;
      },
    };
  }, [artifactLookup, refs]);

  return (
    <Markdown
      remarkPlugins={chatMarkdownRemarkPlugins}
      rehypePlugins={chatMarkdownRehypePlugins}
      components={components}
    >
      {markdown}
    </Markdown>
  );
});
