/** Long-press gesture factory. `bind(key, onLong)` returns pointer handlers;
 * onLong fires after `ms` if the pointer stays down and within 8px. The
 * click that follows a fired long-press is swallowed (onClickCapture), so
 * a button can keep its normal onClick for short presses. */
import { useRef } from 'react';

export function useLongPress(ms = 500) {
  const st = useRef<{ timer: ReturnType<typeof setTimeout>; x: number; y: number } | null>(null);
  const fired = useRef(false);
  const cancel = () => {
    if (st.current) clearTimeout(st.current.timer);
    st.current = null;
  };
  return (onLong: () => void) => ({
    onPointerDown: (e: React.PointerEvent) => {
      if (e.button !== 0) return;
      fired.current = false;
      cancel();
      st.current = {
        x: e.clientX,
        y: e.clientY,
        timer: setTimeout(() => {
          st.current = null;
          fired.current = true;
          onLong();
        }, ms),
      };
    },
    onPointerMove: (e: React.PointerEvent) => {
      if (st.current && Math.hypot(e.clientX - st.current.x, e.clientY - st.current.y) > 8) cancel();
    },
    onPointerUp: cancel,
    onPointerLeave: cancel,
    onClickCapture: (e: React.MouseEvent) => {
      if (fired.current) {
        e.preventDefault();
        e.stopPropagation();
        fired.current = false;
      }
    },
  });
}
