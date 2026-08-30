/** Compact room-control strip — three press-and-hold grouped buttons
 * (his ask, 2026-08-17: "group items that are related... make it just a
 * single button that is pressed and held to expand vertically down with
 * the additional options") plus the room-wide brightness dimmer, which
 * he didn't name as belonging to any group and stays a standalone slider.
 *
 * - **Mode** — the Hybrid/Dark/Light display-mode control
 *   (spectra/services/dark_light.py) plus its Light-mode colour/
 *   brightness. Short press CYCLES the three modes; the button is
 *   COLOURED by whichever mode is current (Light even shows the actual
 *   configured colour, since that's the whole point of the mode). Hold
 *   expands to the colour picker + brightness slider.
 * - **Ambient** — a light-bulb icon (spectra/services/ambient_music_gate.py).
 *   Short press toggles it on/off (remembers the last non-off setting so
 *   toggling back "on" restores it, rather than one fixed choice). Hold
 *   expands to the three-setting select, both authored colours, the Hue
 *   entertainment-area picker (AmbientGroupsPicker, embedded directly —
 *   no separate modal), and the live status.
 * - **Scenes** — scene-change tier, Force Scene, AND the global
 *   transition pace bundled in (his own ask: "bundle transitions into
 *   scenes"). A press just opens the panel — no cycle behaviour, by his
 *   own stated reason ("it don't want it to cycle anything").
 *
 * THE ONE-SECOND APPLY DELAY (Mode only, his words: "don't apply change
 * for 1s to avoid spam") is deliberately NOT a debounce on the button —
 * that would make every tap feel sluggish, the opposite of the ask. The
 * button's own display updates synchronously on every tap (`setLocal`);
 * only the actual PUT is delayed and re-armed on each further tap
 * (`useDebouncedApply`, trailing-edge), so a burst of cycling applies
 * exactly once, for whichever mode was landed on last, after taps stop
 * for a full second. See useDebouncedApply's own docstring. */
import { useEffect, useMemo, useRef, useState } from 'react';
import AmbientGroupsPicker from './AmbientGroupsPicker';
import ColorGradientPicker from './ColorGradientPicker';
import DriftGradientBar from './DriftGradientBar';
import TopBarGroupButton from './TopBarGroupButton';
import HelpLink from '../help/HelpLink';
import { useDebouncedApply } from '../lib/useDebouncedApply';
import {
  useAmbientHueGroups, useAmbientStatusPush, useEngineStatus, useRoomControls,
  useSaveRoomControls, useScenes,
  useSpotColorSets,
} from '../queries';
import type {
  AmbientPhase, AmbientResult, DarkLightResult, DisplayMode, ForceColorResult, ForceSceneResult,
  RoomControlState, SceneChangeMode,
} from '../types';
import SearchSelect from './forms/SearchSelect';

/** His three-way display-mode control (spectra/services/dark_light.py).
 * "default" is his word "hybrid" — labelled that way here per his standing
 * ruling, kept "default" internally/on the wire. Cycle order (short press
 * on the Mode button walks this array, wrapping): Hybrid -> Dark -> Light. */
const DISPLAY_MODES: { value: DisplayMode; label: string; title: string }[] = [
  { value: 'default', label: 'Hybrid',
    title: 'Nothing forced — each device shows whatever its scene authors.' },
  { value: 'dark', label: 'Dark',
    title: "Force every non-shielded device's background black, hard-clamped at LedFX." },
  { value: 'light', label: 'Light',
    title: 'Force the colour/brightness below onto every non-shielded device\'s background, live, '
      + 'right now — works while music is playing, no waiting for a scene change.' },
];

const AMBIENT_NOTE: Record<string, string> = {
  dark: "SPECTRA isn't driving the lights right now — saved, nothing changed live",
  'no-hue-devices': 'no live Hue device in the room — saved, nothing to hold',
  failed: 'every live Hue device rejected the change (bridge unreachable?) — saved, but the room may not match this switch',
};

/** The FROZEN phase contract, rendered (spectra/services/
 * ambient_music_gate.py). A transition takes 15-22s on his real room, so
 * the button MUST say which way it is going — that lag with no feedback is
 * the whole reason he kept pressing it again. The button is NEVER disabled
 * while in flight: a press during a transition is the INTERRUPT (it snaps
 * the room to the new state), not a no-op to be prevented. */
