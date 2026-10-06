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
 * branch on it — PreviewFrame's wire shape is identical either way
 * (api/devicePreviewWs.ts) — but the "reconnecting…" badge's tooltip does,
 * so it never claims to be reconnecting to LedFX when LedFX was never the
 * source.
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
 * COLLAPSED = ONE AVERAGED COLOUR PER FAVOURITE DEVICE, on the lightweight
 * "summary" level — three bytes per device, nothing else fetched. This
 * never changed; "Expand" is the only thing that does.
 *
 * EXPANDED NOW MATCHES THE DEVICES PAGE'S LIVE TAB, FORMAT AND RENDERER
 * ALIKE (2026-10-06, the owner's own words: "make the expanded preview
 * for the devices look like the layout screen on devices. match the
 * layout and the format"). Before this, expanding drew a flat per-device
 * grid/strip (one <canvas> per favourite, painted with plain
 * putImageData calls) — workable, but a DIFFERENT shape from the real
 * fixture geometry the Live tab draws (the crystal's hex lattice, the TV
 * strip as a frame, bulbs as discs). Expanding now builds its stage from
 * the SAME layout the Live tab's Layout view reads (`/device-preview/layout`,
 * narrowed here to his favourites only — never every in-use fixture,
 * that stays the Live view's own, broader job) and draws a `StagePlan`
 * with the identical renderer (`live/useLiveStageCanvas.ts`, the hook
 * factored out of `LiveView.tsx` for exactly this reuse — one WebGL stage
 * class, one draw loop, never two copies that could drift apart). A
 * fixture's SHAPE and click-to-select read the same as the Live tab's
 * Layout view; the ARRANGEMENT and the text no longer do — see "NO TEXT
 * IN THE EXPANDED STAGE" below, added 2026-10-06. "Open settings" reuses
 * its exact navigation target. What stays strip-only: no Room map, no
 * solo/drag/fullscreen/link-meter chrome — those belong to the dedicated
 * page, not a compact top-bar widget, and adding them here was never the
 * ask ("match the layout and the format", not "become the Live tab").
 *
 * Expanding still switches the WS subscription level to "full" (every
 * favourite's whole frame) and collapsing back to "summary" — unchanged
 * from before, and the one thing the hook needs to actually have pixels
 * to draw. The SCOPE stays "favorites" throughout (api/devicePreviewWs.ts)
 * — expanding here never asks for "in_use" the way mounting the Live view
 * does, so the strip's own cost never grows past his chosen handful of
 * devices regardless of how many fixtures the room has.
 *
 * NOT CARRIED FROM LEDFX: the ~81-total-pixel downsample its backend
 * applies by default (visualisation_maxlen, ledfx/core.py) is deliberately
 * NOT added — see spectra/services/device_preview.py's module docstring
 * for why that file doesn't port it either, and the Live tab's own
 * docstring for why a real matrix shape is worth the extra points.
 *
 * THE STRIP ASKS ONLY FOR WHAT IT DRAWS (2026-10-05, the protocol-2 stream —
 * api/devicePreviewWs.ts). Collapsed, it subscribes at "summary" and each
 * frame is the device's mean colour, three bytes, computed on the server
 * over the device's REAL cells; expanded, it subscribes at "full". Before
 * this the server sent every viewer every favourite's whole frame (10.8 kB
 * for the crystal) on every page, to paint one swatch. A full frame carries
 * real cells only: `cellIndex` says where each one sits, and the rest of the
 * rectangle stays black — the crystal draws as the hexagon it is.
 *
 * A HELD HUE FAVOURITE DRAWS ITS REAL COLOUR, NOT THE STREAM (`layout`'s
 * `LiveVirtual.held`/`LiveFixture.held`, services/preview_layout.py's own
 * `_virtual_held_hex`/`_held_hex`) — a frozen Hue bulb's driving virtual
 * never stops rendering (hue_preview_colour.py's own docstring), so without
 * this the swatch/stage would show the room's live show, not the colour the
 * real bulb is actually held at. Collapsed, the swatch paint helpers below
 * check `held` before the stream; expanded, `live/positions.ts`'s
 * `withHeldOverlay` bakes the same override straight into the `StagePlan`
 * so the shared stage draws it with no extra code here — one definition,
 * reused by this strip and the Live tab's Layout view alike.
 *
 * NO TEXT IN THE EXPANDED STAGE, AND IT NOW LANDS BELOW THE REST OF THE TOP
 * BAR AS ITS OWN FULL-WIDTH ROW (2026-10-06, his own words: "take all the
 * text out of the preview window, it is too messy. also, make it land
 * below the rest of the items on that horizontal bar and have it fill
 * horizontally. it is okay to rearange the different devices for it to fit
 * well on different devices"). Three things:
 *
 * - Every visible string the expanded stage used to draw — a fixture's
 *   name/detail under its shape, the paused/idle/connecting notice, the
 *   selected-fixture name/detail and the "Open settings" button's own
 *   label — is gone. Accessibility survives through `aria-label`/`title`
 *   only, never visible text, per his own instruction: a fixture's hit
 *   target still carries its name+detail as an accessible name and a
 *   hover tooltip, the stage wrap carries the state notice as a `title`
 *   (the status button beside it already carries the SAME sentence, so
 *   nothing informative was dropped, only its always-visible copy), and
 *   "Open settings" is now an icon-only gear button (`Icon name="settings"`
 *   — see iconRegistry.ts) with the same accessible name it always had.
 * - `<DevicePreviewStrip />` returns TWO top-level siblings (a Fragment),
 *   not one: `.device-preview-strip` (the status/expand/favourites
 *   controls, unchanged in place) and, only while expanded,
 *   `.device-preview-expanded-row` (the stage). Both are DIRECT children
 *   of `TopBarStrip`'s own flex-wrap row, so giving the second one
 *   `flex: 1 0 100%` forces it onto its own line below every other top-bar
 *   item and lets it fill that line's full width — no portal, no change to
 *   where the controls themselves sit.
 * - The stage's own ARRANGEMENT is now MEASURED, not a phone/not-phone
 *   guess: `compactPositions` (live/positions.ts, strip-only — the Live
 *   tab's own Layout view keeps calling `layoutPositions`, untouched)
 *   wraps fixtures at the row's own observed pixel width (ResizeObserver on
 *   the wrap, ~`UNIT_PX` stage units per pixel) rather than one of
 *   `layoutPositions`' two fixed presets, so a phone gets a tall single
 *   column, a tablet gets a couple of rows, and a wide desktop spreads
 *   fixtures across one or two short rows that actually use the space —
 *   reflowing continuously rather than switching between two hardcoded
 *   shapes. It carries no per-row label allowance (there is no label to
 *   draw), so it never wastes the vertical room `layoutPositions` reserves
 *   for one. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  frameColor, onDevicePreviewFrame, onDevicePreviewStatus,
  onDevicePreviewTabHiddenPause, setDevicePreviewLevel,
} from '../api/devicePreviewWs';
import type { PreviewFrame } from '../api/devicePreviewWs';
import HelpLink from '../help/HelpLink';
import { compactPositions, withHeldOverlay } from '../live/positions';
import type { LiveLayout, StagePlan } from '../live/positions';
import { useLiveStageCanvas } from '../live/useLiveStageCanvas';
import {
  pauseDevicePreview, resumeDevicePreview, useDevicePreviewFavorites, useDevicePreviewLayout,
} from '../queries';
import type { DevicePreviewStatus } from '../types';
import FavoritesPicker from './FavoritesPicker';
import Icon from './Icon';
import { useToast } from './Toast';

const EXPANDED_KEY = 'spectra-device-preview-expanded';
/** Stage units per measured pixel of the expanded row's own width —
 * chosen to land close to `layoutPositions`' old fixed presets at their
 * own typical container widths (phone ~62 units at ~370px, the "others"
 * column ~118 units at ~700px), so a given screen size looks about as
 * large as it did before this became measured instead of guessed. */
const UNIT_PX = 6;
/** Before the first measurement lands, assume a phone-ish width so there's
 * no flash of an oversized layout on a narrow screen. */
const INITIAL_STAGE_WIDTH_PX = 320;
const DARK_PLACEHOLDER = 'rgb(40,40,40)';

export default function DevicePreviewStrip() {
  const { data: favorites } = useDevicePreviewFavorites();
  // Every HELD Hue favourite's own colour (services/preview_layout.py's
  // `_virtual_held_hex`) — the whole point: a frozen Hue bulb's driving
  // virtual never stops rendering (hue_preview_colour.py's own docstring),
  // so without this the swatch shows the room's live show, not the colour
  // the real bulb is actually held at.
  const { data: layout } = useDevicePreviewLayout();
  const [status, setStatus] = useState<DevicePreviewStatus | null>(null);
  const [expanded, setExpanded] = useState(() => localStorage.getItem(EXPANDED_KEY) === '1');
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pausePending, setPausePending] = useState(false);
  const [tabHiddenPause, setTabHiddenPause] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const toast = useToast();
  const navigate = useNavigate();
  const [stageWidthPx, setStageWidthPx] = useState(INITIAL_STAGE_WIDTH_PX);
  // A STATE-BACKED CALLBACK REF, not a plain `useRef` object — the same
  // shape `useLiveStageCanvas.ts`'s own `canvasRef` uses, and for the
  // identical reason (see that hook's own docstring): `expanded` can
  // already be `true` on mount (restored from localStorage) before
  // `favoriteIds`/`stageLayout` have loaded, so the wrap element doesn't
  // exist on the FIRST render that runs this effect. A plain object ref
  // read once at that render would stay null forever once the wrap
  // actually mounts later, because nothing else in the measuring effect's
  // dependency array changes to re-run it.
  const [stageWrapEl, setStageWrapEl] = useState<HTMLDivElement | null>(null);
  const stageWrapRef = useCallback((el: HTMLDivElement | null) => setStageWrapEl(el), []);

  const swatchRefs = useRef<Record<string, HTMLSpanElement | null>>({});
  const latestFrames = useRef<Record<string, PreviewFrame>>({});
  const liveRef = useRef(false);
  const heldRef = useRef<Record<string, string | null>>({});
  const heldByVirtual = useMemo(() => {
    const m: Record<string, string | null> = {};
    (layout?.virtuals ?? []).forEach((v) => { m[v.id] = v.held; });
    return m;
  }, [layout]);
  heldRef.current = heldByVirtual;

  useEffect(() => onDevicePreviewStatus(setStatus), []);
  useEffect(() => onDevicePreviewTabHiddenPause(setTabHiddenPause), []);

  const paintSwatch = (id: string, color: string) => {
    const el = swatchRefs.current[id];
    if (el) el.style.backgroundColor = color;
  };
  /** Repaint one collapsed swatch right now, from whatever is already known
   * (no frame required) — held colour wins, else its latest frame, else the
   * dark placeholder. Used when `held` itself changes, so a Set press is
   * reflected without waiting for the next stream frame. The expanded
   * stage needs no equivalent — its held override lives in the `StagePlan`
   * itself (module docstring), so the stage repaints it on its own. */
  const repaintSwatch = (id: string) => {
    if (!liveRef.current) { paintSwatch(id, DARK_PLACEHOLDER); return; }
    const held = heldRef.current[id];
    if (held) { paintSwatch(id, held); return; }
    const frame = latestFrames.current[id];
    if (frame) paintSwatch(id, frameColor(frame));
  };

  // The collapsed strip's own per-frame hot path: no setState, so a frame
  // never triggers a React re-render. The expanded stage paints straight
  // from the same onDevicePreviewFrame stream inside useLiveStageCanvas —
  // this subscription only ever touches the swatches. A held favourite's
  // swatch ignores the stream entirely (repaintSwatch below owns it).
  useEffect(() => onDevicePreviewFrame((frame) => {
    latestFrames.current[frame.visId] = frame;
    if (!liveRef.current || heldRef.current[frame.visId]) return;
    paintSwatch(frame.visId, frameColor(frame));
  }), []);

  // `held` changes independently of the stream (a mode "Set" press, polled
  // via the layout query) — repaint every mounted swatch immediately
  // rather than waiting for its next frame.
  useEffect(() => {
    Object.keys(swatchRefs.current).forEach(repaintSwatch);
  }, [heldByVirtual]);

  // 'summary' collapsed, 'full' expanded (module docstring: THE STRIP ASKS
  // ONLY FOR WHAT IT DRAWS). Scope stays "favorites" either way.
  useEffect(() => {
    setDevicePreviewLevel('top-strip', expanded ? 'full' : 'summary');
    return () => setDevicePreviewLevel('top-strip', null);
  }, [expanded]);

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
  // blank an already-painted swatch. liveRef updates first so a frame
  // racing this effect never slips through and repaints afterward.
  useEffect(() => {
    liveRef.current = live;
    if (!live) Object.keys(swatchRefs.current).forEach((id) => paintSwatch(id, DARK_PLACEHOLDER));
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

  // Expanded: the SAME layout the Devices page's Live tab draws from,
  // narrowed to his favourites — the strip's own scope.
  const favoriteSet = useMemo(() => new Set(favoriteIds), [favoriteIds]);
  const stageLayout: LiveLayout | null = useMemo(() => (layout
    ? { ...layout, virtuals: layout.virtuals.filter((v) => favoriteSet.has(v.id)) }
    : null), [layout, favoriteSet]);
  // The expanded row's own observed content width, in pixels — fed into
  // `compactPositions` (via UNIT_PX) so the arrangement reflows against the
  // row's REAL width (phone/tablet/desktop alike) instead of a phone/
  // not-phone guess. Measured on the wrap, not the stage itself: the
  // stage's own width is a plain `100%` of the wrap (module docstring),
  // never a function of the plan, so there's no circularity in measuring
  // it before `plan` exists.
  useEffect(() => {
    if (!expanded || !stageWrapEl) return undefined;
    const measure = () => setStageWidthPx(stageWrapEl.clientWidth);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(stageWrapEl);
    return () => observer.disconnect();
  }, [expanded, stageWrapEl]);
  const plan: StagePlan | null = useMemo(
    () => (expanded && stageLayout
      ? withHeldOverlay(compactPositions(stageLayout, stageWidthPx / UNIT_PX), stageLayout)
      : null),
    [expanded, stageLayout, stageWidthPx]);
  const { canvasRef } = useLiveStageCanvas({
    plan, live, smooth: true, active: expanded,
  });
  const fixtures = plan?.fixtures ?? [];
  const selectedFixture = fixtures.find((f) => f.key === selected) ?? null;
  useEffect(() => {
    if (!expanded) setSelected(null);
  }, [expanded]);

  const openSettings = (deviceId: string) => navigate(`/devices?device=${encodeURIComponent(deviceId)}`);

  const pct = (value: number, of: number) => `${(value / of) * 100}%`;

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

  const notice = paused
    ? 'The preview is paused.'
    : tabHiddenPause
      ? 'Idle while this tab is hidden.'
      : !connected
        ? (status?.source === 'none'
          ? 'Nothing is driving the lights right now.'
          : 'Connecting…')
        : null;

  // `<DevicePreviewStrip />` returns TWO top-level siblings here, not one —
  // module docstring's "NO TEXT IN THE EXPANDED STAGE..." section explains
  // why: `.device-preview-strip` (the controls, unchanged in place) and,
  // only while expanded, `.device-preview-expanded-row` (the stage) — both
  // land as direct children of `TopBarStrip`'s own flex-wrap row, which is
  // what lets the second one drop onto its own full-width line below every
  // other top-bar item.
  return (
    <>
      <div className="device-preview-strip">
        {favoriteIds.length === 0 ? (
          <span className="device-preview-empty">no favourite devices</span>
        ) : !expanded ? (
          <div className="device-preview-chips">
            {favoriteIds.map((id) => (
              <div key={id} className="device-preview-device" title={id}>
                <span
                  ref={(el) => {
                    swatchRefs.current[id] = el;
                    if (!el) return;
                    const held = heldRef.current[id];
                    if (held && liveRef.current) {
                      paintSwatch(id, held);
                    } else {
                      const frame = latestFrames.current[id];
                      if (frame && liveRef.current) {
                        paintSwatch(id, frameColor(frame));
                      } else {
                        paintSwatch(id, DARK_PLACEHOLDER);
                      }
                    }
                  }}
                  className="device-preview-swatch"
                  style={{ backgroundColor: DARK_PLACEHOLDER }}
                />
              </div>
            ))}
          </div>
        ) : null}

        <button type="button" className={`device-preview-status-btn ${stateClass}`}
          disabled={pausePending || favoriteIds.length === 0}
          onClick={togglePause} aria-label={stateLabel} title={stateTitle}>
          {stateIcon}
        </button>

        {favoriteIds.length > 0 && (
          <button type="button" className="device-preview-btn" onClick={toggleExpanded}
            title={expanded ? 'Collapse to one swatch per device' : 'Expand to the real fixture layout'}>
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

      {expanded && favoriteIds.length > 0 && (
        <div className="device-preview-expanded-row">
          <div className="device-preview-live">
            <div className="device-preview-live-wrap" ref={stageWrapRef} title={notice ?? undefined}>
              <div className="device-preview-live-stage"
                   style={{ '--live-ar': plan ? plan.width / plan.height : 2 } as React.CSSProperties}>
                <canvas ref={canvasRef} className="live-canvas" />
                {plan && fixtures.map((f) => (
                  <button key={f.key} type="button"
                          className={`live-hit${selected === f.key ? ' selected' : ''}`}
                          style={{
                            left: pct(f.x, plan.width), top: pct(f.y, plan.height),
                            width: pct(f.w, plan.width), height: pct(f.h, plan.height),
                          }}
                          onClick={() => setSelected(selected === f.key ? null : f.key)}
                          aria-label={`${f.name}, ${f.detail}`}
                          title={`${f.name} — ${f.detail}`} />
                ))}
              </div>
            </div>
            {selectedFixture && (
              <div className="live-selected">
                <button type="button" onClick={() => openSettings(selectedFixture.deviceId)}
                        aria-label={`Open settings for ${selectedFixture.name}, ${selectedFixture.detail}`}
                        title={`Open settings for ${selectedFixture.name} — ${selectedFixture.detail}`}>
                  <Icon name="settings" size={14} />
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
