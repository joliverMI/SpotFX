/** Live device-preview strip (data/spectra-device-preview-plan/report.md)
 * — the second occupant of the shared TopBarStrip (see TopBarStrip.tsx),
 * mounted once so it's visible on every SPECTRA route while he tweaks
 * scenes/settings/colour sets, and so the WS connection
 * (api/devicePreviewWs.ts, module-level singleton) survives route changes
 * rather than tearing down and resubscribing on every navigation.
 *
 * Approved by the owner with one explicit condition: "add a pause button
 * to pause the preview and conserve resources." Pause/resume call the
 * server (spectra/services/device_preview.py), which genuinely drops or
 * reopens the live upstream connection — this component never fakes that
 * by hiding swatches while a hidden feed keeps running; `connected` here
 * is the server's own honest state, not a local guess, and swatches only
 * ever render live colour while unpaused, not auto-paused, AND connected.
 *
 * SOURCE IS OWNERSHIP-ROUTED, not always LedFX (2026-08-16 correction):
 * `status.source` names which world is actually driving the lights right
 * now — "facade" (SPECTRA's own in-process render pipeline, his normal S3
 * operating state), "ledfx" (the external LedFX process), or "none"
 * (nobody currently owns the lights). The swatches themselves don't
 * branch on it — DevicePreviewFrame's wire shape is identical either way
 * (types.ts) — but the "reconnecting…" badge's tooltip does, so it never
 * claims to be reconnecting to LedFX when LedFX was never the source.
 *
 * HIDDEN-TAB AUTO-PAUSE (OQ-7, decided 2026-08-15): a browser tab going
 * hidden auto-pauses the feed too (api/devicePreviewWs.ts closes its own
 * socket, which genuinely drops the live upstream connection server-side
 * — see that module's docstring), and returning to the tab auto-resumes
 * it with no click needed. This is a SEPARATE, ephemeral mechanism from
 * his own sticky Pause button — never persisted, never the same badge —
 * so he can always tell at a glance which one is in effect: "paused"
 * (gray) means he clicked Pause and it stays that way until he clicks
 * Resume; "idle — tab hidden" (blue) means only that this tab isn't
 * looking right now and it will pick back up on its own.
 *
 * Default view is a compact single swatch per favourite device (LedFX's
 * own per-pixel average — see api/devicePreviewWs.ts's averageRgb);
 * "Expand" reveals the full per-pixel layout, remembered client-side
 * (report §5), same local-first pattern as the feedback queue.
 *
 * PHONE-FIRST LAYOUT (fixed 2026-08-16, his own report: "the preview
 * stretches out in a line super far ... I don't see any Matrix for The
 * Matrix previews"). Every frame already carries `shape: [rows, cols]`
 * (services/device_preview.py reads it off the real virtual and has since
 * launch — this was never a payload gap) but this component used to ignore
 * it and render every device, matrix or strip, as one flat row of
 * fixed-width pixel spans: fine for a handful of strip pixels, but his
 * `crystal-mapper` favourite is a real 72x37 matrix (2664 pixels laid out
 * in ONE row = 2664 * 3px wide), which is exactly the "stretches out in a
 * line super far" and "I don't see any Matrix" reports. Fix, per his own
 * stated rule ("a matrix reads as a grid, a strip reads as a line,
 * expanding grows downward not sideways"):
 *   - `shape[0] > 1` (more than one row) renders as a CSS grid
 *     (`device-preview-matrix`, `repeat(cols, 1fr)` columns via a `--cols`/
 *     `--rows` custom property, `aspect-ratio: cols / rows` so it never
 *     needs JS measurement) — reads as a grid, grows only as tall as its
 *     own aspect ratio requires at 100% of the available width.
 *   - `shape[0] === 1` (an ordinary strip) renders as a single flexible
 *     line (`device-preview-pixel-strip`) whose pixels use `flex: 1` to
 *     share exactly 100% of the container width, rather than a fixed
 *     per-pixel width — a 7-pixel dining room strip and a 2664-pixel strip
 *     alike stay within the container, never off the side.
 *   - Expanded devices stack VERTICALLY (`device-preview-chips.expanded`
 *     switches from a flex row to a flex column) instead of sitting side
 *     by side, so "expand" genuinely grows the page downward.
 * Collapsed mode's separate complaint ("it still doesn't quite fit") was
 * `.device-preview-strip`'s own `white-space: nowrap` with no `flex-wrap`
 * — the whole label+swatches+badge+buttons row was forced onto one line
 * that just ran off the right edge of a phone screen. Now wraps.
 *
 * NO "PREVIEW" LABEL, ONE ICON-ONLY STATUS/PAUSE CONTROL (2026-08-16, his
 * own words: "it doesn't need to say the word preview I know what it is
 * ... we don't need a button for pause and resume and also an indicator
 * for if it's paused or running or reconnecting. make the button the
 * indicator ... don't put text use icons"). The separate label span, the
 * standalone paused/running/reconnecting badge, and the Pause/Resume text
 * button collapse into ONE `device-preview-status-btn`: its icon+colour
 * pairing IS the current state, and clicking it is still the same
 * pause/resume toggle. The four states the badge used to carry stay
 * distinguishable at a glance, unchanged in substance — his own manual
 * Pause is a DIFFERENT icon+colour than the automatic hidden-tab pause,
 * on purpose, because collapsing that distinction was never part of the
 * ask (module docstring above, HIDDEN-TAB AUTO-PAUSE): ⏸ live/purple
 * (click pauses), ▶ his own pause/gray (click resumes), ⏾ auto idle —
 * tab hidden/blue (click still pauses manually, same as before), ↻
 * reconnecting-or-unavailable/amber. The full explanation each state used
 * to carry in the badge's `title` lives on this button's `title` +
 * `aria-label` now instead — nothing lost, just not printed as visible
 * text.
 *
 * CANVAS PIXEL PAINT, NOT REACT STATE (2026-08-17, "not anywhere near as
 * smooth as ledfx" — his report; docs/SPECTRA_SPEC.md's device-preview-
 * smoothness section carries the measured numbers). The old shape used one
 * <span> DOM element per pixel inside React state (`setFrames` on every
 * incoming frame, for EVERY favourite device, coalesced into one shared
 * object) — for his `crystal-mapper` favourite (72x37 = 2664 pixels) that
 * meant reconciling 2664 elements on every frame, AND on every OTHER
 * favourite device's frame too, since one shared `frames` state object
 * re-renders the whole strip regardless of which device's frame arrived.
 * Measured: React reconciliation of that grid costs ~30-1000x a single
 * canvas.putImageData() call for the same frame, and under a phone-class
 * (4x) CPU-throttle proxy the DOM path climbed to 43-98ms per frame — a
 * third to most of the entire 125ms budget at the relay's 8fps, BEFORE any
 * other page activity — while canvas stayed under 1.2ms throttled. LedFX's
 * own frontend reaches the identical conclusion: it ships FIVE preview
 * render variants, and the DOM-per-pixel one ('original') is kept only as
 * a slower legacy fallback behind a settings toggle — 'canvas'
 * (PixelGraphCanvas.tsx: direct WebSocket subscription callback ->
 * ctx.putImageData(), no React state in the hot path) is what actually
 * ships by default.
 *
 * Pixel data therefore never touches React state at all: `canvasRefs`/
 * `swatchRefs` hold direct DOM refs per favourite device, and the single
 * onDevicePreviewFrame subscription below paints straight into whichever
 * one is currently mounted (paintDevice) — imperative, exactly LedFX's own
 * division of labour (structural things like a device's shape go through
 * React state since they change rarely and drive which CSS layout to use;
 * per-frame pixel colour never does). `shapes` state exists ONLY to pick
 * matrix-vs-strip layout and is guarded to skip setState when a device's
 * shape hasn't actually changed, so it doesn't reintroduce a per-frame
 * re-render. `latestFrames` remembers each device's last frame so
 * expanding (mounting a fresh canvas) or the live/paused transition can
 * repaint immediately instead of waiting for the next tick.
 *
 * NOT CARRIED FROM LEDFX: the ~81-total-pixel downsample its backend
 * applies by default (visualisation_maxlen, ledfx/core.py — see
 * spectra/services/device_preview.py's module docstring for why that file
 * doesn't port it either) is deliberately NOT added on the frontend side —
 * measured JSON.parse + decode cost for crystal-mapper's full 2664-pixel
 * payload is <1ms even under the same throttle, so it buys no smoothness
 * once canvas removes the render bottleneck, and it would directly conflict
 * with his own explicit ask three months earlier ("I don't see any Matrix
 * for The Matrix previews" — the phone-matrix fix above): downsampling to
 * ~81 points would make Expand show a blur instead of his actual matrix
 * shape. Named incompatibility, not a silent omission. */
