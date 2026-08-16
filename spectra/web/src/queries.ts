/** Data hooks for the SPECTRA app (react-query). */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiDel, apiGet, apiPost, apiPostForm, apiPut, spotfxDel, spotfxGet, spotfxPost } from './api/client';
import type { CurvePoint } from './components/CurveEditor';
import type {
  ColorWheelPosition, DevicePreviewFavorites, DevicePreviewStatus, DriftProfile, EngineStatus,
  FeedbackCapture, FeedbackEntry, FireResult, IntensityScaleMark, Registry, ReviewSession,
  ReviewTimeline, RoomColorState, RoomControlState, RoomControlsSaveResult, SceneV2,
  SettingChangeEntry, SettingsMessageResult, SettingsRegistry, SonicAppliedChange,
  SonicUsageSummary, SpectraTrigger, SpotColorSetCard, TranscribeResult, UndoResult,
} from './types';

/* ── scenes ── */

export function useScenes() {
  return useQuery({
    queryKey: ['spectra-scenes'],
    queryFn: () => apiGet<SceneV2[]>('/scenes'),
  });
}

export function useSaveScene() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (scene: SceneV2) => apiPost('/scenes', scene),
    onSuccess: (_d, scene) => {
      qc.setQueryData<SceneV2[]>(['spectra-scenes'], (old) => {
        if (!old) return old;
        return old.some((s) => s.id === scene.id)
          ? old.map((s) => (s.id === scene.id ? scene : s))
          : [...old, scene];
      });
      void qc.invalidateQueries({ queryKey: ['spectra-scenes'] });
    },
  });
}

export function useDeleteScene() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDel(`/scenes/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['spectra-scenes'] }),
  });
}

export const fireScene = (id: string, intensity: number, dryRun = true) =>
  apiPost<FireResult>(`/scenes/${id}/fire`, { dry_run: dryRun, intensity });

/* ── registry / colour sets ── */

export function useRegistry() {
  return useQuery({
    queryKey: ['spectra-registry'],
    queryFn: () => apiGet<Registry>('/registry'),
    staleTime: 60_000,
  });
}

export function useWheelPositions() {
  return useQuery({
    queryKey: ['spectra-wheel-positions'],
    queryFn: () => apiGet<Record<string, ColorWheelPosition>>('/scenes/wheel-positions'),
    staleTime: 60_000,
  });
}

/** Full cards from the spot-effects surface (read + the one supported
 * opt-out toggle) — the S2 bridge formalizes this feed. */
export function useSpotColorSets() {
  return useQuery({
    queryKey: ['spot-color-sets'],
    queryFn: () => spotfxGet<SpotColorSetCard[]>('/color-sets'),
  });
}

export function useToggleSetOptOut() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (card: SpotColorSetCard) =>
      spotfxPost('/color-sets', { ...card, scene_v2_opt_out: !card.scene_v2_opt_out }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['spot-color-sets'] }),
  });
}

/** Create/update a Set or a Group (§10) — spot-effects' own upsert-by-id
 * POST, the same endpoint useToggleSetOptOut already uses. */
export function useSaveColorSet() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (card: SpotColorSetCard) => spotfxPost('/color-sets', card),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['spot-color-sets'] }),
  });
}

export function useDeleteColorSet() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => spotfxDel(`/color-sets/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['spot-color-sets'] }),
  });
}

/** Apply a Set (or a Group — §10, picks one member and merges its own
 * override entries) to the room right now — the same POST the room-colour
 * apply surface uses; used here as the authoring page's live test/preview. */
export function useApplyColorSet() {
  return useMutation({
    mutationFn: (setId: string) => apiPost('/room-color/apply', { set_id: setId }),
  });
}

/** Gradient library (read-only) for fixed-colour pickers. */
export function useGradients() {
  return useQuery({
    queryKey: ['spot-gradients'],
    queryFn: () => spotfxGet<{ id: string; name: string; value: string }[]>('/gradients'),
    staleTime: 60_000,
  });
}

