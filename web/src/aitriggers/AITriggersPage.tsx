/** AI Triggers — Claude/embedded trigger generation + review workflow
 * (port of frontend/ai_triggers.html). Profile card on top, full-width
 * review panel below; canvas reuses the builder stack. */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, apiDel, apiGet, apiPost } from '../api/client';
import { onMessage } from '../api/ws';
import { useEvents } from '../api/queries';
import SearchSelect from '../components/forms/SearchSelect';
import { useToast } from '../components/Toast';
import { ensureLiveState, useLiveStore } from '../live/liveStore';
import { uuid } from '../lib/uid';
import ReviewPanel from './ReviewPanel';
import {
  AnalyzeResultModal, CostConfirmModal, ExistingTriggersModal,
  LoadSavedModal, ManageProfilesModal, ManualAddModal, SongPickerModal,
} from './modals';
import {
  TP_EVENT_SLOTS,
  type CachedSet, type CostEstimate, type SavedSetSummary, type SongInfo,
  type Suggestion, type TrainingProfile,
} from './types';

const emptyProfile = (): TrainingProfile => ({
  id: '', name: '', description: '', genres: [], is_default: false, notes: '',
  training_uris: [], embedded_only_uris: [], target_uris: [],
  min_trigger_spacing_beats: 4, min_scene_change_spacing_beats: 16,
  fill_min_spacing_beats: 48, flare_max_gap_beats: 32,
});

