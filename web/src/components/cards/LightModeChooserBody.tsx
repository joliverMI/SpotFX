import type { Action, IntensityChooserAction, IntensityLane } from '../../types/events';
import { newIntensityLane } from '../../lib/defaults';
import { uuid } from '../../lib/uid';
import { useEditorStore } from '../../store/editorStore';
import { cloneForPaste, useClipboard, writeClip } from '../../store/clipboard';
import { LabelsInput, Select, TextInput } from '../forms/inputs';
import { ParentScopeToggle } from '../forms/ScopePicker';
import RampOverride from '../forms/RampOverride';
import EditableActionContainer from '../tracks/EditableActionContainer';
import { groupPathOf } from './groupPath';
import PreviewButton from '../PreviewButton';
import { previewIntensityLane } from '../../lib/preview';
import HelpLink from '../../help/HelpLink';

const MODE_TAG: Record<string, string> = { dark: '🌙 Dark', light: '☀️ Light' };

/** Expanded body of a Light Mode Chooser (intensity_chooser with source
 * 'display_mode'): the resolved Dark/Light mode — Now Playing 🌗 toggle, then
 * trigger, active scene group, current scene — picks the first lane whose
 * mode matches. "Default" resolution runs the `default_mode` lane. */
export default function LightModeChooserBody({ uid, action }: { uid: string; action: IntensityChooserAction }) {
  const draft = useEditorStore((s) => s.draft);
  const updateAction = useEditorStore((s) => s.updateAction);
  const clip = useClipboard();
  if (!draft) return null;
  const groupPath = groupPathOf(draft, uid);
  if (!groupPath) return null;

  const set = (fn: (g: IntensityChooserAction) => void) =>
    updateAction(uid, (a) => { if (a.type === 'intensity_chooser') fn(a); });

  const laneLabel = (lane: IntensityLane, j: number) =>
    lane.name || MODE_TAG[lane.mode ?? ''] || `Lane ${j + 1}`;

  return (
    <div style={{ marginBottom: 10 }}>
      <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 8 }}>
        The room’s Dark/Light mode (Now Playing 🌗 → trigger → scene group → scene)
        picks ONE lane — re-checked at fire time. When nothing forces a mode, the
        default lane below runs.
        <HelpLink topic="light-mode-chooser" />
      </p>

      <label style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '0 6px 12px', fontSize: 13 }}
        title="Which lane runs while the resolved mode is Default (nothing in the cascade forces dark or light)">
        <span style={{ color: 'var(--text-muted)' }}>When mode is Default, run</span>
        <Select value={action.default_mode ?? 'light'} width={130}
          onChange={(v) => set((g) => { g.default_mode = v as 'dark' | 'light'; })}
          options={[
            { value: 'light', label: '☀️ Light lane' },
            { value: 'dark', label: '🌙 Dark lane' },
          ]} />
      </label>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '0 6px 12px', fontSize: 13 }}>
        <span style={{ color: 'var(--text-muted)' }}
          title="Override forces this ramp on everything the chosen lane fires — through scene groups and scenes. ⚡ can map it to trigger intensity, 🎲 rolls it per fire. Scene / scene-group overrides win over this one.">
          Ramp
        </span>
        <RampOverride value={action.ramp_ms} onChange={(v) => set((g) => { g.ramp_ms = v; })} />
      </div>

      {action.lanes.map((lane, j) => (
        <div key={lane.id} className="action-card" style={{ padding: 10, marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
            <Select value={lane.mode ?? 'light'} width={110}
              onChange={(v) => set((g) => {
                const l = g.lanes.find((x) => x.id === lane.id);
                if (l) l.mode = v as 'dark' | 'light';
              })}
              options={[
                { value: 'light', label: '☀️ Light' },
                { value: 'dark', label: '🌙 Dark' },
              ]} />
            <TextInput value={lane.name} placeholder="lane name (optional)" width={150}
              onChange={(v) => set((g) => { const l = g.lanes.find((x) => x.id === lane.id); if (l) l.name = v; })} />
            {(action.default_mode ?? 'light') === lane.mode
              && action.lanes.findIndex((l) => l.mode === lane.mode) === j && (
              <span className="chip" title="Runs when nothing forces dark or light">default</span>
            )}
            <span style={{ flex: 1 }} />
            <button title="Copy lane" style={{ padding: '2px 7px', fontSize: 12 }}
              onClick={() => writeClip('intensity_lane', lane, `lane “${laneLabel(lane, j)}” · ${lane.actions.length} actions`)}>📋</button>
            <button title="Duplicate lane" style={{ padding: '2px 7px', fontSize: 12 }}
              onClick={() => set((g) => {
                const clone = JSON.parse(JSON.stringify(lane, (k, v) => (k.startsWith('_') ? undefined : v))) as IntensityLane;
                clone.id = uuid();
                g.lanes.push(clone);
              })}>⧉</button>
            <PreviewButton title="Preview — fire this lane now (mode ignored)"
              run={() => previewIntensityLane(action, lane)} />
            <button className="danger" disabled={action.lanes.length === 1}
              title="Delete lane" style={{ padding: '2px 7px', fontSize: 12 }}
              onClick={() => set((g) => {
                const i = g.lanes.findIndex((x) => x.id === lane.id);
                if (i >= 0) g.lanes.splice(i, 1);
              })}>✕</button>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }} title="Device/category this lane targets (empty leaf scopes adopt it)">target</span>
            <ParentScopeToggle scope={lane.scope} onChange={(s) => set((g) => { const l = g.lanes.find((x) => x.id === lane.id); if (l) l.scope = s; })} />
          </div>
          <div style={{ marginBottom: 6 }}>
            <LabelsInput value={lane.labels} placeholder="lane filter labels (merge with trigger labels)"
              onChange={(v) => set((g) => { const l = g.lanes.find((x) => x.id === lane.id); if (l) l.labels = v; })} />
          </div>
          <div style={{ marginLeft: 12 }}>
            <EditableActionContainer
              containerPath={`${groupPath}.lanes.${j}.actions`}
              actions={lane.actions}
              emptyNote="No actions — this lane fires nothing."
            />
          </div>
        </div>
      ))}
      <button style={{ fontSize: 12 }} onClick={() => set((g) => {
        const missing = (['light', 'dark'] as const).find((m) => !g.lanes.some((l) => l.mode === m));
        g.lanes.push({ ...newIntensityLane(0), mode: missing ?? 'dark' });
      })}>+ Add lane</button>
      {(clip?.kind === 'intensity_lane' || clip?.kind === 'action') && (
        <button style={{ fontSize: 12, marginLeft: 6 }} title={`Paste “${clip.summary}”`}
          onClick={() => set((g) => {
            if (clip.kind === 'intensity_lane') {
              const pasted = cloneForPaste(clip.data as IntensityLane);
              pasted.mode = pasted.mode ?? 'dark';
              g.lanes.push(pasted);
            } else {
              const l = { ...newIntensityLane(0), mode: 'dark' as const };
              l.actions.push(cloneForPaste(clip.data as Action));
              g.lanes.push(l);
            }
          })}>
          📋 Paste lane
        </button>
      )}
    </div>
  );
}
