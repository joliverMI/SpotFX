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
import HelpLink from '../help/HelpLink';
import { chipLine } from '../house/houseSummary';
import type { LightingStatus } from '../house/types';
import { useHoldToConfirm } from '../lib/useHoldToConfirm';
import { useEngineStatus, useToggleHouseEnabled } from '../queries';
import {
  holdTooltip, resolveEnabledFromResponse, shouldNavigateOnClick, shouldNavigateOnKeyUp,
  toggleErrorMessage, toggleResultMessage,
} from './modeChipHold';
import { useToast } from './Toast';

const RING_SIZE = 16;
const STROKE = 2;
const RADIUS = (RING_SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
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

  return (
    <span className={`mode-chip mode-chip-${tone}`}>
      <Link
        to="/house"
        className="mode-chip-link"
        title={holdTooltip(title)}
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
        {pressing && (
          <svg
            className="mode-chip-hold-ring"
            width={RING_SIZE}
            height={RING_SIZE}
            viewBox={`0 0 ${RING_SIZE} ${RING_SIZE}`}
            aria-hidden="true"
          >
            <circle
              cx={RING_SIZE / 2}
              cy={RING_SIZE / 2}
              r={RADIUS}
              fill="none"
              stroke="currentColor"
              strokeWidth={STROKE}
              strokeDasharray={CIRCUMFERENCE}
              strokeDashoffset={CIRCUMFERENCE * (1 - progress)}
              transform={`rotate(-90 ${RING_SIZE / 2} ${RING_SIZE / 2})`}
            />
          </svg>
        )}
        ⌂ {text}
      </Link>
      <HelpLink topic="house-chip" />
      {(pressing || justReleasedEarly) && (
        <span className="mode-chip-hold-hint" role="status">
          {pressing ? 'Keep holding…' : 'Hold to turn house lighting on/off'}
        </span>
      )}
    </span>
  );
}
