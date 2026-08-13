/** Scenes (SPECTRA SceneV2) — full device-aware scene editor. Two-pane layout
 * matching Color Sets / Devices; edits live in local drafts until Save.
 * A SceneV2 states outright what every targeted device shows (effect, params,
 * colors, brightness) plus flare response bands and phase choreography; the
 * legacy scene_update events on the Events page are untouched by this page. */
import { useMemo, useState } from 'react';
import CollapsibleCard from '../components/CollapsibleCard';
import CurveLab from '../components/CurveLab';
import { useToast } from '../components/Toast';
import { LabelsInput } from '../components/forms/inputs';
import HelpLink from '../help/HelpLink';
import { uuid } from '../lib/uid';
import { useColorSetCards, useSaveColorSet } from '../colorsets/queries';
import DeviceRow from './DeviceRow';
import {
  fireSceneV2, useDeleteSceneV2, useEffectConfig, useSaveSceneV2, useScenesV2,
  useWheelPositions,
} from './queries';
import { emptyBand, emptyDevice, newScene, type FireResult, type SceneV2 } from './types';

const CURVES = ['linear', 'ease_in', 'ease_out', 'pulse'] as const;

export default function ScenesPage() {
  const toast = useToast();
  const { data: serverScenes = [], isLoading } = useScenesV2();
  const { data: config } = useEffectConfig();
  const { data: setCards = [] } = useColorSetCards();
  const { data: wheel = {} } = useWheelPositions();
  const saveMut = useSaveSceneV2();
  const delMut = useDeleteSceneV2();
  const saveSetMut = useSaveColorSet();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [drafts, setDrafts] = useState<Record<string, SceneV2>>({});
  const [fireResult, setFireResult] = useState<FireResult | null>(null);

  const scenes = useMemo(() => {
    const merged = serverScenes.map((s) => drafts[s.id] ?? s);
    const serverIds = new Set(serverScenes.map((s) => s.id));
    for (const d of Object.values(drafts)) if (!serverIds.has(d.id)) merged.push(d);
    return merged;
  }, [serverScenes, drafts]);

  const scene = scenes.find((s) => s.id === selectedId) ?? null;
  const setScene = (next: SceneV2) => setDrafts((d) => ({ ...d, [next.id]: next }));

  const visible = useMemo(() => {
    const q = search.toLowerCase();
    return scenes.filter((s) =>
      s.name.toLowerCase().includes(q) || (s.labels ?? []).some((l) => l.toLowerCase().includes(q)));
  }, [scenes, search]);

  const colorSets = setCards.filter((c) => c.kind === 'set');

  const save = async (s: SceneV2 | null = scene) => {
    if (!s) return false;
    try {
      await saveMut.mutateAsync(s);
      setDrafts((d) => {
        const { [s.id]: _, ...rest } = d;
        return rest;
      });
      toast('Saved', 'success');
      return true;
    } catch (e) {
      toast(`Save failed: ${e}`, 'error');
      return false;
    }
  };

  const del = async () => {
    if (!scene) return;
    if (!confirm(`Delete scene "${scene.name}"?`)) return;
    try {
      if (serverScenes.some((s) => s.id === scene.id)) await delMut.mutateAsync(scene.id);
      setDrafts((d) => {
        const { [scene.id]: _, ...rest } = d;
        return rest;
      });
      setSelectedId(null);
      setFireResult(null);
    } catch (e) {
      toast(`Delete failed: ${e}`, 'error');
    }
  };

  const duplicate = () => {
    if (!scene) return;
    const copy: SceneV2 = JSON.parse(JSON.stringify(scene));
    copy.id = uuid();
    copy.name = `${scene.name} (copy)`;
    copy.devices = copy.devices.map((d) => ({ ...d, id: uuid() }));
    setDrafts((d) => ({ ...d, [copy.id]: copy }));
    setSelectedId(copy.id);
  };

  /** Test-fire = save, then compile through the LedFX-client seam WITHOUT
   * contacting devices (dry run); the compiled writes render below. */
  const testFire = async () => {
    if (!scene) return;
    if (!(await save())) return;
    try {
      const res = await fireSceneV2(scene.id, true);
      setFireResult(res);
      toast(`Compiled ${res.writes.length} virtual write${res.writes.length === 1 ? '' : 's'} (dry run)`, 'success');
    } catch (e) {
      toast(`Test fire failed: ${e}`, 'error');
    }
  };

  const create = () => {
    const s = newScene(uuid());
    setDrafts((d) => ({ ...d, [s.id]: s }));
    setSelectedId(s.id);
    setFireResult(null);
  };

  const toggleSetAccepted = (setId: string) => {
    if (!scene) return;
    const has = scene.accepted_set_ids.includes(setId);
    setScene({
      ...scene,
      accepted_set_ids: has
        ? scene.accepted_set_ids.filter((x) => x !== setId)
        : [...scene.accepted_set_ids, setId],
    });
  };

  const toggleGlobalOptOut = async (setId: string) => {
    const card = setCards.find((c) => c.id === setId);
    if (!card) return;
    try {
      await saveSetMut.mutateAsync({ ...card, scene_v2_opt_out: !card.scene_v2_opt_out });
      toast(card.scene_v2_opt_out ? 'Set re-enabled for scenes' : 'Set opted out of all scenes', 'success');
    } catch (e) {
      toast(`Update failed: ${e}`, 'error');
    }
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 16, alignItems: 'start' }}>
      {/* ── Scene list ── */}
      <div className="card" style={{ minWidth: 0, maxHeight: 'calc(100vh - 80px)', display: 'flex', flexDirection: 'column' }}>
        <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          Scenes <HelpLink topic="scenes-v2" />
          <button className="primary" style={{ marginLeft: 'auto', fontSize: 11, padding: '3px 10px' }} onClick={create}>
            + Scene
          </button>
        </div>
        <div className="field">
          <input type="text" placeholder="Search…" value={search} style={{ width: '100%' }}
            onChange={(e) => setSearch(e.target.value)} />
        </div>
        <div style={{ overflowY: 'auto', flex: 1, minHeight: 0 }}>
          {isLoading && <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: 10 }}>Loading…</div>}
          {!isLoading && !visible.length && (
            <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: 10 }}>
              No scenes yet — create one with + Scene.
            </div>
          )}
          {visible.map((s) => (
            <div key={s.id} className={`pane-row${s.id === selectedId ? ' selected' : ''}`}
              onClick={() => { setSelectedId(s.id); setFireResult(null); }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500 }}>
                  {s.name}
                  {drafts[s.id] && <span title="Unsaved changes" style={{ color: 'var(--accent2)' }}> •</span>}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  {s.devices.length} device entr{s.devices.length === 1 ? 'y' : 'ies'}
                  {[...new Set(s.devices.map((d) => d.effect_type).filter(Boolean))].length > 1 && ' · multi-effect'}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Editor ── */}
      {scene ? (
        <div className="card" style={{ maxHeight: 'calc(100vh - 80px)', overflowY: 'auto' }}>
          <div className="card-title">Edit Scene</div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
            <button className="primary" onClick={() => void save()}>Save</button>
            <button style={{ fontSize: 12 }} onClick={duplicate}>⧉ Duplicate</button>
            <button style={{ fontSize: 12 }} title="Compile through the LedFX client seam without touching devices"
              onClick={() => void testFire()}>
              ▶ Test Fire (dry run)
            </button>
            <button className="danger" style={{ fontSize: 12 }} onClick={() => void del()}>✕ Delete</button>
          </div>

          <div className="field">
            <label>Name</label>
            <input type="text" value={scene.name} style={{ width: '100%' }}
              onChange={(e) => setScene({ ...scene, name: e.target.value })} />
          </div>
          <div className="field">
            <label>Labels (comma separated)</label>
            <LabelsInput value={scene.labels ?? []} placeholder="e.g. chill, drop"
              onChange={(labels) => setScene({ ...scene, labels })} />
          </div>

          {/* Devices */}
          <div className="card-title" style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
            Devices
            <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 400 }}>
              — each entry may use a different effect
            </span>
            <button style={{ marginLeft: 'auto', fontSize: 11, padding: '3px 10px' }}
              onClick={() => setScene({ ...scene, devices: [...scene.devices, emptyDevice(uuid())] })}>
              + Device entry
            </button>
          </div>
          {!scene.devices.length && (
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
              No device entries — the scene fires nothing yet.
            </div>
          )}
          {scene.devices.map((dev, i) => (
            <DeviceRow key={dev.id} dev={dev} config={config}
              onChange={(d) => setScene({ ...scene, devices: scene.devices.map((x, j) => (j === i ? d : x)) })}
              onRemove={() => setScene({ ...scene, devices: scene.devices.filter((_, j) => j !== i) })} />
          ))}

          {/* Flare response */}
          <div className="card-title" style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
            Flare response
            <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 400 }}>
              — per intensity band
            </span>
            <button style={{ marginLeft: 'auto', fontSize: 11, padding: '3px 10px' }}
              onClick={() => setScene({ ...scene, flare_bands: [...scene.flare_bands, emptyBand()] })}>
              + Band
            </button>
          </div>
          {scene.flare_bands.map((b, i) => {
            const setBand = (patch: Partial<typeof b>) => setScene({
              ...scene,
              flare_bands: scene.flare_bands.map((x, j) => (j === i ? { ...x, ...patch } : x)),
            });
            return (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', background: 'var(--surface2)', padding: 8, borderRadius: 'var(--radius)', marginBottom: 6 }}>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Intensity</span>
                <input type="number" min={0} max={1} step={0.05} value={b.intensity_min}
                  style={{ width: 60, fontSize: 12 }}
                  onChange={(e) => setBand({ intensity_min: Number(e.target.value) })} />
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>to</span>
                <input type="number" min={0} max={1} step={0.05} value={b.intensity_max}
                  style={{ width: 60, fontSize: 12 }}
                  onChange={(e) => setBand({ intensity_max: Number(e.target.value) })} />
                <select value={b.curve} style={{ fontSize: 12 }}
                  onChange={(e) => setBand({ curve: e.target.value as typeof b.curve })}>
                  {CURVES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>gain</span>
                <input type="number" min={0} step={0.1} value={b.gain} style={{ width: 60, fontSize: 12 }}
                  onChange={(e) => setBand({ gain: Number(e.target.value) })} />
                <button className="danger" style={{ fontSize: 11, padding: '2px 8px', marginLeft: 'auto' }}
                  onClick={() => setScene({ ...scene, flare_bands: scene.flare_bands.filter((_, j) => j !== i) })}>✕</button>
              </div>
            );
          })}

          {/* Choreography */}
          <div className="card-title" style={{ marginTop: 12 }}>Phase choreography</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, cursor: 'pointer' }}>
              <input type="checkbox" checked={scene.choreography.enabled}
                onChange={(e) => setScene({ ...scene, choreography: { ...scene.choreography, enabled: e.target.checked } })} />
              Enabled
            </label>
            {scene.choreography.enabled && (
              <>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>transition (ms)</span>
                <input type="number" min={0} max={20000} step={50} value={scene.choreography.transition_ms}
                  style={{ width: 80, fontSize: 12 }}
                  onChange={(e) => setScene({ ...scene, choreography: { ...scene.choreography, transition_ms: Number(e.target.value) } })} />
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>mode</span>
                <input type="text" value={scene.choreography.transition_mode} style={{ width: 90, fontSize: 12 }}
                  onChange={(e) => setScene({ ...scene, choreography: { ...scene.choreography, transition_mode: e.target.value } })} />
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}
                  title="Crossfade fraction where the visual payoff lands — the engine fires early so the payoff hits the beat">
                  anchor
                </span>
                <input type="number" min={0} max={1} step={0.05} value={scene.choreography.anchor_frac}
                  style={{ width: 60, fontSize: 12 }}
                  onChange={(e) => setScene({ ...scene, choreography: { ...scene.choreography, anchor_frac: Number(e.target.value) } })} />
              </>
            )}
          </div>

          {/* Color Set filter */}
          <div className="card-title" style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
            Color Set filter <HelpLink topic="scenes-v2-set-filter" />
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, cursor: 'pointer', marginBottom: 6 }}>
            <input type="checkbox" checked={scene.accept_all_sets}
              onChange={(e) => setScene({ ...scene, accept_all_sets: e.target.checked })} />
            Accept every Color Set (that hasn't opted out globally)
          </label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 260, overflowY: 'auto' }}>
            {colorSets.map((c) => {
              const w = wheel[c.id];
              const optedOut = !!c.scene_v2_opt_out;
              const checked = scene.accept_all_sets || scene.accepted_set_ids.includes(c.id);
              return (
                <div key={c.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, padding: '2px 4px', opacity: optedOut ? 0.5 : 1 }}>
                  <input type="checkbox" checked={checked && !optedOut}
                    disabled={scene.accept_all_sets || optedOut}
                    title={optedOut ? 'Opted out of all scenes' : undefined}
                    onChange={() => toggleSetAccepted(c.id)} />
                  <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.name}</span>
                  {w?.rainbow && <span title={`Rainbow set — hues span ${w.span_deg}°, no single wheel position`}>🌈</span>}
                  {w && !w.rainbow && w.position_deg != null && (
                    <span title={`Wheel position ${w.position_deg}° (span ${w.span_deg}°, R=${w.resultant})`}
                      style={{
                        width: 14, height: 14, borderRadius: '50%', flexShrink: 0,
                        border: '1px solid var(--border)',
                        background: `hsl(${w.position_deg}, 85%, 55%)`,
                      }} />
                  )}
                  <button style={{ fontSize: 10, padding: '1px 6px' }}
                    title={optedOut
                      ? 'This set has opted out of ALL scenes — click to re-enable'
                      : 'Opt this set out of ALL scenes (global, affects every scene)'}
                    onClick={() => void toggleGlobalOptOut(c.id)}>
                    {optedOut ? '🚫 opted out' : 'opt out'}
                  </button>
                </div>
              );
            })}
          </div>

          {/* Compiled writes from the last test fire */}
          {fireResult && (
            <>
              <div className="card-title" style={{ marginTop: 12 }}>
                Test fire result — {fireResult.writes.length} virtual write{fireResult.writes.length === 1 ? '' : 's'} (dry run, nothing sent)
              </div>
              {!fireResult.writes.length && (
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  Nothing compiled — check that entries have a target and an effect, and that categories contain virtuals.
                </div>
              )}
              <pre style={{ fontSize: 11, background: 'var(--surface2)', padding: 8, borderRadius: 'var(--radius)', overflowX: 'auto', maxHeight: 300 }}>
                {JSON.stringify(fireResult.writes, null, 2)}
              </pre>
            </>
          )}
        </div>
      ) : (
        <div className="card" style={{ color: 'var(--text-muted)', fontSize: 13 }}>
          Select a scene on the left, or create one. A SceneV2 is a full device-aware
          configuration — per device: effect, params, colors, brightness — plus flare
          response and phase choreography. <HelpLink topic="scenes-v2" />
        </div>
      )}

      {/* Dev affordance: sequencer curve-editor preview (SPECTRA sequencing
        * core — attachment UI awaits the open design decisions). */}
      <div style={{ gridColumn: '1 / -1' }}>
        <CollapsibleCard id="scenes-curve-lab" defaultCollapsed
          title={<>Curve editor lab <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 400 }}>— dev preview</span></>}>
          <CurveLab />
        </CollapsibleCard>
      </div>
    </div>
  );
}
