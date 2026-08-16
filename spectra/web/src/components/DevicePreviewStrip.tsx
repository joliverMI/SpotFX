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
 * reopens the upstream LedFX connection — this component never fakes that
 * by hiding swatches while a hidden feed keeps running; `connected` here
 * is the server's own honest state, not a local guess, and swatches only
 * ever render live colour while BOTH unpaused and connected.
 *
 * Default view is a compact single swatch per favourite device (LedFX's
 * own per-pixel average — see api/devicePreviewWs.ts's averageRgb);
 * "Expand" reveals the full per-pixel strip, remembered client-side
 * (report §5), same local-first pattern as the feedback queue. */
import { useEffect, useState } from 'react';
import { averageRgb, decodePixels, onDevicePreviewFrame, onDevicePreviewStatus } from '../api/devicePreviewWs';
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
  const toast = useToast();

  useEffect(() => onDevicePreviewStatus(setStatus), []);
  useEffect(() => onDevicePreviewFrame((frame) => {
    setFrames((prev) => ({ ...prev, [frame.vis_id]: frame }));
  }), []);

  const toggleExpanded = () => setExpanded((prev) => {
    const next = !prev;
    localStorage.setItem(EXPANDED_KEY, next ? '1' : '0');
    return next;
  });

  const paused = status?.paused ?? false;
  const connected = status?.connected ?? false;
  const live = !paused && connected;

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
        <div className="device-preview-chips">
          {favoriteIds.map((id) => {
            const frame = frames[id];
            const triples = live && frame ? decodePixels(frame.pixels) : [];
            return (
              <div key={id} className="device-preview-device" title={id}>
                {expanded && triples.length > 0 ? (
                  <div className="device-preview-pixel-strip">
                    {triples.map((rgb, i) => (
                      <span key={i} className="device-preview-pixel"
                        style={{ backgroundColor: `rgb(${rgb[0]},${rgb[1]},${rgb[2]})` }} />
                    ))}
                  </div>
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
        className={`badge ${paused ? 'badge-gray' : connected ? 'badge-purple' : 'badge-amber'}`}
        title={paused
          ? 'Paused — the connection to LedFX is closed, not just hidden, so nothing is being subscribed to right now'
          : connected
            ? "Live — subscribed to LedFX's own visualisation feed"
            : 'Preview unavailable — reconnecting to LedFX (never restarts or wakes it)'}
      >
        {paused ? 'paused' : connected ? 'live' : 'reconnecting…'}
      </span>

      <button type="button" className="device-preview-btn" disabled={pausePending || favoriteIds.length === 0}
        onClick={togglePause}
        title={paused ? 'Resume the preview' : 'Pause the preview — drops the LedFX connection to conserve resources'}>
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
