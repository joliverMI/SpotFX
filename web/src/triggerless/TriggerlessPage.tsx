/** Triggerless Profiles — genre-keyed event mappings + embedded-pipeline
 * training (port of frontend/triggerless.html). Event pickers reuse the
 * events page's SearchSelect. Train opens a dialog (now / schedule at a
 * time / queue right after); Cancel stays a 500ms long-press. */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiDel, apiGet, apiPost } from '../api/client';
import { useEvents } from '../api/queries';
import SearchSelect from '../components/forms/SearchSelect';
import { CsvInput } from '../components/forms/inputs';
import { useToast } from '../components/Toast';
import { useLongPress } from '../lib/useLongPress';
import { uuid } from '../lib/uid';

type TLProfile = Record<string, unknown> & {
  id: string;
  name: string;
  genres?: string[];
  is_default?: boolean;
  training_uris?: string[];
  embedded_only_uris?: string[];
};

interface TrainingSong { uri: string; title?: string; artist?: string; trigger_count?: number; }

interface TuneProgress {
  running: boolean;
  profile_id?: string;
  profile_name?: string;
  phase?: string;
  pct?: number;
}

interface ScheduleEntry {
  id: string;
  profile_id: string;
  profile_name?: string;
  at: string;              // "HH:MM" or "after"
  due_at?: string | null;  // ISO timestamp for timed entries
}

interface HistoryRun {
  profile_id?: string;
  profile_name?: string;
  trigger?: string;
  finished_at?: string;
  status?: string;         // completed | failed | cancelled
  error?: string | null;
  improved?: boolean;
  baseline_f1?: number;
  tuned_f1?: number;
}

interface TuneResult {
  cancelled?: boolean;
  improved?: boolean;
  baseline_f1?: number;
  tuned_f1?: number;
  improvement_pct?: number;
  songs_used?: number;
  timestamp?: number;
  duration_s?: number;
  scene_triggers?: number;
  flare_triggers?: number;
  total_triggers?: number;
  score_breakdown?: Record<string, { f1: number; precision: number; recall: number; weight?: number }>;
  best_params?: Record<string, unknown>;
  song_list?: { artist?: string; title?: string }[];
}

/** [section, [slotKey, label, hint?][]] — each slot has <key>_event_id + <key>_labels. */
const EVENT_SECTIONS: [string, [string, string][]][] = [
  ['Shared Events', [
    ['song_start', 'Song Start'], ['song_end', 'Song End'],
    ['scene_fill', 'Scene Fill'], ['flare', 'Flare'],
  ]],
  ['Analyzed Mode (embedded pipeline, requires librosa)', [
    ['beat_start', 'Beat Start'], ['quiet', 'Quiet'], ['drop', 'Drop'],
    ['lull', 'Lull'], ['charge', 'Charge'],
  ]],
  ['Flare Tiers (Analyzed)', [
    ['flare_low', 'Flare Low (subtle)'], ['flare_mid', 'Flare Mid (moderate)'],
    ['flare_high', 'Flare High (clear musical element)'],
    ['flare_scene', 'Flare Scene (top-tier burst → scene update)'],
  ]],
];

const SCORE_DEFS: Record<string, string> = {
  drop: 'Bass re-entry after silence',
  scene_change: 'Energy/timbral shift (scene trigger)',
  structural: 'Beat start, lull, charge, quiet',
  flare: 'Legacy single-tier flare',
  flare_low: 'Subtle flare (FPs okay)',
  flare_mid: 'Moderate flare',
  flare_high: 'Clear musical element flare',
  flare_scene: 'Scene-level flare burst (top tier)',
  song_start: 'Song beginning marker',
  song_end: 'Fade-out detection',
};

function Section({ title, children, defaultOpen = false }: {
  title: React.ReactNode; children: React.ReactNode; defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <>
      <div style={{
        fontSize: 13, fontWeight: 600, margin: '16px 0 8px 0', paddingBottom: 4,
        borderBottom: '1px solid var(--border)', cursor: 'pointer', userSelect: 'none',
      }} onClick={() => setOpen((o) => !o)}>
        <span style={{ marginRight: 6 }}>{open ? '▼' : '▶'}</span>{title}
      </div>
      {open && children}
    </>
  );
}