export default function AITriggersPage() {
  ensureLiveState();
  const toast = useToast();
  const qc = useQueryClient();

  const analysisEnabled = useLiveStore((s) => s.analysisEnabled);
  const autoGenEnabled = useLiveStore((s) => s.autoGenEnabled);

  const { data: events = [] } = useEvents();
  const { data: trainingSongs = [], refetch: refetchTraining } = useQuery({
    queryKey: ['ai-training-songs'],
    queryFn: () => apiGet<SongInfo[]>('/ai-triggers/training-songs'),
    retry: false,
  });
  const { data: candidateSongsBase = [], refetch: refetchCandidates } = useQuery({
    queryKey: ['ai-candidate-songs'],
    queryFn: () => apiGet<SongInfo[]>('/ai-triggers/candidate-songs'),
    retry: false,
  });
  const { data: profiles = [] } = useQuery({
    queryKey: ['ai-profiles'],
    queryFn: () => apiGet<TrainingProfile[]>('/ai-triggers/training-profiles'),
  });
  const { data: savedSets = [] } = useQuery({
    queryKey: ['ai-suggestion-sets'],
    queryFn: () => apiGet<SavedSetSummary[]>('/ai-suggestions'),
    retry: false,
  });
  const pendingReview = savedSets.filter((s) => !s.reviewed && !s.applied).length;

  // Saved-set songs not in the candidate list still need duration/title info.
  const [extraSongs, setExtraSongs] = useState<SongInfo[]>([]);
  const candidateSongs = useMemo(() => {
    const have = new Set(candidateSongsBase.map((s) => s.uri));
    return [...candidateSongsBase, ...extraSongs.filter((s) => !have.has(s.uri))];
  }, [candidateSongsBase, extraSongs]);

  // ── Profile draft ──────────────────────────────────────────────────────────
  const [profile, setProfile] = useState<TrainingProfile>(emptyProfile());
  const [profileId, setProfileId] = useState('');
  const [collapsed, setCollapsed] = useState(false);
  const set = (k: string, v: unknown) => setProfile((p) => ({ ...p, [k]: v }));

  const loadProfile = (id: string) => {
    setProfileId(id);
    const p = profiles.find((x) => x.id === id);
    setProfile(p ? JSON.parse(JSON.stringify(p)) as TrainingProfile : emptyProfile());
    setCache({});
    setReviewed(new Set());
    setShowReview(false);
  };

  const saveProfile = async (): Promise<string> => {
    const id = profileId || uuid();
    await apiPost('/ai-triggers/training-profiles', {
      ...profile,
      id,
      name: (profile.name || '').trim() || 'Untitled Profile',
    });
    setProfileId(id);
    await qc.invalidateQueries({ queryKey: ['ai-profiles'] });
    return id;
  };

  // ── Review state ───────────────────────────────────────────────────────────
  const [cache, setCache] = useState<Record<string, CachedSet>>({});
  const [reviewed, setReviewed] = useState<Set<string>>(new Set());
  const [targetIdx, setTargetIdx] = useState(0);
  const [showReview, setShowReview] = useState(false);
  const [postApply, setPostApply] = useState<{ msg: string; added?: boolean } | null>(null);
  const recentEventIds = useRef<string[]>([]);

  const targetUris = profile.target_uris ?? [];
  const currentUri = targetUris[targetIdx] ?? null;
  const cached = currentUri ? cache[currentUri] : undefined;

  // ── Generation ─────────────────────────────────────────────────────────────
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);
  const [genProgress, setGenProgress] = useState<{ status: string; pct: number; cost: string; log: string[] } | null>(null);
  const [genError, setGenError] = useState<string | null>(null);

  // ── Modals ─────────────────────────────────────────────────────────────────
  const [picker, setPicker] = useState<'training' | 'embedded' | 'target' | null>(null);
  const [manageOpen, setManageOpen] = useState(false);
  const [loadSavedOpen, setLoadSavedOpen] = useState(false);
  const [existingSong, setExistingSong] = useState<SongInfo | null>(null);
  const [manualAddMs, setManualAddMs] = useState<number | null | 'closed'>('closed');
  const [analyzeText, setAnalyzeText] = useState<string | null>(null);

  useEffect(() => {
    const offs = [
      onMessage('auto_generate_started', (msg) =>
        toast(`Generating AI triggers for ${msg.artist} — ${msg.title}…`, 'info')),
      onMessage('auto_generate_complete', (msg) => {
        toast(`AI triggers ready: ${msg.count} suggestions for ${msg.artist} — ${msg.title}`, 'success');
        void refetchCandidates();
        void qc.invalidateQueries({ queryKey: ['ai-suggestion-sets'] });
      }),
      onMessage('auto_generate_failed', (msg) =>
        toast(`Auto-gen failed for ${msg.title}: ${msg.error}`, 'error')),
    ];
    return () => offs.forEach((off) => off());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const genresMatch = (song: SongInfo): boolean => {
    const pg = (profile.genres ?? []).map((g) => g.toLowerCase());
    const sg = (song.genres ?? []).map((g) => g.toLowerCase());
    if (!pg.length || !sg.length) return false;
    return pg.some((p) => sg.some((s) => p.includes(s) || s.includes(p)));
  };

  const addMatchingVerified = (box: 'training' | 'embedded') => {
    const pg = (profile.genres ?? []).map((g) => g.trim().toLowerCase()).filter(Boolean);
    if (!pg.length) { alert('Add genre tags to the profile first.'); return; }
    const training = new Set(profile.training_uris ?? []);
    const embedded = new Set(profile.embedded_only_uris ?? []);
    let added = 0;
    for (const s of trainingSongs) {
      if (!genresMatch(s)) continue;
      if (box === 'training') {
        if (!training.has(s.uri)) { training.add(s.uri); added++; }
      } else if (!embedded.has(s.uri) && !training.has(s.uri)) {
        embedded.add(s.uri); added++;
      }
    }
    setProfile((p) => ({ ...p, training_uris: [...training], embedded_only_uris: [...embedded] }));
    if (!added) toast('No verified songs match the profile genres.', 'info');
    else toast(`Added ${added} matching song${added !== 1 ? 's' : ''}.`, 'success');
  };

  const addTarget = (song: SongInfo) => {
    if ((profile.target_uris ?? []).includes(song.uri)) return;
    if ((song.trigger_count ?? 0) > 0) { setExistingSong(song); return; }
    set('target_uris', [...(profile.target_uris ?? []), song.uri]);
  };

  // ── Generate flow ──────────────────────────────────────────────────────────
  const generateAll = async () => {
    if (!targetUris.length) { alert('Add at least one target song.'); return; }
    if (!(profile.training_uris ?? []).length) { alert('Add at least one training song.'); return; }
    try {
      const est = await apiPost<CostEstimate>('/ai-triggers/estimate-cost', {
        training_uris: profile.training_uris,
        target_uris: targetUris,
        description: profile.description ?? '',
      });
      setEstimate(est);
    } catch (e) {
      alert(`Cannot generate: ${e instanceof Error ? e.message : e}`);
    }
  };

  const runGeneration = async (model: string) => {
    setEstimate(null);
    setGenError(null);
    setShowReview(false);
    const total = targetUris.length;
    let totalCost = 0;
    const log: string[] = [];
    try {
      for (let i = 0; i < total; i++) {
        const uri = targetUris[i];
        const song = candidateSongs.find((s) => s.uri === uri);
        const modelShort = model.includes('haiku') ? 'Haiku' : 'Sonnet';
        setGenProgress({
          status: `Calling Claude ${modelShort}… ${song?.title || uri} (${i + 1}/${total})`,
          pct: (i / total) * 100,
          cost: totalCost ? `$${totalCost.toFixed(4)} total` : '',
          log: [...log],
        });
        const result = await apiPost<{
          target_title: string; target_artist: string;
          cost_usd?: number; input_tokens?: number; output_tokens?: number;
          suggestions?: Partial<Suggestion>[];
        }>('/ai-triggers/generate', {
          training_uris: profile.training_uris,
          target_uri: uri,
          description: profile.description ?? '',
          model,
          training_profile_id: profileId || '',
          training_profile_name: profiles.find((p) => p.id === profileId)?.name || '',
        });
        totalCost += result.cost_usd ?? 0;
        const sugCount = (result.suggestions ?? []).length;
        log.push(`✓ ${song?.title || uri} — ${sugCount} triggers · ${result.input_tokens ?? 0}+${result.output_tokens ?? 0} tok · $${(result.cost_usd ?? 0).toFixed(4)}`);
        setGenProgress({
          status: `Calling Claude ${modelShort}…`,
          pct: ((i + 1) / total) * 100,
          cost: `$${totalCost.toFixed(4)} total`,
          log: [...log],
        });
        setCache((c) => ({
          ...c,
          [uri]: {
            title: result.target_title,
            artist: result.target_artist,
            songComment: c[uri]?.songComment || '',
            duration_ms: song?.duration_ms || 0,
            generated_at: new Date().toISOString(),
            training_profile_id: profileId || '',
            training_profile_name: profiles.find((p) => p.id === profileId)?.name || '',
            applied: false,
            cost_usd: result.cost_usd ?? 0,
            input_tokens: result.input_tokens ?? 0,
            output_tokens: result.output_tokens ?? 0,
            suggestions: (result.suggestions ?? []).map((s) => ({
              timestamp_ms: Number(s.timestamp_ms ?? 0),
              event_id: String(s.event_id ?? ''),
              confidence: Number(s.confidence ?? 0),
              reasoning: String(s.reasoning ?? ''),
              original_timestamp_ms: Number(s.timestamp_ms ?? 0),
              original_event_id: String(s.event_id ?? ''),
              labels: [], comment: '', manually_added: false, approved: null,
            })),
          },
        }));
      }
      setReviewed(new Set());
      setTargetIdx(0);
      setCollapsed(true);
      setShowReview(true);
    } catch (e) {
      setGenError(`Error: ${e instanceof Error ? e.message : e}`);
    } finally {
      setGenProgress(null);
    }
  };

  const runEmbedded = async () => {
    setEstimate(null);
    const allTrain = [...(profile.training_uris ?? []), ...(profile.embedded_only_uris ?? [])];
    if (!allTrain.length) { toast('Add training songs first.', 'error'); return; }
    if (!targetUris.length) { toast('Add target songs first.', 'error'); return; }
    let applied = 0, failed = 0;
    for (const uri of targetUris) {
      try {
        const r = await apiPost<{ applied?: number }>('/ai-triggers/generate-embedded', {
          target_uri: uri, training_uris: allTrain, training_profile_id: profileId || '',
        });
        applied += r.applied ?? 0;
      } catch {
        failed++;
      }
    }
    if (failed) toast(`Embedded: ${applied} triggers applied, ${failed} song(s) failed.`, 'error');
    else toast(`Embedded: ${applied} triggers applied to ${targetUris.length} song(s).`, 'success');
  };

  // ── Review navigation / lazy fetch of saved sets ──────────────────────────
  const showSong = async (idx: number) => {
    const uri = targetUris[idx];
    if (!uri) return;
    setTargetIdx(idx);
    setPostApply(null);
    if (!cache[uri]) {
      const trackId = uri.split(':').pop();
      try {
        const setData = await apiGet<Record<string, unknown>>(`/ai-suggestions/${trackId}`);
        setCache((c) => ({ ...c, [uri]: savedSetToCache(setData) }));
      } catch {
        return;
      }
    }
    setReviewed((r) => new Set([...r, uri]));
    setShowReview(true);
  };

  const loadSaved = async (trackId: string) => {
    let setData: Record<string, unknown>;
    try {
      setData = await apiGet<Record<string, unknown>>(`/ai-suggestions/${trackId}`);
    } catch (e) {
      alert(`Failed to load: ${e instanceof Error ? e.message : e}`);
      return;
    }
    const uri = String(setData.spotify_uri);
    setCache((c) => ({ ...c, [uri]: savedSetToCache(setData) }));
    // Nav across all unapplied sets — unreviewed first, then newest.
    const unapplied = [...savedSets.filter((s) => !s.applied)].sort((a, b) => {
      const au = !a.reviewed ? 0 : 1, bu = !b.reviewed ? 0 : 1;
      if (au !== bu) return au - bu;
      return (b.generated_at || '').localeCompare(a.generated_at || '');
    });
    const uris = unapplied.map((s) => s.spotify_uri);
    setExtraSongs((x) => [
      ...x,
      ...unapplied
        .filter((s) => !candidateSongs.find((c) => c.uri === s.spotify_uri))
        .map((s) => ({ uri: s.spotify_uri, title: s.title, artist: s.artist, duration_ms: s.duration_ms, mark_count: 0 })),
    ]);
    set('target_uris', uris);
    const idx = Math.max(0, uris.indexOf(uri));
    setTargetIdx(idx);
    setReviewed((r) => new Set([...r, uri]));
    setLoadSavedOpen(false);
    setCollapsed(true);
    setShowReview(true);
    setPostApply(null);
  };

  // ── Review actions ─────────────────────────────────────────────────────────
  const mutateCurrentSet = (fn: (s: CachedSet) => CachedSet) => {
    if (!currentUri) return;
    setCache((c) => (c[currentUri] ? { ...c, [currentUri]: fn(c[currentUri]) } : c));
  };

  const approveHighConf = () => mutateCurrentSet((s) => ({
    ...s,
    suggestions: s.suggestions.map((sg) =>
      (sg.manually_added || sg.confidence >= 0.8) && sg.approved !== false
        ? { ...sg, approved: true } : sg),
  }));

  const applyApproved = async () => {
    if (!currentUri || !cached) return;
    const approved = cached.suggestions
      .filter((s) => s.approved === true)
      .map((s) => ({ timestamp_ms: s.timestamp_ms, event_id: s.event_id }));
    if (!approved.length) { alert('No suggestions approved yet.'); return; }
    try {
      const result = await apiPost<{ applied: number }>('/ai-triggers/apply', {
        target_uri: currentUri,
        suggestions: approved,
        ai_training_profile_id: profileId || '',
      });
      setPostApply({ msg: `✓ Applied ${result.applied} triggers to ${cached.title}.` });
    } catch (e) {
      alert(`Failed to apply: ${e instanceof Error ? e.message : e}`);
    }
  };

  const saveCurrent = async () => {
    if (!currentUri || !cached) return;
    const trackId = currentUri.split(':').pop();
    const body = {
      spotify_uri: currentUri,
      title: cached.title,
      artist: cached.artist,
      duration_ms: cached.duration_ms || 0,
      generated_at: cached.generated_at || new Date().toISOString(),
      training_profile_id: cached.training_profile_id || '',
      training_profile_name: cached.training_profile_name || '',
      suggestions: cached.suggestions.map((s) => ({
        ...s,
        event_name: s.event_name || events.find((e) => e.id === s.event_id)?.name || '',
        approved: s.approved ?? null,
      })),
      song_comment: cached.songComment || '',
      reviewed: true,
      applied: cached.applied || false,
    };
    try {
      await api('PUT', `/ai-suggestions/${trackId}`, body);
      toast('Saved', 'success');
      void qc.invalidateQueries({ queryKey: ['ai-suggestion-sets'] });
    } catch (e) {
      alert(`Save failed: ${e instanceof Error ? e.message : e}`);
    }
  };

  const saveAsTraining = async () => {
    if (!currentUri) return;
    if (!profileId) { alert('Save a training profile first.'); return; }
    if ((profile.training_uris ?? []).includes(currentUri)) {
      setPostApply((p) => (p ? { ...p, added: true } : p));
      return;
    }
    const next = { ...profile, id: profileId, training_uris: [...(profile.training_uris ?? []), currentUri] };
    setProfile(next);
    await apiPost('/ai-triggers/training-profiles', next);
    await qc.invalidateQueries({ queryKey: ['ai-profiles'] });
    void refetchTraining();
    setPostApply((p) => (p ? { msg: `${p.msg} · Added to training!`, added: true } : p));
  };

  const analyzeLearning = async (uris: string[]) => {
    const feedback = uris.flatMap((uri) => {
      const c = cache[uri];
      if (!c) return [];
      const toEntry = (s: Suggestion) => ({
        timestamp_ms: s.timestamp_ms,
        event_name: events.find((e) => e.id === s.event_id)?.name || s.event_id,
        reasoning: s.reasoning || '',
        comment: s.comment || '',
      });
      return [{
        song: `${c.artist} — ${c.title}`,
        song_comment: c.songComment || '',
        approved: c.suggestions.filter((s) => s.approved === true && !s.manually_added).map(toEntry),
        rejected: c.suggestions.filter((s) => s.approved === false).map(toEntry),
        manually_added: c.suggestions.filter((s) => s.manually_added).map((s) => ({
          timestamp_ms: s.timestamp_ms,
          event_name: events.find((e) => e.id === s.event_id)?.name || s.event_id,
          comment: s.comment || '',
        })),
      }];
    });
    if (!feedback.length) { alert('No reviewed songs with feedback.'); return; }
    try {
      const result = await apiPost<{ refined_description?: string }>('/ai-triggers/analyze-learning', {
        current_description: profile.description ?? '',
        feedback,
      });
      setAnalyzeText(result.refined_description || '');
    } catch (e) {
      alert(`Analyze failed: ${e instanceof Error ? e.message : e}`);
    }
  };

  const addSuggestion = (data: { ms: number; eventId: string; labels: string[]; comment: string }) => {
    if (!currentUri || !cache[currentUri]) return;
    const sug: Suggestion = {
      timestamp_ms: data.ms, event_id: data.eventId, confidence: 1.0, reasoning: '',
      original_timestamp_ms: data.ms, original_event_id: data.eventId,
      labels: data.labels, comment: data.comment, manually_added: true, approved: true,
    };
    mutateCurrentSet((s) => ({
      ...s,
      suggestions: [...s.suggestions, sug].sort((a, b) => a.timestamp_ms - b.timestamp_ms),
    }));
    if (data.eventId) {
      recentEventIds.current = [data.eventId, ...recentEventIds.current.filter((id) => id !== data.eventId)];
    }
  };

  const eventOptions = useMemo(
    () => events.map((e) => ({ id: e.id, name: e.name, color: e.color })),
    [events],
  );
  const allReviewed = targetUris.length > 1 && targetUris.every((u) => reviewed.has(u) && cache[u]);
  const summary = `${(profile.name || 'New Profile')} — ${(profile.training_uris ?? []).length} training · ${targetUris.length} target`;

  return (
    <>
      {/* ── Training Profile ── */}
      <div className="card">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', userSelect: 'none', flexWrap: 'wrap' }}
          onClick={() => setCollapsed((c) => !c)}>
          <div className="card-title" style={{ margin: 0 }}>Training Profile</div>
          {collapsed && <span style={{ fontSize: 13, color: 'var(--text-muted)', flex: 1 }}>{summary}</span>}
          <button className="primary" style={{ fontSize: 12, padding: '4px 12px', marginLeft: 'auto' }}
            onClick={(e) => { e.stopPropagation(); void generateAll(); }}>
            ▶ Generate All
          </button>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{collapsed ? '▶' : '▼'}</span>
        </div>

        {!collapsed && (
          <div style={{ marginTop: 12 }}>
            {/* Profile selector row */}
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 10, flexWrap: 'wrap' }}>
              <select value={profileId} style={{ flex: 1, minWidth: 120 }}
                onChange={(e) => loadProfile(e.target.value)}>
                <option value="">— new profile —</option>
                {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <input type="text" placeholder="Profile name" value={profile.name}
                style={{ flex: 1, minWidth: 120 }}
                onChange={(e) => set('name', e.target.value)} />
              <button className="primary" style={{ fontSize: 12 }} onClick={() => void saveProfile()}>Save</button>
              <button style={{ fontSize: 12 }} onClick={() => loadProfile('')}>New</button>
              <button style={{ fontSize: 12 }} title="Copy this profile with a new name"
                onClick={async () => {
                  if (!profileId) { alert('Load a profile to duplicate first.'); return; }
                  const src = profiles.find((p) => p.id === profileId);
                  if (!src) return;
                  const newId = uuid();
                  await apiPost('/ai-triggers/training-profiles', {
                    ...src, id: newId, name: `${src.name || 'Profile'} - Copy`, is_default: false,
                  });
                  await qc.invalidateQueries({ queryKey: ['ai-profiles'] });
                  setProfileId(newId);
                  setProfile({ ...src, id: newId, name: `${src.name || 'Profile'} - Copy`, is_default: false });
                }}>Duplicate</button>
              <button className="danger" style={{ fontSize: 12 }}
                onClick={async () => {
                  if (!profileId || !confirm('Delete this training profile?')) return;
                  await apiDel(`/ai-triggers/training-profiles/${profileId}`);
                  await qc.invalidateQueries({ queryKey: ['ai-profiles'] });
                  loadProfile('');
                }}>Delete</button>
              <button style={{ fontSize: 12 }} title="Search and delete training profiles"
                onClick={() => setManageOpen(true)}>⋯</button>
              <button className={`toggle-btn ${analysisEnabled ? 'active' : ''}`} style={{ fontSize: 12 }}
                title="Enable audio capture for new songs (required for Auto Analyze)"
                onClick={() => void apiPost('/analysis/toggle', {})}>
                Capture Shape: {analysisEnabled ? 'On' : 'Off'}
              </button>
              <button className={`toggle-btn ${autoGenEnabled ? 'active' : ''}`} style={{ fontSize: 12 }}
                title="Auto-generate AI triggers after each shape capture"
                onClick={() => void apiPost(`/control/auto-generate?enabled=${!autoGenEnabled}`)}>
                Auto Analyze: {autoGenEnabled ? 'On' : 'Off'}
              </button>
            </div>

            <div style={{ marginBottom: 10 }}>
              <label style={{ fontSize: 11, color: 'var(--text-muted)' }}>Prompt / vibe description</label>
              <textarea value={String(profile.description ?? '')} style={{ width: '100%', height: 60, resize: 'vertical' }}
                placeholder="e.g. High-energy EDM rave drops, lots of bass, strobe-worthy moments"
                onChange={(e) => set('description', e.target.value)} />
            </div>

            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, marginBottom: 10 }}>
              <div style={{ flex: 1 }}>
                <label style={{ fontSize: 11, color: 'var(--text-muted)' }}>Genre tags (comma-separated)</label>
                <input type="text" placeholder="e.g. edm, dubstep, bass music" style={{ width: '100%' }}
                  value={(profile.genres ?? []).join(', ')}
                  onChange={(e) => set('genres', e.target.value.split(',').map((s) => s.trim()).filter(Boolean))} />
              </div>
              <label style={{ fontSize: 12, whiteSpace: 'nowrap', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5, paddingBottom: 6, marginBottom: 0 }}>
                <input type="checkbox" checked={!!profile.is_default}
                  onChange={(e) => set('is_default', e.target.checked)} />
                Default profile
              </label>
            </div>

            <div style={{ marginBottom: 10 }}>
              <label style={{ fontSize: 11, color: 'var(--text-muted)' }}>Profile Notes</label>
              <textarea value={String(profile.notes ?? '')} style={{ width: '100%', height: 56, resize: 'vertical', fontSize: 12 }}
                placeholder="Running notes about this profile — how it behaves, what to tweak, song observations…"
                onChange={(e) => set('notes', e.target.value)} />
            </div>

            {/* Embedded trigger settings */}
            <details style={{ marginBottom: 10 }}>
              <summary style={{ fontSize: 12, color: 'var(--text-muted)', cursor: 'pointer', userSelect: 'none' }}>
                ⚙ Embedded Trigger Settings
              </summary>
              <div style={{ marginTop: 8, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                <NumSetting label="Min Trigger Spacing" suffix="beats" value={Number(profile.min_trigger_spacing_beats ?? 4)}
                  onChange={(v) => set('min_trigger_spacing_beats', v)} />
                <NumSetting label="Min Scene Change Spacing" suffix="beats" value={Number(profile.min_scene_change_spacing_beats ?? 16)}
                  onChange={(v) => set('min_scene_change_spacing_beats', v)} />
                {TP_EVENT_SLOTS.map(([key, label, hint]) => (
                  <div key={key}>
                    <label style={{ fontSize: 11, color: 'var(--text-muted)' }} title={hint}>{label}</label>
                    <SearchSelect
                      value={String(profile[key] ?? '')}
                      onChange={(v) => set(key, v)}
                      options={events.map((e) => ({ value: e.id, label: e.name }))}
                      placeholder="(none)"
                      width="100%"
                    />
                  </div>
                ))}
                <NumSetting label="Fill Min Spacing (beats)" suffix="" value={Number(profile.fill_min_spacing_beats ?? 48)}
                  onChange={(v) => set('fill_min_spacing_beats', v)} />
                <NumSetting label="Flare Max Gap" suffix="beats (low-energy max)" value={Number(profile.flare_max_gap_beats ?? 32)}
                  onChange={(v) => set('flare_max_gap_beats', v)} />
              </div>
            </details>

            {/* Song lists */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Song lists cached at page load.</span>
              <button style={{ fontSize: 11, padding: '2px 8px' }}
                onClick={async () => {
                  await Promise.all([refetchTraining(), refetchCandidates()]);
                  toast('Song lists refreshed.', 'success');
                }}>
                ↺ Reload Songs
              </button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 10 }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <ChipBox
                  title="AI + Embedded Training"
                  subtitle="(sent to Claude AND used for KNN)"
                  uris={profile.training_uris ?? []}
                  songs={trainingSongs}
                  onRemove={(uri) => set('training_uris', (profile.training_uris ?? []).filter((u) => u !== uri))}
                  buttons={
                    <>
                      <button style={{ fontSize: 12, padding: '3px 10px' }} onClick={() => setPicker('training')}>+ Add</button>
                      <button style={{ fontSize: 12, padding: '3px 10px' }} title="Add verified songs whose genres match this profile"
                        onClick={() => addMatchingVerified('training')}>+ Matching</button>
                    </>
                  }
                />
                <ChipBox
                  title="Embedded Only Training"
                  subtitle="(KNN only — not sent to Claude)"
                  uris={profile.embedded_only_uris ?? []}
                  songs={trainingSongs}
                  onRemove={(uri) => set('embedded_only_uris', (profile.embedded_only_uris ?? []).filter((u) => u !== uri))}
                  buttons={
                    <>
                      <button style={{ fontSize: 12, padding: '3px 10px' }} onClick={() => setPicker('embedded')}>+ Add</button>
                      <button style={{ fontSize: 12, padding: '3px 10px' }} onClick={() => addMatchingVerified('embedded')}>+ Matching</button>
                    </>
                  }
                />
              </div>
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, marginBottom: 4 }}>
                  Target Songs <span style={{ fontWeight: 'normal' }}>(need audio shape)</span>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6, minHeight: 28 }}>
                  {!targetUris.length && (
                    <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>No target songs added</span>
                  )}
                  {targetUris.map((uri) => {
                    const song = candidateSongs.find((s) => s.uri === uri);
                    const c = cache[uri];
                    return (
                      <span key={uri} className="chip" style={{ gap: 5 }}>
                        {song ? `${song.artist} — ${song.title}` : uri.split(':').pop()}
                        <span style={{ fontSize: 10, color: c ? '#4caf50' : 'var(--text-muted)' }}>
                          {c ? `(${c.suggestions.length} sug)` : `(${song?.trigger_count ?? 0} triggers)`}
                        </span>
                        {!c && song && !song.has_suggestions && (
                          <button style={{ fontSize: 11, padding: '1px 6px' }}
                            title="Generate AI suggestions for this song"
                            onClick={async () => {
                              await apiPost(`/ai-triggers/generate-now?uri=${encodeURIComponent(uri)}`);
                              toast('Generation started…', 'info');
                            }}>
                            Generate
                          </button>
                        )}
                        <span style={{ cursor: 'pointer', fontSize: 14, marginLeft: 2 }}
                          onClick={() => {
                            set('target_uris', targetUris.filter((u) => u !== uri));
                            setCache((c2) => {
                              const { [uri]: _, ...rest } = c2;
                              return rest;
                            });
                          }}>×</span>
                      </span>
                    );
                  })}
                </div>
                <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                  <button style={{ fontSize: 12, padding: '3px 10px' }} onClick={() => setPicker('target')}>+ Add</button>
                  <span style={{ position: 'relative', display: 'inline-block' }}>
                    <button style={{ fontSize: 12, padding: '3px 10px' }} onClick={() => setLoadSavedOpen(true)}>↓ Load Saved</button>
                    {pendingReview > 0 && (
                      <span style={{
                        position: 'absolute', top: -6, right: -8, background: '#e65100', color: '#fff',
                        borderRadius: 10, fontSize: 10, padding: '1px 5px', pointerEvents: 'none',
                      }}>
                        {pendingReview}
                      </span>
                    )}
                  </span>
                </div>
              </div>
            </div>

            {genProgress && (
              <div style={{ marginTop: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>{genProgress.status}</span>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{genProgress.cost}</span>
                </div>
                <div style={{ background: 'var(--surface)', borderRadius: 3, height: 5, overflow: 'hidden', margin: '5px 0' }}>
                  <div style={{ height: '100%', background: '#7c4dff', borderRadius: 3, width: `${genProgress.pct}%`, transition: 'width 0.4s ease' }} />
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.6, maxHeight: 80, overflowY: 'auto' }}>
                  {genProgress.log.map((l, i) => <div key={i}>{l}</div>)}
                </div>
              </div>
            )}
            {genError && <div style={{ color: '#ef5350', fontSize: 13, marginTop: 8 }}>{genError}</div>}
          </div>
        )}
      </div>

      {/* ── Review panel ── */}
      {showReview && currentUri && cached && (
        <ReviewPanel
          uri={currentUri}
          cached={cached}
          durationMs={candidateSongs.find((s) => s.uri === currentUri)?.duration_ms || cached.duration_ms || 240_000}
          events={eventOptions}
          navLabel={`${targetIdx + 1} / ${targetUris.length}`}
          onNav={(delta) => {
            const next = targetIdx + delta;
            if (next >= 0 && next < targetUris.length) void showSong(next);
          }}
          mutateSet={mutateCurrentSet}
          onManualAdd={(ms) => setManualAddMs(ms)}
          onQuickAdd={(ms) => {
            const eventId = recentEventIds.current[0];
            if (!eventId) return;
            addSuggestion({ ms, eventId, labels: [], comment: '' });
          }}
          actions={
            <>
              <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
                <button style={{ fontSize: 12, padding: '5px 12px' }} onClick={approveHighConf}>✓ Approve ≥80%</button>
                <button style={{ fontSize: 12, padding: '5px 12px', background: '#2e7d32', color: '#fff', borderColor: 'transparent' }}
                  onClick={() => void applyApproved()}>Apply Approved</button>
                <button style={{ fontSize: 12, padding: '5px 12px' }} onClick={() => void saveCurrent()}>Save</button>
                <button style={{ fontSize: 12, padding: '5px 12px' }} onClick={() => void analyzeLearning([currentUri])}>
                  Analyze This Song
                </button>
                {allReviewed && (
                  <button style={{ fontSize: 12, padding: '5px 12px' }} onClick={() => void analyzeLearning(targetUris)}>
                    Analyze All
                  </button>
                )}
              </div>
              {postApply && (
                <div style={{ border: '1px solid #2e7d32', borderRadius: 5, padding: '8px 12px', marginBottom: 10 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                    <span style={{ color: '#4caf50', fontSize: 13, flex: 1, minWidth: 0 }}>{postApply.msg}</span>
                    <button className="primary" style={{ fontSize: 11, padding: '3px 10px', whiteSpace: 'nowrap' }}
                      onClick={() => void saveAsTraining()}>
                      {postApply.added ? '✓ Added' : '+ Add to Training'}
                    </button>
                  </div>
                </div>
              )}
            </>
          }
        />
      )}

      {/* ── Modals ── */}
      {picker && (
        <SongPickerModal
          mode={picker}
          songs={picker === 'target' ? candidateSongs : trainingSongs}
          activeUris={new Set(
            picker === 'training' ? profile.training_uris
              : picker === 'embedded' ? profile.embedded_only_uris
                : targetUris,
          )}
          matchesFilter={picker === 'target' ? (s) => {
            const trainingSet = new Set(trainingSongs.map((x) => x.uri));
            return genresMatch(s) && !trainingSet.has(s.uri) && !s.has_suggestions;
          } : null}
          onPick={(song) => {
            if (picker === 'training') set('training_uris', [...(profile.training_uris ?? []), song.uri]);
            else if (picker === 'embedded') set('embedded_only_uris', [...(profile.embedded_only_uris ?? []), song.uri]);
            else addTarget(song);
            setPicker(null);
          }}
          onClose={() => setPicker(null)}
        />
      )}
      {manageOpen && (
        <ManageProfilesModal
          profiles={profiles}
          onLoad={(id) => { loadProfile(id); setManageOpen(false); }}
          onDelete={async (id, name) => {
            if (!confirm(`Delete training profile "${name}"?`)) return;
            await apiDel(`/ai-triggers/training-profiles/${id}`);
            await qc.invalidateQueries({ queryKey: ['ai-profiles'] });
            if (profileId === id) loadProfile('');
          }}
          onBackfill={() => apiPost<{ updated: number }>('/audio-shape/backfill-genres', {})}
          onClose={() => setManageOpen(false)}
        />
      )}
      {loadSavedOpen && (
        <LoadSavedModal sets={savedSets} onLoad={(id) => void loadSaved(id)} onClose={() => setLoadSavedOpen(false)} />
      )}
      {estimate && (
        <CostConfirmModal
          estimate={estimate}
          onRun={(model) => void runGeneration(model)}
          onRunEmbedded={() => void runEmbedded()}
          onClose={() => setEstimate(null)}
        />
      )}
      {existingSong && (
        <ExistingTriggersModal
          song={existingSong}
          onKeep={() => {
            set('target_uris', [...targetUris, existingSong.uri]);
            setExistingSong(null);
          }}
          onDeleteAll={async () => {
            const song = existingSong;
            setExistingSong(null);
            const prof = await apiGet<{ triggers: unknown[] } & Record<string, unknown>>(
              `/profiles/by-uri?uri=${encodeURIComponent(song.uri)}`).catch(() => null);
            if (prof) {
              prof.triggers = [];
              await apiPost('/profiles', prof);
              song.trigger_count = 0;
            }
            set('target_uris', [...targetUris, song.uri]);
          }}
          onClose={() => setExistingSong(null)}
        />
      )}
      {manualAddMs !== 'closed' && (
        <ManualAddModal
          prefillMs={manualAddMs}
          events={eventOptions}
          defaultEventId={recentEventIds.current[0] || events[0]?.id || ''}
          onAdd={(data) => { addSuggestion(data); setManualAddMs('closed'); }}
          onClose={() => setManualAddMs('closed')}
        />
      )}
      {analyzeText !== null && (
        <AnalyzeResultModal
          text={analyzeText}
          onApply={() => {
            set('description', analyzeText);
            setAnalyzeText(null);
            if (profileId) void saveProfile();
          }}
          onClose={() => setAnalyzeText(null)}
        />
      )}
    </>
  );
}

