/** Phase Choreography — descriptive + agent (the interface doctrine):
 * durations, modes, and anchor fractions read as a sentence and are
 * adjusted by telling the agent, not by a settings form. */
import HelpLink from '../../help/HelpLink';
import type { SceneV2 } from '../../types';

export default function PhaseTab({ scene }: { scene: SceneV2 }) {
  const c = scene.choreography;
  return (
    <div>
      <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        Phase choreography <HelpLink topic="tab-phase" />
      </div>
      <div style={{ background: 'var(--surface2)', padding: 12, borderRadius: 'var(--radius)', fontSize: 13, lineHeight: 1.6 }}>
        {c.enabled ? (
          <>
            Scene changes into this scene crossfade over <b>{c.transition_ms} ms</b> in{' '}
            <b>{c.transition_mode}</b> mode, with the visual payoff anchored at{' '}
            <b>{Math.round(c.anchor_frac * 100)}%</b> of the crossfade — the engine fires
            early by that fraction so the payoff lands on the beat.
          </>
        ) : (
          <>Choreography is <b>off</b> — this scene lands as an instant switch.</>
        )}
      </div>
      <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
        Adjusted by telling the agent (durations and modes are numbers, not shapes —
        no sliders here by design). Surges keep their own jump-not-blend moment; this
        choreography belongs to scene <i>changes</i>.
      </p>
    </div>
  );
}
