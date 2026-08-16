/** Checkbox picker for the device-preview strip's favourite virtuals
 * (report §4) — against the same GET /api/registry every scene-editing
 * tab already reads, no new "list the virtuals" endpoint. Saving an empty
 * selection resets to the zero-configuration default (room_topology's
 * genuinely-driven ground truth) rather than showing nothing. */
import { useEffect, useState } from 'react';
import { useDevicePreviewFavorites, useRegistry, useSaveDevicePreviewFavorites } from '../queries';
import { useToast } from './Toast';

export default function FavoritesPicker({ onClose }: { onClose: () => void }) {
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
        <button type="button" onClick={onClose}>Cancel</button>
        <button type="button" className="primary" disabled={save.isPending}
          onClick={() => commit(picked ?? [])}>
          Save
        </button>
      </div>
    </div>
  );
}