export default function TriggerlessPage() {
  const toast = useToast();
  const qc = useQueryClient();
  const longPress = useLongPress(500);

  const { data: profiles = [], isLoading } = useQuery({
    queryKey: ['tl-profiles'],
    queryFn: () => apiGet<TLProfile[]>('/ai-triggers/training-profiles'),
  });
  const { data: events = [] } = useEvents();
  const { data: trainingSongs = [] } = useQuery({
    queryKey: ['training-songs'],
    queryFn: () => apiGet<TrainingSong[]>('/ai-triggers/training-songs'),
    retry: false,
  });

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [draft, setDraft] = useState<TLProfile | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  const selected = profiles.find((p) => p.id === selectedId) ?? null;
  useEffect(() => {
    setDraft(selected ? JSON.parse(JSON.stringify(selected)) as TLProfile : null);
  }, [selectedId, selected]);

  const set = (k: string, v: unknown) => setDraft((d) => (d ? { ...d, [k]: v } : d));
  const invalidate = () => qc.invalidateQueries({ queryKey: ['tl-profiles'] });

  const eventOptions = useMemo(
    () => events.map((e) => ({
      value: e.id,
      label: e.name + (e.labels?.length ? ` [${e.labels.join(', ')}]` : ''),
    })),
    [events],
  );

  // ── Training run state ─────────────────────────────────────────────────────
  const [trainingId, setTrainingId] = useState<string | null>(null);
  const [banner, setBanner] = useState<TuneProgress | null>(null);
  const [trainStatus, setTrainStatus] = useState<{ text: string; color: string } | null>(null);
  const [results, setResults] = useState<Record<string, TuneResult>>({});
  const trainingIdRef = useRef(trainingId);
  trainingIdRef.current = trainingId;

  // Poll progress while a run is active (also picks up runs started elsewhere).
  useEffect(() => {
    if (!trainingId) return;
    const t = setInterval(async () => {
      try {
        const prog = await apiGet<TuneProgress>(`/ai-triggers/training-profiles/${trainingId}/tune/progress`);
        if (prog.running) setBanner(prog);
      } catch { /* transient */ }
    }, 1500);
    return () => clearInterval(t);
  }, [trainingId]);

  // Resume banner if a run is active on page load (survives navigation).
  useEffect(() => {
    void (async () => {
      try {
        const prog = await apiGet<TuneProgress>('/ai-triggers/tune/active');
        if (prog.running && prog.profile_id) {
          setTrainingId(prog.profile_id);
          setBanner(prog);
        }
      } catch { /* none active */ }
    })();
  }, []);

  const save = async (p: TLProfile | null = draft): Promise<boolean> => {
    if (!p) return false;
    try {
      await apiPost('/ai-triggers/training-profiles', p);
      await invalidate();
      return true;
    } catch (e) {
      toast(`Error: ${e instanceof Error ? e.message : e}`, 'error');
      return false;
    }
  };

  // ── Schedule + history ─────────────────────────────────────────────────────
  const [trainDialogOpen, setTrainDialogOpen] = useState(false);
  const [scheduleTime, setScheduleTime] = useState('21:00');
  const { data: schedule } = useQuery({
    queryKey: ['tune-schedule'],
    queryFn: () => apiGet<{ entries: ScheduleEntry[]; running: TuneProgress | null }>('/ai-triggers/tune/schedule'),
    refetchInterval: 15000,
  });
  const { data: history } = useQuery({
    queryKey: ['tune-history'],
    queryFn: () => apiGet<{ runs: HistoryRun[] }>('/ai-triggers/tune/history?limit=5'),
    refetchInterval: 30000,
  });
  const scheduleEntries = schedule?.entries ?? [];
  const anyRunning = !!trainingId || !!schedule?.running?.running;
  const lastRun = history?.runs?.[0];
  const invalidateSchedule = () => qc.invalidateQueries({ queryKey: ['tune-schedule'] });

  const scheduleTune = async (at: string) => {
    if (!draft) return;
    await save();
    try {
      await apiPost('/ai-triggers/tune/schedule', { profile_id: draft.id, at });
      toast(at === 'after' ? 'Queued right after the pending run' : `Scheduled for ${at}`, 'success');
      setTrainDialogOpen(false);
      await invalidateSchedule();
    } catch (e) {
      toast(`Error: ${e instanceof Error ? e.message : e}`, 'error');
    }
  };

  const removeScheduleEntry = async (entryId: string) => {
    try {
      await apiDel(`/ai-triggers/tune/schedule/${entryId}`);
      await invalidateSchedule();
    } catch (e) {
      toast(`Error: ${e instanceof Error ? e.message : e}`, 'error');
    }
  };

  const train = async () => {
    if (!draft || trainingId) return;
    await save();
    setTrainDialogOpen(false);
    const profileId = draft.id;
    setTrainStatus({ text: 'Training started...', color: '#ffb74d' });
    setTrainingId(profileId);
    setBanner({ running: true, profile_name: draft.name, phase: 'starting...', pct: 0 });
    try {
      const result = await apiPost<TuneResult>(`/ai-triggers/training-profiles/${profileId}/tune`, {});
      setResults((r) => ({ ...r, [profileId]: result }));
      if (result.cancelled) {
        setTrainStatus({ text: 'Training cancelled — old parameters kept.', color: 'var(--text-muted)' });
      } else if (result.improved) {
        setTrainStatus({
          text: `Improved: ${result.baseline_f1} → ${result.tuned_f1} (+${result.improvement_pct}%)`,
          color: '#81c784',
        });
        await invalidate();
      } else {
        setTrainStatus({
          text: `No improvement found (F1=${result.baseline_f1}, ${result.songs_used} songs).`,
          color: 'var(--text-muted)',
        });
      }
    } catch (e) {
      setTrainStatus({ text: `Failed: ${e instanceof Error ? e.message : e}`, color: '#e74c3c' });
    } finally {
      setTrainingId(null);
      setBanner(null);
    }
  };

  const cancelTrain = async () => {
    if (!trainingIdRef.current) return;
    try {
      await apiPost(`/ai-triggers/training-profiles/${trainingIdRef.current}/tune/cancel`, {});
      setBanner((b) => (b ? { ...b, phase: 'Cancelling...' } : b));
    } catch { /* ignore */ }
  };

  const visible = useMemo(() => {
    const q = search.toLowerCase();
    return q
      ? profiles.filter((p) =>
          (p.name || '').toLowerCase().includes(q) ||
          (p.genres || []).some((g) => g.toLowerCase().includes(q)))
      : profiles;
  }, [profiles, search]);

  const songUris = [...(draft?.training_uris ?? []), ...(draft?.embedded_only_uris ?? [])];
  const result = draft ? results[draft.id] : undefined;
  const phaseLabels: Record<string, string> = {
    loading: 'Loading songs...', scene: 'Tuning scenes...', flare: 'Tuning flares...',
    placement: 'Tuning placement/intensity...',
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 16, alignItems: 'start' }}>
      {/* ── List ── */}
      <div className="card" style={{ maxHeight: 'calc(100vh - 80px)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
          <input type="text" placeholder="Search..." value={search} style={{ flex: 1 }}
            onChange={(e) => setSearch(e.target.value)} />
          <button className="primary" style={{ fontSize: 12 }} onClick={async () => {
            const id = uuid();
            await apiPost('/ai-triggers/training-profiles', { id, name: 'New Profile', genres: [], is_default: false });
            toast('Created', 'success');
            await invalidate();
            setSelectedId(id);
          }}>+ New</button>
        </div>
        <div style={{ overflowY: 'auto', flex: 1, minHeight: 0 }}>
          {isLoading && <div className="empty-note" style={{ padding: 8 }}>Loading…</div>}
          {!isLoading && !visible.length && (
            <div style={{ color: 'var(--text-muted)', padding: 8, fontSize: 13 }}>No profiles yet</div>
          )}
          {visible.map((p) => (
            <div key={p.id} className={`pane-row${p.id === selectedId ? ' selected' : ''}`}
              style={{ flexDirection: 'column', alignItems: 'stretch', gap: 2 }}
              onClick={() => setSelectedId(p.id)}>
              <div style={{ fontWeight: 600, fontSize: 14 }}>
                {p.name || '(unnamed)'}
                {p.is_default && (
                  <span style={{
                    fontSize: 10, background: 'rgba(29,185,84,0.15)', color: 'var(--accent)',
                    padding: '1px 6px', borderRadius: 8, marginLeft: 6,
                  }}>DEFAULT</span>
                )}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                {(p.genres || []).length ? p.genres!.join(', ') : 'No genres'}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Editor ── */}
      {draft ? (
        <div className="card" style={{ maxHeight: 'calc(100vh - 80px)', overflowY: 'auto' }}>
          {/* Training banner */}
          {banner && (
            <div style={{
              fontSize: 12, background: 'var(--surface)', border: '1px solid var(--border)',
              borderRadius: 6, padding: '10px 14px', marginBottom: 14,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontWeight: 600 }}>{banner.profile_name || '—'}</span>
                <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                  {phaseLabels[banner.phase ?? ''] || banner.phase || 'loading...'}
                </span>
                <span style={{ fontWeight: 600, color: '#ffb74d', minWidth: 42, textAlign: 'right' }}>
                  {(banner.pct ?? 0).toFixed(1)}%
                </span>
                <button
                  style={{ marginLeft: 'auto', fontSize: 11, padding: '2px 10px', background: 'rgba(231,76,60,0.15)', color: '#e74c3c', borderColor: '#e74c3c' }}
                  title="Hold 500ms to cancel"
                  {...longPress(() => void cancelTrain())}
                >
                  Cancel
                </button>
              </div>
              <div style={{ height: 4, background: 'var(--surface2)', borderRadius: 2, marginTop: 6, overflow: 'hidden' }}>
                <div style={{ height: '100%', background: '#ffb74d', borderRadius: 2, width: `${banner.pct ?? 0}%`, transition: 'width 0.3s ease' }} />
              </div>
            </div>
          )}

          {/* Actions */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
            <button className="primary" onClick={() => { void save().then((ok) => ok && toast('Saved', 'success')); }}>Save</button>
            <button
              disabled={!!trainingId}
              style={{ background: 'rgba(255,152,0,0.15)', color: '#ffb74d', borderColor: '#ffb74d' }}
              title="Train now, or schedule for later"
              onClick={() => setTrainDialogOpen(true)}
            >
              Train
            </button>
            <button onClick={async () => {
              const d = { ...draft, id: uuid(), name: `${draft.name} (copy)`, is_default: false };
              if (await save(d)) { toast('Duplicated', 'success'); setSelectedId(d.id); }
            }}>Duplicate</button>
            <button className="danger" onClick={async () => {
              if (!confirm(`Delete "${draft.name}"?`)) return;
              await apiDel(`/ai-triggers/training-profiles/${draft.id}`);
              setSelectedId(null);
              toast('Deleted', 'success');
              await invalidate();
            }}>Delete</button>
          </div>
          {trainStatus && (
            <div style={{ fontSize: 12, color: trainStatus.color, marginBottom: 8 }}>{trainStatus.text}</div>
          )}

          {/* Scheduled queue */}
          {scheduleEntries.length > 0 && (
            <div style={{ fontSize: 12, marginBottom: 8, display: 'flex', flexDirection: 'column', gap: 3 }}>
              {scheduleEntries.map((e, i) => (
                <div key={e.id} style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--text-muted)' }}>
                  <span>⏰</span>
                  <span style={{ color: 'var(--text)' }}>{e.profile_name || e.profile_id}</span>
                  <span>
                    {e.at === 'after'
                      ? (i === 0 && !anyRunning ? 'next up' : 'right after previous')
                      : `at ${e.at}${e.due_at ? ` (${new Date(e.due_at).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })})` : ''}`}
                  </span>
                  <button title="Remove from schedule"
                    style={{ fontSize: 11, padding: '0 6px', marginLeft: 4 }}
                    onClick={() => void removeScheduleEntry(e.id)}>×</button>
                </div>
              ))}
            </div>
          )}

          {/* Last run outcome (surfaces scheduled-run failures) */}
          {lastRun?.status === 'failed' && (
            <div style={{ fontSize: 12, color: '#e74c3c', marginBottom: 8 }}>
              Last training run failed ({lastRun.profile_name}, {lastRun.finished_at}): {lastRun.error}
              <span style={{ color: 'var(--text-muted)' }}> — full log in storage/tune_runs.log</span>
            </div>
          )}

          {/* Profile info */}
          <div className="field">
            <label>Name</label>
            <input type="text" value={draft.name} style={{ width: '100%' }}
              onChange={(e) => set('name', e.target.value)} />
          </div>
          <div className="field">
            <label>Genres (comma-separated)</label>
            <CsvInput key={`${draft.id}-genres`} placeholder="reggaeton, trap latino"
              value={draft.genres ?? []} style={{ width: '100%' }}
              onChange={(v) => set('genres', v)} />
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 13, marginBottom: 8 }}>
            <input type="checkbox" checked={!!draft.is_default}
              onChange={(e) => set('is_default', e.target.checked)} />
            Default profile (fallback when no genre match)
          </label>
          <div className="field" style={{ marginBottom: 12 }}>
            <label title="Starting intensity scale for songs matching these genres. Songs with their own (user/auto) value ignore this; a future backfill may stamp it onto un-set songs.">
              Intensity scale (genre default) — {Math.round(((draft.default_intensity_scale as number) ?? 1) * 100)}%
            </label>
            <input type="range" min={0} max={200} step={5} style={{ width: 260, accentColor: 'var(--accent)' }}
              value={Math.round(((draft.default_intensity_scale as number) ?? 1) * 100)}
              onChange={(e) => set('default_intensity_scale', parseInt(e.target.value, 10) / 100)} />
          </div>

          {/* Event sections */}
          {EVENT_SECTIONS.map(([title, slots], si) => (
            <Section key={title} title={title} defaultOpen={si === 0 ? false : false}>
              {slots.map(([key, label]) => (
                <div className="field" key={key}>
                  <label>{label}</label>
                  <SearchSelect
                    value={String(draft[`${key}_event_id`] ?? '')}
                    onChange={(v) => set(`${key}_event_id`, v)}
                    options={eventOptions}
                    placeholder="-- None --"
                    width="100%"
                  />
                  <CsvInput key={`${draft.id}-${key}`} placeholder="Filter labels (e.g. -rainbow)"
                    value={(draft[`${key}_labels`] as string[]) ?? []}
                    style={{ width: '100%', fontSize: 11, padding: '3px 6px', marginTop: 3, color: 'var(--text-muted)' }}
                    onChange={(v) => set(`${key}_labels`, v)} />
                </div>
              ))}
              {title.startsWith('Analyzed') && (
                <div style={{ marginTop: 8, display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                  <NumField label="Min trigger spacing (beats)" k="min_trigger_spacing_beats" fb={4} draft={draft} set={set} />
                  <NumField label="Min scene spacing (beats)" k="min_scene_change_spacing_beats" fb={16} draft={draft} set={set} />
                  <NumField label="Flare max gap (beats)" k="flare_max_gap_beats" fb={32} draft={draft} set={set} />
                </div>
              )}
            </Section>
          ))}

          <Section title="Simple Mode (interval-based, no librosa)">
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              <NumField label="Scene interval (sec)" k="scene_change_interval_s" fb={30} draft={draft} set={set} />
              <NumField label="Flare interval (sec)" k="flare_interval_s" fb={15} draft={draft} set={set} />
              <NumField label="End pre-fire (ms)" k="end_pre_fire_ms" fb={5000} step={500} draft={draft} set={set} />
            </div>
          </Section>

          <Section title={<>Training Songs <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 400 }}>{songUris.length} songs</span></>}>
            <button style={{ fontSize: 12, marginBottom: 6 }} onClick={() => setPickerOpen(true)}>+ Add Song</button>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
              {songUris.map((uri) => {
                const song = trainingSongs.find((s) => s.uri === uri);
                const label = song ? `${song.artist} - ${song.title}` : uri.split(':').pop();
                return (
                  <span key={uri} className="chip" style={{ gap: 4 }}>
                    {label}
                    <span style={{ cursor: 'pointer', fontSize: 14, marginLeft: 2 }}
                      onClick={() => setDraft({
                        ...draft,
                        training_uris: (draft.training_uris ?? []).filter((u) => u !== uri),
                        embedded_only_uris: (draft.embedded_only_uris ?? []).filter((u) => u !== uri),
                      })}>
                      ×
                    </span>
                  </span>
                );
              })}
            </div>
          </Section>

          {/* Last training results */}
          {result && !result.cancelled && (
            <Section title="Last Training Results">
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'auto auto auto', gap: '3px 14px', marginBottom: 8 }}>
                  <span style={{ color: 'var(--text)' }}>Result</span>
                  <span style={{ fontFamily: 'monospace', fontSize: 11, color: result.improved ? '#81c784' : 'var(--text-muted)' }}>
                    {result.improved ? 'Improved' : 'No improvement'}
                  </span>
                  <span style={{ fontSize: 11, opacity: 0.5 }}>
                    {result.baseline_f1} → {result.tuned_f1} ({(result.improvement_pct ?? 0) > 0 ? '+' : ''}{result.improvement_pct}%)
                  </span>
                  <span style={{ color: 'var(--text)' }}>When</span>
                  <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{result.timestamp ? new Date(result.timestamp * 1000).toLocaleString() : '—'}</span>
                  <span />
                  <span style={{ color: 'var(--text)' }}>Duration</span>
                  <span style={{ fontFamily: 'monospace', fontSize: 11 }}>
                    {result.duration_s ? (result.duration_s < 60 ? `${result.duration_s}s` : `${(result.duration_s / 60).toFixed(1)}min`) : '—'}
                  </span>
                  <span />
                  <span style={{ color: 'var(--text)' }}>Songs</span>
                  <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{result.songs_used}</span>
                  <span />
                  <span style={{ color: 'var(--text)' }}>Scene triggers</span>
                  <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{result.scene_triggers ?? '—'}</span>
                  <span />
                  <span style={{ color: 'var(--text)' }}>Flare triggers</span>
                  <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{result.flare_triggers ?? '—'}</span>
                  <span />
                  <span style={{ color: 'var(--text)' }}>Total triggers</span>
                  <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{result.total_triggers ?? '—'}</span>
                  <span />
                </div>
                {result.score_breakdown && !!Object.keys(result.score_breakdown).length && (
                  <div style={{ borderTop: '1px solid var(--border)', paddingTop: 8, marginTop: 4 }}>
                    <div style={{ fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>Score Breakdown</div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'auto auto auto', gap: '3px 14px' }}>
                      {Object.entries(result.score_breakdown)
                        .sort((a, b) => (b[1].weight || 1) - (a[1].weight || 1))
                        .map(([cat, sc]) => (
                          <React.Fragment key={cat}>
                            <span style={{ color: 'var(--text)' }}>{cat}</span>
                            <span style={{
                              fontFamily: 'monospace', fontSize: 11,
                              color: sc.f1 >= 0.7 ? '#81c784' : sc.f1 >= 0.4 ? '#ffb74d' : '#e74c3c',
                            }}>
                              {sc.f1.toFixed(3)}{' '}
                              <span style={{ opacity: 0.5, fontSize: 10 }}>
                                P={sc.precision.toFixed(2)} R={sc.recall.toFixed(2)} x{sc.weight ?? 1}
                              </span>
                            </span>
                            <span style={{ fontSize: 11, opacity: 0.5 }}>{SCORE_DEFS[cat] ?? ''}</span>
                          </React.Fragment>
                        ))}
                    </div>
                  </div>
                )}
                {result.best_params && !!Object.keys(result.best_params).length && (
                  <div style={{ borderTop: '1px solid var(--border)', paddingTop: 8, marginTop: 8 }}>
                    <div style={{ fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>
                      Parameters {result.improved ? 'Saved' : '(not applied)'}
                    </div>
                    <div style={{ fontFamily: 'monospace', fontSize: 11, opacity: 0.8 }}>
                      {Object.entries(result.best_params).sort().map(([k, v]) => (
                        <div key={k}>{k}: {String(v)}</div>
                      ))}
                    </div>
                  </div>
                )}
                {!!result.song_list?.length && (
                  <Section title={`Songs Used (${result.song_list.length})`}>
                    {result.song_list.map((s, i) => (
                      <div key={i} style={{ fontSize: 11, padding: '2px 0', color: 'var(--text-muted)' }}>
                        <b>{s.artist}</b> — {s.title}
                      </div>
                    ))}
                  </Section>
                )}
              </div>
            </Section>
          )}

          <Section title="Notes">
            <textarea rows={3} placeholder="Describe the vibe, tuning notes, etc."
              value={String(draft.notes ?? draft.description ?? '')}
              style={{ width: '100%', resize: 'vertical' }}
              onChange={(e) => set('notes', e.target.value)} />
          </Section>
        </div>
      ) : (
        <p className="empty-note" style={{ marginTop: 24 }}>Select a profile, or create one with + New.</p>
      )}

      {/* Train dialog: now / schedule at time / queue right after */}
      {trainDialogOpen && draft && (
        <div onClick={() => setTrainDialogOpen(false)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100,
                   display: 'flex', alignItems: 'flex-start', justifyContent: 'center', paddingTop: '18vh' }}>
          <div className="card" onClick={(e) => e.stopPropagation()}
            style={{ width: 380, maxWidth: '92vw', margin: 0 }}>
            <div className="card-title">Train “{draft.name}”</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <button className="primary" disabled={anyRunning}
                title={anyRunning ? 'Another training run is active — schedule or queue instead' : 'Start the full tuning run now'}
                onClick={() => void train()}>
                Train now{anyRunning ? ' (busy)' : ''}
              </button>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <button style={{ flex: 1 }} onClick={() => void scheduleTune(scheduleTime)}>
                  Schedule at
                </button>
                <input type="time" value={scheduleTime} style={{ width: 110 }}
                  onChange={(e) => setScheduleTime(e.target.value)} />
              </div>
              {(anyRunning || scheduleEntries.length > 0) && (
                <button onClick={() => void scheduleTune('after')}
                  title="Queue this profile right after the running/scheduled tune finishes">
                  Queue right after {scheduleEntries.length > 0
                    ? `“${scheduleEntries[scheduleEntries.length - 1].profile_name}”`
                    : 'the current run'}
                </button>
              )}
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                Scheduled times run at the next occurrence (today if still ahead, else tomorrow) and
                survive restarts. Improved parameters apply automatically; failures are logged to
                storage/tune_runs.log and shown here.
              </div>
              <button onClick={() => setTrainDialogOpen(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* Song picker */}
      {pickerOpen && draft && (
        <SongPicker
          songs={trainingSongs}
          existing={new Set(songUris)}
          onPick={(uri) => {
            setDraft({ ...draft, embedded_only_uris: [...(draft.embedded_only_uris ?? []), uri] });
          }}
          onClose={() => setPickerOpen(false)}
        />
      )}
    </div>
  );
}