import { useEffect, useRef, useState } from 'react';
import {
  averageRgb, decodePixels, onDevicePreviewFrame, onDevicePreviewStatus,
  onDevicePreviewTabHiddenPause,
} from '../api/devicePreviewWs';
import HelpLink from '../help/HelpLink';
import { pauseDevicePreview, resumeDevicePreview, useDevicePreviewFavorites } from '../queries';
import type { DevicePreviewFrame, DevicePreviewStatus } from '../types';
import FavoritesPicker from './FavoritesPicker';
import { useToast } from './Toast';

const EXPANDED_KEY = 'spectra-device-preview-expanded';
const DARK_PLACEHOLDER = 'rgb(40,40,40)';

export default function DevicePreviewStrip() {
  const { data: favorites } = useDevicePreviewFavorites();
  const [status, setStatus] = useState<DevicePreviewStatus | null>(null);
  const [shapes, setShapes] = useState<Record<string, [number, number]>>({});
  const [expanded, setExpanded] = useState(() => localStorage.getItem(EXPANDED_KEY) === '1');
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pausePending, setPausePending] = useState(false);
  const [tabHiddenPause, setTabHiddenPause] = useState(false);
  const toast = useToast();

  const canvasRefs = useRef<Record<string, HTMLCanvasElement | null>>({});
  const swatchRefs = useRef<Record<string, HTMLSpanElement | null>>({});
  const latestFrames = useRef<Record<string, DevicePreviewFrame>>({});
  const liveRef = useRef(false);

  useEffect(() => onDevicePreviewStatus(setStatus), []);
  useEffect(() => onDevicePreviewTabHiddenPause(setTabHiddenPause), []);

  /** Imperative paint helpers — never touch React state, so a frame never
   * costs a re-render (see the module docstring's CANVAS PIXEL PAINT
   * section). Each reads only ref containers, so it stays correct even
   * though it's captured once by the frame-subscription effect below. */
  const paintCanvas = (id: string, triples: [number, number, number][], rows: number, cols: number) => {
    const canvas = canvasRefs.current[id];
    if (!canvas) return;
    if (canvas.width !== cols || canvas.height !== rows) {
      canvas.width = cols;
      canvas.height = rows;
    }
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.imageSmoothingEnabled = false;
    const imageData = ctx.createImageData(cols, rows);
    for (let i = 0; i < triples.length; i++) {
      const [r, g, b] = triples[i];
      imageData.data[i * 4] = r;
      imageData.data[i * 4 + 1] = g;
      imageData.data[i * 4 + 2] = b;
      imageData.data[i * 4 + 3] = 255;
    }
    ctx.putImageData(imageData, 0, 0);
  };
  const blankCanvas = (id: string) => {
    const canvas = canvasRefs.current[id];
    if (!canvas || !canvas.width || !canvas.height) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.fillStyle = DARK_PLACEHOLDER;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  };
  const paintSwatch = (id: string, color: string) => {
    const el = swatchRefs.current[id];
    if (el) el.style.backgroundColor = color;
  };
  const paintDevice = (id: string, frame: DevicePreviewFrame) => {
    if (!liveRef.current) return;
    const triples = decodePixels(frame.pixels);
    const [rows, cols] = frame.shape;
    paintCanvas(id, triples, rows, cols);
    paintSwatch(id, averageRgb(triples));
  };

  // The single per-frame hot path: no setState, so a frame never triggers a
  // React re-render (or worse, re-renders EVERY favourite device's DOM just
  // because one of them got a new frame — the exact cross-device
  // amplification the old shared `frames` state object caused).
  useEffect(() => onDevicePreviewFrame((frame) => {
    latestFrames.current[frame.vis_id] = frame;
    const [rows, cols] = frame.shape;
    setShapes((prev) => {
      const existing = prev[frame.vis_id];
      if (existing && existing[0] === rows && existing[1] === cols) return prev;
      return { ...prev, [frame.vis_id]: [rows, cols] };
    });
    paintDevice(frame.vis_id, frame);
  }), []);

  const toggleExpanded = () => setExpanded((prev) => {
    const next = !prev;
    localStorage.setItem(EXPANDED_KEY, next ? '1' : '0');
    return next;
  });

  const paused = status?.paused ?? false;
  const connected = status?.connected ?? false;
  const live = !paused && !tabHiddenPause && connected;

  // No new frames arrive once non-live (server-side: upstream genuinely
  // stops — see services/device_preview.py), so nothing else would ever
  // blank an already-painted canvas/swatch. liveRef updates first so a
  // frame racing this effect never slips through and repaints afterward.
  useEffect(() => {
    liveRef.current = live;
    if (!live) {
      Object.keys(canvasRefs.current).forEach(blankCanvas);
      Object.keys(swatchRefs.current).forEach((id) => paintSwatch(id, DARK_PLACEHOLDER));
    }
  }, [live]);

  const togglePause = async () => {
    setPausePending(true);
    try {
      await (paused ? resumeDevicePreview() : pauseDevicePreview());
    } catch (err) {
      toast(`Couldn't ${paused ? 'resume' : 'pause'}: ${(err as Error).message}`, 'error');
    } finally {
      setPausePending(false);
    }
  };

  const favoriteIds = favorites?.effective_virtual_ids ?? [];

  const state: 'paused' | 'idle' | 'live' | 'reconnecting' = paused
    ? 'paused' : tabHiddenPause ? 'idle' : connected ? 'live' : 'reconnecting';
  const stateIcon = { paused: '▶', idle: '⏾', live: '⏸', reconnecting: '↻' }[state];
  const stateClass = {
    paused: 'device-preview-status-gray',
    idle: 'device-preview-status-blue',
    live: 'device-preview-status-purple',
    reconnecting: 'device-preview-status-amber',
  }[state];
  const stateTitle = {
    paused: 'Paused — you clicked this. Stays this way until you click again to resume.',
    idle: "Idle — this tab isn't visible, so the connection is closed to conserve resources. It reopens on its own the moment you switch back. Clicking now pauses it manually — it'll stay paused even after you switch back.",
    live: (status?.source === 'facade'
      ? "Live — reading SPECTRA's own live render pipeline directly (in-process, no LedFX involved). Click to pause."
      : "Live — subscribed to LedFX's own visualisation feed. Click to pause."),
    reconnecting: (status?.source === 'none'
      ? "Unavailable — SPECTRA doesn't currently own the lights right now (a handover is in progress, or the room's been released). Picks back up on its own once ownership settles."
      : status?.source === 'facade'
        ? 'Reconnecting to the live render pipeline.'
        : 'Reconnecting to LedFX (never restarts or wakes it).'),
  }[state];
  const stateLabel = { paused: 'Paused, click to resume', idle: 'Idle, tab hidden, click to pause',
    live: 'Live, click to pause', reconnecting: 'Reconnecting' }[state];

  return (
    <div className="device-preview-strip">
      {favoriteIds.length === 0 ? (
        <span className="device-preview-empty">no favourite devices</span>
      ) : (
        <div className={`device-preview-chips${expanded ? ' expanded' : ''}`}>
          {favoriteIds.map((id) => {
            const [rows, cols] = shapes[id] ?? [1, 1];
            const isMatrix = rows > 1;
            return (
              <div key={id} className={`device-preview-device${expanded ? ' expanded' : ''}`} title={id}>
                {expanded && <span className="device-preview-device-label">{id}</span>}
                {expanded ? (
                  <canvas
                    ref={(el) => {
                      canvasRefs.current[id] = el;
                      if (!el) return;
                      const frame = latestFrames.current[id];
                      if (frame && liveRef.current) paintDevice(id, frame);
                      else blankCanvas(id);
                    }}
                    className={isMatrix ? 'device-preview-matrix' : 'device-preview-pixel-strip'}
                    style={{ '--cols': cols, '--rows': rows } as React.CSSProperties}
                  />
                ) : (
                  <span
                    ref={(el) => {
                      swatchRefs.current[id] = el;
                      if (!el) return;
                      const frame = latestFrames.current[id];
                      if (frame && liveRef.current) {
                        paintSwatch(id, averageRgb(decodePixels(frame.pixels)));
                      } else {
                        paintSwatch(id, DARK_PLACEHOLDER);
                      }
                    }}
                    className="device-preview-swatch"
                    style={{ backgroundColor: DARK_PLACEHOLDER }}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}

      <button type="button" className={`device-preview-status-btn ${stateClass}`}
        disabled={pausePending || favoriteIds.length === 0}
        onClick={togglePause} aria-label={stateLabel} title={stateTitle}>
        {stateIcon}
      </button>

      {favoriteIds.length > 0 && (
        <button type="button" className="device-preview-btn" onClick={toggleExpanded}
          title={expanded ? 'Collapse to one swatch per device' : 'Expand to a per-pixel strip'}>
          {expanded ? '▾ Collapse' : '▸ Expand'}
        </button>
      )}

      <button type="button" className="device-preview-btn" onClick={() => setPickerOpen(true)}
        title="Choose favourite devices">
        ★ Favourites
      </button>

      {pickerOpen && (
        <div className="device-preview-picker-overlay" onClick={() => setPickerOpen(false)}>
          <div onClick={(e) => e.stopPropagation()}>
            <FavoritesPicker onClose={() => setPickerOpen(false)} />
          </div>
        </div>
      )}

      <HelpLink topic="device-preview" />
    </div>
  );
}
