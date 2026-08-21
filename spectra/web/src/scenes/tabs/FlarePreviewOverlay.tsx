/** The flare scrubbing-preview timeline (owner ask, flares first —
 * data/timeline-preview-scrub-flares-and-drop-sequences/HIS-VERBATIM-
 * WORDS.md), a TRUE SIMULATION (owner correction 2026-08-21, data/
 * preview-loops-and-fires-on-the-trigger — spectra/services/
 * flare_preview_hold.py's own docstring has the full history). Opened
 * from a "▶ Preview" button on a flare kind card (ResponseTab.tsx). Open
 * computes a deterministic write timeline for this ONE kind (spectra/
 * services/flare_preview.py, still hardware-free — the ruler/scrub/loop
 * below plays this locally, no repeated backend calls per frame) — that
 * alone never touches his fixtures. The LIVE fire is a separate call
 * (fireFlarePreview), issued by the playhead effect below once per loop,
 * timed to land exactly when the simulated playhead crosses
 * `fire_at_s` — never on open, and every lap, not once: "it should happen
 * every time... with the same timing as if the playhead was crossing a
 * trigger." fire_at_s (2026-08-21, fm/preview-must-hold-scene-changes) is
 * NOT animation_anchor_s: it's animation_anchor_s adjusted by this kind's
 * own automatic lead (scene_response.kind_lead_ms — the SAME lead a real
 * trigger fire would compute, never a hardcoded number), so the preview
 * fires at the same real-time moment production would, per his own ask —
 * "the same lead the real show applies must apply here, or the preview
 * lies about when his flare lands." Closing (or losing the tab/connection
 * — see the heartbeat block below) reverts his room to exactly what it
 * showed before the preview opened.
 *
 * Two independent marker kinds, per his brief:
 *   - the TRIGGER mark (draggable) — where he considers this kind
 *     "fired." Dragging it writes SceneV2.flare_kinds[].trigger_offset_ms
 *     via onTriggerOffsetChange, HIS sign convention (negative = fires
 *     earlier, positive = later, 0 = coincident — see FlareKind.
 *     trigger_offset_ms's own docstring, spectra/models/scene.py, for the
 *     full ruling) — this is a real scene-draft EDIT, saved by the page's
 *     own Save button like any other field, not a preview-only,
 *     forgotten-on-close exploration.
 *   - the ANIMATION START/END markers (fixed, computed) — read straight
 *     off the real production timing constants (DICE_REROLL_GLIDE_MS,
 *     hold_ms, PULSE_RELEASE_S, GAIN_GLIDE_S, the colour-jump ramp). This
 *     is the instrument for his "explosion starts early" complaint: the
 *     gap readout below the ruler states, in milliseconds, how far the
 *     trigger sits from where the effect actually starts moving.
 *
 * animAnchorS/triggerMarkS/fireAtS below are read straight off the
 * backend's own `animation_anchor_s`/`trigger_mark_s`/`fire_at_s`
 * (spectra/services/flare_preview.py) rather than re-derived client-side —
 * ONE source of truth: the ruler draw and the live-fire loop's real-time
 * schedule can never silently disagree on where the animation starts or
 * when the write actually fires (fire_at_s, animAnchorS adjusted by this
 * kind's own automatic lead — see FlarePreviewTimeline.fire_at_s's own
 * docstring, spectra/web/src/queries.ts).
 *
 * "Automatically pauses the trigger engine": /flare-preview/open arms
 * preview_pause for as long as this overlay stays mounted, kept alive by
 * a heartbeat (server timeout is generous — a missed beat or two doesn't
 * un-pause under it) and explicitly released on close/unmount/tab-close.
 * Since the loop below issues real fires, the SAME heartbeat also keeps
 * the live hold's own server-side revert timer armed — a lapsed heartbeat
 * (closed browser, dropped connection) reverts his room automatically,
 * not just un-pauses the trigger engine.
 *
 * MAXIMUM HOLD CEILING (2026-08-21): the server also enforces an ABSOLUTE
 * cap on one continuous hold (spectra/services/flare_preview_hold.py,
 * MAX_HOLD_DURATION_S = 180s) that heartbeats/re-fires can never push
 * back out — his room was once held 13m54s by a client that never
 * stopped heartbeating. Once that ceiling fires, /fire and /heartbeat
 * both start coming back with `expired: true` — the loop below stops
 * itself and shows exactly why, rather than silently continuing to poll
 * a room that has already released itself. */
