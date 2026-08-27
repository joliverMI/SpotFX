/** The shared playhead + CUE-firing loop for SPECTRA's previews
 * (2026-08-27, fm/flare-preview-offsets-everywhere).
 *
 * THE RULE IT ENFORCES: the server computes every moment; this loop only
 * schedules against `cues[].at_s` from the timeline response. It derives
 * no time of its own — no lead, no anchor, no offset arithmetic — because
 * the founding defect of this system was a preview whose drawing and whose
 * firing disagreed about the same moment (data/preview-loops-and-fires-on-
 * the-trigger). The flare preview's own single-cue loop, whose scheduling
 * shape this generalizes, is spec-covered offline by
 * scripts/check_flare_preview_frontend_loop.mjs; the multi-cue shape here
 * is covered the same way by
 * scripts/check_preview_cue_loop.mjs — the formulas are extracted VERBATIM
 * from this file so the proof cannot drift from the code.
 *
 * Every lap fires every cue, in ruler order, once. A cue whose at_s the
 * playhead has already passed when the loop (re)starts waits for the NEXT
 * lap rather than firing immediately — a preview that fires the instant it
 * opens, before its own mark, is precisely what his correction of
 * 2026-08-21 rejected. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { heartbeatFlarePreview } from '../../queries';

const HEARTBEAT_MS = 5000;

export interface CueTimeline {
  duration_s: number;
  cues: { step: string; at_s: number; label: string }[];
}

/** Keeps the shared server-side hold alive while an overlay is open, and
 * reports the absolute-ceiling expiry the server can announce at any
 * time (spectra/services/flare_preview_hold.py MAX_HOLD_DURATION_S). */
export function useHeartbeat() {
  const [holdExpired, setHoldExpired] = useState(false);
  const expiredRef = useRef(false);

  useEffect(() => {
    const iv = setInterval(() => {
      void heartbeatFlarePreview().then((res) => {
        if (res.expired) {
          expiredRef.current = true;
          setHoldExpired(true);
        }
      });
    }, HEARTBEAT_MS);
    return () => clearInterval(iv);
  }, []);

  const onHoldExpired = useCallback(() => {
    expiredRef.current = true;
    setHoldExpired(true);
  }, []);
  const clearExpired = useCallback(() => {
    expiredRef.current = false;
    setHoldExpired(false);
  }, []);
  return { holdExpired, expiredRef, onHoldExpired, clearExpired };
}

export function useCueLoop({ timeline, fire }: {
  timeline: CueTimeline | null;
  fire: (step: string) => void | Promise<unknown>;
}) {
  const [playheadS, setPlayheadS] = useState(0);
  const [playing, setPlaying] = useState(true);
  const playheadRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const lastFrameRef = useRef<number | null>(null);
  // Absolute (performance.now()) deadline for each cue's NEXT firing,
  // derived fresh from the CURRENT playhead every time the loop
  // (re)starts, so it can never drift out of phase with what is drawn.
  const nextFireRef = useRef<Record<string, number>>({});

  const durationS = timeline?.duration_s ?? 0;
  const cuesKey = timeline ? JSON.stringify(timeline.cues) : '';

  // A fresh timeline resets the playhead so the first fire waits for its
  // own mark, exactly like a fresh open — never an immediate catch-up
  // fire at whatever position the slider happened to leave behind.
  useEffect(() => {
    setPlayheadS(0);
    playheadRef.current = 0;
    nextFireRef.current = {};
  }, [cuesKey]);

  useEffect(() => {
    if (!playing || !timeline || durationS <= 0) {
      lastFrameRef.current = null;
      return undefined;
    }
    const schedule: Record<string, number> = {};
    const now0 = performance.now();
    for (const cue of timeline.cues) {
      const atS = ((cue.at_s % durationS) + durationS) % durationS;
      const delayS = atS >= playheadRef.current
        ? atS - playheadRef.current
        : durationS - playheadRef.current + atS;
      schedule[cue.step] = now0 + delayS * 1000;
    }
    nextFireRef.current = schedule;

    const step = (now: number) => {
      if (lastFrameRef.current != null) {
        const dt = (now - lastFrameRef.current) / 1000;
        setPlayheadS((prev) => {
          const next = prev + dt;
          const wrapped = next >= durationS ? next % durationS : next;
          playheadRef.current = wrapped;
          return wrapped;
        });
      }
      lastFrameRef.current = now;
      for (const cue of timeline.cues) {
        const due = nextFireRef.current[cue.step];
        if (due != null && now >= due) {
          void fire(cue.step);
          // Advance by WHOLE laps, so a backgrounded tab that produced one
          // huge frame delta never issues a burst of catch-up fires.
          let next = due;
          while (next <= now) next += durationS * 1000;
          nextFireRef.current[cue.step] = next;
        }
      }
      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      lastFrameRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, durationS, cuesKey]);

  const scrubTo = useCallback((s: number) => {
    setPlaying(false);
    setPlayheadS(s);
    playheadRef.current = s;
  }, []);

  return { playheadS, playing, setPlaying, scrubTo };
}
