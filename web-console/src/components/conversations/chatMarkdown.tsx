import type { Components } from 'react-markdown';
import type { PluggableList } from 'unified';
import 'highlight.js/styles/github.css';
import rehypeHighlight from 'rehype-highlight';
import remarkBreaks from 'remark-breaks';
import remarkGfm from 'remark-gfm';

/** GFM plus single newlines → `<br>` inside paragraphs (chat-style prose). */
export const chatMarkdownRemarkPlugins = [remarkGfm, remarkBreaks];

/** Syntax highlighting for fenced ```lang blocks via lowlight / highlight.js. */
export const chatMarkdownRehypePlugins: PluggableList = [
  [rehypeHighlight, { plainText: ['text', 'txt', 'plain'] }],
];

function isExternalHref(href: string | undefined): boolean {
  if (!href) return false;
  return /^https?:\/\//i.test(href) || href.startsWith('mailto:') || href.startsWith('tel:');
}

/** Richer / safer defaults for agent and user chat bodies. */
export const chatMarkdownComponents: Partial<Components> = {
  a: ({ node: _node, href, children, ...rest }) => {
    if (isExternalHref(href)) {
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>
          {children}
        </a>
      );
    }
    return (
      <a href={href} {...rest}>
        {children}
      </a>
    );
  },
};
