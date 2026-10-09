/** THE LIGHT SHOW's SEQUENCE TAB — Show Sequences (the Admiral,
 * 2026-10-09: "A 'Show Sequence' is a sequence of pre-armed sets ... it
 * goes in order, running the sets when they trigger, but never skipping
 * ahead").
 *
 * Two sub-views over the same data:
 *   Build — his sequences: create / rename / duplicate / delete, add Sets
 *           (the app's searchable picker) each armed with the same four
 *           icons as the Run view's one-tap row, add Waits (a fixed time, a
 *           number of triggers, a number of songs, or one of a list of
 *           songs — searched from the songs SPECTRA knows), reorder by drag
 *           (pointer events, so a finger works as well as a mouse) or ↑/↓.
 *   Run   — start one, then the current item highlighted with what it is
 *           waiting for, what is done and what is next, and the human
 *           override: Pause / Resume, Stop, Previous, Next, Fire now.
 *
 * What a run DOES is the server's business (spectra/services/
 * show_sequence.py); this view only shows `GET /light-show/sequence-run`,
 * polled, and its sentence `waiting_for` verbatim — never a second copy of
 * the runner's rules. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { apiDel, apiGet, apiPost } from '../api/client';
import Icon from '../components/Icon';
import SearchSelect from '../components/forms/SearchSelect';
import HelpLink from '../help/HelpLink';
import { namedOptions } from '../lib/pickerOptions';
import useIsPhone from '../lib/useIsPhone';
import {
  ARM_ICON, ARM_LABEL, ARM_ORDER, WAIT_LABEL, clock, defaultWait, dropIndex, itemPhase,
  logLine, newSetItem, newWaitItem, reorder,
} from './sequenceOps';
import type {
  ArmTrigger, SequenceItem, SequenceStatus, SequenceWait, ShowSequence, ShowSet, SongRef, WaitKind,
} from './types';

type Toast = (msg: string, kind?: 'success' | 'error') => void;

const NEW_ID = '__new__';

export default function SequenceView({ sets, toast }: { sets: ShowSet[]; toast: Toast }) {
  const isPhone = useIsPhone();
  const [sub, setSub] = useState<'build' | 'run'>(() => (window.matchMedia('(max-width: 720px)').matches ? 'run' : 'build'));
  const [sequences, setSequences] = useState<ShowSequence[]>([]);
  const [status, setStatus] = useState<SequenceStatus | null>(null);

  const reload = useCallback(async () => {
    const r = await apiGet<{ sequences: ShowSequence[] }>('/light-show/sequences');
    setSequences(r.sequences);
    return r.sequences;
  }, []);
  const reloadStatus = useCallback(
    () => void apiGet<SequenceStatus>('/light-show/sequence-run').then(setStatus).catch(() => undefined), []);

  useEffect(() => { void reload().catch((e) => toast(String(e), 'error')); }, [reload, toast]);
  useEffect(() => {
    reloadStatus();
    const t = window.setInterval(reloadStatus, 1500);
    return () => window.clearInterval(t);
  }, [reloadStatus]);

  return (
    <div className="show-seq">
      <div className="light-show-mode-select show-seq-sub" role="tablist" aria-label="Build or run a sequence">
        <button role="tab" aria-selected={sub === 'build'} className={sub === 'build' ? 'active' : ''}
          onClick={() => setSub('build')}>Build</button>
        <button role="tab" aria-selected={sub === 'run'} className={sub === 'run' ? 'active' : ''}
          onClick={() => setSub('run')}>Run{isPhone ? ' (recommended)' : ''}
          {status?.run?.active && <span className="show-seq-live-dot" aria-label="a sequence is running" />}
        </button>
        <HelpLink topic="show-sequences" />
      </div>
      {sub === 'build'
        ? <SequenceBuild sets={sets} sequences={sequences} reload={reload} status={status}
            onStarted={() => { reloadStatus(); setSub('run'); }} toast={toast} />
        : <SequenceRunView sequences={sequences} status={status} reloadStatus={reloadStatus} toast={toast} />}
    </div>
  );
}

// ── Build ──────────────────────────────────────────────────────────────────

function SequenceBuild({ sets, sequences, reload, status, onStarted, toast }: {
  sets: ShowSet[]; sequences: ShowSequence[]; reload: () => Promise<ShowSequence[]>;
  status: SequenceStatus | null; onStarted: () => void; toast: Toast;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<ShowSequence | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setSelected((cur) => cur ?? sequences[0]?.id ?? null);
  }, [sequences]);

  useEffect(() => {
    if (selected === NEW_ID) return;
    const s = sequences.find((x) => x.id === selected) ?? null;
    setDraft(s ? JSON.parse(JSON.stringify(s)) : null);
    setDirty(false);
  }, [selected, sequences]);

  const edit = (fn: (d: ShowSequence) => void) => {
    setDraft((d) => {
      if (!d) return d;
      const copy: ShowSequence = JSON.parse(JSON.stringify(d));
      fn(copy);
      return copy;
    });
    setDirty(true);
  };

  const choose = (id: string | null) => {
    if (dirty && !window.confirm('Discard unsaved changes to this sequence?')) return;
    setSelected(id);
  };

  const save = async (): Promise<ShowSequence | null> => {
    if (!draft) return null;
    try {
      const body = { ...draft, items: draft.items.map(({ title: _t, problems: _p, ...it }) => it) };
      const saved = await apiPost<ShowSequence>('/light-show/sequences', body);
      await reload();
      setSelected(saved.id ?? null);
      setDirty(false);
      toast(`Saved ${saved.name}`, 'success');
      return saved;
    } catch (e) {
      toast(String(e), 'error');
      return null;
    }
  };

  const duplicate = async () => {
    if (!draft?.id) return;
    try {
      const copy = await apiPost<ShowSequence>(`/light-show/sequences/${draft.id}/duplicate`);
      await reload();
      setSelected(copy.id ?? null);
      toast(`Duplicated as ${copy.name}`, 'success');
    } catch (e) {
      toast(String(e), 'error');
    }
  };

  const remove = async () => {
    if (!draft?.id || !window.confirm(`Delete the sequence "${draft.name}"?`)) return;
    try {
      await apiDel(`/light-show/sequences/${draft.id}`);
      const s = await reload();
      setSelected(s[0]?.id ?? null);
    } catch (e) {
      toast(String(e), 'error');
    }
  };

  const start = async () => {
    let id = draft?.id;
    if (dirty || !id) {
      const saved = await save();
      if (!saved?.id) return;
      id = saved.id;
    }
    const running = status?.run?.active ? status.run : null;
    if (running && !window.confirm(`"${running.name}" is running. Stop it and start this one?`)) return;
    try {
      await apiPost('/light-show/sequence-run/start', { sequence_id: id, replace: Boolean(running) });
      toast('Sequence started', 'success');
      onStarted();
    } catch (e) {
      toast(String(e), 'error');
    }
  };

  const setOptions = namedOptions(sets.filter((s) => s.id).map((s) => ({ id: s.id as string, name: s.name })));

  return (
    <div className="light-show-layout show-seq-layout">
      <div className="card light-show-sets">
        <div className="light-show-sets-head">
          <strong>Sequences</strong>
          <button onClick={() => {
            if (dirty && !window.confirm('Discard unsaved changes to this sequence?')) return;
            setSelected(NEW_ID);
            setDraft({ name: 'New sequence', items: [], loop: false });
            setDirty(true);
          }}>+ New</button>
        </div>
        {sequences.length === 0 && <p className="muted">No sequences yet.</p>}
        <ul>
          {sequences.map((s) => (
            <li key={s.id}>
              <button className={s.id === selected ? 'active' : ''} onClick={() => choose(s.id ?? null)}>
                {s.name}
                {(s.problems?.length ?? 0) > 0 && <span title={s.problems?.join('\n')}> ⚠</span>}
                <span className="muted"> · {s.items.length}</span>
                {status?.run?.active && status.run.sequence_id === s.id && <span className="show-seq-live-dot" />}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="card light-show-editor">
        {!draft && <p className="muted">Choose a sequence, or make a new one.</p>}
        {draft && (
          <>
            <div className="light-show-editor-head">
              <input type="text" value={draft.name} aria-label="Sequence name"
                onChange={(e) => edit((d) => { d.name = e.target.value; })} />
              <button className="primary" onClick={() => void start()} disabled={draft.items.length === 0}
                title="Save if needed, then run this sequence from the top">▶ Start</button>
              <button disabled={!dirty} onClick={() => void save()}>Save</button>
              {draft.id && (
                <button disabled={dirty} onClick={() => void duplicate()}
                  title={dirty ? 'Save this sequence before duplicating it'
                    : 'An independent copy, named "<name> copy", right after this one'}>⧉ Duplicate</button>
              )}
              {draft.id && <button className="danger" onClick={() => void remove()}>Delete</button>}
            </div>
            <label className="show-seq-loop" title="Start again from the top after the last item">
              <input type="checkbox" checked={draft.loop}
                onChange={(e) => edit((d) => { d.loop = e.target.checked; })} /> Loop
            </label>
            {(draft.problems?.length ?? 0) > 0 && !dirty && (
              <ul className="light-show-problems">{draft.problems!.map((p) => <li key={p}>⚠ {p}</li>)}</ul>
            )}
            {draft.items.length === 0 && (
              <p className="muted">Add a Set or a Wait. Items run strictly in order: each one starts
                listening only after the one before it has run.</p>
            )}
            <ItemList items={draft.items} setOptions={setOptions} sets={sets}
              onChange={(items) => edit((d) => { d.items = items; })} toast={toast} />
            <div className="show-seq-add">
              <button onClick={() => edit((d) => { d.items.push(newSetItem()); })}>+ Set</button>
              <button onClick={() => edit((d) => { d.items.push(newWaitItem()); })}>+ Wait</button>
              <HelpLink topic="show-sequence-waits" />
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function ItemList({ items, setOptions, sets, onChange, toast }: {
  items: SequenceItem[]; setOptions: { value: string; label: string }[]; sets: ShowSet[];
  onChange: (items: SequenceItem[]) => void; toast: Toast;
}) {
  const rows = useRef<(HTMLLIElement | null)[]>([]);
  const [drag, setDrag] = useState<{ from: number; to: number; pointer: number } | null>(null);

  const rects = () => rows.current.slice(0, items.length).map((el) => {
    const r = el?.getBoundingClientRect();
    return { top: r?.top ?? 0, bottom: r?.bottom ?? 0 };
  });

  const update = (i: number, next: SequenceItem) => {
    const out = items.slice();
    out[i] = next;
    onChange(out);
  };

  return (
    <ol className="show-seq-items">
      {items.map((it, i) => {
        const cls = ['show-seq-item', it.kind,
          drag && drag.from === i ? 'dragging' : '',
          drag && drag.to === i && drag.from !== i ? 'drop-target' : ''].filter(Boolean).join(' ');
        return (
          <li key={it.id ?? i} className={cls} ref={(el) => { rows.current[i] = el; }}>
            <div className="show-seq-item-head">
              <span className="light-show-step-handle show-seq-handle" aria-label="Drag to reorder"
                title="Drag to reorder"
                onPointerDown={(e) => {
                  e.preventDefault();
                  e.currentTarget.setPointerCapture(e.pointerId);
                  setDrag({ from: i, to: i, pointer: e.pointerId });
                }}
                onPointerMove={(e) => {
                  if (!drag || drag.pointer !== e.pointerId) return;
                  const to = dropIndex(e.clientY, rects(), drag.from);
                  if (to !== drag.to) setDrag({ ...drag, to });
                }}
                onPointerUp={(e) => {
                  if (!drag || drag.pointer !== e.pointerId) return;
                  if (drag.to !== drag.from) onChange(reorder(items, drag.from, drag.to));
                  setDrag(null);
                }}
                onPointerCancel={() => setDrag(null)}>⠿</span>
              <span className="show-seq-num">{i + 1}</span>
              <b>{it.kind === 'set' ? 'Set' : 'Wait'}</b>
              <span className="light-show-step-tools">
                <button disabled={i === 0} onClick={() => onChange(reorder(items, i, i - 1))} aria-label="Move up">↑</button>
                <button disabled={i === items.length - 1} onClick={() => onChange(reorder(items, i, i + 1))} aria-label="Move down">↓</button>
                <button onClick={() => onChange(items.filter((_x, j) => j !== i))} aria-label="Remove item">✕</button>
              </span>
            </div>
            {it.kind === 'set'
              ? <SetItemEditor item={it} options={setOptions} sets={sets} onChange={(n) => update(i, n)} />
              : <WaitEditor wait={it.wait ?? defaultWait()} onChange={(w) => update(i, { ...it, wait: w })} toast={toast} />}
            {(it.problems?.length ?? 0) > 0 && (
              <ul className="light-show-problems">{it.problems!.map((p) => <li key={p}>⚠ {p}</li>)}</ul>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function SetItemEditor({ item, options, sets, onChange }: {
  item: SequenceItem; options: { value: string; label: string }[]; sets: ShowSet[];
  onChange: (i: SequenceItem) => void;
}) {
  const missing = item.set_id && !sets.some((s) => s.id === item.set_id);
  return (
    <div className="show-seq-set">
      <SearchSelect value={item.set_id ?? ''} options={options} placeholder="— pick a set —" width="100%"
        onChange={(v) => onChange({ ...item, set_id: v || null })} />
      {missing && <span className="light-show-problems">that set was deleted</span>}
      <ArmPicker value={item.arm} onChange={(arm) => onChange({ ...item, arm })} />
    </div>
  );
}

export function ArmPicker({ value, onChange }: { value: SequenceItem['arm']; onChange: (a: SequenceItem['arm']) => void }) {
  return (
    <div className="light-show-run-set-actions show-seq-arm" role="radiogroup" aria-label="How it is armed">
      {ARM_ORDER.map((a) => (
        <button key={a} type="button" role="radio" aria-checked={value === a}
          className={`light-show-run-set-icon-btn${a === 'instant' ? ' fire' : ''}${value === a ? ' armed' : ''}`}
          title={ARM_LABEL[a]} aria-label={ARM_LABEL[a]} onClick={() => onChange(a)}>
          <Icon name={ARM_ICON[a]} size={22} />
        </button>
      ))}
      <span className="muted show-seq-arm-word">{ARM_LABEL[value]}</span>
    </div>
  );
}

function WaitEditor({ wait, onChange, toast }: {
  wait: SequenceWait; onChange: (w: SequenceWait) => void; toast: Toast;
}) {
  const kinds = Object.keys(WAIT_LABEL) as WaitKind[];
  const mins = Math.floor(wait.seconds / 60);
  const secs = Math.round(wait.seconds % 60);
  return (
    <div className="show-seq-wait">
      <label className="light-show-param">
        <span className="light-show-param-label">Wait for</span>
        <select value={wait.kind} onChange={(e) => onChange({ ...wait, kind: e.target.value as WaitKind })}>
          {kinds.map((k) => <option key={k} value={k}>{WAIT_LABEL[k]}</option>)}
        </select>
      </label>
      {wait.kind === 'duration' && (
        <span className="show-seq-duration">
          <label className="light-show-param"><span className="light-show-param-label">Minutes</span>
            <input type="number" min={0} max={360} value={mins}
              onChange={(e) => onChange({ ...wait, seconds: Math.max(0, Number(e.target.value) || 0) * 60 + secs })} />
          </label>
          <label className="light-show-param"><span className="light-show-param-label">Seconds</span>
            <input type="number" min={0} max={59} value={secs}
              onChange={(e) => onChange({ ...wait, seconds: mins * 60 + Math.min(59, Math.max(0, Number(e.target.value) || 0)) })} />
          </label>
          <span className="muted">{clock(wait.seconds)}</span>
        </span>
      )}
      {wait.kind === 'trigger_count' && (
        <span className="show-seq-duration">
          <label className="light-show-param"><span className="light-show-param-label">How many</span>
            <input type="number" min={1} max={500} value={wait.count}
              onChange={(e) => onChange({ ...wait, count: Math.max(1, Number(e.target.value) || 1) })} />
          </label>
          <TriggerPicker value={wait.trigger} onChange={(t) => onChange({ ...wait, trigger: t })} />
        </span>
      )}
      {wait.kind === 'songs' && (
        <label className="light-show-param"><span className="light-show-param-label">Songs to start</span>
          <input type="number" min={1} max={500} value={wait.count}
            onChange={(e) => onChange({ ...wait, count: Math.max(1, Number(e.target.value) || 1) })} />
        </label>
      )}
      {wait.kind === 'song_list' && (
        <SongListEditor songs={wait.songs} onChange={(songs) => onChange({ ...wait, songs })} toast={toast} />
      )}
    </div>
  );
}

function TriggerPicker({ value, onChange }: { value: ArmTrigger; onChange: (t: ArmTrigger) => void }) {
  const opts: ArmTrigger[] = ['scene_change', 'high', 'low'];
  const words: Record<ArmTrigger, string> = { scene_change: 'scene changes', high: 'High Triggers', low: 'Low Triggers' };
  return (
    <div className="light-show-run-set-actions show-seq-arm" role="radiogroup" aria-label="Which trigger">
      {opts.map((t) => (
        <button key={t} type="button" role="radio" aria-checked={value === t}
          className={`light-show-run-set-icon-btn${value === t ? ' armed' : ''}`}
          title={words[t]} aria-label={words[t]} onClick={() => onChange(t)}>
          <Icon name={ARM_ICON[t]} size={22} />
        </button>
      ))}
      <span className="muted show-seq-arm-word">{words[value]}</span>
    </div>
  );
}

/** The song-list Wait's list, plus a search over the songs SPECTRA knows
 * (GET /light-show/songs — his profile library), by title or artist. */
