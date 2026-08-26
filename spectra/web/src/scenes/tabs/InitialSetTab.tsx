/** Initial Set — the scene's initial conditions. Device entries render as
 * SUB-TABS, one per category/virtual, titled by that name, created as
 * entries are added. Per entry: every registry parameter visible with a
 * real slider, grouped by aspect; unset params show dimmed at the effect's
 * real default (click the name to enable). Every value carries the ⚡/🎲
 * affordances; colour strings are the one un-bindable value here (palette
 * variation is the colour-set system's job).
 *
 * Stepped effect (decision: star-fold-entry-growth): an entry may resolve
 * to a DIFFERENT effect at/above an ⚡ threshold. The honest minimal form:
 * a variant strip (base + one chip per step) that re-points the SAME params
 * grid at the selected variant's effect + param set — no second editor, no
 * sprawl. Colours, brightness and drift stay entry-level. */
import { useMemo, useState } from 'react';
import { BindableNumber, BindableOption, BindableToggle } from '../../components/BindingControl';
import ColorGradientPicker from '../../components/ColorGradientPicker';
import HelpLink from '../../help/HelpLink';
import { uuid } from '../../lib/uid';
import { useGradients } from '../../queries';
import type { EffectParamMeta, Registry, SceneDeviceConfig, SceneV2 } from '../../types';
import { emptyColor, emptyDevice, isBinding } from '../../types';

const HIDDEN_TYPES = new Set(['color', 'gradient', 'polar', 'move_xy', 'move_polar']);
const ASPECT_ORDER = ['shape', 'reactivity', 'brightness', 'blur', 'color', 'bg_color', 'other'];
const ASPECT_TITLES: Record<string, string> = {
  shape: 'Shape', reactivity: 'Reactivity', brightness: 'Brightness',
  blur: 'Blur', color: 'Colour params', bg_color: 'Background', other: 'Other',
};

function entryTitle(dev: SceneDeviceConfig): string {
  if (dev.target_kind === 'all') return 'All Devices';
  return dev.target || '— new entry —';
}

function paramDefault(meta: EffectParamMeta): number | boolean | string {
  if (meta.type === 'toggle') return typeof meta.default === 'boolean' ? meta.default : false;
  if (meta.type === 'enum' || meta.type === 'string') {
    return typeof meta.default === 'string' ? meta.default : meta.options?.[0] ?? '';
  }
  if (typeof meta.default === 'number') {
    return meta.type === 'integer' ? Math.round(meta.default) : meta.default;
  }
  return meta.min ?? 0;
}

export default function InitialSetTab({ scene, setScene, registry }: {
  scene: SceneV2;
  setScene: (s: SceneV2) => void;
  registry: Registry | undefined;
}) {
  const [activeEntry, setActiveEntry] = useState<string | null>(null);
  const dev = scene.devices.find((d) => d.id === activeEntry) ?? scene.devices[0] ?? null;

  const setDev = (next: SceneDeviceConfig) =>
    setScene({ ...scene, devices: scene.devices.map((d) => (d.id === next.id ? next : d)) });

  const addEntry = () => {
    const d = emptyDevice(uuid());
    setScene({ ...scene, devices: [...scene.devices, d] });
    setActiveEntry(d.id);
  };

  const removeEntry = () => {
    if (!dev) return;
    if (!confirm(`Remove entry "${entryTitle(dev)}"?`)) return;
    setScene({ ...scene, devices: scene.devices.filter((d) => d.id !== dev.id) });
    setActiveEntry(null);
  };

  return (
    <div>
      <div className="subtab-bar">
        {scene.devices.map((d) => (
          <button key={d.id} className={dev?.id === d.id ? 'active' : ''}
            onClick={() => setActiveEntry(d.id)}>
            {entryTitle(d)}
            {d.effect_type && (
              <span style={{ opacity: 0.6 }}>
                {' '}· {d.effect_type}{(d.effect_steps?.length ?? 0) > 0 ? ' ⚡' : ''}
              </span>
            )}
          </button>
        ))}
        <button onClick={addEntry} title="Add a device entry (All Devices / a category / a virtual)">＋ Add entry</button>
        <span style={{ marginLeft: 4, alignSelf: 'center' }}><HelpLink topic="tab-initial-set" /></span>
      </div>

      {!dev && (
        <div className="empty-note">
          No device entries — the scene fires nothing yet. Add one per category or virtual;
          narrower entries override wider ones (All Devices &lt; category &lt; virtual).
        </div>
      )}

      {dev && <EntryPanel key={dev.id} dev={dev} setDev={setDev}
        registry={registry} onRemove={removeEntry} />}
    </div>
  );
}

