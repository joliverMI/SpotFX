/** Data hooks for the Jukebox page — SpotFX's own /api/jukebox routes,
 * reached same-origin (the engine lives in SpotFX: routers/jukebox_router.py).
 *
 * The STATUS is an in-memory read, polled every 3 s while a night runs and
 * every 15 s otherwise. The PREVIEW is what the set-list editor draws; the
 * server caches the set for 60 s, so re-reading it after every click costs
 * no Spotify call — `refresh` (his Reload) reads the playlist again. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { spotfxDel, spotfxGet, spotfxPost, spotfxPut } from '../api/client';
import type {
  BonusCodesRead, CardRead, GuestsRead, JukeboxBoardRead, JukeboxPreview, JukeboxStatus, NightReport, PriceCheck,
  ProgramConfig, SetMoveResult, ShowRead, SimResult,
} from './types';

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

// ── the show settings (phase 3.3) ───────────────────────────────────────────

export const SHOW_KEYS = {
  show: ['jukebox-show'],
  priceCheck: (guests: number) => ['jukebox-price-check', guests],
} as const;

export function useJukeboxShow() {
  return useQuery({ queryKey: SHOW_KEYS.show, queryFn: () => spotfxGet<ShowRead>('/jukebox/show') });
}

export function usePriceCheck(guests: number) {
  return useQuery({
    queryKey: SHOW_KEYS.priceCheck(guests),
    queryFn: () => spotfxGet<PriceCheck>(`/jukebox/price-check?guests=${guests}`),
  });
}

/** A PARTIAL edit — the server validates it whole and answers 422 naming a
 * bad key; on success the price check is worked again. */
export function useSaveShow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: { economy?: Record<string, number | boolean>; approve_new_phones?: boolean }
      & Record<string, unknown>) =>
      spotfxPut<ShowRead>('/jukebox/show', patch),
    onSuccess: (r) => {
      qc.setQueryData(SHOW_KEYS.show, r);
      qc.invalidateQueries({ queryKey: ['jukebox-price-check'] });
      qc.invalidateQueries({ queryKey: ['jukebox-board'] });
    },
  });
}

export function useApplyPreset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (preset: string) => spotfxPost<ShowRead & { config: ProgramConfig }>('/jukebox/show/preset', { preset }),
    onSuccess: (r) => {
      qc.setQueryData(SHOW_KEYS.show, r);
      qc.setQueryData(JUKEBOX_KEYS.config, r.config);
      qc.invalidateQueries({ queryKey: JUKEBOX_KEYS.preview });
      qc.invalidateQueries({ queryKey: JUKEBOX_KEYS.status });
    },
  });
}

// ── the party simulator (phase 3.4) ─────────────────────────────────────────

export interface SimulateRequest {
  guests: number;
  nights?: number;
  seed: number;
  program: 'saved' | 'preset';
}

/** One model night under the SAVED settings (POST, since it runs a
 * simulation — it writes nothing). */
export function useSimulate() {
  return useMutation({
    mutationFn: (req: SimulateRequest) => spotfxPost<SimResult>('/jukebox/simulate', { nights: 20, ...req }),
  });
}

// ── the post-party report ───────────────────────────────────────────────────

/** The latest night's report; with a party size the model's nights come
 * alongside (a simulation server-side, so it is fetched on demand). */
export function useJukeboxReport(enabled: boolean, guests: number | null, nightId: string | null) {
  return useQuery({
    queryKey: ['jukebox-report', nightId, guests],
    queryFn: () => spotfxGet<NightReport>(`/jukebox/report${guests ? `?guests=${guests}` : ''}`),
    enabled,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

// ── the host's controls over tonight's guests (phase 2.2) ───────────────────

export function useGuests(running: boolean) {
  return useQuery({
    queryKey: ['jukebox-guests'],
    queryFn: () => spotfxGet<GuestsRead>('/jukebox/guests'),
    refetchInterval: running ? 5000 : 30000,
  });
}

/** The board (tonight's top songs, the people boards, the song playing):
 *  the Guests tab's Board card and the TV page. */
export function useJukeboxBoard(fast: boolean) {
  return useQuery({
    queryKey: ['jukebox-board'],
    queryFn: () => spotfxGet<JukeboxBoardRead>('/jukebox/board'),
    refetchInterval: fast ? 5000 : 15000,
  });
}

/** The host's gift (report §4: "Everyone +2", "Give…"), credits mode. */
export function useGift() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ to, amount }: { to: string; amount: number }) => {
      const r = await spotfxPost<{ status: string; detail?: string;
        gift?: { amount: number; phones: number; names: string[] } }>('/jukebox/gift', { to, amount });
      if (r.status === 'refused') throw new Error(r.detail || 'The gift could not be given.');
      return r;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jukebox-guests'] }),
  });
}

