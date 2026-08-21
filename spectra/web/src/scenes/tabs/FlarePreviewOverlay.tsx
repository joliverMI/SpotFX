/** The flare scrubbing-preview timeline (owner ask, flares first —
 * data/timeline-preview-scrub-flares-and-drop-sequences/HIS-VERBATIM-
 * WORDS.md), NOW WITH A LIVE HOLD (owner correction, same day —
 * spectra/services/flare_preview_hold.py's own docstring has the full
 * history). Opened from a "▶ Preview" button on a flare kind card
 * (ResponseTab.tsx). /flare-preview/open does two things: computes a
 * deterministic write timeline for this ONE kind (spectra/services/
 * flare_preview.py, still hardware-free — the ruler/scrub/loop below plays
 * this locally, no repeated backend calls per frame) AND, separately,
 * fires this card's scene + kind for REAL onto his fixtures and holds
 * them there for as long as this overlay stays open. Closing (or losing
 * the tab/connection — see the heartbeat block below) reverts his room to
 * exactly what it showed before the preview opened.
 *
 * Two independent marker kinds, per his brief:
 *   - the TRIGGER mark (draggable) — where he considers this kind
 *     "fired." Dragging it writes SceneV2.flare_kinds[].trigger_offset_ms
 *     via onTriggerOffsetChange — this is a real scene-draft EDIT, saved
 *     by the page's own Save button like any other field, not a
 *     preview-only, forgotten-on-close exploration.
 *   - the ANIMATION START/END markers (fixed, computed) — read straight
 *     off the real production timing constants (DICE_REROLL_GLIDE_MS,
 *     hold_ms, PULSE_RELEASE_S, GAIN_GLIDE_S, the colour-jump ramp). This
 *     is the instrument for his "explosion starts early" complaint: the
 *     gap readout below the ruler states, in milliseconds, how far the
 *     trigger sits from where the effect actually starts moving.
 *
 * "Automatically pauses the trigger engine": /flare-preview/open arms
 * preview_pause for as long as this overlay stays mounted, kept alive by
 * a heartbeat (server timeout is generous — a missed beat or two doesn't
 * un-pause under it) and explicitly released on close/unmount/tab-close.
 * Since the hold above is now a real fire, the SAME heartbeat also keeps
 * the live hold's own server-side revert timer armed — a lapsed heartbeat
 * (closed browser, dropped connection) reverts his room automatically,
 * not just un-pauses the trigger engine. */
import { useEffect, useRef, useState } from 'react';
import HelpLink from '../../help/HelpLink';
import {
  closeFlarePreview, closeFlarePreviewBeacon, heartbeatFlarePreview, openFlarePreview,
} from '../../queries';
import type { FlarePreviewTimeline, FlarePreviewWrite } from '../../queries';
import type { FlareKind } from '../../types';

const HEARTBEAT_MS = 5000;
const EXTEND_STEP_S = 2;
const MAX_DURATION_S = 60;
const PAD_X = 16;
const RULER_W = 680;
const RULER_H = 96;

const fmtMs = (s: number) => `${Math.round(s * 1000)} ms`;
const fmtS = (s: number) => `${s.toFixed(2)}s`;

function tickStep(durationS: number): number {
  if (durationS <= 8) return 1;
  if (durationS <= 20) return 2;
  return 5;
}

function writeLabel(w: FlarePreviewWrite): string {
  const params = Object.entries(w.params)
    .map(([p, v]) => `${p}→${typeof v === 'number' ? Math.round(v * 1000) / 1000 : v}`)
    .join(', ');
  const verb = w.kind === 'jump' ? 'jumps' : `glides over ${w.duration_ms}ms`;
  return `${w.virtual_id}: ${verb} — ${params}`;
}