function savedSetToCache(setData: Record<string, unknown>): CachedSet {
  return {
    title: String(setData.title ?? ''),
    artist: String(setData.artist ?? ''),
    songComment: String(setData.song_comment ?? ''),
    duration_ms: Number(setData.duration_ms ?? 0),
    generated_at: String(setData.generated_at ?? ''),
    training_profile_id: String(setData.training_profile_id ?? ''),
    training_profile_name: String(setData.training_profile_name ?? ''),
    applied: Boolean(setData.applied ?? false),
    cost_usd: Number(setData.cost_usd ?? 0),
    input_tokens: Number(setData.input_tokens ?? 0),
    output_tokens: Number(setData.output_tokens ?? 0),
    suggestions: ((setData.suggestions as Partial<Suggestion>[]) ?? []).map((s) => ({
      timestamp_ms: Number(s.timestamp_ms ?? 0),
      event_id: String(s.event_id ?? ''),
      event_name: s.event_name,
      confidence: Number(s.confidence ?? 1),
      reasoning: String(s.reasoning ?? ''),
      original_timestamp_ms: Number(s.original_timestamp_ms ?? s.timestamp_ms ?? 0),
      original_event_id: String(s.original_event_id ?? s.event_id ?? ''),
      labels: (s.labels as string[]) ?? [],
      comment: String(s.comment ?? ''),
      manually_added: Boolean(s.manually_added ?? false),
      approved: (s.approved as boolean | null) ?? null,
    })),
  };
}

