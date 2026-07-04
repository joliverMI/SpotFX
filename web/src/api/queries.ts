import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost, apiDel } from './client';
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
  type: string; // numeric | color | toggle | gradient | polar | move_xy | move_polar
  min: number | null;
  max: number | null;
}

export function useParamLabels() {
  return useQuery({
    queryKey: ['param-labels'],
    queryFn: () => apiGet<ParamLabel[]>('/effect-params/labels'),
    staleTime: 60_000,
  });
}

export interface MorphAspectsInfo {
  aspect_ids: string[];
  aspect_labels: Record<string, string>;
  supported_effects: string[];
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

export function useDeleteEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDel(`/events/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['events'] }),
  });
}
