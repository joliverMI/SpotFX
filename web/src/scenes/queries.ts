import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiDel, apiGet, apiPost } from '../api/client';
import type { ColorWheelPosition, EffectParamMeta, FireResult, SceneV2 } from './types';

export function useScenesV2() {
  return useQuery({
    queryKey: ['scenes-v2'],
    queryFn: () => apiGet<SceneV2[]>('/scenes-v2'),
  });
}

export function useSaveSceneV2() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (scene: SceneV2) => apiPost('/scenes-v2', scene),
    onSuccess: (_d, scene) => {
      // Patch the cache so a just-saved scene doesn't flicker out of the list.
      qc.setQueryData<SceneV2[]>(['scenes-v2'], (old) => {
        if (!old) return old;
        return old.some((s) => s.id === scene.id)
          ? old.map((s) => (s.id === scene.id ? scene : s))
          : [...old, scene];
      });
      void qc.invalidateQueries({ queryKey: ['scenes-v2'] });
    },
  });
}

export function useDeleteSceneV2() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDel(`/scenes-v2/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scenes-v2'] }),
  });
}

/** Computed wheel positions for every Color Set, keyed by set id. */
export function useWheelPositions() {
  return useQuery({
    queryKey: ['scenes-v2-wheel-positions'],
    queryFn: () => apiGet<Record<string, ColorWheelPosition>>('/scenes-v2/wheel-positions'),
    staleTime: 60_000,
  });
}

export const fireSceneV2 = (id: string, dryRun = true) =>
  apiPost<FireResult>(`/scenes-v2/${id}/fire`, { dry_run: dryRun });

/** The full /effect-params/config payload — same endpoint (and cache entry)
 * as useParamConfig, typed here for the parts the Scenes page needs. */
export interface EffectConfig {
  categories: Record<
    string,
    { id: string; virtuals: string[]; effects: string[] }
  >;
  effects: Record<string, { params?: Record<string, EffectParamMeta> }>;
}

export function useEffectConfig() {
  return useQuery({
    queryKey: ['param-config'],
    queryFn: () => apiGet<EffectConfig>('/effect-params/config'),
    staleTime: 60_000,
  });
}
