/** Phase Choreography — descriptive + agent (the interface doctrine):
 * durations, modes, and anchor fractions read as a sentence and are
 * adjusted by telling the agent, not by a settings form.
 *
 * SINCE 2026-08-27 this tab is also where the two scrubbing previews his
 * own sequencing deferred are opened ("start with the flares, then we will
 * do lull charge drop") — a scene-to-scene TRANSITION and the charge/lull/
 * drop SEQUENCE. Both belong here rather than beside the flare preview
 * because this tab already IS the page for those two things: the sentence
 * above describes the transition's crossfade and anchor, and the Override
 * Blend sentence below describes the charge/lull stretch. A preview is the
 * same statement, shown instead of said. */
import { useState } from 'react';
import HelpLink from '../../help/HelpLink';
import type { SceneV2 } from '../../types';
import SequencePreviewOverlay from './SequencePreviewOverlay';
import TransitionPreviewOverlay from './TransitionPreviewOverlay';

export default function PhaseTab({ scene, setScene, scenes }: {
  scene: SceneV2;
  setScene: (s: SceneV2) => void;
  scenes: SceneV2[];
}) {
  const c = scene.choreography;
  const [previewing, setPreviewing] = useState<'transition' | 'sequence' | null>(null);
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
      <div
        className="card-title"
        style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 14 }}
      >
        Override Blend <HelpLink topic="override-blend-spectra" />
      </div>
      <div style={{ background: 'var(--surface2)', padding: 12, borderRadius: 'var(--radius)', fontSize: 13, lineHeight: 1.6 }}>
        Charge/lull ramps stretch automatically to the real gap to the next
        trigger — ramp to ~90% of the gap, hang the remaining ~10% before
        the next moment. No per-scene number to set; an unknown gap falls
        back to the tuned default (charge 4000 ms, lull 2500 ms).
        <br />
        Scene entry ramp:{' '}
        <b>{scene.entry_ramp_ms > 0 ? `${scene.entry_ramp_ms} ms blend-in` : 'instant (jump)'}</b>
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
        <button onClick={() => setPreviewing('transition')}>
          ▶ Preview transition into this scene
        </button>
        <button onClick={() => setPreviewing('sequence')}>
          ▶ Preview drop sequence
        </button>
        <HelpLink topic="transition-preview-timeline" title="What a preview does to your room" />
      </div>
      <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>
        Both previews take over your room while they are open — your live show stops, this
        scene is held on your fixtures, and everything goes back when you close.
      </p>

      {previewing === 'transition' && (
        <TransitionPreviewOverlay
          scene={scene} scenes={scenes}
          onClose={() => setPreviewing(null)}
          onTriggerOffsetChange={(ms) => setScene({ ...scene, trigger_offset_ms: ms })}
        />
      )}
      {previewing === 'sequence' && (
        <SequencePreviewOverlay scene={scene} onClose={() => setPreviewing(null)} />
      )}

      <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
        Scene entry blend is adjusted by telling the agent (a number, not a
        shape — no sliders here by design). Surges keep their own
        jump-not-blend moment; this choreography belongs to scene{' '}
        <i>changes</i>.
      </p>
    </div>
  );
}
