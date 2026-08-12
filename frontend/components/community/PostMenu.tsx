'use client';

import { useEffect, useRef, useState } from 'react';
import { MoreHorizontal, Pencil, Trash2 } from 'lucide-react';

interface PostMenuProps {
  /** Omitted for a moderator: removing someone else's post is not editing it. */
  onEdit?: () => void;
  onDelete: () => void;
  isDeleting?: boolean;
  /**
   * Renders the destructive item as a moderator action on somebody else's
   * content. Labelling matters here — "Delete" on another person's post reads
   * like your own, and the two go to different endpoints.
   */
  isModerator?: boolean;
}

/**
 * The "⋯" menu on a post.
 *
 * Only rendered for the author or an admin — the caller decides that, because
 * only it knows who is signed in. Deletion asks first: a post can carry a
 * thread, and there is no undo.
 */
export default function PostMenu({
  onEdit,
  onDelete,
  isDeleting = false,
  isModerator = false,
}: PostMenuProps) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
        setConfirming(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setOpen(false);
      setConfirming(false);
      triggerRef.current?.focus();
    };

    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const itemClass =
    'flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg';

  return (
    <div ref={containerRef} className="relative shrink-0">
      <button
        ref={triggerRef}
        type="button"
        aria-label="Post options"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setOpen((value) => !value);
        }}
        className="rounded p-1 text-fg-subtle transition-colors hover:text-fg"
      >
        <MoreHorizontal className="h-3.5 w-3.5" />
      </button>

      {open && (
        <div
          role="menu"
          className="surface absolute right-0 top-7 z-20 w-44 overflow-hidden py-1 shadow-lg"
        >
          {onEdit && (
            <button
              type="button"
              role="menuitem"
              className={itemClass}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                setOpen(false);
                onEdit();
              }}
            >
              <Pencil className="h-3.5 w-3.5" />
              Edit
            </button>
          )}

          <button
            type="button"
            role="menuitem"
            disabled={isDeleting}
            className={`${itemClass} ${confirming ? 'text-down hover:text-down' : ''}`}
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              if (!confirming) {
                setConfirming(true);
                return;
              }
              setOpen(false);
              setConfirming(false);
              onDelete();
            }}
          >
            <Trash2 className="h-3.5 w-3.5" />
            {confirming ? 'Click again to confirm' : isModerator ? 'Remove (moderator)' : 'Delete'}
          </button>
        </div>
      )}
    </div>
  );
}
