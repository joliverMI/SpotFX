/** The top bar's ENERGY readout (spectra/services/energy.py is the binding
 * statement): the number the engine acts on — the song's section energy on
 * its own 0..1 scale, with the Mark math (x 0.8 x the song's scale, an
 * unmarked song capped at 0.75) — not a display-only recomputation. It reads
 * the song's Energy timeline (GET /api/energy/timeline) at the SHOW CLOCK
 * (lib/showClock.ts, the clock the trigger poll fires on) on every animation
 * frame, so it changes exactly at a section edge instead of up to 3 s later
 * on the engine-status poll. Each frame writes the meter and the number
 * straight to the DOM: no React render per frame. With no timeline yet it
 * shows the engine status's own reading (bridge.intensity — the same Energy,
 * polled).
 *
 * DRAWN AS A BORDERED 34px SLOT (design-fidelity pass, 2026-10-14 — the
 * approved mockup's own `.sp .en`: a bolt glyph in the warning colour, a
 * 6px purple→magenta meter, and a bold tabular value). It also OPENS MARK
 * below desktop width, where the mockup hides the Mark box (Q12's "folds
 * INTO the Energy button") — see IntensityMarkControl.tsx's own `compact`
 * prop for that half. */
import { useEffect, useRef } from 'react';
import Icon from './Icon';
import InfoTip from './InfoTip';
import { useEnergyTimeline, useEngineStatus } from '../queries';
import { energyAt, energyFill } from '../lib/energyAt';
import { getShowClockMs } from '../lib/showClock';

export default function LiveEnergyReadout({ onOpenMark }: { onOpenMark?: () => void }) {
  const { data: st } = useEngineStatus();
  const uri = st?.bridge.track?.uri ?? null;
  const { data: tl } = useEnergyTimeline(uri);
  const polled = st?.bridge.intensity ?? null;
  const connected = st?.bridge.connected ?? false;
  const playing = st?.bridge.track?.is_playing ?? false;
  const sections = tl?.status === 'ok' && tl.uri === uri ? tl.sections : null;

  const fillRef = useRef<HTMLSpanElement | null>(null);
  const valueRef = useRef<HTMLSpanElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  // the latest inputs, read by the frame loop without restarting it
  const inputs = useRef({ sections, polled });
  inputs.current = { sections, polled };

  useEffect(() => {
    let raf = 0;
    let shown = '';
    const frame = () => {
      const { sections: secs, polled: fallback } = inputs.current;
      const live = energyAt(secs, getShowClockMs());
      const v = live ?? fallback;
      const text = v != null ? v.toFixed(2) : '—';
      if (text !== shown) {
        shown = text;
        if (valueRef.current) valueRef.current.textContent = text;
        if (fillRef.current) fillRef.current.style.width = `${Math.round(energyFill(v) * 100)}%`;
        buttonRef.current?.setAttribute('aria-label', `Energy ${v != null ? text : 'unavailable'}`);
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, []);

  const known = sections != null || polled != null;
  const title = known
    ? 'Energy now — the number the engine acts on: this section on the song\'s own scale (0 = its quietest, 1 = its loudest) with the Mark applied. An unmarked song stops at 0.75.'
    : !connected
      ? 'Bridge to spot-effects is down — no Energy (the engine holds 0.5 neutral)'
      : !playing
        ? 'Nothing playing — no Energy'
        : 'This song has no section analysis yet — no Energy (the engine holds 0.5 neutral)';

  return (
    <InfoTip
      topic="live-energy"
      text="Energy: the number the engine acts on — this section on the song's own 0 to 1 scale, with the Mark applied. Below desktop width, tapping it opens this song's Mark."
    >
      <button type="button" className="energy-readout" title={title} ref={buttonRef}
        data-mark-opener
        onClick={onOpenMark} aria-label="Energy">
        <Icon name="bolt" size={14} className="energy-readout-bolt" />
        <span className="energy-meter">
          <span className="energy-meter-fill" ref={fillRef} style={{ width: '0%' }} />
        </span>
        <span className="energy-readout-value tabular-nums" ref={valueRef}>—</span>
      </button>
    </InfoTip>
  );
}
