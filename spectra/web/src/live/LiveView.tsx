/** The Live view — every in-use fixture in its real shape, lit by the preview
 * stream, drawn at the display's own rate.
 *
 * ONE component, mounted three ways: the Devices page's "Live" tab, the
 * pop-out window (/live) and, from the Rooms page, a link to the tab.
 *
 * Division of labour (each file's own header is the binding statement):
 *   positions.ts   WHERE each pixel is drawn — a position table. Today it is
 *                  a tidy layout; the room map will be another table for the
 *                  same renderer.
 *   stage.ts       the renderer and the smoothing between frames.
 *   linkMeter.ts   fps / delay / kbit/s from the stream's own headers.
 *   this file      the page around them: the toolbar, the click targets,
 *                  pause, solo, full screen.
 *
 * NOTHING PER FRAME GOES THROUGH REACT. Frames go from the socket straight
 * into the stage; the meter writes its own text node. React state here is
 * only what changes when he presses something.
 *
 * PAUSE IS THE PREVIEW'S OWN PAUSE, not a second one: the button calls the
 * same server pause the top strip's button does (services/device_preview.py),
 * so the two can never disagree, and a paused preview stays paused here —
 * the stage goes dark and says why. Tab hidden and "nobody is driving the
 * lights" are shown as what they are, the strip's own three-way honesty. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  onDevicePreviewFrame, onDevicePreviewMessage, onDevicePreviewStatus,
  onDevicePreviewTabHiddenPause, setDevicePreviewInUse, setDevicePreviewLevel,
} from '../api/devicePreviewWs';
import { useToast } from '../components/Toast';
import HelpLink from '../help/HelpLink';
import useIsPhone from '../lib/useIsPhone';
import { pauseDevicePreview, resumeDevicePreview, useDevicePreviewLayout } from '../queries';
import type { DevicePreviewStatus } from '../types';
import { LinkMeter } from './linkMeter';
import type { LinkReading } from './linkMeter';
import { layoutPositions } from './positions';
import type { StageFixture } from './positions';
import { LiveStage } from './stage';

const SMOOTH_KEY = 'spectra-live-smooth';
const CONSUMER = 'live-view';

function readSmooth(): boolean {
  try {
    return localStorage.getItem(SMOOTH_KEY) !== '0';
  } catch {
    return true;
  }
}

export default function LiveView({ popout = false, forceCanvas = false }: {
  popout?: boolean;
  /** Draw with the 2D canvas even where WebGL2 exists (the perf test). */
  forceCanvas?: boolean;
}) {
  const phone = useIsPhone();
  const navigate = useNavigate();
  const toast = useToast();
  const { data: layout, error, refetch } = useDevicePreviewLayout();
  const [status, setStatus] = useState<DevicePreviewStatus | null>(null);
  const [tabHidden, setTabHidden] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [solo, setSolo] = useState<string | null>(null);
  const [smooth, setSmooth] = useState(readSmooth);
  const [fullscreen, setFullscreen] = useState(false);
  const [pausePending, setPausePending] = useState(false);
  const [mode, setMode] = useState<'webgl' | 'canvas' | null>(null);

  const rootRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const meterRef = useRef<HTMLSpanElement | null>(null);
  const stageRef = useRef<LiveStage | null>(null);
  const liveRef = useRef(false);
  const meter = useMemo(() => new LinkMeter(), []);
  const refetchRef = useRef(refetch);
  refetchRef.current = refetch;

  const plan = useMemo(
    () => (layout ? layoutPositions(layout, !phone) : null), [layout, phone]);

  useEffect(() => onDevicePreviewStatus(setStatus), []);
  useEffect(() => onDevicePreviewTabHiddenPause(setTabHidden), []);

  // Full frames of every in-use device, only while this view is mounted.
  useEffect(() => {
    setDevicePreviewLevel(CONSUMER, 'full');
    setDevicePreviewInUse(CONSUMER, true);
    return () => {
      setDevicePreviewLevel(CONSUMER, null);
      setDevicePreviewInUse(CONSUMER, false);
    };
  }, []);

  // The stage and its draw loop live as long as the canvas does.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const stage = new LiveStage(canvas, forceCanvas);
    stageRef.current = stage;
    setMode(stage.mode);
    stage.setSmooth(readSmooth());
    stage.resize();
    const observer = new ResizeObserver(() => stage.resize());
    observer.observe(canvas);
    let raf = 0;
    const tick = (now: number) => {
      stage.draw(now);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    const stopFrames = onDevicePreviewFrame((frame) => {
      if (liveRef.current) stage.pushFrame(frame, performance.now());
    });
    const stopMessages = onDevicePreviewMessage((bytes, stats, age, at) => {
      meter.note(bytes, stats, age, at);
    });
    const reading: LinkReading = { fps: 0, delayMs: null, kbps: 0, rateFps: 0 };
    let refetchedAt = 0;
    const meterTimer = window.setInterval(() => {
      // Frames that no longer fit the layout: read the layout again (at most
      // every few seconds — the old stream format never fits a masked device).
      if (stage.stale && performance.now() - refetchedAt > 5000) {
        stage.stale = false;
        refetchedAt = performance.now();
        refetchRef.current();
      }
      const el = meterRef.current;
      if (!el) return;
      if (!liveRef.current) { el.textContent = '—'; return; }
      meter.read(performance.now(), stage.holdMs(), reading);
      const delay = reading.delayMs === null ? '— ms' : `${Math.round(reading.delayMs)} ms`;
      el.textContent = `${reading.fps.toFixed(0)} fps · ${delay} · ${reading.kbps.toFixed(0)} kbit/s`;
    }, 500);
    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
      stopFrames();
      stopMessages();
      window.clearInterval(meterTimer);
      stage.dispose();
      stageRef.current = null;
    };
  }, [forceCanvas, meter]);

  useEffect(() => {
    if (plan) stageRef.current?.setPlan(plan);
  }, [plan, mode]);

  const paused = status?.paused ?? false;
  const connected = status?.connected ?? false;
  const live = !paused && !tabHidden && connected;
  useEffect(() => {
    liveRef.current = live;
    if (!live) {
      stageRef.current?.blank();
      meter.reset();
    }
  }, [live, meter]);

  // What is in use can change with who is driving the lights.
  const source = status?.source;
  useEffect(() => { if (source) refetch(); }, [source, connected, refetch]);

  const fixtures = plan?.fixtures ?? [];
  const selectedFixture = fixtures.find((f) => f.key === selected) ?? null;
  const soloFixture = fixtures.find((f) => f.key === solo) ?? null;
  useEffect(() => {
    stageRef.current?.setSolo(soloFixture
      ? { first: soloFixture.first, count: soloFixture.count } : null);
  }, [soloFixture, plan, mode]);

  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement === rootRef.current);
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);

  const togglePause = useCallback(async () => {
    setPausePending(true);
    try {
      await (paused ? resumeDevicePreview() : pauseDevicePreview());
    } catch (err) {
      toast(`Couldn't ${paused ? 'resume' : 'pause'}: ${(err as Error).message}`, 'error');
    } finally {
      setPausePending(false);
    }
  }, [paused, toast]);

  const toggleSmooth = () => setSmooth((prev) => {
    const next = !prev;
    try { localStorage.setItem(SMOOTH_KEY, next ? '1' : '0'); } catch { /* private window */ }
    stageRef.current?.setSmooth(next);
    return next;
  });

  const toggleFullscreen = () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else rootRef.current?.requestFullscreen?.().catch(() => toast('Full screen was refused by the browser', 'error'));
  };

  const popOut = () => {
    window.open('/spectra/live', 'spectra-live', 'popup,width=1180,height=780');
  };

  const openSettings = (fixture: StageFixture) => {
    const to = `/devices?device=${encodeURIComponent(fixture.deviceId)}`;
    if (popout) window.open(`/spectra${to}`, '_blank');
    else navigate(to);
  };

  const notice = paused
    ? 'The preview is paused.'
    : tabHidden
      ? 'Idle while this tab is hidden.'
      : !connected
        ? (source === 'none'
          ? 'Nothing is driving the lights right now, so there is no picture to show. The shapes are from the stored configuration.'
          : 'Connecting to the lights…')
        : null;

  const pct = (value: number, of: number) => `${(value / of) * 100}%`;

  return (
    <div ref={rootRef}
         className={`live-view${fullscreen ? ' live-fullscreen' : ''}${popout ? ' live-popout' : ''}`}>
      <div className="live-toolbar">
        <div className="live-views" role="group" aria-label="View">
          <button type="button" className="active">Layout</button>
          <button type="button" disabled
                  title="Each LED where the camera saw it. Appears as devices get mapped — not built yet.">
            Room map
          </button>
        </div>
        <span className="live-meter" title="What this browser is getting: frames a second · how old the picture is when drawn · data rate">
          <span ref={meterRef}>—</span> <HelpLink topic="live-link-meter" />
        </span>
        <span className="live-actions">
          <button type="button" onClick={togglePause} disabled={pausePending}
                  title={paused ? 'Resume the preview (the top strip too)' : 'Pause the preview everywhere, to save resources'}>
            {paused ? '▶ Resume' : '⏸ Pause'}
          </button>
          <button type="button" onClick={toggleSmooth} className={smooth ? 'active' : ''}
                  aria-pressed={smooth}
                  title="Blend between frames so motion is even. Costs about one frame (33ms) of delay on a good link, more on a rough one.">
            Smooth
          </button>
          <HelpLink topic="live-smooth" />
          <button type="button" onClick={toggleFullscreen}>
            {fullscreen ? 'Exit full screen' : '⛶ Full screen'}
          </button>
          {!popout && <button type="button" onClick={popOut} title="Open in its own window">↗ Pop out</button>}
          <HelpLink topic="devices-live" />
        </span>
      </div>

      <div className="live-stage-wrap">
        <div className="live-stage"
             style={{ '--live-ar': plan ? plan.width / plan.height : 2 } as React.CSSProperties}>
          <canvas ref={canvasRef} className="live-canvas" />
          {plan && fixtures.map((f) => (
            <button key={f.key} type="button"
                    className={`live-hit${selected === f.key ? ' selected' : ''}${solo && solo !== f.key ? ' dimmed' : ''}`}
                    style={{
                      left: pct(f.x, plan.width), top: pct(f.y, plan.height),
                      width: pct(f.w, plan.width), height: pct(f.h, plan.height),
                    }}
                    onClick={() => setSelected(selected === f.key ? null : f.key)}
                    aria-label={`${f.name}, ${f.detail}`}>
              <span className="live-label">
                <span className="live-label-name">{f.name}</span>
                <span className="live-label-detail">{f.detail}</span>
              </span>
            </button>
          ))}
          {notice && (
            <div className="live-notice">
              <span>{notice}</span>
              {paused && (
                <button type="button" onClick={togglePause} disabled={pausePending}>▶ Resume</button>
              )}
            </div>
          )}
        </div>
      </div>

      {error && <div className="empty-note">Could not read the layout: {(error as Error).message}</div>}
      {layout && fixtures.length === 0 && (
        <div className="empty-note">No in-use fixture to draw yet.</div>
      )}

      {selectedFixture && (
        <div className="live-selected">
          <span>
            <strong>{selectedFixture.name}</strong>
            <span className="live-selected-detail"> · {selectedFixture.detail} · fed by {selectedFixture.visId}</span>
          </span>
          <button type="button" onClick={() => openSettings(selectedFixture)}>Open settings</button>
          <button type="button" className={solo === selectedFixture.key ? 'active' : ''}
                  onClick={() => setSolo(solo === selectedFixture.key ? null : selectedFixture.key)}>
            {solo === selectedFixture.key ? 'Show all' : 'Solo'}
          </button>
        </div>
      )}

      <div className="live-list">
        {fixtures.map((f) => (
          <button key={f.key} type="button"
                  className={selected === f.key ? 'active' : ''}
                  onClick={() => setSelected(selected === f.key ? null : f.key)}>
            {f.name} <span className="live-list-detail">{f.detail}</span>
          </button>
        ))}
        {solo && <button type="button" onClick={() => setSolo(null)}>Show all</button>}
        {mode === 'canvas' && (
          <span className="live-list-detail" title="This browser has no WebGL2, so the stage is drawn with a plain canvas.">
            plain canvas
          </span>
        )}
      </div>
    </div>
  );
}
