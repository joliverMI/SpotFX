/** SPECTRA-native trigger edit dialog: timestamp, action kind + target +
 * intensity, a quick-pick row of recently used actions, enabled toggle.
 * Owns its own save/delete mutations (SpectraTriggersCard just holds which
 * trigger is being edited). Mirrors TriggerDialog.tsx's layout/save-close
 * conventions, typed for SpectraTrigger — a separate authoring surface from
 * the legacy dialog (CLAUDE.md: two worlds coexist during migration). */
import { useEffect, useState } from 'react';
import HelpLink from '../../help/HelpLink';
import SearchSelect from '../../components/forms/SearchSelect';
import { fmtMsTenths, parseMsTenths } from '../../lib/time';
import { readSticky, writeSticky } from '../../lib/useSticky';
import { useDeleteSpectraTrigger, useSaveSpectraTrigger, useScenes, useSpotColorSets } from '../../queries';
import { RESPONSE_CLASSES } from '../../types';
import type { ResponseClass, SpectraTrigger, TriggerAction, TriggerActionKind } from '../../types';
import { actionSummary } from './SpectraTriggerBar';

const KIND_LABEL: Record<TriggerActionKind, string> = {
  fire_scene: 'Fire Scene', fire_response: 'Fire Response', select_color_set: 'Select Colours',
  fire_scene_update: 'Fire Update',
};

const blankAction = (kind: TriggerActionKind, carryIntensity: number): TriggerAction => {
  // scene_id null = "pick at fire time through the sequencer selection kernel"
  // (front 3's generation-friendly default) — a legal, un-forced choice.
  if (kind === 'fire_scene') return { kind, scene_id: null, intensity: carryIntensity, color_set_id: null };
  if (kind === 'fire_response') return { kind, event_class: 'flare', intensity: carryIntensity };
  if (kind === 'fire_scene_update') return { kind, intensity: carryIntensity };
  return { kind, set_id: '' };
};

interface RecentAction {
  kind: TriggerActionKind;
  scene_id?: string;
  event_class?: ResponseClass;
  set_id?: string;
  label: string;
}

const intensityOf = (a: TriggerAction) => (a.kind === 'select_color_set' ? 0.5 : a.intensity);

