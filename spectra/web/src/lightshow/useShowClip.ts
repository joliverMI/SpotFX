/** The Light Show builders' clipboard (builderOps.ts), as reactive state —
 * a copy in one tab enables Paste in every other. */
import { useMemo, useSyncExternalStore } from 'react';
import { CLIP_KEY, readClip, subscribeClip, type ShowClip } from './builderOps';

export default function useShowClip(): ShowClip | null {
  const raw = useSyncExternalStore(subscribeClip,
    () => { try { return localStorage.getItem(CLIP_KEY); } catch { return null; } },
    () => null);
  return useMemo(() => (raw ? readClip() : null), [raw]);
}
