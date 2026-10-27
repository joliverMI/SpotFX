/** The CHARGE / LULL / DROP SEQUENCE scrubbing preview (2026-08-27,
 * fm/flare-preview-offsets-everywhere) — the second half he deferred with
 * "start with the flares, then we will do lull charge drop". Opened from
 * the Phase tab.
 *
 * WHAT THE RULER SHOWS, and why the gap sliders are the control that
 * matters. Each class's ramp is production's own (scene_response.
 * _phase_ramp_ms), which since 2026-08-20 STRETCHES a charge or lull to
 * ~90% of the real gap to its own lull or drop (the PHASE PARTNER rule,
 * spectra/services/phase_partner.py — nothing else ever sits between the
 * marks on this ruler) and hangs the remaining ~10%.
 * That hang is his own spec — "the single blob waiting in lull should
 * reach the center just and hang for just a moment, maybe 10% of the lull
 * time, before the explosion" — and a number in a form could never show
 * it. So the ruler draws ramp and hang as separate bands, and the two
 * sliders set the gaps those ramps stretch to fill. The DROP is never
 * stretched and BEGINS on its mark: the settled start anchor.
 *
 * THE DROP'S RED LINE IS DRAGGABLE (2026-10-12, the Admiral: "I wanted to
 * be able to edit red line for the drop in the preview drop sequence page
 * for a scene, but I cannot click it and drag it"). It sets THIS SCENE's
 * drop timing (SceneV2.drop_timing_offset_ms, spectra/services/
 * drop_timing.py — negative = the drop fires earlier), measured from the
 * music's own drop mark (the faint dashed line). It is a scene-draft edit
 * like the transition preview's trigger mark: the preview shows the draft
 * at once (the request carries it), and the Scenes page's Save keeps it.
 * For a crowded ruler and a tablet: a handle in its own lane under the
 * ruler, a grab strip on the line, snapping (10 ms; on the mark and the
 * room's value pull), and −50/−10/+10/+50 ms buttons plus "Use the room's"
 * for when a finger is not precise enough — see PreviewRuler's dragMark
 * and dropMarkDrag.ts.
 *
 * THE OTHER MARKS ARE NOT DRAGGABLE HERE, deliberately. Each mark is its band's
 * ANCHOR, an aggregate over however many flare kinds it attaches (min over
 * every enabled kind's offset, zero included), while every kind keeps its
 * own offset and lands at it relative to that anchor (scene_response's
 * "PER-FLARE TRIGGER MOMENT") — so a drag would have to pick one kind to write it to, and
 * picking would be invention. The place a kind's own offset is authored
 * already exists and is per-kind by construction: the flare preview's own
 * marker. This preview SHOWS where each class's fire begins, so the ruler
 * still tells the truth about where the show will fire.
 *
 * THE DROP-LED SCENE SWITCH (spectra/services/drop_switch.py): the preview
 * runs the room's own resolver for this scene as if it had grown stale, and
 * — with "Show the drop switch" on — performs the cut it would make, live,
 * on the same hold: a hard cut on the drop (or, early, at the charge) into
 * the scene it names, the lull told what is coming. The cut's moment is the
 * server's cut_s.
 *
 * THE PRE-DROP (predrop plan step 5): a kind switch (Off / Spike / Vocal
 * intro) and a gap slider held inside this scene's DRAFT window for that
 * kind try a pre-drop against the scene. The request carries the draft's
 * windows and every entry's looks (the drop timing's own overlay rule), the
 * server says whether the scene plays it, and the ruler draws it orange at
 * the server's mark_s — dashed when this scene would not play it.
 *
 * Every time here is server-computed (marks[].mark_s / fire_at_s /
 * ramp_*_s, cues[].at_s); this file derives none of them. */
