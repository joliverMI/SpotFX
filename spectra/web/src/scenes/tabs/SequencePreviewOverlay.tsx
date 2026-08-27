/** The CHARGE / LULL / DROP SEQUENCE scrubbing preview (2026-08-27,
 * fm/flare-preview-offsets-everywhere) — the second half he deferred with
 * "start with the flares, then we will do lull charge drop". Opened from
 * the Phase tab.
 *
 * WHAT THE RULER SHOWS, and why the gap sliders are the control that
 * matters. Each class's ramp is production's own (scene_response.
 * _phase_ramp_ms), which since 2026-08-20 STRETCHES a charge or lull to
 * ~90% of the real gap to the next trigger and hangs the remaining ~10%.
 * That hang is his own spec — "the single blob waiting in lull should
 * reach the center just and hang for just a moment, maybe 10% of the lull
 * time, before the explosion" — and a number in a form could never show
 * it. So the ruler draws ramp and hang as separate bands, and the two
 * sliders set the gaps those ramps stretch to fill. The DROP is never
 * stretched and BEGINS on its mark: the settled start anchor.
 *
 * THE MARKS ARE NOT DRAGGABLE HERE, deliberately. A band's authored offset
 * is an aggregate over however many flare kinds it attaches (min over the
 * nonzero values — a band fires atomically), so a drag would have to pick
 * one kind to write it to, and picking would be invention. The place a
 * kind's own offset is authored already exists and is per-kind by
 * construction: the flare preview's own marker. This preview SHOWS what
 * those authored offsets add up to per class, so the ruler still tells the
 * truth about where the show will fire.
 *
 * Every time here is server-computed (marks[].mark_s / fire_at_s /
 * ramp_*_s, cues[].at_s); this file derives none of them. */
import { useEffect, useState } from 'react';
import HelpLink from '../../help/HelpLink';
import {
  closeFlarePreview, closeFlarePreviewBeacon, fireSequencePreview, openSequencePreview,
} from '../../queries';
import type { PhasePreviewTimeline } from '../../queries';
import type { SceneV2 } from '../../types';
import PreviewRuler from './PreviewRuler';
import type { RulerBand, RulerMark } from './PreviewRuler';
import { useCueLoop, useHeartbeat } from './usePreviewLoop';

const DEFAULT_CHARGE_GAP_MS = 4444;   // phase_preview.DEFAULT_GAP_MS
const DEFAULT_LULL_GAP_MS = 2778;

export default function SequencePreviewOverlay({ scene, onClose }: {
  scene: SceneV2;
  onClose: () => void;
}) {
  const [intensity, setIntensity] = useState(1.0);
  const [chargeGapMs, setChargeGapMs] = useState(DEFAULT_CHARGE_GAP_MS);
  const [lullGapMs, setLullGapMs] = useState(DEFAULT_LULL_GAP_MS);
  const [timeline, setTimeline] = useState<PhasePreviewTimeline | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { holdExpired, onHoldExpired, clearExpired } = useHeartbeat();

  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      openSequencePreview(scene.id, intensity, chargeGapMs, lullGapMs)
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
  }, [scene.id, intensity, chargeGapMs, lullGapMs]);

  const { playheadS, playing, setPlaying, scrubTo } = useCueLoop({
    timeline,
    fire: (step) => fireSequencePreview(scene.id, intensity, chargeGapMs, lullGapMs, step)
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
  for (const m of timeline?.marks ?? []) {
    bands.push({ from_s: m.ramp_start_s, to_s: m.ramp_end_s,
                 label: `${m.event_class} ramp`, tone: 'accent' });
    if (m.hang_end_s > m.ramp_end_s) {
      bands.push({ from_s: m.ramp_end_s, to_s: m.hang_end_s,
                   label: 'hang', tone: 'muted' });
    }
    marks.push({ at_s: m.mark_s, label: m.event_class, tone: 'hot' });
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
                  )}.
                </div>
              ))}
              <div style={{ marginTop: 6, color: 'var(--text-muted)' }}>
                The marks here aren't draggable: a band's offset is shared by every flare kind
                attached to it, so there's no single kind to write a drag to. Retime one from that
                kind's own ▶ Preview on the Response tab and it shows up here.
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
