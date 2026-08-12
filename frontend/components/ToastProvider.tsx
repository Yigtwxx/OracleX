'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { setToastCallback } from '@/lib/queryClient';
import { AlertTriangle, X, CheckCircle } from 'lucide-react';

interface Toast {
  id: number;
  message: string;
  type: 'error' | 'success';
}

let idCounter = 0;

export default function ToastProvider() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const initialized = useRef(false);

  const addToast = useCallback((message: string, type: 'error' | 'success' = 'error') => {
    const id = ++idCounter;
    setToasts((prev) => {
      // Prevent duplicate messages
      if (prev.some((t) => t.message === message)) return prev;
      // Limit to 3 toasts
      const updated = [...prev, { id, message, type }];
      return updated.slice(-3);
    });

    // Auto-dismiss after 5 seconds
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 5000);
  }, []);

  const removeToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  useEffect(() => {
    if (!initialized.current) {
      setToastCallback((msg) => addToast(msg, 'error'));
      initialized.current = true;
    }
  }, [addToast]);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 max-w-sm">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role="status"
          className={`flex items-start gap-2.5 px-3 py-2.5 rounded-lg border bg-surface animate-slide-in-right ${
            toast.type === 'error' ? 'border-down' : 'border-up'
          }`}
        >
          {toast.type === 'error' ? (
            <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0 text-down" />
          ) : (
            <CheckCircle className="w-3.5 h-3.5 mt-0.5 shrink-0 text-up" />
          )}
          <p className="text-base text-fg flex-1">{toast.message}</p>
          <button
            onClick={() => removeToast(toast.id)}
            aria-label="Dismiss notification"
            className="shrink-0 p-0.5 text-fg-subtle hover:text-fg rounded transition-colors"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
      ))}
    </div>
  );
}
