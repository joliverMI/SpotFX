/** THE LIGHT SHOW (/show) — phase 1: the Build view.
 *
 * His named sets of actions, edited here and fired NOW from a button. The
 * form for every step is rendered from the SERVED catalogue
 * (GET /api/light-show/catalogue): each action kind declares its own
 * parameters, so a new kind — including any future room effect — appears
 * here with no change to this page.
 *
 * What a fire does is the server's business (spectra/services/
 * show_actions.py); this page shows the outcome of EVERY step, so a set
 * that only partly ran says which step did not and why. End show puts the
 * room back. Nothing here takes or releases the room: when SPECTRA does
 * not own it, or a preview / camera run / night run holds it, the banner
 * says so and Fire is refused by the server with that same reason.
 *
 * Phase 2 adds ARMING: a set waits for the next scene change or this
 * song's High / Low Trigger (ArmBoard.tsx). Phase 3 adds a tap-mode
 * selector between this editing surface (Build) and RunView.tsx, the
 * phone-first surface for standing in the room: a big armed board,
 * per-arm Disarm, the Holding list, Disarm all and End show, with no
 * editing. Both read the same polled status/arms — one source of truth
 * for the countdowns, never two. */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiDel, apiGet, apiPost } from '../api/client';
import HelpLink from '../help/HelpLink';
import { useToast } from '../components/Toast';
import SonicChatPopover from '../components/SonicChatPopover';
import useIsPhone from '../lib/useIsPhone';
import { useAmbientHueGroups, useGradient2dProfiles, useScenes, useSpotColorSets } from '../queries';
import { ArmBoard, ArmControl } from './ArmBoard';
import RunView from './RunView';
import { endShowSummary, runSummary } from './showSummary';
import type {
  ArmsStatus, EndShowReport, ShowAction, ShowCatalogue, ShowKind, ShowParam, ShowRun, ShowSet,
  ShowStatus, ShowTargets,
} from './types';

const NEW_ID = '__new__';

function defaultsFor(kind: ShowKind): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const p of kind.params) {
    if (p.default !== null && p.default !== undefined) out[p.name] = p.default;
    else if (p.type === 'target') out[p.name] = { kind: 'everything', id: null };
  }
  return out;
}

function newId() {
  return Math.random().toString(16).slice(2, 14);
}

