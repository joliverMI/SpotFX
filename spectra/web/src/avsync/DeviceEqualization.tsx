/** The PER-DEVICE half of /avsync: measure one fixture at a time, then read
 * the offsets that would make them all land together.
 *
 * His words behind it: "Different devices seem to have different network
 * and physical latencies... tune the per device settings so that they are
 * timed equally."
 *
 * WHY ONE DEVICE AT A TIME. Each run's number is (that light's lag) minus
 * (the sound's lag), and the sound's lag is the SAME in every run — the
 * phone's mic, the speakers, SPECTRA's audio hub. So subtracting one
 * device's run from another's cancels it exactly, along with every
 * systematic the two runs share. The DIFFERENCES between devices are a far
 * better number than any single absolute one, and they are all the
 * equalization needs.
 *
 * NOTHING IS AUTO-WRITTEN. The server computes the proposal (so the sign
 * translation has one implementation) and this panel renders it; applying
 * is a press per device, through the same PUT the device page uses. That
 * is the same rule the room-lead Apply dialogue follows.
 */
import { useCallback, useEffect, useState } from 'react';
import { apiGet, apiPut } from '../api/client';
import { useToast } from '../components/Toast';
import HelpLink from '../help/HelpLink';
import type { DeviceListing } from '../types';

type MeasuredRow = {
  device_id: string; device_name: string; av_offset_ms: number; intrinsic_ms: number;
  applied_delay_ms: number; runs: number; sigma_ms: number | null;
  spread_ms: number | null; at_iso: string | null;
};
type ProposalRow = {
  device_id: string; device_name: string; measured_av_offset_ms: number;
  current_timing_offset_ms: number; proposed_timing_offset_ms: number;
  delta_ms: number; is_reference: boolean; sentence: string;
};
export type DeviceProposal = {
  applicable: boolean; reason: string; measured: MeasuredRow[];
  reference_device_id: string | null; proposals: ProposalRow[];
  spread_ms: number | null; out_of_range: string[]; after_note: string;
  offset_limit_ms: number;
};

export default function DeviceEqualization({ canMeasure, measuring, onMeasure }: {
  canMeasure: boolean;
  measuring: string | null;
  onMeasure: (deviceId: string) => void;
}) {
  const toast = useToast();
  const [devices, setDevices] = useState<DeviceListing | null>(null);
  const [prop, setProp] = useState<DeviceProposal | null>(null);
  const [applying, setApplying] = useState<string | null>(null);
  // Same default as /devices: only the devices the room actually uses, with
  // one expansion for the rest. Same server-computed `in_use` flag, so the
  // two surfaces cannot disagree about what "used" means.
  const [showAll, setShowAll] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [d, p] = await Promise.all([
        apiGet<DeviceListing>('/devices'),
        apiGet<DeviceProposal>('/av-sync/device-proposal'),
      ]);
      setDevices(d);
      setProp(p);
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), 'error');
    }
  }, [toast]);

  useEffect(() => { void reload(); }, [reload]);
  // a finished run adds a record, so refresh the proposal when one ends
  useEffect(() => { if (measuring === null) void reload(); }, [measuring, reload]);

  const apply = async (row: ProposalRow) => {
    setApplying(row.device_id);
    try {
      const r = await apiPut<{ summary: string }>(
        `/devices/${encodeURIComponent(row.device_id)}/timing`,
        { timing_offset_ms: row.proposed_timing_offset_ms });
      toast(r.summary, 'success');
      await reload();
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), 'error');
    } finally {
      setApplying(null);
    }
  };

  const measuredById = new Map((prop?.measured ?? []).map((m) => [m.device_id, m]));
  const allDevices = devices?.devices ?? [];
  const hidden = allDevices.filter((d) => !d.in_use).length;
  const shownDevices = showAll ? allDevices : allDevices.filter((d) => d.in_use);

  return (
    <div className="card">
      <div className="card-title">
        Per-device — line the fixtures up with each other <HelpLink topic="av-sync-per-device" />
      </div>
      <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 10 }}>
        Point the phone at ONE fixture and measure it on its own; repeat for the
        others. Only that device flashes — everything else keeps playing the show.
        The useful answer is the DIFFERENCE between devices: the shared sound path
        cancels in the subtraction, so the differences are far tighter than any one
        absolute number.
      </div>

      {!devices && <div className="empty-note">Loading devices…</div>}
      {devices && allDevices.length === 0 && (
        <div className="empty-note">No devices to measure.</div>
      )}
      {devices && shownDevices.map((d) => {
        const m = measuredById.get(d.id);
        return (
          <div key={d.id} style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
            <button disabled={!canMeasure || measuring !== null}
                    onClick={() => onMeasure(d.id)} style={{ padding: '8px 12px' }}>
              ⚡ Measure {d.name}
            </button>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {m
                ? `${Math.abs(m.av_offset_ms).toFixed(0)} ms ${m.av_offset_ms > 0 ? 'BEHIND' : 'AHEAD'}`
                  + ` · ${m.runs} run${m.runs === 1 ? '' : 's'}`
                  + (m.spread_ms !== null ? ` · spread ${m.spread_ms.toFixed(0)} ms` : '')
                  + (m.applied_delay_ms ? ` · held ${m.applied_delay_ms} ms today` : '')
                : 'not measured yet'}
              {d.timing_offset_ms !== 0 && ` · offset ${d.timing_offset_ms > 0 ? '+' : ''}${d.timing_offset_ms} ms`}
            </span>
          </div>
        );
      })}

      {hidden > 0 && (
        <div style={{ marginTop: 6 }}>
          <button onClick={() => setShowAll(!showAll)}>
            {showAll ? `Hide ${hidden} not in use` : `Show all devices — ${hidden} more not in use`}
          </button>
          {' '}<HelpLink topic="devices-in-use" />
        </div>
      )}

      <div className="card-subtitle" style={{ marginTop: 14 }}>Proposed equalization</div>
      {!prop && <div className="empty-note">Loading…</div>}
      {prop && !prop.applicable && <div className="empty-note">{prop.reason}</div>}
      {prop && prop.applicable && (
        <>
          <div style={{ fontSize: 13, marginBottom: 8 }}>
            Spread across the room: <b>{prop.spread_ms?.toFixed(0)} ms</b>. The slowest
            device sets the pace, so every proposal below is a WAIT — nothing is asked
            to fire before its frame exists.
          </div>
          {prop.proposals.map((row) => (
            <div key={row.device_id}
                 style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
              <span style={{ minWidth: 240, fontSize: 13 }}>{row.sentence}</span>
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                now {row.current_timing_offset_ms > 0 ? '+' : ''}{row.current_timing_offset_ms} ms
                {' → '}
                {row.proposed_timing_offset_ms > 0 ? '+' : ''}{row.proposed_timing_offset_ms} ms
              </span>
              <button disabled={row.delta_ms === 0 || applying !== null}
                      onClick={() => void apply(row)}>
                {row.delta_ms === 0 ? 'already set' : 'Apply'}
              </button>
            </div>
          ))}
          {prop.out_of_range.length > 0 && (
            <div style={{ fontSize: 13, color: 'var(--danger)', marginTop: 6 }}>
              {prop.out_of_range.join(', ')} would need more than {prop.offset_limit_ms} ms —
              shown clamped. A gap that big usually means the capture, not the room:
              re-measure before applying it.
            </div>
          )}
          <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 10 }}>
            {prop.after_note}
          </div>
        </>
      )}
    </div>
  );
}