import { useEffect, useState } from 'react';
import Icon from '../../components/Icon';
import HelpLink from '../../help/HelpLink';
import {
  closeFlarePreview, closeFlarePreviewBeacon, fireSequencePreview, openSequencePreview,
  useRegistry, useScenes,
} from '../../queries';
import type { PhasePreviewTimeline } from '../../queries';
import { PRE_DROP_COLOR, PRE_DROP_KIND_NAME, type PreDropKind } from '../../timeline/dropSequences';
import type { SceneV2 } from '../../types';
import PreviewRuler from './PreviewRuler';
import type { RulerBand, RulerDragMark, RulerMark } from './PreviewRuler';
import {
  NUDGE_BIG_MS, NUDGE_SMALL_MS, NUDGE_STEPS, appliedOffsetMs, dragToOffset, effectiveOffsetMs,
  markSForOffset, nudgeOffsetMs, offsetWords, signedMs,
} from './dropMarkDrag';
import { useCueLoop, useHeartbeat } from './usePreviewLoop';
import { programBands } from './programStages';
import {
  DEFAULT_PREVIEW_GAP_MS, KIND_ICON, clampGap, kindMeta, preDropSentence, previewPreDropRequest,
  windowFor,
} from './preDropWindows';

const DEFAULT_CHARGE_GAP_MS = 4444;   // phase_preview.DEFAULT_GAP_MS
const DEFAULT_LULL_GAP_MS = 2778;

