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
 * for the countdowns, never two. A third tab, Sequence (SequenceView.tsx),
 * builds and runs Show Sequences: ordered sets, each pre-armed one of the
 * same four ways, and Waits, run strictly in order. A fourth, Playlists
 * (PlaylistView.tsx), builds Show Playlists: programs keyed to the Spotify
 * playlist he plays, arming each song's steps as the song starts; the
 * banner (PlaylistRunCard.tsx) says on every view when one is following. */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiDel, apiGet, apiPost } from '../api/client';
import HelpLink from '../help/HelpLink';
import Icon from '../components/Icon';
import { useToast } from '../components/Toast';
import SonicChatPopover from '../components/SonicChatPopover';
import SearchSelect, { type SearchOption } from '../components/forms/SearchSelect';
import useIsPhone from '../lib/useIsPhone';
import { useScenes, useSpotColorSets } from '../queries';
import { ArmBoard, ArmControl } from './ArmBoard';
import {
  callersOf, calledIds, cloneFresh, duplicateAt, insertAt, pasteSetName, writeClip,
  type SummaryLookups,
} from './builderOps';
import { PlaylistBanner, usePlaylistStatus } from './PlaylistRunCard';
import PlaylistView from './PlaylistView';
import useShowClip from './useShowClip';
import RunView from './RunView';
import SequenceView from './SequenceView';
import SortableList from './SortableList';
import StepCard, { type PreviewLine } from './StepCard';
import { reorder } from './sequenceOps';
import { endShowSummary, runSummary } from './showSummary';
import type {
  ArmsStatus, EndShowReport, ShowAction, ShowCatalogue, ShowKind, ShowRun, ShowSet,
  ShowStatus, ShowTargets,
} from './types';

