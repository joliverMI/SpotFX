/** /status — the S1 placeholder status surface. Real liveness (per-virtual
 * frame-flush freshness, the named contract) arrives with S3 ownership;
 * this page states what exists now rather than pretending. */
import HelpLink from '../help/HelpLink';
import { useAppStatus, useSequencerStatus } from '../queries';

export default function StatusPage() {
  const { data: st } = useAppStatus();
  const { data: seq } = useSequencerStatus();

  return (
    <div>
      <div className="card">
        <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          SPECTRA status <HelpLink topic="status-page" />
        </div>
        {!st ? (
          <div className="empty-note">Loading…</div>
        ) : (
          <div className="meta-grid">
            <div><div className="k">Increment</div>{st.increment} — editor + model (engine lands in S2)</div>
            <div><div className="k">Scenes</div>{st.scenes}</div>
            <div><div className="k">Light ownership</div>
              <span className="badge badge-gray" title="One system owns the lights at a time; the S3 handover is the owner's call">
                {st.light_ownership}
              </span>
            </div>
            <div><div className="k">Music bridge</div>
              {st.bridge_connected ? 'connected' : 'not wired (S2) — intensity defaults to 0.5'}
            </div>
            <div><div className="k">Sequencer</div>
              {st.sequencer_enabled ? 'enabled' : 'dark (its own switch, agent-enabled)'}
            </div>
            <div><div className="k">Room journey</div>
              {st.room_journey_degrees_per_min}°/min
              {st.room_wheel_position_deg != null && ` · wheel at ${st.room_wheel_position_deg.toFixed(0)}°`}
            </div>
          </div>
        )}
      </div>
      {seq?.last_moment && (
        <div className="card" style={{ fontSize: 13 }}>
          <div className="card-title">Last sequencer moment</div>
          {seq.last_moment.source} → {seq.last_moment.result}
        </div>
      )}
      <p className="empty-note">
        The full status surface — the liveness endpoint serving real
        frame-flush freshness — ships with S3 light ownership.
      </p>
    </div>
  );
}
