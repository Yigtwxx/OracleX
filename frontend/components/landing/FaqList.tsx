'use client';

import { useCallback, useEffect, useState } from 'react';
import { FAQ_ENTRIES, type FaqGroup } from '@/lib/marketing/faq';
import { REPO_URL } from '@/lib/landing/links';
import AnsweredTally from './AnsweredTally';
import FaqItem from './FaqItem';
import Reveal from './Reveal';

interface FaqListProps {
  groups: readonly FaqGroup[];
}

const RAIL_LINKS: readonly { readonly href: string; readonly label: string }[] = [
  { href: REPO_URL, label: 'Source' },
  { href: `${REPO_URL}/tree/main/agent-skill`, label: 'Agent skills' },
  { href: `${REPO_URL}/tree/main/mcp-server`, label: 'MCP server' },
  { href: `${REPO_URL}/issues`, label: 'Issues' },
];

/**
 * The questions, and a rail that fills in as they are answered.
 *
 * The open set lives here rather than in each item so the tally has something to
 * count. A deep link opens its own question on mount — an anchor that scrolled
 * to a collapsed row would land on a heading with nothing under it, which reads
 * as the link being broken.
 */
export default function FaqList({ groups }: FaqListProps) {
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set());

  useEffect(() => {
    const id = window.location.hash.slice(1);
    if (id && FAQ_ENTRIES.some((entry) => entry.id === id)) {
      setOpen(new Set([id]));
    }
  }, []);

  const toggle = useCallback((id: string) => {
    setOpen((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }, []);

  const marks = FAQ_ENTRIES.map((entry) => open.has(entry.id));

  return (
    <div className="grid gap-x-10 gap-y-12 xl:grid-cols-[minmax(0,1fr)_300px]">
      <div>
        {groups.map((group) => (
          <section
            key={group.id}
            id={group.id}
            data-doc-section=""
            aria-labelledby={`${group.id}-heading`}
            className="scroll-mt-16 py-8"
          >
            <Reveal>
              <div className="mb-2 flex items-center gap-2.5">
                <span className="font-mono text-2xs uppercase tracking-[0.08em] text-fg-subtle">
                  {group.label}
                </span>
                <span className="flex-1 border-t border-dashed border-line" />
              </div>
              {/* The visible label is the eyebrow above; this names the section
                  for assistive technology without printing it twice. */}
              <h2 id={`${group.id}-heading`} className="sr-only">
                {group.label}
              </h2>

              <div>
                {group.entries.map((entry) => (
                  <FaqItem
                    key={entry.id}
                    id={entry.id}
                    question={entry.question}
                    answer={entry.answer}
                    open={open.has(entry.id)}
                    onToggle={toggle}
                  />
                ))}
              </div>
            </Reveal>
          </section>
        ))}
      </div>

      {/* Below `xl` this lands after the last group, where it reads as a closing
          note rather than as a rail that lost its column. */}
      <aside className="xl:sticky xl:top-[5.5rem] xl:self-start">
        <div className="landing-plate p-5">
          <div className="mb-4 flex items-center gap-2.5">
            <span className="font-mono text-2xs uppercase tracking-[0.08em] text-fg-subtle">
              Progress
            </span>
            <span className="flex-1 border-t border-dashed border-line" />
          </div>

          <AnsweredTally marks={marks} />

          <div className="my-4 border-t border-dashed border-line" />

          <ul className="space-y-1">
            {RAIL_LINKS.map((link) => (
              <li key={link.href}>
                <a
                  href={link.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="landing-riser inline-block rounded-md py-0.5 text-sm text-fg-muted transition-colors"
                >
                  {link.label}
                  <span aria-hidden="true" className="landing-riser-fill">
                    <span className="landing-riser-ink">{link.label}</span>
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      </aside>
    </div>
  );
}