function EntryPanel({ dev, setDev, registry, onRemove }: {
  dev: SceneDeviceConfig;
  setDev: (d: SceneDeviceConfig) => void;
  registry: Registry | undefined;
  onRemove: () => void;
}) {
  const { data: gradients = [] } = useGradients();
  const set = (patch: Partial<SceneDeviceConfig>) => setDev({ ...dev, ...patch });

  // Stepped effect: which variant the params grid edits (-1 = the base
  // form, otherwise an effect_steps index). Selection is a fire-time step
  // server-side; here it only re-points the grid.
  const steps = dev.effect_steps ?? [];
  const [variantIdx, setVariantIdx] = useState(-1);
  const variant = variantIdx >= 0 && variantIdx < steps.length ? steps[variantIdx] : null;
  const effEffect = variant ? variant.effect_type : dev.effect_type;
  const effParams = variant ? variant.params : dev.params;
  const setStep = (idx: number, patch: Partial<import('../../types').EffectStep>) =>
    set({ effect_steps: steps.map((s, i) => (i === idx ? { ...s, ...patch } : s)) });
  const addStep = () => {
    set({ effect_steps: [...steps, { threshold: 0.7, effect_type: '', params: {} }] });
    setVariantIdx(steps.length);
  };
  const removeStep = (idx: number) => {
    set({ effect_steps: steps.filter((_, i) => i !== idx) });
    setVariantIdx(-1);
  };

  const categories = Object.keys(registry?.categories ?? {});
  const allVirtuals = useMemo(
    () => [...new Set(categories.flatMap((c) => registry?.categories[c]?.virtuals ?? []))],
    [registry, categories],
  );
  const allEffects = Object.keys(registry?.effects ?? {});
  // A category target fires its whole subtree, so its effect options are the
  // subtree's union of curated lists.
  const subtreeEffects = useMemo(() => {
    if (dev.target_kind !== 'category') return [];
    const cats = Object.values(registry?.categories ?? {});
    const root = registry?.categories[dev.target];
    if (!root) return [];
    const ids = new Set([root.id]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const c of cats) {
        if (c.parent_id && ids.has(c.parent_id) && !ids.has(c.id)) {
          ids.add(c.id);
          grew = true;
        }
      }
    }
    return [...new Set(cats.filter((c) => ids.has(c.id)).flatMap((c) => c.effects))];
  }, [registry, dev.target_kind, dev.target]);
  const effectOptions =
    dev.target_kind === 'category' && subtreeEffects.length ? subtreeEffects : allEffects;

  const params = registry?.effects[effEffect]?.params ?? {};
  const visible = Object.entries(params).filter(([, m]) => !HIDDEN_TYPES.has(m.type ?? ''));
  const byAspect = new Map<string, [string, EffectParamMeta][]>();
  for (const [name, meta] of visible) {
    const aspect = meta.aspect && ASPECT_ORDER.includes(meta.aspect) ? meta.aspect : 'other';
    if (!byAspect.has(aspect)) byAspect.set(aspect, []);
    byAspect.get(aspect)!.push([name, meta]);
  }

  const setParam = (name: string, value: SceneDeviceConfig['params'][string] | null) => {
    const next = { ...effParams };
    if (value === null) delete next[name];
    else next[name] = value;
    if (variant) setStep(variantIdx, { params: next });
    else set({ params: next });
  };

  const colorDefaults = useMemo(() => gradients.map((g) => g.value), [gradients]);

  return (
    <div>
      {/* Target + effect */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 4 }}>
        <select value={dev.target_kind} style={{ fontSize: 12 }}
          onChange={(e) => set({ target_kind: e.target.value as SceneDeviceConfig['target_kind'], target: '' })}>
          <option value="all">All Devices</option>
          <option value="category">Category</option>
          <option value="virtual">Virtual</option>
        </select>
        {dev.target_kind === 'all' ? (
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}
            title="Every imported virtual; category/virtual entries override it">
            every imported virtual
          </span>
        ) : (
          <select value={dev.target} style={{ fontSize: 12, minWidth: 160 }}
            onChange={(e) => set({ target: e.target.value })}>
            <option value="">— pick {dev.target_kind} —</option>
            {/* Keep a stored target visible even when the registry doesn't
              * list it (topology not loaded / renamed) — never blank it. */}
            {dev.target && !(dev.target_kind === 'category' ? categories : allVirtuals).includes(dev.target) && (
              <option value={dev.target}>{dev.target}</option>
            )}
            {(dev.target_kind === 'category' ? categories : allVirtuals).map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        )}
        <select value={effEffect} style={{ fontSize: 12, minWidth: 130 }}
          title={variant ? 'The effect this ⚡ step switches to (its params reset)' : undefined}
          onChange={(e) => {
            if (variant) setStep(variantIdx, { effect_type: e.target.value, params: {} });
            else set({ effect_type: e.target.value, params: {}, drift: {} });
          }}>
          <option value="">— effect —</option>
          {effectOptions.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        {effEffect === 'fish' && <HelpLink topic="fish-effect" />}
        {steps.length === 0 && dev.effect_type && (
          <button style={{ fontSize: 11 }} onClick={addStep}
            title="Stepped effect: switch to a DIFFERENT effect at/above an ⚡ intensity threshold">
            ⚡ Stepped effect…
          </button>
        )}
        <button className="danger" style={{ fontSize: 11, padding: '2px 8px', marginLeft: 'auto' }}
          onClick={onRemove}>✕ Remove entry</button>
      </div>

      {/* Stepped effect: variant strip — the params grid below edits the
        * highlighted variant; the fire picks one variant per its intensity. */}
      {steps.length > 0 && (
        <div style={{ marginBottom: 6 }}>
          <div className="param-section-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            Effect over ⚡ intensity <HelpLink topic="stepped-effect" />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <button className={variantIdx === -1 ? 'active' : ''} style={{ fontSize: 12 }}
              title="The base form — what fires below the first threshold (and with no intensity signal)"
              onClick={() => setVariantIdx(-1)}>
              {dev.effect_type || '—'} <small>&lt; {steps[0].threshold.toFixed(2)}</small>
            </button>
            {steps.map((s, i) => (
              <button key={i} className={variantIdx === i ? 'active' : ''} style={{ fontSize: 12 }}
                title="Fires at/above this ⚡ threshold, with its own params"
                onClick={() => setVariantIdx(i)}>
                {s.effect_type || '— pick effect —'} <small>≥ {s.threshold.toFixed(2)}</small>
              </button>
            ))}
            <button style={{ fontSize: 11 }} onClick={addStep} title="Add another threshold step">＋ step</button>
          </div>
          {variant && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4, fontSize: 12 }}>
              <span style={{ color: 'var(--text-muted)' }}>switches at ⚡ ≥</span>
              <input type="number" min={0.01} max={1} step={0.05} value={variant.threshold}
                style={{ width: 70 }}
                onChange={(e) => setStep(variantIdx, {
                  threshold: Math.min(1, Math.max(0.01, Number(e.target.value) || 0.01)),
                })} />
              <button className="danger" style={{ fontSize: 11, padding: '2px 8px' }}
                onClick={() => removeStep(variantIdx)}>✕ Remove step</button>
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                Colours, brightness and drift stay entry-level — they ride whichever effect the fire selects.
              </span>
            </div>
          )}
        </div>
      )}

      {/* Aspect-grouped params — the highlighted variant's set */}
      {effEffect && ASPECT_ORDER.filter((a) => byAspect.has(a)).map((aspect) => (
        <div key={aspect}>
          <div className="param-section-title">{ASPECT_TITLES[aspect]}</div>
          {byAspect.get(aspect)!.map(([name, meta]) => (
            <ParamRow key={name} name={name} meta={meta}
              value={effParams[name]}
              onChange={(v) => setParam(name, v)} />
          ))}
        </div>
      ))}

      {/* Colour assignment — the un-bindable value on this page */}
      <div className="param-section-title">Colours <HelpLink topic="colour-gradient-picker" /></div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <select value={dev.color.mode} style={{ fontSize: 12 }}
          title="Where colours come from when the scene fires — palette variation is the colour-set system's job"
          onChange={(e) => set({
            color: e.target.value === 'set'
              ? emptyColor()
              : { ...dev.color, mode: 'fixed', color_kind: dev.color.color_kind ?? 'solid' },
          })}>
          <option value="set">Colours from active Colour Set</option>
          <option value="fixed">Fixed colours</option>
        </select>
        {dev.color.mode === 'fixed' && (
          <>
            <ColorGradientPicker
              gradient
              value={dev.color.color_value ?? '#ffffff'}
              defaultColors={colorDefaults}
              swatchWidth={48}
              swatchHeight={30}
              title="Solid colour or gradient — click to build either"
              onChange={(v) => set({
                color: { ...dev.color, color_kind: v.includes('linear-gradient') ? 'gradient' : 'solid', color_value: v },
              })}
            />
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--text-muted)', cursor: 'pointer' }}>
              <input type="checkbox" checked={dev.color.bg_color != null}
                onChange={(e) => set({ color: { ...dev.color, bg_color: e.target.checked ? '#000000' : null } })} />
              BG
            </label>
            {dev.color.bg_color != null && (
              <ColorGradientPicker
                value={dev.color.bg_color}
                swatchWidth={48}
                swatchHeight={30}
                title="Background colour"
                onChange={(v) => set({ color: { ...dev.color, bg_color: v } })}
              />
            )}
          </>
        )}
      </div>

      {/* Brightness pair — bindable like any value */}
      <div className="param-section-title">Entry brightness</div>
      {(['brightness', 'background_brightness'] as const).map((field) => {
        const value = dev[field];
        const on = value !== null;
        return (
          <div key={field} className={`param-row${on ? '' : ' disabled'}`}>
            <span className="param-label" title="Click to enable/disable — unset leaves the device's value alone"
              onClick={() => set({ [field]: on ? null : 1 } as Partial<SceneDeviceConfig>)}>
              {field === 'brightness' ? 'Brightness' : 'BG Brightness'}
              {!on && <small> — unset</small>}
            </span>
            {on && (
              <BindableNumber value={value} min={0} max={1} step={0.01} slider
                onChange={(v) => set({ [field]: v } as Partial<SceneDeviceConfig>)} />
            )}
          </div>
        );
      })}
    </div>
  );
}