/* ── sequencer ── */

export interface CurveProfile { id: string; name: string; points: CurvePoint[]; }

export interface SelectorEntry {
  curve_ref: string | null;
  inline_points: CurvePoint[] | null;
  genre_mult: Record<string, number>;
  dwell_weight: number;
}

export interface AffinityEdge { from_id: string; to_id: string; mult: number; }

export interface SequencerConfig {
  enabled: boolean;
  change_mode: 'transition' | 'timed' | 'both';
  base_dwell_s: number;
  entries: Record<string, SelectorEntry>;
  affinity: AffinityEdge[];
  flare_entries: Record<string, SelectorEntry>;
  color_set_entries: Record<string, SelectorEntry>;
  wheel_travel_curve: string | null;
}

export interface SequencerStatus {
  enabled: boolean;
  change_mode: string;
  next_change_source: string;
  deferred_by: string | null;
  bridge_connected: boolean;
  active_scene_id: string | null;
  active_scene_name: string | null;
  dwell: { served_songs: number; target_songs: number; weight: number } | null;
  last_pick: {
    picked_id: string | null;
    picked_name: string | null;
    rung: string;
    intensity: number;
    factors: Record<string, { curve: number; genre: number; affinity: number; score: number }>;
    source: string;
    at: number;
  } | null;
  last_moment: { source: string; result: string; at: number } | null;
  color: {
    active_set_id: string | null;
    active_set_name: string | null;
    wheel_position_deg: number | null;
    last_pick: Record<string, unknown> | null;
  };
}

export function useSequencerCurves() {
  return useQuery({
    queryKey: ['spectra-seq-curves'],
    queryFn: () => apiGet<Record<string, CurveProfile>>('/sequencer/curves'),
  });
}

export function useSequencerConfig() {
  return useQuery({
    queryKey: ['spectra-seq-config'],
    queryFn: () => apiGet<SequencerConfig>('/sequencer/config'),
  });
}

export function useSequencerStatus() {
  return useQuery({
    queryKey: ['spectra-seq-status'],
    queryFn: () => apiGet<SequencerStatus>('/sequencer/status'),
    refetchInterval: 5000,
  });
}

export function useIntensityHistogram() {
  return useQuery({
    queryKey: ['spectra-intensity-histogram'],
    queryFn: () => apiGet<{ bins: number; counts: number[]; total: number }>('/sequencer/intensity-histogram'),
    staleTime: 300_000,
  });
}

export function useSaveCurves() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (curves: Record<string, CurveProfile>) => apiPut('/sequencer/curves', curves),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['spectra-seq-curves'] }),
  });
}

/** Curve-attachment mutation: round-trips the STORED config and rewrites
 * only entries[sceneId]'s curve fields — relationships stay agent-owned. */
export function useAttachCurve() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: {
      sceneId: string;
      attachment:
        | { kind: 'none' }
        | { kind: 'flat' }
        | { kind: 'profile'; profileId: string }
        | { kind: 'inline'; points: CurvePoint[] };
    }) => {
      const config = await apiGet<SequencerConfig>('/sequencer/config');
      const { [args.sceneId]: existing, ...rest } = config.entries;
      if (args.attachment.kind === 'none') {
        return apiPut('/sequencer/config', { ...config, entries: rest });
      }
      const entry: SelectorEntry = existing ?? {
        curve_ref: null, inline_points: null, genre_mult: {}, dwell_weight: 1.0,
      };
      const curve =
        args.attachment.kind === 'profile'
          ? { curve_ref: args.attachment.profileId, inline_points: null }
          : args.attachment.kind === 'inline'
            ? { curve_ref: null, inline_points: args.attachment.points }
            : { curve_ref: null, inline_points: null };
      return apiPut('/sequencer/config', {
        ...config,
        entries: { ...rest, [args.sceneId]: { ...entry, ...curve } },
      });
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['spectra-seq-config'] }),
  });
}

