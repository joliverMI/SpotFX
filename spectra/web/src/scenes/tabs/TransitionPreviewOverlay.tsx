/** The SCENE-TO-SCENE TRANSITION scrubbing preview (2026-08-27,
 * fm/flare-preview-offsets-everywhere) — half two of his own sequencing
 * for this system ("start with the flares, then we will do lull charge
 * drop"). Opened from the Phase tab.
 *
 * SAME SHAPE AS THE FLARE PREVIEW, deliberately: /open computes a
 * hardware-free timeline and arms the pause (his live show stops the
 * instant a preview opens); the LIVE half is a separate call per CUE per
 * lap, timed against times the SERVER computed and returned. Every marker
 * position and every fire moment in this file comes off the response —
 * animation_anchor_s / trigger_mark_s / fire_at_s / cues[].at_s — never
 * re-derived here. That rule is not stylistic: the founding defect of this
 * whole system was a preview whose drawing and whose firing disagreed
 * about the same moment.
 *
 * WHAT THE RULER SHOWS
 *   - the accent band: the transition's REAL, intensity-scaled crossfade
 *     (crossfade_ms — the same fallback chain the show resolves, so his
 *     global_transition_ms of 0 reads as the intensity-scaled default and
 *     not as "instant");
 *   - the ANCHOR line: where the crossfade's payoff lands. A scene
 *     transition anchors its MIDDLE — the settled family — at
 *     anchor_frac x crossfade: the plain 0.5 midpoint, or a registered
 *     phased pair's own 0.45;
 *   - the TRIGGER mark (draggable): dragging writes
 *     SceneV2.trigger_offset_ms, HIS sign convention — right to fire
 *     earlier (negative), left to fire later (positive) — the identical
 *     gesture and identical formula the flare preview's own marker uses.
 *     It is a real scene-draft edit, saved by the page's Save button.
 *
 * TWO CUES PER LAP, both server-timed: "rearm" puts the room back on the
 * outgoing scene at the top of the lap (so the next lap has something to
 * cross FROM), "fire" performs the transition being judged. */
import { useEffect, useRef, useState } from 'react';
import HelpLink from '../../help/HelpLink';
import {
  closeFlarePreview, closeFlarePreviewBeacon, fireTransitionPreview, openTransitionPreview,
} from '../../queries';
import type { TransitionPreviewTimeline } from '../../queries';
import type { SceneV2 } from '../../types';
import PreviewRuler from './PreviewRuler';
import type { RulerBand, RulerMark } from './PreviewRuler';
import { useCueLoop, useHeartbeat } from './usePreviewLoop';

const fmtMs = (ms: number) => `${Math.round(ms)} ms`;

