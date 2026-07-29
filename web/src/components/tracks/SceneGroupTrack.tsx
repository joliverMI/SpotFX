import { Link } from 'react-router-dom';
import type { MusicEvent } from '../../types/events';
import { useColorSets, useEvents } from '../../api/queries';
import { useEditorStore } from '../../store/editorStore';
import { Checkbox, NumberInput, Select } from '../forms/inputs';
import SearchSelect from '../forms/SearchSelect';
import HelpLink from '../../help/HelpLink';
import PreviewButton from '../PreviewButton';
import { previewAction } from '../../lib/preview';

/** Editor body for event_type "scene_group": member Scene Updates + selection
 * behavior. Mirrors the Color Group editor (mode / cycle behaviour / exclude
 * current + ordered, weighted members) but writes to the event draft. */
export default function SceneGroupTrack({ event }: { event: MusicEvent }) {
  const mutate = useEditorStore((s) => s.mutate);
  const { data: events } = useEvents();
  const { data: colorSets } = useColorSets();

  const colorGroupOptions = (colorSets ?? [])
    .filter((c) => c.kind === 'group')
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((c) => ({ value: c.id, label: c.name }));

  const sceneOptions = (events ?? [])
    .filter((e) => e.event_type === 'scene_update')
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((e) => ({ value: e.id, label: e.name, keywords: e.labels.join(' ') }));

  const members = event.scene_group_members;
  const weighted = event.scene_group_mode === 'weighted';

  return (
    <div className="track">
      <div className="track-header">
        <span>🎬</span>
        <span>Scene Group — fires one member scene per pick</span>
        <HelpLink topic="events-scene-groups" />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 12, flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
          <span style={{ color: 'var(--text-muted)' }}>mode</span>
          <Select value={event.scene_group_mode} width={170}
            onChange={(v) => mutate((d) => { d.scene_group_mode = v as MusicEvent['scene_group_mode']; })}
            options={[
              { value: 'cycle', label: 'Cycle (sequential)' },
              { value: 'weighted', label: 'Weighted (random)' },
            ]} />
        </label>
        {!weighted && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
            <span style={{ color: 'var(--text-muted)' }}>cycle behaviour</span>
            <Select value={event.scene_group_cycle_behavior} width={110}
              onChange={(v) => mutate((d) => { d.scene_group_cycle_behavior = v as MusicEvent['scene_group_cycle_behavior']; })}
              options={[
                { value: 'wrap', label: 'wrap' },
                { value: 'bounce', label: 'bounce' },
              ]} />
          </label>
        )}
        {weighted && (
          <Checkbox value={event.scene_group_exclude_current} label="exclude current from next"
            onChange={(v) => mutate((d) => { d.scene_group_exclude_current = v; })} />
        )}
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}
          title="Color Group this scene group designates — Set Color actions set to “Scene Group's Color Group” pull from it while this group is active">
          <span style={{ color: 'var(--text-muted)' }}>color group</span>
          <SearchSelect value={event.scene_group_color_ref_id} width={200}
            onChange={(v) => mutate((d) => { d.scene_group_color_ref_id = v; })}
            options={colorGroupOptions} placeholder="— none —" />
          {event.scene_group_color_ref_id && (
            <Link to={`/color-sets?id=${encodeURIComponent(event.scene_group_color_ref_id)}`} target="_blank"
              title="Open this Color Group in a new tab" style={{ fontSize: 13, textDecoration: 'none' }}>↗</Link>
          )}
        </label>
      </div>

      {members.map((m, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
          <span className="step-badge">{i + 1}</span>
          <SearchSelect value={m.event_id} width={260}
            onChange={(v) => mutate((d) => { d.scene_group_members[i].event_id = v; })}
            options={sceneOptions} placeholder="— pick a Scene Update —" allowEmpty={false} />
          {m.event_id && (
            <Link to={`/event/${m.event_id}`} target="_blank" title="Open this scene in a new tab"
              style={{ fontSize: 13, textDecoration: 'none' }}>↗</Link>
          )}
          {weighted && (
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
              <span style={{ color: 'var(--text-muted)' }}>weight</span>
              <NumberInput value={m.weight} min={0} step={0.1} width={70}
                onChange={(v) => mutate((d) => { d.scene_group_members[i].weight = v ?? 1; })} />
            </label>
          )}
          <span style={{ flex: 1 }} />
          <button title="Move up" disabled={i === 0} style={{ padding: '2px 7px', fontSize: 12 }}
            onClick={() => mutate((d) => {
              const [x] = d.scene_group_members.splice(i, 1);
              d.scene_group_members.splice(i - 1, 0, x);
            })}>↑</button>
          <button title="Move down" disabled={i === members.length - 1} style={{ padding: '2px 7px', fontSize: 12 }}
            onClick={() => mutate((d) => {
              const [x] = d.scene_group_members.splice(i, 1);
              d.scene_group_members.splice(i + 1, 0, x);
            })}>↓</button>
          {m.event_id && (
            <PreviewButton title="Preview — fire this member scene now"
              run={() => previewAction({ type: 'event_ref', event_id: m.event_id, labels: [], weight: 1 })} />
          )}
          <button className="danger" title="Remove member" style={{ padding: '2px 7px', fontSize: 12 }}
            onClick={() => mutate((d) => { d.scene_group_members.splice(i, 1); })}>✕</button>
        </div>
      ))}

      {!members.length && (
        <p className="empty-note">No members yet — add the Scene Updates this group rotates through.</p>
      )}

      <button style={{ fontSize: 12 }} onClick={() => mutate((d) => {
        d.scene_group_members.push({ event_id: '', weight: 1 });
      })}>
        + Member
      </button>
      <p className="empty-note" style={{ marginTop: 8 }}>
        Order matters for cycle mode; weights matter for weighted mode. Firing
        the group (or any scene pick while Force Scene holds it) advances one
        member and runs its normal First/Rest lanes.
      </p>
    </div>
  );
}
