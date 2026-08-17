/** Checkbox picker for RoomControlState.ambient_hue_group_ids — WHICH Hue
 * entertainment areas Ambient may hold (spectra/services/ambient.py, "Hue
 * entertainment-area selection"), ported from legacy's own per-group
 * picker on the front-page Ambient button
 * (web/src/nowplaying/AmbientButton.tsx's long-press checkbox list).
 * Same phone-safe modal shape as FavoritesPicker.tsx (device-preview's own
 * favourites picker) — reused deliberately rather than a second one-off
 * overlay pattern.
 *
 * `[]` means "every live Hue device" (today's unmodified default), so an
 * unset selection shows every checkbox pre-checked rather than empty —
 * saving with every currently-known group checked normalizes BACK to []
 * (not an explicit full list), so a group added later is picked up
 * automatically instead of silently excluded by a now-stale explicit set. */
import { useEffect, useState } from 'react';
import HelpLink from '../help/HelpLink';
import { useAmbientHueGroups } from '../queries';

export default function AmbientGroupsPicker({ value, onSave, onClose }: {
  value: string[];
  onSave: (ids: string[]) => void;
  onClose: () => void;
}) {
  const { data, isLoading } = useAmbientHueGroups();
  const groups = data?.groups ?? [];
  const [picked, setPicked] = useState<string[] | null>(null);

  useEffect(() => {
    if (groups.length > 0 && picked === null) {
      setPicked(value.length > 0 ? value : groups.map((g) => g.id));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groups.length]);

  const toggle = (id: string) => {
    setPicked((prev) => {
      const cur = prev ?? [];
      return cur.includes(id) ? cur.filter((v) => v !== id) : [...cur, id];
    });
  };

  const save = () => {
    const cur = picked ?? [];
    onSave(cur.length >= groups.length ? [] : cur);
  };

  return (
    <div className="device-preview-picker">
      <div className="device-preview-picker-title">
        Ambient Hue areas <HelpLink topic="ambient-hue-groups" />
        <span className="device-preview-picker-hint">
          Which Hue entertainment areas Ambient may hold — an unchecked area keeps running its normal show, untouched.
        </span>
      </div>
      <div className="device-preview-picker-list">
        {isLoading && <div className="empty-note">loading…</div>}
        {!isLoading && groups.length === 0 && (
          <div className="empty-note">No live Hue device found in the room right now.</div>
        )}
        {groups.map((g) => (
          <label key={g.id} className="device-preview-picker-row">
            <input type="checkbox" checked={(picked ?? []).includes(g.id)} onChange={() => toggle(g.id)} />
            {g.name}
          </label>
        ))}
      </div>
      <div className="device-preview-picker-actions">
        <button type="button" onClick={() => onSave([])}
          title="Clear your choices — every live Hue device is held, today's default">
          Reset to default (all)
        </button>
        <button type="button" onClick={onClose}>Cancel</button>
        <button type="button" className="primary" onClick={save}>Save</button>
      </div>
    </div>
  );
}
