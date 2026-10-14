/** The Light Show's slot in the one bar (UI declutter plan §3): "current →
 * next", each with its trigger icon and a live countdown, replacing the
 * old plain-text "Show: 9 Pulse holds, 6 settings changed" line. A
 * countdown timer instead of text, with a 10s lead-in fill (his edited
 * decision) — `.light-show-countdown-near` lights up inside the last 10s.
 * Tapping goes to the Sequence run page while a sequence is running, else
 * the plain Run page (showNowNext()'s own `href`).
 *
 * Reads three already-existing sources, no new server work: `useEngineStatus`
 * (the `light_show` brief, already on the wire — spectra/services/engine.py's
 * `_light_show_brief()` — plus `bridge.track` for the live countdown clock),
 * `useShowArms` (the armed board, 10s poll), and `useSequenceRunStatus` (the
 * running sequence, 10s poll) — both from timeline/queries.ts, folded onto
 * the SAME cache entries the WS already pushes into (useLightShowBriefPush /
 * useLightShowSequencePush, mounted here once). */
import { Link } from 'react-router-dom';
import { useShowArms, useSequenceRunStatus } from '../timeline/queries';
import {
  useEngineStatus, useLightShowBriefPush, useLightShowSequencePush,
} from '../queries';
import { useLivePosition } from '../lib/useLivePosition';
import Icon from './Icon';
import InfoTip from './InfoTip';
import { showNowNext, type ShowNowNextItem } from '../lightshow/showSummary';
import type { ShowBrief } from '../lightshow/types';

/** "12.4s" under a minute, "1:04.2" over — a tenth-of-a-second countdown
 * against the live, interpolated song position, never the raw 3s/10s poll
 * value alone. */
function tenthsCountdown(dueMs: number, nowMs: number): string {
  const remaining = Math.max(0, dueMs - nowMs) / 1000;
  if (remaining < 60) return `${remaining.toFixed(1)}s`;
  const m = Math.floor(remaining / 60);
  const s = remaining - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, '0')}`;
}

function NowNextItem({ item, livePositionMs }: { item: ShowNowNextItem; livePositionMs: number | null }) {
  const live = item.dueMs != null && livePositionMs != null;
  const remainingMs = live ? item.dueMs! - livePositionMs! : null;
  const near = remainingMs != null && remainingMs <= 10_000 && remainingMs >= 0;
  return (
    <span className={`light-show-item${near ? ' light-show-item-near' : ''}`}>
      <Icon name={item.icon} size={13} />
      <span className="light-show-item-label">{item.label}</span>
      <span className="light-show-item-when">
        {live ? tenthsCountdown(item.dueMs!, livePositionMs!) : item.whenText}
      </span>
    </span>
  );
}

export default function LightShowStrip() {
  useLightShowBriefPush();
  useLightShowSequencePush();
  const { data: st } = useEngineStatus();
  const brief = (st as { light_show?: ShowBrief } | undefined)?.light_show;
  const { data: arms } = useShowArms();
  const { data: sequence } = useSequenceRunStatus();
  const livePositionMs = useLivePosition(st?.bridge.track);

  const { current, next, href, holdsCount } = showNowNext(brief, arms, sequence);

  if (!current && !brief?.active) return null;

  return (
    <span className="light-show-strip">
      <Link to={href} className="light-show-link" aria-label="Light Show — tap for the run page">
        <span className="light-show-diamond" title={holdsCount > 0 ? `${holdsCount} thing(s) the show is holding` : undefined}>
          ◈{holdsCount > 0 && <span className="light-show-holds-badge">{holdsCount}</span>}
        </span>
        {current ? <NowNextItem item={current} livePositionMs={livePositionMs} /> : <span className="light-show-item-when">Nothing armed</span>}
        {next && (
          <>
            <span className="light-show-sep">›</span>
            <NowNextItem item={next} livePositionMs={livePositionMs} />
          </>
        )}
      </Link>
      <InfoTip
        topic="show-strip"
        text="What the Light Show is doing right now and what's armed next — tap the icon to open the run page."
      />
    </span>
  );
}