/* ── journey / drift profiles ── */

export function useRoomJourney() {
  return useQuery({
    queryKey: ['spectra-room-journey'],
    queryFn: () => apiGet<RoomColorState>('/room-journey'),
    staleTime: 30_000,
  });
}

export function useDriftProfiles() {
  return useQuery({
    queryKey: ['spectra-drift-profiles'],
    queryFn: () => apiGet<Record<string, DriftProfile>>('/drift-profiles'),
  });
}

export function useSaveDriftProfiles() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (profiles: Record<string, DriftProfile>) => apiPut('/drift-profiles', profiles),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['spectra-drift-profiles'] }),
  });
}

/* ── room controls (brightness multiplier / ambient / global transition) ── */

export function useRoomControls() {
  return useQuery({
    queryKey: ['spectra-room-controls'],
    queryFn: () => apiGet<RoomControlState>('/room-controls'),
    staleTime: 10_000,
  });
}

export function useSaveRoomControls() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (state: RoomControlState) =>
      apiPut<RoomControlsSaveResult>('/room-controls', state),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['spectra-room-controls'] }),
  });
}

/* ── device preview ── */

export function useDevicePreviewFavorites() {
  return useQuery({
    queryKey: ['spectra-device-preview-favorites'],
    queryFn: () => apiGet<DevicePreviewFavorites>('/device-preview/favorites'),
    staleTime: 10_000,
  });
}

export function useSaveDevicePreviewFavorites() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (favorite_virtual_ids: string[]) =>
      apiPut<DevicePreviewFavorites>('/device-preview/favorites', { favorite_virtual_ids }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['spectra-device-preview-favorites'] }),
  });
}

export const pauseDevicePreview = () => apiPost<DevicePreviewStatus>('/device-preview/pause');
export const resumeDevicePreview = () => apiPost<DevicePreviewStatus>('/device-preview/resume');

/* ── engine (S2) ── */

/** The evolution engine's live surface — display only (the strip on the
 * Scenes page and the Drift tab's live positions read this). */
export function useEngineStatus() {
  return useQuery({
    queryKey: ['spectra-engine-status'],
    queryFn: () => apiGet<EngineStatus>('/engine/status'),
    refetchInterval: 3000,
  });
}

/* ── status ── */

export interface AppStatus {
  app: string;
  increment: string;
  scenes: number;
  sequencer_enabled: boolean;
  bridge_connected: boolean;
  engine_dark: boolean;
  light_ownership: string;
  room_journey_degrees_per_min: number;
  room_wheel_position_deg: number | null;
}

export function useAppStatus() {
  return useQuery({
    queryKey: ['spectra-status'],
    queryFn: () => apiGet<AppStatus>('/status'),
    refetchInterval: 10_000,
  });
}

/* ── light ownership / the panic release ── */

export interface OwnershipRecord {
  owner: string;
  handover: {
    from: string; to: string; step: string; started_at: number;
    token: string; age_s?: number;
  } | null;
  updated_at: number;
  armed: boolean;
  live_stack_active: boolean;
  history: { at: number; event: string; detail: string }[];
}

/** Polls fast enough that the banner/button reflect a press from another
 * tab or device within a beat — this is a panic surface, staleness reads
 * as "did it work?". */
export function useOwnership() {
  return useQuery({
    queryKey: ['spectra-ownership'],
    queryFn: () => apiGet<OwnershipRecord>('/ownership'),
    refetchInterval: 4_000,
  });
}

/** THE PANIC HANDLE. No body, no confirmation — the press is the consent. */
export function useReleaseRoom() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiPost<{ result: string; owner: string; problems?: string[] }>('/ownership/release'),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['spectra-ownership'] }),
  });
}

/** The way back from released: the normal guarded handover to SPECTRA,
 * readiness-gated and SPECTRA_HANDOVER_ARMED-gated same as any handover. */
