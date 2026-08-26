/** Data hooks for the SPECTRA app (react-query). */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiDel, apiGet, apiPost, apiPostForm, apiPut, spotfxDel, spotfxGet, spotfxPost } from './api/client';
import type { CurvePoint } from './components/CurveEditor';
import type {
  AmbientHueGroup, ColorWheelPosition, DevicePreviewFavorites, DevicePreviewStatus, DriftProfile,
  EngineStatus, FeedbackCapture, FeedbackEntry, FireResult, IntensityScaleMark, Registry,
  ReviewSession, ReviewTimeline, RoomColorState, RoomControlState, RoomControlsSaveResult,
  SceneV2, SettingChangeEntry, SettingsMessageResult, SettingsRegistry, SonicAppliedChange,
  Liveness, SonicUsageSummary, SpectraTrigger, SpotColorSetCard, TestSessionStatus,
  TranscribeResult, UndoResult,
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

/** Gradient library (read-only) for fixed-colour pickers. */
export function useGradients() {
  return useQuery({
    queryKey: ['spot-gradients'],
    queryFn: () => spotfxGet<{ id: string; name: string; value: string }[]>('/gradients'),
    staleTime: 60_000,
  });
}

/* ── room-colour Preview (owner ask 2026-08-17) ──
 * Plain async functions, not mutations — ColorSetsPage.tsx drives these
 * directly off its own press/drag/unmount timing, not a click-triggered
 * mutation lifecycle. */

export interface PreviewStartResult {
  applied: boolean;
  virtuals: string[];
  hold: boolean;
  expires_in_s: number;
  /** True when the previewed card is marked Disabled — the preview still
   * ran (an explicit press always wins), and the contradiction is named
   * rather than silent. Same shape as Force Scene's own overrode_disabled. */
  overrode_disabled?: boolean;
}
export interface PreviewUpdateResult { applied: boolean; virtuals: string[]; }
export interface PreviewReleaseResult { reverted: boolean; }

export const startPreview = (card: SpotColorSetCard, hold: boolean) =>
  apiPost<PreviewStartResult>('/room-preview/start', { card, hold });

export const updatePreview = (card: SpotColorSetCard) =>
  apiPost<PreviewUpdateResult>('/room-preview/update', { card });

export const releasePreview = () =>
  apiPost<PreviewReleaseResult>('/room-preview/release', {});

/** Tab-close/reload release: `fetch` isn't reliably delivered from a
 * beforeunload handler, so this uses sendBeacon instead — fire-and-forget,
 * best-effort. The server-side auto-revert timer (5s tap / 60s hold) is
 * the backstop if even this never lands (a killed process, not just a
 * closed tab). */
export const releasePreviewBeacon = (): void => {
  try {
    navigator.sendBeacon('/spectra/api/room-preview/release',
      new Blob(['{}'], { type: 'application/json' }));
  } catch {
    // best-effort only
  }
};

/* ── flare scrubbing preview (owner ask, flares first — data/
   timeline-preview-scrub-flares-and-drop-sequences) ──
 * Plain async functions, not mutations — FlarePreviewOverlay.tsx drives
 * these off its own open/heartbeat/close lifecycle, the same shape the
 * room-colour Preview above uses. */

export interface FlarePreviewWrite {
  seq: number;
  at_s: number;
  kind: 'jump' | 'glide';
  virtual_id: string;
  effect_type: string;
  params: Record<string, unknown>;
  duration_ms: number;
}

export interface FlarePreviewTimeline {
  kind_name: string;
  kind_type: string;
  intensity: number;
  result: string;
  /** Both relative to the EARLIEST write (== the fire instant) — null
   * when the kind produced no writes at this intensity (an unregistered
   * param, or a colour-jump kind with no eligible sets). */
  animation_start_s: number | null;
  animation_end_s: number | null;
  duration_s: number;
  /** Where "the animation starts" is DRAWN — a fixed ruler-layout
   * position, computed server-side (spectra/services/flare_preview.
   * animation_anchor_s). trigger_mark_s is derived from it via the kind's
   * own trigger_offset_ms (HIS sign convention — see FlareKind.
   * trigger_offset_ms's docstring, spectra/models/scene.py): negative
   * offset fires earlier (mark to the right of anchor), positive fires
   * later (mark to the left), 0 = coincident. */
  animation_anchor_s: number;
  trigger_mark_s: number;
  /** The AUTOMATIC lead (ms) a real trigger fire would compute for this
   * exact kind — scene_response.kind_lead_ms, the fixed DICE_REROLL_GLIDE_MS
   * for a registry-smooth momentary param glide, or the intensity-scaled
   * color_rotate ramp, never a hardcoded number. 0 for a kind with neither. */
  lead_ms: number;
  /** Where the live-fire loop actually issues its /fire call each cycle —
   * NOT animation_anchor_s. fire_at_s = animation_anchor_s - lead_ms/1000
   * (spectra/services/flare_preview.fire_at_s): his authored offset is
   * already baked into animation_anchor_s by construction of
   * trigger_mark_s's own formula, so this is the SAME target-then-lead
   * composition #172 established for SpectraTrigger.trigger_offset_ms,
   * with nothing left to add on top. Can be negative or exceed duration_s
   * — the loop's own modular real-time wraparound handles both, never
   * clamp this before scheduling against it. */
  fire_at_s: number;
  writes: FlarePreviewWrite[];
}

export interface FlarePreviewFireResult {
  held: boolean;
  first_open?: boolean;
  fire_record?: Record<string, unknown>;
  /** True once the server's absolute MAX_HOLD_DURATION_S ceiling has fired
   * (spectra/services/flare_preview_hold.py — heartbeats can never push
   * this back out) and released the room on its own; reason is always
   * "max_duration" when set. FlarePreviewOverlay surfaces this rather than
   * silently letting the loop keep calling a no-op /fire. */
  expired?: boolean;
  reason?: string;
}

/** Computes the timeline ONLY — no live fire. Call on mount and whenever
 * intensity changes; the live fire is a separate call (fireFlarePreview),
 * timed by the frontend's own playhead loop to land on animation_anchor_s
 * each cycle, never here (see spectra/api/flare_preview.py's module
 * docstring for why open/fire split apart). */
export const openFlarePreview = (sceneId: string, kindName: string, intensity: number) =>
  apiPost<FlarePreviewTimeline>('/flare-preview/open',
    { scene_id: sceneId, kind_name: kindName, intensity });

/** The live half — fires scene+kind for real and holds it. Called once
 * per loop cycle by FlarePreviewOverlay's playhead effect, not on open. */
export const fireFlarePreview = (sceneId: string, kindName: string, intensity: number) =>
  apiPost<FlarePreviewFireResult>('/flare-preview/fire',
    { scene_id: sceneId, kind_name: kindName, intensity });

export const heartbeatFlarePreview = () =>
  apiPost<{ active: boolean; remaining_s: number; expired?: boolean; reason?: string }>(
    '/flare-preview/heartbeat', {});

export const closeFlarePreview = () =>
  apiPost<{ active: boolean }>('/flare-preview/close', {});

/** Tab-close/reload release — same sendBeacon-over-fetch rationale as
 * releasePreviewBeacon above. */
export const closeFlarePreviewBeacon = (): void => {
  try {
    navigator.sendBeacon('/spectra/api/flare-preview/close',
      new Blob(['{}'], { type: 'application/json' }));
  } catch {
    // best-effort only
  }
};

/* ── sequencer ── */

export interface CurveProfile { id: string; name: string; points: CurvePoint[]; }

export interface SelectorEntry {
  curve_ref: string | null;
  inline_points: CurvePoint[] | null;
  genre_mult: Record<string, number>;
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
  /** Minimum dwell (spectra/services/dwell.py, 2026-08-20) — process-global,
   * fed by EVERY real fire, not just this sequencer's own rolls. null
   * fields mean nothing is tracked yet (cold start, or a restart with no
   * fire since). */
  dwell: {
    active_scene_id: string | null;
    active_scene_name: string | null;
    dwell_seconds: number | null;
    remaining_s: number | null;
  };
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
    last_pick: {
      picked_id: string | null;
      picked_name: string | null;
      kept_set_id: string | null;
      rung: string;
      /** curve/genre/wheel/group/score per candidate at the FULL rung —
       * "group" is the resolved product of every enclosing Colour Group's
       * own curve (1.0 when the set is in no group / every enclosing
       * group defaulted to flat) — the observability the compounding
       * multiply needs so a starved set is explainable, not a mystery. */
      factors: Record<string, { curve: number; genre: number; wheel: number; group: number; score: number }>;
      /** POOL EXHAUSTED (owner ask 2026-08-25's safety half): nothing was
       * eligible at all, so the room KEPT its colours. The outcome is
       * always safe (a room is never left with nothing to pick) but must
       * never be silent — `pool` names how many of his sets are currently
       * Disabled, the one cause he can act on. */
      pool_exhausted?: boolean;
      pool?: { sets: number; disabled: number; eligible: number };
    } | null;
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

/* ── two-dimensional drift gradient (owner ask 2026-08-20) ── */

/** One saved 2D drift gradient — top/bottom are each the SAME "#rrggbb
 * solid or linear-gradient(...)" string every colour value in this app
 * already uses, so each edge reuses ColorGradientPicker verbatim (his ask:
 * "the UI should be very similar to the current gradient picker, just
 * make it a square"). x_mode is "part of the setting stored with the
 * gradient": bounce or loop along the x (time) axis. */
export interface DriftGradientProfile {
  id: string;
  name: string;
  top: string;
  bottom: string;
  x_mode: 'loop' | 'bounce';
}

export function useGradient2dProfiles() {
  return useQuery({
    queryKey: ['spectra-gradient2d'],
    queryFn: () => apiGet<Record<string, DriftGradientProfile>>('/gradients2d'),
  });
}

export function useSaveGradient2dProfiles() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (profiles: Record<string, DriftGradientProfile>) =>
      apiPut('/gradients2d', profiles),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['spectra-gradient2d'] }),
  });
}