export default function FlarePreviewOverlay({ sceneId, kind, onClose, onTriggerOffsetChange }: {
  sceneId: string;
  kind: FlareKind;
  onClose: () => void;
  onTriggerOffsetChange: (ms: number) => void;
}) {
  const [intensity, setIntensity] = useState(1.0);
  const [timeline, setTimeline] = useState<FlarePreviewTimeline | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [durationS, setDurationS] = useState(6.0);
  const [animAnchorS, setAnimAnchorS] = useState(2.0);
  const [triggerMarkS, setTriggerMarkS] = useState(2.0 + kind.trigger_offset_ms / 1000);
  const [playheadS, setPlayheadS] = useState(0);
  const [playing, setPlaying] = useState(true);
  const rulerRef = useRef<SVGSVGElement | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastFrameRef = useRef<number | null>(null);
  const initializedMarksRef = useRef(false);

  // ── fetch a fresh timeline whenever intensity changes (debounced) —
  // also (re)arms preview_pause on the server. ──────────────────────────
  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      openFlarePreview(sceneId, kind.name, intensity)
        .then((tl) => {
          if (cancelled) return;
          setTimeline(tl);
          setError(null);
          const anchor = Math.min(2.0, tl.duration_s / 3);
          setAnimAnchorS(anchor);
          setDurationS((prev) => (initializedMarksRef.current ? Math.max(prev, tl.duration_s) : tl.duration_s));
          if (!initializedMarksRef.current) {
            setTriggerMarkS(Math.max(0, Math.min(tl.duration_s, anchor + kind.trigger_offset_ms / 1000)));
            initializedMarksRef.current = true;
          }
        })
        .catch((e) => !cancelled && setError(String(e)));
    }, 200);
    return () => { cancelled = true; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sceneId, kind.name, intensity]);

  // ── heartbeat + release-on-close (auto-pauses the trigger engine for
  // as long as this overlay is open) ────────────────────────────────────
  useEffect(() => {
    const iv = setInterval(() => { void heartbeatFlarePreview(); }, HEARTBEAT_MS);
    const onBeforeUnload = () => closeFlarePreviewBeacon();
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => {
      clearInterval(iv);
      window.removeEventListener('beforeunload', onBeforeUnload);
      void closeFlarePreview();
    };
  }, []);

  // ── play/loop: advance the playhead in real time, wrap at durationS ───
  useEffect(() => {
    if (!playing) { lastFrameRef.current = null; return undefined; }
    const step = (now: number) => {
      if (lastFrameRef.current != null) {
        const dt = (now - lastFrameRef.current) / 1000;
        setPlayheadS((prev) => {
          const next = prev + dt;
          return next >= durationS ? next % durationS : next;
        });
      }
      lastFrameRef.current = now;
      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      lastFrameRef.current = null;
    };
  }, [playing, durationS]);

  const xToS = (clientX: number): number => {
    const svg = rulerRef.current;
    if (!svg) return 0;
    const rect = svg.getBoundingClientRect();
    const frac = (clientX - rect.left - PAD_X) / (rect.width - 2 * PAD_X);
    return Math.max(0, Math.min(durationS, frac * durationS));
  };
  const sToX = (s: number): number => PAD_X + (s / durationS) * (RULER_W - 2 * PAD_X);

  const dragTrigger = (e: React.PointerEvent) => {
    e.stopPropagation();
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    const move = (ev: PointerEvent) => {
      const s = xToS(ev.clientX);
      setTriggerMarkS(s);
    };
    const up = (ev: PointerEvent) => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      const s = xToS(ev.clientX);
      onTriggerOffsetChange(Math.round((s - animAnchorS) * 1000));
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const scrubRuler = (e: React.PointerEvent) => {
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    setPlaying(false);
    setPlayheadS(xToS(e.clientX));
    const move = (ev: PointerEvent) => setPlayheadS(xToS(ev.clientX));
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const gapMs = Math.round((triggerMarkS - animAnchorS) * 1000);
  const animStartAbs = timeline?.animation_start_s != null ? animAnchorS + timeline.animation_start_s : null;
  const animEndAbs = timeline?.animation_end_s != null ? animAnchorS + timeline.animation_end_s : null;
  const ticks: number[] = [];
  for (let t = 0; t <= durationS + 1e-6; t += tickStep(durationS)) ticks.push(t);

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)', zIndex: 300,
                  display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={onClose}>
      <div className="card" style={{ width: 'min(760px, 96vw)', maxHeight: '92vh', overflowY: 'auto' }}
        onClick={(e) => e.stopPropagation()}>
        <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          ▶ Preview — {kind.name}
          <span className="chip">{kind.type}</span>
          <HelpLink topic="flare-preview-timeline" title="What the markers mean" />
          <button style={{ marginLeft: 'auto', fontSize: 12 }} onClick={onClose}>✕ Close</button>
        </div>

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, margin: '8px 0' }}>
          <span style={{ color: 'var(--text-muted)' }}>Intensity</span>
          <input type="range" min={0} max={1} step={0.01} value={intensity}
            onChange={(e) => setIntensity(Number(e.target.value))} style={{ flex: 1 }} />
          <span style={{ fontVariantNumeric: 'tabular-nums', width: 36 }}>{intensity.toFixed(2)}</span>
        </label>

        {error && <div style={{ color: 'var(--danger, #f66)', fontSize: 12 }}>{error}</div>}
        {!timeline && !error && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Computing…</div>}

        {timeline && timeline.writes.length === 0 && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            This kind produces no writes at this intensity — {timeline.result === 'no_visible_effect'
              ? 'its params don\'t match any live virtual\'s registered params (or its gain is 1.0 with no params at all).'
              : `result: ${timeline.result}.`}
          </div>
        )}

        {timeline && (
          <>
            <svg ref={rulerRef} viewBox={`0 0 ${RULER_W} ${RULER_H}`}
              style={{ width: '100%', height: RULER_H, touchAction: 'none', cursor: 'pointer' }}
              onPointerDown={scrubRuler}>
              <rect x={0} y={0} width={RULER_W} height={RULER_H} fill="var(--panel-bg, #1a1024)" />
              {animStartAbs != null && animEndAbs != null && (
                <rect x={sToX(animStartAbs)} y={20} width={Math.max(1, sToX(animEndAbs) - sToX(animStartAbs))}
                  height={RULER_H - 40} fill="var(--accent)" opacity={0.18} />
              )}
              {ticks.map((t) => (
                <g key={t}>
                  <line x1={sToX(t)} x2={sToX(t)} y1={RULER_H - 18} y2={RULER_H - 12} stroke="var(--text-muted)" />
                  <text x={sToX(t)} y={RULER_H - 2} fontSize={9} fill="var(--text-muted)" textAnchor="middle">
                    {t}s
                  </text>
                </g>
              ))}
              {animStartAbs != null && (
                <g>
                  <line x1={sToX(animStartAbs)} x2={sToX(animStartAbs)} y1={16} y2={RULER_H - 20}
                    stroke="var(--accent)" strokeWidth={2} />
                  <text x={sToX(animStartAbs)} y={12} fontSize={9} fill="var(--accent)" textAnchor="middle">start</text>
                </g>
              )}
              {animEndAbs != null && (
                <g>
                  <line x1={sToX(animEndAbs)} x2={sToX(animEndAbs)} y1={16} y2={RULER_H - 20}
                    stroke="var(--accent)" strokeWidth={2} strokeDasharray="3,2" />
                  <text x={sToX(animEndAbs)} y={12} fontSize={9} fill="var(--accent)" textAnchor="middle">end</text>
                </g>
              )}
              <line x1={sToX(playheadS)} x2={sToX(playheadS)} y1={0} y2={RULER_H}
                stroke="#fff" strokeWidth={1.5} opacity={0.9} />
              <g onPointerDown={dragTrigger} style={{ cursor: 'ew-resize' }}>
                <line x1={sToX(triggerMarkS)} x2={sToX(triggerMarkS)} y1={0} y2={RULER_H}
                  stroke="#ff5a3c" strokeWidth={2} />
                <polygon points={`${sToX(triggerMarkS) - 6},0 ${sToX(triggerMarkS) + 6},0 ${sToX(triggerMarkS)},10`}
                  fill="#ff5a3c" />
                <text x={sToX(triggerMarkS)} y={RULER_H - 24} fontSize={9} fill="#ff5a3c" textAnchor="middle">
                  trigger
                </text>
              </g>
            </svg>

            <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, marginTop: 4 }}>
              <button onClick={() => setPlaying((p) => !p)}>{playing ? '⏸ Pause' : '▶ Play'}</button>
              <span style={{ color: 'var(--text-muted)' }}>↻ loops at {fmtS(durationS)}</span>
              <button onClick={() => setDurationS((d) => Math.min(MAX_DURATION_S, d + EXTEND_STEP_S))}
                disabled={durationS >= MAX_DURATION_S}>
                ⇥ Extend +{EXTEND_STEP_S}s
              </button>
              <span style={{ marginLeft: 'auto', color: 'var(--text-muted)' }}>
                playhead {fmtS(playheadS)}
              </span>
            </div>

            {animStartAbs != null && (
              <div style={{ fontSize: 12, marginTop: 6, padding: '6px 8px', borderRadius: 6,
                            background: 'var(--panel-bg, #1a1024)' }}>
                Trigger is <strong>{gapMs === 0 ? 'exactly on' : `${Math.abs(gapMs)}ms ${gapMs > 0 ? 'after' : 'before'}`}</strong>{' '}
                where this kind's animation actually starts moving
                {animEndAbs != null && <> — the visible effect runs for {fmtMs(animEndAbs - animStartAbs)} total</>}.
                Drag the trigger line to test a different alignment; it saves onto this kind's
                own trigger_offset_ms (Save the scene to keep it).
              </div>
            )}

            {timeline.writes.length > 0 && (
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
                {timeline.writes.map((w) => (
                  <div key={w.seq}>
                    +{fmtMs(w.at_s)} — {writeLabel(w)}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
