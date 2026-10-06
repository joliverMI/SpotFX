/** A press-and-HOLD confirm gesture, with visible progress, for a control
 * whose short tap must do nothing — the Release-to-Home-Assistant button
 * (his ask 2026-10-06: "make the release to home assistant button require
 * a long press"), which hands the room away from SPECTRA and is rare and
 * consequential by design.
 *
 * Unlike `useLongPress.ts` (fire-after-N-ms, no visible feedback, pointer
 * events only — built for "hold to open a panel"), this reports live
 * `progress` (0..1) every frame so a caller can draw a filling ring/bar,
 * and binds BOTH pointer events (covers mouse, touch and pen — one event
 * model) AND keyboard (`Enter`/`Space`, held down — `onKeyDown` with
 * `!e.repeat` starts the clock once; the browser's own key-repeat must
 * not restart it on every repeated keydown). A release before `durationMs`
 * elapses cancels and resets to 0 — it NEVER fires partway — and sets
 * `justReleasedEarly` briefly (`HINT_MS`) so the caller can show a "hold
 * to release" hint; a release that reaches 1.0 fires `onConfirm` exactly
 * once and resets.
 *
 * Does not call `preventDefault()` on pointerdown — unlike a hold-to-open
 * gesture there is no click to protect (no onClick on this button at
 * all), and withholding it keeps normal focus/tab behaviour intact for
 * keyboard users. */
import { useCallback, useRef, useState } from 'react';

const HINT_MS = 1600;

export interface HoldToConfirmState {
  /** 0..1 while held, reset to 0 on release/cancel/fire. */
  progress: number;
  pressing: boolean;
  /** Briefly true after a release that did NOT reach 1.0 — the "hold to
   * release" hint window. */
  justReleasedEarly: boolean;
}

export function useHoldToConfirm(durationMs: number, onConfirm: () => void) {
  const [state, setState] = useState<HoldToConfirmState>({
    progress: 0, pressing: false, justReleasedEarly: false,
  });
  const rafRef = useRef<number | null>(null);
  const startedAtRef = useRef<number | null>(null);
  const firedRef = useRef(false);
  const hintTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stopRaf = () => {
    if (rafRef.current !== null) { cancelAnimationFrame(rafRef.current); rafRef.current = null; }
  };

  const tick = useCallback(() => {
    if (startedAtRef.current === null) return;
    const elapsed = performance.now() - startedAtRef.current;
    const progress = Math.min(1, elapsed / durationMs);
    if (progress >= 1) {
      stopRaf();
      startedAtRef.current = null;
      if (!firedRef.current) {
        firedRef.current = true;
        setState({ progress: 0, pressing: false, justReleasedEarly: false });
        onConfirm();
      }
      return;
    }
    setState((s) => ({ ...s, progress, pressing: true }));
    rafRef.current = requestAnimationFrame(tick);
  }, [durationMs, onConfirm]);

  const start = useCallback(() => {
    if (startedAtRef.current !== null) return;
    firedRef.current = false;
    startedAtRef.current = performance.now();
    if (hintTimerRef.current) { clearTimeout(hintTimerRef.current); hintTimerRef.current = null; }
    setState({ progress: 0, pressing: true, justReleasedEarly: false });
    rafRef.current = requestAnimationFrame(tick);
  }, [tick]);

  const cancel = useCallback(() => {
    if (startedAtRef.current === null) return;
    stopRaf();
    startedAtRef.current = null;
    setState({ progress: 0, pressing: false, justReleasedEarly: true });
    hintTimerRef.current = setTimeout(() => {
      setState((s) => ({ ...s, justReleasedEarly: false }));
    }, HINT_MS);
  }, []);

  const bind = {
    onPointerDown: (e: React.PointerEvent) => {
      if (e.button !== 0 && e.pointerType === 'mouse') return;
      start();
    },
    onPointerUp: cancel,
    onPointerLeave: cancel,
    onPointerCancel: cancel,
    onKeyDown: (e: React.KeyboardEvent) => {
      if ((e.key === 'Enter' || e.key === ' ') && !e.repeat) {
        e.preventDefault();
        start();
      }
    },
    onKeyUp: (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        cancel();
      }
    },
    onBlur: cancel,
    onContextMenu: (e: React.MouseEvent) => e.preventDefault(),
  };

  return { ...state, bind };
}
