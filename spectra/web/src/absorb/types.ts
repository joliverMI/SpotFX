/** The wire shapes of SpotFX's own /api/absorb routes (routers/
 * absorb_router.py; models/absorb.py is the binding statement for every
 * field). The Absorb page reaches them same-origin, exactly as the
 * Timeline reaches SpotFX's /api — SPECTRA's own backend never sees them. */

export type AbsorbRunState = 'running' | 'paused' | 'ended' | 'refused';
export type AbsorbPlayMode = 'fresh' | 'recapture' | 'warmup';

export interface AbsorbCounts {
  captured: number;
  failed: number;
  requeued: number;
  skipped: number;
  parked: number;
  head_missed: number;
}

export interface AbsorbHeadTally {
  attempted: number;
  with_head: number;
}

export interface AbsorbHeadRate extends AbsorbHeadTally {
  /** Only on the full run record, never on the brief. */
  by_mode?: Record<string, AbsorbHeadTally>;
}

export interface AbsorbNowPlaying {
  uri: string;
  title: string;
  started_ms: number;
  attempt: number;
  mode: AbsorbPlayMode;
}

/** `{start, end}` in epoch ms (`end` null for a press), plus
 * `scheduled_start`/`label` for a window the schedule opened. */
export interface AbsorbRunWindow {
  start?: number;
  end?: number | null;
  scheduled_start?: number;
  label?: string;
}

/** `absorb.brief()` — small and flat; what every action answers with. */
export interface AbsorbBrief {
  state: AbsorbRunState | 'idle';
  stage?: string;
  run_id?: string;
  started_ms?: number;
  ended_ms?: number;
  end_reason?: string;
  end_detail?: string;
  started_by?: string;
  source_playlist_uri?: string;
  source_playlist_name?: string;
  now_playing?: AbsorbNowPlaying | null;
  queue_len?: number;
  counts?: AbsorbCounts;
  head_rate?: AbsorbHeadTally;
  lights_held?: boolean;
  silent?: boolean;
  restore_pending?: string;
  sleeping_at_open?: boolean | null;
  yields?: number;
  resumes?: number;
  window?: AbsorbRunWindow;
  opened_ms?: number;
  wait_reason?: string;
  wait_detail?: string;
}

export interface AbsorbSongEntry {
  uri: string;
  title: string;
  at_ms: number;
  attempt: number;
  mode: string;
  reason: string;
  detail: string;
  head_ms: number | null;
}

/** A committed re-capture's timebase realign (report §8.3 item 4):
 * `triggers > 0` means his authored marks on that song were moved. */
export interface AbsorbRealign {
  uri: string;
  title: string;
  status: string;
  shift_ms: number;
  r: number;
  triggers: number;
  at_ms: number;
}

export interface AbsorbSilenceCheck {
  at_ms: number;
  ok: boolean;
  detail: string;
  sleeping?: boolean;
}

export interface AbsorbCaptureClient {
  id?: string;
  name?: string;
  percent?: number;
  muted?: boolean;
  group_muted?: boolean;
}

export interface AbsorbRun {
  id: string;
  state: AbsorbRunState;
  started_ms: number;
  ended_ms: number;
  end_reason: string;
  end_detail: string;
  window: AbsorbRunWindow;
  started_by: string;
  /** The restore contract: what the house was before the window silenced it. */
  pre_window: {
    snap_volume?: number;
    capture?: AbsorbCaptureClient;
    muted?: { id: string; name?: string; percent?: number }[];
    via?: string;
  };
  queue: string[];
  now_playing: AbsorbNowPlaying | null;
  captured: AbsorbSongEntry[];
  failed: AbsorbSongEntry[];
  parked: AbsorbSongEntry[];
  skipped: AbsorbSongEntry[];
  counts: AbsorbCounts;
  head_rate: AbsorbHeadRate;
  realigned: AbsorbRealign[];
  sleeping_at_open: boolean | null;
  silence_checks: AbsorbSilenceCheck[];
  yields: { at_ms?: number; foreign_uri?: string; restored_ms?: number }[];
  resumes: number;
  log: string[];
  opened_ms: number;
  wait_reason: string;
  wait_detail: string;
  silent: boolean;
  lights_held: boolean;
  restore: { at_ms?: number; ok?: boolean; detail?: string; why?: string };
  restore_pending: string;
  source_playlist_uri: string;
  source_playlist_name: string;
  stage: string;
}

