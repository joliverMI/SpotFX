/** S2 evolution-engine status strip — Scenes-page header, pure display.
 * Live journey position (custody, pace, wheel), active drift legs, bridge
 * health, and the last surge. The engine runs DARK (recording executor)
 * until the S3 handover — the strip says so rather than pretending. */
import HelpLink from '../help/HelpLink';
import { useEngineStatus } from '../queries';

const DEFER_LABEL: Record<string, string> = {
  paused: 'paused',
  dinner_party: 'Dinner Party',
  ambient: 'Ambient Mode',
};

export default function EngineStatusStrip() {
  const { data: st } = useEngineStatus();
  if (!st) return null;
  const j = st.conductor.journey;
  const legs = st.conductor.mechanisms;
  const surge = st.responses.recent_surges.length
    ? st.responses.recent_surges[st.responses.recent_surges.length - 1]
    : null;

  return (
    <div className="card" style={{
      gridColumn: '1 / -1', display: 'flex', alignItems: 'center', gap: 14,
      flexWrap: 'wrap', padding: '8px 12px', fontSize: 12,
    }}>
      <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
        Engine <HelpLink topic="engine" /><HelpLink topic="engine-strip" title="The Engine strip" />
      </span>
      {st.dark && (
        <span className="badge badge-purple"
          title="The evolution engine computes and records every leg and surge, but no write reaches the lights — live execution arrives with the S3 handover (owner's call)">
          dark — recording <HelpLink topic="engine-dark" title="Dark — recording, not driving" />
        </span>
      )}

      <span title={`Who steers the room's colour wheel. The journey always heads for a DESTINATION set picked by the selector — the destination fixes its own travel pace from its distance (reference ${j.room_degrees_per_min}°/min).`}>
        journey: {j.custody === 'scene' ? 'scene OVERRIDE' : 'room'}
        {j.wheel_position_deg != null && ` @ ${j.wheel_position_deg.toFixed(0)}°`}
        {j.rainbow_paused && ' · 🌈 paused'}
      </span>
      {j.destination ? (
        <span
          title={`Current destination: ${j.destination.set_name} at ${j.destination.position_deg.toFixed(0)}° — travelling at ${j.destination.pace_deg_per_min.toFixed(1)}°/min (picked via ${j.destination.rung}). On arrival the next destination is selected.`}>
          → {j.destination.set_name}
          {' '}{Math.round(j.destination.progress * 100)}%
          {' '}@ {j.destination.pace_deg_per_min.toFixed(1)}°/min
        </span>
      ) : (
        j.wheel_position_deg != null && !j.rainbow_paused && (
          <span style={{ color: 'var(--text-muted)' }}
            title="No destination right now — either the walk is held (pace 0) or no eligible colour set exists to head for; the journey never creeps aimlessly">
            no destination
          </span>
        )
      )}

      {st.conductor.active_scene ? (
        <details style={{ display: 'inline' }}>
          <summary style={{ cursor: 'pointer' }}
            title="Scene the engine is evolving; expand for the active drift legs">
            {st.conductor.active_scene.name} · {legs.length} drift leg{legs.length === 1 ? '' : 's'}
          </summary>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
            {legs.map((m, i) => (
              <div key={i}>
                {m.virtual_id} · {m.param} · {m.kind}
                {m.kind === 'creep'
                  ? ` @ ${m.position?.toFixed(3)} in [${m.lo}, ${m.hi}] (${m.rate_per_min}/min, ${m.motion})`
                  : ` (slew ${m.slew_s}s)`}
              </div>
            ))}
            {!legs.length && <div>no drift declared on this scene</div>}
          </div>
        </details>
      ) : (
        <span style={{ color: 'var(--text-muted)' }}
          title="No scene fired through SPECTRA yet — the engine re-baselines on any real fire">
          no active scene
        </span>
      )}

      {st.conductor.deferred_by && (
        <span style={{ color: 'var(--warning)' }}
          title="Drift holds under pause / Dinner Party / Ambient (Force Scene does NOT hold it — a pinned scene keeps its declared life)">
          held by {DEFER_LABEL[st.conductor.deferred_by] ?? st.conductor.deferred_by}
        </span>
      )}

      {surge && (
        <span style={{ color: 'var(--text-muted)' }}
          title="Most recent response event and what it did">
          last surge: {surge.class} @ {surge.intensity.toFixed(2)} → {surge.result}
          <HelpLink topic="engine-surges" title="Surges — how a response executes" />
        </span>
      )}

      <span style={{ marginLeft: 'auto',
                     color: st.bridge.connected ? 'var(--text-muted)' : 'var(--warning)' }}
        title={st.bridge.connected
          ? `Read-only spot-effects feed live (${st.bridge.ws_url}) — track state, trigger fires with intensity, deferral flags`
          : 'The read-only spot-effects feed is down — no moments, no surges; intensity holds at the 0.5 neutral (stated degradation)'}>
        bridge {st.bridge.connected ? '● live' : '○ down'}
        {st.bridge.connected && st.bridge.intensity != null
          && ` · i=${st.bridge.intensity.toFixed(2)}`}
        {st.bridge.connected && st.bridge.last_event?.class
          && ` · ${st.bridge.last_event.class}`}
        <HelpLink topic="engine-bridge" title="The read-only bridge" />
      </span>
    </div>
  );
}
