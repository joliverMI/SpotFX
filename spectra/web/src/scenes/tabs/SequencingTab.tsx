/** Sequencing — as shipped in the sequencer increment. The GRAPHICAL half:
 * which likelihood curve the scene carries (named profile / inline / flat /
 * not sequenced) and the curve's shape. Relationships (genre, affinity)
 * render read-only — adjusted by telling the agent.
 *
 * The curve tile grid / modal window / save-as-named-curve safety flow
 * lives in the shared CurveAttachmentEditor (2026-08-17, extracted so
 * colour Sets and Groups edit curves through the identical component —
 * see that file's own docstring for the safety rule this carries with it).
 *
 * Minimum dwell (owner ask 2026-08-20, data/plan-make-dwell-meaningful-
 * under-the-rea-4p73/) gets its OWN CurveAttachmentEditor below, reusing
 * the identical component — a per-scene MINIMUM HOLD TIME (seconds, not a
 * likelihood weight) is a fundamentally different curve from the
 * likelihood one above, backed by SceneV2.dwell_curve directly (not
 * SequencerConfig), so it round-trips /scenes via attachField="dwell_curve"
 * — see queries.ts's useAttachCurve and spectra/services/dwell.py.
 */
import CurveAttachmentEditor from '../../components/CurveAttachmentEditor';
import HelpLink from '../../help/HelpLink';
import { useIntensityHistogram, useScenes, useSequencerConfig, useSequencerCurves } from '../../queries';
import { DWELL_CURVE_DEFAULT, type SceneV2 } from '../../types';
import type { SelectorEntry } from '../../queries';

export default function SequencingTab({ scene, scenes }: {
  scene: SceneV2;
  scenes: SceneV2[];
}) {
  const { data: curves = {} } = useSequencerCurves();
  const { data: config } = useSequencerConfig();
  const { data: hist } = useIntensityHistogram();
  const { data: allScenes = scenes } = useScenes();

  const entry = config?.entries?.[scene.id];
  const sceneName = (id: string) => scenes.find((s) => s.id === id)?.name ?? id;
  const affinityEdges = (config?.affinity ?? []).filter(
    (e) => e.from_id === scene.id || e.to_id === scene.id);

  // Reuses the SAME entries-record shape CurveAttachmentEditor already
  // expects for the likelihood curve above — computed here from every
  // scene's own dwell_curve, since it's a plain SceneV2 field, not a
  // SequencerConfig dict.
  const dwellEntries: Record<string, SelectorEntry> = Object.fromEntries(
    allScenes.map((s) => [s.id, {
      curve_ref: s.dwell_curve?.curve_ref ?? null,
      inline_points: s.dwell_curve?.inline_points ?? null,
      genre_mult: {},
    } as SelectorEntry]));

  return (
    <div>
      <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        Sequencing <HelpLink topic="tab-sequencing" />
        <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 'normal' }}>
          (replaces legacy energy gates/tilt — <HelpLink topic="energy-gates-equivalence" title="Energy gates/tilt equivalence" />)
        </span>
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
              Relationships — read-only; adjust these by telling the agent.
            </div>
            {Object.keys(entry.genre_mult).length > 0 && (
              <div>genre {Object.entries(entry.genre_mult)
                .map(([g, m]) => `${g} ×${m}`).join(', ')}</div>
            )}
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

      <div style={{ marginTop: 16 }}>
        <CurveAttachmentEditor
          id={scene.id}
          entries={dwellEntries}
          curves={curves}
          title="Minimum dwell (seconds)"
          attachField="dwell_curve"
          labelForEntry={sceneName}
          defaultPoints={DWELL_CURVE_DEFAULT}
          noneLabel="Default (16s → 4s)"
          noneNote="No override — his default minimum: 16s held at intensity 0, 4s at intensity 1, linear between. A scene change requested before this clears fires this scene's own Update effect instead (spectra-help topic below)."
          flatNote="A flat minimum, held regardless of intensity — edit the curve to change the value."
        />
      </div>

      <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
        Minimum dwell gates every AUTOMATIC scene change (sequencer roll,
        trigger, song transition) — never a manual Fire press. Y is
        SECONDS here, not a likelihood. <HelpLink topic="minimum-dwell" />
      </p>
    </div>
  );
}
