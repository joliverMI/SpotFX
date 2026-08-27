/** APPLY THE MEASUREMENT — the /avsync result becoming the room's own
 * A/V-sync lead (owner ask 2026-08-28: "how do I update the offset value
 * based on that data?").
 *
 * Four holds, none of them decoration:
 *  1. NOTHING TO APPLY WITHOUT A NUMBER. `applicable` comes from the
 *     server (spectra/services/av_sync_lead.py), which refuses exactly
 *     where the instrument refuses. A refusal renders the reason and NO
 *     apply path — there is no branch here that can enable the button
 *     without one.
 *  2. ENOUGH TO DECIDE, NOT ONE FIGURE. The run-to-run wobble (±sigma)
 *     is shown SEPARATELY from the named directional systematics, with
 *     the recent runs beside them so stability is visible rather than
 *     taken on trust.
 *  3. CURRENT vs PROPOSED, DIRECTION SPELLED OUT. Never a bare signed
 *     delta he has to sign-infer — the sentence is as much the
 *     deliverable as the number. An uncalibrated room reads "none yet",
 *     never a borrowed number: the two spot-effects offsets that look
 *     related (audio_latency_ms, the legacy trigger buffer) are DIFFERENT
 *     JOBS, not previous values of this one, and the panel says so.
 *  4. APPLY IS HIS PRESS. Never on measurement completion. The write is
 *     PUT /api/room-controls — the established save path every other room
 *     control uses — followed by a real GET read-back before anything
 *     here claims success. Undo is the same path in reverse, offered only
 *     once there is a previous value to return to.
 *
 * Nothing in this file computes the sign translation; it renders what the
 * server proposed. Re-deriving it here is exactly how the flare preview's
 * inverted-sign defect happened.
 */
import { useCallback, useEffect, useState } from 'react';
import HelpLink from '../help/HelpLink';
import { apiGet, apiPut } from '../api/client';
import { useToast } from '../components/Toast';

export type RecentRun = {
  id: string | null; at_iso: string | null; mode: string | null;
  ok: boolean; av_offset_ms: number | null; sigma_ms: number | null;
};
export type Systematic = { term: string; bound_ms: number; direction: string; depends_on: string };
export type Proposal = {
  applicable: boolean; reason: string;
  measured_av_offset_ms: number | null; sigma_ms: number | null;
  systematic_later_ms: number; systematic_earlier_ms: number;
  systematic_bound_ms: number; systematics: Systematic[];
  current_lead_ms: number | null; current_phrase: string;
  proposed_lead_ms: number | null; delta_ms: number | null;
  direction_sentence: string; out_of_range: boolean; statement: string;
  recent: RecentRun[]; source: string; spread_ms: number | null;
  two_runs_note: string; lead_min_ms: number; lead_max_ms: number;
};

/** Why the instrument had no number, in his words. Every one of these is
 * a state av_sync_correlate.py can genuinely return; none of them is a
 * reason to offer a value anyway. */
const REFUSAL_TEXT: Record<string, string> = {
  weak: 'The signal was too weak to stand behind — the correlation peak did not rise clearly out of the noise.',
  ambiguous: 'Several offsets fit the data about equally well. A periodic-looking pattern does this; move the phone or run the flash pattern again.',
  unstable: 'The offset drifted during the capture, so there is no single number to report — something moved, or playback changed mid-run.',
  no_data: 'Not enough was captured yet. Let it run longer with the lights in frame.',
  clock: 'The phone and server clocks had not paired yet.',
  audio: 'The microphone side did not lock — the room may be too quiet, or the phone too far from the speakers.',
  light: 'The camera side did not lock — the lights may be out of frame, too dim, or washed out.',
  no_measurement: 'No measurement yet. Run one first.',
  out_of_range: 'The correction this measurement asks for is larger than the setting allows. Re-measure before applying anything this big — a result this far out usually means the capture, not the room.',
};

function fmtRun(r: RecentRun): string {
  if (!r.ok || r.av_offset_ms === null) return 'no number';
  const ms = r.av_offset_ms;
  return `${Math.abs(ms).toFixed(0)} ms ${ms > 0 ? 'behind' : 'ahead'}`
    + (r.sigma_ms !== null ? ` ±${r.sigma_ms.toFixed(0)}` : '');
}