function ParamRow({ name, meta, value, onChange }: {
  name: string;
  meta: EffectParamMeta;
  value: SceneDeviceConfig['params'][string] | undefined;
  onChange: (v: SceneDeviceConfig['params'][string] | null) => void;
}) {
  const on = value !== undefined;
  const label = meta.label ?? name;
  const isNumeric = meta.type === 'numeric' || meta.type === 'integer';
  const isToggle = meta.type === 'toggle';
  const isOption = (meta.type === 'enum' || meta.type === 'string');
  const options = meta.options ?? [];

  return (
    <div className={`param-row${on ? '' : ' disabled'}`}>
      <span className="param-label"
        title={on ? 'Click to unset — the device keeps its own value'
          : `Click to enable at the effect's real default (${String(paramDefault(meta))})`}
        onClick={() => onChange(on ? null : paramDefault(meta))}>
        {label}
        {!on && <small> — {String(paramDefault(meta))}</small>}
      </span>
      {meta.help_topic && <HelpLink topic={meta.help_topic} />}
      {!on && isNumeric && meta.min !== undefined && meta.max !== undefined && (
        <input type="range" min={meta.min} max={meta.max} disabled
          value={typeof meta.default === 'number' ? meta.default : meta.min} readOnly />
      )}
      {on && isNumeric && (
        <BindableNumber
          value={value as number | import('../../types').ValueBinding}
          min={meta.min} max={meta.max}
          step={meta.type === 'integer' ? 1 : undefined}
          slider
          onChange={(v) => onChange(v)} />
      )}
      {on && isToggle && (
        <BindableToggle
          value={value as boolean | import('../../types').ValueBinding}
          onChange={(v) => onChange(v)}
          renderScalar={(v, setV) => (
            <input type="checkbox" checked={!!v} onChange={(e) => setV(e.target.checked)} />
          )} />
      )}
      {on && isOption && (options.length > 0 ? (
        <BindableOption
          value={value as string | import('../../types').ValueBinding}
          options={options}
          onChange={(v) => onChange(v)} />
      ) : (
        <input type="text" value={isBinding(value) ? '' : String(value ?? '')}
          style={{ width: 220, fontSize: 12 }}
          onChange={(e) => onChange(e.target.value)} />
      ))}
    </div>
  );
}
