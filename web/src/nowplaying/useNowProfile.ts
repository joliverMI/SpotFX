/** The Now Playing trigger list: user profile triggers enriched with event
 * name/color, overridden by the engine's active non-user source (triggerless /
 * analyzed / analyzed_override) — port of legacy loadProfile(). */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiGet } from '../api/client';
import { useEvents } from '../api/queries';
import { useProfileByUri } from '../builder/queries';
import { useLiveStore } from '../live/liveStore';

export interface DisplayTrigger {
  id: string;
  timestamp_ms: number;
  event_id: string;
  name: string;
  color: string;
  labels: string[];
  intensity: number; // 0-1 — drawn as the circle height on the shape graph
}

interface ActiveTriggers {
  source: string; // 'user' | 'none' | 'triggerless' | 'analyzed' | 'analyzed_override'
  triggers: {
    id: string; timestamp_ms: number; event_id: string;
    labels?: string[]; intensity?: number;
  }[];
}

export type TriggerSource =
  | 'manual' | 'ai_generated' | 'triggerless' | 'analyzed' | 'analyzed_override' | 'none';

export function useNowProfile(uri: string | null) {
  const useAnalyzed = useLiveStore((s) => s.useAnalyzed);
  const analyzedOverride = useLiveStore((s) => s.analyzedOverride);
  const dinnerParty = useLiveStore((s) => s.dinnerParty);

  const { data: profile } = useProfileByUri(uri);
  const { data: events } = useEvents();
  const { data: active } = useQuery({
    // Refetch whenever a mode toggle changes — the engine swaps trigger sources.
    queryKey: ['active-triggers', uri, useAnalyzed, analyzedOverride, dinnerParty],
    queryFn: () => apiGet<ActiveTriggers>('/control/active-triggers'),
    enabled: !!uri,
    retry: false,
  });

  return useMemo(() => {
    const evById = new Map((events ?? []).map((e) => [e.id, e]));
    let source: TriggerSource = 'none';
    let triggers: DisplayTrigger[] = [];

    if (active && active.source !== 'user' && active.source !== 'none' && active.triggers?.length) {
      source = active.source as TriggerSource;
      const fallback = active.source.startsWith('analyzed') ? '#4caf50' : '#9c27b0';
      triggers = active.triggers.map((t) => {
        const ev = evById.get(t.event_id);
        return {
          id: t.id,
          timestamp_ms: t.timestamp_ms,
          event_id: t.event_id,
          name: ev?.name ?? t.event_id,
          color: ev?.color ?? fallback,
          labels: t.labels ?? [],
          intensity: t.intensity ?? 0.5,
        };
      });
    } else if (profile?.triggers?.length) {
      source = (profile as { ai_generated?: boolean }).ai_generated ? 'ai_generated' : 'manual';
      triggers = profile.triggers.map((t) => {
        const ev = evById.get(t.event_id);
        return {
          id: t.id,
          timestamp_ms: t.timestamp_ms,
          event_id: t.event_id,
          name: ev?.name ?? t.event_id,
          color: ev?.color ?? '#888',
          labels: t.labels ?? [],
          intensity: (t as { intensity?: number }).intensity ?? 0.5,
        };
      });
    }
    triggers.sort((a, b) => a.timestamp_ms - b.timestamp_ms);
    return { profile: profile ?? null, triggers, source };
  }, [profile, events, active]);
}

export const SOURCE_BADGE: Record<TriggerSource, { label: string; color: string } | null> = {
  none: null,
  manual: { label: 'Manual', color: '#888' },
  ai_generated: { label: 'AI Generated', color: '#00bcd4' },
  triggerless: { label: 'Simple Triggerless', color: '#9c27b0' },
  analyzed: { label: 'Auto Triggerless', color: '#4caf50' },
  analyzed_override: { label: 'Analyzed Override', color: '#4caf50' },
};
