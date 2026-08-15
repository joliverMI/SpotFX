/** Sequencing — as shipped in the sequencer increment. The GRAPHICAL half:
 * which likelihood curve the scene carries (named profile / inline / flat /
 * not sequenced) and the curve's shape. Relationships and durations (genre,
 * dwell, affinity) render read-only — adjusted by telling the agent. */
import { useState } from 'react';
import CurveEditor, { type CurvePoint } from '../../components/CurveEditor';
import CurveThumbnail from '../../components/CurveThumbnail';
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

  // Stop sharing: copy the currently-attached profile's points into this
  // scene's own inline curve and detach the curve_ref. Same mechanism as
  // picking "Inline one-off…" from the dropdown, surfaced as an explicit
  // one-click action at the point of editing so a scene-only tweak never
  // has to travel through a shared profile by accident.
  const detachToScene = () => void attach('inline');

  // Promote: give this scene's inline curve a name and turn it into a
  // shared profile, re-attaching this scene to it by reference. The
  // reverse of detach — keeps "share it later" cheap, not a one-way door.
  const promoteToProfile = async () => {
    const name = prompt('Profile name (e.g. "High-energy ramp"):');
    if (!name) return;
    const id = crypto.randomUUID();
    const pts = draft ?? entry?.inline_points ?? FLAT;
    try {
      await saveCurvesMut.mutateAsync({ ...curves, [id]: { id, name, points: pts } });
      await attachMut.mutateAsync({ sceneId: scene.id, attachment: { kind: 'profile', profileId: id } });
      setDraft(null);
      toast(`Promoted to shared profile "${name}"`, 'success');
    } catch (e) {
      toast(`Promote failed: ${e}`, 'error');
    }
  };

  const users = profile ? usedBy(profile.id) : [];
  const affinityEdges = (config?.affinity ?? []).filter(
    (e) => e.from_id === scene.id || e.to_id === scene.id);

  // Grid tiles: each one is either a fixed choice (none/flat/inline) or a
  // named shared profile, paired with the SAME points its curve editor would
  // draw — the thumbnail is the real shape, not a stand-in for the name.
  // Inline's tile previews what it would start from if picked right now
  // (mirrors attach()'s own seed: the currently-attached profile, or the
  // scene's current curve), since a not-yet-detached scene has no fixed
  // inline shape of its own yet.
  const tiles: { value: string; label: string; points: CurvePoint[] | null; badge?: string }[] = [
    { value: 'none', label: '— not sequenced —', points: null },
    { value: 'flat', label: 'Flat 1.0 (no curve)', points: FLAT },
    ...Object.values(curves)
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((p) => {
        const n = usedBy(p.id).length;
        return { value: p.id, label: p.name, points: p.points, badge: n > 1 ? `${n} scenes` : undefined };
      }),
    { value: 'inline', label: 'Inline one-off…', points: profile ? profile.points : points },
  ];

  return (
    <div>
      <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        Sequencing <HelpLink topic="tab-sequencing" />
      </div>

      <div style={{ marginBottom: 6 }}>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Likelihood curve</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(112px, 1fr))', gap: 6 }}>
          {tiles.map((t) => (
            <button
              key={t.value}
              type="button"
              aria-label={t.label}
              aria-pressed={attachment === t.value}
              title={t.label}
              onClick={() => void attach(t.value)}
              style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3,
                padding: 5, borderRadius: 'var(--radius)', background: 'var(--surface2)',
                border: attachment === t.value ? '2px solid var(--accent2)' : '1px solid var(--border)',
                cursor: 'pointer',
              }}
            >
              {t.points ? <CurveThumbnail points={t.points} /> : (
                <div style={{
                  width: 96, height: 48, display: 'flex', alignItems: 'center',
                  justifyContent: 'center', color: 'var(--text-muted)', fontSize: 16,
                }}>—</div>
              )}
              <span style={{
                fontSize: 11, textAlign: 'center', overflow: 'hidden',
                textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 106,
              }}>{t.label}</span>
              {t.badge && <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>{t.badge}</span>}
            </button>
          ))}
        </div>
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
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11, color: 'var(--text-muted)', flexWrap: 'wrap' }}>
            {profile
              ? <span>Editing profile “{profile.name}”{users.length > 1 ? ` — changes every scene using it (${users.join(', ')})` : ''}</span>
              : <span>Inline one-off — this scene only</span>}
            {profile && (
              <button style={{ fontSize: 11, padding: '2px 8px', marginLeft: draft ? undefined : 'auto' }}
                title="Copy this profile's curve into this scene only — stops sharing, no effect on other scenes using it"
                onClick={detachToScene}>
                Detach — edit just this scene
              </button>
            )}
            {attachment === 'inline' && (
              <button style={{ fontSize: 11, padding: '2px 8px', marginLeft: draft ? undefined : 'auto' }}
                title="Save this scene's curve as a named profile other scenes can pull too"
                onClick={() => void promoteToProfile()}>
                ⇪ Promote to shared profile…
              </button>
            )}
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
