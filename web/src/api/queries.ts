import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, apiGet, apiPost, apiDel } from './client';
import type { MusicEvent } from '../types/events';

export interface ColorSetCard {
  id: string;
  name: string;
  kind?: string;
  [k: string]: unknown;
}

export function useEvents() {
  return useQuery({
    queryKey: ['events'],
    queryFn: () => apiGet<MusicEvent[]>('/events'),
  });
}

export function useColorSets() {
  return useQuery({
    queryKey: ['color-sets'],
    queryFn: () => apiGet<ColorSetCard[]>('/color-sets'),
    staleTime: 60_000,
  });
}

export interface LedFxScene {
  id: string;
  name: string;
}

export function useScenes() {
  return useQuery({
    queryKey: ['ledfx-scenes'],
    queryFn: () => apiGet<LedFxScene[]>('/control/ledfx/scenes'),
    staleTime: 60_000,
  });
}

export interface ParamLabel {
  label: string;
  type: string; // numeric | color | toggle | gradient | polar | move_xy | move_polar | string
  min: number | null;
  max: number | null;
  options_source?: string | null; // e.g. "gif_assets" → populate a dropdown
}

export function useParamLabels() {
  return useQuery({
    queryKey: ['param-labels'],
    queryFn: () => apiGet<ParamLabel[]>('/effect-params/labels'),
    staleTime: 60_000,
  });
}

export interface GifAsset {
  id: string;
  path: string;
  style?: string;
  energy?: string;
  frames?: number;
  beat_frames?: string;
  big_variant?: string;
  uploaded: boolean;
}

export function useGifAssets() {
  return useQuery({
    queryKey: ['gif-assets'],
    queryFn: () => apiGet<{ assets: GifAsset[] }>('/gif-assets'),
    staleTime: 60_000,
  });
}

export interface AspectParamMeta {
  label: string;
  type: string;
  min: number | null;
  max: number | null;
  aspect: string | null;
  aspect_scale: number | null;
  distribute: boolean;
}

export interface MorphAspectsInfo {
  aspect_ids: string[];
  aspect_labels: Record<string, string>;
  supported_effects: string[];
  // {effect_type: {param_name: meta}} for every aspect-tagged param
  param_meta?: Record<string, Record<string, AspectParamMeta>>;
}

export interface ParamConfig {
  categories: Record<string, { virtuals: string[] }>;
}

export function useParamConfig() {
  return useQuery({
    queryKey: ['param-config'],
    queryFn: () => apiGet<ParamConfig>('/effect-params/config'),
    staleTime: 60_000,
  });
}

export function useMorphAspects() {
  return useQuery({
    queryKey: ['morph-aspects'],
    queryFn: () => apiGet<MorphAspectsInfo>('/morph/aspects'),
    staleTime: 60_000,
  });
}

export function useSettings() {
  return useQuery({
    queryKey: ['settings'],
    queryFn: () => apiGet<Record<string, unknown>>('/settings'),
    staleTime: 60_000,
  });
}

export interface AmbientGroup {
  id: string;      // LedFX Hue device id
  name: string;    // friendly name from the device config
  ambient: boolean; // currently held in Ambient Mode
}

export function useAmbientGroups() {
  return useQuery({
    queryKey: ['ambient-groups'],
    queryFn: () => apiGet<{ groups: AmbientGroup[]; transition_s: number }>('/control/ambient-groups'),
    staleTime: 300_000, // topology is stable; live held-state comes from the WS store
  });
}

export function usePatchSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Record<string, unknown>) => api('PATCH', '/settings', patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  });
}

export function useFireEvent() {
  return useMutation({
    mutationFn: (id: string) => apiPost(`/events/${id}/fire`),
  });
}

export function useSaveEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (event: MusicEvent) => apiPost<MusicEvent>('/events', event),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['events'] }),
  });
}

/** Built-in events only: drop the saved settings overrides. */
export function useResetEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiPost(`/events/${id}/reset`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['events'] }),
  });
}

export function useDeleteEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDel(`/events/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['events'] }),
  });
}
