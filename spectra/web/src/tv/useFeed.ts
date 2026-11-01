/** A thin React binding over the singleton `feed` (feed.ts) — subscribes
 * on mount, starts the connection once, and re-renders on every state
 * change. One hook, shared by every plane that needs the feed; no plane
 * owns its own connection. */
import { useEffect, useState } from 'react';
import { feed, FeedState } from './feed';

const INITIAL: FeedState = {
  connected: false, layout: null, clock: null, jukebox: null,
  jukeboxReceivedAtMs: null, offsetMs: null, disconnectedAtMs: null,
};

export function useFeed(): FeedState {
  const [state, setState] = useState<FeedState>(INITIAL);
  useEffect(() => {
    feed.start();
    return feed.subscribe(setState);
  }, []);
  return state;
}
