import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost, apiDel, api } from '../api/spotfx';
import type {
  AudioShapeData, AudioShapeMeta, LibrosaAnalysis, Palette, Setlist, SongProfile,
} from './types';

const enc = encodeURIComponent;

export function useProfileByUri(uri: string | null) {
  return useQuery({
    queryKey: ['profile', uri],
    queryFn: () => apiGet<SongProfile>(`/profiles/by-uri?uri=${enc(uri!)}`),
    enabled: !!uri,
    retry: false,
  });
}

export function useAudioShapeMeta(uri: string | null) {
  return useQuery({
    queryKey: ['shape-meta', uri],
    queryFn: () => apiGet<AudioShapeMeta>(`/audio-shape/meta?uri=${enc(uri!)}`),
    enabled: !!uri,
    retry: false,
  });
}

export function useAudioShapeData(uri: string | null, captureComplete: boolean) {
  return useQuery({
    queryKey: ['shape-data', uri],
    queryFn: () => apiGet<AudioShapeData>(`/audio-shape/data?uri=${enc(uri!)}`),
    enabled: !!uri && captureComplete,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

/** In-progress capture polling — only while analysis is on and the capture
 * isn't complete. Serves the same band arrays as /data (avg_rms_1s absent). */
export function useLiveShape(uri: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['shape-live', uri],
    queryFn: () => apiGet<AudioShapeData>(`/audio-shape/live?uri=${enc(uri!)}`),
    enabled: !!uri && enabled,
    refetchInterval: 1000,
    retry: false,
    gcTime: 0,
  });
}

/** Whether xcorr auto-calibration is currently targeting this song — ported
 * from the legacy builder's on-load status readout. */
export function useCalibrationStatus(uri: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['calibration-status', uri],
    queryFn: () => apiGet<{ active: boolean }>(`/audio-shape/calibration-status?uri=${enc(uri!)}`),
    enabled: !!uri && enabled,
    refetchInterval: 15_000,
    retry: false,
  });
}

export function useLibrosa(uri: string | null) {
  return useQuery({
    queryKey: ['librosa', uri],
    queryFn: () => apiGet<LibrosaAnalysis>(`/audio-shape/librosa?uri=${enc(uri!)}`),
    enabled: !!uri,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useProfilesList() {
  return useQuery({
    queryKey: ['profiles-list'],
    queryFn: () => apiGet<SongProfile[]>('/profiles'),
    staleTime: 60_000,
  });
}

export function useSaveProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (profile: SongProfile) => apiPost('/profiles', profile),
    onSuccess: (_d, profile) =>
      qc.invalidateQueries({ queryKey: ['profile', profile.spotify_uri] }),
  });
}

export function usePalettes() {
  return useQuery({
    queryKey: ['palettes'],
    queryFn: () => apiGet<Palette[]>('/palettes'),
    staleTime: 60_000,
  });
}

export function usePaletteMutations() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ['palettes'] });
  return {
    create: useMutation({
      mutationFn: (p: Omit<Palette, 'id'>) => apiPost<Palette>('/palettes', p),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, ...p }: Palette) => api<Palette>('PATCH', `/palettes/${id}`, p),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: string) => apiDel(`/palettes/${id}`),
      onSuccess: invalidate,
    }),
  };
}

export function useSetlists() {
  return useQuery({
    queryKey: ['setlists'],
    queryFn: () => apiGet<Setlist[]>('/setlists'),
    staleTime: 60_000,
  });
}