function NumField({ label, k, fb, step, draft, set }: {
  label: string; k: string; fb: number; step?: number;
  draft: TLProfile; set: (k: string, v: unknown) => void;
}) {
  return (
    <div className="field">
      <label>{label}</label>
      <input type="number" min={step ? 0 : 1} step={step ?? 1} style={{ width: 90 }}
        value={Number(draft[k] ?? fb)}
        onChange={(e) => set(k, parseInt(e.target.value) || fb)} />
    </div>
  );
}

function SongPicker({ songs, existing, onPick, onClose }: {
  songs: TrainingSong[];
  existing: Set<string>;
  onPick: (uri: string) => void;
  onClose: () => void;
}) {
  const [q, setQ] = useState('');
  const filtered = songs.filter((s) =>
    !q || (s.title ?? '').toLowerCase().includes(q.toLowerCase()) || (s.artist ?? '').toLowerCase().includes(q.toLowerCase()));
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10,
        padding: 16, width: 500, maxWidth: '90vw', maxHeight: '70vh', overflowY: 'auto',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <b>Add Training Song</b>
          <button style={{ fontSize: 12 }} onClick={onClose}>Close</button>
        </div>
        <input type="text" placeholder="Search by title or artist..." value={q} autoFocus
          style={{ width: '100%', marginBottom: 8 }}
          onChange={(e) => setQ(e.target.value)} />
        <div style={{ maxHeight: '50vh', overflowY: 'auto' }}>
          {!filtered.length && (
            <div style={{ color: 'var(--text-muted)', padding: 8 }}>No matching songs</div>
          )}
          {filtered.map((s) => {
            const added = existing.has(s.uri);
            return (
              <div key={s.uri}
                style={{
                  padding: '6px 8px', borderRadius: 4, fontSize: 13,
                  cursor: added ? 'default' : 'pointer', opacity: added ? 0.4 : 1,
                }}
                onClick={() => { if (!added) onPick(s.uri); }}>
                <b>{s.artist}</b> - {s.title}
                <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 8 }}>
                  {s.trigger_count ?? 0} triggers{added ? ' · added' : ''}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