export default function TransitionPreviewOverlay({
  scene, scenes, onClose, onTriggerOffsetChange,
}: {
  scene: SceneV2;
  scenes: SceneV2[];
  onClose: () => void;
  onTriggerOffsetChange: (ms: number) => void;
}) {
  const [intensity, setIntensity] = useState(1.0);
  const [fromSceneId, setFromSceneId] = useState<string | null>(
    scenes.find((s) => s.id !== scene.id)?.id ?? null);
  const [timeline, setTimeline] = useState<TransitionPreviewTimeline | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [markS, setMarkS] = useState<number | null>(null);
  const markInitialized = useRef(false);

  const { holdExpired, onHoldExpired, clearExpired } = useHeartbeat();

  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      openTransitionPreview(scene.id, fromSceneId, intensity)
        .then((tl) => {
          if (cancelled) return;
          setTimeline(tl);
          setError(null);
          clearExpired();
          if (!markInitialized.current) {
            setMarkS(tl.trigger_mark_s);
            markInitialized.current = true;
          }
        })
        .catch((e) => !cancelled && setError(String(e)));
    }, 200);
    return () => { cancelled = true; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene.id, fromSceneId, intensity]);

  const { playheadS, playing, setPlaying, scrubTo } = useCueLoop({
    timeline,
    fire: (step) => fireTransitionPreview(scene.id, fromSceneId, intensity, step)
      .then((res) => { if (res.expired) onHoldExpired(); })
      .catch((e) => setError(String(e))),
  });

  useEffect(() => () => { void closeFlarePreview(); }, []);
  useEffect(() => {
    const onBeforeUnload = () => closeFlarePreviewBeacon();
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, []);

  const anchorS = timeline
    ? timeline.animation_start_s + timeline.anchor_frac
      * (timeline.animation_end_s - timeline.animation_start_s)
    : 0;
  const drawnMarkS = markS ?? timeline?.trigger_mark_s ?? 0;
  const bands: RulerBand[] = timeline
    ? [{ from_s: timeline.animation_start_s, to_s: timeline.animation_end_s,
         label: 'crossfade', tone: 'accent' }]
    : [];
  const marks: RulerMark[] = timeline
    ? [{ at_s: anchorS, label: 'anchor', tone: 'accent' },
       { at_s: timeline.animation_start_s, label: 'start', tone: 'muted', dashed: true },
       { at_s: timeline.animation_end_s, label: 'end', tone: 'muted', dashed: true }]
    : [];

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)', zIndex: 300,
                  display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={onClose}>
      <div className="card" style={{ width: 'min(760px, 96vw)', maxHeight: '92vh', overflowY: 'auto' }}
        onClick={(e) => e.stopPropagation()}>
        <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          ▶ Preview transition → {scene.name}
          <HelpLink topic="transition-preview-timeline" title="What the markers mean" />
          <button style={{ marginLeft: 'auto', fontSize: 12 }} onClick={onClose}>✕ Close</button>
        </div>

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, margin: '8px 0' }}>
          <span style={{ color: 'var(--text-muted)' }}>Coming from</span>
          <select value={fromSceneId ?? scene.id} style={{ flex: 1 }}
            onChange={(e) => setFromSceneId(e.target.value === scene.id ? null : e.target.value)}>
            {scenes.map((s) => (
              <option key={s.id} value={s.id}>{s.id === scene.id ? `${s.name} (itself)` : s.name}</option>
            ))}
          </select>
        </label>

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, margin: '8px 0' }}>
          <span style={{ color: 'var(--text-muted)' }}>Intensity</span>
          <input type="range" min={0} max={1} step={0.01} value={intensity}
            onChange={(e) => setIntensity(Number(e.target.value))} style={{ flex: 1 }} />
          <span style={{ fontVariantNumeric: 'tabular-nums', width: 36 }}>{intensity.toFixed(2)}</span>
        </label>

        {holdExpired && (
          <div style={{ fontSize: 12, padding: '6px 8px', borderRadius: 6, marginBottom: 4,
                        background: 'var(--accent)', color: '#1a1024' }}>
            ⏱ This preview reached its maximum hold time and let go of your room on its
            own — your show has resumed. Close and reopen — or nudge the intensity
            slider — to look again.
          </div>
        )}
        {error && <div style={{ color: 'var(--danger, #f66)', fontSize: 12 }}>{error}</div>}
        {!timeline && !error && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Computing…</div>}

        {timeline && (
          <>
            <PreviewRuler
              durationS={timeline.duration_s}
              playheadS={playheadS}
              bands={bands}
              marks={marks}
              triggerMarkS={drawnMarkS}
              onScrub={scrubTo}
              onTriggerDrag={setMarkS}
              onTriggerDragEnd={(s) => {
                // HIS sign convention, and the SAME formula the flare
                // preview's own drag uses (the inverse of the server's
                // trigger_mark_s): offset = anchor - mark, so dragging
                // RIGHT makes it more negative = fires earlier.
                onTriggerOffsetChange(Math.round(
                  (timeline.animation_anchor_s - s) * 1000));
              }}
            />

            <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, marginTop: 4 }}>
              <button onClick={() => setPlaying(!playing)}>{playing ? '⏸ Pause' : '▶ Play'}</button>
              <span style={{ color: 'var(--text-muted)' }}>
                ↻ loops & re-fires live every {timeline.duration_s.toFixed(2)}s — pausing stops both
              </span>
              <span style={{ marginLeft: 'auto', color: 'var(--text-muted)' }}>
                playhead {playheadS.toFixed(2)}s
              </span>
            </div>

            <div style={{ fontSize: 12, marginTop: 6, padding: '6px 8px', borderRadius: 6,
                          background: 'var(--panel-bg, #1a1024)' }}>
              This transition crossfades over <strong>{fmtMs(timeline.crossfade_ms)}</strong>
              {' '}at this intensity, and its payoff is anchored at{' '}
              <strong>{Math.round(timeline.anchor_frac * 100)}%</strong> of the blend —{' '}
              {timeline.anchor_source === 'phased_pair'
                ? 'this pair of effects choreographs a phased handoff, so that phase is what lands on the mark'
                : 'the plain mid-point, which is what every ordinary scene change uses'}
              . The show therefore fires it <strong>{fmtMs(timeline.lead_ms)}</strong> early, so the
              anchor — not the start of the blend — lands on the trigger.
              <br />
              Drag the trigger line to retime it: right to fire earlier (negative), left to fire
              later (positive). It saves onto this scene's own trigger_offset_ms (Save the scene to
              keep it), and your real song triggers then fire this scene by the same offset — the
              drag retimes your show, not just this preview.
            </div>
          </>
        )}
      </div>
    </div>
  );
}