function SongListEditor({ songs, onChange, toast }: {
  songs: SongRef[]; onChange: (s: SongRef[]) => void; toast: Toast;
}) {
  const [q, setQ] = useState('');
  const [found, setFound] = useState<SongRef[]>([]);
  const [playing, setPlaying] = useState<SongRef | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let live = true;
    setLoading(true);
    const t = window.setTimeout(() => {
      apiGet<{ songs: SongRef[]; playing: SongRef | null }>(`/light-show/songs?q=${encodeURIComponent(q)}&limit=30`)
        .then((r) => { if (live) { setFound(r.songs); setPlaying(r.playing); } })
        .catch((e) => toast(String(e), 'error'))
        .finally(() => { if (live) setLoading(false); });
    }, 200);
    return () => { live = false; window.clearTimeout(t); };
  }, [q, toast]);

  const chosen = new Set(songs.map((s) => s.uri));
  const add = (s: SongRef) => { if (!chosen.has(s.uri)) onChange([...songs, s]); };
  const word = (s: SongRef) => (s.artist ? `${s.title} — ${s.artist}` : s.title);

  return (
    <div className="show-seq-songs">
      <span className="light-show-param-label">Continue when one of these starts playing</span>
      {songs.length === 0 && <p className="muted">No songs yet — search below and add them.</p>}
      <ul className="show-seq-song-list">
        {songs.map((s) => (
          <li key={s.uri}>
            <span>{word(s)}</span>
            <button type="button" aria-label={`Remove ${s.title}`} onClick={() => onChange(songs.filter((x) => x.uri !== s.uri))}>✕</button>
          </li>
        ))}
      </ul>
      <input type="search" placeholder="Search songs by title or artist…" value={q}
        aria-label="Search songs" onChange={(e) => setQ(e.target.value)} />
      {playing && !chosen.has(playing.uri) && (
        <button type="button" className="show-seq-playing" onClick={() => add(playing)}>
          + Playing now: {word(playing)}
        </button>
      )}
      <ul className="show-seq-song-results">
        {found.map((s) => (
          <li key={s.uri}>
            <span>{word(s)}</span>
            <button type="button" disabled={chosen.has(s.uri)} onClick={() => add(s)}
              aria-label={`Add ${s.title}`}>{chosen.has(s.uri) ? 'Added' : '+ Add'}</button>
          </li>
        ))}
        {!loading && found.length === 0 && <li className="muted">No songs match.</li>}
      </ul>
    </div>
  );
}

