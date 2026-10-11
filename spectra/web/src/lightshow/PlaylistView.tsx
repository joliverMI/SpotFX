/** THE LIGHT SHOW's PLAYLISTS TAB — Show Playlists (the Admiral,
 * 2026-10-11: "I use a playlist and make a script through the playlist so
 * that when a specific song is played, it arms an action to fire on the
 * given High/Low Trigger"; plan: data/playlist-plan/report.md).
 *
 * A program answers to the Spotify playlist(s) he plays on Serenity and
 * says, per song, which sets arm on which trigger. Spectra FOLLOWS
 * playback: nothing here starts or changes what plays.
 *
 * This is phase 1's MINIMAL Build view, on today's Light Show editing
 * patterns (the searchable set picker, the Run view's timing icons, the
 * song search the sequence tab already uses). Phase 2a moves it onto the
 * ported SpotFX editor (collapsible cards, nested drag, clipboard).
 *
 * What a program DOES is the server's business
 * (spectra/services/show_playlists.py); the Run view's card shows it. */
import { useCallback, useEffect, useState } from 'react';
import { apiDel, apiGet, apiPost, apiPut, spotfxGet } from '../api/client';
import Icon from '../components/Icon';
import SearchSelect from '../components/forms/SearchSelect';
import HelpLink from '../help/HelpLink';
import { namedOptions } from '../lib/pickerOptions';
import PlaylistRunCard from './PlaylistRunCard';
import {
  TIMING_ICON, TIMING_LABEL, TIMING_ORDER, contextLabel, copyEntrySteps, newPlaylist, newSong,
  newStep, parseContext, reorder, songWord, toWire,
} from './playlistOps';
import type {
  PlaylistStatus, PlaylistStep, ShowPlaylist, ShowSequence, ShowSet, SongEntry, SongRef, SpotifyContext,
} from './types';

type Toast = (msg: string, kind?: 'success' | 'error') => void;
type Options = { value: string; label: string }[];

const NEW_ID = '__new__';

