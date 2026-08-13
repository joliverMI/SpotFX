/** Toasts — bottom-center, 4s (the spot-effects idiom, SPECTRA palette). */
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react';

type ToastKind = 'info' | 'success' | 'error';
interface ToastItem { id: number; msg: string; kind: ToastKind; }

const ToastCtx = createContext<(msg: string, kind?: ToastKind) => void>(() => {});

export const useToast = () => useContext(ToastCtx);

const BG: Record<ToastKind, string> = { success: '#6d28d9', error: '#b91c1c', info: '#4c1d95' };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const show = useCallback((msg: string, kind: ToastKind = 'info') => {
    const id = nextId.current++;
    setToasts((t) => [...t, { id, msg, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000);
  }, []);

  return (
    <ToastCtx.Provider value={show}>
      {children}
      <div style={{ position: 'fixed', bottom: 16, left: '50%', transform: 'translateX(-50%)',
                    display: 'flex', flexDirection: 'column', gap: 6, zIndex: 9999, alignItems: 'center' }}>
        {toasts.map((t) => (
          <div key={t.id} style={{
            padding: '8px 16px', borderRadius: 6, fontSize: 13, color: '#fff',
            background: BG[t.kind], boxShadow: '0 2px 8px rgba(0,0,0,.5)',
            whiteSpace: 'nowrap', maxWidth: '90vw', overflow: 'hidden', textOverflow: 'ellipsis',
          }}>
            {t.msg}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
