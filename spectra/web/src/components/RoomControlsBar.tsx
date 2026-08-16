/** Compact room-control strip — brightness multiplier (wired: the legacy
 * Brightness Multiplier action equivalent, scales every write uniformly at
 * the fx_executor / scene_compiler seams) plus ambient mode/colour (wired:
 * freezes the room's live Hue devices and holds them at the chosen colour
 * over direct bridge REST — spectra/services/ambient.py) and global
 * transition pace (state only), the scene-change settings model (three
 * additive ticks — see SCENE_CHANGE_MODES below and
 * spectra/services/room_controls.py), and Force Scene — the legacy Now
 * Playing control ported verbatim (owner direction: reuse the old system's
 * design/behaviour). Mounted once in App.tsx, next to the ownership bar. */
import { useEffect, useMemo, useState } from 'react';
import ColorGradientPicker from './ColorGradientPicker';
import HelpLink from '../help/HelpLink';
import { useEngineStatus, useRoomControls, useSaveRoomControls, useScenes } from '../queries';
import type { AmbientMode, AmbientResult, RoomControlState, SceneChangeMode } from '../types';
import SearchSelect from './forms/SearchSelect';

const AMBIENT_NOTE: Record<string, string> = {
  dark: "SPECTRA isn't driving the lights right now — saved, nothing changed live",
  'no-hue-devices': 'no live Hue device in the room — saved, nothing to hold',
  failed: 'every live Hue device rejected the change (bridge unreachable?) — saved, but the room may not match this switch',
};

/** His own three settings (spectra/services/ambient_music_gate.py). */
const AMBIENT_MODES: { value: AmbientMode; label: string; title: string }[] = [
  { value: 'off', label: 'Off',
    title: 'Ambient never holds — the whole room performs, Hue included.' },
  { value: 'always', label: 'On during music',
    title: 'Hue held lit at the ambient colour at all times, music playing or not — '
      + 'every other device keeps running the show regardless.' },
  { value: 'auto', label: 'Auto-return',
    title: 'Hue holds only while nothing is playing; releases the instant music starts, '
      + 'and returns on its own — with the same eased release — when it stops.' },
];

/** The live mode (spectra/services/ambient_music_gate.py's status(), polled
 * every 3s via useEngineStatus — NOT the one-shot PUT outcome below). This
 * is the honest "what is Ambient actually doing right now" indicator: the
 * select alone can't say it, because "Auto-return" means "hold only when
 * confirmed quiet" — that diverges from what's actually held whenever
 * music is playing. Under "On during music" this normally reads "holding";
 * "partial" is the status-honesty fix (2026-08-15) — Ambient believes it
 * should be holding but the most recent check (a write's own read-back, or
 * the independent periodic GET-only recheck) found at least one light not
 * actually lit, or found nothing left to hold at all. */
const AMBIENT_MODE_NOTE: Record<string, string> = {
  holding: 'Ambient is actively holding the room at its colour — every light confirmed.',
  partial: "Ambient believes it should be holding, but the last check found at least one "
    + 'light not actually lit at the ambient colour (or nothing to hold at all) — see the '
    + 'lights named below.',
  yielding: "Auto-return is standing aside for music (or its playback state is momentarily "
    + 'unknown) — it resumes on its own the instant the room goes quiet.',
  transitioning: 'Ambient is mid hold/release right now.',
};
const AMBIENT_MODE_BADGE: Record<string, string> = {
  holding: 'badge-purple',
  partial: 'badge-red',
  yielding: 'badge-amber',
  transitioning: 'badge-gray',
};

/** "confirmed 4s ago" vs "confirmed 20m ago" — the honest alternative to a
 * live re-check on every 3s poll (spectra/services/ambient_music_gate.py's
 * own docstring: cheap enough to run every VERIFY_TICK_S seconds, not
 * cheap enough to run on every poll — so the age itself is the signal). */