import { useEffect, useRef, useState } from 'react';
import HelpLink from '../../help/HelpLink';
import {
  closeFlarePreview, closeFlarePreviewBeacon, fireFlarePreview, heartbeatFlarePreview,
  openFlarePreview,
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
  // Set once the server's absolute MAX_HOLD_DURATION_S ceiling has fired
  // and released the room on its own (see the module docstring above) —
  // distinct from `error` so it reads as "the preview let go on its own,"
  // not a failure. Stops the fire loop (setPlaying(false)) so it doesn't
  // keep polling a room the server has already stopped holding.
  const [holdExpired, setHoldExpired] = useState(false);
  const onHoldExpired = () => { setHoldExpired(true); setPlaying(false); };
  const [durationS, setDurationS] = useState(6.0);
  const [animAnchorS, setAnimAnchorS] = useState(2.0);
  const [fireAtS, setFireAtS] = useState(2.0);
  const [triggerMarkS, setTriggerMarkS] = useState(2.0 - kind.trigger_offset_ms / 1000);
  const [playheadS, setPlayheadS] = useState(0);
  const [playing, setPlaying] = useState(true);
  const rulerRef = useRef<SVGSVGElement | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastFrameRef = useRef<number | null>(null);
  const initializedMarksRef = useRef(false);
  // Mirrors playheadS for the fire-loop effect below to read synchronously
  // (that effect deliberately does NOT depend on playheadS itself — doing
  // so would restart the RAF loop, and therefore the fire schedule, on
  // every single frame). Kept in sync everywhere playheadS is set.
  const playheadRef = useRef(0);
  // The real-time deadline (performance.now() domain) for the NEXT live
  // fire — recomputed from playheadRef whenever the loop (re)starts, so it
  // never drifts out of sync with what's drawn (see the effect below).
  const nextFireAtRef = useRef<number | null>(null);
  // Read by the fire loop without needing to be a RAF-effect dependency —
  // an intensity slider drag must not restart the loop/fire schedule on
  // every tick, only the debounced timeline-refetch effect below does that.
  const fireParamsRef = useRef({ sceneId, kindName: kind.name, intensity });
  useEffect(() => {
    fireParamsRef.current = { sceneId, kindName: kind.name, intensity };
  }, [sceneId, kind.name, intensity]);

  // ── fetch a fresh (dark) timeline whenever intensity changes (debounced)
  // — also (re)arms preview_pause on the server. NEVER fires live here —
  // his report was that the live fire used to happen "almost as soon as
  // the preview started" instead of waiting for the mark, so even the
  // FIRST fire (not just subsequent loops) now waits for the playhead to
  // reach fireAtS. An intensity change restarts the playhead at 0 and
  // clears the fire schedule, so the next fire (at the new intensity)
  // waits for the mark exactly like a fresh open, rather than firing
  // immediately at the slider's new position. ────────────────────────────
  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      openFlarePreview(sceneId, kind.name, intensity)
        .then((tl) => {
          if (cancelled) return;
          setTimeline(tl);
          setError(null);
          setHoldExpired(false);
          setAnimAnchorS(tl.animation_anchor_s);
          setFireAtS(tl.fire_at_s);
          setDurationS((prev) => (initializedMarksRef.current ? Math.max(prev, tl.duration_s) : tl.duration_s));
          if (!initializedMarksRef.current) {
            setTriggerMarkS(tl.trigger_mark_s);
            initializedMarksRef.current = true;
          }
          setPlayheadS(0);
          playheadRef.current = 0;
          nextFireAtRef.current = null;
        })
        .catch((e) => !cancelled && setError(String(e)));
    }, 200);
    return () => { cancelled = true; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sceneId, kind.name, intensity]);

  // ── heartbeat + release-on-close (auto-pauses the trigger engine for
  // as long as this overlay is open) ────────────────────────────────────
  useEffect(() => {
    const iv = setInterval(() => {
      void heartbeatFlarePreview().then((res) => {
        if (res.expired) onHoldExpired();
      });
    }, HEARTBEAT_MS);
    const onBeforeUnload = () => closeFlarePreviewBeacon();
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => {
      clearInterval(iv);
      window.removeEventListener('beforeunload', onBeforeUnload);
      void closeFlarePreview();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── play/loop: advance the playhead in real time, wrap at durationS, AND
  // fire the kind live for real exactly when the playhead crosses
  // fireAtS (animAnchorS adjusted by this kind's own automatic lead — see
  // fire_at_s's own docstring, spectra/services/flare_preview.py) — every
  // lap, not once on open, "the same timing as if the playhead was
  // crossing a trigger." The next-fire deadline is derived fresh from the
  // CURRENT playhead position every time this effect (re)starts
  // (pause/resume, an Extend, a fresh timeline after an intensity change)
  // rather than carried across restarts, so it can never drift out of
  // phase with what's drawn. Pausing/scrubbing stops the fire loop too
  // (scrubRuler below sets playing=false), matching "scrubbing never sends
  // anything further to your fixtures." fireAtS can be negative or exceed
  // durationS (a lead longer than the gap to the ruler's own front edge) —
  // normalize into [0, durationS) first so the wraparound below is always
  // correct, never assume it already sits inside the ruler. ─────────────
  useEffect(() => {
    if (!playing || !timeline) { lastFrameRef.current = null; return undefined; }
    const normalizedFireAtS = ((fireAtS % durationS) + durationS) % durationS;
    const delayToFireS = normalizedFireAtS >= playheadRef.current
      ? normalizedFireAtS - playheadRef.current
      : durationS - playheadRef.current + normalizedFireAtS;
    nextFireAtRef.current = performance.now() + delayToFireS * 1000;
    const fireLive = () => {
      const { sceneId: sid, kindName, intensity: it } = fireParamsRef.current;
      fireFlarePreview(sid, kindName, it)
        .then((res) => { if (res.expired) onHoldExpired(); })
        .catch((e) => setError(String(e)));
    };
    const step = (now: number) => {
      if (lastFrameRef.current != null) {
        const dt = (now - lastFrameRef.current) / 1000;
        setPlayheadS((prev) => {
          const next = prev + dt;
          const wrapped = next >= durationS ? next % durationS : next;
          playheadRef.current = wrapped;
          return wrapped;
        });
      }
      lastFrameRef.current = now;
      if (nextFireAtRef.current != null && now >= nextFireAtRef.current) {
        fireLive();
        // advance by whole periods (never a burst of catch-up fires if a
        // backgrounded tab caused a huge single dt)
        while (nextFireAtRef.current <= now) nextFireAtRef.current += durationS * 1000;
      }
      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      lastFrameRef.current = null;
    };
  }, [playing, durationS, fireAtS, timeline]);

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
      // HIS sign convention (ruling 2026-08-21): negative offset = fire
      // earlier (mark right of anchor), positive = later (mark left) —
      // offset = animAnchorS - markS. Mirrors flare_preview.trigger_mark_s
      // (spectra/services/flare_preview.py), which computes the inverse.
      onTriggerOffsetChange(Math.round((animAnchorS - s) * 1000));
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const scrubRuler = (e: React.PointerEvent) => {
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    setPlaying(false);
    const s0 = xToS(e.clientX);
    setPlayheadS(s0);
    playheadRef.current = s0;
    const move = (ev: PointerEvent) => {
      const s = xToS(ev.clientX);
      setPlayheadS(s);
      playheadRef.current = s;
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  // The accent "start"/"end" lines represent when the write actually
  // lands — that's fireAtS now (animAnchorS adjusted by this kind's own
  // automatic lead), not animAnchorS itself, so they stay honest about
  // when the real live /fire call goes out. animation_start_s is always
  // exactly 0 (every recorded write is normalized to its own earliest
  // write), so animStartAbs === fireAtS whenever there are any writes.
  const gapMs = Math.round((triggerMarkS - fireAtS) * 1000);
  const animStartAbs = timeline?.animation_start_s != null ? fireAtS + timeline.animation_start_s : null;
  const animEndAbs = timeline?.animation_end_s != null ? fireAtS + timeline.animation_end_s : null;
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

        {holdExpired && (
          <div style={{ fontSize: 12, padding: '6px 8px', borderRadius: 6, marginBottom: 4,
                        background: 'var(--accent)', color: '#1a1024' }}>
            ⏱ This preview reached its maximum hold time and let go of your room on its
            own — your show has resumed. Close and reopen to look again.
          </div>
        )}
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
              <span style={{ color: 'var(--text-muted)' }}>
                ↻ loops & re-fires live every {fmtS(durationS)} — pausing stops both
              </span>
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
                own trigger_offset_ms (Save the scene to keep it) — drag it right to fire
                earlier (negative), left to fire later (positive). The live fire waits for the
                white playhead to reach the accent-coloured "start" line before it fires, every
                loop{timeline?.lead_ms ? <> — {timeline.lead_ms}ms earlier than the trigger mark
                itself, the same automatic lead a real trigger fire would apply for this kind</> : null}.
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
