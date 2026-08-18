/** Sequencing — as shipped in the sequencer increment. The GRAPHICAL half:
 * which likelihood curve the scene carries (named profile / inline / flat /
 * not sequenced) and the curve's shape. Relationships and durations (genre,
 * dwell, affinity) render read-only — adjusted by telling the agent.
 *
 * The curve tile grid / modal window / save-as-named-curve safety flow
 * lives in the shared CurveAttachmentEditor (2026-08-17, extracted so
 * colour Sets and Groups edit curves through the identical component —
 * see that file's own docstring for the safety rule this carries with it).
 */
import CurveAttachmentEditor from '../../components/CurveAttachmentEditor';
import HelpLink from '../../help/HelpLink';
import { useIntensityHistogram, useSequencerConfig, useSequencerCurves } from '../../queries';
import type { SceneV2 } from '../../types';

export default function SequencingTab({ scene, scenes }: {
  scene: SceneV2;
  scenes: SceneV2[];
}) {
  const { data: curves = {} } = useSequencerCurves();
  const { data: config } = useSequencerConfig();
  const { data: hist } = useIntensityHistogram();

  const entry = config?.entries?.[scene.id];
  const sceneName = (id: string) => scenes.find((s) => s.id === id)?.name ?? id;
  const affinityEdges = (config?.affinity ?? []).filter(
    (e) => e.from_id === scene.id || e.to_id === scene.id);

  return (
    <div>
      <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        Sequencing <HelpLink topic="tab-sequencing" />
      </div>

      <CurveAttachmentEditor
        id={scene.id}
        entries={config?.entries ?? {}}
        curves={curves}
        histogram={hist?.counts}
        attachField="entries"
        labelForEntry={sceneName}
        noneNote="Not in the sequencer — attach a curve to make this scene a candidate when the sequencer rolls at song transitions."
        flatNote="Eligible everywhere at weight 1.0. Pick a named profile (or an inline one-off) to shape it over intensity."
        footer={entry && (
          <div style={{ background: 'var(--surface2)', padding: 8, borderRadius: 'var(--radius)', marginTop: 8, fontSize: 11 }}>
            <div style={{ color: 'var(--text-muted)', marginBottom: 4 }}>
              Relationships & pace — read-only; adjust these by telling the agent.
            </div>
            <div>
              Dwell weight <b>{entry.dwell_weight}</b>
              {' '}(≈ {entry.dwell_weight} song{entry.dwell_weight === 1 ? '' : 's'} per stay)
              {Object.keys(entry.genre_mult).length > 0 && (
                <> · genre {Object.entries(entry.genre_mult)
                  .map(([g, m]) => `${g} ×${m}`).join(', ')}</>
              )}
            </div>
            {affinityEdges.length > 0 && (
              <div style={{ marginTop: 2 }}>
                {affinityEdges.map((e, i) => (
                  <div key={i}>
                    {sceneName(e.from_id)} → {sceneName(e.to_id)} ×{e.mult}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      />
    </div>
  );
}
