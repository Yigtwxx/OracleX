'use client';

import { isValidElement, type ReactNode } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

/**
 * Shared markdown renderer.
 *
 * Every element is mapped onto the design tokens by hand rather than through a
 * typography plugin: the app runs a dense terminal-style type scale and a
 * general-purpose prose stylesheet would fight it at every size.
 *
 * Three variants:
 *
 *   report     everything, including tables — reports are mostly tables
 *   chat       the same, at a bubble's scale rather than a document's
 *   community  user-generated content, deliberately narrower (see below)
 *
 * ── Why the community variant is restricted ──────────────────────────────────
 * This is the only place in the app that renders text a stranger wrote.
 *
 * `react-markdown` does not render raw HTML unless `rehype-raw` is installed,
 * and it is not — so `<script>` in a post is inert text, and that is a property
 * worth not losing: do not add `rehype-raw` to make some embed work.
 *
 * On top of that default the community variant:
 *   * drops `img`, so a post cannot embed a remote image. Images belong in the
 *     upload field. An arbitrary `![](https://tracker/x.png)` would report every
 *     viewer's IP and user-agent to a host the poster picked.
 *   * marks links `nofollow` alongside `noopener noreferrer`, so the board is
 *     not a place to farm links.
 *   * drops headings to `h4`-sized text, because a post that renders its first
 *     line at page-title size dominates the feed.
 *
 * `urlTransform` is left at react-markdown's default, which already strips
 * `javascript:` and other dangerous protocols from hrefs.
 */

const base: Components = {
  h1: ({ children }) => (
    <h1 className="text-lg font-semibold text-fg mt-6 mb-2 first:mt-0">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-md font-semibold text-fg mt-6 mb-2 pb-1.5 border-b border-line first:mt-0">
      {children}
    </h2>
  ),
  h3: ({ children }) => <h3 className="text-base font-semibold text-fg mt-4 mb-1.5">{children}</h3>,
  p: ({ children }) => <p className="text-base text-fg-muted mb-3 leading-relaxed">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-fg">{children}</strong>,
  em: ({ children }) => <em className="italic text-fg-muted">{children}</em>,
  ul: ({ children }) => (
    <ul className="list-disc pl-4 mb-3 space-y-1 text-base text-fg-muted marker:text-fg-subtle">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="list-decimal pl-4 mb-3 space-y-1 text-base text-fg-muted marker:text-fg-subtle">
      {children}
    </ol>
  ),
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-line-strong pl-3 my-3 text-base text-fg-subtle italic">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-5 border-line" />,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-accent hover:underline"
    >
      {children}
    </a>
  ),
  code: ({ children }) => (
    <code className="font-mono text-sm bg-surface-2 border border-line rounded px-1 py-0.5 text-fg">
      {children}
    </code>
  ),
  pre: ({ children }) => (
    <pre className="font-mono text-sm bg-surface-2 border border-line rounded-md p-3 mb-3 overflow-x-auto custom-scrollbar">
      {children}
    </pre>
  ),
  // Tables carry most of a report's substance, so they get a horizontal scroll
  // container of their own rather than forcing the page to scroll.
  table: ({ children }) => (
    <div className="mb-4 overflow-x-auto custom-scrollbar border border-line rounded-md">
      <table className="w-full border-collapse text-base">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-surface-2">{children}</thead>,
  tr: ({ children }) => <tr className="border-b border-line last:border-b-0">{children}</tr>,
  th: ({ children }) => (
    <th className="label text-left px-2.5 py-2 whitespace-nowrap">{children}</th>
  ),
  td: ({ children }) => <td className="px-2.5 py-2 text-fg-muted tabnum align-top">{children}</td>,
};

/**
 * ── Tinted table cells (report variant only) ─────────────────────────────────
 * A report's substance is its tables, and a reader scanning one for "where is
 * support" should not have to read every row to find it. The rule from
 * globals.css still holds — colour carries direction, nothing else — so the
 * only cells tinted are the ones whose entire text *is* a directional label:
 * the Side column of the zone table, the Type column of the watchlist, the
 * Scenario column, the Trend column.
 *
 * The match is deliberately narrow. A cell only qualifies if it is short and
 * the label stands alone as a word, so the "Why it matters" prose that happens
 * to mention support stays muted, and a figure is never tinted — direction on
 * a distance number would read as good/bad, which it is not. Anything that
 * does not match keeps the default `text-fg-muted`.
 *
 * The community variant deliberately does not inherit this: a table a stranger
 * wrote should not be able to paint itself.
 */
