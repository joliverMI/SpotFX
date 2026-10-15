/** HOUSE LIGHTING's chip — first in the shared top bar on every page:
 * "Mode: Evening · HA", "Mode: Evening · ♪" while music has the room,
 * "· not applied" when SPECTRA does not hold the room, "· off" muted when
 * HouseSettings.enabled is false. A short tap opens the House page. Reads
 * the `lighting` key of the engine status the app already polls; no extra
 * request. The words live in house/houseSummary.ts so the chip and the
 * House page's Now panel can never disagree.
 *
 * HOLD TO TOGGLE (his ask, 2026-10-06: "pressing and holding the house
 * mode button on the top bars should turn it on and off") — a ~1s hold
 * flips the cutover switch, same `useHoldToConfirm` progress-ring gesture
 * ReleaseButton.tsx uses, so holding shows a visible fill rather than
 * firing blind. `useToggleHouseEnabled` (queries.ts) reads the switch
 * fresh before writing and folds the PUT's own returned state back into
 * the engine-status cache, so this chip shows the CONFIRMED new state —
 * never an assumed one — the instant the write lands.
 *
 * A short tap must still navigate and a completed hold must NOT — both
 * are one gesture on one element, so the click that follows a fired hold
 * is swallowed (`firedRef` + `onClickCapture`), the same shape
 * `useLongPress.ts`'s own onClickCapture swallow already uses elsewhere in
 * this app. Keyboard: `useHoldToConfirm`'s `onKeyDown` already
 * `preventDefault()`s Enter/Space before the native anchor activation can
 * fire, so a short key press must navigate manually here (there is no
 * native click left to do it), while a completed hold must not.
 *
 * `firedRef` is cleared at the START of every new gesture (pointerdown /
 * a fresh non-repeat keydown), never on a timer — a timer raced the real
 * hold duration during eye-check verification: a hold that fires at the
 * ~1s mark but is held a little LONGER before release (the ordinary
 * case — nothing requires him to release at exactly 1000ms) let a
 * short-lived reset clear the flag before the trailing click/keyup ever
 * arrived, so the swallow silently stopped swallowing and the chip both
 * toggled AND navigated. Clearing on the next gesture's own start instead
 * self-heals the one case a timer was guarding (a pointer dragged off the
 * chip after a hold completes, so no click ever follows) without ever
 * expiring while the current gesture is still live. */
import { useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import Icon from './Icon';
import InfoTip from './InfoTip';
import { chipLine } from '../house/houseSummary';
import type { LightingStatus } from '../house/types';
import { useHoldToConfirm } from '../lib/useHoldToConfirm';
import { useEngineStatus, useToggleHouseEnabled } from '../queries';
import {
  holdTooltip, resolveEnabledFromResponse, shouldNavigateOnClick, shouldNavigateOnKeyUp,
  toggleErrorMessage, toggleResultMessage,
} from './modeChipHold';
import { useToast } from './Toast';

/** THE HOLD RING SITS OUTSIDE THE BUTTON (design-fidelity pass,
 * 2026-10-14 — the approved mockup's own `.sp .house .holdring`, `inset:
 * -4px`): "so holding moves nothing" (audit B1). It used to be a 16px
 * circle drawn INSIDE the 34px chip, next to the icon, which both shrank
 * the glyph's room and read as a second control. It is now a rounded-rect
 * stroke tracing the button's own 36px outline, 4px outside it, with
 * `pathLength=100` so one `stroke-dashoffset` number IS the percentage —
 * the mockup's own trick, and simpler than a circumference calculation. */
const RING_INSET = 4;
const RING_BOX = 36 + RING_INSET * 2;
const HOLD_MS = 1000;

export default function ModeChip() {
  const { data } = useEngineStatus();
  const lighting = (data as { lighting?: LightingStatus } | undefined)?.lighting;
  const { text, tone, title } = chipLine(lighting);
  const navigate = useNavigate();
  const toast = useToast();
  const toggleEnabled = useToggleHouseEnabled();
  const firedRef = useRef(false);

  const doToggle = () => {
    firedRef.current = true;
    toggleEnabled.mutate(undefined, {
      onSuccess: (res) => toast(toggleResultMessage(resolveEnabledFromResponse(res)), 'success'),
      onError: (e) => toast(toggleErrorMessage((e as Error).message), 'error'),
    });
  };

  const { progress, pressing, justReleasedEarly, bind } = useHoldToConfirm(HOLD_MS, doToggle);

  const musicHasTheRoom = tone === 'music';

  return (
    <InfoTip
      className={`mode-chip mode-chip-${tone}`}
      topic="house-chip"
      text="Lit while a house mode drives the room, with a ♪ badge while music has it, dim when house lighting is off. Tap to open House; hold ~1s to turn house lighting on/off."
    >
      <Link
        to="/house"
        className="mode-chip-link"
        title={holdTooltip(title)}
        aria-label={`House: ${text}. ${holdTooltip('Tap to open House, hold to turn house lighting on/off')}`}
        {...bind}
        onPointerDown={(e) => {
          firedRef.current = false;
          bind.onPointerDown(e);
        }}
        onKeyDown={(e) => {
          if (!e.repeat && (e.key === 'Enter' || e.key === ' ')) firedRef.current = false;
          bind.onKeyDown(e);
        }}
        onKeyUp={(e) => {
          bind.onKeyUp(e);
          if (shouldNavigateOnKeyUp(e.key, firedRef.current)) navigate('/house');
          firedRef.current = false;
        }}
        onClickCapture={(e) => {
          if (!shouldNavigateOnClick(firedRef.current)) {
            e.preventDefault();
            e.stopPropagation();
          }
          firedRef.current = false;
        }}
      >
        <Icon name="home" size={18} />
        {/* The ♪ BADGE the mockup draws on the corner while music has the
          * room (audit B1) — drawn, never the Unicode character. */}
        {musicHasTheRoom && (
          <span className="mode-chip-music-badge" aria-hidden>
            <Icon name="note" size={9} />
          </span>
        )}
        {pressing && (
          <svg
            className="mode-chip-hold-ring"
            viewBox={`0 0 ${RING_BOX} ${RING_BOX}`}
            aria-hidden="true"
          >
            <rect
              x={1.5} y={1.5} width={RING_BOX - 3} height={RING_BOX - 3} rx={11}
              fill="none" stroke="currentColor" strokeWidth={3}
              pathLength={100} strokeDasharray={100}
              strokeDashoffset={100 - progress * 100}
            />
          </svg>
        )}
      </Link>
      {/* `justReleasedEarly` is still read so a short tap's own feedback
        * stays in the accessible name rather than popping a text hint
        * under the bar (the mockup has no such hint — audit B1). */}
      <span className="sr-only" role="status">
        {pressing ? 'Keep holding to switch house lighting' : justReleasedEarly ? 'Hold to turn house lighting on/off' : ''}
      </span>
    </InfoTip>
  );
}
