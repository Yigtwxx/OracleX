'use client';

import { ReactNode, useEffect } from 'react';
import { X } from 'lucide-react';

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  /** Tailwind max-width class for the dialog. */
  maxWidth?: string;
}

/**
 * Shared dialog shell. Owns the scrim, Escape-to-close and background scroll
 * lock so individual modals only describe their content.
 */
export default function Modal({
  isOpen,
  onClose,
  title,
  children,
  maxWidth = 'max-w-lg',
}: ModalProps) {
  useEffect(() => {
    if (!isOpen) return;

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKeyDown);

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
        className={`surface w-full ${maxWidth} max-h-[85vh] flex flex-col overflow-hidden`}
      >
        <div className="shrink-0 flex justify-between items-center px-4 h-11 border-b border-line">
          <h3 className="text-md font-semibold text-fg">{title}</h3>
          <button
            onClick={onClose}
            aria-label="Close dialog"
            className="p-1 text-fg-muted hover:text-fg rounded transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">{children}</div>
      </div>
    </div>
  );
}
