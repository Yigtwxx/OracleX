'use client';

import { aiNoteText, isGenerating, type AiNote as AiNoteEnvelope } from '@/lib/ai-note';

interface AiNoteProps {
  aiNote: AiNoteEnvelope | undefined;
  className?: string;
}

/**
 * The one place a model-written sentence is rendered.
 *
 * Three states, and only two of them draw anything. A note that arrived is
 * prose; a note being written is a single shimmering line the height of that
 * prose, so the panel does not resize under the reader when it lands. A note
 * that will not arrive draws nothing at all.
 *
 * That last case is the important one. Every surface using this computes its
 * own figures in Python and renders them beside this component, so an absent
 * note costs a paragraph and nothing else. Showing "AI unavailable" here would
 * turn a complete panel into one that looks broken, and would report an outage
 * the reader can do nothing about on a page that is still entirely correct.
 */
export default function AiNote({ aiNote, className = '' }: AiNoteProps) {
  const text = aiNoteText(aiNote);

  if (text) {
    return <p className={`text-xs leading-relaxed text-fg-muted ${className}`}>{text}</p>;
  }

  if (isGenerating(aiNote)) {
    return <div className={`shimmer h-3.5 w-2/3 rounded ${className}`} aria-hidden />;
  }

  return null;
}
