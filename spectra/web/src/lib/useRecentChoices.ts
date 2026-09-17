import { useCallback, useState } from 'react';

const MAX_RECENTS = 6;

function readRecents(key: string): string[] {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : [];
  } catch {
    return [];
  }
}

function writeRecents(key: string, ids: string[]) {
  try {
    window.localStorage.setItem(key, JSON.stringify(ids));
  } catch {
    // per-viewer convenience only — a blocked/full store just means no
    // memory persists this session, never a reason to fail the pick itself.
  }
}

/** Most-recently-used ids, newest first, deduped, capped at MAX_RECENTS —
 * a per-viewer convenience (localStorage) for "what did I pick here last
 * time", the same shape FeedbackPage's own local queue uses. This is
 * never a source of truth for what's currently selected — callers own
 * that (a `RoomControlState` field, here); `record()` only ever appends
 * to the memory of past picks, and a stale id (the scene/colour set it
 * named has since been deleted) is the caller's job to filter out of the
 * options it still recognises before rendering a button for it. */
export function useRecentChoices(storageKey: string) {
  const [recents, setRecents] = useState<string[]>(() => readRecents(storageKey));

  const record = useCallback((id: string) => {
    if (!id) return;
    setRecents((prev) => {
      const next = [id, ...prev.filter((v) => v !== id)].slice(0, MAX_RECENTS);
      writeRecents(storageKey, next);
      return next;
    });
  }, [storageKey]);

  return { recents, record };
}
