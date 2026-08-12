'use client';

import Markdown from '@/components/ui/Markdown';

/**
 * Markdown renderer for generated reports.
 *
 * The element map moved to `components/ui/Markdown.tsx` when the community
 * board needed the same styling with a narrower, user-content-safe variant.
 * This wrapper stays so report code keeps reading as report code.
 */
export default function ReportMarkdown({ content }: { content: string }) {
  return <Markdown content={content} variant="report" />;
}
