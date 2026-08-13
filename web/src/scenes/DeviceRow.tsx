/** One SceneV2 device entry: target (category/virtual) + effect + params +
 * color assignment + brightness pair. Mirrors the Color Sets EntryRow idiom. */
import { useMemo } from 'react';
import { useGradients } from '../colorsets/queries';
import type { EffectConfig } from './queries';
import type { SceneDeviceConfig } from './types';
import { emptyColor } from './types';

function Toggle({ label, on, onChange }: { label: string; on: boolean; onChange: (v: boolean) => void }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--text-muted)', cursor: 'pointer' }}>
      <input type="checkbox" checked={on} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

export default function DeviceRow({
  dev,
  config,
  onChange,
  onRemove,
}: {
  dev: SceneDeviceConfig;
  config: EffectConfig | undefined;
  onChange: (d: SceneDeviceConfig) => void;
  onRemove: () => void;
}) {
  const { data: gradients = [] } = useGradients();
  const set = (patch: Partial<SceneDeviceConfig>) => onChange({ ...dev, ...patch });

  const categories = Object.keys(config?.categories ?? {});
  const allVirtuals = useMemo(
    () => [...new Set(categories.flatMap((c) => config?.categories[c]?.virtuals ?? []))],
    [config, categories],
  );
  const allEffects = Object.keys(config?.effects ?? {});
  // Category entries offer the category's own effect list when it has one.
  const effectOptions =
    dev.target_kind === 'category'
      ? (config?.categories[dev.target]?.effects?.length
          ? config.categories[dev.target].effects
          : allEffects)
      : allEffects;

  const paramMeta = config?.effects[dev.effect_type]?.params ?? {};
  const isSolid = (dev.color.color_kind ?? 'solid') === 'solid';
  const inLib = gradients.some((g) => g.value === dev.color.color_value);

  const setParam = (name: string, value: number | boolean | null) => {
    const params = { ...dev.params };
    if (value === null) delete params[name];
    else params[name] = value;
    set({ params });
  };

  return (
    <div style={{ background: 'var(--surface2)', padding: 8, borderRadius: 'var(--radius)', marginBottom: 8 }}>
      {/* Target + effect */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <select value={dev.target_kind} style={{ fontSize: 12 }}
          onChange={(e) => set({ target_kind: e.target.value as 'category' | 'virtual', target: '' })}>
          <option value="category">Category</option>
          <option value="virtual">Virtual</option>
        </select>
        <select value={dev.target} style={{ fontSize: 12, minWidth: 160 }}
          onChange={(e) => set({ target: e.target.value })}>
          <option value="">— pick {dev.target_kind} —</option>
          {(dev.target_kind === 'category' ? categories : allVirtuals).map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <select value={dev.effect_type} style={{ fontSize: 12, minWidth: 130 }}
          onChange={(e) => set({ effect_type: e.target.value, params: {} })}>
          <option value="">— effect —</option>
          {effectOptions.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <button className="danger" style={{ fontSize: 11, padding: '2px 8px', marginLeft: 'auto' }}
          title="Remove device entry" onClick={onRemove}>✕</button>
      </div>

      {/* Effect params (from the effect registry; unset = leave alone) */}
      {!!Object.keys(paramMeta).length && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginTop: 6 }}>
          {Object.entries(paramMeta).map(([name, meta]) => {
            const val = dev.params[name];
            const on = val !== undefined;
            return (
              <span key={name} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <Toggle label={meta.label ?? name} on={on}
                  onChange={(en) => setParam(name, en ? (meta.type === 'toggle' ? true : (meta.min ?? 0)) : null)} />
                {on && meta.type === 'toggle' && (
                  <input type="checkbox" checked={!!val} onChange={(e) => setParam(name, e.target.checked)} />
                )}
                {on && meta.type !== 'toggle' && (
                  <input type="number" value={Number(val)} step="any"
                    min={meta.min} max={meta.max}
                    style={{ width: 64, fontSize: 12 }}
                    onChange={(e) => setParam(name, Number(e.target.value))} />
                )}
              </span>
            );
          })}
        </div>
      )}

      {/* Color assignment */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 6 }}>
        <select value={dev.color.mode} style={{ fontSize: 12 }}
          title="Where colors come from when the scene fires"
          onChange={(e) => set({
            color: e.target.value === 'set'
              ? emptyColor()
              : { ...dev.color, mode: 'fixed', color_kind: dev.color.color_kind ?? 'solid' },
          })}>
          <option value="set">Colors from active Color Set</option>
          <option value="fixed">Fixed colors</option>
        </select>
        {dev.color.mode === 'fixed' && (
          <>
            <select value={isSolid ? 'solid' : 'gradient'} style={{ fontSize: 12 }}
              onChange={(e) => {
                const solid = e.target.value === 'solid';
                set({ color: { ...dev.color, color_kind: solid ? 'solid' : 'gradient', color_value: solid ? '#ffffff' : gradients[0]?.value ?? null } });
              }}>
              <option value="solid">Solid</option>
              <option value="gradient">Gradient</option>
            </select>
            {isSolid ? (
              <input type="color" value={dev.color.color_value ?? '#ffffff'} style={{ width: 48, height: 30, padding: 1 }}
                onChange={(e) => set({ color: { ...dev.color, color_value: e.target.value } })} />
            ) : (
              <select value={dev.color.color_value ?? ''} style={{ width: 180, fontSize: 12 }}
                onChange={(e) => set({ color: { ...dev.color, color_value: e.target.value } })}>
                {dev.color.color_value && !inLib && <option value={dev.color.color_value}>(unsaved)</option>}
                {gradients.map((g) => <option key={g.id} value={g.value}>{g.name}</option>)}
              </select>
            )}
            <Toggle label="BG" on={dev.color.bg_color != null}
              onChange={(on) => set({ color: { ...dev.color, bg_color: on ? '#000000' : null } })} />
            {dev.color.bg_color != null && (
              <input type="color" value={dev.color.bg_color} style={{ width: 48, height: 30, padding: 1 }}
                onChange={(e) => set({ color: { ...dev.color, bg_color: e.target.value } })} />
            )}
          </>
        )}
      </div>

      {/* Brightness pair */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 6 }}>
        <Toggle label="Brightness" on={dev.brightness != null}
          onChange={(on) => set({ brightness: on ? 1 : null })} />
        {dev.brightness != null && (
          <input type="range" min={0} max={1} step={0.01} value={dev.brightness} style={{ width: 120 }}
            title={`${Math.round(dev.brightness * 100)}%`}
            onChange={(e) => set({ brightness: Number(e.target.value) })} />
        )}
        <Toggle label="BG Brightness" on={dev.background_brightness != null}
          onChange={(on) => set({ background_brightness: on ? 1 : null })} />
        {dev.background_brightness != null && (
          <input type="range" min={0} max={1} step={0.01} value={dev.background_brightness} style={{ width: 120 }}
            title={`${Math.round(dev.background_brightness * 100)}%`}
            onChange={(e) => set({ background_brightness: Number(e.target.value) })} />
        )}
      </div>
    </div>
  );
}
