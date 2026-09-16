import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { IconAlert, IconCheck, IconClose } from './icons';

type ToastTone = 'info' | 'success' | 'error';

interface ToastItem {
  id: number;
  tone: ToastTone;
  message: string;
}

const ToastContext = createContext<{ push: (message: string, tone?: ToastTone) => void } | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const push = useCallback((message: string, tone: ToastTone = 'info') => {
    const id = Date.now() + Math.random();
    setItems((prev) => [...prev, { id, tone, message }]);
    window.setTimeout(() => {
      setItems((prev) => prev.filter((item) => item.id !== id));
    }, tone === 'error' ? 6000 : 3600);
  }, []);

  const value = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {items.map((item) => (
          <div key={item.id} className={`toast${item.tone === 'info' ? '' : ` toast--${item.tone}`}`}>
            {item.tone === 'success' ? <IconCheck width={16} height={16} /> : null}
            {item.tone === 'error' ? <IconAlert width={16} height={16} /> : null}
            <span>{item.message}</span>
            <button
              type="button"
              className="toast__close"
              aria-label="关闭提示"
              onClick={() => setItems((prev) => prev.filter((entry) => entry.id !== item.id))}
            >
              <IconClose width={14} height={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast 必须在 ToastProvider 内使用');
  return context;
}