export default function PlaylistView({ sets, status, reloadStatus, toast }: {
  sets: ShowSet[]; status: PlaylistStatus | null; reloadStatus: () => void; toast: Toast;
}) {
  const [playlists, setPlaylists] = useState<ShowPlaylist[]>([]);
  const [followEnabled, setFollowEnabled] = useState(true);
  const [sequences, setSequences] = useState<ShowSequence[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<ShowPlaylist | null>(null);
  const [dirty, setDirty] = useState(false);
  const [clip, setClip] = useState<PlaylistStep[] | null>(null);

  const reload = useCallback(async () => {
    const r = await apiGet<{ playlists: ShowPlaylist[]; follow_enabled: boolean }>('/light-show/playlists');
    setPlaylists(r.playlists);
    setFollowEnabled(r.follow_enabled);
    return r.playlists;
  }, []);

  useEffect(() => {
    void reload().then((p) => setSelected((cur) => cur ?? p[0]?.id ?? null)).catch((e) => toast(String(e), 'error'));
    void apiGet<{ sequences: ShowSequence[] }>('/light-show/sequences').then((r) => setSequences(r.sequences)).catch(() => undefined);
  }, [reload, toast]);

  useEffect(() => {
    if (selected === NEW_ID) return;
    const p = playlists.find((x) => x.id === selected) ?? null;
    setDraft(p ? JSON.parse(JSON.stringify(p)) : null);
    setDirty(false);
  }, [selected, playlists]);

  const edit = (fn: (d: ShowPlaylist) => void) => {
    setDraft((d) => {
      if (!d) return d;
      const copy: ShowPlaylist = JSON.parse(JSON.stringify(d));
      fn(copy);
      return copy;
    });
    setDirty(true);
  };

  const choose = (id: string | null) => {
    if (dirty && !window.confirm('Discard unsaved changes to this program?')) return;
    setSelected(id);
  };

  const save = async (): Promise<ShowPlaylist | null> => {
    if (!draft) return null;
    try {
      const saved = await apiPost<ShowPlaylist>('/light-show/playlists', toWire(draft));
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
      const copy = await apiPost<ShowPlaylist>(`/light-show/playlists/${draft.id}/duplicate`);
      await reload();
      setSelected(copy.id ?? null);
      toast(`Duplicated as ${copy.name} — give it its own Spotify playlist`, 'success');
    } catch (e) {
      toast(String(e), 'error');
    }
  };

  const remove = async () => {
    if (!draft?.id || !window.confirm(`Delete the playlist program "${draft.name}"?`)) return;
    try {
      await apiDel(`/light-show/playlists/${draft.id}`);
      const p = await reload();
      setSelected(p[0]?.id ?? null);
    } catch (e) {
      toast(String(e), 'error');
    }
  };

  const follow = async () => {
    let id = draft?.id;
    if (dirty || !id) {
      const saved = await save();
      if (!saved?.id) return;
      id = saved.id;
    }
    const running = status?.run?.active ? status.run : null;
    if (running && !window.confirm(`"${running.name}" is following. Stop it and follow this one?`)) return;
    try {
      await apiPost('/light-show/playlist-run/start', { playlist_id: id, replace: Boolean(running) });
      toast('Following — whatever is playing now', 'success');
      reloadStatus();
    } catch (e) {
      toast(String(e), 'error');
    }
  };

  const setFollow = async (on: boolean) => {
    try {
      const r = await apiPut<{ follow_enabled: boolean }>('/light-show/playlists/follow', { enabled: on });
      setFollowEnabled(r.follow_enabled);
      reloadStatus();
    } catch (e) {
      toast(String(e), 'error');
    }
  };

  const setOptions = namedOptions(sets.filter((s) => s.id).map((s) => ({ id: s.id as string, name: s.name })));
  const seqOptions = namedOptions(sequences.filter((s) => s.id).map((s) => ({ id: s.id as string, name: s.name })));
  const followingId = status?.run?.active ? status.run.playlist_id : null;

  return (
    <div className="show-playlists">
      <PlaylistRunCard status={status} onChange={reloadStatus} toast={toast} />
      <div className="light-show-layout show-seq-layout">
        <div className="card light-show-sets">
          <div className="light-show-sets-head">
            <strong>Playlist programs</strong> <HelpLink topic="show-playlists" />
            <button onClick={() => {
              if (dirty && !window.confirm('Discard unsaved changes to this program?')) return;
              setSelected(NEW_ID);
              setDraft(newPlaylist());
              setDirty(true);
            }}>+ New</button>
          </div>
          <label className="show-playlist-follow" title="Off: no program starts following on its own (a manual start still works)">
            <input type="checkbox" checked={followEnabled} onChange={(e) => void setFollow(e.target.checked)} />
            Follow playlists
          </label>
          {playlists.length === 0 && <p className="muted">No programs yet.</p>}
          <ul>
            {playlists.map((p) => (
              <li key={p.id}>
                <button className={p.id === selected ? 'active' : ''} onClick={() => choose(p.id ?? null)}>
                  {p.name}
                  {(p.problems?.length ?? 0) > 0 && <span title={p.problems?.join('\n')}> ⚠</span>}
                  <span className="muted"> · {p.songs.length} song{p.songs.length === 1 ? '' : 's'}</span>
                  {followingId === p.id && <span className="show-seq-live-dot" aria-label="following" />}
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="card light-show-editor">
          {!draft && <p className="muted">Choose a program, or make a new one.</p>}
          {draft && (
            <>
              <div className="light-show-editor-head">
                <input type="text" value={draft.name} aria-label="Program name"
                  onChange={(e) => edit((d) => { d.name = e.target.value; })} />
                <button className="primary" onClick={() => void follow()}
                  title="Save if needed, then follow this program now, whatever is playing">▶ Follow now</button>
                <button disabled={!dirty} onClick={() => void save()}>Save</button>
                {draft.id && (
                  <button disabled={dirty} onClick={() => void duplicate()}
                    title={dirty ? 'Save before duplicating' : 'An independent copy, with no Spotify playlist of its own'}>
                    ⧉ Duplicate</button>
                )}
                {draft.id && <button className="danger" onClick={() => void remove()}>Delete</button>}
              </div>
              {(draft.problems?.length ?? 0) > 0 && !dirty && (
                <ul className="light-show-problems">{draft.problems!.map((p) => <li key={p}>⚠ {p}</li>)}</ul>
              )}

              <ContextEditor draft={draft} edit={edit} playingUri={status?.playing_from ?? null} toast={toast} />

              <div className="show-playlist-options">
                <label title="Start following by itself when one of its playlists starts playing">
                  <input type="checkbox" checked={draft.auto_follow}
                    onChange={(e) => edit((d) => { d.auto_follow = e.target.checked; })} /> Auto-follow</label>
                <label title="Also apply a listed song's steps when that song plays from anywhere (Liked Songs on shuffle)">
                  <input type="checkbox" checked={draft.follow_songs_anywhere}
                    onChange={(e) => edit((d) => { d.follow_songs_anywhere = e.target.checked; })} /> Follow its songs anywhere</label>
              </div>

              <section className="show-playlist-section">
                <h4>On start <HelpLink topic="show-playlist-steps" /></h4>
                <div className="show-playlist-seq">
                  <span className="light-show-param-label">Start a sequence</span>
                  <SearchSelect value={draft.on_start.sequence_id ?? ''} options={[{ value: '', label: '— none —' }, ...seqOptions]}
                    placeholder="— none —" width="100%"
                    onChange={(v) => edit((d) => { d.on_start.sequence_id = v || null; })} />
                  {draft.on_start.sequence_id && (
                    <label title="Stop a sequence that is already running to start this one">
                      <input type="checkbox" checked={draft.on_start.replace_running_sequence}
                        onChange={(e) => edit((d) => { d.on_start.replace_running_sequence = e.target.checked; })} />
                      replace a running sequence</label>
                  )}
                </div>
                <StepList steps={draft.on_start.steps} options={setOptions}
                  onChange={(steps) => edit((d) => { d.on_start.steps = steps; })} />
              </section>

              <section className="show-playlist-section">
                <h4>Songs</h4>
                {draft.songs.length === 0 && <p className="muted">Add the songs that should arm something.</p>}
                <ol className="show-playlist-songs">
                  {draft.songs.map((song, i) => (
                    <SongCard key={song.id ?? song.uri} song={song} index={i} count={draft.songs.length}
                      options={setOptions} clip={clip}
                      onCopy={() => { setClip(song.steps); toast(`Copied ${song.title || 'the song'}'s steps`, 'success'); }}
                      onChange={(next) => edit((d) => { d.songs[i] = next; })}
                      onMove={(delta) => edit((d) => { d.songs = reorder(d.songs, i, i + delta); })}
                      onRemove={() => edit((d) => { d.songs.splice(i, 1); })} />
                  ))}
                </ol>
                <SongSearch chosen={new Set(draft.songs.map((s) => s.uri))} toast={toast}
                  onAdd={(s) => edit((d) => { d.songs.push(newSong(s.uri, s.title, s.artist)); })} />
              </section>

              <section className="show-playlist-section">
                <h4>Other songs</h4>
                <label className="light-show-param">
                  <span className="light-show-param-label">A song not listed above</span>
                  <select value={draft.unlisted_song}
                    onChange={(e) => edit((d) => { d.unlisted_song = e.target.value as ShowPlaylist['unlisted_song']; })}>
                    <option value="default">uses the default steps below</option>
                    <option value="nothing">arms nothing</option>
                  </select>
                </label>
                {draft.unlisted_song === 'default' && (
                  draft.default_song
                    ? <StepList steps={draft.default_song.steps} options={setOptions}
                        onChange={(steps) => edit((d) => { if (d.default_song) d.default_song.steps = steps; })} />
                    : <button onClick={() => edit((d) => { d.default_song = { uri: '', title: 'Default', artist: '', steps: [], enabled: true }; })}>
                        + Default steps</button>
                )}
              </section>

              <section className="show-playlist-section">
                <h4>On end <span className="muted">(when the music leaves the playlist)</span></h4>
                <StepList steps={draft.on_end.steps} options={setOptions}
                  onChange={(steps) => edit((d) => { d.on_end.steps = steps; })} />
                <label><input type="checkbox" checked={draft.on_end.end_show}
                  onChange={(e) => edit((d) => { d.on_end.end_show = e.target.checked; })} /> End show</label>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function ContextEditor({ draft, edit, playingUri, toast }: {
  draft: ShowPlaylist; edit: (fn: (d: ShowPlaylist) => void) => void;
  playingUri: { uri: string; name: string | null } | null; toast: Toast;
}) {
  const [recent, setRecent] = useState<SpotifyContext[]>([]);
  const [paste, setPaste] = useState('');
  useEffect(() => {
    void spotfxGet<{ recent: SpotifyContext[] }>('/spotify/contexts').then((r) => setRecent(r.recent)).catch(() => undefined);
  }, []);
  const add = async (uri: string, name?: string | null) => {
    if (draft.contexts.includes(uri)) return;
    let label = name || '';
    if (!label) {
      label = (await apiGet<{ name: string }>(`/light-show/context-name?uri=${encodeURIComponent(uri)}`)
        .catch(() => ({ name: '' }))).name;
    }
    edit((d) => { d.contexts.push(uri); if (label) d.context_names[uri] = label; });
  };
  const offers = [
    ...(playingUri ? [{ context_uri: playingUri.uri, name: playingUri.name || '', type: '' }] : []),
    ...recent.slice().reverse(),
  ].filter((c, i, all) => !draft.contexts.includes(c.context_uri)
    && all.findIndex((x) => x.context_uri === c.context_uri) === i);
  return (
    <section className="show-playlist-section">
      <h4>Spotify playlists it follows</h4>
      {draft.contexts.length === 0 && <p className="muted">None yet — it only runs when started by hand.</p>}
      <ul className="show-playlist-contexts">
        {draft.contexts.map((c) => (
          <li key={c}><span title={c}>{contextLabel(draft, c)}</span>
            <button type="button" aria-label={`Remove ${contextLabel(draft, c)}`}
              onClick={() => edit((d) => { d.contexts = d.contexts.filter((x) => x !== c); delete d.context_names[c]; })}>✕</button>
          </li>
        ))}
      </ul>
      {offers.length > 0 && (
        <div className="show-playlist-offers">
          <span className="muted">Recently played:</span>
          {offers.slice(0, 8).map((c, i) => (
            <button key={c.context_uri} type="button" onClick={() => void add(c.context_uri, c.name)}>
              + {i === 0 && playingUri?.uri === c.context_uri ? 'Playing now: ' : ''}{c.name || c.context_uri}
            </button>
          ))}
        </div>
      )}
      <div className="show-playlist-paste">
        <input type="text" placeholder="…or paste a Spotify playlist link" value={paste}
          aria-label="Spotify playlist link" onChange={(e) => setPaste(e.target.value)} />
        <button type="button" disabled={!paste.trim()} onClick={() => {
          const uri = parseContext(paste);
          if (!uri) { toast('That is not a Spotify playlist or album link', 'error'); return; }
          void add(uri);
          setPaste('');
        }}>Add</button>
      </div>
    </section>
  );
}

function SongCard({ song, index, count, options, clip, onCopy, onChange, onMove, onRemove }: {
  song: SongEntry; index: number; count: number; options: Options; clip: PlaylistStep[] | null;
  onCopy: () => void; onChange: (s: SongEntry) => void; onMove: (delta: number) => void; onRemove: () => void;
}) {
  const [open, setOpen] = useState(song.steps.length === 0);
  return (
    <li className={`show-playlist-song${song.enabled ? '' : ' off'}`}>
      <div className="show-seq-item-head">
        <button type="button" className="show-playlist-toggle" aria-expanded={open}
          onClick={() => setOpen(!open)}>{open ? '▾' : '▸'}</button>
        <span className="show-seq-num">{index + 1}</span>
        <b className="show-playlist-song-title">{songWord(song.title, song.artist, song.uri)}</b>
        {!open && <span className="muted show-playlist-summary">
          {song.steps.length ? (song.summary || `${song.steps.length} step${song.steps.length === 1 ? '' : 's'}`) : 'nothing yet'}</span>}
        <span className="light-show-step-tools">
          <button disabled={index === 0} onClick={() => onMove(-1)} aria-label="Move up">↑</button>
          <button disabled={index === count - 1} onClick={() => onMove(1)} aria-label="Move down">↓</button>
          <button onClick={onCopy} disabled={song.steps.length === 0} title="Copy this song's steps" aria-label="Copy steps">📋</button>
          <button onClick={() => clip && onChange({ ...song, steps: [...song.steps, ...copyEntrySteps(clip)] })}
            disabled={!clip} title="Paste copied steps onto this song" aria-label="Paste steps">⎘</button>
          <button onClick={onRemove} aria-label="Remove song">✕</button>
        </span>
      </div>
      {open && (
        <>
          <label><input type="checkbox" checked={song.enabled}
            onChange={(e) => onChange({ ...song, enabled: e.target.checked })} /> on</label>
          <StepList steps={song.steps} options={options} onChange={(steps) => onChange({ ...song, steps })} />
        </>
      )}
    </li>
  );
}

function StepList({ steps, options, onChange }: {
  steps: PlaylistStep[]; options: Options; onChange: (s: PlaylistStep[]) => void;
}) {
  const update = (i: number, next: PlaylistStep) => {
    const out = steps.slice();
    out[i] = next;
    onChange(out);
  };
  return (
    <div className="show-playlist-steps">
      {steps.map((st, i) => (
        <div key={st.id ?? i} className={`show-playlist-step${st.enabled ? '' : ' off'}`}>
          <SearchSelect value={st.set_id ?? ''} options={options} placeholder="— pick a set —" width="100%"
            onChange={(v) => update(i, { ...st, set_id: v || null })} />
          <TimingPicker value={st.on} onChange={(on) => update(i, { ...st, on })} />
          <span className="show-playlist-step-flags">
            {st.on !== 'song_start' && (
              <label title="Stay armed after firing, and fire again every time on this song">
                <input type="checkbox" checked={st.repeat}
                  onChange={(e) => update(i, { ...st, repeat: e.target.checked })} /> repeat</label>
            )}
            {(st.on === 'high' || st.on === 'low') && (
              <label title="Start early so this set's fades complete ON the trigger">
                <input type="checkbox" checked={st.finish_on_mark}
                  onChange={(e) => update(i, { ...st, finish_on_mark: e.target.checked })} /> finish on the mark</label>
            )}
            <label><input type="checkbox" checked={st.enabled}
              onChange={(e) => update(i, { ...st, enabled: e.target.checked })} /> on</label>
            <button type="button" onClick={() => onChange(steps.filter((_x, j) => j !== i))} aria-label="Remove step">✕</button>
          </span>
          {(st.problems?.length ?? 0) > 0 && (
            <span className="light-show-problems">{st.problems!.join('; ')}</span>
          )}
        </div>
      ))}
      <button type="button" onClick={() => onChange([...steps, newStep()])}>+ Step</button>
    </div>
  );
}

function TimingPicker({ value, onChange }: { value: PlaylistStep['on']; onChange: (t: PlaylistStep['on']) => void }) {
  return (
    <div className="light-show-run-set-actions show-seq-arm" role="radiogroup" aria-label="When">
      {TIMING_ORDER.map((t) => (
        <button key={t} type="button" role="radio" aria-checked={value === t}
          className={`light-show-run-set-icon-btn${t === 'song_start' ? ' fire' : ''}${value === t ? ' armed' : ''}`}
          title={TIMING_LABEL[t]} aria-label={TIMING_LABEL[t]} onClick={() => onChange(t)}>
          <Icon name={TIMING_ICON[t]} size={20} />
        </button>
      ))}
      <span className="muted show-seq-arm-word">{TIMING_LABEL[value]}</span>
    </div>
  );
}

/** Add a song: a search over the songs SPECTRA knows (his profile library,
 * GET /light-show/songs), plus the one playing now. */
function SongSearch({ chosen, onAdd, toast }: {
  chosen: Set<string>; onAdd: (s: SongRef) => void; toast: Toast;
}) {
  const [q, setQ] = useState('');
  const [found, setFound] = useState<SongRef[]>([]);
  const [playing, setPlaying] = useState<SongRef | null>(null);
  useEffect(() => {
    let live = true;
    const t = window.setTimeout(() => {
      apiGet<{ songs: SongRef[]; playing: SongRef | null }>(`/light-show/songs?q=${encodeURIComponent(q)}&limit=20`)
        .then((r) => { if (live) { setFound(q.trim() ? r.songs : []); setPlaying(r.playing); } })
        .catch((e) => toast(String(e), 'error'));
    }, 200);
    return () => { live = false; window.clearTimeout(t); };
  }, [q, toast]);
  return (
    <div className="show-seq-songs show-playlist-song-search">
      <input type="search" placeholder="+ Song: search by title or artist…" value={q}
        aria-label="Search songs" onChange={(e) => setQ(e.target.value)} />
      {playing && !chosen.has(playing.uri) && (
        <button type="button" className="show-seq-playing" onClick={() => onAdd(playing)}>
          + Playing now: {songWord(playing.title, playing.artist)}
        </button>
      )}
      <ul className="show-seq-song-results">
        {found.map((s) => (
          <li key={s.uri}>
            <span>{songWord(s.title, s.artist)}</span>
            <button type="button" disabled={chosen.has(s.uri)} onClick={() => onAdd(s)}
              aria-label={`Add ${s.title}`}>{chosen.has(s.uri) ? 'Added' : '+ Add'}</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
