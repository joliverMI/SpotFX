/** Sequencer data hooks for the Scenes page (SPECTRA). The interface split
 * governs what the UI may WRITE: curve profiles and each scene entry's curve
 * attachment (curve_ref / inline_points) are graphical and belong to the UI;
 * relationships and durations (genre_mult, dwell_weight, affinity, enabled)
 * are agent-adjusted through PUT /api/sequencer/config and are READ-ONLY
 * here — the mutations below always round-trip the stored config and only
 * touch the curve side. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost, apiPut } from '../api/client';
import type { CurvePoint } from '../components/CurveEditor';

export interface CurveProfile {
  id: string;
  name: string;
  points: CurvePoint[];
}

export interface SelectorEntry {
  curve_ref: string | null;
  inline_points: CurvePoint[] | null;
  genre_mult: Record<string, number>;
  dwell_weight: number;
}

export interface AffinityEdge {
  from_id: string;
  to_id: string;
  mult: number;
}

export interface SequencerConfig {
  enabled: boolean;
  change_mode: 'transition' | 'timed' | 'both';
  base_dwell_s: number;
  entries: Record<string, SelectorEntry>;
  affinity: AffinityEdge[];
  flare_entries: Record<string, SelectorEntry>;
}

export interface SequencerStatus {
  enabled: boolean;
  change_mode: string;
  next_change_source: string;
  deferred_by: string | null;
  active_scene_id: string | null;
  active_scene_name: string | null;
  dwell: { served_songs: number; target_songs: number; weight: number } | null;
  last_pick: {
    picked_id: string | null;
    picked_name: string | null;
    rung: string;
    intensity: number;
    factors: Record<string, { curve: number; genre: number; affinity: number; score: number }>;
    source: string;
    at: number;
  } | null;
  last_moment: { source: string; result: string; at: number } | null;
}

export interface IntensityHistogram {
  bins: number;
  counts: number[];
  total: number;
}

export function useSequencerCurves() {
  return useQuery({
    queryKey: ['sequencer-curves'],
    queryFn: () => apiGet<Record<string, CurveProfile>>('/sequencer/curves'),
  });
}

export function useSequencerConfig() {
  return useQuery({
    queryKey: ['sequencer-config'],
    queryFn: () => apiGet<SequencerConfig>('/sequencer/config'),
  });
}

export function useSequencerStatus() {
  return useQuery({
    queryKey: ['sequencer-status'],
    queryFn: () => apiGet<SequencerStatus>('/sequencer/status'),
    refetchInterval: 5000,
  });
}

export function useIntensityHistogram() {
  return useQuery({
    queryKey: ['sequencer-intensity-histogram'],
    queryFn: () => apiGet<IntensityHistogram>('/sequencer/intensity-histogram'),
    staleTime: 300_000,
  });
}

/** Replace the whole profile library (the API validates references). */
export function useSaveCurves() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (curves: Record<string, CurveProfile>) => apiPut('/sequencer/curves', curves),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['sequencer-curves'] }),
  });
}

/** Curve-attachment mutation: round-trips the STORED config and rewrites only
 * entries[sceneId]'s curve fields (or removes the entry). Relationship fields
 * of an existing entry are preserved verbatim; a new entry gets the model
 * defaults (dwell 1.0, no genre mults) for the agent to adjust later. */
export function useAttachCurve() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: {
      sceneId: string;
      attachment:
        | { kind: 'none' }                          // remove from the sequencer
        | { kind: 'flat' }                          // entry with no curve ≡ flat 1.0
        | { kind: 'profile'; profileId: string }
        | { kind: 'inline'; points: CurvePoint[] };
    }) => {
      const config = await apiGet<SequencerConfig>('/sequencer/config');
      const { [args.sceneId]: existing, ...rest } = config.entries;
      if (args.attachment.kind === 'none') {
        return apiPut('/sequencer/config', { ...config, entries: rest });
      }
      const entry: SelectorEntry = existing ?? {
        curve_ref: null, inline_points: null, genre_mult: {}, dwell_weight: 1.0,
      };
      const curve =
        args.attachment.kind === 'profile'
          ? { curve_ref: args.attachment.profileId, inline_points: null }
          : args.attachment.kind === 'inline'
            ? { curve_ref: null, inline_points: args.attachment.points }
            : { curve_ref: null, inline_points: null };
      return apiPut('/sequencer/config', {
        ...config,
        entries: { ...rest, [args.sceneId]: { ...entry, ...curve } },
      });
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['sequencer-config'] }),
  });
}

export interface SimulateResult {
  n: number;
  intensity: number;
  kind: string;
  shares: Record<string, number>;
  rungs: Record<string, number>;
  factors: Record<string, { curve: number; genre: number; affinity: number; score: number }>;
}

export const simulate = (body: {
  intensity: number; n?: number; kind?: 'scene' | 'flare';
  current_id?: string | null; genre_bucket?: string | null; seed?: number;
}) => apiPost<SimulateResult>('/sequencer/simulate', body);
