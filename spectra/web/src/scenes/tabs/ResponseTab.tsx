/** Response tabs — Flares (one class) and Charges/Lulls/Drops (three).
 * The graphical piece is the band strip over the intensity axis; per band,
 * a curve select and gain box. Param patches stay AGENT-ONLY with a visible
 * indicator; the per-class flags (re-roll dice, colour-set jump) render as
 * read-only chips — tell the agent to change them. */
import BandStrip from '../../components/BandStrip';
import HelpLink from '../../help/HelpLink';
import { NumberInput, Select } from '../../components/inputs';
import type { ResponseClass, ResponseSpec, SceneV2 } from '../../types';
import { emptyResponse } from '../../types';

const CURVES = ['linear', 'ease_in', 'ease_out', 'pulse'] as const;

const CLASS_TITLES: Record<ResponseClass, string> = {
  flare: 'Flares', charge: 'Charges', lull: 'Lulls', drop: 'Drops',
};
// The S2 engine executes these: the bridge classifies every spot-effects
// trigger fire (charge/lull/drop stay themselves; scene changes are not
// surges; everything else is a flare) and the band containing the fire's
// intensity applies.
const CLASS_HINTS: Record<ResponseClass, string> = {
  flare: 'Any ordinary trigger fire is a flare. The band containing its intensity EXECUTES: 🎲 re-roll + jump, patches as a jump, gain as the envelope (pulse returns; linear/ease holds), the colour-set jump — and drift resumes from the new baseline (surges carry).',
  charge: 'A charge (build-up) fires from the music: its band executes — gain/patches coil the room into the payoff.',
  lull: 'A lull fires: its band executes — typically gain < 1 ducks the room and holds (the ducked level carries).',
  drop: 'A drop fires: its band executes — the payoff lands as jumps; drift resumes from the new point.',
};

export default function ResponseTab({ scene, setScene, classes, helpTopic }: {
  scene: SceneV2;
  setScene: (s: SceneV2) => void;
  classes: ResponseClass[];
  helpTopic: string;
}) {
  const setSpec = (cls: ResponseClass, spec: ResponseSpec | null) => {
    const responses = { ...scene.responses };
    if (spec === null) delete responses[cls];
    else responses[cls] = spec;
    setScene({ ...scene, responses });
  };

  return (
    <div>
      {classes.map((cls) => {
        const spec = scene.responses[cls];
        return (
          <div key={cls} style={{ marginBottom: 18 }}>
            <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              {CLASS_TITLES[cls]} <HelpLink topic={helpTopic} />
              {spec && (
                <>
                  <span className="chip" title="On this class's fires, the scene's 🎲 values re-roll (fresh dice) and jump — tell the agent to change">
                    🎲 re-roll {spec.reroll_dice ? 'on' : 'off'}
                  </span>
                  <span className="chip" title="On this class's fires, jump to the next colour set through the selector (jump, not blend; keep-current rung intact) — tell the agent to change">
                    🎨 set jump {spec.color_set_jump ? 'on' : 'off'}
                  </span>
                </>
              )}
              {spec ? (
                <button style={{ marginLeft: 'auto', fontSize: 11, padding: '2px 8px' }}
                  className="danger"
                  onClick={() => confirm(`Remove the whole ${CLASS_TITLES[cls]} response?`) && setSpec(cls, null)}>
                  remove class
                </button>
              ) : (
                <button style={{ marginLeft: 'auto', fontSize: 11, padding: '2px 8px' }}
                  onClick={() => setSpec(cls, {
                    ...emptyResponse(),
                    color_set_jump: cls === 'flare',
                    bands: [{ intensity_min: 0, intensity_max: 1, curve: 'linear', gain: 1, param_patch: {} }],
                  })}>
                  + respond to {cls}s
                </button>
              )}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>
              {CLASS_HINTS[cls]}
            </div>
            {spec && (
              <>
                <BandStrip bands={spec.bands}
                  onChange={(bands) => setSpec(cls, { ...spec, bands })} />
                {[...spec.bands]
                  .map((b, i) => ({ b, i }))
                  .sort((a, z) => a.b.intensity_min - z.b.intensity_min)
                  .map(({ b, i }) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: 12, padding: '3px 0' }}>
                      <span style={{ color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>
                        [{b.intensity_min.toFixed(2)}–{b.intensity_max.toFixed(2)})
                      </span>
                      <Select value={b.curve} width={100}
                        onChange={(v) => setSpec(cls, {
                          ...spec,
                          bands: spec.bands.map((x, j) => (j === i ? { ...x, curve: v as typeof b.curve } : x)),
                        })}
                        options={CURVES.map((c) => ({ value: c, label: c }))} />
                      <span style={{ color: 'var(--text-muted)' }}>gain</span>
                      <NumberInput value={b.gain} min={0} step={0.1} width={64}
                        onChange={(v) => setSpec(cls, {
                          ...spec,
                          bands: spec.bands.map((x, j) => (j === i ? { ...x, gain: v ?? 0 } : x)),
                        })} />
                      {Object.keys(b.param_patch ?? {}).length > 0 && (
                        <span className="chip"
                          title={`Agent-authored parameter jumps fired with this band — edit via the agent, not here. Saving preserves them untouched.\n${Object.entries(b.param_patch).map(([k, v]) => `${k}: ${v}`).join('\n')}`}>
                          ⚙ {Object.keys(b.param_patch).length} param{Object.keys(b.param_patch).length === 1 ? '' : 's'} patched — tell the agent
                        </span>
                      )}
                    </div>
                  ))}
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
