/** /status — app status + the S2 engine surface. Real liveness (per-virtual
 * frame-flush freshness, the named contract) arrives with S3 ownership;
 * this page states what exists now rather than pretending. */
import HelpLink from '../help/HelpLink';
import { useAppStatus, useEngineStatus, useSequencerStatus } from '../queries';

export default function StatusPage() {
  const { data: st } = useAppStatus();
  const { data: seq } = useSequencerStatus();
  const { data: eng } = useEngineStatus();

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
            <div><div className="k">Increment</div>{st.increment} — evolution engine live (dark against lights)</div>
            <div><div className="k">Scenes</div>{st.scenes}</div>
            <div><div className="k">Light ownership</div>
              <span className="badge badge-gray" title="One system owns the lights at a time; the S3 handover is the owner's call">
                {st.light_ownership}
              </span>
            </div>
            <div><div className="k">Music bridge</div>
              {st.bridge_connected ? 'connected (read-only)' : 'down — intensity holds at 0.5 neutral'}
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
      {eng && (
        <div className="card">
          <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            Evolution engine <HelpLink topic="engine" />
            {eng.dark && (
              <span className="badge badge-purple"
                title="Every leg and surge is computed and recorded; no write reaches the lights until the S3 handover">
                dark — recording
              </span>
            )}
          </div>
          <div className="meta-grid">
            <div><div className="k">Journey custody</div>
              {eng.conductor.journey.custody === 'scene' ? 'scene OVERRIDE' : 'room'}
              {' '}· {eng.conductor.journey.degrees_per_min}°/min
              {eng.conductor.journey.destination
                && ` · → ${eng.conductor.journey.destination.set_name}`
                + ` ${Math.round(eng.conductor.journey.destination.progress * 100)}%`}
              {eng.conductor.journey.rainbow_paused && ' · 🌈 paused'}
            </div>
            <div><div className="k">Active scene</div>
              {eng.conductor.active_scene?.name ?? '— none yet —'}
              {eng.conductor.mechanisms.length > 0 && ` · ${eng.conductor.mechanisms.length} drift leg(s)`}
            </div>
            <div><div className="k">Leg cadence</div>{eng.conductor.leg_s}s</div>
            <div><div className="k">Bridge</div>
              {eng.bridge.connected ? '● live' : '○ down'}
              {eng.bridge.track?.title && ` · ${eng.bridge.track.title}`}
              {eng.bridge.intensity != null && ` · i=${eng.bridge.intensity.toFixed(2)}`}
            </div>
            <div><div className="k">Surges seen</div>{eng.bridge.counts.responses ?? 0}</div>
            <div><div className="k">Recorded writes</div>{eng.executor.recent_writes.length ? `…${eng.executor.recent_writes[eng.executor.recent_writes.length - 1].seq}` : '0'}</div>
          </div>
        </div>
      )}
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
