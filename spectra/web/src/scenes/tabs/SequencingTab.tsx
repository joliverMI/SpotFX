/** Sequencing — as shipped in the sequencer increment. The GRAPHICAL half:
 * which likelihood curve the scene carries (named profile / inline / flat /
 * not sequenced) and the curve's shape. Relationships and durations (genre,
 * dwell, affinity) render read-only — adjusted by telling the agent. */
import { useState } from 'react';
import CurveEditor, { type CurvePoint } from '../../components/CurveEditor';
import { useToast } from '../../components/Toast';
import HelpLink from '../../help/HelpLink';
import {
  useAttachCurve, useIntensityHistogram, useSaveCurves, useSequencerConfig,
  useSequencerCurves,
} from '../../queries';
import type { SceneV2 } from '../../types';

const FLAT: CurvePoint[] = [{ x: 0, y: 1 }];

export default function SequencingTab({ scene, scenes }: {
  scene: SceneV2;
  scenes: SceneV2[];
}) {
  const toast = useToast();
  const { data: curves = {} } = useSequencerCurves();
  const { data: config } = useSequencerConfig();
  const { data: hist } = useIntensityHistogram();
  const attachMut = useAttachCurve();
  const saveCurvesMut = useSaveCurves();

  const entry = config?.entries?.[scene.id];
  const attachment: string = !entry ? 'none'
    : entry.curve_ref ? entry.curve_ref
    : entry.inline_points ? 'inline'
    : 'flat';
  const profile = entry?.curve_ref ? curves[entry.curve_ref] : undefined;

  const [draft, setDraft] = useState<CurvePoint[] | null>(null);
  const points = draft ?? (profile ? profile.points : entry?.inline_points ?? FLAT);

  const sceneName = (id: string) => scenes.find((s) => s.id === id)?.name ?? id;
  const usedBy = (profileId: string) =>
    Object.entries(config?.entries ?? {})
      .filter(([, e]) => e.curve_ref === profileId)
      .map(([sid]) => sceneName(sid));

  const attach = async (value: string) => {
    setDraft(null);
    try {
      if (value === 'none') await attachMut.mutateAsync({ sceneId: scene.id, attachment: { kind: 'none' } });
      else if (value === 'flat') await attachMut.mutateAsync({ sceneId: scene.id, attachment: { kind: 'flat' } });
      else if (value === 'inline') {
        await attachMut.mutateAsync({
          sceneId: scene.id,
          attachment: { kind: 'inline', points: profile ? profile.points : points },
        });
      } else {
        await attachMut.mutateAsync({ sceneId: scene.id, attachment: { kind: 'profile', profileId: value } });
      }
      toast('Curve attachment saved', 'success');
    } catch (e) {
      toast(`Attach failed: ${e}`, 'error');
    }
  };

  const saveDraft = async () => {
    if (!draft) return;
    try {
      if (attachment === 'inline') {
        await attachMut.mutateAsync({ sceneId: scene.id, attachment: { kind: 'inline', points: draft } });
      } else if (profile) {
        await saveCurvesMut.mutateAsync({
          ...curves,
          [profile.id]: { ...profile, points: draft },
        });
      }
      setDraft(null);
      toast('Curve saved', 'success');
    } catch (e) {
      toast(`Save failed: ${e}`, 'error');
    }
  };

  const users = profile ? usedBy(profile.id) : [];
  const affinityEdges = (config?.affinity ?? []).filter(
    (e) => e.from_id === scene.id || e.to_id === scene.id);

  return (
    <div>
      <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        Sequencing <HelpLink topic="tab-sequencing" />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Likelihood curve</span>
        <select value={attachment} style={{ fontSize: 12 }} onChange={(e) => void attach(e.target.value)}>
          <option value="none">— not sequenced —</option>
          <option value="flat">Flat 1.0 (no curve)</option>
          {Object.values(curves).map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
          <option value="inline">Inline one-off…</option>
        </select>
        {profile && users.length > 1 && (
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }} title={users.join(', ')}>
            shared by {users.length} scenes
          </span>
        )}
      </div>

      {attachment === 'none' && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>
          Not in the sequencer — attach a curve to make this scene a candidate
          when the sequencer rolls at song transitions.
        </div>
      )}
      {attachment === 'flat' && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>
          Eligible everywhere at weight 1.0. Pick a named profile (or an inline
          one-off) to shape it over intensity.
        </div>
      )}

      {(profile || attachment === 'inline') && (
        <div key={`${scene.id}:${attachment}`}>
          <CurveEditor points={points} onChange={setDraft} histogram={hist?.counts} />
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11, color: 'var(--text-muted)' }}>
            {profile
              ? <span>Editing profile “{profile.name}”{users.length > 1 ? ` — changes every scene using it (${users.join(', ')})` : ''}</span>
              : <span>Inline one-off — this scene only</span>}
            {draft && (
              <>
                <button className="primary" style={{ fontSize: 11, padding: '2px 10px', marginLeft: 'auto' }}
                  onClick={() => void saveDraft()}>
                  Save curve
                </button>
                <button style={{ fontSize: 11, padding: '2px 8px' }} onClick={() => setDraft(null)}>
                  Discard
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {entry && (
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
    </div>
  );
}
