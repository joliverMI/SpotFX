/** Data hooks for the Absorb page — SpotFX's own /api/absorb routes, reached
 * same-origin (the runner lives in SpotFX: routers/absorb_router.py).
 *
 * Polling, not a push: the run brief also rides SpotFX's websocket `state`
 * broadcast, but a 3 s poll of GET /run while a window is open is cheap
 * (an in-memory read) and carries the full record the cards need. The
 * PREVIEW reads the whole playlist from Spotify, so it is never polled —
 * it is fetched on open, after an edit that changes its answer, and on
 * his Refresh. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { spotfxGet, spotfxPost, spotfxPut } from '../api/client';
import type {
  AbsorbActionResult, AbsorbConfig, AbsorbLaneStatus, AbsorbParkedSong, AbsorbPreview, AbsorbRunResponse,
  AbsorbSchedule, SpotifyContextOffer,
} from './types';

const KEY = {
  config: ['absorb-config'],
  run: ['absorb-run'],
  preview: ['absorb-preview'],
  schedule: ['absorb-schedule'],
  parked: ['absorb-parked'],
} as const;

const live = (d: AbsorbRunResponse | undefined) =>
  d?.brief.state === 'running' || d?.brief.state === 'paused';

export function useAbsorbConfig() {
  return useQuery({ queryKey: KEY.config, queryFn: () => spotfxGet<AbsorbConfig>('/absorb/config') });
}

/** The live (or last) run and the earlier ones — every 3 s while a window
 * is open, every 15 s otherwise (a scheduled window can open on its own). */
export function useAbsorbRun() {
  return useQuery({
    queryKey: KEY.run,
    queryFn: () => spotfxGet<AbsorbRunResponse>('/absorb/run?history=20'),
    refetchInterval: (q) => (live(q.state.data) ? 3000 : 15_000),
  });
}

export function useAbsorbPreview(enabled: boolean) {
  return useQuery({
    queryKey: KEY.preview,
    queryFn: () => spotfxGet<AbsorbPreview>('/absorb/preview'),
    enabled,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

/** The backlog on the hidden player: every 5 s while it is switched on,
 * every 30 s otherwise (an in-memory read). */
export function useAbsorbLane(on: boolean) {
  return useQuery({
    queryKey: ['absorb-lane'],
    queryFn: () => spotfxGet<AbsorbLaneStatus>('/absorb/lane'),
    refetchInterval: on ? 5000 : 30_000,
  });
}

export function useAbsorbSchedule() {
  return useQuery({
    queryKey: KEY.schedule,
    queryFn: () => spotfxGet<AbsorbSchedule>('/absorb/schedule?outcomes=10'),
    refetchInterval: 30_000,
  });
}

export function useAbsorbParked(windowIsOpen: boolean) {
  return useQuery({
    queryKey: KEY.parked,
    queryFn: () => spotfxGet<{ parked: AbsorbParkedSong[] }>('/absorb/parked'),
    refetchInterval: windowIsOpen ? 10_000 : 60_000,
  });
}

/** The recently observed Spotify contexts (playing now first), for the
 * "link a playlist" quick picks — playlists only. */
export function useSpotifyPlaylistOffers(enabled: boolean) {
  return useQuery({
    queryKey: ['absorb-spotify-offers'],
    enabled,
    queryFn: async () => {
      const r = await spotfxGet<{ playing: SpotifyContextOffer | null; recent: SpotifyContextOffer[] }>(
        '/spotify/contexts');
      const all = [
        ...(r.playing ? [r.playing] : []),
        ...(r.recent ?? []).slice().reverse(),
      ];
      return all.filter((c, i) => c.context_uri.startsWith('spotify:playlist:')
        && all.findIndex((x) => x.context_uri === c.context_uri) === i);
    },
  });
}

/** A PARTIAL config edit — only the keys sent change (PUT /config's own
 * contract). Linking a playlist or flipping force recapture changes what
 * the preview would say, so those invalidate it. */
export function useSaveAbsorbConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<AbsorbConfig>) => spotfxPut<AbsorbConfig>('/absorb/config', patch),
    onSuccess: (cfg, patch) => {
      qc.setQueryData(KEY.config, cfg);
      if ('source_playlist_uri' in patch || 'force_recapture' in patch || 'head_max_ms' in patch) {
        void qc.invalidateQueries({ queryKey: KEY.preview });
      }
      if ('windows' in patch || 'enabled' in patch) void qc.invalidateQueries({ queryKey: KEY.schedule });
      if ('use_capture_lane' in patch) void qc.invalidateQueries({ queryKey: ['absorb-lane'] });
    },
  });
}

function useRunAction(path: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body?: unknown) => spotfxPost<AbsorbActionResult>(path, body),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: KEY.run });
      void qc.invalidateQueries({ queryKey: KEY.schedule });
    },
  });
}

export const useStartAbsorb = () => useRunAction('/absorb/start');
export const useStopAbsorb = () => useRunAction('/absorb/stop');
export const useSkipAbsorbSong = () => useRunAction('/absorb/skip-song');

/** His per-song Retry: un-parks it (and, mid-run, puts it straight back
 * in the queue — `AbsorbRunner.unpark`). */
export function useRetryParked() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (uri: string) => spotfxPost<{ uri: string; unparked: boolean }>('/absorb/retry', { uri }),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: KEY.parked });
      void qc.invalidateQueries({ queryKey: KEY.run });
    },
  });
}

export const ABSORB_QUERY_KEYS = KEY;
