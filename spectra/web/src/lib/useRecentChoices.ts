import { useCallback, useMemo } from 'react';
import { useSticky } from './useSticky';

const MAX_RECENTS = 6;

function asIdList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

/** Most-recently-used ids, newest first, deduped, capped at MAX_RECENTS —
 * a per-viewer convenience (localStorage, via useSticky) for "what did I
 * pick here last time", the same shape FeedbackPage's own local queue uses.
 * This is never a source of truth for what's currently selected — callers
 * own that (a `RoomControlState` field, here); `record()` only ever appends
 * to the memory of past picks, and a stale id (the scene/colour set it
 * named has since been deleted) is the caller's job to filter out of the
 * options it still recognises before rendering a button for it. */
export function useRecentChoices(storageKey: string) {
  const [stored, setStored] = useSticky<string[]>(storageKey, []);
  const recents = useMemo(() => asIdList(stored), [stored]);

  const record = useCallback((id: string) => {
    if (!id) return;
    setStored((prev) => [id, ...asIdList(prev).filter((v) => v !== id)].slice(0, MAX_RECENTS));
  }, [setStored]);

  return { recents, record };
}
