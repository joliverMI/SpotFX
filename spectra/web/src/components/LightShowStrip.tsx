/** The Light Show's slot in the one bar (UI declutter plan §3): "current →
 * next", each with its trigger icon and a live countdown, replacing the
 * old plain-text "Show: 9 Pulse holds, 6 settings changed" line. A
 * countdown timer instead of text, with a 10s lead-in fill (his edited
 * decision) — `.light-show-countdown-near` lights up inside the last 10s.
 * Tapping goes to the Sequence run page while a sequence is running, else
 * the plain Run page (showNowNext()'s own `href`).
 *
 * IT NEVER UNMOUNTS (design-fidelity pass, 2026-10-14 — audit B7/N2, one
 * of the two biggest reasons the live bar did not look like the approved
 * artifact). `if (!current && !brief?.active) return null;` removed the
 * whole slot whenever nothing was armed — his own state the evening he
 * reviewed the deploy — so the element the plan made the CENTRE of the
 * bar was absent most of the day, and its arrival/departure moved
 * everything after it. The mockup keeps the slot on screen with its own
 * third state (`showSlot('idle')`): the sparkle, "Nothing armed", and
 * "tap to run an action". Drawn as a bordered 34px slot
 * (`.sp .show`/`.sp .act`) with the holds count as a badge on the
 * sparkle, not as 0.85em inline text behind a "◈" glyph.
 *
 * BOTH IDLE LINES HAVE SHORTER PHONE VARIANTS (fm/ls-idle-clip-360
 * supersedes the note this replaces, which said only the "when" line
 * did). spotfx-deploy-427 fixed `.light-show-act-name`'s own fixed cap
 * (72px, clipping "Nothing armed" to "Nothing a…") everywhere but the
 * phone tier, on the theory that an uncapped `display: block` text
 * element fills its fixed-width slot and only ellipsises when genuinely
 * too wide. True on desktop; FALSE on a real 360px phone, where the
 * post-deploy check (spotfx-deploy-428) measured the idle name box at
 * ~71px against "Nothing armed"'s own ~92px at 12px/700 — still "Nothing
 * a…", with only ~9px of slack left even at 390. So the idle NAME gets
 * the exact same two-span treatment the "when" line already had:
 * `.light-show-act-name-full`/`-short` toggle on `tokens.css`'s own
 * `max-width: 520px` rule, never a second cap and never a JS width
 * check — costs nothing above that width, and both strings always sit
 * in `textContent`. An author-chosen action name is untouched and still
 * just ellipsises; only the idle "Nothing armed" placeholder shortens.
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
import { countdownParts } from './songStrip';
import { showNowNext, type ShowNowNextItem } from '../lightshow/showSummary';
import type { ShowBrief } from '../lightshow/types';

/** The countdown goes bold/white inside this many ms of the mark — the
 * mockup's own 10s lead-in (his edited decision). */
const NEAR_MS = 10_000;

/** The SAME countdown rule the song timeline's own next-event box uses
 * (components/songStrip.ts::countdownParts, the mockup's `cd()`): tenths
 * up to 99.95s, plain m:ss above it — never a tenth that keeps changing
 * for minutes. The unit is its own `<small>`, as the mockup draws it
 * (`.sp .act .wh small`). Against the live, interpolated song position,
 * never the raw 3s/10s poll value alone. */
function tenthsCountdown(dueMs: number, nowMs: number): { value: string; unit: string | null } {
  return countdownParts(dueMs - nowMs);
}

function NowNextItem({
  item, livePositionMs, role,
}: {
  item: ShowNowNextItem;
  livePositionMs: number | null;
  role: 'cur' | 'nxt';
}) {
  const live = item.dueMs != null && livePositionMs != null;
  const remainingMs = live ? item.dueMs! - livePositionMs! : null;
  const near = remainingMs != null && remainingMs <= NEAR_MS && remainingMs >= 0;
  const cd = live ? tenthsCountdown(item.dueMs!, livePositionMs!) : null;
  return (
    <span className={`light-show-act light-show-act-${role}${near ? ' light-show-act-near' : ''}`}>
      <span className="light-show-act-tag"><Icon name={item.icon} size={11} /></span>
      <span className="light-show-act-text">
        <span className="light-show-act-name">{item.label}</span>
        <span className="light-show-act-when tabular-nums">
          {cd ? <>{cd.value}{cd.unit && <small>{cd.unit}</small>}</> : item.whenText}
        </span>
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
  const idle = !current;

  return (
    <InfoTip
      className="light-show-strip"
      topic="show-strip"
      text="What the Light Show is doing right now and what's armed next — tap to open the run page."
    >
      <Link
        to={href}
        className={`light-show-slot${idle ? ' light-show-slot-idle' : ''}`}
        aria-label={idle
          ? 'Light Show — nothing armed. Tap to run an action.'
          : `Light Show — now ${current.label}${next ? `, next ${next.label}` : ''}. Tap for the run page.`}
        title={idle
          ? 'Light Show: nothing armed — tap for the Run page'
          : 'Light Show — tap for the Run page'}
      >
        <span className="light-show-spark">
          <Icon name="spark" size={18} />
          {holdsCount > 0 && (
            <span className="light-show-holds-badge"
              title={`${holdsCount} thing(s) the show is holding`}>{holdsCount}</span>
          )}
        </span>
        {idle ? (
          <span className="light-show-act light-show-act-cur light-show-act-wide">
            <span className="light-show-act-text">
              <span className="light-show-act-name light-show-act-name-idle">
                <span className="light-show-act-name-full">Nothing armed</span>
                <span className="light-show-act-name-short">Not armed</span>
              </span>
              <span className="light-show-act-when">
                <span className="light-show-act-when-full">tap to run an action</span>
                <span className="light-show-act-when-short">tap to run</span>
              </span>
            </span>
          </span>
        ) : (
          <>
            <NowNextItem item={current} livePositionMs={livePositionMs} role="cur" />
            <span className="light-show-chev"><Icon name="chevron" size={12} /></span>
            {next ? (
              <NowNextItem item={next} livePositionMs={livePositionMs} role="nxt" />
            ) : (
              <span className="light-show-act light-show-act-nxt">
                <span className="light-show-act-tag light-show-act-tag-dim"><Icon name="more" size={11} /></span>
                <span className="light-show-act-text">
                  <span className="light-show-act-name light-show-act-name-idle">nothing after</span>
                </span>
              </span>
            )}
          </>
        )}
      </Link>
    </InfoTip>
  );
}