function fmtLead(ms: number | null): string {
  if (ms === null) return 'none yet';
  if (ms === 0) return '0 ms';
  return `${Math.abs(ms)} ms ${ms > 0 ? 'earlier' : 'later'}`;
}

export default function ApplyOffsetDialog({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const [prop, setProp] = useState<Proposal | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // The value that was in force when this dialogue opened — what "undo"
  // returns to. Captured before the write, never re-read from the room
  // afterwards (that would make undo return to what we just wrote).
  const [undoTo, setUndoTo] = useState<number | null | undefined>(undefined);
  const [wrote, setWrote] = useState<{ value: number | null; confirmed: boolean } | null>(null);

  const load = useCallback(async () => {
    try {
      setProp(await apiGet<Proposal>('/av-sync/apply-proposal'));
      setLoadErr(null);
    } catch (e) {
      setLoadErr(String(e));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  /** THE WRITE. Established save path only: read the whole room-control
   * state, change ONE field, PUT it back, then GET it again and check.
   * A PUT echoing its own body back is not a read-back. */
  const writeLead = useCallback(async (value: number | null, previous: number | null) => {
    setBusy(true);
    try {
      const state = await apiGet<Record<string, unknown>>('/room-controls');
      await apiPut('/room-controls', { ...state, av_sync_lead_ms: value });
      const after = await apiGet<{ av_sync_lead_ms: number | null }>('/room-controls');
      const confirmed = after.av_sync_lead_ms === value;
      setUndoTo(previous);
      setWrote({ value, confirmed });
      if (confirmed) toast(`Saved: lights now fire ${fmtLead(value)}`, 'success');
      else toast('The room did not read back the value that was written — nothing is confirmed', 'error');
      await load();
    } catch (e) {
      toast(`Could not save: ${String(e)}`, 'error');
    } finally {
      setBusy(false);
    }
  }, [load, toast]);

  const body = () => {
    if (loadErr) return <div style={{ color: 'var(--danger)' }}>{loadErr}</div>;
    if (!prop) return <div className="empty-note">Reading the measurement…</div>;

    const refusalKey = prop.out_of_range ? 'out_of_range' : prop.reason;
    const refusal = REFUSAL_TEXT[refusalKey]
      || (refusalKey ? `The instrument did not stand behind this run (${refusalKey}).` : '');

    return (
      <>
        {/* ── hold 2: the measurement, with its uncertainty split apart ── */}
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          Measured {prop.source === 'live' ? 'just now' : prop.source === 'stored' ? 'on the last saved run' : ''}
        </div>
        <div style={{ fontSize: 24, fontWeight: 700,
                      color: prop.applicable ? 'var(--accent2)' : 'var(--text-muted)' }}>
          {prop.measured_av_offset_ms === null ? 'No number yet'
            : `Lights ${Math.abs(prop.measured_av_offset_ms).toFixed(0)} ms `
              + (prop.measured_av_offset_ms > 0 ? 'BEHIND the sound' : 'AHEAD OF the sound')}
        </div>
        {prop.sigma_ms !== null && (
          <div style={{ fontSize: 12, marginTop: 2 }}>
            <b>Run-to-run wobble:</b> ±{prop.sigma_ms.toFixed(0)} ms (this capture's own repeatability)
          </div>
        )}
        {(prop.systematic_later_ms > 0 || prop.systematic_earlier_ms > 0) && (
          <div style={{ fontSize: 12, marginTop: 2 }}>
            <b>Named systematics, separately:</b> the true value could be up to{' '}
            {prop.systematic_later_ms} ms further AHEAD or {prop.systematic_earlier_ms} ms further
            BEHIND than shown
            {prop.systematics.length > 0
              && ` (${prop.systematics.map((s) => `${s.term} ±${s.bound_ms}`).join(', ')})`}.
          </div>
        )}
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>{prop.two_runs_note}</div>

        {/* ── recent runs, so stability is visible not asserted ── */}
        {prop.recent.length > 1 && (
          <div style={{ marginTop: 8, fontSize: 12 }}>
            <b>Recent runs</b>
            {prop.spread_ms !== null && (
              <span style={{ color: 'var(--text-muted)' }}> — spread {prop.spread_ms} ms across the ones that produced a number</span>
            )}
            <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
              {prop.recent.map((r, i) => (
                <li key={r.id ?? i} style={{ color: r.ok ? undefined : 'var(--text-muted)' }}>
                  {fmtRun(r)}
                  {r.mode ? ` · ${r.mode}` : ''}
                  {r.at_iso ? ` · ${r.at_iso.replace('T', ' ').slice(0, 16)}` : ''}
                </li>
              ))}
            </ul>
          </div>
        )}

        <hr style={{ border: 0, borderTop: '1px solid var(--border)', margin: '12px 0' }} />

        {/* ── hold 3: current vs proposed, direction in words ── */}
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 120px', minWidth: 0 }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Current A/V-sync lead</div>
            <div style={{ fontSize: 18, fontWeight: 600 }}>{prop.current_phrase}</div>
          </div>
          <div style={{ flex: '1 1 120px', minWidth: 0 }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Proposed</div>
            <div style={{ fontSize: 18, fontWeight: 600,
                          color: prop.applicable ? 'var(--accent2)' : 'var(--text-muted)' }}>
              {prop.applicable ? fmtLead(prop.proposed_lead_ms) : '—'}
            </div>
          </div>
        </div>
        {prop.applicable && (
          <div style={{ fontSize: 15, fontWeight: 600, marginTop: 8 }}>
            {prop.direction_sentence}
          </div>
        )}

        {/* ── hold 1: a refusal renders the reason and no apply path ── */}
        {!prop.applicable && (
          <div style={{ marginTop: 10, fontSize: 13, color: 'var(--warning)' }}>
            <b>Nothing to apply.</b> {refusal}
          </div>
        )}

        {/* what the setting IS — and what it is not */}
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 10 }}>
          This is SPECTRA's own A/V-sync lead: the one authored number in the show clock,
          applied where the clock feeds the trigger engine. It is not the same thing as
          SpotFX's <i>Audio Latency</i> (which aligns audio capture for analysis) or the
          legacy <i>LedFX Trigger Buffer</i> (which compensated a write path SPECTRA does not
          use) — those are different jobs, not earlier values of this one, and nothing here
          reads or changes either.
        </div>

        {/* ── hold 4: his press, then a stated read-back ── */}
        {wrote && (
          <div style={{ marginTop: 10, fontSize: 13,
                        color: wrote.confirmed ? 'var(--ok)' : 'var(--danger)' }}>
            {wrote.confirmed
              ? `Written and read back: the room's A/V-sync lead is now ${fmtLead(wrote.value)}.`
              : 'The write did not read back. Nothing is confirmed — check the room and try again.'}
          </div>
        )}
      </>
    );
  };

  const canApply = !!prop && prop.applicable && !busy;
  const canUndo = undoTo !== undefined && !busy && !!wrote?.confirmed
    && wrote.value !== undoTo;

  return (
    <div onClick={onClose}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100,
               display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
               paddingTop: '8vh', overflowY: 'auto' }}>
      <div className="card" onClick={(e) => e.stopPropagation()}
        style={{ width: 460, maxWidth: '94vw', margin: 0 }}>
        <div className="card-title">
          Apply this measurement <HelpLink topic="av-sync-apply" />
        </div>
        {body()}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 14 }}>
          {/* NOT MERELY DISABLED — ABSENT. A disabled button still renders in
              the primary accent here, which reads as pressable and invites
              exactly the press hold 1 exists to prevent (caught in a real
              390px render, not reasoned about). When the instrument did not
              stand behind a number there is no apply control at all; the
              refusal text above is the whole answer. */}
          {prop?.applicable && (
            <button className="primary" disabled={!canApply}
              onClick={() => void writeLead(prop.proposed_lead_ms, prop.current_lead_ms)}>
              {busy ? 'Saving…' : 'Apply to the room'}
            </button>
          )}
          {canUndo && (
            <button onClick={() => void writeLead(undoTo as number | null, wrote!.value)}>
              ↺ Put back {fmtLead(undoTo as number | null)}
            </button>
          )}
          <span style={{ flex: 1 }} />
          <button onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
