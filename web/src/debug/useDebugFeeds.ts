/** Debug-page live feeds: WS collections (xcorr windows, spikes, monitor
 * rolling-R, anchor match, last fire) + the 1.5s live-frames poll. Everything
 * resets on track change. */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiGet } from '../api/client';
import { onMessage } from '../api/ws';
import type { LiveShapeLayerData, MonitorPoint, SpikeMarker, XcorrWinMarker } from '../builder/canvas/frame';
import type { AudioShapeData } from '../builder/types';
import { binTo25ms, computeDiff, shiftLive } from './diff';

export interface MonitorStatus {
  state: 'ok' | 'suspect' | 'recovering' | string;
  rollingR: number | null;
  recoveries: number;
  atWallMs: number; // Date.now() of last message — staleness detection
}

export interface AnchorMatch {
  offset_ms: number;
  r: number;
  q: number;
  candidate_idx: number;
  band: string;
  source?: string;
}

export interface LastFire {
  event_name?: string;
  trigger_id?: string;
  scheduled_ms?: number;
  fired_at_ms?: number;
  effective_offset_ms?: number;
}

export function useDebugFeeds(uri: string | null, shapeOffsetMs: number, savedShape: AudioShapeData | null) {
  const [xcorrWindows, setXcorrWindows] = useState<XcorrWinMarker[]>([]);
  const [xcorrLines, setXcorrLines] = useState<string[]>([]);
  const [spikes, setSpikes] = useState<SpikeMarker[]>([]);
  const [spikeLines, setSpikeLines] = useState<string[]>([]);
  const [monitorHistory, setMonitorHistory] = useState<MonitorPoint[]>([]);
  const [monitor, setMonitor] = useState<MonitorStatus | null>(null);
  const [anchorMatch, setAnchorMatch] = useState<AnchorMatch | null>(null);
  const [lastFire, setLastFire] = useState<LastFire | null>(null);
  const uriRef = useRef(uri);
  uriRef.current = uri;
  const offsetRef = useRef(shapeOffsetMs);
  offsetRef.current = shapeOffsetMs;

  // Reset all per-play state when the song changes.
  useEffect(() => {
    setXcorrWindows([]);
    setXcorrLines([]);
    setSpikes([]);
    setSpikeLines([]);
    setMonitorHistory([]);
    setMonitor(null);
    setAnchorMatch(null);
  }, [uri]);

  useEffect(() => {
    const mine = (msg: Record<string, unknown>) => !msg.uri || msg.uri === uriRef.current;
    const offs = [
      onMessage('xcorr_window', (msg) => {
        if (!mine(msg)) return;
        setXcorrWindows((ws) => [...ws.slice(-29), {
          win_start: Number(msg.win_start), win_end: Number(msg.win_end),
          winner: msg.winner as string | undefined, failed: Boolean(msg.failed),
          new_offset_ms: (msg.new_offset_ms as number | null) ?? null,
          new_r: (msg.new_r as number | null) ?? null,
        }]);
        const winner = (msg.winner as string) || (msg.failed ? 'fail' : '?');
        const r = Number((msg.winner === 'new' ? msg.new_r : msg.old_r) ?? 0);
        const off = Number((msg.winner === 'new' ? msg.new_offset_ms : msg.old_offset_ms) ?? 0);
        const q = Number(msg.new_quality ?? msg.old_quality ?? 0);
        setXcorrLines((ls) => [
          `[${msg.win_start}-${msg.win_end}] ${winner.padEnd(4)} ` +
          `${off >= 0 ? '+' : ''}${off}ms r=${r.toFixed(2)} Q=${q.toFixed(2)} ` +
          `diff=${Number(msg.difficulty ?? 0).toFixed(2)}` +
          (msg.applied ? ' ★' : '') + (msg.failed ? '  REJECT' : ''),
          ...ls.slice(0, 29),
        ]);
      }),
      onMessage('xcorr_spike', (msg) => {
        if (!mine(msg)) return;
        setSpikes((sp) => [...sp.slice(-3), {
          spike_ms: Number(msg.spike_ms), win_start: Number(msg.win_start),
          win_end: Number(msg.win_end), strength: Number(msg.strength ?? 0),
        }]);
        setSpikeLines((ls) => [
          `spike @${msg.spike_ms}ms → window [${msg.win_start}-${msg.win_end}] ` +
          `strength=${Number(msg.strength ?? 0).toFixed(2)}`,
          ...ls.slice(0, 9),
        ]);
      }),
      onMessage('xcorr_monitor', (msg) => {
        if (!mine(msg)) return;
        const r = msg.rolling_r != null ? Number(msg.rolling_r) : null;
        setMonitor({
          state: String(msg.state ?? 'ok') as MonitorStatus['state'],
          rollingR: r,
          recoveries: Number(msg.recoveries ?? 0),
          atWallMs: Date.now(),
        });
        // t_ms is live-capture time; the monitor's rolling span ends at
        // t_ms + engine offset in saved-shape time — shift so the trace
        // aligns with the (already-shifted) live overlay and diff.
        setMonitorHistory((h) => [...h.slice(-599), { ms: Number(msg.t_ms ?? 0) + offsetRef.current, r }]);
      }),
      onMessage('shape_match_updated', (msg) => {
        if (!mine(msg)) return;
        setAnchorMatch({
          offset_ms: Number(msg.offset_ms ?? 0), r: Number(msg.r ?? 0), q: Number(msg.q ?? 0),
          candidate_idx: Number(msg.candidate_idx ?? -1), band: String(msg.band ?? ''),
          source: msg.source as string | undefined,
        });
      }),
      onMessage('trigger_fired', (msg) => setLastFire(msg as LastFire)),
    ];
    return () => offs.forEach((off) => off());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Live xcorr-frame polling (1.5s) ────────────────────────────────────────
  const { data: rawFrames } = useQuery({
    queryKey: ['xcorr-frames', uri],
    queryFn: () => apiGet<LiveShapeLayerData>(`/debug/xcorr-frames?uri=${encodeURIComponent(uri!)}`),
    enabled: !!uri,
    refetchInterval: 1500,
    retry: false,
    gcTime: 0,
  });

  const live = useMemo(() => {
    if (!rawFrames?.timestamps_ms?.length) return null;
    return shiftLive(binTo25ms(rawFrames), shapeOffsetMs);
  }, [rawFrames, shapeOffsetMs]);

  const diff = useMemo(
    () => (savedShape && live ? computeDiff(savedShape, live) : null),
    [savedShape, live],
  );

  // Live capture edge (lags the song) — the follow anchor while xcorr runs.
  const liveEdge = useRef<{ ms: number; wallMs: number } | null>(null);
  useEffect(() => {
    if (!live?.timestamps_ms?.length) {
      liveEdge.current = null;
      return;
    }
    const edge = live.timestamps_ms[live.timestamps_ms.length - 1];
    if (liveEdge.current?.ms !== edge) liveEdge.current = { ms: edge, wallMs: Date.now() };
  }, [live]);

  return {
    xcorrWindows, xcorrLines, spikes, spikeLines,
    monitorHistory, monitor, anchorMatch, lastFire,
    live, diff, liveEdge,
  };
}
