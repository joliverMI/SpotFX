/** Shared live engine state — one lazy WS subscription feeding a zustand
 * store. Used by Now Playing and Debug (the builder keeps its own slice).
 * Fast-changing playhead interpolation is exposed via getLiveProgressMs()
 * (module-level base, no re-renders); React text uses useLiveTick(). */
import { useEffect, useState } from 'react';
import { create } from 'zustand';
import { onMessage } from '../api/ws';

export interface LiveTrack {
  spotify_uri: string;
  title: string;
  artist: string;
  genres: string[];
  duration_ms: number;
  progress_ms: number;
  is_playing: boolean;
  device_name: string | null;
}

export interface TimingInfo {
  buffer_ms?: number;
  ledfx_rtt_ms?: number;
  shape_offset_ms?: number;
  shape_offset_quality?: number;
  effective_offset_ms?: number;
  active_setlist_id?: string | null;
  [k: string]: unknown;
}

export interface LastCapture {
  status: 'ok' | 'failed' | null;
  reason?: string;
  uri: string | null;
}

interface LiveState {
  track: LiveTrack | null;
  paused: boolean;
  onTargetDevice: boolean;
  recordingActive: boolean;
  lastCapture: LastCapture | null;
  dinnerParty: boolean;
  ambient: boolean;
  /** LedFX Hue device ids currently held in Ambient Mode */
  ambientGroups: string[];
  useAnalyzed: boolean;
  analyzedOverride: boolean;
  useAiTriggers: boolean;
  lastScene: { name: string; color: string } | null;
  lastColorSet: { name: string; color: string } | null;
  ledfxRttMs: number | null;
  timing: TimingInfo;
  nextTrackUri: string | null;
  /** engine mode flags (AI Triggers page toggles) */
  analysisEnabled: boolean;
  autoGenEnabled: boolean;
  /** wall-clock (Date.now()) of the last state message — poll age. */
  lastPollAt: number;
}

export const useLiveStore = create<LiveState>(() => ({
  track: null,
  paused: false,
  onTargetDevice: false,
  recordingActive: false,
  lastCapture: null,
  dinnerParty: false,
  ambient: false,
  ambientGroups: [],
  useAnalyzed: true,
  analyzedOverride: false,
  useAiTriggers: false,
  lastScene: null,
  lastColorSet: null,
  ledfxRttMs: null,
  timing: {},
  nextTrackUri: null,
  analysisEnabled: false,
  autoGenEnabled: false,
  lastPollAt: 0,
}));

// ── Playhead interpolation base (module-level; no store churn) ──────────────
let progressBase: { ms: number; at: number; playing: boolean } | null = null;

export function getLiveProgressMs(): number | null {
  const s = useLiveStore.getState();
  if (!s.track) return null;
  if (!progressBase) return s.track.progress_ms;
  const elapsed = progressBase.playing ? performance.now() - progressBase.at : 0;
  return Math.min(progressBase.ms + elapsed, s.track.duration_ms);
}

let started = false;
export function ensureLiveState(): void {
  if (started) return;
  started = true;

  onMessage('state', (msg) => {
    const t = msg.track as Record<string, unknown> | null;
    const track: LiveTrack | null = t
      ? {
          spotify_uri: String(t.spotify_uri ?? ''),
          title: String(t.title ?? ''),
          artist: String(t.artist ?? ''),
          genres: (t.genres as string[]) ?? [],
          duration_ms: Number(t.duration_ms ?? 0),
          progress_ms: Number(t.progress_ms ?? 0),
          is_playing: Boolean(t.is_playing),
          device_name: (t.device_name as string) ?? null,
        }
      : null;
    progressBase = track
      ? { ms: track.progress_ms, at: performance.now(), playing: track.is_playing }
      : null;
    useLiveStore.setState({
      track,
      paused: Boolean(msg.paused),
      onTargetDevice: Boolean(msg.on_target_device ?? false),
      recordingActive: Boolean(msg.recording_active ?? false),
      lastCapture: (msg.last_capture as LastCapture) ?? null,
      dinnerParty: Boolean(msg.dinner_party_mode ?? false),
      ambient: Boolean(msg.ambient_mode_enabled ?? false),
      ambientGroups: (msg.ambient_groups as string[]) ?? [],
      useAnalyzed: Boolean(msg.use_analyzed_triggerless ?? true),
      analyzedOverride: Boolean(msg.analyzed_trigger_override ?? false),
      useAiTriggers: Boolean(msg.use_unreviewed_ai_triggers ?? false),
      lastScene: msg.last_scene_name
        ? { name: String(msg.last_scene_name), color: String(msg.last_scene_color ?? '#888') }
        : null,
      lastColorSet: msg.last_color_set_name
        ? { name: String(msg.last_color_set_name), color: String(msg.last_color_set_color ?? '#888') }
        : null,
      ledfxRttMs: msg.ledfx_rtt_ms != null ? Number(msg.ledfx_rtt_ms) : null,
      timing:
        msg.timing && Object.keys(msg.timing as object).length
          ? (msg.timing as TimingInfo)
          : useLiveStore.getState().timing,
      nextTrackUri: (msg.next_track_uri as string) ?? null,
      analysisEnabled: Boolean(msg.audio_analysis_enabled ?? false),
      autoGenEnabled: Boolean(msg.auto_generate_enabled ?? false),
      lastPollAt: Date.now(),
    });
  });

  // Immediate offset refresh between 1Hz state broadcasts (anchor snap/sweep saves).
  onMessage('shape_offset_updated', (msg) => {
    const s = useLiveStore.getState();
    if (msg.uri !== s.track?.spotify_uri) return;
    useLiveStore.setState({
      timing: {
        ...s.timing,
        shape_offset_ms: Number(msg.offset_ms),
        ...(msg.quality != null ? { shape_offset_quality: Number(msg.quality) } : {}),
      },
    });
  });
}

/** Coarse re-render tick for interpolated progress text/bars. */
export function useLiveTick(intervalMs = 250): number | null {
  const [ms, setMs] = useState<number | null>(getLiveProgressMs());
  useEffect(() => {
    const t = setInterval(() => setMs(getLiveProgressMs()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return ms;
}