// ── Run ────────────────────────────────────────────────────────────────────

function SequenceRunView({ sequences, status, reloadStatus, toast }: {
  sequences: ShowSequence[]; status: SequenceStatus | null; reloadStatus: () => void; toast: Toast;
}) {
  const [pick, setPick] = useState('');
  const [busy, setBusy] = useState(false);
  const run = status?.run ?? null;
  const active = Boolean(run?.active);

  const call = async (path: string, body?: unknown) => {
    setBusy(true);
    try {
      await apiPost(`/light-show/sequence-run/${path}`, body);
    } catch (e) {
      toast(String(e), 'error');
    } finally {
      setBusy(false);
      reloadStatus();
    }
  };

  const start = (id: string) => {
    if (active && !window.confirm(`"${run!.name}" is running. Stop it and start this one?`)) return;
    void call('start', { sequence_id: id, replace: active });
  };

  return (
    <div className="light-show-run-view show-seq-run">
      <div className="card show-seq-start">
        <strong>Start a sequence</strong>
        <div className="show-seq-start-row">
          <SearchSelect value={pick} placeholder="— pick a sequence —" width="100%"
            options={namedOptions(sequences.filter((s) => s.id).map((s) => ({ id: s.id as string, name: s.name })))}
            onChange={setPick} />
          <button className="primary big" disabled={!pick || busy} onClick={() => start(pick)}>▶ Start</button>
        </div>
        {sequences.length === 0 && <p className="muted">No sequences yet — build one on the Build view.</p>}
      </div>

      {run && (
        <div className={`card show-seq-now ${run.state}`}>
          <div className="show-seq-now-head">
            <strong>{run.name}</strong>
            <span className={`show-seq-state ${run.state}`}>{stateWord(run.state)}</span>
            {run.loop && <span className="muted">loop{run.loops_done ? ` · pass ${run.loops_done + 1}` : ''}</span>}
          </div>
          {active && <p className="show-seq-waiting" aria-live="polite">{run.waiting_for}</p>}
          {!active && run.end_reason && <p className="muted">{run.end_reason}</p>}

          {active && (
            <div className="show-seq-controls">
              {run.state === 'running'
                ? <button className="big" disabled={busy} onClick={() => void call('pause')}>⏸ Pause</button>
                : <button className="big primary" disabled={busy} onClick={() => void call('resume')}>▶ Resume</button>}
              <button className="big" disabled={busy || run.index <= 0} onClick={() => void call('previous')}
                title="Back one item and re-arm it (nothing it did is undone)">◀ Previous</button>
              <button className="big" disabled={busy || run.index >= run.items.length} onClick={() => void call('next')}
                title="Skip the current item without running it">Next ▶</button>
              <button className="big fire" disabled={busy || run.state !== 'running'} onClick={() => void call('fire-now')}
                title="Run the current set now and move on (on a Wait: end the wait)">
                <Icon name="bolt" size={18} /> Fire now</button>
              <button className="big danger" disabled={busy} onClick={() => void call('stop')}>■ Stop</button>
              <HelpLink topic="show-sequence-run" />
            </div>
          )}

          <ol className="show-seq-run-items">
            {run.items.map((it, i) => {
              const phase = itemPhase(i, run.index, active);
              return (
                <li key={it.id ?? i} className={`show-seq-run-item ${phase}`} aria-current={phase === 'current' ? 'step' : undefined}>
                  <span className="show-seq-num">{i + 1}</span>
                  <span className="show-seq-run-title">
                    {it.kind === 'set' && <Icon name={ARM_ICON[it.arm]} size={16} />}
                    {it.title}
                  </span>
                  {phase === 'current' && <span className="show-seq-run-now">{run.waiting_for}</span>}
                  {phase === 'done' && <span className="muted">✓</span>}
                </li>
              );
            })}
          </ol>

          {run.log.length > 0 && (
            <details className="show-seq-log">
              <summary>History ({run.log.length})</summary>
              <ul>
                {run.log.map((e, i) => (
                  <li key={i}><span className="muted">{new Date(e.at_ms).toLocaleTimeString()}</span> {logLine(e)}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

function stateWord(s: string): string {
  return ({ running: 'Running', paused: 'Paused', finished: 'Finished', stopped: 'Stopped' } as Record<string, string>)[s] ?? s;
}
