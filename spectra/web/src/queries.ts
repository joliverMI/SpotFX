/** Data hooks for the SPECTRA app (react-query). */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiDel, apiGet, apiPost, apiPut, spotfxGet, spotfxPost } from './api/client';
import type { CurvePoint } from './components/CurveEditor';
import type {
  ColorWheelPosition, DriftProfile, EngineStatus, FireResult, Registry,
  RoomColorState, RoomControlState, SceneV2, SpectraTrigger, SpotColorSetCard,
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
    mutationFn: (state: RoomControlState) => apiPut('/room-controls', state),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['spectra-room-controls'] }),
  });
}

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
