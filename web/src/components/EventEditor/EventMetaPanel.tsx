import type { MusicEvent } from '../../types/events';
import { DISPLAY_MODE_OPTIONS } from '../../types/events';
import { useEditorStore } from '../../store/editorStore';
import { Checkbox, ColorInput, LabelsInput, NumberInput, Row, Select, TextInput } from '../forms/inputs';
import HelpLink from '../../help/HelpLink';

export default function EventMetaPanel({ event }: { event: MusicEvent }) {
  const mutate = useEditorStore((s) => s.mutate);
  const set = (fn: (d: MusicEvent) => void) => mutate(fn);

  return (
    <div className="card">
      <div className="card-title">Event settings</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '0 24px' }}>
        <div>
          <Row label="Name">
            <TextInput value={event.name} onChange={(v) => set((d) => { d.name = v; })} />
          </Row>
          <Row label="Timeline color">
            <ColorInput value={event.color} onChange={(v) => set((d) => { d.color = v ?? '#FFD700'; })} />
          </Row>
          <Row label="Labels">
            <LabelsInput value={event.labels} onChange={(v) => set((d) => { d.labels = v; })} />
          </Row>
          <Row label="Energy (1–10)" help="Blank = energy-agnostic">
            <NumberInput value={event.energy_level} nullable min={1} max={10} step={1}
              onChange={(v) => set((d) => { d.energy_level = v == null ? null : Math.max(1, Math.min(10, Math.round(v))); })} />
          </Row>
          <Row label="Fire offset (ms)" help="Negative fires earlier, positive later">
            <NumberInput value={event.event_offset_ms} step={10}
              onChange={(v) => set((d) => { d.event_offset_ms = v ?? 0; })} />
          </Row>
        </div>
        <div>
          <Row label="Flags">
            <span style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              <Checkbox value={event.ai_exposed} label="AI exposed"
                onChange={(v) => set((d) => { d.ai_exposed = v; })} />
              {/* Scene override only applies to a stored single/morph_set body,
                  so it's meaningless on a built-in. */}
              {!event.fixed && (
                <Checkbox value={event.scene_override} label="Scene override"
                  onChange={(v) => set((d) => { d.scene_override = v; })} />
              )}
            </span>
          </Row>
          {event.event_type === 'scene_update' && (
            <Row label="Mode 🌗"
              help="Dark/Light mode while this scene is current. Default defers to the Set Color / color card levels; TopBar, trigger and scene group outrank it.">
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <Select value={event.display_mode ?? 'default'} width={160}
                  onChange={(v) => set((d) => { d.display_mode = v as MusicEvent['display_mode']; })}
                  options={DISPLAY_MODE_OPTIONS} />
                <HelpLink topic="display-modes" title="Dark / Light mode" />
              </span>
            </Row>
          )}
        </div>
      </div>
    </div>
  );
}