const BONUS_KEY = ['jukebox-bonus-codes'];
const CARD_KEY = ['jukebox-card'];

/** The printable card's link and unused codes (the token is made if missing). */
export function useJukeboxCard() {
  return useQuery({ queryKey: CARD_KEY, queryFn: () => spotfxGet<CardRead>('/jukebox/card') });
}

/** Set the guest link's public address (serenity.<tailnet>.ts.net) — the one
 *  guest-link validator; it never switches the link on. */
export function useSaveLinkHost() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (host: string) => spotfxPut<unknown>('/jukebox/guest-link', { public_host: host }),
    onSuccess: () => qc.invalidateQueries({ queryKey: CARD_KEY }),
  });
}

/** The printed bonus cards' codes, unused first. */
export function useBonusCodes() {
  return useQuery({ queryKey: BONUS_KEY, queryFn: () => spotfxGet<BonusCodesRead>('/jukebox/bonus-codes') });
}

/** Make a batch of one-time codes for the printed cards. */
export function useMintBonus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ count, batch }: { count: number; batch?: string }) =>
      spotfxPost<BonusCodesRead>('/jukebox/bonus-codes', { count, batch: batch ?? '' }),
    onSuccess: (r) => qc.setQueryData(BONUS_KEY, r),
  });
}

/** Void an unused code (a lost card). */
export function useVoidBonus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (code: string) => spotfxDel<BonusCodesRead>(`/jukebox/bonus-codes/${encodeURIComponent(code)}`),
    onSuccess: (r) => qc.setQueryData(BONUS_KEY, r),
  });
}

/** Approve, block, rename, lock the name of, or pardon one phone. */
export function useHostPhone() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...patch }: { id: string; approved?: boolean; blocked?: boolean;
                                     name_locked?: boolean; name?: string; pardon?: boolean }) =>
      spotfxPost<GuestsRead>(`/jukebox/guests/${encodeURIComponent(id)}`, patch),
    onSuccess: (r) => {
      qc.setQueryData(['jukebox-guests'], r);
      qc.invalidateQueries({ queryKey: JUKEBOX_KEYS.status });
    },
  });
}

/** Hold a waiting song (it keeps its place; slots pass it) or let it go. */
export function useHoldEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, held }: { id: string; held: boolean }) =>
      spotfxPost<{ status: string; detail?: string }>(`/jukebox/line/${encodeURIComponent(id)}/hold`, { held }),
    onSuccess: () => qc.invalidateQueries({ queryKey: JUKEBOX_KEYS.status }),
  });
}

/** Play next (free play's host-only move): a waiting song to the front of
 * the waiting songs. A refusal (it was sent to Spotify meanwhile) is an error. */
export function usePlayNext() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const r = await spotfxPost<{ status: string; detail?: string }>(
        `/jukebox/line/${encodeURIComponent(id)}/move`, { to: 0 });
      if (r.status === 'refused') throw new Error(r.detail || 'It could not move.');
      return r;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: JUKEBOX_KEYS.status }),
  });
}

/** Keep a song from every skip tonight — the room's vote and a paid skip —
 * or let it be skipped again. */
export function useSkipLock() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ uri, locked }: { uri: string; locked: boolean }) => {
      const r = await spotfxPost<{ status: string; detail?: string }>('/jukebox/skip-lock', { uri, locked });
      if (r.status === 'refused') throw new Error(r.detail || 'That could not change.');
      return r;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: JUKEBOX_KEYS.status }),
  });
}

/** Remove a song from the line (one already sent to Spotify is skipped as it starts). */
export function useRemoveEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => spotfxDel<{ status: string; detail?: string }>(`/jukebox/line/${encodeURIComponent(id)}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: JUKEBOX_KEYS.status });
      qc.invalidateQueries({ queryKey: ['jukebox-guests'] });
    },
  });
}
