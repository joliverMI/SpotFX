/** THE NEXT-EVENT BOX — the type glyph of whatever will actually fire
 * next, and a countdown to it.
 *
 * IT LIVES IN TWO PLACES, AND NEVER IN BOTH AT ONCE (the Admiral's Q1
 * answer, 2026-10-15): inside the song-timeline row at the widths where
 * that row has space for it, and in the ONE BAR's second row at
 * `<=1100px` — the 1024 tablet and the 800 wall kiosk — where the row's
 * own 96px box squeezed the track it sits beside. `useNextBoxInBar()` is
 * the one predicate both callers ask, so the box can never be drawn twice
 * or nowhere.
 *
 * It owns its OWN rAF loop rather than being driven by whichever parent
 * mounts it: the countdown, the lead-in fill, the flash and the glyph
 * swap all write attributes/textContent directly, so neither host pays a
 * React render per frame (report §4.2, and PR 424's own rule). That is
 * also what lets it move between hosts with no state to hand over.
 *
 * Its SIBLING EFFECTS on the timeline row — the pulsing "it is next" ring
 * on the track, and the marker flash — stay in SongStrip.tsx, because
 * they are drawn ON the track. Both pick the same event by the same
 * `pickNext`, so they agree wherever this box happens to be. */
import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import {
  countdownParts, eventFireMs, eventLabel, FINAL_STRETCH_MS, kindGlyphSvg, NEXT_EVENT_BOX_WIDTH,
  pickNext, type UpcomingEvent,
} from './songStrip';
import { getShowClockMs } from '../lib/showClock';
import useMediaQuery from '../lib/useMediaQuery';

/** The width band where the box belongs to the BAR rather than the
 * timeline row — EXACTLY the band tokens.css gives its deliberate two
 * rows (`521px`-`1100px`, his own "do C" decision), which is also
 * exactly the band his Q1 answer names ("at <=1100 px (1024 tablet,
 * kiosk)").
 *
 * THE PHONE TIER (<=520px) IS DELIBERATELY EXCLUDED, and it was measured:
 * the phone's own bar already wraps to two rows by its content, and
 * adding a 92px occupant to row 2 there pushed it to THREE. The phone's
 * timeline row has its own two-row layout with a dedicated next-box
 * column, so the box stays in the row there — which is what the
 * separately-tuned phone tier was built for. */
const IN_BAR_QUERY = '(min-width: 521px) and (max-width: 1100px)';

export function useNextBoxInBar(): boolean {
  return useMediaQuery(IN_BAR_QUERY);
}

export default function SongNextBox({
  events, durationMs, host,
}: {
  events: UpcomingEvent[];
  durationMs: number;
  /** Which of the two hosts is drawing it — styling only (the bar's own
   * copy is a bar-height slot, the row's is the 39px track-height box). */
  host: 'strip' | 'bar';
}) {
  // HTMLElement, not HTMLDivElement: the same ref is attached to a <div>
  // on the timeline row and an <a> in the bar, and the rAF loop below
  // only ever touches `classList`/`title`, which both have.
  const boxRef = useRef<HTMLElement>(null);
  const fillRef = useRef<HTMLDivElement>(null);
  const iconRef = useRef<SVGSVGElement>(null);
  const countRef = useRef<HTMLSpanElement>(null);
  const unitRef = useRef<HTMLElement>(null);
  const flashedKeyRef = useRef<string | null>(null);
  const lastGlyphRef = useRef<string | null>(null);

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const now = getShowClockMs();
      const next = now != null ? pickNext(events, now) : null;
      if (next) {
        // a drop counts to the moment it FIRES (mark + drop timing, his Q4)
        const remaining = eventFireMs(next) - (now as number);
        const key = `${next.ms}:${next.kind}`;
        const glyphKey = `${next.kind}:${next.num ?? ''}`;
        if (iconRef.current && lastGlyphRef.current !== glyphKey) {
          lastGlyphRef.current = glyphKey;
          iconRef.current.innerHTML = kindGlyphSvg(next.kind, next.num);
        }
        const parts = countdownParts(remaining);
        if (countRef.current) countRef.current.textContent = parts.value;
        if (unitRef.current) unitRef.current.textContent = parts.unit ?? '';
        if (boxRef.current) boxRef.current.title = eventLabel(next);
        const soon = remaining <= FINAL_STRETCH_MS;
        if (fillRef.current) {
          fillRef.current.style.transform =
            `scaleX(${soon ? 1 - remaining / FINAL_STRETCH_MS : 0})`;
        }
        boxRef.current?.classList.toggle('song-strip-next-soon', soon);
        if (remaining <= 0 && flashedKeyRef.current !== key) {
          flashedKeyRef.current = key;
          boxRef.current?.classList.add('song-strip-next-flash');
          setTimeout(() => boxRef.current?.classList.remove('song-strip-next-flash'), 600);
        }
      } else {
        if (countRef.current) countRef.current.textContent = '—';
        if (unitRef.current) unitRef.current.textContent = '';
        if (iconRef.current) { iconRef.current.innerHTML = ''; lastGlyphRef.current = null; }
        if (boxRef.current) {
          boxRef.current.title = durationMs > 0 ? 'Nothing left this song' : 'Nothing playing';
        }
        if (fillRef.current) fillRef.current.style.transform = 'scaleX(0)';
        boxRef.current?.classList.remove('song-strip-next-soon');
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [events, durationMs]);

  const body = (
    <>
      <div ref={fillRef} className="song-strip-next-fill" />
      {/* The TYPE GLYPH IS THE MARKER SHAPE, filled and kind-coloured
        * (songStrip.ts::kindGlyphSvg) — swapped with one innerHTML write
        * from the rAF loop, never a React render. */}
      <svg ref={iconRef} viewBox="0 0 16 16" width={18} height={18}
          className="song-strip-next-icon" aria-hidden="true" />
      <span className="song-strip-next-count tabular-nums">
        <span ref={countRef}>—</span>
        <small ref={unitRef} />
      </span>
    </>
  );

  // IN THE BAR it is a tappable slot like its neighbours (every other bar
  // occupant goes somewhere); on the row it is the mockup's plain box.
  if (host === 'bar') {
    return (
      <Link ref={boxRef as React.Ref<HTMLAnchorElement>} to="/"
          className="song-strip-next song-strip-next-in-bar"
          aria-label="What fires next — tap to open Home">
        {body}
      </Link>
    );
  }
  return (
    <div ref={boxRef as React.Ref<HTMLDivElement>} className="song-strip-next"
        style={{ width: NEXT_EVENT_BOX_WIDTH }}>
      {body}
    </div>
  );
}