const LABEL_MAX_LENGTH = 28;

const CELL_TONES: ReadonlyArray<readonly [RegExp, string]> = [
  [/\b(support|bullish|bull)\b/i, 'text-up'],
  [/\b(resistance|bearish|bear)\b/i, 'text-down'],
  [/\b(inside|neutral)\b/i, 'text-warn'],
];

/**
 * Flattens a cell back to plain text. Cells are usually a bare string, but a
 * `**Support**` arrives as an element, and that should still match.
 */
function cellText(node: ReactNode): string {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(cellText).join('');
  if (isValidElement(node)) return cellText((node.props as { children?: ReactNode }).children);
  return '';
}

function cellTone(children: ReactNode): string | null {
  const text = cellText(children).trim();
  if (!text || text.length > LABEL_MAX_LENGTH) return null;
  return CELL_TONES.find(([pattern]) => pattern.test(text))?.[1] ?? null;
}

const report: Components = {
  ...base,
  td: ({ children }) => (
    <td className={`px-2.5 py-2 tabnum align-top ${cellTone(children) ?? 'text-fg-muted'}`}>
      {children}
    </td>
  ),
};

/**
 * ── The chat variant ─────────────────────────────────────────────────────────
 * A chat bubble is not a report. `report`'s vertical rhythm is built for a
 * full-width document and blows a bubble out; the answer's own text also runs
 * to a few hundred words rather than a few thousand, so the headings step down
 * one level and the margins tighten.
 *
 * What it keeps from `report` is the part that matters: `remarkGfm` and the
 * tinted table cells. The chat page used to render its own inline
 * `ReactMarkdown` with no GFM at all, which meant the tables the system prompt
 * explicitly asks the model for arrived as rows of raw pipe characters.
 */
const chat: Components = {
  ...report,
  h1: ({ children }) => (
    <h2 className="text-md font-semibold text-fg mt-4 mb-1.5 first:mt-0">{children}</h2>
  ),
  h2: ({ children }) => (
    <h3 className="text-base font-semibold text-fg mt-3 mb-1.5 first:mt-0">{children}</h3>
  ),
  h3: ({ children }) => (
    <h4 className="text-base font-semibold text-fg mt-3 mb-1 first:mt-0">{children}</h4>
  ),
  p: ({ children }) => (
    <p className="text-base text-fg mb-2.5 last:mb-0 leading-relaxed">{children}</p>
  ),
  ul: ({ children }) => (
    <ul className="list-disc pl-4 mb-2.5 space-y-1 text-base text-fg marker:text-fg-subtle">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="list-decimal pl-4 mb-2.5 space-y-1 text-base text-fg marker:text-fg-subtle">
      {children}
    </ol>
  ),
};

const community: Components = {
  ...base,
  h1: ({ children }) => (
    <h4 className="text-base font-semibold text-fg mt-3 mb-1.5 first:mt-0">{children}</h4>
  ),
  h2: ({ children }) => (
    <h4 className="text-base font-semibold text-fg mt-3 mb-1.5 first:mt-0">{children}</h4>
  ),
  h3: ({ children }) => (
    <h4 className="text-base font-semibold text-fg mt-3 mb-1.5 first:mt-0">{children}</h4>
  ),
  p: ({ children }) => (
    <p className="text-base text-fg-muted mb-2 last:mb-0 leading-relaxed">{children}</p>
  ),
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className="text-accent hover:underline break-words"
    >
      {children}
    </a>
  ),
  // Rendered as the alt text it came with, rather than dropped silently, so the
  // reader can tell something was left out.
  img: ({ alt }) => (
    <span className="text-sm text-fg-subtle italic">{alt ? `[image: ${alt}]` : '[image]'}</span>
  ),
};

const VARIANTS = { report, community, chat } as const;

export interface MarkdownProps {
  content: string;
  variant?: keyof typeof VARIANTS;
  className?: string;
}

export default function Markdown({ content, variant = 'report', className }: MarkdownProps) {
  return (
    <div className={className ?? 'max-w-none'}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={VARIANTS[variant]}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
