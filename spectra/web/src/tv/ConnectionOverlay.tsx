/** THE LOST-CONNECTION OVERLAY (data/tv-display-plan/plan.html PR 1.5,
 * §2.2): "After 5 s without the feed: a small dim 'reconnecting' mark,
 * the last screen kept; after 60 s: black." Mounted above every other
 * plane in TvApp.tsx so it can cover them once the 60s mark passes,
 * while the brief <5s blip and the 5-60s window both leave whatever's
 * already on screen fully visible underneath. */
import { useEffect, useState } from 'react';
import { nowMs } from './feed';
import { useFeed } from './useFeed';

const MARK_AFTER_MS = 5_000;
const BLACK_AFTER_MS = 60_000;

export default function ConnectionOverlay() {
  const feed = useFeed();
  const [, force] = useState(0);
  useEffect(() => {
    const id = setInterval(() => force((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);

  if (feed.disconnectedAtMs === null) return null;
  // `feed.disconnectedAtMs` is stamped with `nowMs()` (feed.ts's own
  // performance.timeOrigin-anchored clock) — comparing it against
  // `Date.now()` here would be exactly the clock-source mismatch PR 1.4's
  // review caught in PartyScreen.tsx (data/tv-display-plan review,
  // tv-party-progress-clock-mixing).
  const downFor = nowMs() - feed.disconnectedAtMs;
  if (downFor < MARK_AFTER_MS) return null;
  if (downFor >= BLACK_AFTER_MS) return <div className="tv-lost-black" aria-hidden="true" />;
  return <div className="tv-lost-mark" role="status">Reconnecting…</div>;
}
