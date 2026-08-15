/** Live engine timing feed for the ported Timing/Debug pages — a trimmed
 * port of spot-effects' shared live/liveStore.ts (its Now Playing + Debug
 * feed), kept to just the fields these two pages read: track basics,
 * timing (the xcorr shape_offset_ms family), ledfx_rtt_ms, poll age, and
 * the analyzed-triggerless override flag. SPECTRA's ported timeline
 * (spectra/web/src/timeline/) already has its own separate, lighter
 * position tracker (hooks/usePlayhead.ts) for the trigger-authoring
 * canvas — this isn't a merge of the two, it's the same pattern spot-
 * effects itself uses (Now Playing, Builder, and Debug each read the
 * same same-origin WS "state" broadcast independently) applied to this
 * page pair. Fast-changing playhead interpolation is exposed via
 * getLiveProgressMs() (module-level base, no re-renders), matching
 * spot-effects' own getLiveProgressMs(). */
import { create } from 'zustand';
import { onMessage } from '../api/ws';

export interface LiveTrack {
  spotify_uri: string;
  title: string;
  artist: string;
  duration_ms: number;
  progress_ms: number;
  is_playing: boolean;
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

interface LiveState {
  track: LiveTrack | null;
  analyzedOverride: boolean;
  ledfxRttMs: number | null;
  timing: TimingInfo;
  /** wall-clock (Date.now()) of the last state message — poll age. */
  lastPollAt: number;
}

export const useLiveStore = create<LiveState>(() => ({
  track: null,
  analyzedOverride: false,
  ledfxRttMs: null,
  timing: {},
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
          duration_ms: Number(t.duration_ms ?? 0),
          progress_ms: Number(t.progress_ms ?? 0),
          is_playing: Boolean(t.is_playing),
        }
      : null;
    progressBase = track
      ? { ms: track.progress_ms, at: performance.now(), playing: track.is_playing }
      : null;
    useLiveStore.setState({
      track,
      analyzedOverride: Boolean(msg.analyzed_trigger_override ?? false),
      ledfxRttMs: msg.ledfx_rtt_ms != null ? Number(msg.ledfx_rtt_ms) : null,
      timing:
        msg.timing && Object.keys(msg.timing as object).length
          ? (msg.timing as TimingInfo)
          : useLiveStore.getState().timing,
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
