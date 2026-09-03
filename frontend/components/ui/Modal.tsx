'use client';

import { ReactNode, useEffect, useRef } from 'react';
import { X } from 'lucide-react';

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  /** Tailwind max-width class for the dialog. Ignored when `fullScreen`. */
  maxWidth?: string;
  /**
   * Scrim classes. The default is an opaque wash, which is right for a dialog
   * that replaces what is behind it — a form, a confirmation. Pass a lighter,
   * blurred scrim (`scrim-blur`) when the dialog is an expansion of something on
   * the page and the reader should still feel where it came from.
   */
  scrimClassName?: string;
  /**
   * Fill the viewport on small screens and take a large fixed frame on larger
   * ones. For a dialog that is a workspace rather than a form.
   */
  fullScreen?: boolean;
  /** Render the header row without the default bottom border. */
  headerBorder?: boolean;
}

/** Everything that can hold focus, minus the things that cannot be tabbed to. */
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Shared dialog shell. Owns the scrim, Escape-to-close, background scroll lock
 * and focus containment so individual modals only describe their content.
 */
export default function Modal({
  isOpen,
  onClose,
  title,
  children,
  maxWidth = 'max-w-lg',
  scrimClassName = 'bg-black/70',
  fullScreen = false,
  headerBorder = true,
}: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);

  // `onClose` is an inline arrow at nearly every call site, so it is a new
  // function on every parent render. Held in a ref, it stays out of the effect's
  // dependencies: otherwise a background refetch anywhere above the dialog tore
  // the whole effect down and set it back up, which stole focus back to the
  // frame mid-sentence and left `opener` pointing at the dialog instead of at
  // the control that opened it.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!isOpen) return;

    // Remember who opened the dialog so focus can go back there on close —
    // otherwise a keyboard user lands at the top of the document.
    const opener = document.activeElement as HTMLElement | null;

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onCloseRef.current();
        return;
      }
      if (e.key !== 'Tab' || !dialogRef.current) return;

      // Containment, not just an initial focus: a full-screen dialog covers the
      // page, so tabbing out of it moves focus to controls the user cannot see.
      const items = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.offsetParent !== null
      );
      if (items.length === 0) return;

      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;

      if (e.shiftKey && (active === first || !dialogRef.current.contains(active))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    // Focus the dialog itself rather than its first control: an autofocused
    // input would scroll a long dialog to wherever that input happens to be.
    // Unless the dialog's own content already claimed focus — a picker that
    // marks its search field `autoFocus` means it, and taking that focus away a
    // tick later leaves the reader typing into nothing.
    if (!dialogRef.current?.contains(document.activeElement)) {
      dialogRef.current?.focus();
    }

    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
      opener?.focus?.();
    };
  }, [isOpen]);

  if (!isOpen) return null;

  // `surface-flat` on the full-screen frame is not optional: the lit rim is
  // anchored to the viewport with `background-attachment: fixed`, and on an
  // element this large Safari re-resolves it on every scroll frame.
  const frame = fullScreen
    ? `surface surface-flat w-full max-w-none h-full sm:max-w-5xl sm:h-[min(85vh,780px)]`
    : `surface w-full ${maxWidth} max-h-[85vh]`;

  return (
    <div
      className={`fixed inset-0 z-[100] flex items-center justify-center ${
        fullScreen ? 'p-0 sm:p-6' : 'p-4'
      } ${scrimClassName}`}
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className={`${frame} flex flex-col overflow-hidden focus:outline-none`}
      >
        <div
          className={`shrink-0 flex justify-between items-center px-4 h-11 ${
            headerBorder ? 'border-b border-line' : ''
          }`}
        >
          <h3 className={`font-semibold text-fg ${fullScreen ? 'text-lg' : 'text-md'}`}>{title}</h3>
          <button
            onClick={onClose}
            aria-label="Close dialog"
            className="p-1 text-fg-muted hover:text-fg rounded transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div
          className={`flex-1 min-h-0 ${
            fullScreen ? 'overflow-hidden' : 'overflow-y-auto overflow-x-hidden custom-scrollbar'
          }`}
        >
          {children}
        </div>
      </div>
    </div>
  );
}
