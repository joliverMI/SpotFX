/** Data hooks for the Jukebox page — SpotFX's own /api/jukebox routes,
 * reached same-origin (the engine lives in SpotFX: routers/jukebox_router.py).
 *
 * The STATUS is an in-memory read, polled every 3 s while a night runs and
 * every 15 s otherwise. The PREVIEW is what the set-list editor draws; the
 * server caches the set for 60 s, so re-reading it after every click costs
 * no Spotify call — `refresh` (his Reload) reads the playlist again. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { spotfxGet, spotfxPost, spotfxPut } from '../api/client';
import type { JukeboxPreview, JukeboxStatus, ProgramConfig, SetMoveResult } from './types';

export const JUKEBOX_KEYS = {
  config: ['jukebox-config'],
  status: ['jukebox-status'],
  preview: ['jukebox-preview'],
} as const;

export function useJukeboxConfig() {
  return useQuery({
    queryKey: JUKEBOX_KEYS.config,
    queryFn: () => spotfxGet<ProgramConfig>('/jukebox/config'),
  });
}

export function useJukeboxStatus() {
  return useQuery({
    queryKey: JUKEBOX_KEYS.status,
    queryFn: () => spotfxGet<JukeboxStatus>('/jukebox/status?count=20'),
    refetchInterval: (q) => (q.state.data?.running ? 3000 : 15_000),
  });
}

export function useJukeboxPreview(enabled: boolean) {
  return useQuery({
    queryKey: JUKEBOX_KEYS.preview,
    queryFn: () => spotfxGet<JukeboxPreview>('/jukebox/preview?count=20'),
    enabled,
    refetchOnWindowFocus: false,
  });
}

/** Save a PARTIAL program-settings edit (the server validates it whole and
 * answers 422 naming a bad key), then redraw the editor. */
export function useSaveJukeboxConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<ProgramConfig>) =>
      spotfxPut<{ config: ProgramConfig }>('/jukebox/config', patch),
    onSuccess: (r) => {
      qc.setQueryData(JUKEBOX_KEYS.config, r.config);
      qc.invalidateQueries({ queryKey: JUKEBOX_KEYS.preview });
      qc.invalidateQueries({ queryKey: JUKEBOX_KEYS.status });
    },
  });
}

/** His Reload: read the set playlist from Spotify again. */
export function useReloadSet() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => spotfxGet<JukeboxPreview>('/jukebox/preview?count=20&refresh=true'),
    onSuccess: (r) => qc.setQueryData(JUKEBOX_KEYS.preview, r),
  });
}

/** Reorder the SET PLAYLIST in Spotify (two or more ahead during a night). */
export function useMoveSetSong() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (m: { from_index: number; to_index: number }) =>
      spotfxPost<SetMoveResult>('/jukebox/set/move', m),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: JUKEBOX_KEYS.preview });
      qc.invalidateQueries({ queryKey: JUKEBOX_KEYS.status });
    },
  });
}
