/** Compact room-control strip — brightness multiplier (wired: the legacy
 * Brightness Multiplier action equivalent, scales every write uniformly at
 * the fx_executor / scene_compiler seams) plus ambient mode/colour and
 * global transition pace (state today — folded into this surface ahead of
 * the full Ambient/Dinner-Party room-modes build, not bridge flags).
 * Mounted once in App.tsx, next to the ownership bar. */
import { useEffect, useState } from 'react';
import HelpLink from '../help/HelpLink';
import { useRoomControls, useSaveRoomControls } from '../queries';
import type { RoomControlState } from '../types';

export default function RoomControlsBar() {
  const { data } = useRoomControls();
  const save = useSaveRoomControls();
  const [local, setLocal] = useState<RoomControlState | null>(null);

  // Adopt server state unless a local edit is in flight (avoid clobbering
  // a slider drag with a stale refetch).
  useEffect(() => {
    if (data && !save.isPending) setLocal(data);
  }, [data, save.isPending]);

  if (!local) return null;

  const commit = (next: RoomControlState) => {
    setLocal(next);
    save.mutate(next);
  };

  return (
    <div className="room-controls-bar">
      <label className="room-control" title="Dims/undims the whole room uniformly">
        Brightness
        <input
          type="range" min={0} max={100} step={1}
          value={Math.round(local.brightness_multiplier * 100)}
          onChange={(e) => setLocal({ ...local, brightness_multiplier: Number(e.target.value) / 100 })}
          onMouseUp={() => commit(local)}
          onTouchEnd={() => commit(local)}
        />
        <span className="room-control-value">{Math.round(local.brightness_multiplier * 100)}%</span>
      </label>

      <label className="room-control">
        <input
          type="checkbox"
          checked={local.ambient_enabled}
          onChange={(e) => commit({ ...local, ambient_enabled: e.target.checked })}
        />
        Ambient
      </label>

      <label className="room-control" title="Ambient colour">
        <input
          type="color"
          value={local.ambient_color ?? '#ffffff'}
          onChange={(e) => commit({ ...local, ambient_color: e.target.value })}
          disabled={!local.ambient_enabled}
        />
      </label>

      <label className="room-control" title="Default scene-entry blend when a scene doesn't set its own">
        Transition
        <input
          type="number" min={0} max={20000} step={100}
          value={local.global_transition_ms}
          onChange={(e) => setLocal({ ...local, global_transition_ms: Number(e.target.value) })}
          onBlur={() => commit(local)}
        />
        ms
      </label>

      <label className="room-control"
        title="Whether GENERATED (seeded) mid-song triggers are allowed to fire. Off = fall back to transitions-only; hand-placed triggers always fire regardless.">
        <input
          type="checkbox"
          checked={local.midsong_triggers_enabled}
          onChange={(e) => commit({ ...local, midsong_triggers_enabled: e.target.checked })}
        />
        Mid-song triggers
      </label>

      <HelpLink topic="room-controls-bar" />
    </div>
  );
}
