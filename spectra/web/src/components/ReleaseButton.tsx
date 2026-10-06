/** THE PANIC HANDLE — now small, iconic, and hold-to-confirm (his ask,
 * 2026-10-06: "the release to home assistant button is too prominent...
 * put it at the right end of the top bar after brightness and make it a
 * small button with an icon... make the release to home assistant button
 * require a long press"). SPECTRA now runs his everyday house lighting
 * (house.py's own layer, see AGENTS.md), so releasing the room is rare and
 * consequential — the opposite of the always-reachable, no-confirmation
 * button this replaces, which was right when SPECTRA's own uptime wasn't
 * his daily lighting.
 *
 * Mounted at the right end of RoomControlsBar's row, after the brightness
 * dimmer. Renders NOTHING once the room is actually released — the
 * full-width banner in RoomOwnershipBar (unchanged by this task, per his
 * own "its behaviour after release is unchanged") is the way back from
 * there, and a second small control with nothing to do would just be
 * clutter next to it.
 *
 * The hold is `useHoldToConfirm` (pointer + keyboard, visible progress) —
 * see that hook's own docstring. A short tap/keypress shows "hold to
 * release" and does nothing; the full ~1s hold fires the release exactly
 * once. */
import Icon from './Icon';
import { useHoldToConfirm } from '../lib/useHoldToConfirm';
import { useOwnership, useReleaseRoom } from '../queries';
import { useToast } from './Toast';

const SIZE = 28;
const STROKE = 2.5;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const HOLD_MS = 1000;

export default function ReleaseButton() {
  const { data } = useOwnership();
  const release = useReleaseRoom();
  const toast = useToast();

  const doRelease = () => {
    release.mutate(undefined, {
      onSuccess: (result) => {
        if (result.result !== 'released') {
          // Loud, not silent: the record moved to released, but a device
          // could not be confirmed dark — it may still be lit.
          toast(
            `Release unverified — these lights may still be lit: ${(result.problems ?? []).join('; ')}`,
            'error',
          );
        } else {
          toast('Room released to Home Assistant', 'success');
        }
      },
      onError: (e) => toast(`Release failed: ${(e as Error).message}`, 'error'),
    });
  };

  const { progress, pressing, justReleasedEarly, bind } = useHoldToConfirm(HOLD_MS, doRelease);

  if (!data) return null;
  const released = data.owner === 'released';
  const handingOver = data.owner === 'handing-over';
  if (released) return null;

  const disabled = handingOver || release.isPending;

  return (
    <span className="release-hold-wrap">
      <button
        type="button"
        className="release-hold-btn"
        style={{ width: SIZE, height: SIZE }}
        disabled={disabled}
        aria-label="Release the room to Home Assistant — hold for about a second to confirm"
        title="Release ALL lights to Home Assistant — hold for ~1s to confirm. Rare and consequential: this hands the room away from SPECTRA."
        {...bind}
      >
        <Icon name="home" size={14} />
        <svg
          className="release-hold-ring"
          width={SIZE}
          height={SIZE}
          viewBox={`0 0 ${SIZE} ${SIZE}`}
          aria-hidden="true"
        >
          <circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke="currentColor"
            strokeWidth={STROKE}
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={CIRCUMFERENCE * (1 - progress)}
            transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
          />
        </svg>
      </button>
      {(pressing || justReleasedEarly) && (
        <span className="release-hold-hint" role="status">
          {pressing ? 'Keep holding…' : 'Hold to release'}
        </span>
      )}
    </span>
  );
}