/** Curve-attachment mutation: round-trips the STORED config and rewrites
 * only field[entryId]'s curve fields — relationships stay agent-owned.
 * field defaults to 'entries' (the scene selector, original behaviour);
 * pass 'color_set_entries' to attach a curve to a colour SET or GROUP card
 * instead — same dict, same reuse the owner asked for (a Group's curve is
 * just another entry here, keyed by the Group's own card id).
 *
 * 'dwell_curve' (2026-08-20, minimum dwell) is a THIRD, structurally
 * different path: not a SequencerConfig dict entry at all, but a single
 * nullable field directly on the SceneV2 named by entryId — round-trips
 * /scenes instead. 'none' here means "no override — his default 16s/4s
 * curve" (dwell_curve: null), never "not sequenced" (a per-scene minimum
 * always means something); 'flat' means an explicit flat 1.0-SECOND
 * minimum, authored as an inline one-point curve rather than the sentinel
 * null the default uses, so it stays a real, editable, distinct choice
 * from "no override" once picked. */
export function useAttachCurve(field: 'entries' | 'color_set_entries' | 'dwell_curve' = 'entries') {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: {
      entryId: string;
      attachment:
        | { kind: 'none' }
        | { kind: 'flat' }
        | { kind: 'profile'; profileId: string }
        | { kind: 'inline'; points: CurvePoint[] };
    }) => {
      if (field === 'dwell_curve') {
        const scenes = await apiGet<SceneV2[]>('/scenes');
        const scene = scenes.find((s) => s.id === args.entryId);
        if (!scene) throw new Error(`scene ${args.entryId} not found`);
        const dwell_curve =
          args.attachment.kind === 'none' ? null
          : args.attachment.kind === 'flat' ? { curve_ref: null, inline_points: [{ x: 0, y: 1 }] }
          : args.attachment.kind === 'profile' ? { curve_ref: args.attachment.profileId, inline_points: null }
          : { curve_ref: null, inline_points: args.attachment.points };
        return apiPost('/scenes', { ...scene, dwell_curve });
      }
      const config = await apiGet<SequencerConfig>('/sequencer/config');
      const map = config[field];
      const { [args.entryId]: existing, ...rest } = map;
      if (args.attachment.kind === 'none') {
        return apiPut('/sequencer/config', { ...config, [field]: rest });
      }
      const entry: SelectorEntry = existing ?? {
        curve_ref: null, inline_points: null, genre_mult: {},
      };
      const curve =
        args.attachment.kind === 'profile'
          ? { curve_ref: args.attachment.profileId, inline_points: null }
          : args.attachment.kind === 'inline'
            ? { curve_ref: null, inline_points: args.attachment.points }
            : { curve_ref: null, inline_points: null };
      return apiPut('/sequencer/config', {
        ...config,
        [field]: { ...rest, [args.entryId]: { ...entry, ...curve } },
      });
    },
    onSuccess: () => void qc.invalidateQueries({
      queryKey: field === 'dwell_curve' ? ['spectra-scenes'] : ['spectra-seq-config'],
    }),
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

