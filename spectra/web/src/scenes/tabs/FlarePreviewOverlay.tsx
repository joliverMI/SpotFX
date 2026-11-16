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
 * THE WORD SHAPE KIND (Word Shapes row W2.1) draws its own three marks
 * instead of the start/end pair above, from the SAME server numbers: the
 * write at `fire_at_s` (a form before the word), the TRIGGER mark on the
 * word itself, and the hold + release past it, read off the timeline's
 * `word_shape` envelope (wordShapePreview.wordShapeMarks). Two deliberate
 * differences from every other kind:
 *   - the spans are read from the ENVELOPE, not from the writes, because a
 *     shape produces no writes at all until wave 1 wires an effect into
 *     fx.device_model.WORD_SHAPE_EFFECTS — the shape's timing is the
 *     ROOM's, not the fixture's, so the ruler must tell him the truth
 *     about it either way (flare_preview.word_shape_effect_ms's reasoning);
 *   - the trigger mark DOES NOT DRAG. The Words section fires its band
 *     atomically, so a per-kind `trigger_offset_ms` never moves the real
 *     fire (scene_response.on_word_shape; the save warns about one, and
 *     flare_preview forces the drawn offset to 0 for this type). A
 *     draggable mark here would author a number the engine ignores.
 * The SHAPE PICKER beside the Energy slider reads its options from the
 * shape library itself (GET /api/sung-labels' `shapes` rows — never three
 * hard-coded ids) and re-opens the timeline on a change, carrying the
 * choice into the live fire too so the room draws what the ruler draws.
 *
 * MAXIMUM HOLD CEILING (2026-08-21): the server also enforces an ABSOLUTE
 * cap on one continuous hold (spectra/services/flare_preview_hold.py,
 * MAX_HOLD_DURATION_S = 180s) that heartbeats/re-fires can never push
 * back out — his room was once held 13m54s by a client that never
 * stopped heartbeating. Once that ceiling fires, /fire and /heartbeat
 * both start coming back with `expired: true` — the loop below stops
 * itself and shows exactly why, rather than silently continuing to poll
 * a room that has already released itself. */
import { useEffect, useMemo, useRef, useState } from 'react';
import HelpLink from '../../help/HelpLink';
import {
  closeFlarePreview, closeFlarePreviewBeacon, fireFlarePreview, heartbeatFlarePreview,
  openFlarePreview, useSungLabels,
} from '../../queries';
import type { FlarePreviewTimeline, FlarePreviewWrite } from '../../queries';
import type { FlareKind } from '../../types';
import {
  PREFERRED_PREVIEW_SHAPE, pickDefaultShape, shapePickerOptions, wordShapeMarks,
  wordShapeSentence,
} from './wordShapePreview';

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
  // THE SHAPE PICKER (Word Shapes row W2.1). Only a `word_shape` kind has
  // one; every other type sends no shape and the server ignores the field.
  // The options come from the shape LIBRARY (fx/effects/word_shapes.py via
  // GET /api/sung-labels' `shapes`), so a shape added there appears here
  // with no frontend change — the three ids are never written down.
  const isWordShape = kind.type === 'word_shape';
  const { data: sungLabels } = useSungLabels(isWordShape);
  const shapeOptions = useMemo(
    () => shapePickerOptions(sungLabels?.shapes), [sungLabels]);
  const [shape, setShape] = useState<string | null>(
    isWordShape ? PREFERRED_PREVIEW_SHAPE : null);
  // Heart is preselected and is also the server's own default, so the
  // first /open needs no library read. This only corrects a choice the
  // library does not actually have (a renamed or removed shape).
  useEffect(() => {
    if (!isWordShape || !shapeOptions.length) return;
    setShape((prev) => (prev && shapeOptions.some((o) => o.id === prev)
      ? prev : pickDefaultShape(shapeOptions)));
  }, [isWordShape, shapeOptions]);
  const [timeline, setTimeline] = useState<FlarePreviewTimeline | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Set once the server's absolute MAX_HOLD_DURATION_S ceiling has fired
  // and released the room on its own (see the module docstring above) —
  // distinct from `error` so it reads as "the preview let go on its own,"
  // not a failure. Stops the fire loop (setPlaying(false)) so it doesn't
  // keep polling a room the server has already stopped holding.
  const [holdExpired, setHoldExpired] = useState(false);
  // Ref twin of holdExpired for the timeline-refetch .then below — that
  // closure's own state value can be stale by the time the fetch resolves
  // (the debounce + network sit between them), and it must know whether the
  // loop was stopped by the CEILING (revive it — the /open it just made
  // cleared the server's ceiling lock and began a genuine new session) or
  // by his own ⏸ Pause (leave it paused — an intensity change while
  // deliberately paused must never restart the live firing).
  const holdExpiredRef = useRef(false);
  const onHoldExpired = () => {
    holdExpiredRef.current = true;
    setHoldExpired(true);
    setPlaying(false);
  };
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
  const fireParamsRef = useRef<{ sceneId: string; kindName: string; intensity: number;
                                 shape: string | null }>(
    { sceneId, kindName: kind.name, intensity, shape });
  useEffect(() => {
    fireParamsRef.current = { sceneId, kindName: kind.name, intensity, shape };
  }, [sceneId, kind.name, intensity, shape]);

  // ── fetch a fresh (dark) timeline whenever the intensity — or, for a
  // word shape, the picked shape — changes (debounced)
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
      openFlarePreview(sceneId, kind.name, intensity, shape)
        .then((tl) => {
          if (cancelled) return;
          setTimeline(tl);
          setError(null);
          if (holdExpiredRef.current) {
            // The 3-minute ceiling stopped the loop; this /open just began
            // a genuine new session server-side (clear_ceiling_lock — "a
            // real mount, or him moving the intensity slider"). Without
            // this the banner cleared but `playing` stayed false: playhead
            // frozen at 0, nothing ever fired again until a manual ▶ Play.
            holdExpiredRef.current = false;
            setPlaying(true);
          }
          setHoldExpired(false);
          setAnimAnchorS(tl.animation_anchor_s);
          setFireAtS(tl.fire_at_s);
          // A word shape's envelope can run past the server's own
          // duration_s (which is the bare minimum when the kind produced
          // no writes), so the ruler grows to hold the whole form + hold +
          // release — the same widening "⇥ Extend" does, never a second
          // source for the moments themselves.
          const needed = Math.max(tl.duration_s, wordShapeMarks(tl)?.needed_duration_s ?? 0);
          setDurationS((prev) => (initializedMarksRef.current ? Math.max(prev, needed) : needed));
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
  }, [sceneId, kind.name, intensity, shape]);

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
      const { sceneId: sid, kindName, intensity: it, shape: sh } = fireParamsRef.current;
      fireFlarePreview(sid, kindName, it, sh)
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
  //
  // THE WORD SHAPE's own marks (null for every other kind) — read off the
  // server's envelope, so the three spans and the "the word" mark cannot
  // disagree with the write.
  const marks = wordShapeMarks(timeline);
  const shapeName = shapeOptions.find((o) => o.id === marks?.shape)?.name;
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
          <span style={{ color: 'var(--text-muted)' }}>Energy</span>
          <input type="range" min={0} max={1} step={0.01} value={intensity}
            onChange={(e) => setIntensity(Number(e.target.value))} style={{ flex: 1 }} />
          <span style={{ fontVariantNumeric: 'tabular-nums', width: 36 }}>{intensity.toFixed(2)}</span>
        </label>

        {isWordShape && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12,
                        margin: '0 0 8px', flexWrap: 'wrap' }}>
            <span style={{ color: 'var(--text-muted)' }}>Shape</span>
            {shapeOptions.length === 0 ? (
              <span style={{ color: 'var(--text-muted)' }}>
                reading the shape library…
              </span>
            ) : shapeOptions.map((o) => (
              <button key={o.id} className={o.id === shape ? 'primary' : ''}
                style={{ fontSize: 12, padding: '3px 10px' }}
                title={`Draw ${o.name} — the preview re-opens and the live fire draws this shape`}
                onClick={() => setShape(o.id)}>
                {o.name}
              </button>
            ))}
            <HelpLink topic="word-shapes" title="Word shapes" />
          </div>
        )}

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

        {/* An explicit press always wins — but he is told he is looking at a
            flare his own bands will never fire (models/scene.py
            FlareKind.enabled; the Force-Scene precedent). */}
        {timeline?.overrode_disabled && (
          <div style={{ fontSize: 12, color: 'var(--warning)' }}>
            ⚠ This flare is switched OFF — it never fires automatically. Previewing it
            anyway (an explicit press always wins); tap its power button to turn it
            back on.
          </div>
        )}

        {timeline && timeline.writes.length === 0 && marks && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Nothing in your room draws shapes yet — no live effect in this scene is one that
            knows them, so this fires no writes. The ruler below is still the real timing:
            it is the room's own Word shape settings, not a fixture's.
          </div>
        )}

        {timeline && timeline.writes.length === 0 && !marks && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            This kind produces no writes at this intensity — {timeline.result === 'no_visible_effect'
              ? 'its params don\'t match any live virtual\'s registered params (or its gain is 1.0 with no params at all).'
              : timeline.result === 'below_min_intensity'
                ? `it only fires above Energy ${kind.min_intensity ?? '?'}; raise the Energy slider to see it.`
                : `result: ${timeline.result}.`}
          </div>
        )}

        {timeline && (
          <>
            <svg ref={rulerRef} viewBox={`0 0 ${RULER_W} ${RULER_H}`}
              style={{ width: '100%', height: RULER_H, touchAction: 'none', cursor: 'pointer' }}
              onPointerDown={scrubRuler}>
              <rect x={0} y={0} width={RULER_W} height={RULER_H} fill="var(--panel-bg, #1a1024)" />
              {animStartAbs != null && animEndAbs != null && !marks && (
                <rect x={sToX(animStartAbs)} y={20} width={Math.max(1, sToX(animEndAbs) - sToX(animStartAbs))}
                  height={RULER_H - 40} fill="var(--accent)" opacity={0.18} />
              )}
              {/* A WORD SHAPE's three spans, in his words: it forms, it
                  holds, it releases. Brightest while it forms, because that
                  is the stretch the whole design is about — it ends ON the
                  word. */}
              {marks?.spans.map((span, i) => (
                <g key={span.label}>
                  <rect x={sToX(span.from_s)} y={20}
                    width={Math.max(1, sToX(span.to_s) - sToX(span.from_s))}
                    height={RULER_H - 40} fill="var(--accent)"
                    opacity={[0.28, 0.17, 0.09][i] ?? 0.12} />
                  <text x={(sToX(span.from_s) + sToX(span.to_s)) / 2} y={12} fontSize={9}
                    fill="var(--accent)" textAnchor="middle">{span.label}</text>
                </g>
              ))}
              {ticks.map((t) => (
                <g key={t}>
                  <line x1={sToX(t)} x2={sToX(t)} y1={RULER_H - 18} y2={RULER_H - 12} stroke="var(--text-muted)" />
                  <text x={sToX(t)} y={RULER_H - 2} fontSize={9} fill="var(--text-muted)" textAnchor="middle">
                    {t}s
                  </text>
                </g>
              ))}
              {animStartAbs != null && !marks && (
                <g>
                  <line x1={sToX(animStartAbs)} x2={sToX(animStartAbs)} y1={16} y2={RULER_H - 20}
                    stroke="var(--accent)" strokeWidth={2} />
                  <text x={sToX(animStartAbs)} y={12} fontSize={9} fill="var(--accent)" textAnchor="middle">start</text>
                </g>
              )}
              {animEndAbs != null && !marks && (
                <g>
                  <line x1={sToX(animEndAbs)} x2={sToX(animEndAbs)} y1={16} y2={RULER_H - 20}
                    stroke="var(--accent)" strokeWidth={2} strokeDasharray="3,2" />
                  <text x={sToX(animEndAbs)} y={12} fontSize={9} fill="var(--accent)" textAnchor="middle">end</text>
                </g>
              )}
              {marks && (
                <g>
                  <line x1={sToX(marks.start_s)} x2={sToX(marks.start_s)} y1={16} y2={RULER_H - 20}
                    stroke="var(--accent)" strokeWidth={2} />
                  <line x1={sToX(marks.end_s)} x2={sToX(marks.end_s)} y1={16} y2={RULER_H - 20}
                    stroke="var(--accent)" strokeWidth={2} strokeDasharray="3,2" />
                </g>
              )}
              <line x1={sToX(playheadS)} x2={sToX(playheadS)} y1={0} y2={RULER_H}
                stroke="#fff" strokeWidth={1.5} opacity={0.9} />
              {/* THE WORD does not drag (see the module docstring): the
                  Words section fires its band atomically, so an authored
                  offset would be a number the engine ignores. Every other
                  kind's trigger mark is the draggable alignment tool it has
                  always been. */}
              <g onPointerDown={marks ? undefined : dragTrigger}
                style={{ cursor: marks ? 'default' : 'ew-resize' }}>
                <line x1={sToX(triggerMarkS)} x2={sToX(triggerMarkS)} y1={0} y2={RULER_H}
                  stroke="#ff5a3c" strokeWidth={2} />
                {!marks && (
                  <polygon points={`${sToX(triggerMarkS) - 6},0 ${sToX(triggerMarkS) + 6},0 ${sToX(triggerMarkS)},10`}
                    fill="#ff5a3c" />
                )}
                <text x={sToX(triggerMarkS)} y={RULER_H - 24} fontSize={9} fill="#ff5a3c" textAnchor="middle">
                  {marks ? 'the word' : 'trigger'}
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

            {marks && (
              <div style={{ fontSize: 12, marginTop: 6, padding: '6px 8px', borderRadius: 6,
                            background: 'var(--panel-bg, #1a1024)' }}>
                {wordShapeSentence(marks, shapeName)} The forming time <strong>IS</strong> the
                lead: the band fires {Math.round(marks.form_s * 1000)} ms early so the shape
                stands complete on the word, and the live fire waits for the white playhead to
                reach the left edge of “forms”, every loop. The red line is the word itself and
                does not drag — a Words band fires on the word, so a per-kind trigger offset is
                not applied there (save the scene and it says so). Only a sung word fires this
                in your show; nothing here is a trigger.
              </div>
            )}

            {animStartAbs != null && !marks && (
              <div style={{ fontSize: 12, marginTop: 6, padding: '6px 8px', borderRadius: 6,
                            background: 'var(--panel-bg, #1a1024)' }}>
                Trigger is <strong>{gapMs === 0 ? 'exactly on' : `${Math.abs(gapMs)}ms ${gapMs > 0 ? 'after' : 'before'}`}</strong>{' '}
                where this kind's animation actually starts moving
                {animEndAbs != null && <> — the visible effect runs for {fmtMs(animEndAbs - animStartAbs)} total</>}.
                Drag the trigger line to test a different alignment; it saves onto this kind's
                own trigger_offset_ms (Save the scene to keep it) — drag it right to fire
                earlier (negative), left to fire later (positive). Once saved, your real song
                triggers fire this flare by the same offset — the drag retimes your show, not
                just this preview. The live fire waits for the
                white playhead to reach the accent-coloured "start" line before it fires, every
                loop{timeline?.lead_ms ? <> — {timeline.lead_ms}ms earlier than the trigger mark
                itself, the same automatic lead a real trigger fire would apply for this kind</> : null}.
                {timeline?.anchor_rule === 'drop_start' && (
                  <> <br />
                    <strong>Drop rule:</strong> this kind is attached only to a <b>drop</b> band, so
                    it <b>begins</b> on the trigger mark and never fires early — no lead, whatever
                    its params would otherwise need. That is the settled anchor for an explosion.
                  </>
                )}
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
