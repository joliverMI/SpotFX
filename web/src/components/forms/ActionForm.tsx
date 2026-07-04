/** Per-type form dispatcher + the light-weight forms. Every form gets the action
 * and an `update` that mutates it inside the editor store (immer recipe). */
import type { Action } from '../../types/events';
import { useColorSets, useEvents, useScenes } from '../../api/queries';
import { LabelsInput, NumberInput, Row, Select, ColorInput, TextInput, Checkbox } from './inputs';
import SearchSelect from './SearchSelect';
import EffectParamForm from './EffectParamForm';
import MorphStepForm from './MorphStepForm';
import DeviceSettingsForm from './DeviceSettingsForm';
import JsonEditor from './JsonEditor';

export type UpdateAction = (fn: (a: Action) => void) => void;

export default function ActionForm({ action, update }: { action: Action; update: UpdateAction }) {
  return (
    <div>
      <TypedForm action={action} update={update} />
      <Row label="Filter labels" help="Trigger labels must match; '-x' excludes">
        <LabelsInput value={action.labels} onChange={(v) => update((a) => { a.labels = v; })} />
      </Row>
      <Row label="Weight" help="Weighted-random pick weight within a pool">
        <NumberInput value={action.weight} min={0} step={0.1} onChange={(v) => update((a) => { a.weight = v ?? 1; })} />
      </Row>
      <div style={{ marginTop: 6 }}>
        <JsonEditor action={action} onApply={(parsed) => update((a) => Object.assign(a, parsed))} />
      </div>
    </div>
  );
}

function TypedForm({ action, update }: { action: Action; update: UpdateAction }) {
  switch (action.type) {
    case 'event_ref':
      return <EventRefForm action={action} update={update} />;
    case 'ledfx_scene':
      return <SceneForm action={action} update={update} />;
    case 'ledfx_ambient':
      return <AmbientForm action={action} update={update} />;
    case 'ledfx_ambient_color':
      return <p className="empty-note">Applies the complementary of the current ambient color. No parameters.</p>;
    case 'ledfx_global_brightness':
      return (
        <>
          <Row label="Brightness">
            <NumberInput value={action.brightness} min={0} max={1} step={0.05}
              onChange={(v) => update((a) => { if (a.type === 'ledfx_global_brightness') a.brightness = v ?? 1; })} />
          </Row>
          <Row label="Ramp (ms)" help="Blank = settings default, 0 = instant">
            <NumberInput value={action.ramp_ms} nullable
              onChange={(v) => update((a) => { if (a.type === 'ledfx_global_brightness') a.ramp_ms = v; })} />
          </Row>
        </>
      );
    case 'ledfx_global_transition':
      return (
        <>
          <Row label="Transition (s)">
            <NumberInput value={action.transition_time} min={0} step={0.1}
              onChange={(v) => update((a) => { if (a.type === 'ledfx_global_transition') a.transition_time = v ?? 0.5; })} />
          </Row>
          <Row label="Mode">
            <TextInput value={action.transition_mode ?? ''} placeholder="e.g. Add, Dissolve (blank = keep)"
              onChange={(v) => update((a) => { if (a.type === 'ledfx_global_transition') a.transition_mode = v || null; })} />
          </Row>
        </>
      );
    case 'ledfx_effect_param':
      return <EffectParamForm action={action} update={update as never} />;
    case 'morph_step':
      return <MorphStepForm action={action} update={update as never} />;
    case 'morph_color':
      return <MorphColorForm action={action} update={update} />;
    case 'device_settings':
      return <DeviceSettingsForm action={action} update={update as never} />;
    case 'random_group':
    case 'sequence_group':
    case 'parallel_group':
      return null; // container bodies render above (RandomGroup/SequenceGroup/ParallelGroupBody)
  }
}

function EventRefForm({ action, update }: { action: Extract<Action, { type: 'event_ref' }>; update: UpdateAction }) {
  const { data: events } = useEvents();
  const opts = (events ?? [])
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((e) => ({ value: e.id, label: e.name }));
  return (
    <Row label="Event">
      <SearchSelect value={action.event_id} width={280}
        onChange={(v) => update((a) => { if (a.type === 'event_ref') a.event_id = v; })}
        options={opts} placeholder="— pick an event —" />
    </Row>
  );
}