/** The ambient_hue_group_ids picker's data source — every live Hue area
 * Ambient can be scoped to (spectra/services/ambient.py's list_groups()).
 * Topology is stable once the room is up, so this doesn't need the 3s
 * poll useEngineStatus uses. */
export function useAmbientHueGroups() {
  return useQuery({
    queryKey: ['spectra-ambient-hue-groups'],
    queryFn: () => apiGet<{ groups: AmbientHueGroup[] }>('/room-controls/ambient-groups'),
    staleTime: 30_000,
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

/** One light the last take-back/resume could not bring up (spectra/
 * services/activation_report.py SkippedDevice.to_json). `why` is the
 * sentence he reads; `reason` the verifier's raw text; `still_dark`
 * flips false the moment a recheck confirms the light driving. */
export interface SkippedLight {
  device_id: string;
  name: string;
  kind: 'unresolved' | 'unreachable' | 'not-receiving' | string;
  why: string;
  reason: string;
  address: string | null;
  first_seen_wall: number;
  last_checked_wall: number;
  last_checked_age_s: number;
  recovered_wall: number | null;
  recovered_age_s: number | null;
  still_dark: boolean;
  retries: number;
}

/** The activation report (spectra/services/activation_report.py
 * ActivationReport.to_json): what the last activation of the live stack
 * brought up and what it had to skip. null while the stack is down or
 * nothing was recorded. Owner ruling 2026-08-21: a take-back from
 * `released` commits over an unreachable light instead of aborting to
 * darkness — and the skipped light must be VISIBLE, not only logged. */
export interface ActivationReport {
  source: 'take-back' | 'resume' | string;
  at_wall_ms: number;
  age_s: number;
  partial: boolean;
  expected_virtuals: number;
  up_virtuals: number;
  devices_total: number;
  devices_skipped: number;
  devices_still_dark: number;
  skipped: SkippedLight[];
  virtual_gaps: Record<string, string>;
  summary: string;
  recheck_interval_s: number;
}

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
  activation: ActivationReport | null;
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
/** The way back from released. result "committed" (every light up) or
 * "committed-partial" (the room came up minus the lights named in
 * `activation` — the owner's 2026-08-21 ruling: never abort to darkness
 * over one unreachable light; never hide which one it was). */
export function useTakeBackToSpectra() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiPost<{ result: string; owner: string; activation?: ActivationReport }>(
        '/ownership/handover', { to: 'spectra' }),
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

/* ── TESTING IN PROGRESS bar (his ask 2026-08-24) ── */

/** The room-visibility surface. `retry: false` on purpose: the bar's own
 * failure handling counts CONSECUTIVE failures to debounce a transient
 * blip (TestingBar.tsx), and react-query's internal retries would hide
 * those transitions from it. 3s to match useEngineStatus. */
export function useTestSession() {
  return useQuery({
    queryKey: ['spectra-test-session'],
    queryFn: () => apiGet<TestSessionStatus>('/test-session'),
    refetchInterval: 3000,
    retry: false,
  });
}

/** Liveness — already published, no new plumbing. The bar uses it to say
 * WHICH kind of busy the room is: driving frames, or holding and not
 * painting (which is a fault, not a test). */
export function useLiveness() {
  return useQuery({
    queryKey: ['spectra-liveness'],
    queryFn: () => apiGet<Liveness>('/liveness'),
    refetchInterval: 3000,
    retry: false,
  });
}
