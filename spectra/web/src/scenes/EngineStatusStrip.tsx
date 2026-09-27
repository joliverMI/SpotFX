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

const HELD_LABEL: Record<string, string> = {
  gradient_drift: 'drift gradient',
  force_color: 'Force Colour',
};

const HELD_TITLE: Record<string, string> = {
  gradient_drift: 'A drift gradient is switched on (top bar → Gradient), so it drives the colour and the journey waits — switch the gradient off to hand colour back to the journey',
  force_color: 'Force Colour pins the room\'s colours, so the journey waits until the pin is released',
};

/** Song time as m:ss.t. */
function fmtSongTime(ms: number | null | undefined): string {
  if (ms == null) return '?';
  const s = ms / 1000;
  return `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`;
}

function cueLabel(kind?: string | null, source?: string | null): string {
  const what = kind === 'select_color_set' ? 'colour cue' : 'scene change';
  return source === 'authored' ? `${what} (your trigger)` : `analysed ${what}`;
}

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
      {j.held_for ? (
        <span style={{ color: 'var(--text-muted)' }}
          title={HELD_TITLE[j.held_for] ?? `The walk is held by ${j.held_for}`}>
          held — {HELD_LABEL[j.held_for] ?? j.held_for}
        </span>
      ) : j.destination ? (
        <span
          title={j.destination.timed
            ? `Timed destination: ${j.destination.set_name} at ${j.destination.position_deg.toFixed(0)}°, paced at ${j.destination.pace_deg_per_min.toFixed(1)}°/min to ARRIVE on the next ${cueLabel(j.destination.cue_kind, j.destination.cue_source)} at ${fmtSongTime(j.destination.cue_at_ms)} (picked via ${j.destination.rung}). When that cue fires the next one is picked.`
            : `Current destination: ${j.destination.set_name} at ${j.destination.position_deg.toFixed(0)}° — travelling at ${j.destination.pace_deg_per_min.toFixed(1)}°/min (picked via ${j.destination.rung}). No next cue is known, so the pace comes from the distance; on arrival the next destination is selected.`}>
          → {j.destination.set_name}
          {' '}{Math.round(j.destination.progress * 100)}%
          {' '}@ {j.destination.pace_deg_per_min.toFixed(1)}°/min
          {j.destination.timed && j.destination.cue_at_ms != null && (
            <>
              {' '}· ⏱ {fmtSongTime(j.destination.cue_at_ms)}
              {j.destination.cue_in_s != null && ` (in ${Math.round(j.destination.cue_in_s)}s)`}
            </>
          )}
          <HelpLink topic="journey-destination" title="Trigger-timed destinations" />
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
