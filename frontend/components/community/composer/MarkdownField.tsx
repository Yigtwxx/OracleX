'use client';

import { useId, useState } from 'react';
import { Eye, PenLine } from 'lucide-react';

import Markdown from '@/components/ui/Markdown';

interface MarkdownFieldProps {
  value: string;
  onChange: (value: string) => void;
  label: string;
  placeholder?: string;
  rows?: number;
  maxLength: number;
  required?: boolean;
}

/**
 * A textarea that can show what its markdown will look like.
 *
 * The preview renders through the same `community` variant the feed uses, so
 * what you see here is what the board will show — including the restrictions
 * (no embedded remote images, links marked nofollow).
 */
export default function MarkdownField({
  value,
  onChange,
  label,
  placeholder,
  rows = 6,
  maxLength,
  required = false,
}: MarkdownFieldProps) {
  const [previewing, setPreviewing] = useState(false);
  const fieldId = useId();

  const remaining = maxLength - value.length;
  // Silent until it matters, then increasingly insistent.
  const counterTone =
    remaining < 0 ? 'text-down' : remaining < maxLength * 0.1 ? 'text-warn' : 'text-fg-subtle';

  const toggleClass = (active: boolean) =>
    `flex items-center gap-1.5 rounded px-2 py-0.5 text-xs transition-colors ${
      active ? 'bg-surface-2 text-fg' : 'text-fg-subtle hover:text-fg'
    }`;

  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <label htmlFor={fieldId} className="label">
          {label}
        </label>

        <div className="flex items-center gap-0.5">
          <button
            type="button"
            onClick={() => setPreviewing(false)}
            aria-pressed={!previewing}
            className={toggleClass(!previewing)}
          >
            <PenLine className="h-3 w-3" />
            Write
          </button>
          <button
            type="button"
            onClick={() => setPreviewing(true)}
            aria-pressed={previewing}
            className={toggleClass(previewing)}
          >
            <Eye className="h-3 w-3" />
            Preview
          </button>
        </div>
      </div>

      {previewing ? (
        <div
          className="min-h-[8rem] rounded-md border border-line bg-surface-2 p-3"
          style={{ minHeight: `${rows * 1.5}rem` }}
        >
          {value.trim() ? (
            <Markdown content={value} variant="community" />
          ) : (
            <p className="text-sm italic text-fg-subtle">Nothing to preview yet.</p>
          )}
        </div>
      ) : (
        <textarea
          id={fieldId}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          rows={rows}
          required={required}
          className="w-full resize-y rounded-md border border-line bg-surface-2 px-2.5 py-2 text-base text-fg placeholder:text-fg-subtle focus:border-accent focus:outline-none"
        />
      )}

      <div className="mt-1 flex items-center justify-between">
        <span className="text-2xs text-fg-subtle">
          Markdown supported — **bold**, lists, `code`, [links](https://example.com)
        </span>
        <span className={`font-mono text-2xs tabnum ${counterTone}`}>{remaining}</span>
      </div>
    </div>
  );
}
