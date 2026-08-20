/** Sequencer status strip — Scenes-page header, pure display (as shipped).
 * Dark/enabled state, deferrals, active scene + minimum dwell remaining
 * (spectra/services/dwell.py, process-global — not just this sequencer's
 * own rolls), next change source, last pick with factor breakdown, and the
 * room's colour state. */
import HelpLink from '../help/HelpLink';
import { useSequencerStatus, useSpotColorSets } from '../queries';
import type { SceneV2 } from '../types';

const DEFER_LABEL: Record<string, string> = {
  force_scene: 'Force Scene',
  paused: 'paused',
  dinner_party: 'Dinner Party',
  ambient: 'Ambient Mode',
};

export default function SequencerStatusStrip({ scenes }: { scenes: SceneV2[] }) {
  const { data: st } = useSequencerStatus();
  const { data: colorCards = [] } = useSpotColorSets();
  if (!st) return null;
  const sceneName = (id: string) => scenes.find((s) => s.id === id)?.name ?? id;
  const colorName = (id: string) => colorCards.find((c) => c.id === id)?.name ?? id;

  return (
    <div className="card" style={{
      gridColumn: '1 / -1', display: 'flex', alignItems: 'center', gap: 14,
      flexWrap: 'wrap', padding: '8px 12px', fontSize: 12,
    }}>
      <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
        Sequencer <HelpLink topic="tab-sequencing" />
      </span>

      {!st.enabled ? (
        <span style={{ color: 'var(--text-muted)' }}>
          dark — not enabled (ask the agent; the bridge already feeds it song
          transitions and intensity)
        </span>
      ) : (
        <>
          <span title="Scene the sequencer last placed">
            {st.active_scene_name ?? '— no scene yet —'}
          </span>
          {st.dwell.remaining_s != null && (
            <span style={{ color: 'var(--text-muted)' }}
              title={`Minimum dwell: ${st.dwell.dwell_seconds}s latched for "${st.dwell.active_scene_name ?? st.dwell.active_scene_id}" — an automatic scene change requested before this clears does an update effect instead`}>
              min dwell {st.dwell.remaining_s > 0
                ? `${st.dwell.remaining_s.toFixed(1)}s left`
                : 'cleared'}
            </span>
          )}
          <span style={{ color: 'var(--text-muted)' }}
            title="Change moments come only from song transitions — no timer runs (a long mix holds its scene; that is by design)">
            next change: song transition
          </span>
          {!st.bridge_connected && (
            <span style={{ color: 'var(--warning)' }}
              title="The read-only spot-effects feed is down — nothing ticks moments; intensity holds at the 0.5 neutral (stated degradation)">
              bridge down
            </span>
          )}
          {st.deferred_by && (
            <span style={{ color: 'var(--warning)' }}>
              deferred by {DEFER_LABEL[st.deferred_by] ?? st.deferred_by}
            </span>
          )}
          {st.color.active_set_name && (
            <span style={{ color: 'var(--text-muted)' }}>
              palette: {st.color.active_set_name}
              {st.color.wheel_position_deg != null && ` @ ${st.color.wheel_position_deg.toFixed(0)}°`}
            </span>
          )}
          {st.last_pick && (
            <details style={{ marginLeft: 'auto' }}>
              <summary style={{ cursor: 'pointer', color: 'var(--text-muted)' }}>
                last pick: {st.last_pick.picked_name ?? st.last_pick.rung}
                {' '}· rung {st.last_pick.rung} · i={st.last_pick.intensity.toFixed(2)}
              </summary>
              <table style={{ fontSize: 11, marginTop: 4 }}>
                <thead>
                  <tr style={{ color: 'var(--text-muted)' }}>
                    <th style={{ textAlign: 'left', paddingRight: 10 }}>candidate</th>
                    <th style={{ paddingRight: 10 }}>curve</th>
                    <th style={{ paddingRight: 10 }}>genre</th>
                    <th style={{ paddingRight: 10 }}>affinity</th>
                    <th>score</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(st.last_pick.factors)
                    .sort(([, a], [, b]) => b.score - a.score)
                    .map(([id, f]) => (
                      <tr key={id} style={id === st.last_pick!.picked_id ? { fontWeight: 600 } : undefined}>
                        <td style={{ paddingRight: 10 }}>{sceneName(id)}</td>
                        <td style={{ textAlign: 'center' }}>{f.curve.toFixed(2)}</td>
                        <td style={{ textAlign: 'center' }}>×{f.genre}</td>
                        <td style={{ textAlign: 'center' }}>×{f.affinity}</td>
                        <td style={{ textAlign: 'center' }}>{f.score.toFixed(2)}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </details>
          )}
          {st.color.last_pick && (
            <details style={st.last_pick ? undefined : { marginLeft: 'auto' }}
              title="Curve × genre × wheel-travel × group — 'group' is the resolved product of every enclosing Colour Group's own curve (1.0 = in no group, or every enclosing group is flat)">
              <summary style={{ cursor: 'pointer', color: 'var(--text-muted)' }}>
                last colour pick: {st.color.last_pick.picked_name ?? st.color.last_pick.rung}
                {' '}· rung {st.color.last_pick.rung}
              </summary>
              <table style={{ fontSize: 11, marginTop: 4 }}>
                <thead>
                  <tr style={{ color: 'var(--text-muted)' }}>
                    <th style={{ textAlign: 'left', paddingRight: 10 }}>candidate</th>
                    <th style={{ paddingRight: 10 }}>curve</th>
                    <th style={{ paddingRight: 10 }}>genre</th>
                    <th style={{ paddingRight: 10 }}>wheel</th>
                    <th style={{ paddingRight: 10 }}>group</th>
                    <th>score</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(st.color.last_pick.factors)
                    .sort(([, a], [, b]) => b.score - a.score)
                    .map(([id, f]) => (
                      <tr key={id} style={id === st.color.last_pick!.picked_id ? { fontWeight: 600 } : undefined}>
                        <td style={{ paddingRight: 10 }}>{colorName(id)}</td>
                        <td style={{ textAlign: 'center' }}>{f.curve.toFixed(2)}</td>
                        <td style={{ textAlign: 'center' }}>×{f.genre}</td>
                        <td style={{ textAlign: 'center' }}>×{f.wheel.toFixed(2)}</td>
                        <td style={{ textAlign: 'center' }}>×{f.group.toFixed(2)}</td>
                        <td style={{ textAlign: 'center' }}>{f.score.toFixed(3)}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </details>
          )}
        </>
      )}
    </div>
  );
}
