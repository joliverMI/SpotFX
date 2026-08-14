/** Compact room-control strip — brightness multiplier (wired: the legacy
 * Brightness Multiplier action equivalent, scales every write uniformly at
 * the fx_executor / scene_compiler seams) plus ambient mode/colour (wired:
 * freezes the room's live Hue devices and holds them at the chosen colour
 * over direct bridge REST — spectra/services/ambient.py) and global
 * transition pace (state only), plus the scene-change settings model
 * (three additive ticks — see SCENE_CHANGE_MODES below and
 * spectra/services/room_controls.py).
 * Mounted once in App.tsx, next to the ownership bar. */
import { useEffect, useState } from 'react';
import HelpLink from '../help/HelpLink';
import { useRoomControls, useSaveRoomControls } from '../queries';
import type { AmbientResult, RoomControlState, SceneChangeMode } from '../types';

const AMBIENT_NOTE: Record<string, string> = {
  dark: "SPECTRA isn't driving the lights right now — saved, nothing changed live",
  'no-hue-devices': 'no live Hue device in the room — saved, nothing to hold',
  failed: 'every live Hue device rejected the change (bridge unreachable?) — saved, but the room may not match this switch',
};

const SCENE_CHANGE_MODES: { value: SceneChangeMode; label: string; title: string }[] = [
  { value: 'transitions', label: 'Transitions only',
    title: 'A scene change on every song transition. Nothing else fires.' },
  { value: 'analysed', label: '+ Analysed',
    title: 'Transitions, plus the analysed mid-song triggers "⟳ Generate" seeds. '
      + 'Your own hand-placed triggers and flares still don’t fire.' },
  { value: 'full', label: '+ My triggers',
    title: 'Everything: transitions, analysed mid-song triggers, your own '
      + 'hand-placed triggers, and response-engine flares.' },
];

export default function RoomControlsBar() {
  const { data } = useRoomControls();
  const save = useSaveRoomControls();
  const [local, setLocal] = useState<RoomControlState | null>(null);
  const [ambientResult, setAmbientResult] = useState<AmbientResult | null>(null);

  // Adopt server state unless a local edit is in flight (avoid clobbering
  // a slider drag with a stale refetch).
  useEffect(() => {
    if (data && !save.isPending) setLocal(data);
  }, [data, save.isPending]);

  if (!local) return null;

  const commit = (next: RoomControlState) => {
    setLocal(next);
    save.mutate(next, {
      onSuccess: (res) => setAmbientResult(res.ambient_result ?? null),
    });
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

      {ambientResult && ambientResult.status !== 'on' && ambientResult.status !== 'off' && (
        <span
          className={`badge ${ambientResult.status === 'failed' ? 'badge-red' : 'badge-gray'}`}
          title={AMBIENT_NOTE[ambientResult.status]}
        >
          ambient: {ambientResult.status}
        </span>
      )}

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

      <label className="room-control" title="What drives scene changes">
        Scene changes
        <select
          value={local.scene_change_mode}
          onChange={(e) => commit({ ...local, scene_change_mode: e.target.value as SceneChangeMode })}
        >
          {SCENE_CHANGE_MODES.map((m) => (
            <option key={m.value} value={m.value} title={m.title}>{m.label}</option>
          ))}
        </select>
      </label>

      <HelpLink topic="room-controls-bar" />
    </div>
  );
}
