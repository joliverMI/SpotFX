/** The Live view — every in-use fixture in its real shape, lit by the preview
 * stream, drawn at the display's own rate.
 *
 * ONE component, mounted three ways: the Devices page's "Live" tab, the
 * pop-out window (/live) and, from the Rooms page, a link to the tab.
 *
 * Division of labour (each file's own header is the binding statement):
 *   positions.ts   WHERE each pixel is drawn — a position table: the tidy
 *                  Layout.
 *   roomMap.ts     the other table for the same renderer: each pixel where
 *                  one camera saw its light, a glow of that light under it,
 *                  and a tray of what nobody has placed.
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
 * lights" are shown as what they are, the strip's own three-way honesty.
 *
 * THE ROOM MAP WRITES ONE THING: where he put a piece by hand, per camera
 * pose (PUT /room-view/placements). His hand state here is the truth for
 * the pose he is looking at; the server's copy is read when a pose is first
 * shown and after a save fails. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  onDevicePreviewFrame, onDevicePreviewMessage, onDevicePreviewStatus,
  onDevicePreviewTabHiddenPause, setDevicePreviewInUse, setDevicePreviewLevel,
} from '../api/devicePreviewWs';
import { useToast } from '../components/Toast';
import HelpLink from '../help/HelpLink';
import useIsPhone from '../lib/useIsPhone';
import {
  pauseDevicePreview, putRoomViewPlacements, resumeDevicePreview, useDevicePreviewLayout,
  useRoomView, useRoomViewPoses,
} from '../queries';
import type { DevicePreviewStatus } from '../types';
import { LinkMeter } from './linkMeter';
import type { LinkReading } from './linkMeter';
import { layoutPositions, withHeldOverlay } from './positions';
import type { StageFixture, StagePlan } from './positions';
import { decodeRoomView, roomMapPositions, STAGE_H, STAGE_W } from './roomMap';
import type { RoomPlacement, RoomPlan, RoomView, TrayPiece } from './roomMap';
import { LiveStage } from './stage';

const SMOOTH_KEY = 'spectra-live-smooth';
const VIEW_KEY = 'spectra-live-view';
const POSE_KEY = 'spectra-live-pose';
const FIT_KEY = 'spectra-live-fit';
const CONSUMER = 'live-view';
const EMPTY_PLAN: StagePlan = {
  width: 16, height: 9, pointCount: 0, xy: new Float32Array(0), size: new Float32Array(0),
  src: new Uint32Array(0), groups: [], fixtures: [],
};
const TRAY_REASON: Record<string, string> = {
  unseen: 'not seen from this view', unmapped: 'not mapped',
};

function stored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function remember(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* private window */ }
}

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

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
  const queryClient = useQueryClient();
  const { data: layout, error, refetch } = useDevicePreviewLayout();
  // `?view=room` (the Rooms page's link) opens the map whatever was open last.
  const [view, setView] = useState<'layout' | 'room'>(() => {
    const asked = new URLSearchParams(window.location.search).get('view');
    return (asked ?? stored(VIEW_KEY)) === 'room' ? 'room' : 'layout';
  });
  const [poseChoice, setPoseChoice] = useState<string | null>(() => stored(POSE_KEY));
  const [fit, setFit] = useState(() => stored(FIT_KEY) !== '0');
  const [arrange, setArrange] = useState(false);
  const [hand, setHand] = useState<{ pose: string | null; map: Record<string, RoomPlacement> }>(
    { pose: null, map: {} });
  const [placing, setPlacing] = useState<{ keys: string[]; index: number } | null>(null);
  const [pinnedFrame, setPinnedFrame] = useState<RoomPlan['frame'] | null>(null);
  const [status, setStatus] = useState<DevicePreviewStatus | null>(null);
  const [tabHidden, setTabHidden] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [solo, setSolo] = useState<string | null>(null);
  const [smooth, setSmooth] = useState(readSmooth);
  const [fullscreen, setFullscreen] = useState(false);
  const [pausePending, setPausePending] = useState(false);
  const [mode, setMode] = useState<'webgl' | 'canvas' | null>(null);

  const rootRef = useRef<HTMLDivElement | null>(null);
  const stageBoxRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const meterRef = useRef<HTMLSpanElement | null>(null);
  const stageRef = useRef<LiveStage | null>(null);
  const liveRef = useRef(false);
  const meter = useMemo(() => new LinkMeter(), []);
  const refetchRef = useRef(refetch);
  refetchRef.current = refetch;

  const room = view === 'room';
  const posesQuery = useRoomViewPoses(room);
  const poses = posesQuery.data?.poses ?? [];
  const poseId = poses.find((p) => p.pose_id === poseChoice)?.pose_id ?? poses[0]?.pose_id ?? null;
  const roomQuery = useRoomView(room ? poseId : null);
  const roomView: RoomView | null = (room && roomQuery.data?.pose_id === poseId && roomQuery.data) || null;
  const decoded = useMemo(() => (roomView ? decodeRoomView(roomView) : null), [roomView]);
  const handMap = roomView && hand.pose === roomView.pose_id ? hand.map : roomView?.hand;

  const layoutPlan = useMemo(
    () => (layout && !room ? withHeldOverlay(layoutPositions(layout, !phone), layout) : null),
    [layout, phone, room]);
  const roomPlan = useMemo(
    () => (layout && roomView && decoded
      ? withHeldOverlay(
        roomMapPositions(layout, roomView, decoded, handMap ?? {}, { fit, frame: pinnedFrame ?? undefined }),
        layout)
      : null),
    [layout, roomView, decoded, handMap, fit, pinnedFrame]);
  const plan: StagePlan | null = room ? roomPlan : layoutPlan;

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
    stageRef.current?.setPlan(plan ?? EMPTY_PLAN);
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
  useEffect(() => {
    if (!source) return;
    refetch();
    // the map's pieces are cut from the same layout
    queryClient.invalidateQueries({ queryKey: ['spectra-room-view'] });
  }, [source, connected, refetch, queryClient]);

  const fixtures = plan?.fixtures ?? [];
  // On the map pieces overlap: a small one must sit above a large one to be
  // clickable.
  const hits = useMemo(
    () => (room ? [...fixtures].sort((a, b) => b.w * b.h - a.w * a.h) : fixtures), [fixtures, room]);
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

  const chooseView = (next: 'layout' | 'room') => {
    setView(next);
    remember(VIEW_KEY, next);
    setSelected(null);
    setSolo(null);
    setPlacing(null);
    setArrange(false);
  };

  /** Save hand placements for the pose on screen (null removes one). */
  const savePlacements = useCallback((patch: Record<string, RoomPlacement | null>) => {
    if (!roomView) return;
    const pose = roomView.pose_id;
    setHand((prev) => {
      const map = { ...(prev.pose === pose ? prev.map : roomView.hand) };
      Object.entries(patch).forEach(([key, value]) => {
        if (value) map[key] = value;
        else delete map[key];
      });
      return { pose, map };
    });
    putRoomViewPlacements(pose, patch)
      .then((saved) => {
        queryClient.setQueryData<RoomView>(['spectra-room-view', pose],
          (old) => (old ? { ...old, hand: saved.placements } : old));
      })
      .catch((err) => {
        toast(`Couldn't save that placement: ${(err as Error).message}`, 'error');
        setHand({ pose: null, map: {} });
        queryClient.invalidateQueries({ queryKey: ['spectra-room-view', pose] });
      });
  }, [queryClient, roomView, toast]);

  // Dragging a placed piece (Arrange): the piece follows the pointer in the
  // picture's own coordinates and is saved when it is let go.
  const dragRef = useRef<{
    key: string; x: number; y: number; origin: RoomPlacement; latest: RoomPlacement; moved: boolean;
  } | null>(null);
  const draggedRef = useRef(false);
  const startDrag = (e: React.PointerEvent<HTMLButtonElement>, f: StageFixture) => {
    if (!arrange || !f.placement || !roomPlan || placing) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = {
      key: f.key, x: e.clientX, y: e.clientY, origin: f.placement, latest: f.placement, moved: false,
    };
    draggedRef.current = false;
  };
  const moveDrag = (e: React.PointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    const box = stageBoxRef.current?.getBoundingClientRect();
    if (!drag || !box || !roomPlan || !roomView) return;
    if (!drag.moved) {
      if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 4) return;
      drag.moved = true;
      draggedRef.current = true;
      setPinnedFrame(roomPlan.frame);
      setSelected(drag.key);
    }
    drag.latest = {
      ...drag.origin,
      x: clamp01(drag.origin.x + ((e.clientX - drag.x) / box.width) * (roomPlan.frame.w / STAGE_W)),
      y: clamp01(drag.origin.y + ((e.clientY - drag.y) / box.height) * (roomPlan.frame.h / STAGE_H)),
    };
    const { key, latest } = drag;
    const pose = roomView.pose_id;
    setHand((prev) => ({ pose, map: { ...(prev.pose === pose ? prev.map : roomView.hand), [key]: latest } }));
  };
  const endDrag = () => {
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag?.moved) return;
    setPinnedFrame(null);
    savePlacements({ [drag.key]: drag.latest });
  };

  const tray: TrayPiece[] = roomPlan?.tray ?? [];
  const trayGroups = useMemo(() => {
    const groups = new Map<string, { id: string; name: string; source: string; pieces: TrayPiece[] }>();
    tray.forEach((piece) => {
      const id = `${piece.fixtureKey}|${piece.source}`;
      const group = groups.get(id) ?? { id, name: piece.fixtureName, source: piece.source, pieces: [] };
      group.pieces.push(piece);
      groups.set(id, group);
    });
    return [...groups.values()];
  }, [tray]);
  const placingPiece = placing ? tray.find((t) => t.key === placing.keys[placing.index]) ?? null : null;
  useEffect(() => {
    // the piece being placed left the tray some other way: stop asking
    if (placing && !placingPiece) setPlacing(null);
  }, [placing, placingPiece]);

  const placeAt = (e: React.MouseEvent<HTMLDivElement>) => {
    const box = stageBoxRef.current?.getBoundingClientRect();
    if (!placing || !placingPiece || !box || !roomPlan) return;
    const { frame } = roomPlan;
    savePlacements({
      [placingPiece.key]: {
        x: clamp01((frame.x + ((e.clientX - box.left) / box.width) * frame.w) / STAGE_W),
        y: clamp01((frame.y + ((e.clientY - box.top) / box.height) * frame.h) / STAGE_H),
        size: placingPiece.defaultSize, angle: 0,
      },
    });
    setSelected(placingPiece.key);
    setPlacing(placing.index + 1 < placing.keys.length
      ? { keys: placing.keys, index: placing.index + 1 } : null);
  };

  const adjust = (f: StageFixture, change: Partial<RoomPlacement>) => {
    if (f.placement) savePlacements({ [f.key]: { ...f.placement, ...change } });
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
  const roomNotice = !room ? null
    : posesQuery.error ? `Could not read the camera views: ${(posesQuery.error as Error).message}`
      : roomQuery.error ? `Could not read this view: ${(roomQuery.error as Error).message}`
        : posesQuery.data && poses.length === 0 ? 'none'
          : null;

  const pct = (value: number, of: number) => `${(value / of) * 100}%`;

  return (
    <div ref={rootRef}
         className={`live-view${fullscreen ? ' live-fullscreen' : ''}${popout ? ' live-popout' : ''}`}>
      <div className="live-toolbar">
        <div className="live-views" role="group" aria-label="View">
          <button type="button" className={room ? '' : 'active'} onClick={() => chooseView('layout')}
                  title="Every fixture in its own shape, tidily arranged.">
            Layout
          </button>
          <button type="button" className={room ? 'active' : ''} onClick={() => chooseView('room')}
                  title="Every fixture where a camera saw its light, over a glow of that light.">
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

      {room && poses.length > 0 && (
        <div className="live-room-bar">
          <label>
            Camera view{' '}
            <select value={poseId ?? ''} onChange={(e) => {
              setPoseChoice(e.target.value);
              remember(POSE_KEY, e.target.value);
              setSelected(null);
              setSolo(null);
              setPlacing(null);
            }}>
              {poses.map((p) => (
                <option key={p.pose_id} value={p.pose_id}>
                  {p.label} — {p.mapped} mapped{p.unseen ? `, ${p.unseen} unseen` : ''}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className={fit ? 'active' : ''} aria-pressed={fit}
                  onClick={() => { setFit(!fit); remember(FIT_KEY, fit ? '0' : '1'); }}
                  title="On: zoom to where the lights are. Off: the camera's whole picture.">
            Fit lights
          </button>
          <button type="button" className={arrange ? 'active' : ''} aria-pressed={arrange}
                  onClick={() => { setArrange(!arrange); setPlacing(null); }}
                  title="Move pieces by hand: drag one on the picture, or pick one from Not placed and click where it goes.">
            ✥ Arrange
          </button>
          <HelpLink topic="live-room-map" />
          {roomPlan && (
            <span className="live-room-counts">
              {roomPlan.counts.camera} placed by the camera · {roomPlan.counts.hand} by hand · {roomPlan.counts.tray} not placed
            </span>
          )}
        </div>
      )}

      {placingPiece && placing && (
        <div className="live-placing">
          <span>
            Click the picture where <strong>{placingPiece.label}</strong> is
            {placing.keys.length > 1 ? ` (${placing.index + 1} of ${placing.keys.length})` : ''}.
          </span>
          {placing.index + 1 < placing.keys.length && (
            <button type="button" onClick={() => setPlacing({ keys: placing.keys, index: placing.index + 1 })}>
              Skip
            </button>
          )}
          <button type="button" onClick={() => setPlacing(null)}>Done</button>
        </div>
      )}

      <div className={`live-stage-wrap${room ? ' live-room' : ''}`}>
        <div className="live-stage" ref={stageBoxRef}
             style={{ '--live-ar': plan ? plan.width / plan.height : room ? 16 / 9 : 2 } as React.CSSProperties}>
          <canvas ref={canvasRef} className="live-canvas" />
          {plan && hits.map((f) => (
            <button key={f.key} type="button"
                    className={`live-hit${selected === f.key ? ' selected' : ''}${solo && solo !== f.key ? ' dimmed' : ''}${room && arrange ? ' arrange' : ''}`}
                    style={{
                      left: pct(f.x, plan.width), top: pct(f.y, plan.height),
                      width: pct(f.w, plan.width), height: pct(f.h, plan.height),
                    }}
                    onPointerDown={room ? (e) => startDrag(e, f) : undefined}
                    onPointerMove={room ? moveDrag : undefined}
                    onPointerUp={room ? endDrag : undefined}
                    onPointerCancel={room ? endDrag : undefined}
                    onClick={() => {
                      if (draggedRef.current) { draggedRef.current = false; return; }
                      setSelected(selected === f.key ? null : f.key);
                    }}
                    aria-label={`${f.name}, ${f.detail}`}>
              <span className="live-label">
                <span className="live-label-name">{f.name}</span>
                <span className="live-label-detail">{f.detail}</span>
              </span>
            </button>
          ))}
          {placingPiece && <div className="live-place-catcher" onClick={placeAt} />}
          {roomNotice ? (
            <div className="live-notice">
              {roomNotice === 'none' ? (
                <>
                  <span>No camera view has mapped anything yet. Map a room on the Rooms page and it appears here.</span>
                  <button type="button" onClick={() => (popout ? window.open('/spectra/rooms', '_blank') : navigate('/rooms'))}>
                    Open Rooms
                  </button>
                </>
              ) : <span>{roomNotice}</span>}
            </div>
          ) : notice && (
            <div className="live-notice">
              <span>{notice}</span>
              {paused && (
                <button type="button" onClick={togglePause} disabled={pausePending}>▶ Resume</button>
              )}
            </div>
          )}
        </div>
      </div>

      {room && roomView && (
        <div className="live-room-caption">
          The picture behind the lights is what this camera measured — every mapped light added up — not a photograph.
          A marker sits at the centre of its light as the camera saw it, which is not always where the fixture hangs.
          {roomView.notes.map((note) => <span key={note}> {note}</span>)}
        </div>
      )}

      {error && <div className="empty-note">Could not read the layout: {(error as Error).message}</div>}
      {layout && !room && fixtures.length === 0 && (
        <div className="empty-note">No in-use fixture to draw yet.</div>
      )}

      {selectedFixture && (
        <div className="live-selected">
          <span>
            <strong>{selectedFixture.name}</strong>
            <span className="live-selected-detail"> · {selectedFixture.detail} · fed by {selectedFixture.visId}</span>
          </span>
          {selectedFixture.note && <span className="live-selected-detail">{selectedFixture.note}</span>}
          {room && arrange && selectedFixture.placement && (
            <>
              <button type="button" title="Smaller"
                      onClick={() => adjust(selectedFixture, { size: Math.max(0.01, selectedFixture.placement!.size / 1.15) })}>
                −
              </button>
              <button type="button" title="Larger"
                      onClick={() => adjust(selectedFixture, { size: Math.min(1, selectedFixture.placement!.size * 1.15) })}>
                +
              </button>
              {selectedFixture.count > 1 && (
                <>
                  <button type="button" title="Turn left"
                          onClick={() => adjust(selectedFixture, { angle: ((selectedFixture.placement!.angle - 15 + 540) % 360) - 180 })}>
                    ⟲
                  </button>
                  <button type="button" title="Turn right"
                          onClick={() => adjust(selectedFixture, { angle: ((selectedFixture.placement!.angle + 15 + 540) % 360) - 180 })}>
                    ⟳
                  </button>
                </>
              )}
              {selectedFixture.placedBy === 'hand' && (
                <button type="button" title="Forget where you put it: back to where the camera placed it, or to Not placed"
                        onClick={() => savePlacements({ [selectedFixture.key]: null })}>
                  Undo my placement
                </button>
              )}
            </>
          )}
          <button type="button" onClick={() => openSettings(selectedFixture)}>Open settings</button>
          <button type="button" className={solo === selectedFixture.key ? 'active' : ''}
                  onClick={() => setSolo(solo === selectedFixture.key ? null : selectedFixture.key)}>
            {solo === selectedFixture.key ? 'Show all' : 'Solo'}
          </button>
        </div>
      )}

      {room && roomPlan && (
        <div className="live-tray">
          <span className="live-tray-title">
            Not placed ({tray.length}) <HelpLink topic="live-room-map-tray" />
          </span>
          {tray.length === 0 && <span className="live-list-detail">Every piece is on the picture.</span>}
          {trayGroups.map((group) => (
            <button key={group.id} type="button"
                    className={placing && group.pieces.some((p) => p.key === placing.keys[placing.index]) ? 'active' : ''}
                    title={`${group.pieces[0].note || 'Click, then click the picture where it is.'}`}
                    onClick={() => {
                      setArrange(true);
                      setPlacing({ keys: group.pieces.map((p) => p.key), index: 0 });
                    }}>
              {group.pieces.length === 1 ? group.pieces[0].label : `${group.name} × ${group.pieces.length}`}
              <span className="live-list-detail"> {TRAY_REASON[group.source] ?? group.source}</span>
            </button>
          ))}
          {solo && <button type="button" onClick={() => setSolo(null)}>Show all</button>}
        </div>
      )}

      <div className="live-list" hidden={room}>
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
