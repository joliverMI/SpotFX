/** Keyboard intensity editing for the selected trigger circle(s):
 *  ↑/↓ = ±0.01 (shift = ±0.1) on every selected trigger
 *  ←/→ = select prev/next trigger (shift extends the selection)
 *  Enter = copy the PREVIOUS trigger's intensity, then advance to the next
 *  "." then 1-2 digits = set value (".9" → 0.90, ".09" → 0.09)
 *  Ctrl/Cmd+A = select all · Escape = deselect
 * Registered in the capture phase so consumed keys never reach the palette
 * hook (digits stay palette keys except during "." entry). */
import { useEffect, useRef } from 'react';
import { useBuilderStore } from '../store';

export function useIntensityKeyboard() {
  const entry = useRef<{ buf: string; timer: ReturnType<typeof setTimeout> | null } | null>(null);

  useEffect(() => {
    const clamp = (v: number) => Math.max(0, Math.min(1, Math.round(v * 100) / 100));

    const sortedTriggers = () =>
      [...useBuilderStore.getState().workingTriggers()].sort((a, b) => a.timestamp_ms - b.timestamp_ms);

    const applyToSelected = (fn: (cur: number) => number) => {
      const st = useBuilderStore.getState();
      const ids = new Set(st.selectedIds);
      st.mutateWorking((ts) => {
        for (const t of ts) if (ids.has(t.id)) t.intensity = clamp(fn(t.intensity ?? 0.5));
      });
    };

    const endEntry = () => {
      if (entry.current?.timer) clearTimeout(entry.current.timer);
      entry.current = null;
    };

    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) {
        return;
      }
      const st = useBuilderStore.getState();
      const consume = () => { e.preventDefault(); e.stopPropagation(); };

      // Ctrl/Cmd+A — select all triggers
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
        const all = sortedTriggers().map((t) => t.id);
        if (all.length) {
          st.setSelection(all, all[all.length - 1]);
          consume();
        }
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      // "." numeric entry
      if (entry.current) {
        if (/^[0-9]$/.test(e.key)) {
          entry.current.buf += e.key;
          const buf = entry.current.buf;
          const v = clamp(parseFloat(`0.${buf}`) || 0);
          applyToSelected(() => v);
          if (buf.length >= 2) endEntry();
          consume();
          return;
        }
        endEntry(); // any other key ends entry mode and falls through
      }
      if (e.key === '.' && st.selectedIds.length) {
        endEntry();
        entry.current = { buf: '', timer: setTimeout(endEntry, 1500) };
        consume();
        return;
      }

      if (e.key === 'Escape') {
        if (st.selectedIds.length) {
          st.setSelection([]);
          consume(); // palette disarm stays on a second Escape
        }
        return;
      }

      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        if (!st.selectedIds.length) return;
        const step = (e.shiftKey ? 0.1 : 0.01) * (e.key === 'ArrowUp' ? 1 : -1);
        applyToSelected((cur) => cur + step);
        consume();
        return;
      }

      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        const ts = sortedTriggers();
        if (!ts.length) return;
        const dir = e.key === 'ArrowRight' ? 1 : -1;
        const curIdx = st.lastSelectedId ? ts.findIndex((t) => t.id === st.lastSelectedId) : -1;
        let next: number;
        if (curIdx === -1) next = dir === 1 ? 0 : ts.length - 1;
        else next = Math.max(0, Math.min(ts.length - 1, curIdx + dir));
        const id = ts[next].id;
        if (e.shiftKey && st.selectedIds.length) {
          const set = new Set(st.selectedIds);
          set.add(id);
          st.setSelection([...set], id);
        } else {
          st.setSelection([id], id);
        }
        consume();
        return;
      }

      if (e.key === 'Enter') {
        const ts = sortedTriggers();
        const idx = st.lastSelectedId ? ts.findIndex((t) => t.id === st.lastSelectedId) : -1;
        if (idx < 0) return;
        if (idx > 0) {
          const prev = ts[idx - 1].intensity ?? 0.5;
          const id = ts[idx].id;
          st.mutateWorking((list) => {
            const t = list.find((tt) => tt.id === id);
            if (t) t.intensity = clamp(prev);
          });
        }
        const nextIdx = Math.min(ts.length - 1, idx + 1);
        st.setSelection([ts[nextIdx].id], ts[nextIdx].id);
        consume();
        return;
      }
    };

    window.addEventListener('keydown', onKey, { capture: true });
    return () => window.removeEventListener('keydown', onKey, { capture: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