export default function LightShowPage() {
  const toast = useToast();
  const isPhone = useIsPhone();
  const [mode, setMode] = useState<'build' | 'run'>(() => (window.matchMedia('(max-width: 720px)').matches ? 'run' : 'build'));
  const [catalogue, setCatalogue] = useState<ShowCatalogue | null>(null);
  const [targets, setTargets] = useState<ShowTargets | null>(null);
  const [sets, setSets] = useState<ShowSet[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<ShowSet | null>(null);
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState<ShowStatus | null>(null);
  const [preview, setPreview] = useState<{ label: string; change?: string; problem?: string }[] | null>(null);
  const [lastRun, setLastRun] = useState<ShowRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [arms, setArms] = useState<ArmsStatus | null>(null);
  const reloadArms = useCallback(
    () => void apiGet<ArmsStatus>('/light-show/arms').then(setArms).catch(() => undefined), []);

  const kinds = useMemo(() => new Map((catalogue?.kinds ?? []).map((k) => [k.kind, k])), [catalogue]);

  const reloadSets = useCallback(async () => {
    const r = await apiGet<{ sets: ShowSet[] }>('/light-show/sets');
    setSets(r.sets);
    return r.sets;
  }, []);

  useEffect(() => {
    void apiGet<ShowCatalogue>('/light-show/catalogue').then(setCatalogue).catch((e) => toast(String(e), 'error'));
    void apiGet<ShowTargets>('/light-show/targets').then(setTargets).catch(() => undefined);
    void reloadSets().then((s) => setSelected((cur) => cur ?? s[0]?.id ?? null));
  }, [reloadSets, toast]);

  useEffect(() => {
    const poll = () => {
      void apiGet<ShowStatus>('/light-show/status').then(setStatus).catch(() => undefined);
      reloadArms();
    };
    poll();
    const t = window.setInterval(poll, 1500);
    return () => window.clearInterval(t);
  }, [reloadArms]);

  // A run with a pause keeps going after Fire returns — follow it.
  useEffect(() => {
    if (!lastRun || lastRun.state !== 'running' || !status) return;
    const fresh = [...status.running_sets, ...status.recent_runs].find((r) => r.id === lastRun.id);
    if (fresh) setLastRun(fresh);
  }, [status, lastRun]);

  useEffect(() => {
    if (selected === NEW_ID) return;
    const s = sets.find((x) => x.id === selected) ?? null;
    setDraft(s ? JSON.parse(JSON.stringify(s)) : null);
    setDirty(false);
    setPreview(null);
  }, [selected, sets]);

  const edit = (fn: (d: ShowSet) => void) => {
    setDraft((d) => {
      if (!d) return d;
      const copy: ShowSet = JSON.parse(JSON.stringify(d));
      fn(copy);
      return copy;
    });
    setDirty(true);
    setPreview(null);
  };

  const save = async (): Promise<ShowSet | null> => {
    if (!draft) return null;
    try {
      const saved = await apiPost<ShowSet>('/light-show/sets', draft);
      await reloadSets();
      setSelected(saved.id ?? null);
      setDirty(false);
      toast(`Saved ${saved.name}`, 'success');
      return saved;
    } catch (e) {
      toast(String(e), 'error');
      return null;
    }
  };

  const fireNow = async () => {
    let id = draft?.id;
    if (dirty || !id) {
      const saved = await save();
      if (!saved?.id) return;
      id = saved.id;
    }
    setBusy(true);
    try {
      const run = await apiPost<ShowRun>(`/light-show/sets/${id}/fire`);
      setLastRun(run);
      toast(runSummary(run), run.state === 'done' || run.state === 'running' ? 'success' : 'error');
    } catch (e) {
      toast(String(e), 'error');
    } finally {
      setBusy(false);
    }
  };

  const doPreview = async () => {
    if (!draft?.id) return;
    if (dirty) await save();
    const r = await apiPost<{ steps: { label: string; change?: string; problem?: string }[] }>(
      `/light-show/sets/${draft.id}/preview`);
    setPreview(r.steps);
  };

  const remove = async () => {
    if (!draft?.id || !window.confirm(`Delete the set "${draft.name}"?`)) return;
    await apiDel(`/light-show/sets/${draft.id}`);
    const s = await reloadSets();
    setSelected(s[0]?.id ?? null);
  };

  const endShow = async () => {
    setBusy(true);
    try {
      const r = await apiPost<EndShowReport>('/light-show/end');
      toast(endShowSummary(r), r.failed.length ? 'error' : 'success');
    } catch (e) {
      toast(String(e), 'error');
    } finally {
      setBusy(false);
    }
  };

  const release = async (device: string) => {
    await apiPost(`/light-show/release/${encodeURIComponent(device)}`).catch((e) => toast(String(e), 'error'));
  };
  const endLevel = async (id: string) => {
    await apiPost(`/light-show/levels/${id}/end`).catch((e) => toast(String(e), 'error'));
  };

  const gate = status?.output.refusal ?? status?.output.standdown ?? null;

  return (
    <div className="light-show-page">
      <div className="light-show-head">
        <h2>Light Show <HelpLink topic="light-show-page" /></h2>
        <div className="light-show-mode-select" role="tablist" aria-label="Build or run the show">
          <button role="tab" aria-selected={mode === 'build'} className={mode === 'build' ? 'active' : ''}
            onClick={() => setMode('build')}>Build</button>
          <button role="tab" aria-selected={mode === 'run'} className={mode === 'run' ? 'active' : ''}
            onClick={() => setMode('run')}>Run{isPhone ? ' (recommended)' : ''}</button>
          <HelpLink topic="show-run-view" />
        </div>
        {mode === 'build' && (
          <div className="light-show-head-actions">
            <button className="danger" disabled={busy} onClick={() => void endShow()}
              title="Cancel running sets, stop the show's room effect, let every fixture go and put back every setting the show changed">
              End show
            </button>
            <HelpLink topic="show-end-restore" />
          </div>
        )}
      </div>

      {gate && (
        <div className="light-show-gate" role="status">
          ⏸ The Light Show is standing down: {gate}
        </div>
      )}

      {mode === 'run' ? (
        <RunView sets={sets} status={status} arms={arms} onChangeArms={reloadArms}
          onEndShowDone={() => void reloadSets()} toast={toast} />
      ) : (
      <>
      <ArmBoard arms={arms} onChange={reloadArms} toast={toast} />

      <ShowNowPanel status={status} onRelease={release} onEndLevel={endLevel} />

      <div className="light-show-layout">
        <div className="card light-show-sets">
          <div className="light-show-sets-head">
            <strong>Sets</strong> <HelpLink topic="show-sets" />
            <button onClick={() => {
              setSelected(NEW_ID);
              setDraft({ name: 'New set', actions: [] });
              setDirty(true);
            }}>+ New</button>
          </div>
          {sets.length === 0 && <p className="muted">No sets yet.</p>}
          <ul>
            {sets.map((s) => (
              <li key={s.id}>
                <button className={s.id === selected ? 'active' : ''} onClick={() => {
                  if (dirty && !window.confirm('Discard unsaved changes to this set?')) return;
                  setSelected(s.id ?? null);
                }}>
                  {s.name}
                  {(s.problems?.length ?? 0) > 0 && <span title={s.problems?.join('\n')}> ⚠</span>}
                  <span className="muted"> · {s.actions.length}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="card light-show-editor">
          {!draft && <p className="muted">Choose a set, or make a new one.</p>}
          {draft && catalogue && (
            <>
              <div className="light-show-editor-head">
                <input type="text" value={draft.name} aria-label="Set name"
                  onChange={(e) => edit((d) => { d.name = e.target.value; })} />
                <button className="primary" disabled={busy || !targets} onClick={() => void fireNow()}
                  title="Run this set now">▶ Fire now</button>
                <button disabled={!dirty} onClick={() => void save()}>Save</button>
                <button disabled={!draft.id} onClick={() => void doPreview()}
                  title="What it would change against the room as it is now — writes nothing">Preview changes</button>
                {draft.id && <button className="danger" onClick={() => void remove()}>Delete</button>}
              </div>
              <ArmControl setId={draft.id} disabled={busy || dirty} onArmed={reloadArms} toast={toast} />
              {dirty && <p className="muted">Save the set before arming it.</p>}
              {(draft.problems?.length ?? 0) > 0 && !dirty && (
                <ul className="light-show-problems">{draft.problems!.map((p) => <li key={p}>⚠ {p}</li>)}</ul>
              )}
              {(draft.conflicts?.length ?? 0) > 0 && !dirty && (
                <ul className="light-show-conflicts">{draft.conflicts!.map((p) => <li key={p}>↯ {p}</li>)}</ul>
              )}
              <ol className="light-show-steps">
                {draft.actions.map((a, i) => (
                  <StepEditor key={a.id ?? i} action={a} index={i} count={draft.actions.length}
                    kind={kinds.get(a.kind)} catalogue={catalogue} targets={targets}
                    onChange={(next) => edit((d) => { d.actions[i] = next; })}
                    onMove={(delta) => edit((d) => {
                      const j = i + delta;
                      if (j < 0 || j >= d.actions.length) return;
                      [d.actions[i], d.actions[j]] = [d.actions[j], d.actions[i]];
                    })}
                    onReorderFrom={(from) => edit((d) => {
                      if (from < 0 || from >= d.actions.length || from === i) return;
                      const [moved] = d.actions.splice(from, 1);
                      d.actions.splice(i, 0, moved);
                    })}
                    onDelete={() => edit((d) => { d.actions.splice(i, 1); })}
                    previewLine={preview?.[i]} />
                ))}
              </ol>
              <AddStep catalogue={catalogue} onAdd={(k) => edit((d) => {
                d.actions.push({ id: newId(), kind: k.kind, params: defaultsFor(k), enabled: true });
              })} />
            </>
          )}
        </div>
      </div>

      {lastRun && <RunReport run={lastRun} />}
      </>
      )}
      <SonicChatPopover helpTopic="sonic-light-show" />
    </div>
  );
}

export function ShowNowPanel({ status, onRelease, onEndLevel }: {
  status: ShowStatus | null;
  onRelease: (device: string) => void;
  onEndLevel: (id: string) => void;
}) {
  if (!status) return null;
  const { holds, levels } = status.output;
  if (!holds.length && !levels.length && !status.baselines.length && !status.room_effect
      && !status.running_sets.length) {
    return null;
  }
  return (
    <div className="card light-show-now">
      <strong>Right now</strong> <HelpLink topic="show-device-states" />
      {status.output.suspended && <span className="muted"> — output paused while the room is held</span>}
      <ul>
        {holds.map((h) => (
          <li key={h.device}>
            {h.name}: <b>{h.state}</b>
            {h.held_by_ambient && <span className="muted"> (held by Hue Hold)</span>}
            <button onClick={() => onRelease(h.device)}>Release</button>
          </li>
        ))}
        {levels.map((l) => (
          <li key={l.id}>
            {l.names.join(', ')}: level <b>{Math.round(l.level * 100)}%</b>
            {l.remaining_s !== null ? ` · ${l.remaining_s}s left` : ` · until ${l.until.replace('_', ' ')}`}
            <button onClick={() => onEndLevel(l.id)}>End</button>
          </li>
        ))}
        {status.room_effect && <li>Room effect: <b>{status.room_effect.name}</b></li>}
        {status.baselines.length > 0 && (
          <li className="muted">Settings changed by the show: {status.baselines.map((b) => b.label).join(', ')}</li>
        )}
        {status.running_sets.map((r) => <li key={r.id}>{runSummary(r)}</li>)}
      </ul>
    </div>
  );
}

function RunReport({ run }: { run: ShowRun }) {
  return (
    <div className="card light-show-run">
      <strong>{runSummary(run)}</strong>
      <ol>
        {run.steps.map((s) => (
          <li key={s.action_id} className={`show-step-${s.status}`}>
            <span className="show-step-status">{s.status}</span> {s.label}
            {s.detail && <span className="muted"> — {s.detail}</span>}
          </li>
        ))}
      </ol>
    </div>
  );
}

function AddStep({ catalogue, onAdd }: { catalogue: ShowCatalogue; onAdd: (k: ShowKind) => void }) {
  const groups: [string, string][] = [
    ['setting', 'Settings'], ['device', 'Devices'], ['effect', 'Room effects'], ['control', 'Control'],
  ];
  return (
    <div className="light-show-add">
      <select value="" aria-label="Add a step" onChange={(e) => {
        const k = catalogue.kinds.find((x) => x.kind === e.target.value);
        if (k) onAdd(k);
      }}>
        <option value="">+ Add a step…</option>
        {groups.map(([g, label]) => (
          <optgroup key={g} label={label}>
            {catalogue.kinds.filter((k) => k.group === g).map((k) => (
              <option key={k.kind} value={k.kind}>{k.label}</option>
            ))}
          </optgroup>
        ))}
      </select>
      <HelpLink topic="show-actions" />
    </div>
  );
}

function StepEditor({ action, index, count, kind, catalogue, targets, onChange, onMove, onReorderFrom, onDelete, previewLine }: {
  action: ShowAction; index: number; count: number; kind: ShowKind | undefined;
  catalogue: ShowCatalogue; targets: ShowTargets | null;
  onChange: (a: ShowAction) => void; onMove: (d: number) => void;
  onReorderFrom: (fromIndex: number) => void; onDelete: () => void;
  previewLine?: { change?: string; problem?: string };
}) {
  const [dragOver, setDragOver] = useState(false);
  const set = (name: string, value: unknown) => {
    const params = { ...action.params };
    if (value === undefined || value === '' || value === null) delete params[name];
    else params[name] = value;
    onChange({ ...action, params });
  };
  return (
    <li className={`light-show-step${action.enabled === false ? ' off' : ''}${dragOver ? ' drag-over' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        const from = Number(e.dataTransfer.getData('text/plain'));
        if (!Number.isNaN(from)) onReorderFrom(from);
      }}>
      <div className="light-show-step-head">
        <span className="light-show-step-handle" draggable aria-label="Drag to reorder"
          title="Drag to reorder"
          onDragStart={(e) => { e.dataTransfer.setData('text/plain', String(index)); }}>
          ⠿
        </span>
        <label title="Switch this step off without deleting it">
          <input type="checkbox" checked={action.enabled !== false}
            onChange={(e) => onChange({ ...action, enabled: e.target.checked })} />
          <b>{kind?.label ?? action.kind}</b>
        </label>
        {kind && <HelpLink topic={kind.help_topic} />}
        <span className="light-show-step-tools">
          <button disabled={index === 0} onClick={() => onMove(-1)} aria-label="Move up">↑</button>
          <button disabled={index === count - 1} onClick={() => onMove(1)} aria-label="Move down">↓</button>
          <button onClick={onDelete} aria-label="Remove step">✕</button>
        </span>
      </div>
      {!kind && <p className="light-show-problems">Unknown action kind “{action.kind}”.</p>}
      {kind && <p className="muted light-show-step-help">{kind.help}</p>}
      {kind && (
        <div className="light-show-params">
          {kind.params.map((p) => (
            <ParamField key={p.name} p={p} value={action.params[p.name]} onChange={(v) => set(p.name, v)}
              catalogue={catalogue} targets={targets} action={action} />
          ))}
        </div>
      )}
      {previewLine && (
        <p className={previewLine.problem ? 'light-show-problems' : 'light-show-preview'}>
          {previewLine.problem ? `⚠ ${previewLine.problem}` : `→ ${previewLine.change}`}
        </p>
      )}
    </li>
  );
}

function Chips({ options, value, onChange }: {
  options: { id: string; name: string }[]; value: string[]; onChange: (v: string[]) => void;
}) {
  return (
    <span className="light-show-chips">
      {options.map((o) => {
        const on = value.includes(o.id);
        return (
          <button key={o.id} className={on ? 'active' : ''} type="button"
            onClick={() => onChange(on ? value.filter((x) => x !== o.id) : [...value, o.id])}>
            {o.name}
          </button>
        );
      })}
    </span>
  );
}

function ParamField({ p, value, onChange, catalogue, targets, action }: {
  p: ShowParam; value: unknown; onChange: (v: unknown) => void;
  catalogue: ShowCatalogue; targets: ShowTargets | null; action: ShowAction;
}) {
  const scenes = useScenes().data ?? [];
  const colorSets = useSpotColorSets().data ?? [];
  const gradients = useGradient2dProfiles().data ?? {};
  const hueAreas = useAmbientHueGroups().data?.groups ?? [];
  const label = <span className="light-show-param-label" title={p.help}>{p.label}{p.unit ? ` (${p.unit})` : ''}</span>;
  const wrap = (input: JSX.Element) => <label className="light-show-param">{label}{input}</label>;

  switch (p.type) {
    case 'bool':
      return wrap(<input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />);
    case 'enum':
      return wrap(
        <select value={String(value ?? '')} onChange={(e) => onChange(e.target.value)}>
          {(p.choices ?? []).map((c) => <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>)}
        </select>);
    case 'number':
      return wrap(<input type="number" value={value === undefined ? '' : String(value)}
        placeholder={p.default !== null && p.default !== undefined ? String(p.default) : ''}
        min={p.min ?? undefined} max={p.max ?? undefined}
        step={p.max !== null && p.max <= 1 ? 0.05 : 1}
        onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))} />);
    case 'color':
      return wrap(
        <span>
          <input type="color" value={typeof value === 'string' ? value : '#ffffff'}
            onChange={(e) => onChange(e.target.value)} />
          {value ? <button type="button" onClick={() => onChange(undefined)}>clear</button>
            : <span className="muted"> default</span>}
        </span>);
    case 'scene':
      return wrap(
        <select value={String(value ?? '')} onChange={(e) => onChange(e.target.value || undefined)}>
          <option value="">— choose —</option>
          {scenes.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>);
    case 'scenes':
      return wrap(<Chips options={scenes.map((s) => ({ id: s.id, name: s.name }))}
        value={(value as string[]) ?? []} onChange={onChange} />);
    case 'color_set':
      return wrap(
        <select value={String(value ?? '')} onChange={(e) => onChange(e.target.value || undefined)}>
          <option value="">— choose —</option>
          {colorSets.map((c) => <option key={c.id} value={c.id}>{c.kind === 'group' ? '▣ ' : ''}{c.name}</option>)}
        </select>);
    case 'color_sets':
      return wrap(<Chips options={colorSets.map((c) => ({ id: c.id, name: c.name }))}
        value={(value as string[]) ?? []} onChange={onChange} />);
    case 'gradient':
      return wrap(
        <select value={String(value ?? '')} onChange={(e) => onChange(e.target.value || undefined)}>
          <option value="">— choose —</option>
          {Object.entries(gradients).map(([id, g]) => (
            <option key={id} value={id}>{(g as { name?: string }).name ?? id}</option>
          ))}
        </select>);
    case 'hue_areas':
      return wrap(<Chips options={hueAreas} value={(value as string[]) ?? []} onChange={onChange} />);
    case 'target': {
      const t = (value as { kind: string; id: string | null }) ?? { kind: 'everything', id: null };
      return wrap(
        <span className="light-show-target">
          <select value={t.kind} onChange={(e) => onChange({ kind: e.target.value, id: null })}>
            <option value="everything">Everything</option>
            <option value="category">Category</option>
            <option value="fixture">Fixture</option>
          </select>
          {t.kind === 'category' && (
            <select value={t.id ?? ''} onChange={(e) => onChange({ kind: 'category', id: e.target.value || null })}>
              <option value="">— choose —</option>
              {(targets?.categories ?? []).map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
          )}
          {t.kind === 'fixture' && (
            <select value={t.id ?? ''} onChange={(e) => onChange({ kind: 'fixture', id: e.target.value || null })}>
              <option value="">— choose —</option>
              {(targets?.fixtures ?? []).map((f) => (
                <option key={f.id} value={f.id}>{f.name}{f.held_by_ambient ? ' (held by Hue Hold)' : ''}</option>
              ))}
            </select>
          )}
          {targets && !targets.live && <span className="muted"> live stack down — fixtures unknown</span>}
        </span>);
    }
    case 'room_effect':
      return wrap(
        <select value={String(value ?? '')} onChange={(e) => onChange(e.target.value || undefined)}>
          <option value="">— choose —</option>
          {catalogue.room_effects.map((e) => <option key={e.id} value={e.name}>{e.name} ({e.kind.replace(/_/g, ' ')})</option>)}
        </select>);
    case 'overrides': {
      const props = catalogue.room_effect_schema?.properties ?? {};
      const numeric = Object.entries(props).filter(([, s]) => s.type === 'number' || s.type === 'integer');
      const cur = (value as Record<string, number>) ?? {};
      if (!action.params.effect || numeric.length === 0) return null;
      return (
        <div className="light-show-param light-show-overrides">
          {label}
          {numeric.map(([name, s]) => (
            <label key={name}>
              {name}
              <input type="number" placeholder="effect's own" value={cur[name] ?? ''}
                min={s.minimum} max={s.maximum} step={0.05}
                onChange={(e) => {
                  const next = { ...cur };
                  if (e.target.value === '') delete next[name];
                  else next[name] = Number(e.target.value);
                  onChange(next);
                }} />
            </label>
          ))}
        </div>);
    }
    default:
      return wrap(<input type="text" value={String(value ?? '')} onChange={(e) => onChange(e.target.value || undefined)} />);
  }
}