export default function SequencePreviewOverlay({ scene, onClose, onDropOffsetChange }: {
  scene: SceneV2;
  onClose: () => void;
  /** Write the scene draft's own drop timing (null = the room's). Absent =
   * the drop mark is drawn but cannot be moved. */
  onDropOffsetChange?: (ms: number | null) => void;
}) {
  // The scene DRAFT's own drop timing — what the preview shows and fires.
  const draftDropMs = scene.drop_timing_offset_ms ?? null;
  // While the drop mark is held: the offset it would set now.
  const [dropGhost, setDropGhost] = useState<{ ms: number; snappedTo: number | null } | null>(null);
  const { data: savedScenes } = useScenes();
  const savedDropMs = savedScenes?.find((s) => s.id === scene.id)?.drop_timing_offset_ms ?? null;
  const [intensity, setIntensity] = useState(1.0);
  const [chargeGapMs, setChargeGapMs] = useState(DEFAULT_CHARGE_GAP_MS);
  const [lullGapMs, setLullGapMs] = useState(DEFAULT_LULL_GAP_MS);
  const [dropSwitch, setDropSwitch] = useState(true);
  const [timeline, setTimeline] = useState<PhasePreviewTimeline | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { holdExpired, onHoldExpired, clearExpired } = useHeartbeat();
  // THE PRE-DROP to try: its kind (null = none) and, per kind, the gap the
  // slider last set — always read back clamped into the draft's window.
  const { data: registry } = useRegistry();
  const [preKind, setPreKind] = useState<PreDropKind | null>(null);
  const [preGaps, setPreGaps] = useState<Record<PreDropKind, number>>(DEFAULT_PREVIEW_GAP_MS);
  const preWin = windowFor(scene, preKind ?? 'spike', registry);
  const preGapMs = clampGap(preGaps[preKind ?? 'spike'], preWin);
  const preDrop = previewPreDropRequest(scene, preKind, preGapMs, registry);
  const preDropKey = JSON.stringify(preDrop);

  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      openSequencePreview(scene.id, intensity, chargeGapMs, lullGapMs, dropSwitch, draftDropMs, preDrop)
        .then((tl) => {
          if (cancelled) return;
          setTimeline(tl);
          setError(null);
          clearExpired();
        })
        .catch((e) => !cancelled && setError(String(e)));
    }, 200);
    return () => { cancelled = true; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene.id, intensity, chargeGapMs, lullGapMs, dropSwitch, draftDropMs, preDropKey]);

  const { playheadS, playing, setPlaying, scrubTo } = useCueLoop({
    timeline,
    fire: (step) => fireSequencePreview(scene.id, intensity, chargeGapMs, lullGapMs, step,
      dropSwitch, draftDropMs, preDrop)
      .then((res) => { if (res.expired) onHoldExpired(); })
      .catch((e) => setError(String(e))),
  });

  useEffect(() => () => { void closeFlarePreview(); }, []);
  useEffect(() => {
    const onBeforeUnload = () => closeFlarePreviewBeacon();
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, []);

  const bands: RulerBand[] = [];
  const marks: RulerMark[] = [];
  const info = timeline?.drop_timing ?? null;
  const dropMark = timeline?.marks.find((m) => m.event_class === 'drop') ?? null;
  const editable = !!onDropOffsetChange && dropMark?.music_mark_s != null;
  // The offset in force for the DRAFT (null = the room's) — what the line,
  // the handle and the buttons all speak about.
  const inForceMs = effectiveOffsetMs(draftDropMs, info);
  const shownMs = dropGhost?.ms ?? inForceMs;
  for (const m of timeline?.marks ?? []) {
    bands.push({ from_s: m.ramp_start_s, to_s: m.ramp_end_s,
                 label: `${m.event_class} ramp`, tone: 'accent' });
    if (m.hang_end_s > m.ramp_end_s) {
      bands.push({ from_s: m.ramp_end_s, to_s: m.hang_end_s,
                   label: 'hang', tone: 'muted' });
    }
    // the drop's line is the draggable one (drawn last, on top) when it can move
    if (m.event_class === 'drop' && editable) continue;
    marks.push({ at_s: m.mark_s, label: m.event_class, tone: 'hot' });
  }
  // The server's own mark once it has caught up with the draft; the same
  // mapping inverted (dropMarkDrag.markSForOffset) while held, or for the
  // moment between a release and the next timeline.
  const serverCaughtUp = !dropGhost && info != null && info.offset_ms === inForceMs;
  const dropLineS = dropMark == null ? 0
    : serverCaughtUp || dropMark.music_mark_s == null ? dropMark.mark_s
      : markSForOffset(shownMs, dropMark.music_mark_s, info);
  const setDropMs = (ms: number | null) => {
    setDropGhost(null);
    onDropOffsetChange?.(ms);
  };
  const dragMark: RulerDragMark | null = editable && dropMark ? {
    at_s: dropLineS,
    label: 'drop',
    readout: signedMs(shownMs),
    valueText: offsetWords(shownMs),
    title: 'Drag to retime this scene\'s drops — left fires earlier, right later. '
      + '←/→ steps 10 ms (Shift: 50 ms).',
    active: dropGhost != null,
    onDrag: (s) => setDropGhost(dragToOffset(s, dropMark.music_mark_s!, info)),
    onDragEnd: (s) => {
      const next = dragToOffset(s, dropMark.music_mark_s!, info);
      if (next.snappedTo != null && next.ms === info?.room_offset_ms && draftDropMs == null) {
        setDropGhost(null); // landed back on the room's — nothing to change
        return;
      }
      setDropMs(next.ms);
    },
    onDragCancel: () => setDropGhost(null),
    onStep: (dir, big) => setDropMs(nudgeOffsetMs(
      inForceMs, dir * (big ? NUDGE_BIG_MS : NUDGE_SMALL_MS), info)),
  } : null;
  const dropRef = editable && dropMark && shownMs !== 0
    ? { at_s: dropMark.music_mark_s!, label: 'mark' } : null;
  const sourceWord = draftDropMs != null ? "this scene's own" : "the room's";
  const appliedHere = appliedOffsetMs(shownMs, info);
  const sw = timeline?.drop_switch ?? null;
  if (sw?.switch && sw.cut_s != null) {
    marks.push({ at_s: sw.cut_s, label: `⇄ ${sw.to_scene_name ?? 'switch'}`, tone: 'accent' });
    // a cut that runs a thematic transition program: its stages from the
    // cut, muted under the phase bands they overlap
    bands.push(...programBands(sw.program, false));
  }
  const pre = timeline?.pre_drop ?? null;
  if (pre) {
    marks.push({ at_s: pre.mark_s, label: PRE_DROP_KIND_NAME[pre.kind], tone: 'predrop',
                 dashed: !pre.plays });
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)', zIndex: 300,
                  display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={onClose}>
      <div className="card" style={{ width: 'min(760px, 96vw)', maxHeight: '92vh', overflowY: 'auto' }}
        onClick={(e) => e.stopPropagation()}>
        <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          ▶ Preview drop sequence — {scene.name}
          <HelpLink topic="drop-sequence-preview-timeline" title="What the bands mean" />
          <button style={{ marginLeft: 'auto', fontSize: 12 }} onClick={onClose}>✕ Close</button>
        </div>

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, margin: '8px 0' }}>
          <span style={{ color: 'var(--text-muted)' }}>Intensity</span>
          <input type="range" min={0} max={1} step={0.01} value={intensity}
            onChange={(e) => setIntensity(Number(e.target.value))} style={{ flex: 1 }} />
          <span style={{ fontVariantNumeric: 'tabular-nums', width: 36 }}>{intensity.toFixed(2)}</span>
        </label>

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, margin: '4px 0' }}>
          <span style={{ color: 'var(--text-muted)', width: 110 }}>Charge → lull gap</span>
          <input type="range" min={400} max={12000} step={100} value={chargeGapMs}
            onChange={(e) => setChargeGapMs(Number(e.target.value))} style={{ flex: 1 }} />
          <span style={{ fontVariantNumeric: 'tabular-nums', width: 56 }}>{chargeGapMs} ms</span>
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, margin: '4px 0' }}>
          <span style={{ color: 'var(--text-muted)', width: 110 }}>Lull → drop gap</span>
          <input type="range" min={400} max={12000} step={100} value={lullGapMs}
            onChange={(e) => setLullGapMs(Number(e.target.value))} style={{ flex: 1 }} />
          <span style={{ fontVariantNumeric: 'tabular-nums', width: 56 }}>{lullGapMs} ms</span>
        </label>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, margin: '4px 0',
                      flexWrap: 'wrap' }}>
          <span style={{ color: 'var(--text-muted)', width: 110 }}>Pre-drop</span>
          <span role="group" aria-label="Pre-drop to try" style={{ display: 'inline-flex', gap: 4 }}>
            {([null, 'spike', 'intro'] as const).map((k) => {
              const on = preKind === k;
              return (
                <button key={k ?? 'off'} type="button" data-pre-drop-kind={k ?? 'off'} aria-pressed={on}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12,
                           borderColor: on ? PRE_DROP_COLOR : undefined,
                           color: on && k ? PRE_DROP_COLOR : undefined,
                           background: on ? 'rgba(251,146,60,0.14)' : undefined }}
                  title={k ? `Try a ${PRE_DROP_KIND_NAME[k]} before this drop` : 'No pre-drop'}
                  onClick={() => setPreKind(k)}>
                  {k && <Icon name={KIND_ICON[k]} size={14} />}
                  {k ? kindMeta(registry, k).label : 'Off'}
                </button>
              );
            })}
          </span>
          <HelpLink topic="pre-drop-scene-window" title="Pre-drops on this scene" />
        </div>
        {preKind && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, margin: '4px 0' }}>
            <span style={{ color: 'var(--text-muted)', width: 110 }}>Pre-drop → drop gap</span>
            <input type="range" data-testid="pre-drop-gap" min={preWin.min_ms} max={preWin.max_ms} step={10}
              value={preGapMs} style={{ flex: 1 }}
              onChange={(e) => setPreGaps({ ...preGaps, [preKind]: Number(e.target.value) })} />
            <span style={{ fontVariantNumeric: 'tabular-nums', width: 56 }}>{preGapMs} ms</span>
          </label>
        )}
        {pre && (
          <div data-testid="pre-drop-line" style={{ fontSize: 12, padding: '6px 8px', borderRadius: 6,
                        marginBottom: 4, background: 'var(--panel-bg, #1a1024)' }}>
            <b style={{ color: PRE_DROP_COLOR }}>Pre-drop:</b> {preDropSentence(pre)}
            {pre.member_lull && (
              <> The effects that play pre-drops build their lull to it over <b>{pre.member_lull.ramp_ms} ms</b>,
                holding their breath <b>{pre.member_lull.breath_s.toFixed(2)} s</b> right before it.</>
            )}
          </div>
        )}

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, margin: '4px 0' }}>
          <input type="checkbox" checked={dropSwitch}
            onChange={(e) => setDropSwitch(e.target.checked)} />
          <span>Show the drop switch — the scene change this drop would make once the scene has grown stale</span>
          <HelpLink topic="drop-led-switch" title="When a drop changes the scene" />
        </label>
        {sw && (
          <div style={{ fontSize: 12, padding: '6px 8px', borderRadius: 6, marginBottom: 4,
                        background: 'var(--panel-bg, #1a1024)' }}>
            <b>Drop switch:</b> {sw.sentence}
            {sw.switch && sw.lull_told && sw.moment === 'drop' && (
              <> The lull is told to leave {sw.lull_told.keep} piece{sw.lull_told.keep === 1 ? '' : 's'}
                {Object.keys(sw.lull_told.next).length > 0 && (
                  <> for {[...new Set(Object.values(sw.lull_told.next))].join(', ')}</>
                )}.</>
            )}
          </div>
        )}
        {holdExpired && (
          <div style={{ fontSize: 12, padding: '6px 8px', borderRadius: 6, marginBottom: 4,
                        background: 'var(--accent)', color: '#1a1024' }}>
            ⏱ This preview reached its maximum hold time and let go of your room on its
            own — your show has resumed. Close and reopen — or nudge a slider — to look again.
          </div>
        )}
        {error && <div style={{ color: 'var(--danger, #f66)', fontSize: 12 }}>{error}</div>}
        {!timeline && !error && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Computing…</div>}

        {timeline && timeline.phase_targets.length === 0 && (
          <div style={{ fontSize: 12, color: 'var(--danger, #f66)', padding: '6px 8px' }}>
            None of this scene's effects can be driven by charge/lull/drop, so this sequence
            would change nothing in your room. The ruler below still shows the timing this
            scene would use if it had a phase-capable effect.
          </div>
        )}

        {timeline && (
          <>
            <PreviewRuler
              durationS={timeline.duration_s}
              playheadS={playheadS}
              bands={bands}
              marks={marks}
              triggerMarkS={null}
              onScrub={scrubTo}
              dragMark={dragMark}
              dragRef={dropRef}
            />

            {editable && (
              <div className="drop-timing-row" data-testid="drop-timing-row"
                style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap',
                         fontSize: 12, marginTop: 6, padding: '6px 8px', borderRadius: 6,
                         background: 'var(--panel-bg, #1a1024)' }}>
                <span style={{ minWidth: 0 }}>
                  <b>Drop timing:</b>{' '}
                  <b data-testid="drop-timing-value" style={{ color: '#ff5a3c',
                    fontVariantNumeric: 'tabular-nums' }}>{signedMs(shownMs)}</b>{' '}
                  <span style={{ color: 'var(--text-muted)' }}>
                    ({offsetWords(shownMs)} — {dropGhost ? 'dragging' : sourceWord})
                  </span>
                  <HelpLink topic="drop-mark-drag" />
                </span>
                <span style={{ display: 'flex', gap: 4, marginLeft: 'auto', flexWrap: 'wrap' }}>
                  {NUDGE_STEPS.map((d) => (
                    <button key={d} className="drop-nudge-btn" data-nudge={d}
                      style={{ minHeight: 40, minWidth: 52, fontVariantNumeric: 'tabular-nums' }}
                      title={`Fire this scene's drops ${Math.abs(d)} ms ${d < 0 ? 'earlier' : 'later'}`}
                      onClick={() => setDropMs(nudgeOffsetMs(inForceMs, d, info))}>
                      {d < 0 ? '−' : '+'}{Math.abs(d)}
                    </button>
                  ))}
                  <button data-testid="drop-timing-reset" style={{ minHeight: 40 }}
                    disabled={draftDropMs == null}
                    title="Put this scene back on the room's drop timing (the Scenes panel in the top bar)"
                    onClick={() => setDropMs(null)}>
                    ↺ Room's{info?.room_offset_ms != null ? ` (${signedMs(info.room_offset_ms)})` : ''}
                  </button>
                </span>
                {appliedHere !== shownMs && (
                  <div style={{ flexBasis: '100%', color: 'var(--text-muted)' }}>
                    The lull is only {lullGapMs} ms ahead on this ruler, so the drop
                    can only move to {signedMs(appliedHere)} here — a real song's lull is further
                    back, where the full {signedMs(shownMs)} applies.
                  </div>
                )}
                {draftDropMs !== savedDropMs && (
                  <div data-testid="drop-timing-unsaved"
                    style={{ flexBasis: '100%', color: 'var(--accent2, var(--accent))' }}>
                    Not saved yet — press <b>Save</b> on the scene to keep it (the preview already
                    plays it).
                  </div>
                )}
              </div>
            )}

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
              {timeline.marks.map((m) => (
                <div key={m.event_class}>
                  <strong style={{ textTransform: 'capitalize' }}>{m.event_class}</strong>:{' '}
                  {m.stretched
                    ? <>ramps over <b>{m.ramp_ms} ms</b> ({Math.round((1 - timeline.hang_fraction) * 100)}%
                      of its {m.gap_ms} ms gap) then <b>hangs {m.hang_ms} ms</b> at full before the
                      next moment</>
                    : <>snaps over <b>{m.ramp_ms} ms</b> — a drop is never stretched</>}
                  {m.anchor_rule === 'drop_start'
                    ? <> and <b>begins on its mark</b> (no head start — the settled anchor for an
                        explosion)</>
                    : m.lead_ms > 0
                      ? <> and fires <b>{m.lead_ms} ms early</b> so its first switch finishes on the
                          mark</>
                      : null}
                  {m.trigger_offset_ms !== 0 && (
                    <> — its band's authored offset moves the mark <b>{Math.abs(m.trigger_offset_ms)} ms{' '}
                      {m.trigger_offset_ms < 0 ? 'earlier' : 'later'}</b></>
                  )}
                  {(m.drop_timing_offset_ms ?? 0) !== 0 && (
                    <> — the {timeline.drop_timing?.source === 'scene' ? "scene's" : "room's"} drop
                      timing fires it <b>{Math.abs(m.drop_timing_offset_ms)} ms{' '}
                      {m.drop_timing_offset_ms < 0 ? 'early' : 'late'}</b>, and the lull builds to
                      that moment <HelpLink topic="drop-timing-offset" /></>
                  )}.
                </div>
              ))}
              <div style={{ marginTop: 6, color: 'var(--text-muted)' }}>
                {editable && <>Drag the drop's red line — or its handle under the ruler — to
                  retime this scene's drops (the dashed line is the music's own drop mark). </>}
                The charge and lull marks aren't draggable: each is its band's anchor, the earliest
                offset among its flare kinds (one still at 0 counts), while every kind keeps its own
                offset, so there's no single kind to write a drag to. Retime one from that kind's
                own ▶ Preview on the Response tab and it shows up here; kinds authored later than
                the anchor land that much after the mark.
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