function formatVerifyAge(seconds: number): string {
  if (seconds < 1) return 'just now';
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}

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
  const { data: scenes } = useScenes();
  const { data: engineStatus } = useEngineStatus();
  const ambientMode = engineStatus?.ambient;
  const [local, setLocal] = useState<RoomControlState | null>(null);
  const [ambientResult, setAmbientResult] = useState<AmbientResult | null>(null);
  const sceneOptions = useMemo(
    () => (scenes ?? []).map((s) => ({ value: s.id, label: s.name })),
    [scenes],
  );

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

      <label className="room-control" title="Ambient">
        Ambient
        <select
          value={local.ambient_mode}
          onChange={(e) => commit({ ...local, ambient_mode: e.target.value as AmbientMode })}
        >
          {AMBIENT_MODES.map((m) => (
            <option key={m.value} value={m.value} title={m.title}>{m.label}</option>
          ))}
        </select>
      </label>

      <label className="room-control" title="Ambient colour">
        <ColorGradientPicker
          value={local.ambient_color ?? '#ffffff'}
          onChange={(v) => commit({ ...local, ambient_color: v })}
          disabled={local.ambient_mode === 'off'}
          swatchWidth={40}
          swatchHeight={28}
          title="Ambient colour — a Hue entertainment stream only ever takes one solid colour"
        />
      </label>

      {local.ambient_mode !== 'off' && ambientMode && ambientMode.mode !== 'off' && (
        <span
          className={`badge ${AMBIENT_MODE_BADGE[ambientMode.mode]}`}
          title={AMBIENT_MODE_NOTE[ambientMode.mode]
            + (ambientMode.verified_age_s != null
              ? ` Confirmed ${formatVerifyAge(ambientMode.verified_age_s)}.`
              : '')
            + (ambientMode.mode === 'partial' && ambientMode.verify?.unlit?.length
              ? ` Not lit: ${ambientMode.verify.unlit.join(', ')}.`
              : '')}
        >
          ambient: {ambientMode.mode}
          {ambientMode.mode === 'partial' && ambientMode.verify?.status === 'verified'
            && ` (${ambientMode.verify.lights_lit ?? 0}/${ambientMode.verify.lights_total ?? '?'} lit)`}
          {ambientMode.verified_age_s != null && ` · ${formatVerifyAge(ambientMode.verified_age_s)}`}
        </span>
      )}

      {ambientResult && !['on', 'off', 'yielding'].includes(ambientResult.status) && (
        <span
          className={`badge ${ambientResult.status === 'failed' ? 'badge-red' : 'badge-gray'}`}
          title={AMBIENT_NOTE[ambientResult.status]}
        >
          ambient: {ambientResult.status}
        </span>
      )}

      {ambientResult?.status === 'partial' && (
        <span
          className="badge badge-red"
          title={`Held at ${ambientResult.lights_set ?? 0}/${ambientResult.lights_total ?? '?'} — `
            + `still showing the old colour: ${(ambientResult.unconfirmed ?? []).join(', ')}. `
            + 'Read back from the bridge after bounded, spaced retries — not just what was sent.'}
        >
          ambient: {ambientResult.lights_set ?? 0}/{ambientResult.lights_total ?? '?'} held —{' '}
          {(ambientResult.unconfirmed ?? []).join(', ')}
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

      <label className="room-control"
        title="Hold one scene: whenever a new scene would be picked, reassert the forced scene instead">
        <input
          type="checkbox"
          checked={local.force_scene_enabled}
          onChange={(e) => commit({ ...local, force_scene_enabled: e.target.checked })}
        />
        Force Scene
      </label>
      {local.force_scene_enabled && (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <SearchSelect value={local.force_scene_scene_id ?? ''} options={sceneOptions} width={160}
            placeholder="— pick scene —" allowEmpty={false}
            onChange={(v) => commit({ ...local, force_scene_scene_id: v })} />
          <HelpLink topic="force-scene" />
        </span>
      )}

      <HelpLink topic="room-controls-bar" />
    </div>
  );
}