const AMBIENT_PHASE_LABEL: Partial<Record<AmbientPhase, string>> = {
  turning_on: 'Turning on…',
  turning_off: 'Turning off…',
};
const AMBIENT_PHASE_TITLE: Record<AmbientPhase, string> = {
  on: 'Ambient is on — tap to turn off, hold for options',
  off: 'Ambient is off — tap to turn on, hold for options',
  turning_on: 'Turning on… — tap again to snap it straight back off',
  turning_off: 'Turning off… — tap again to snap it straight back to full brightness',
  unavailable: "SPECTRA isn't driving the lights right now — your choice is saved and "
    + 'applies the moment the room comes back',
};

/** The live mode (spectra/services/ambient_music_gate.py's status(), on the
 * 3s poll AND the gate's own push — NOT the one-shot PUT outcome below).
 * `phase` above answers "which way is the room going"; this answers the
 * separate question "what are the BULBS actually doing", which can differ:
 * "partial" is the status-honesty fix (2026-08-15) — something believes it
 * should be holding but the most recent check (a write's own read-back, or
 * the independent periodic GET-only recheck) found at least one light not
 * actually lit, or found nothing left to hold at all — and "yielding" is
 * only reachable while the "When music pauses" switch is on. */
const AMBIENT_MODE_NOTE: Record<string, string> = {
  holding: 'Ambient is actively holding the room at its colour — every light confirmed.',
  partial: "Ambient believes it should be holding, but the last check found at least one "
    + 'light not actually lit at the ambient colour (or nothing to hold at all) — see the '
    + 'lights named below.',
  yielding: '"When music pauses" is standing aside for music (or its playback state is '
    + 'momentarily unknown) — it resumes on its own the instant the room goes quiet.',
  transitioning: 'Ambient is mid hold/release right now.',
};
const AMBIENT_MODE_BADGE: Record<string, string> = {
  holding: 'badge-purple',
  partial: 'badge-red',
  yielding: 'badge-amber',
  transitioning: 'badge-gray',
};
const AMBIENT_MODE_DOT: Record<string, string> = {
  holding: 'top-bar-group-btn-dot-purple',
  partial: 'top-bar-group-btn-dot-red',
  yielding: 'top-bar-group-btn-dot-amber',
  transitioning: 'top-bar-group-btn-dot-gray',
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

const DARK_LIGHT_NOTE: Record<string, string> = {
  'no-devices': "SPECTRA doesn't know of any virtual to touch — saved, nothing to lock",
  'handover-in-progress': 'light ownership is mid-handover right now — saved, nothing changed live',
  released: 'the room is released to Home Assistant right now — saved, nothing changed live',
  failed: 'could not reach LedFX to apply the change — saved, but the room may not match this switch',
};

// His own correction, 2026-08-19: the old "+" ladder implied all four
// tiers stack cumulatively, which is only true of three of them —
// "My triggers only" is a fourth, separate mode, not another rung, and
// its old label ("+ My triggers", on the FULL tier) read as exclusive
// when the code was additive — the tooltip contradicted the label on his
// own screen. No label below may imply exclusivity — or additivity — it
// doesn't have.
const SCENE_CHANGE_MODES: { value: SceneChangeMode; label: string; title: string }[] = [
  { value: 'transitions', label: 'Transitions only',
    title: 'A scene change on every song transition. Nothing else fires.' },
  { value: 'analysed', label: 'Transitions + analysed',
    title: 'Transitions, plus the analysed mid-song triggers "⟳ Generate" seeds. '
      + 'Your own hand-placed triggers and flares still don’t fire.' },
  { value: 'triggers_only', label: 'My triggers only',
    title: 'On a song where you\'ve placed any trigger: ONLY your own hand-placed '
      + 'triggers fire — transitions, analysed mid-song triggers, and flares are all '
      + 'silenced for that song. On a song where you haven\'t placed one, this behaves '
      + 'exactly like "Transitions + analysed" instead — it never goes silent.' },
  { value: 'full', label: 'Everything',
    title: 'Transitions, analysed mid-song triggers, your own hand-placed triggers, '
      + 'and response-engine flares — every source, on every song.' },
];

export default function RoomControlsBar() {
  const { data } = useRoomControls();
  const save = useSaveRoomControls();
  const { data: scenes } = useScenes();
  const { data: engineStatus } = useEngineStatus();
  // Ambient's phase must be visible within a second of a press, which the
  // 3s poll above cannot promise — this folds the gate's own pushed
  // ambient_status straight into that same cache entry.
  useAmbientStatusPush();
  const { data: hueGroupsData } = useAmbientHueGroups();
  const ambientLive = engineStatus?.ambient;
  const hueGroups = hueGroupsData?.groups ?? [];
  const [local, setLocal] = useState<RoomControlState | null>(null);
  const [ambientResult, setAmbientResult] = useState<AmbientResult | null>(null);
  const [darkLightResult, setDarkLightResult] = useState<DarkLightResult | null>(null);
  const [forceSceneResult, setForceSceneResult] = useState<ForceSceneResult | null>(null);
  const [forceColorResult, setForceColorResult] = useState<ForceColorResult | null>(null);
  const { data: colorCards } = useSpotColorSets();
  const [hueGroupsResetKey, setHueGroupsResetKey] = useState(0);
  const localRef = useRef<RoomControlState | null>(null);

  useEffect(() => { localRef.current = local; }, [local]);

  const sceneOptions = useMemo(
    () => (scenes ?? []).map((s) => ({ value: s.id, label: s.disabled ? `⛔ ${s.name}` : s.name })),
    [scenes],
  );

  // FORCE COLOUR's picker (owner ask 2026-08-27) — SETS AND GROUPS in one
  // list, because the pin genuinely accepts either (a Group pins the pool
  // and keeps its own rotation live; see spectra/services/force_color.py).
  // Groups are prefixed rather than split into a second control: this is
  // the deliberately minimal functional control he asked for ("focus on
  // fucntion and we will work on UI later"), not the finished shape.
  const colorTargetOptions = useMemo(
    () => (colorCards ?? []).map((c) => ({
      value: c.id,
      label: `${c.disabled ? '⛔ ' : ''}${c.kind === 'group' ? '▤ ' : ''}${c.name}`,
    })),
    [colorCards],
  );

  // Hoisted function declaration (not a `const`) so it's fully defined
  // for every render's closures — including modeApply's callback below,
  // which is created before local's null-check and must never reference
  // an uninitialized binding if that callback ever fires from a stale
  // render.
  function commit(next: RoomControlState) {
    setLocal(next);
    save.mutate(next, {
      onSuccess: (res) => {
        setAmbientResult(res.ambient_result ?? null);
        setDarkLightResult(res.dark_light_result ?? null);
        setForceSceneResult(res.force_scene_result ?? null);
        setForceColorResult(res.force_color_result ?? null);
      },
    });
  }

  const modeApply = useDebouncedApply<DisplayMode>((mode) => {
    if (!localRef.current) return;
    commit({ ...localRef.current, display_mode: mode });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, 1000);

  // Adopt server state unless a local edit is in flight — a mode cycle's
  // debounced apply hasn't landed on the server yet also counts as "in
  // flight": without this, a background refetch mid-cycle (react-query's
  // window-focus refetch, say) would silently snap the button back to the
  // old mode before the 1s delay even fires, which is exactly the
  // "sluggish/unresponsive" feel the delay was built to avoid.
  useEffect(() => {
    if (data && !save.isPending && !modeApply.isPending()) setLocal(data);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, save.isPending]);

  if (!local) return null;

  const cycleMode = () => {
    const idx = DISPLAY_MODES.findIndex((m) => m.value === local.display_mode);
    const nextMode = DISPLAY_MODES[(idx + 1) % DISPLAY_MODES.length].value;
    setLocal({ ...local, display_mode: nextMode });
    modeApply.schedule(nextMode);
  };
  const pickMode = (mode: DisplayMode) => {
    setLocal({ ...local, display_mode: mode });
    modeApply.schedule(mode);
  };

  const modeMeta = DISPLAY_MODES.find((m) => m.value === local.display_mode) ?? DISPLAY_MODES[0];
  // No text on this button (his ask, 2026-08-17: "I don't need the mode to
  // say dark or light I just want the color to make that clear") — fill
  // colour IS the mode: white=Light, black=Dark, grey=Hybrid, his exact
  // mapping, not adjusted for taste. A fixed accent border on every state
  // (not part of the mapping) keeps the button legible as a button against
  // the bar's own dark-purple background even when the fill is black.
  // #6b6b74 (not a lighter/neutral-er grey) is deliberate: measured against
  // white and black it lands at 5.3:1 / 4.0:1 contrast respectively — a
  // paler grey reads too close to the white state at a glance.
  const modeFill = local.display_mode === 'light'
    ? '#ffffff'
    : local.display_mode === 'dark'
      ? '#000000'
      : '#6b6b74';
  const modeStyle: React.CSSProperties = { background: modeFill, borderColor: 'var(--accent)' };
  const modeUnconfirmed = darkLightResult
    && ['default', 'dark', 'light'].includes(darkLightResult.status)
    && (darkLightResult.unconfirmed?.length ?? 0) > 0;

  // BINARY, by his own ruling — and it always toggles against what the
  // ROOM is currently doing (`phase`), not against the last value this tab
  // happened to save: mid-transition, "off" means "stop turning on", which
  // is exactly the interrupt he asked for.
  const ambientPhase: AmbientPhase = ambientLive?.phase
    ?? (local.ambient_enabled ? 'on' : 'off');
  const ambientInFlight = ambientPhase === 'turning_on' || ambientPhase === 'turning_off';
  const wantOn = ambientPhase === 'turning_on' ? false
    : ambientPhase === 'turning_off' ? true
      : !local.ambient_enabled;
  const toggleAmbient = () => {
    commit({ ...local, ambient_enabled: wantOn });
  };
  const ambientDotClass = ambientPhase === 'unavailable' && local.ambient_enabled
    ? 'top-bar-group-btn-dot-gray'
    : (local.ambient_enabled || ambientInFlight) && ambientLive && ambientLive.mode !== 'off'
      ? AMBIENT_MODE_DOT[ambientLive.mode]
      : null;

  return (
    <div className="room-controls-bar">
      <TopBarGroupButton
        className="mode-group-btn"
        title={`Mode: ${modeMeta.label} — tap to cycle, hold to open the colour/brightness options`}
        ariaLabel={`Display mode: ${modeMeta.label}. Tap to cycle, hold to open options.`}
        style={modeStyle}
        holdToExpand
        onShortPress={cycleMode}
        panelTitle={<>Mode <HelpLink topic="dark-light-mode" /></>}
        panel={(
          <>
            <div className="top-bar-group-field">
              <label>Mode</label>
              <select
                value={local.display_mode}
                onChange={(e) => pickMode(e.target.value as DisplayMode)}
              >
                {DISPLAY_MODES.map((m) => (
                  <option key={m.value} value={m.value} title={m.title}>{m.label}</option>
                ))}
              </select>
            </div>
            <div className="top-bar-group-field">
              <label>Light bg</label>
              <ColorGradientPicker
                value={local.display_light_bg_color}
                onChange={(v) => commit({ ...local, display_light_bg_color: v })}
                swatchWidth={40}
                swatchHeight={28}
                title="Light mode background colour"
              />
              <HelpLink topic="display-light-mode" />
            </div>
            <div className="top-bar-group-field">
              <label>Brightness</label>
              <input
                type="range" min={0} max={100} step={1}
                value={Math.round(local.display_light_bg_brightness * 100)}
                onChange={(e) => setLocal({ ...local, display_light_bg_brightness: Number(e.target.value) / 100 })}
                onMouseUp={() => commit(local)}
                onTouchEnd={() => commit(local)}
              />
              <span className="room-control-value">{Math.round(local.display_light_bg_brightness * 100)}%</span>
            </div>
            {darkLightResult && !['dark', 'light', 'default'].includes(darkLightResult.status) && (
              <span
                className={`badge ${darkLightResult.status === 'failed' ? 'badge-red' : 'badge-gray'}`}
                title={DARK_LIGHT_NOTE[darkLightResult.status]}
              >
                display mode: {darkLightResult.status}
              </span>
            )}
            {modeUnconfirmed && (
              <span
                className="badge badge-red"
                title={`Not confirmed at the requested state after read-back: ${(darkLightResult!.unconfirmed ?? []).join(', ')}`}
              >
                unconfirmed — {(darkLightResult!.unconfirmed ?? []).join(', ')}
              </span>
            )}
            {darkLightResult?.status === 'default' && darkLightResult.repaint_skipped === 'music_playing' && (
              <span
                className="badge badge-gray"
                title="Music is playing, so the stale pre-dark snapshot was not forced back — the room's own live show repaints it on its next natural fire instead"
              >
                repaint deferred to live show
              </span>
            )}
          </>
        )}
      >
        {modeUnconfirmed && <span className="top-bar-group-btn-dot top-bar-group-btn-dot-red" title="unconfirmed" />}
      </TopBarGroupButton>

      <TopBarGroupButton
        className={`ambient-group-btn${!local.ambient_enabled && !ambientInFlight ? ' ambient-group-btn-off' : ''}`}
        title={AMBIENT_PHASE_TITLE[ambientPhase]}
        ariaLabel={`Ambient: ${AMBIENT_PHASE_LABEL[ambientPhase] ?? ambientPhase}. `
          + 'Tap to toggle, hold for options.'}
        holdToExpand
        onShortPress={toggleAmbient}
        panelTitle={<>Ambient <HelpLink topic="ambient" /></>}
        panel={(
          <>
            <div className="top-bar-group-field">
              <label>Ambient</label>
              <button
                type="button"
                className="ambient-toggle-btn"
                onClick={toggleAmbient}
                title={AMBIENT_PHASE_TITLE[ambientPhase]}
              >
                {AMBIENT_PHASE_LABEL[ambientPhase]
                  ?? (ambientPhase === 'on' ? 'On' : ambientPhase === 'unavailable' ? 'Off (room away)' : 'Off')}
              </button>
            </div>
            <div className="top-bar-group-field">
              <label>When music pauses</label>
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <input
                  type="checkbox"
                  checked={local.ambient_on_music_pause}
                  onChange={(e) => commit({ ...local, ambient_on_music_pause: e.target.checked })}
                />
                <span style={{ fontSize: '0.85em', opacity: 0.75 }}>
                  turn Ambient on by itself
                </span>
              </label>
            </div>
            <div className="top-bar-group-field">
              <label>Colour</label>
              <ColorGradientPicker
                value={local.ambient_color ?? '#ffffff'}
                onChange={(v) => commit({ ...local, ambient_color: v })}
                disabled={!local.ambient_enabled}
                swatchWidth={40}
                swatchHeight={28}
                title="Ambient colour — a Hue entertainment stream only ever takes one solid colour"
              />
              <span style={{ fontSize: '0.85em', opacity: 0.75 }}>normal/hybrid</span>
            </div>
            <div className="top-bar-group-field">
              <label>Colour (dark)</label>
              <ColorGradientPicker
                value={local.ambient_color_dark ?? local.ambient_color ?? '#ffffff'}
                onChange={(v) => commit({ ...local, ambient_color_dark: v })}
                disabled={!local.ambient_enabled}
                swatchWidth={40}
                swatchHeight={28}
                title="Ambient colour for Dark mode — held instead of the normal ambient colour while Dark mode is on; starts the same until you pick one"
              />
              <HelpLink topic="ambient-dark-colour" />
            </div>
            <div className="top-bar-group-field" style={{ alignItems: 'flex-start' }}>
              <AmbientGroupsPicker
                key={hueGroupsResetKey}
                value={local.ambient_hue_group_ids}
                onClose={() => setHueGroupsResetKey((k) => k + 1)}
                onSave={(ids) => {
                  commit({ ...local, ambient_hue_group_ids: ids });
                  setHueGroupsResetKey((k) => k + 1);
                }}
              />
            </div>
            {ambientLive && ambientLive.mode !== 'off' && (
              <span
                className={`badge ${AMBIENT_MODE_BADGE[ambientLive.mode]}`}
                title={AMBIENT_MODE_NOTE[ambientLive.mode]
                  + (ambientLive.groups.length > 0 && ambientLive.groups.length < hueGroups.length
                    ? ` Holding: ${ambientLive.groups.join(', ')}.`
                    : '')
                  + (ambientLive.verified_age_s != null
                    ? ` Confirmed ${formatVerifyAge(ambientLive.verified_age_s)}.`
                    : '')
                  + (ambientLive.mode === 'partial' && ambientLive.verify?.unlit?.length
                    ? ` Not lit: ${ambientLive.verify.unlit.join(', ')}.`
                    : '')}
              >
                ambient: {ambientLive.mode}
                {ambientLive.mode === 'partial' && ambientLive.verify?.status === 'verified'
                  && ` (${ambientLive.verify.lights_lit ?? 0}/${ambientLive.verify.lights_total ?? '?'} lit)`}
                {ambientLive.verified_age_s != null && ` · ${formatVerifyAge(ambientLive.verified_age_s)}`}
              </span>
            )}
            {ambientResult
              && !['on', 'off', 'yielding', 'turning_on', 'turning_off', 'superseded']
                .includes(ambientResult.status) && (
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
          </>
        )}
      >
        💡
        {AMBIENT_PHASE_LABEL[ambientPhase] && (
          <span className="top-bar-group-btn-label ambient-group-btn-phase">
            {AMBIENT_PHASE_LABEL[ambientPhase]}
          </span>
        )}
        {ambientDotClass && <span className={`top-bar-group-btn-dot ${ambientDotClass}`} title={ambientLive?.mode} />}
      </TopBarGroupButton>

      <TopBarGroupButton
        className={`scenes-group-btn${local.force_scene_enabled ? ' scenes-group-btn-forced' : ''}`}
        title="Scene changes, Force Scene, transition pace — tap to open"
        holdToExpand={false}
        panelTitle="Scenes"
        panel={(
          <>
            <div className="top-bar-group-field">
              <label>Transition</label>
              <input
                type="number" min={0} max={20000} step={100}
                value={local.global_transition_ms}
                onChange={(e) => setLocal({ ...local, global_transition_ms: Number(e.target.value) })}
                onBlur={() => commit(local)}
              />
              <span style={{ fontSize: '0.85em', opacity: 0.75 }}>ms (0 = use the two below)</span>
            </div>
            <div className="top-bar-group-field">
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                Transition @ low intensity
                <HelpLink topic="intensity-scaled-transitions" />
              </label>
              <input
                type="number" min={0} max={20000} step={50}
                value={local.scene_transition_ms_gentle}
                onChange={(e) => setLocal({ ...local, scene_transition_ms_gentle: Number(e.target.value) })}
                onBlur={() => commit(local)}
              />
              <span style={{ fontSize: '0.85em', opacity: 0.75 }}>ms</span>
            </div>
            <div className="top-bar-group-field">
              <label>Transition @ high intensity</label>
              <input
                type="number" min={0} max={20000} step={50}
                value={local.scene_transition_ms_hard}
                onChange={(e) => setLocal({ ...local, scene_transition_ms_hard: Number(e.target.value) })}
                onBlur={() => commit(local)}
              />
              <span style={{ fontSize: '0.85em', opacity: 0.75 }}>ms</span>
            </div>
            <div className="top-bar-group-field">
              <label>Scene changes</label>
              <select
                value={local.scene_change_mode}
                onChange={(e) => commit({ ...local, scene_change_mode: e.target.value as SceneChangeMode })}
              >
                {SCENE_CHANGE_MODES.map((m) => (
                  <option key={m.value} value={m.value} title={m.title}>{m.label}</option>
                ))}
              </select>
            </div>
            <div className="top-bar-group-field">
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                <input
                  type="checkbox"
                  checked={local.force_scene_enabled}
                  onChange={(e) => commit({ ...local, force_scene_enabled: e.target.checked })}
                />
                Force Scene
              </label>
              <HelpLink topic="force-scene" />
            </div>
            {local.force_scene_enabled && (
              <div className="top-bar-group-field">
                <SearchSelect value={local.force_scene_scene_id ?? ''} options={sceneOptions} width={180}
                  placeholder="— pick scene —" allowEmpty={false}
                  onChange={(v) => commit({ ...local, force_scene_scene_id: v })} />
              </div>
            )}
            {forceSceneResult?.status === 'fired' && (
              <span className="badge badge-gray" title="Fired immediately on this pin — not waiting for the next automatic pick">
                fired: {forceSceneResult.scene_name ?? forceSceneResult.scene_id}
              </span>
            )}
            {forceSceneResult?.status === 'fired' && forceSceneResult.overrode_disabled && (
              <span className="badge badge-red"
                title="This scene is marked Disabled on the Scenes page — the pin still fired it, since you pressed the button, but it won't be picked automatically again while disabled">
                ⚠ overriding disabled scene
              </span>
            )}
            {forceSceneResult?.status === 'fired' && forceSceneResult.overrode_dwell && (
              <span className="badge badge-red"
                title="The previously-active scene hadn't cleared its own minimum dwell yet — the pin fired anyway, since you pressed the button">
                ⚠ overriding minimum dwell
              </span>
            )}
            {forceSceneResult?.status === 'skipped' && (
              <span className="badge badge-red" title="Force Scene did not fire — nothing was activated">
                not fired: {forceSceneResult.reason}
              </span>
            )}
            {forceSceneResult?.status === 'error' && (
              <span className="badge badge-red" title={forceSceneResult.reason}>
                fire failed: {forceSceneResult.reason}
              </span>
            )}
          </>
        )}
      >
        <span className="top-bar-group-btn-label">Scenes</span>
        <span className="top-bar-group-btn-value">
          {SCENE_CHANGE_MODES.find((m) => m.value === local.scene_change_mode)?.label ?? local.scene_change_mode}
        </span>
        {local.force_scene_enabled && <span className="top-bar-group-btn-dot top-bar-group-btn-dot-purple" title="Force Scene is on" />}
      </TopBarGroupButton>

      {/* FORCE COLOUR (owner ask 2026-08-27) — the deliberately MINIMAL
        * functional control he asked for: a picker and an on/off, in the
        * top bar, nothing pretty ("focus on fucntion and we will work on
        * UI later"). Its own group button rather than a row inside
        * Scenes: it pins COLOUR, not scenes, and the two pins are
        * independent (either, both, or neither). */}
      <TopBarGroupButton
        className={`scenes-group-btn${local.force_color_enabled ? ' scenes-group-btn-forced' : ''}`}
        title="Force Colour — pin the room's colour set or group, tap to open"
        holdToExpand={false}
        panelTitle="Colour"
        panel={(
          <>
            <div className="top-bar-group-field">
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                <input
                  type="checkbox"
                  checked={local.force_color_enabled}
                  onChange={(e) => commit({ ...local, force_color_enabled: e.target.checked })}
                />
                Force Colour
              </label>
              <HelpLink topic="force-color" />
            </div>
            {local.force_color_enabled && (
              <div className="top-bar-group-field">
                <SearchSelect value={local.force_color_target_id ?? ''} options={colorTargetOptions}
                  width={180} placeholder="— pick colour set —" allowEmpty={false}
                  onChange={(v) => commit({ ...local, force_color_target_id: v })} />
              </div>
            )}
            {forceColorResult?.status === 'applied' && (
              <span className="badge badge-gray"
                title="Applied immediately on this pin — not waiting for the next automatic colour change">
                applied: {forceColorResult.applied_set_name ?? forceColorResult.target_name}
                {forceColorResult.target_kind === 'group'
                  && ` (from ${forceColorResult.target_name})`}
              </span>
            )}
            {forceColorResult?.status === 'applied' && forceColorResult.overrode_disabled && (
              <span className="badge badge-red"
                title="This colour set is marked Disabled on the Colours page — the pin still applied it, since you pressed the button, but it won't be picked automatically again while disabled">
                ⚠ overriding disabled colour set
              </span>
            )}
            {forceColorResult?.status === 'skipped' && (
              <span className="badge badge-red" title="Force Colour did not apply — nothing changed">
                not applied: {forceColorResult.reason}
              </span>
            )}
            {forceColorResult?.status === 'error' && (
              <span className="badge badge-red" title={forceColorResult.reason}>
                apply failed: {forceColorResult.reason}
              </span>
            )}
            {local.force_color_enabled && local.active_gradient_id && (
              <span className="badge badge-gray"
                title="Force Colour outranks an active drift gradient while it's on — the gradient is untouched and resumes the moment you release the pin">
                gradient paused by the pin
              </span>
            )}
          </>
        )}
      >
        <span className="top-bar-group-btn-label">Colour</span>
        <span className="top-bar-group-btn-value">
          {local.force_color_enabled
            ? (colorTargetOptions.find((o) => o.value === local.force_color_target_id)?.label
               ?? 'none picked')
            : 'free'}
        </span>
        {local.force_color_enabled && <span className="top-bar-group-btn-dot top-bar-group-btn-dot-purple" title="Force Colour is on" />}
      </TopBarGroupButton>

      <DriftGradientBar />

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

      <HelpLink topic="room-controls-bar" />
    </div>
  );
}
