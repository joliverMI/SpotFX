import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, apiDel, apiGet, apiPost } from '../api/client';
import type { ColorSetCard, SavedGradient } from './types';

export function useColorSetCards() {
  return useQuery({
    // Same key as api/queries useColorSets so the events page shares the cache.
    queryKey: ['color-sets'],
    queryFn: () => apiGet<ColorSetCard[]>('/color-sets'),
  });
}

export function useSaveColorSet() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (card: ColorSetCard) => apiPost('/color-sets', card),
    onSuccess: (_d, card) => {
      // Patch the cache immediately so a just-saved (possibly brand-new) card
      // doesn't flicker out of the list while the refetch is in flight.
      qc.setQueryData<ColorSetCard[]>(['color-sets'], (old) => {
        if (!old) return old;
        return old.some((c) => c.id === card.id)
          ? old.map((c) => (c.id === card.id ? card : c))
          : [...old, card];
      });
      void qc.invalidateQueries({ queryKey: ['color-sets'] });
    },
  });
}

export function useDeleteColorSet() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDel(`/color-sets/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['color-sets'] }),
  });
}

export function useGradients() {
  return useQuery({
    queryKey: ['gradients'],
    queryFn: () => apiGet<SavedGradient[]>('/gradients'),
    staleTime: 60_000,
  });
}

export function useGradientMutations() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ['gradients'] });
  return {
    create: useMutation({
      mutationFn: (g: { name: string; value: string }) => apiPost<SavedGradient>('/gradients', g),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, ...g }: SavedGradient) => api<SavedGradient>('PATCH', `/gradients/${id}`, g),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: string) => apiDel(`/gradients/${id}`),
      onSuccess: invalidate,
    }),
  };
}
