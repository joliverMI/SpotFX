/** Response tabs — Flares (one class) and Charges/Lulls/Drops (three).
 * The item-8 doctrine: the scene DECLARES named flare kinds (readable
 * cards below — their content is agent-adjustable, no settings forms);
 * the band strip stays the graphical piece, and each band SELECTS AND
 * SCALES kinds: click a kind chip on a band row to attach/detach it,
 * set its ×scale inline, or drag the strip's handle to scale the whole
 * band. */
import BandStrip from '../../components/BandStrip';
import HelpLink from '../../help/HelpLink';
import { NumberInput } from '../../components/inputs';
import type { FlareKind, ResponseClass, ResponseSpec, SceneV2 } from '../../types';
import { emptyBand, emptyResponse } from '../../types';

const CLASS_TITLES: Record<ResponseClass, string> = {
  flare: 'Flares', charge: 'Charges', lull: 'Lulls', drop: 'Drops',
};
// The S2 engine executes these: the bridge classifies every spot-effects
// trigger fire (charge/lull/drop stay themselves; scene changes are not
// surges; everything else is a flare) and the band containing the fire's
// intensity fires its attached kinds at their scales.
const CLASS_HINTS: Record<ResponseClass, string> = {
  flare: 'Any ordinary trigger fire is a flare. The band containing its intensity fires its attached kinds at their ×scales: drift-jumps roll dice / jump the colour set (ramping in gently on soft flares), momentary kinds spike and return, permanent kinds re-baseline — drift carries on from there.',
  charge: 'A charge (build-up) fires from the music: the phase machinery builds the arc; the band\'s kinds coil the room into the payoff.',
  lull: 'A lull fires: the band\'s kinds colour the suspension — typically a permanent gain < 1 ducks the room and carries.',
  drop: 'A drop fires: the payoff lands; permanent kinds move the baselines and drift resumes from the new point.',
};

const kindIcon = (k: FlareKind): string =>
  k.type === 'drift_jump' ? (k.jump === 'color_set' ? '🎨' : '🎲')
    : k.type === 'momentary' ? '↩' : '⚓';

const kindTypeLabel = (k: FlareKind): string =>
  k.type === 'drift_jump'
    ? (k.jump === 'color_set' ? 'drift-jump · colour set' : 'drift-jump · dice')
    : k.type;

const targetContent = (p: string, t: FlareKind['params'][string]): string => {
  switch (t.mode) {
    case 'offset': return `${p} → baseline ${t.offset! >= 0 ? '+' : ''}${t.offset}`;
    case 'random': return `${p} → random ${t.lo}–${t.hi}`;
    default: return `${p} → ${t.value}`;
  }
};

const kindContent = (k: FlareKind): string => {
  const bits: string[] = [];
  if (k.type === 'drift_jump') {
    bits.push(k.jump === 'color_set'
      ? 'jump the room to the selector\'s next colour set'
      : 're-roll the scene\'s 🎲 values');
  }
  for (const [p, t] of Object.entries(k.params ?? {})) bits.push(targetContent(p, t));
  if (k.gain !== 1) bits.push(`gain ×${k.gain}`);
  if (k.hold_ms != null) bits.push(`hold ${k.hold_ms} ms`);
  return bits.join(' · ');
};

const TYPE_HINT: Record<string, string> = {
  drift_jump: 'Jumps the drift itself — the change CARRIES; the journey walks on from it. On colour jumps the ramp-in eases gentle flares, big ones land hard.',
  momentary: 'Spikes and RETURNS exactly to the carried baseline (a creep\'s current wander position included) after its hold — 250 ms unless the kind sets its own hold_ms. Each param target is absolute, an offset from the carried baseline (up/down), or a fresh random draw in a range; intensity still steers strength via the band\'s ×scale.',
  permanent: 'Lands and BECOMES the new baseline drift carries from. Same target expressions as momentary (absolute / offset / random), just never released.',
};

