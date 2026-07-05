/** Playhead: WS `state` messages carry track progress; between messages we
 * extrapolate with wall-clock (classic builder's 25ms tick equivalent).
 * Canvas reads getNowMs() per frame; React text uses the 4Hz coarse value. */
import { useEffect, useRef, useState } from 'react';
import { onMessage } from '../../api/ws';
import { useBuilderStore } from '../store';

interface Base {
  progressMs: number;
  isPlaying: boolean;
  receivedAt: number;
  uri: string;
}

export function usePlayhead() {
  const base = useRef<Base | null>(null);
  const [coarseMs, setCoarseMs] = useState<number | null>(null);
  const setTrack = useBuilderStore((s) => s.setTrack);

  useEffect(() => {
    const off = onMessage('state', (msg) => {
      const t = msg.track as Record<string, unknown> | null;
      if (!t || !t.spotify_uri) {
        base.current = null;
        setTrack(null);
        return;
      }
      base.current = {
        progressMs: Number(t.progress_ms ?? 0),
        isPlaying: Boolean(t.is_playing),
        receivedAt: performance.now(),
        uri: String(t.spotify_uri),
      };
      setTrack({
        uri: String(t.spotify_uri),
        title: String(t.title ?? ''),
        artist: String(t.artist ?? ''),
        duration_ms: Number(t.duration_ms ?? 0),
        is_playing: Boolean(t.is_playing),
      });
    });
    const tick = setInterval(() => {
      setCoarseMs(getNow());
    }, 250);
    return () => {
      off();
      clearInterval(tick);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function getNow(): number | null {
    const b = base.current;
    if (!b) return null;
    if (!b.isPlaying) return b.progressMs;
    return b.progressMs + (performance.now() - b.receivedAt);
  }

  const getNowRef = useRef(getNow);
  getNowRef.current = getNow;

  return { getNowMs: () => getNowRef.current(), coarseMs };
}