interface PreviewRow extends PreviewLine { action_id: string; top_id?: string }


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
  const [mode, setMode] = useState<'build' | 'run' | 'sequence' | 'playlists'>(() => (window.matchMedia('(max-width: 720px)').matches ? 'run' : 'build'));
  const [catalogue, setCatalogue] = useState<ShowCatalogue | null>(null);
  const [targets, setTargets] = useState<ShowTargets | null>(null);
  const [sets, setSets] = useState<ShowSet[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<ShowSet | null>(null);
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState<ShowStatus | null>(null);
  const [preview, setPreview] = useState<PreviewRow[] | null>(null);
  const [lastRun, setLastRun] = useState<ShowRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [arms, setArms] = useState<ArmsStatus | null>(null);
  /** which steps are open, by step id (collapsed by default, like the
   * legacy editor; a step just added or pasted opens) */
  const [openSteps, setOpenSteps] = useState<Set<string>>(new Set());
  const clip = useShowClip();
  const scenes = useScenes().data ?? [];
  const colorSets = useSpotColorSets().data ?? [];
  const { status: playlistStatus, reload: reloadPlaylist } = usePlaylistStatus();
  const reloadArms = useCallback(
    () => void apiGet<ArmsStatus>('/light-show/arms').then(setArms).catch(() => undefined), []);

  const kinds = useMemo(() => new Map((catalogue?.kinds ?? []).map((k) => [k.kind, k])), [catalogue]);
  const lookups: SummaryLookups = useMemo(() => ({
    sets: new Map(sets.filter((s) => s.id).map((s) => [s.id as string, s.name])),
    scenes: new Map(scenes.map((s) => [s.id, s.name])),
    colorSets: new Map(colorSets.map((c) => [c.id, c.name])),
    fixtures: new Map((targets?.fixtures ?? []).map((f) => [f.id, f.name])),
    houseModes: new Map((catalogue?.house_modes ?? []).map((m) => [m.id, m.name])),
  }), [sets, scenes, colorSets, targets, catalogue]);

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

  const openStep = (...ids: (string | undefined)[]) => setOpenSteps((o) => {
    const n = new Set(o);
    ids.forEach((id) => { if (id) n.add(id); });
    return n;
  });

  /** Choose a set in the editor (from the list, or a "Run another set"
   * step's ↗ / a sequence item's ↗) — unsaved edits are asked about first. */
  const chooseSet = (id: string | null) => {
    if (id === selected) return true;
    if (dirty && !window.confirm('Discard unsaved changes to this set?')) return false;
    setSelected(id);
    return true;
  };
  const openSetFromElsewhere = (id: string) => {
    if (chooseSet(id)) setMode('build');
  };

  const save = async (): Promise<ShowSet | null> => {
    if (!draft) return null;
    try {
      const { problems: _p, conflicts: _c, calls: _ca, used_by: _u, used_in_sequences: _q, ...body } = draft;
      const saved = await apiPost<ShowSet>('/light-show/sets', body);
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

  /** Create a NEW saved set from steps (Duplicate, Paste as new set),
   * placed right after `afterId` when given. */
  const createSet = async (baseName: string, actions: ShowAction[], afterId?: string, notes = '') => {
    const name = pasteSetName(baseName, sets.map((s) => s.name));
    try {
      const saved = await apiPost<ShowSet>('/light-show/sets', {
        name, notes, actions: cloneFresh(actions), ...(afterId ? { after_id: afterId } : {}),
      });
      await reloadSets();
      setSelected(saved.id ?? null);
      setDirty(false);
      return saved;
    } catch (e) {
      toast(String(e), 'error');
      return null;
    }
  };

  /** "Duplicate" (the Admiral, 2026-10-08): an identical, independent copy
   * of a SAVED set, named "<name> copy" (uniqued if that's taken too),
   * saved right after the original (`after_id`) and selected so it's
   * immediately editable. */
  const duplicate = async () => {
    if (!draft?.id) return;
    const saved = await createSet(`${draft.name} copy`, draft.actions, draft.id, draft.notes ?? '');
    if (saved) toast(`Duplicated as ${saved.name}`, 'success');
  };

  const copySet = () => {
    if (!draft) return;
    writeClip({ kind: 'steps', steps: draft.actions, set_name: draft.name,
      summary: `the set “${draft.name}” (${draft.actions.length} step${draft.actions.length === 1 ? '' : 's'})` });
    toast(`Copied “${draft.name}” — paste it as a new set, or into another set`, 'success');
  };

  const pasteAsNewSet = async () => {
    if (clip?.kind !== 'steps') return;
    if (dirty && !window.confirm('Discard unsaved changes to this set?')) return;
    const saved = await createSet(clip.set_name ? `${clip.set_name} copy` : 'Pasted set', clip.steps,
      draft?.id ?? undefined);
    if (saved) toast(`Pasted as ${saved.name}`, 'success');
  };

  const pasteSteps = (at?: number) => {
    if (clip?.kind !== 'steps' || !draft) return;
    const fresh = cloneFresh(clip.steps);
    edit((d) => { d.actions = insertAt(d.actions, at ?? d.actions.length, fresh); });
    openStep(...fresh.map((a) => a.id));
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
    const r = await apiPost<{ steps: PreviewRow[] }>(`/light-show/sets/${draft.id}/preview`);
    setPreview(r.steps);
    openStep(...r.steps.map((x) => x.top_id ?? x.action_id));
  };

  /** A set other sets run (or a sequence uses) warns, naming them, before it
   * goes — the server refuses an unforced delete of such a set with 409. */
  const remove = async () => {
    if (!draft?.id) return;
    const callers = callersOf(draft.id, sets).map((u) => `the set “${u.name}”`);
    const users = [...new Set([...callers, ...(draft.used_by ?? []).map((u) => `the set “${u.name}”`),
      ...(draft.used_in_sequences ?? []).map((u) => `the sequence “${u.name}”`)])];
    const msg = users.length
      ? `“${draft.name}” is used by ${users.join(', ')}.\n\nDelete it anyway? Those steps will fail until you change them.`
      : `Delete the set "${draft.name}"?`;
    if (!window.confirm(msg)) return;
    try {
      await apiDel(`/light-show/sets/${draft.id}${users.length ? '?force=true' : ''}`);
    } catch (e) {
      // The server knows of a user this page did not (another tab's edit):
      // it refuses with 409 and names it — ask again with its own words.
      const text = String(e);
      if (!users.length && text.includes('409') && window.confirm(`${text.split(': ').slice(1).join(': ')}\n\nDelete it anyway?`)) {
        try {
          await apiDel(`/light-show/sets/${draft.id}?force=true`);
        } catch (e2) {
          toast(String(e2), 'error');
          return;
        }
      } else {
        toast(text, 'error');
        await reloadSets();
        return;
      }
    }
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
  const endHold = async (kind: 'pulse-mods' | 'flare-blocks', id: string) => {
    await apiPost(`/light-show/${kind}/${id}/end`).catch((e) => toast(String(e), 'error'));
  };

  const gate = status?.output.refusal ?? status?.output.standdown ?? null;
  const previewByStep = useMemo(() => {
    const m = new Map<string, PreviewRow[]>();
    for (const row of preview ?? []) {
      const key = row.top_id ?? row.action_id;
      m.set(key, [...(m.get(key) ?? []), row]);
    }
    return m;
  }, [preview]);
  const allOpen = Boolean(draft && draft.actions.length > 0 && draft.actions.every((a) => a.id && openSteps.has(a.id)));

  return (
    <div className="light-show-page">
      <div className="light-show-head">
        <h2>Light Show <HelpLink topic="light-show-page" /></h2>
        <div className="light-show-mode-select" role="tablist" aria-label="Build, run or sequence the show">
          <button role="tab" aria-selected={mode === 'build'} className={mode === 'build' ? 'active' : ''}
            onClick={() => setMode('build')}>Build</button>
          <button role="tab" aria-selected={mode === 'run'} className={mode === 'run' ? 'active' : ''}
            onClick={() => setMode('run')}>Run{isPhone ? ' (recommended)' : ''}</button>
          <button role="tab" aria-selected={mode === 'sequence'} className={mode === 'sequence' ? 'active' : ''}
            onClick={() => setMode('sequence')}>Sequence</button>
          <button role="tab" aria-selected={mode === 'playlists'} className={mode === 'playlists' ? 'active' : ''}
            onClick={() => setMode('playlists')}>Playlists
            {playlistStatus?.run?.active && <span className="show-seq-live-dot" aria-label="a playlist program is following" />}
          </button>
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

      <PlaylistBanner status={playlistStatus} onChange={() => { reloadPlaylist(); reloadArms(); }} toast={toast} />

      {mode === 'playlists' ? (
        <PlaylistView sets={sets} status={playlistStatus} reloadStatus={() => { reloadPlaylist(); reloadArms(); }} toast={toast} />
      ) : mode === 'sequence' ? (
        <SequenceView sets={sets} toast={toast} onOpenSet={openSetFromElsewhere} />
      ) : mode === 'run' ? (
        <RunView sets={sets} status={status} arms={arms} onChangeArms={reloadArms}
          playlistStatus={playlistStatus} onChangePlaylist={reloadPlaylist}
          onEndShowDone={() => void reloadSets()} toast={toast} />
      ) : (
      <>
      <ArmBoard arms={arms} onChange={reloadArms} toast={toast} />

      <ShowNowPanel status={status} onRelease={release} onEndLevel={endLevel} onEndHold={endHold} />

      <div className="light-show-layout">
        <div className="card light-show-sets">
          <div className="light-show-sets-head">
            <strong>Sets</strong> <HelpLink topic="show-sets" />
            <button onClick={() => {
              if (dirty && !window.confirm('Discard unsaved changes to this set?')) return;
              setSelected(NEW_ID);
              setDraft({ name: 'New set', actions: [] });
              setDirty(true);
            }}>+ New</button>
          </div>
          {clip?.kind === 'steps' && (
            <button type="button" className="light-show-paste-set" onClick={() => void pasteAsNewSet()}
              title={`Paste ${clip.summary} as a new set`}>
              <Icon name="paste" size={14} /> Paste as new set
            </button>
          )}
          {sets.length === 0 && <p className="muted">No sets yet.</p>}
          <ul>
            {sets.map((s) => {
              const used = (s.used_by?.length ?? 0) + (s.used_in_sequences?.length ?? 0);
              return (
                <li key={s.id}>
                  <button className={s.id === selected ? 'active' : ''} onClick={() => chooseSet(s.id ?? null)}>
                    {s.name}
                    {(s.problems?.length ?? 0) > 0 && <span title={s.problems?.join('\n')}> ⚠</span>}
                    <span className="muted"> · {s.actions.length}</span>
                    {(s.calls?.length ?? 0) > 0 && (
                      <span className="light-show-ref-badge" title={`Runs ${s.calls!.map((c) => c.name ?? 'a deleted set').join(', ')}`}>
                        <Icon name="callSet" size={12} />{s.calls!.length}
                      </span>
                    )}
                    {used > 0 && (
                      <span className="light-show-used-badge" title={usedByTitle(s)}>used by {used}</span>
                    )}
                  </button>
                </li>
              );
            })}
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
                {draft.id && (
                  <button disabled={dirty} onClick={() => void duplicate()}
                    title={dirty ? 'Save this set before duplicating it'
                      : 'An independent copy, named "<name> copy", right after this one'}>
                    <Icon name="duplicate" size={14} /> Duplicate
                  </button>
                )}
                <button onClick={copySet} disabled={draft.actions.length === 0}
                  title="Copy this whole set — paste it as a new set, or its steps into another set">
                  <Icon name="copy" size={14} /> Copy set
                </button>
                {draft.id && <button className="danger" onClick={() => void remove()}>Delete</button>}
              </div>
              <SetReferences draft={draft} sets={sets} onOpenSet={(id) => chooseSet(id)} />
              <ArmControl setId={draft.id} disabled={busy || dirty} onArmed={reloadArms} toast={toast} />
              {dirty && <p className="muted">Save the set before arming it.</p>}
              {(draft.problems?.length ?? 0) > 0 && !dirty && (
                <ul className="light-show-problems">{draft.problems!.map((p) => <li key={p}>⚠ {p}</li>)}</ul>
              )}
              {(draft.conflicts?.length ?? 0) > 0 && !dirty && (
                <ul className="light-show-conflicts">{draft.conflicts!.map((p) => <li key={p}>↯ {p}</li>)}</ul>
              )}
              {draft.actions.length > 0 && (
                <div className="light-show-list-tools">
                  <span className="muted">{draft.actions.length} step{draft.actions.length === 1 ? '' : 's'}</span>
                  <button type="button" onClick={() => setOpenSteps(allOpen ? new Set()
                    : new Set(draft.actions.map((a) => a.id as string)))}>
                    {allOpen ? 'Collapse all' : 'Expand all'}
                  </button>
                  <HelpLink topic="show-builder-editing" />
                </div>
              )}
              <SortableList className="light-show-steps" items={draft.actions}
                getId={(a, i) => a.id ?? `i${i}`}
                getLabel={(a, i) => `step ${i + 1}, ${kinds.get(a.kind)?.label ?? a.kind}`}
                onReorder={(from, to) => edit((d) => { d.actions = reorder(d.actions, from, to); })}
                renderItem={(a, i, row) => (
                  <StepCard key={a.id ?? i} action={a} index={i}
                    kind={kinds.get(a.kind)} kinds={kinds} catalogue={catalogue} targets={targets}
                    sets={sets} currentSetId={draft.id} lookups={lookups}
                    open={Boolean(a.id && openSteps.has(a.id))}
                    onToggle={() => setOpenSteps((o) => {
                      const n = new Set(o);
                      if (a.id && n.has(a.id)) n.delete(a.id); else if (a.id) n.add(a.id);
                      return n;
                    })}
                    onChange={(next) => edit((d) => { d.actions[i] = next; })}
                    onDuplicate={() => {
                      const dup = duplicateAt(draft.actions, i);
                      edit((d) => { d.actions = dup; });
                      openStep(dup[i + 1].id);
                    }}
                    onCopy={() => {
                      writeClip({ kind: 'steps', steps: [a],
                        summary: `the step “${kinds.get(a.kind)?.label ?? a.kind}”` });
                      toast('Step copied — paste it into any set', 'success');
                    }}
                    onDelete={() => edit((d) => { d.actions.splice(i, 1); })}
                    onOpenSet={(id) => chooseSet(id)}
                    previewLines={a.id ? previewByStep.get(a.id) : undefined}
                    row={row} />
                )} />
              <div className="light-show-add-row">
                <AddStep catalogue={catalogue} onAdd={(k) => {
                  const id = newId();
                  edit((d) => { d.actions.push({ id, kind: k.kind, params: defaultsFor(k), enabled: true }); });
                  openStep(id);
                }} />
                {clip?.kind === 'steps' && (
                  <button type="button" onClick={() => pasteSteps()} title={`Paste ${clip.summary} at the end`}>
                    <Icon name="paste" size={14} /> Paste {clip.steps.length} step{clip.steps.length === 1 ? '' : 's'}
                  </button>
                )}
              </div>
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

function usedByTitle(s: ShowSet): string {
  const parts = [...(s.used_by ?? []).map((u) => u.name), ...(s.used_in_sequences ?? []).map((u) => `${u.name} (sequence)`)];
  return `Used by ${parts.join(', ')}`;
}

/** "Runs: …" and "Used by: …" under the set's name — each name opens that
 * set (spectra/services/show_refs.py: a reference, never a copy, so an edit
 * here changes every set listed under Used by). */
function SetReferences({ draft, sets, onOpenSet }: {
  draft: ShowSet; sets: ShowSet[]; onOpenSet: (id: string) => void;
}) {
  const calls = calledIds(draft.actions).map((id) => ({ id, name: sets.find((s) => s.id === id)?.name ?? null }));
  const usedBy = draft.id ? callersOf(draft.id, sets).map((s) => ({ id: s.id as string, name: s.name })) : [];
  const seqs = draft.used_in_sequences ?? [];
  if (!calls.length && !usedBy.length && !seqs.length) return null;
  return (
    <div className="light-show-refs">
      {calls.length > 0 && (
        <div><span className="muted">Runs</span>{' '}
          {calls.map((c) => c.name
            ? <button key={c.id} type="button" className="linklike" onClick={() => onOpenSet(c.id)}>{c.name}</button>
            : <span key={c.id} className="light-show-problems">a deleted set</span>)}
          <HelpLink topic="show-set-references" />
        </div>
      )}
      {(usedBy.length > 0 || seqs.length > 0) && (
        <div><span className="muted">Used by {usedBy.length + seqs.length}:</span>{' '}
          {usedBy.map((u) => (
            <button key={u.id} type="button" className="linklike" onClick={() => onOpenSet(u.id)}>{u.name}</button>
          ))}
          {seqs.map((q) => <span key={q.id} className="light-show-seq-ref">{q.name} (sequence)</span>)}
          <span className="muted"> — editing this set changes {usedBy.length + seqs.length === 1 ? 'it' : 'all of them'}</span>
        </div>
      )}
    </div>
  );
}

export function ShowNowPanel({ status, onRelease, onEndLevel, onEndHold }: {
  status: ShowStatus | null;
  onRelease: (device: string) => void;
  onEndLevel: (id: string) => void;
  /** end a Pulse hold or a flares-off switch (spectra/services/show_mods.py) */
  onEndHold: (kind: 'pulse-mods' | 'flare-blocks', id: string) => void;
}) {
  if (!status) return null;
  const { holds, levels } = status.output;
  const pulseMods = status.output.pulse_mods ?? [];
  const flareBlocks = status.output.flare_blocks ?? [];
  if (!holds.length && !levels.length && !status.baselines.length && !status.room_effect
      && !status.running_sets.length && !pulseMods.length && !flareBlocks.length) {
    return null;
  }
  const ends = (until: string, remaining: number | null) =>
    (remaining !== null ? ` · ${remaining}s left` : ` · until ${until.replace('_', ' ')}`);
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
        {pulseMods.map((m) => (
          <li key={m.id}>
            Pulse on {m.label || m.virtual_ids.join(', ')}:{' '}
            <b>{[
              m.reactivity !== null ? `reactivity ${m.reactivity}` : null,
              m.floor !== null ? `floor ${m.floor}` : null,
              m.ceiling !== null ? `ceiling ${m.ceiling}` : null,
            ].filter(Boolean).join(', ')}</b>
            {ends(m.until, m.remaining_s)}
            <button onClick={() => onEndHold('pulse-mods', m.id)}>End</button>
          </li>
        ))}
        {flareBlocks.map((b) => (
          <li key={b.id}>
            Flares <b>off</b> for {b.label || b.virtual_ids.join(', ')}
            {ends(b.until, b.remaining_s)}
            <button onClick={() => onEndHold('flare-blocks', b.id)}>Flares on</button>
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
            <span className="show-step-status">{s.status}</span>{' '}
            {s.via && s.via.length > 0 && <span className="muted">{s.via.join(' › ')} › </span>}
            {s.label}
            {s.detail && <span className="muted"> — {s.detail}</span>}
          </li>
        ))}
      </ol>
    </div>
  );
}

/** "+ Add a step…" used to sit inline at the bottom of a long steps list —
 * on a set with several steps already, that puts the control (and the
 * SearchSelect dropdown it opens) right at the page's own bottom edge,
 * with no room below to show or expand (his report, 2026-10-08: "it's so
 * low on the page I can't see the options well, and it doesn't expand
 * anywhere"). It is now a plain button that opens a DIALOG near the top
 * of the viewport — the same fixed-overlay/centered-card shape every
 * other dialog in this app uses (SpectraTriggerDialog.tsx,
 * FlareKindEditDialog.tsx) — so the picker always has the viewport below
 * it to open into, on any page length and at any scroll position. */
function AddStep({ catalogue, onAdd }: { catalogue: ShowCatalogue; onAdd: (k: ShowKind) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="light-show-add">
      <button type="button" onClick={() => setOpen(true)}>+ Add a step…</button>
      <HelpLink topic="show-actions" />
      {open && (
        <AddStepDialog catalogue={catalogue} onClose={() => setOpen(false)}
          onAdd={(k) => { onAdd(k); setOpen(false); }} />
      )}
    </div>
  );
}

function AddStepDialog({ catalogue, onAdd, onClose }: {
  catalogue: ShowCatalogue; onAdd: (k: ShowKind) => void; onClose: () => void;
}) {
  const named: [string, string][] = [
    ['setting', 'Settings'], ['device', 'Devices'], ['effect', 'Room effects'], ['control', 'Control'],
  ];
  // a group a later action kind declares (e.g. Home Assistant) lists too
  const extra = [...new Set(catalogue.kinds.map((k) => k.group))]
    .filter((g) => !named.some(([n]) => n === g))
    .map((g): [string, string] => [g, g.charAt(0).toUpperCase() + g.slice(1).replace(/_/g, ' ')]);
  const groups = [...named, ...extra];
  const options: SearchOption[] = groups.flatMap(([g, label]) =>
    catalogue.kinds.filter((k) => k.group === g).map((k) => ({
      value: k.kind, label: k.label, group: label, keywords: k.help,
    })));
  return (
    <div onClick={onClose}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100,
               display: 'flex', alignItems: 'flex-start', justifyContent: 'center', paddingTop: '10vh' }}>
      <div className="card" onClick={(e) => e.stopPropagation()}
        style={{ width: 420, maxWidth: '92vw', margin: 0 }}>
        <div className="card-title">
          Add a step <HelpLink topic="show-actions" />
        </div>
        <SearchSelect value="" options={options} placeholder="Search action kinds…" allowEmpty={false}
          autoFocus width="100%"
          onChange={(v) => {
            const k = catalogue.kinds.find((x) => x.kind === v);
            if (k) onAdd(k);
          }} />
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
          <button onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