export default function ResponseTab({ scene, setScene, classes, helpTopic }: {
  scene: SceneV2;
  setScene: (s: SceneV2) => void;
  classes: ResponseClass[];
  helpTopic: string;
}) {
  const kinds = scene.flare_kinds ?? [];

  const setSpec = (cls: ResponseClass, spec: ResponseSpec | null, extraKinds?: FlareKind[]) => {
    const responses = { ...scene.responses };
    if (spec === null) delete responses[cls];
    else responses[cls] = spec;
    setScene({
      ...scene, responses,
      flare_kinds: extraKinds ? [...kinds, ...extraKinds] : kinds,
    });
  };

  const addClass = (cls: ResponseClass) => {
    // A new flare class starts with the two shared drift-jumps attached
    // (the historical default behavior); other classes start bare.
    const missing: FlareKind[] = [];
    const attach: Record<string, number> = {};
    if (cls === 'flare') {
      for (const [name, jump] of [['Dice Re-roll', 'dice'], ['Colour Jump', 'color_set']] as const) {
        if (!kinds.some((k) => k.name === name)) {
          missing.push({ name, type: 'drift_jump', jump, params: {}, gain: 1, hold_ms: null });
        }
        attach[name] = 1;
      }
    }
    setSpec(cls, {
      ...emptyResponse(),
      bands: [{ ...emptyBand(), kinds: attach }],
    }, missing);
  };

  const setBandKind = (cls: ResponseClass, bandIdx: number, name: string, scale: number | null) => {
    const spec = scene.responses[cls]!;
    setSpec(cls, {
      ...spec,
      bands: spec.bands.map((b, j) => {
        if (j !== bandIdx) return b;
        const next = { ...(b.kinds ?? {}) };
        if (scale === null) delete next[name];
        else next[name] = scale;
        return { ...b, kinds: next };
      }),
    });
  };

  return (
    <div>
      <div style={{ marginBottom: 18 }}>
        <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          Flare kinds <HelpLink topic="flare-kinds" />
          <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 'normal' }}>
            declared once, shared by every class below — tell the agent to add or retune one
          </span>
        </div>
        {kinds.length === 0 && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            No kinds declared yet — adding a Flares response seeds the two drift-jumps, or tell the agent what this scene should do when the music hits.
          </div>
        )}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {kinds.map((k) => (
            <div key={k.name} className="card" style={{ padding: '6px 10px', maxWidth: 260 }}
              title={`${TYPE_HINT[k.type]}\nAgent-adjustable — tell the agent to change it.`}>
              <div style={{ fontSize: 12, fontWeight: 600 }}>
                {kindIcon(k)} {k.name}
                <span className="chip" style={{ marginLeft: 6 }}>{kindTypeLabel(k)}</span>
                {scene.update_kind === k.name && (
                  <span className="chip" style={{ marginLeft: 4 }} title="This scene's fire_scene_update triggers fire this kind">
                    ⚓ UPDATE
                  </span>
                )}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{kindContent(k)}</div>
            </div>
          ))}
        </div>

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, fontSize: 12 }}
          title="A fire_scene_update trigger fires this scene's designated kind directly, bypassing band selection. Only permanent kinds are eligible — a momentary or drift-jump kind would return or roll, not 'become the new baseline'.">
          <span style={{ color: 'var(--text-muted)' }}>Update kind</span>
          <select value={scene.update_kind ?? ''}
            onChange={(e) => setScene({ ...scene, update_kind: e.target.value || null })}
            style={{ fontSize: 12 }}>
            <option value="">— none authored —</option>
            {kinds.filter((k) => k.type === 'permanent').map((k) => (
              <option key={k.name} value={k.name}>{k.name}</option>
            ))}
          </select>
          <HelpLink topic="spectra-trigger-actions" title="Fire Update" />
        </label>
      </div>

      {classes.map((cls) => {
        const spec = scene.responses[cls];
        return (
          <div key={cls} style={{ marginBottom: 18 }}>
            <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              {CLASS_TITLES[cls]} <HelpLink topic={helpTopic} />
              {spec ? (
                <button style={{ marginLeft: 'auto', fontSize: 11, padding: '2px 8px' }}
                  className="danger"
                  onClick={() => confirm(`Remove the whole ${CLASS_TITLES[cls]} response?`) && setSpec(cls, null)}>
                  remove class
                </button>
              ) : (
                <button style={{ marginLeft: 'auto', fontSize: 11, padding: '2px 8px' }}
                  onClick={() => addClass(cls)}>
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
                      {kinds.length === 0 && (
                        <span style={{ color: 'var(--text-muted)' }}>no kinds to attach</span>
                      )}
                      {kinds.map((k) => {
                        const attached = (b.kinds ?? {})[k.name] !== undefined;
                        return (
                          <span key={k.name} style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                            <button
                              style={{ fontSize: 11, padding: '2px 8px', opacity: attached ? 1 : 0.55,
                                borderColor: attached ? 'var(--accent)' : undefined }}
                              title={attached ? `${k.name} fires in this band — click to detach` : `attach ${k.name} to this band`}
                              onClick={() => setBandKind(cls, i, k.name, attached ? null : 1)}>
                              {kindIcon(k)} {k.name}
                            </button>
                            {attached && (
                              <>
                                <span style={{ color: 'var(--text-muted)' }}>×</span>
                                <NumberInput value={b.kinds[k.name]} min={0} step={0.1} width={56}
                                  onChange={(v) => setBandKind(cls, i, k.name, v ?? 1)} />
                              </>
                            )}
                          </span>
                        );
                      })}
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