function NumSetting({ label, suffix, value, onChange }: {
  label: string; suffix: string; value: number; onChange: (v: number) => void;
}) {
  return (
    <div>
      <label style={{ fontSize: 11, color: 'var(--text-muted)' }}>{label}</label>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <input type="number" min={1} step={1} value={value} style={{ width: 70 }}
          onChange={(e) => onChange(parseInt(e.target.value) || value)} />
        {suffix && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{suffix}</span>}
      </div>
    </div>
  );
}

function ChipBox({ title, subtitle, uris, songs, onRemove, buttons }: {
  title: string; subtitle: string; uris: string[]; songs: SongInfo[];
  onRemove: (uri: string) => void; buttons: React.ReactNode;
}) {
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, marginBottom: 4 }}>
        {title} <span style={{ fontWeight: 'normal' }}>{subtitle}</span>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6, minHeight: 28 }}>
        {!uris.length && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>No songs added</span>}
        {uris.map((uri) => {
          const song = songs.find((s) => s.uri === uri);
          return (
            <span key={uri} className="chip" style={{ gap: 5 }}>
              {song ? `${song.artist} — ${song.title}` : uri.split(':').pop()}
              <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>({song?.trigger_count ?? '?'})</span>
              <span style={{ cursor: 'pointer', fontSize: 14, marginLeft: 2 }} onClick={() => onRemove(uri)}>×</span>
            </span>
          );
        })}
      </div>
      <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>{buttons}</div>
    </div>
  );
}
