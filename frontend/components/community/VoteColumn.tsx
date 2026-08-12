'use client';

import { ArrowBigDown, ArrowBigUp } from 'lucide-react';

interface VoteColumnProps {
  score: number;
  /** 1, -1, or 0. */
  myVote: number;
  onVote: (value: 1 | -1) => void;
  /** Signed out — arrows still render, but explain themselves instead of acting. */
  disabled?: boolean;
  orientation?: 'vertical' | 'horizontal';
}

/**
 * The vote control.
 *
 * Colour follows the project rule in globals.css — it carries meaning, not
 * decoration — so the arrows are neutral until you have actually voted, and
 * then they take the same green/red the rest of the app uses for direction.
 * An unvoted post shows no colour at all.
 */
export default function VoteColumn({
  score,
  myVote,
  onVote,
  disabled = false,
  orientation = 'vertical',
}: VoteColumnProps) {
  const isUp = myVote === 1;
  const isDown = myVote === -1;

  const arrow = (direction: 1 | -1) => {
    const active = direction === 1 ? isUp : isDown;
    const Icon = direction === 1 ? ArrowBigUp : ArrowBigDown;
    const activeColor = direction === 1 ? 'text-up' : 'text-down';

    return (
      <button
        type="button"
        onClick={() => onVote(direction)}
        aria-pressed={active}
        aria-label={
          disabled
            ? `Sign in to ${direction === 1 ? 'upvote' : 'downvote'}`
            : `${direction === 1 ? 'Upvote' : 'Downvote'}, score ${score}`
        }
        title={disabled ? 'Sign in to vote' : undefined}
        className={`p-0.5 rounded transition-colors ${
          active ? activeColor : 'text-fg-subtle hover:text-fg'
        } ${disabled ? 'cursor-not-allowed opacity-60' : ''}`}
      >
        <Icon className="w-4 h-4" fill={active ? 'currentColor' : 'none'} />
      </button>
    );
  };

  const scoreColor = isUp ? 'text-up' : isDown ? 'text-down' : 'text-fg-muted';

  if (orientation === 'horizontal') {
    return (
      <div className="flex items-center gap-1">
        {arrow(1)}
        <span className={`text-sm font-mono tabnum min-w-[1.5rem] text-center ${scoreColor}`}>
          {score}
        </span>
        {arrow(-1)}
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-0.5 shrink-0 py-3 px-1.5 bg-surface-2 rounded-l-lg border-r border-line">
      {arrow(1)}
      <span className={`text-sm font-mono tabnum ${scoreColor}`}>{score}</span>
      {arrow(-1)}
    </div>
  );
}
