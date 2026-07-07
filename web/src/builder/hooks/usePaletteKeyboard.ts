/** Full-keyboard palette arming: press a key to arm its event (right-click
 * the timeline to place), Escape disarms, backquote ` toggles follow/manual
 * zoom (the legacy `b` binding moved so b is palette-usable). While the
 * trigger dialog is open, a palette key assigns that key's event directly
 * (dispatched to the dialog via a window event). Inputs are ignored. */
import { useEffect } from 'react';
import { useBuilderStore } from '../store';
import type { Palette } from '../types';

export const PALETTE_ROWS = [
  '1234567890'.split(''),
  'qwertyuiop'.split(''),
  'asdfghjkl'.split(''),
  'zxcvbnm'.split(''),
];
export const PALETTE_KEYS = new Set(PALETTE_ROWS.flat());

export const PALETTE_ASSIGN_EVENT = 'spotfx:palette-assign';

export function usePaletteKeyboard(opts: {
  getPalettes: () => Palette[] | undefined;
  onToggleFollow: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) {
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const st = useBuilderStore.getState();

      if (e.key === 'Escape') {
        if (st.armedKey) {
          st.setArmedKey(null);
          e.preventDefault();
        }
        return;
      }
      if (e.key === '`') {
        opts.onToggleFollow();
        e.preventDefault();
        return;
      }
      const key = e.key.toLowerCase();
      if (!PALETTE_KEYS.has(key)) return;

      // Dialog open: a palette key with an assigned event applies it directly.
      if (st.editingTriggerId && st.activePaletteId) {
        const pal = opts.getPalettes()?.find((p) => p.id === st.activePaletteId);
        const eventId = pal?.keys[key];
        if (eventId) {
          window.dispatchEvent(new CustomEvent(PALETTE_ASSIGN_EVENT, { detail: eventId }));
          e.preventDefault();
        }
        return;
      }

      if (!st.activePaletteId) return;
      // Re-pressing the armed key keeps it armed (no toggle-off) — Escape or
      // clicking the key in the grid disarms.
      st.setArmedKey(key);
      e.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
