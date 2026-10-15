/** Checkbox picker for the device-preview strip's favourite virtuals
 * (report §4) — against the same GET /api/registry every scene-editing
 * tab already reads, no new "list the virtuals" endpoint. Saving an empty
 * selection resets to the zero-configuration default (room_topology's
 * genuinely-driven ground truth) rather than showing nothing. */
import { useEffect, useState } from 'react';
import { useDevicePreviewFavorites, useRegistry, useSaveDevicePreviewFavorites } from '../queries';
import { useToast } from './Toast';

export default function FavoritesPicker({
  onClose, chips = false,
}: {
  onClose: () => void;
  /** THE MOCKUP'S OWN ROW (design-fidelity pass, 2026-10-14 — audit S1:
   * "Preview favourites as inline chips"): one pill per virtual, lit when
   * picked, each a toggle that SAVES ITSELF — no bordered checkbox form
   * and no Reset/Cancel/Save row, which is what the Settings "Room" card
   * drew. The checkbox form stays for every other caller. */
  chips?: boolean;
}) {
  const { data: registry } = useRegistry();
  const { data: favorites } = useDevicePreviewFavorites();
  const save = useSaveDevicePreviewFavorites();
  const toast = useToast();
  const [picked, setPicked] = useState<string[] | null>(null);

  useEffect(() => {
    if (favorites && picked === null) setPicked(favorites.effective_virtual_ids);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [favorites]);

  const allVirtuals = [...new Set(
    Object.values(registry?.categories ?? {}).flatMap((c) => c.virtuals),
  )].sort();

  const toggle = (id: string) => {
    setPicked((prev) => {
      const cur = prev ?? [];
      return cur.includes(id) ? cur.filter((v) => v !== id) : [...cur, id];
    });
  };

  const commit = (ids: string[]) => {
    save.mutate(ids, {
      onError: (err) => toast(`Couldn't save favourites: ${(err as Error).message}`, 'error'),
      onSuccess: onClose,
    });
  };

  // Cancel discards any unsaved checkbox toggles — self-contained rather
  // than relying on `onClose` unmounting this component. That unmount-
  // discards-the-draft assumption held while this was only ever opened in
  // a popover/dialog; mounted permanently inline (settings/RoomCard.tsx),
  // nothing ever unmounts it, so without this the picker would otherwise
  // keep showing whatever was toggled with no way to back out.
  const cancel = () => {
    setPicked(favorites ? favorites.effective_virtual_ids : null);
    onClose();
  };

  if (chips) {
    // Each chip commits on its own press, so there is no draft to cancel
    // and no Save to forget; `onClose` still fires (a no-op inline).
    const current = picked ?? [];
    return (
      <span className="favourite-chips">
        {allVirtuals.length === 0 && <span className="empty-note">No virtuals in the registry yet.</span>}
        {allVirtuals.map((id) => {
          const on = current.includes(id);
          return (
            <button key={id} type="button"
              className={`favourite-chip${on ? ' favourite-chip-on' : ''}`}
              aria-pressed={on}
              title={on ? `${id} — in the preview strip. Tap to remove.` : `${id} — tap to add to the preview strip.`}
              onClick={() => {
                const next = on ? current.filter((v) => v !== id) : [...current, id];
                setPicked(next);
                commit(next);
              }}>
              <span className="favourite-chip-dot" aria-hidden />
              {id}
            </button>
          );
        })}
        <button type="button" className="favourite-chip favourite-chip-reset"
          title="Clear your choices — back to the auto-populated default"
          onClick={() => { setPicked([]); commit([]); }}>
          Reset
        </button>
      </span>
    );
  }

  return (
    <div className="device-preview-picker">
      <div className="device-preview-picker-title">
        Preview favourites
        <span className="device-preview-picker-hint">4 recommended for a compact strip — pick as many as you like</span>
      </div>
      <div className="device-preview-picker-list">
        {allVirtuals.length === 0 && <div className="empty-note">No virtuals in the registry yet.</div>}
        {allVirtuals.map((id) => (
          <label key={id} className="device-preview-picker-row">
            <input type="checkbox" checked={(picked ?? []).includes(id)} onChange={() => toggle(id)} />
            {id}
          </label>
        ))}
      </div>
      <div className="device-preview-picker-actions">
        <button type="button" onClick={() => commit([])} title="Clear your choices — back to the auto-populated default">
          Reset to default
        </button>
        <button type="button" onClick={cancel}>Cancel</button>
        <button type="button" className="primary" disabled={save.isPending}
          onClick={() => commit(picked ?? [])}>
          Save
        </button>
      </div>
    </div>
  );
}
