/** The ⚠ chip (UI declutter plan §13 Q8, decided yes): the three
 * full-width amber strips (RoomOwnershipBar.tsx's ActivationStrip,
 * DarkFixtureStrip, HueScopeStrip) collapse into one small chip in the
 * bar, "⚠ N", tapping it shows the same details those strips show. The
 * strips themselves (and their content) are unchanged — this only changes
 * where they're DRAWN: a popover instead of a full-width row, so a
 * warning that "sat there all session" no longer eats a whole row on
 * every page while staying exactly as reachable.
 *
 * The released-room banner (RoomOwnershipBar's own `released` branch) is
 * untouched — his own "its behaviour after release is unchanged" ruling. */
import { useEffect, useRef, useState } from 'react';
import Icon from './Icon';
import { ActivationStrip, DarkFixtureStrip, HueScopeStrip } from './RoomOwnershipBar';
import { useOwnership } from '../queries';

export default function WarningChip() {
  const { data } = useOwnership();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    const onDocDown = (e: MouseEvent) => {
      if (rootRef.current?.contains(e.target as Node)) return;
      setOpen(false);
    };
    document.addEventListener('mousedown', onDocDown);
    return () => document.removeEventListener('mousedown', onDocDown);
  }, [open]);

  if (!data || data.owner === 'released') return null;

  const activationCount = data.activation?.partial
    ? data.activation.skipped.filter((d) => d.still_dark).length + Object.keys(data.activation.virtual_gaps).length
    : 0;
  const darkCount = data.dark_fixtures?.fault_count ?? 0;
  const hueCount = Object.keys(data.hue_stream_refusals ?? {}).length;
  const total = activationCount + darkCount + hueCount;
  if (total === 0) return null;

  return (
    <div className="warning-chip" ref={rootRef}>
      <button
        type="button"
        className="warning-chip-btn"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        title={`${total} warning${total === 1 ? '' : 's'} — tap for details`}
      >
        <Icon name="warn" size={14} /> {total}
      </button>
      {open && (
        <div className="warning-chip-panel">
          <ActivationStrip act={data.activation} />
          <DarkFixtureStrip dark={data.dark_fixtures} />
          <HueScopeStrip refusals={data.hue_stream_refusals} />
        </div>
      )}
    </div>
  );
}