/** `absorb_store.compact()` — an earlier run, small. */
export interface AbsorbRunSummary {
  id: string;
  state: AbsorbRunState;
  started_ms: number;
  ended_ms: number;
  end_reason: string;
  end_detail: string;
  started_by: string;
  window: AbsorbRunWindow;
  opened_ms: number;
  source_playlist_uri: string;
  source_playlist_name: string;
  counts: AbsorbCounts;
  head_rate: AbsorbHeadRate;
  parked: AbsorbSongEntry[];
  realigned: AbsorbRealign[];
}

export interface AbsorbRunResponse {
  brief: AbsorbBrief;
  run: AbsorbRun | null;
  earlier: AbsorbRunSummary[];
}

export interface AbsorbWindow {
  days: string[];
  start: string;
  end: string;
}

export type AbsorbOrder = 'fresh_first' | 'playlist' | 'worst_head_first';

export interface AbsorbConfig {
  enabled: boolean;
  source_playlist_uri: string;
  captured_playlist_name: string;
  force_recapture: boolean;
  head_max_ms: number;
  order: AbsorbOrder;
  warm_up: boolean;
  windows: AbsorbWindow[];
  max_attempts: number;
  play_window_size: number;
  overrun_grace_min: number;
  recently_captured_max: number;
  recently_captured_includes_skipped: boolean;
  resume_after_quiet_min: number;
  min_remaining_min: number;
  max_resumes_per_window: number;
  run_while_sleeping: boolean;
  silence_recheck_s: number;
  /** the hidden player learns never-captured songs when nothing else runs (phase 4; ships off) */
  use_capture_lane?: boolean;
}

/** GET /api/absorb/lane — Absorb's backlog on the hidden player
 * (services/absorb_lane.py). */
export interface AbsorbLaneStatus {
  enabled: boolean;
  state: 'off' | 'resting' | 'learning' | 'idle';
  /** why it isn't learning right now ("" while it is) */
  reason: string;
  job: { job_id: string; uri: string; title: string; artist: string; duration_ms: number; started_ms?: number } | null;
  learned: { uri: string; title: string; at_ms: number }[];
  failed: { uri: string; title: string; reason: string; attempt: number; at_ms: number }[];
  /** songs passed over after using up their tries */
  passed_over: string[];
  log: string[];
}

export interface AbsorbPreviewCounts {
  total: number;
  skip: number;
  fresh: number;
  recapture: number;
  parked: number;
}

export interface AbsorbPreview {
  linked: boolean;
  resolved?: boolean;
  detail?: string;
  playlist?: { id: string; name: string; snapshot_id?: string };
  counts?: AbsorbPreviewCounts;
  reasons?: Record<string, number>;
  force_recapture?: boolean;
  head_max_ms?: number;
}

export interface AbsorbOccurrence {
  start_ms: number;
  end_ms: number;
  label: string;
  window_index: number;
  fired?: boolean;
  in_s?: number;
}

export interface AbsorbScheduleOutcome {
  occurrence_start_ms: number;
  occurrence_end_ms: number;
  label: string;
  at_ms: number;
  outcome: string;
  reason: string;
  detail: string;
  run_id: string;
  run: {
    state?: AbsorbRunState;
    end_reason?: string;
    end_detail?: string;
    opened_ms?: number;
    counts?: AbsorbCounts;
    head_rate?: AbsorbHeadRate;
  } | null;
}

export interface AbsorbSchedule {
  enabled: boolean;
  /** Switched on AND at least one window — only then does a window open on its own. */
  active: boolean;
  house_tz: string;
  windows: (AbsorbWindow & { index: number; label: string })[];
  open_now: AbsorbOccurrence[];
  next: AbsorbOccurrence | null;
  overrun_grace_min: number;
  outcomes: AbsorbScheduleOutcome[];
}

export interface AbsorbParkedSong {
  uri: string;
  title: string;
  reason: string;
  parked_ms: number;
  lifetime_attempts: number;
  last_failure: string;
  last_attempt_ms: number;
}

export interface AbsorbActionResult {
  status: string;
  reason?: string;
  detail?: string;
  run?: AbsorbBrief;
  skipped_uri?: string;
}

export interface SpotifyContextOffer {
  context_uri: string;
  type: string;
  name: string;
}
