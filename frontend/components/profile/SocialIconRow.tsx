'use client';

import { useState } from 'react';
import { Check, Copy } from 'lucide-react';

import { SocialGlyph } from '@/components/profile/social-icons';
import { PLATFORM_BY_ID } from '@/lib/social-links';
import type { SocialLink } from '@/lib/api';

/**
 * A row of a person's links, read-only.
 *
 * Shared by the editor's preview and the public page so the two can never
 * disagree about how a link renders.
 *
 * Two things are deliberate. Every anchor carries `rel="noopener noreferrer
 * nofollow"` — these destinations are typed by users, so neither this tab's
 * `window` nor this site's link equity should follow them. And nothing here
 * shows a check mark: the handles are self-declared, and a badge would claim a
 * verification that never happened.
 */
export default function SocialIconRow({ links }: { links: SocialLink[] }) {
  const [copied, setCopied] = useState('');

  if (links.length === 0) return null;

  const copy = async (value: string) => {
    await navigator.clipboard.writeText(value);
    setCopied(value);
    window.setTimeout(() => setCopied(''), 1500);
  };

  return (
    <ul className="flex flex-wrap items-center gap-2">
      {links.map((link) => {
        const spec = PLATFORM_BY_ID[link.platform];
        const name = link.label || spec?.label || link.platform;
        const shown = link.handle ? `@${link.handle}` : name;

        // Discord has no addressable profile URL, so its row copies the
        // username instead of pretending to navigate somewhere.
        if (!link.url) {
          const value = link.handle ?? '';
          return (
            <li key={`${link.platform}-${link.position}`}>
              <button
                type="button"
                onClick={() => copy(value)}
                title={`Copy ${name} username`}
                className="flex items-center gap-1.5 rounded-md border border-line bg-surface-2 px-2.5 py-1 text-base text-fg-muted transition-colors hover:text-fg"
              >
                <SocialGlyph platform={link.platform} />
                <span className="max-w-[12rem] truncate">{shown}</span>
                {copied === value ? (
                  <Check className="h-3.5 w-3.5 text-up" />
                ) : (
                  <Copy className="h-3.5 w-3.5 opacity-60" />
                )}
              </button>
            </li>
          );
        }

        return (
          <li key={`${link.platform}-${link.position}`}>
            <a
              href={link.url}
              target="_blank"
              rel="noopener noreferrer nofollow"
              title={`${name} — opens in a new tab`}
              className="flex items-center gap-1.5 rounded-md border border-line bg-surface-2 px-2.5 py-1 text-base text-fg-muted transition-colors hover:border-fg-subtle hover:text-fg"
            >
              <SocialGlyph platform={link.platform} />
              <span className="max-w-[12rem] truncate">{shown}</span>
            </a>
          </li>
        );
      })}
    </ul>
  );
}
