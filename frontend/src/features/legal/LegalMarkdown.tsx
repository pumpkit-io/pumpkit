import { Children, type ReactNode } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import { Link } from 'react-router-dom';
import remarkGfm from 'remark-gfm';
import { TEXT_LINK_CLASS } from './textLink';

const ANCHOR_SUFFIX = /\s*\{#([a-z0-9-]+)\}\s*$/;

/**
 * Splits a heading written as `## Title {#anchor}` into its text and anchor. An explicit anchor
 * keeps links from the banner and the checkout working when the heading is reworded.
 */
function headingParts(children: ReactNode): { id?: string; content: ReactNode } {
  const parts = Children.toArray(children);
  const last = parts[parts.length - 1];
  if (typeof last === 'string') {
    const match = last.match(ANCHOR_SUFFIX);
    if (match) {
      return { id: match[1], content: [...parts.slice(0, -1), last.replace(ANCHOR_SUFFIX, '')] };
    }
  }
  return { content: children };
}

const components: Components = {
  h2: ({ children }) => {
    const { id, content } = headingParts(children);
    return (
      <h2 id={id} className="mt-12 scroll-mt-6 text-xl font-medium tracking-tight text-foreground">
        {content}
      </h2>
    );
  },
  h3: ({ children }) => {
    const { id, content } = headingParts(children);
    return (
      <h3 id={id} className="mt-8 scroll-mt-6 text-base font-medium text-foreground">
        {content}
      </h3>
    );
  },
  p: ({ children }) => <p className="mt-4 leading-7">{children}</p>,
  ul: ({ children }) => <ul className="mt-4 list-disc space-y-2 pl-5 leading-7">{children}</ul>,
  ol: ({ children }) => <ol className="mt-4 list-decimal space-y-2 pl-5 leading-7">{children}</ol>,
  strong: ({ children }) => <strong className="font-medium text-foreground">{children}</strong>,
  code: ({ children }) => (
    <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]">{children}</code>
  ),
  table: ({ children }) => (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full min-w-[32rem] border-collapse text-left text-sm">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border-b border-border py-2 pr-4 align-bottom font-medium text-foreground">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border-b border-border py-2 pr-4 align-top leading-6">{children}</td>
  ),
  a: ({ href = '', children }) => {
    if (href.startsWith('/')) {
      return (
        <Link to={href} className={TEXT_LINK_CLASS}>
          {children}
        </Link>
      );
    }
    const external = /^https?:/.test(href);
    return (
      <a
        href={href}
        className={TEXT_LINK_CLASS}
        {...(external && { target: '_blank', rel: 'noopener noreferrer' })}
      >
        {children}
      </a>
    );
  },
};

/** Renders a legal document's Markdown, with raw HTML in the source dropped rather than rendered. */
export function LegalMarkdown({ markdown }: { markdown: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components} skipHtml>
      {markdown}
    </ReactMarkdown>
  );
}
