/**
 * CitationHighlighter - Parses and highlights behavior_* references in text
 */

import './CitationHighlighter.css';

interface CitationHighlighterProps {
  text: string;
  onCitationClick?: (behaviorId: string) => void;
}

// Regex to match behavior citations like `behavior_xyz` or behavior_xyz
const CITATION_PATTERN = /`?(behavior_[a-z0-9_]+)`?/gi;

interface TextSegment {
  type: 'text' | 'citation';
  content: string;
  behaviorId?: string;
}

function parseText(text: string): TextSegment[] {
  const segments: TextSegment[] = [];
  let lastIndex = 0;

  const matches = text.matchAll(CITATION_PATTERN);

  for (const match of matches) {
    // Add text before the match
    if (match.index !== undefined && match.index > lastIndex) {
      segments.push({
        type: 'text',
        content: text.slice(lastIndex, match.index),
      });
    }

    // Add the citation
    const behaviorId = match[1] || match[0].replace(/`/g, '');
    segments.push({
      type: 'citation',
      content: match[0],
      behaviorId: behaviorId.toLowerCase(),
    });

    lastIndex = (match.index || 0) + match[0].length;
  }

  // Add remaining text
  if (lastIndex < text.length) {
    segments.push({
      type: 'text',
      content: text.slice(lastIndex),
    });
  }

  return segments;
}

export function CitationHighlighter({ text, onCitationClick }: CitationHighlighterProps) {
  const segments = parseText(text);

  return (
    <span className="citation-highlighter">
      {segments.map((segment, index) => {
        if (segment.type === 'citation') {
          return (
            <span
              key={index}
              className="citation-badge"
              onClick={() => segment.behaviorId && onCitationClick?.(segment.behaviorId)}
              role={onCitationClick ? 'button' : undefined}
              tabIndex={onCitationClick ? 0 : undefined}
            >
              {segment.behaviorId}
            </span>
          );
        }
        return <span key={index}>{segment.content}</span>;
      })}
    </span>
  );
}

export default CitationHighlighter;
