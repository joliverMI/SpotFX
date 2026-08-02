/** Shared status/control bar shown under the nav on every page:
 * engine play/pause ("Activate"), Dinner Party + Ambient icon toggles, the
 * active Scene / Color Set, sync-lock status, now-playing track + position,
 * and a color-coded intensity score for the last fired trigger. */
import { useEffect, useRef, useState } from 'react';
import { apiPost } from '../api/client';
import { onMessage } from '../api/ws';
import { fmtMs } from '../lib/time';
import { ensureLiveState, useLiveStore, useLiveTick } from '../live/liveStore';
import AmbientButton from '../nowplaying/AmbientButton';

const LOCK_STALE_MS = 12_000;
const LOCK_LABEL: Record<string, string> = { ok: 'Locked', suspect: 'Suspect', recovering: 'Recovering' };
const LOCK_COLOR: Record<string, string> = { ok: '#00ff88', suspect: '#ffb300', recovering: '#ff5252' };

/** Cool blue (0) → hot red (1). */
const intensityHue = (v: number) => Math.round(215 - 215 * Math.min(1, Math.max(0, v)));

// ── Dark/Light display mode (global level — top of the cascade) ─────────────
const MODE_CYCLE = ['default', 'dark', 'light'] as const;
type TopMode = (typeof MODE_CYCLE)[number];
const MODE_ICON: Record<TopMode, string> = { default: '🌗', dark: '🌙', light: '☀️' };
const MODE_TITLE: Record<TopMode, string> = {
  default: 'Display mode: Default — defer to trigger / scene group / scene / color levels',
  dark: 'Display mode: Dark — force backgrounds black (shielded devices keep theirs)',
  light: 'Display mode: Light — keep backgrounds on; fill in the default light background',
};

/** Cycles Default → Dark → Light. The icon flips immediately but the mode is
 * committed 1 s after the last click, so cycling past a mode never applies it. */
function DisplayModeButton() {
  const stored = useLiveStore((s) => s.displayMode);
  const [pending, setPending] = useState<TopMode | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const mode: TopMode = pending ?? (MODE_CYCLE.includes(stored as TopMode) ? (stored as TopMode) : 'default');
  const click = () => {
    const next = MODE_CYCLE[(MODE_CYCLE.indexOf(mode) + 1) % MODE_CYCLE.length];
    setPending(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      timer.current = null;
      // The endpoint broadcasts the new state before responding, so the store
      // is already correct when pending clears — no flicker back.
      void apiPost(`/control/display-mode?mode=${next}`).finally(() => setPending(null));
    }, 1000);
  };

  return (
    <button className={`icon-btn ${mode !== 'default' ? 'active' : ''}`} title={MODE_TITLE[mode]} onClick={click}>
      {MODE_ICON[mode]}
    </button>
  );
}

interface LastFire {
  intensity: number;
  name: string;
}

export default function TopBar() {
  ensureLiveState();
  const track = useLiveStore((s) => s.track);
  const paused = useLiveStore((s) => s.paused);
  const dinnerParty = useLiveStore((s) => s.dinnerParty);
  const lastScene = useLiveStore((s) => s.lastScene);
  const activeSceneGroup = useLiveStore((s) => s.activeSceneGroup);
  const lastColorSet = useLiveStore((s) => s.lastColorSet);
  const timing = useLiveStore((s) => s.timing);
  const progressMs = useLiveTick(500);

  const uri = track?.spotify_uri ?? null;
  const uriRef = useRef(uri);
  uriRef.current = uri;

  const [monitor, setMonitor] = useState<{ state: string; at: number } | null>(null);
  const [lastFire, setLastFire] = useState<LastFire | null>(null);
  const [, tick] = useState(0);

  useEffect(() => {
    const offs = [
      onMessage('xcorr_monitor', (msg) => {
        if (msg.uri && msg.uri !== uriRef.current) return;
        setMonitor({ state: String(msg.state ?? 'ok'), at: Date.now() });
      }),
      onMessage('trigger_fired', (msg) => {
        if (msg.intensity == null) return;
        setLastFire({ intensity: Number(msg.intensity), name: String(msg.event_name ?? '') });
      }),
    ];
    // Slow re-render so lock staleness flips without new messages.
    const t = setInterval(() => tick((n) => n + 1), 2000);
    return () => {
      offs.forEach((off) => off());
      clearInterval(t);
    };
  }, []);

  // Reset per-song indicators on track change.
  useEffect(() => {
    setMonitor(null);
    setLastFire(null);
  }, [uri]);

  const fresh = monitor && Date.now() - monitor.at < LOCK_STALE_MS;
  const lockLabel = fresh
    ? LOCK_LABEL[monitor.state] ?? monitor.state
    : timing.shape_offset_ms != null ? 'Lock idle' : 'No lock';
  const lockColor = fresh ? LOCK_COLOR[monitor.state] ?? '#888' : '#888';

  return (
    <div className="top-bar">
      <button
        className={`playpause ${!paused ? 'on' : ''}`}
        title={paused ? 'Activate trigger firing' : 'Pause trigger firing'}
        onClick={() => void apiPost(paused ? '/control/resume' : '/control/pause')}
      >
        {paused ? '▶' : '⏸'}
      </button>
      <button
        className={`icon-btn ${dinnerParty ? 'active' : ''}`}
        title="Dinner Party — ignore song triggers, use automatic ambient lighting"
        onClick={() => void apiPost(`/control/dinner-party?enabled=${!dinnerParty}`)}
      >
        🍽️
      </button>
      <AmbientButton compact />
      <DisplayModeButton />

      {lastScene && (
        <span className="tb-chip" title={`Active scene${activeSceneGroup ? ` (group: ${activeSceneGroup.name})` : ''}`}>
          <span className="tb-dot" style={{ background: lastScene.color }} />
          <span className="tb-chip-text">{lastScene.name}</span>
        </span>
      )}
      {lastColorSet && (
        <span className="tb-chip" title="Active color set">
          <span className="tb-dot" style={{ background: lastColorSet.color }} />
          <span className="tb-chip-text">{lastColorSet.name}</span>
        </span>
      )}

      <span className="tb-lock" style={{ color: lockColor }}
        title="Audio sync lock — the live-capture matcher's confidence in the current offset">
        ● {lockLabel}
      </span>

      <span className="tb-track" title={track ? `${track.title} — ${track.artist}` : ''}>
        {track ? `${track.title} — ${track.artist}` : 'Nothing playing'}
      </span>
      <span className="tb-time">
        {track && progressMs != null ? `${fmtMs(progressMs)} / ${fmtMs(track.duration_ms)}` : ''}
      </span>

      {lastFire && (
        <span
          className="tb-intensity"
          style={{
            color: `hsl(${intensityHue(lastFire.intensity)}, 85%, 60%)`,
            borderColor: `hsla(${intensityHue(lastFire.intensity)}, 85%, 55%, 0.45)`,
            background: `hsla(${intensityHue(lastFire.intensity)}, 85%, 55%, 0.12)`,
          }}
          title={`Intensity of the last fired trigger${lastFire.name ? ` (${lastFire.name})` : ''}`}
        >
          ⚡{Math.round(lastFire.intensity * 100)}
        </span>
      )}
    </div>
  );
}