function SceneForm({ action, update }: { action: Extract<Action, { type: 'ledfx_scene' }>; update: UpdateAction }) {
  const { data: scenes } = useScenes();
  const opts = (scenes ?? []).map((s) => ({ value: s.id, label: s.name }));
  return (
    <Row label="Scene">
      <SearchSelect value={action.scene_id} width={280}
        onChange={(v) => update((a) => { if (a.type === 'ledfx_scene') a.scene_id = v; })}
        options={opts} placeholder="— pick a scene —" />
    </Row>
  );
}

function AmbientForm({ action, update }: { action: Extract<Action, { type: 'ledfx_ambient' }>; update: UpdateAction }) {
  const set = (fn: (a: Extract<Action, { type: 'ledfx_ambient' }>) => void) =>
    update((a) => { if (a.type === 'ledfx_ambient') fn(a); });
  return (
    <>
      <Row label="Color" help="Sets gradient + background + sparks together">
        <ColorInput value={action.color} nullable onChange={(v) => set((a) => { a.color = v; })} />
      </Row>
      <Row label="Brightness"><NumberInput value={action.brightness} nullable min={0} max={1} step={0.05} onChange={(v) => set((a) => { a.brightness = v; })} /></Row>
      <Row label="Max brightness"><NumberInput value={action.max_brightness} nullable min={0} max={1} step={0.05} onChange={(v) => set((a) => { a.max_brightness = v; })} /></Row>
      <Row label="Blur"><NumberInput value={action.blur} nullable min={0} onChange={(v) => set((a) => { a.blur = v; })} /></Row>
      <Row label="Bass decay"><NumberInput value={action.bass_decay_rate} nullable min={0} onChange={(v) => set((a) => { a.bass_decay_rate = v; })} /></Row>
      <Row label="BG brightness"><NumberInput value={action.background_brightness} nullable min={0} max={1} step={0.05} onChange={(v) => set((a) => { a.background_brightness = v; })} /></Row>
    </>
  );
}

function MorphColorForm({ action, update }: { action: Extract<Action, { type: 'morph_color' }>; update: UpdateAction }) {
  const { data: colorSets } = useColorSets();
  const set = (fn: (a: Extract<Action, { type: 'morph_color' }>) => void) =>
    update((a) => { if (a.type === 'morph_color') fn(a); });
  const opts = (colorSets ?? []).map((c) => ({ value: c.id, label: `${c.name}${c.kind === 'group' ? ' (group)' : ''}` }));
  return (
    <>
      <Row label="Color set / group">
        <SearchSelect value={action.ref_id} width={280} onChange={(v) => set((a) => { a.ref_id = v; })}
          options={opts} placeholder="— pick a color set —" />
      </Row>
      <Row label="Pick mode">
        <Select value={action.pick_mode} width={140}
          onChange={(v) => set((a) => { a.pick_mode = v as typeof a.pick_mode; })}
          options={['default', 'cycle', 'weighted'].map((v) => ({ value: v, label: v }))} />
      </Row>
      {action.pick_mode === 'cycle' && (
        <>
          <Row label="Advance" help="Members to move per fire"><NumberInput value={action.advance} min={1} step={1} onChange={(v) => set((a) => { a.advance = Math.max(1, Math.round(v ?? 1)); })} /></Row>
          <Row label="Direction">
            <Select value={action.direction} width={140}
              onChange={(v) => set((a) => { a.direction = v as typeof a.direction; })}
              options={['forward', 'backward'].map((v) => ({ value: v, label: v }))} />
          </Row>
        </>
      )}
      <Row label="Ramp (ms)"><NumberInput value={action.ramp_ms} nullable onChange={(v) => set((a) => { a.ramp_ms = v; })} /></Row>
      <Row label="Preserve effect" help="Skip values that would reset the running LedFX effect">
        <Checkbox value={action.preserve_effect} onChange={(v) => set((a) => { a.preserve_effect = v; })} />
      </Row>
    </>
  );
}
