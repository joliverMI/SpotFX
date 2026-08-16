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
 * that just ran off the right edge of a phone screen. Now wraps. */
import { useEffect, useState } from 'react';
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

export default function DevicePreviewStrip() {
  const { data: favorites } = useDevicePreviewFavorites();
  const [status, setStatus] = useState<DevicePreviewStatus | null>(null);
  const [frames, setFrames] = useState<Record<string, DevicePreviewFrame>>({});
  const [expanded, setExpanded] = useState(() => localStorage.getItem(EXPANDED_KEY) === '1');
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pausePending, setPausePending] = useState(false);
  const [tabHiddenPause, setTabHiddenPause] = useState(false);
  const toast = useToast();

  useEffect(() => onDevicePreviewStatus(setStatus), []);
  useEffect(() => onDevicePreviewFrame((frame) => {
    setFrames((prev) => ({ ...prev, [frame.vis_id]: frame }));
  }), []);
  useEffect(() => onDevicePreviewTabHiddenPause(setTabHiddenPause), []);

  const toggleExpanded = () => setExpanded((prev) => {
    const next = !prev;
    localStorage.setItem(EXPANDED_KEY, next ? '1' : '0');
    return next;
  });

  const paused = status?.paused ?? false;
  const connected = status?.connected ?? false;
  const live = !paused && !tabHiddenPause && connected;

  const togglePause = async () => {
    setPausePending(true);
    try {
      await (paused ? resumeDevicePreview() : pauseDevicePreview());
    } catch (err) {
      toast(`Couldn't ${paused ? 'resume' : 'pause'} the preview: ${(err as Error).message}`, 'error');
    } finally {
      setPausePending(false);
    }
  };

  const favoriteIds = favorites?.effective_virtual_ids ?? [];

  return (
    <div className="device-preview-strip">
      <span className="device-preview-label">Preview</span>

      {favoriteIds.length === 0 ? (
        <span className="device-preview-empty">no devices to preview</span>
      ) : (
        <div className={`device-preview-chips${expanded ? ' expanded' : ''}`}>
          {favoriteIds.map((id) => {
            const frame = frames[id];
            const triples = live && frame ? decodePixels(frame.pixels) : [];
            const [rows, cols] = frame?.shape ?? [1, triples.length];
            const isMatrix = rows > 1;
            return (
              <div key={id} className={`device-preview-device${expanded ? ' expanded' : ''}`} title={id}>
                {expanded && <span className="device-preview-device-label">{id}</span>}
                {expanded && triples.length > 0 ? (
                  isMatrix ? (
                    <div className="device-preview-matrix"
                      style={{ '--cols': cols, '--rows': rows } as React.CSSProperties}>
                      {triples.map((rgb, i) => (
                        <span key={i} className="device-preview-matrix-cell"
                          style={{ backgroundColor: `rgb(${rgb[0]},${rgb[1]},${rgb[2]})` }} />
                      ))}
                    </div>
                  ) : (
                    <div className="device-preview-pixel-strip">
                      {triples.map((rgb, i) => (
                        <span key={i} className="device-preview-pixel"
                          style={{ backgroundColor: `rgb(${rgb[0]},${rgb[1]},${rgb[2]})` }} />
                      ))}
                    </div>
                  )
                ) : (
                  <span className="device-preview-swatch"
                    style={{ backgroundColor: live ? averageRgb(triples) : 'rgb(40,40,40)' }} />
                )}
              </div>
            );
          })}
        </div>
      )}

      <span
        className={`badge ${
          paused ? 'badge-gray' : tabHiddenPause ? 'badge-blue' : connected ? 'badge-purple' : 'badge-amber'
        }`}
        title={paused
          ? 'Paused — you clicked Pause. The connection is closed, not just hidden — stays this way until you click Resume.'
          : tabHiddenPause
            ? "Idle — this tab isn't visible, so the connection is closed to conserve resources. It reopens on its own the moment you switch back — nothing to click."
            : connected
              ? (status?.source === 'facade'
                  ? "Live — reading SPECTRA's own live render pipeline directly (in-process, no LedFX involved)"
                  : "Live — subscribed to LedFX's own visualisation feed")
              : status?.source === 'none'
                ? "Preview unavailable — SPECTRA doesn't currently own the lights right now (a handover is in progress, or the room's been released), so there's nothing to read frames from. Picks back up on its own once ownership settles."
                : status?.source === 'facade'
                  ? 'Preview unavailable — reconnecting to the live render pipeline'
                  : 'Preview unavailable — reconnecting to LedFX (never restarts or wakes it)'}
      >
        {paused ? 'paused' : tabHiddenPause ? 'idle — tab hidden' : connected ? 'live'
          : status?.source === 'none' ? 'unavailable' : 'reconnecting…'}
      </span>

      <button type="button" className="device-preview-btn" disabled={pausePending || favoriteIds.length === 0}
        onClick={togglePause}
        title={paused ? 'Resume the preview' : 'Pause the preview — drops the live connection to conserve resources'}>
        {paused ? '▶ Resume' : '⏸ Pause'}
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
