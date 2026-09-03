'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { setAlarmToastCallback, setToastCallback } from '@/lib/queryClient';
import { AlertTriangle, Bell, X, CheckCircle } from 'lucide-react';

type ToastType = 'error' | 'success' | 'alarm';

interface Toast {
  id: number;
  message: string;
  type: ToastType;
}

const TONE: Record<ToastType, { border: string; icon: typeof AlertTriangle; color: string }> = {
  error: { border: 'border-down', icon: AlertTriangle, color: 'text-down' },
  success: { border: 'border-up', icon: CheckCircle, color: 'text-up' },
  alarm: { border: 'border-warn', icon: Bell, color: 'text-warn' },
};

let idCounter = 0;

export default function ToastProvider() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const initialized = useRef(false);

  const addToast = useCallback((message: string, type: ToastType = 'error') => {
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
      setAlarmToastCallback((msg) => addToast(msg, 'alarm'));
      initialized.current = true;
    }
  }, [addToast]);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 max-w-sm">
      {toasts.map((toast) => {
        const tone = TONE[toast.type];
        const Icon = tone.icon;
        return (
          <div
            key={toast.id}
            role="status"
            className={`flex items-start gap-2.5 px-3 py-2.5 rounded-lg border bg-surface animate-slide-in-right ${tone.border}`}
          >
            <Icon className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${tone.color}`} />
            <p className="text-base text-fg flex-1">{toast.message}</p>
            <button
              onClick={() => removeToast(toast.id)}
              aria-label="Dismiss notification"
              className="shrink-0 p-0.5 text-fg-subtle hover:text-fg rounded transition-colors"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