export function useTakeBackToSpectra() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiPost<{ result: string; owner: string }>('/ownership/handover', { to: 'spectra' }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['spectra-ownership'] }),
  });
}

/* ── per-song triggers (THE KEYSTONE — spectra/api/triggers.py) ── */

const enc = encodeURIComponent;

export function useSpectraTriggers(uri: string | null) {
  return useQuery({
    queryKey: ['spectra-triggers', uri],
    queryFn: () => apiGet<SpectraTrigger[]>(`/triggers?uri=${enc(uri!)}`),
    enabled: !!uri,
  });
}

/** Place/move/edit all persist as one upsert — the store replaces by id. */
export function useSaveSpectraTrigger(uri: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (trigger: SpectraTrigger) =>
      apiPost(`/triggers?uri=${enc(uri!)}`, trigger),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['spectra-triggers', uri] }),
  });
}

export function useDeleteSpectraTrigger(uri: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (triggerId: string) =>
      apiDel(`/triggers/${triggerId}?uri=${enc(uri!)}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['spectra-triggers', uri] }),
  });
}

/** Front 3's mid-song generation pass (spectra/services/midsong_generator.py) —
 * idempotent, edit-preserving. Returns a {moments,added,updated,deleted,
 * skipped_authored} summary. */
export function useGenerateMidsongTriggers(uri: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiPost<{ moments: number; added: number; updated: number;
               deleted: number; skipped_authored: number }>(
        `/triggers/generate?uri=${enc(uri!)}`, {}),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['spectra-triggers', uri] }),
  });
}

/* ── feedback sessions (Stage 2 — mark-then-nudge, batch send) ── */

/** MARK button's server half — a fresh wall_ms/uri/position_ms triple read
 * from the live S2 bridge state. Never a cached query: every call must be
 * a genuinely fresh capture. */
export const captureFeedbackMark = () => apiGet<FeedbackCapture>('/feedback/mark');

/** POST /api/feedback/batch — the ONE round-trip a whole show's queue
 * makes. Callers strip the client-only `touched`/`nudge_offset_ms` fields
 * before sending (position_ms is already the combined anchor+offset by
 * the time it reaches here — see FeedbackPage.tsx's handleSend). */
export function useSendFeedbackBatch() {
  return useMutation({
    mutationFn: (entries: Omit<FeedbackEntry, 'touched' | 'nudge_offset_ms'>[]) =>
      apiPost<{ status: string; session_id: string; received_ms: number; count: number }>(
        '/feedback/batch', { entries }),
  });
}

/* ── show review (Stage 3 — his notes pinned against the reconstructed show) ── */

/** GET /api/review/sessions — one row per sent feedback batch, newest
 * first, naming the songs it has notes for (the session/song picker). */
export function useReviewSessions() {
  return useQuery({
    queryKey: ['review-sessions'],
    queryFn: () => apiGet<ReviewSession[]>('/review/sessions'),
  });
}

/** GET /api/review/timeline — one song's merged, ordered timeline within
 * one session (see spectra/services/show_reconstruction.py). */
export function useReviewTimeline(sessionId: string | null, uri: string | null) {
  return useQuery({
    queryKey: ['review-timeline', sessionId, uri],
    queryFn: () => apiGet<ReviewTimeline>(
      `/review/timeline?session_id=${enc(sessionId!)}&uri=${enc(uri!)}`),
    enabled: !!sessionId && !!uri,
  });
}

/* ── Sonic token usage (review page — spectra/services/sonic_usage.py) ── */

/** GET /api/sonic-usage — last query / this fixed day / this fixed week
 * (Monday 22:00 America/New_York anchored, not rolling — see the service
 * module's docstring). Polled: Sonic can be called from other tabs/pages
 * (Settings, or the Scenes-page chat popover) while this one is open. */
export function useSonicUsage() {
  return useQuery({
    queryKey: ['sonic-usage'],
    queryFn: () => apiGet<SonicUsageSummary>('/sonic-usage'),
    refetchInterval: 60_000,
  });
}

/* ── settings console (standing order 5 — spectra/services/settings_console.py) ── */

/** Every declared setting + its live value/range — the read-only summary
 * strip. Polled, not a form: the chat is the only thing that writes. */
export function useSettingsRegistry() {
  return useQuery({
    queryKey: ['spectra-settings-registry'],
    queryFn: () => apiGet<SettingsRegistry>('/settings-console/registry'),
    refetchInterval: 5000,
  });
}

/** Recent change-log entries, newest first — the visible "what changed"
 * record a mis-transcribed voice command needs to be caught by. */
export function useSettingsLog(limit = 20) {
  return useQuery({
    queryKey: ['spectra-settings-log', limit],
    queryFn: () => apiGet<SettingChangeEntry[]>(`/settings-console/log?limit=${limit}`),
    refetchInterval: 5000,
  });
}

function invalidateSettingsConsole(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: ['spectra-settings-registry'] });
  void qc.invalidateQueries({ queryKey: ['spectra-settings-log'] });
  void qc.invalidateQueries({ queryKey: ['spectra-room-controls'] });
}

export function useUndoLastSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<UndoResult>('/settings-console/undo'),
    onSuccess: () => invalidateSettingsConsole(qc),
  });
}

/** POST /settings-console/scene-undo — the plain, model-free "undo last
 * agent change" button (his own words) for the SCENE domain. Deliberately
 * NOT routed through Sonic's chat — undo is a deterministic restore from
 * an already-verified backup, so it needs no live model call. */
export function useUndoLastSceneChange() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<SonicAppliedChange>('/settings-console/scene-undo'),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['spectra-scenes'] }); },
  });
}

/** POST /settings-console/message — Sonic's one chat endpoint, shared by
 * both the Settings page's embedded chat and the Scenes page's popover
 * (SonicChatPopover.tsx). `changes` can be settings- or scene-domain (see
 * SonicAppliedChange), so a successful reply invalidates both worlds
 * rather than trying to sniff which one changed from the result shape. */
export function useSendSettingsMessage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { session_id: string | null; text: string }) =>
      apiPost<SettingsMessageResult>('/settings-console/message', body),
    onSuccess: (result) => {
      if (result.changes.length === 0) return;
      invalidateSettingsConsole(qc);
      void qc.invalidateQueries({ queryKey: ['spectra-scenes'] });
    },
  });
}

/** POST /settings-console/transcribe — the voice seam. Unimplemented
 * server-side tonight (spectra/services/transcription.py); the request is
 * real and fails with a clear 503 the caller surfaces, never a silent
 * no-op. */
export function useTranscribeSettingsAudio() {
  return useMutation({
    mutationFn: (audio: Blob) => {
      const form = new FormData();
      form.append('audio', audio, 'clip.webm');
      return apiPostForm<TranscribeResult>('/settings-console/transcribe', form);
    },
  });
}

/* ── intensity-scale mark (2026-08-15 ruling: the one way past the
   automatic 0.75 ceiling — "he marks the track; automatic never does") ── */

export function useIntensityScaleMark(uri: string | null) {
  return useQuery({
    queryKey: ['spectra-intensity-mark', uri],
    queryFn: () => apiGet<IntensityScaleMark>(`/intensity-scale/mark?uri=${encodeURIComponent(uri!)}`),
    enabled: uri != null,
    refetchInterval: 5000,
  });
}

export function useSetIntensityScaleMark(uri: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (factor: number) =>
      apiPut<{ uri: string; mark: number }>(
        `/intensity-scale/mark?uri=${encodeURIComponent(uri!)}`, { factor }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['spectra-intensity-mark', uri] }),
  });
}

export function useClearIntensityScaleMark(uri: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiDel<{ uri: string; cleared: boolean }>(
        `/intensity-scale/mark?uri=${encodeURIComponent(uri!)}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['spectra-intensity-mark', uri] }),
  });
}
