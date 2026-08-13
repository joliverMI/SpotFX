/** Shared read hooks against the SpotFX app's /api namespace (same origin,
 * same process) — the sanctioned read-through the Timeline page uses for
 * events, colour sets, and settings. SPECTRA's own /spectra/api hooks live
 * in ../queries.ts. */
import { useQuery } from '@tanstack/react-query';
import { apiGet } from './spotfx';

export interface SpotFXEvent {
  id: string;
  name: string;
  color: string;        // always serialized by the MusicEvent model
  event_type: string;
  [k: string]: unknown;
}

export interface ColorSetCard {
  id: string;
  name: string;
  kind?: string;
  [k: string]: unknown;
}

export function useEvents() {
  return useQuery({
    queryKey: ['spotfx-events'],
    queryFn: () => apiGet<SpotFXEvent[]>('/events'),
  });
}

export function useColorSets() {
  return useQuery({
    queryKey: ['spotfx-color-sets'],
    queryFn: () => apiGet<ColorSetCard[]>('/color-sets'),
    staleTime: 60_000,
  });
}

export function useSettings() {
  return useQuery({
    queryKey: ['spotfx-settings'],
    queryFn: () => apiGet<Record<string, unknown>>('/settings'),
    staleTime: 60_000,
  });
}
