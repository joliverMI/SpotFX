/** Sequencer status strip — Scenes-page header. Pure display (no controls):
 * dark/enabled state, the deferral holding it, active scene + dwell progress
 * in songs, the next change source, and the last pick with its factor
 * breakdown (curve × genre × affinity per candidate, expandable). */
import HelpLink from '../help/HelpLink';
import { useSequencerStatus } from './sequencerQueries';
import type { SceneV2 } from './types';

const DEFER_LABEL: Record<string, string> = {
  force_scene: 'Force Scene',
  paused: 'paused',
  dinner_party: 'Dinner Party',
  ambient: 'Ambient Mode',
};

export default function SequencerStatusStrip({ scenes }: { scenes: SceneV2[] }) {
  const { data: st } = useSequencerStatus();
  if (!st) return null;
  const sceneName = (id: string) => scenes.find((s) => s.id === id)?.name ?? id;

  return (
    <div className="card" style={{
      gridColumn: '1 / -1', display: 'flex', alignItems: 'center', gap: 14,
      flexWrap: 'wrap', padding: '8px 12px', fontSize: 12,
    }}>
      <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
        Sequencer <HelpLink topic="sequencer-status" />
      </span>

      {!st.enabled ? (
        <span style={{ color: 'var(--text-muted)' }}>
          dark — not enabled (ask the agent to enable it; the legacy chooser
          path keeps running either way)
        </span>
      ) : (
        <>
          <span title="Scene the sequencer last placed (or adopted from a trigger fire)">
            {st.active_scene_name ?? '— no scene yet —'}
          </span>
          {st.dwell && (
            <span style={{ color: 'var(--text-muted)' }}
              title={`dwell weight ${st.dwell.weight} — target resolved to ${st.dwell.target_songs} song(s) this stay`}>
              dwell {Math.min(st.dwell.served_songs, st.dwell.target_songs)}/{st.dwell.target_songs} songs
            </span>
          )}
          <span style={{ color: 'var(--text-muted)' }}
            title="Change moments come only from song transitions — no timer runs (a long mix holds its scene; that is by design)">
            next change: song transition
          </span>
          {st.deferred_by && (
            <span style={{ color: 'var(--warning, #d9a441)' }}
              title="Change moments are skipped entirely while this holds">
              deferred by {DEFER_LABEL[st.deferred_by] ?? st.deferred_by}
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
        </>
      )}
    </div>
  );
}