export default function SpectraTriggerDialog({
  trigger,
  isNew,
  uri,
  onClose,
}: {
  trigger: SpectraTrigger | null;
  isNew: boolean;
  uri: string | null;
  onClose: () => void;
}) {
  const { data: scenes } = useScenes();
  const { data: colorSets } = useSpotColorSets();
  const save = useSaveSpectraTrigger(uri);
  const del = useDeleteSpectraTrigger(uri);

  const [tsText, setTsText] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [action, setAction] = useState<TriggerAction>(blankAction('fire_scene', 0.5));

  useEffect(() => {
    if (!trigger) return;
    setTsText(fmtMsTenths(trigger.timestamp_ms));
    setEnabled(trigger.enabled);
    setAction(trigger.action);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trigger?.id]);

  if (!trigger) return null;

  const sceneName = (id: string) => scenes?.find((s) => s.id === id)?.name ?? id;
  const sets = (colorSets ?? []).filter((c) => c.kind === 'set');
  const recents = readSticky<RecentAction[]>('recentSpectraActions', []);

  const valid =
    action.kind === 'fire_scene' ||   // scene_id null = kernel-routed, always valid
    action.kind === 'fire_scene_update' ||   // no target field to be missing — always valid
    (action.kind === 'fire_response' && !!action.event_class) ||
    (action.kind === 'select_color_set' && !!action.set_id);
  const ms = parseMsTenths(tsText);

  const close = onClose;

  const doSave = () => {
    if (ms === null || !valid) return;
    const saved: SpectraTrigger = { ...trigger, timestamp_ms: ms, enabled, action };
    save.mutate(saved);
    const label = actionSummary(saved, sceneName);
    const entry: RecentAction = {
      kind: action.kind, label,
      ...(action.kind === 'fire_scene' && action.scene_id
        ? { scene_id: action.scene_id } : {}),
      ...(action.kind === 'fire_response' ? { event_class: action.event_class } : {}),
      ...(action.kind === 'select_color_set' ? { set_id: action.set_id } : {}),
    };
    writeSticky('recentSpectraActions',
      [entry, ...recents.filter((r) => r.label !== label)].slice(0, 5));
    close();
  };

  const doDelete = () => {
    if (!isNew) del.mutate(trigger.id);
    close();
  };

  const applyRecent = (r: RecentAction) => {
    const carry = intensityOf(action);
    if (r.kind === 'fire_scene') setAction({ kind: 'fire_scene', scene_id: r.scene_id ?? null, intensity: carry, color_set_id: null });
    else if (r.kind === 'fire_response') setAction({ kind: 'fire_response', event_class: r.event_class ?? 'flare', intensity: carry });
    else if (r.kind === 'fire_scene_update') setAction({ kind: 'fire_scene_update', intensity: carry });
    else setAction({ kind: 'select_color_set', set_id: r.set_id ?? '' });
  };

  return (
    <div onClick={close}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100,
               display: 'flex', alignItems: 'flex-start', justifyContent: 'center', paddingTop: '14vh' }}>
      <div className="card" onClick={(e) => e.stopPropagation()}
        style={{ width: 440, maxWidth: '92vw', margin: 0 }}>
        <div className="card-title">
          {isNew ? 'New SPECTRA Trigger' : 'Edit SPECTRA Trigger'}{' '}
          <HelpLink topic="spectra-triggers" title="SPECTRA-native triggers" />
        </div>

        {recents.length > 0 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
            {recents.map((r, i) => (
              <button key={i} style={{ fontSize: 11, padding: '2px 8px' }}
                title="Quick-pick a recently used action" onClick={() => applyRecent(r)}>
                {r.label}
              </button>
            ))}
          </div>
        )}

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, fontSize: 13 }}>
          <span style={{ width: 90, color: 'var(--text-muted)' }}>Timestamp</span>
          <input type="text" value={tsText} onChange={(e) => setTsText(e.target.value)}
            placeholder="m:ss.t" style={{ width: 110 }} />
        </label>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, fontSize: 13 }}>
          <span style={{ width: 90, color: 'var(--text-muted)' }}>Action</span>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {(['fire_scene', 'fire_response', 'fire_scene_update', 'select_color_set'] as TriggerActionKind[]).map((k) => (
              <button key={k} className={action.kind === k ? 'primary' : ''}
                style={{ fontSize: 12 }}
                onClick={() => setAction(blankAction(k, intensityOf(action)))}>
                {KIND_LABEL[k]}
              </button>
            ))}
          </div>
        </div>

        {action.kind === 'fire_scene' && (
          <>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, fontSize: 13 }}
              title="Blank = pick a scene at fire time through the sequencer selection kernel (curve × genre × affinity), instead of a fixed scene.">
              <span style={{ width: 90, color: 'var(--text-muted)' }}>Scene</span>
              <SearchSelect value={action.scene_id ?? ''}
                onChange={(v) => setAction({ ...action, scene_id: v || null })}
                options={(scenes ?? []).map((s) => ({ value: s.id, label: s.name }))}
                placeholder="— sequencer picks at fire time —" width={260} allowEmpty />
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, fontSize: 13 }}
              title="Fire wearing THIS colour set instead of the room's active one. Blank = the room's active set.">
              <span style={{ width: 90, color: 'var(--text-muted)' }}>Colours</span>
              <SearchSelect value={action.color_set_id ?? ''}
                onChange={(v) => setAction({ ...action, color_set_id: v || null })}
                options={sets.map((c) => ({ value: c.id, label: c.name }))}
                placeholder="— room's active set —" width={260} allowEmpty />
            </label>
          </>
        )}

        {action.kind === 'fire_response' && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, fontSize: 13 }}
            title="Which response class fires — the same phase drive and band selection a bridge-classified charge/lull/drop/flare already drives.">
            <span style={{ width: 90, color: 'var(--text-muted)' }}>Class</span>
            <select value={action.event_class}
              onChange={(e) => setAction({ ...action, event_class: e.target.value as ResponseClass })}
              style={{ width: 140 }}>
              {RESPONSE_CLASSES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <HelpLink topic="charge-lull-drop" title="Charge / Lull / Drop / Flare" />
          </label>
        )}

        {action.kind === 'fire_scene_update' && (
          <div style={{ marginBottom: 8, fontSize: 12, color: 'var(--text-muted)' }}>
            Fires the ACTIVE scene's own UPDATE content directly — no
            target to pick here. If that scene has no update authored
            yet, this is a silent no-op. <HelpLink topic="spectra-trigger-actions" title="Fire Update" />
          </div>
        )}

        {action.kind === 'select_color_set' && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, fontSize: 13 }}>
            <span style={{ width: 90, color: 'var(--text-muted)' }}>Colours</span>
            <SearchSelect value={action.set_id}
              onChange={(v) => setAction({ ...action, set_id: v })}
              options={sets.map((c) => ({ value: c.id, label: c.name }))}
              placeholder="— pick a colour set —" width={260} allowEmpty={false} />
          </label>
        )}

        {action.kind !== 'select_color_set' && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, fontSize: 13 }}
            title="Fire intensity (0–1) — passed straight through to the action (bindings, response bands).">
            <span style={{ width: 90, color: 'var(--text-muted)' }}>Intensity ⚡</span>
            <input type="range" min={0} max={1} step={0.01} value={action.intensity}
              onChange={(e) => setAction({ ...action, intensity: Number(e.target.value) })}
              style={{ flex: 1 }} />
            <input type="number" min={0} max={1} step={0.01} value={action.intensity}
              onChange={(e) => setAction({ ...action, intensity: Math.max(0, Math.min(1, Number(e.target.value))) })}
              style={{ width: 70, background: 'var(--bg)', color: 'var(--text)',
                       border: '1px solid var(--border)', borderRadius: 6, padding: '5px 8px' }} />
          </label>
        )}

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, fontSize: 13 }}>
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          <span style={{ color: 'var(--text-muted)' }}>Enabled</span>
        </label>

        <div style={{ display: 'flex', gap: 8 }}>
          <button className="primary" onClick={doSave} disabled={!valid || ms === null}>
            Save
          </button>
          {!isNew && <button className="danger" onClick={doDelete}>Delete</button>}
          <span style={{ flex: 1 }} />
          <button onClick={close}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
