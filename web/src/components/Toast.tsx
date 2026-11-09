/**
 * SASAA – Toast Notification System
 * Simple context-based toast notifications.
 */

import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';

type ToastType = 'success' | 'error' | 'info';

interface Toast {
  id: number;
  type: ToastType;
  message: string;
}

interface ToastContextValue {
  toast: (message: string, type?: ToastType) => void;
}

let idCounter = 0;
const ToastContext = createContext<ToastContextValue>({ toast: () => {} });

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const toast = useCallback((message: string, type: ToastType = 'info') => {
    const id = ++idCounter;
    setToasts((prev) => [...prev, { id, type, message }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4000);
  }, []);

  const dismiss = (id: number) => setToasts((prev) => prev.filter((t) => t.id !== id));

  const icons: Record<ToastType, ReactNode> = {
    success: <span style={{ fontSize: 14, color: '#22c55e' }}>✓</span>,
    error:   <span style={{ fontSize: 14, color: '#ef4444' }}>✕</span>,
    info:    <span style={{ fontSize: 14, color: '#9253f4' }}>ℹ</span>,
  };

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="toast-container">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.type}`}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
              {icons[t.type]}
              <span style={{ flex: 1, fontSize: 13 }}>{t.message}</span>
              <button
                onClick={() => dismiss(t.id)}
                style={{ background: 'none', border: 0, color: '#a49bb7', padding: 0, cursor: 'pointer', marginLeft: 4 }}
              >
                ✕
              </button>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
