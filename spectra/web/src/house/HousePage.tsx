/** HOUSE LIGHTING (/house) — the always-on resting look (spectra/services/
 * house.py is the binding statement; spectra/models/house_mode.py the shape).
 *
 * Left: his modes, each with a "Switch to" press (a person's pick — it holds
 * until Home Assistant's lighting mode next changes). Right: the chosen
 * mode as small cards — scenes, colours, per-fixture settings, the Hue Hold
 * looks, what music does, how changes glide, and the Home Assistant words it
 * answers to. Top: "Now" — which mode, who set it, what it is doing, and
 * why it is not applied when it is not.
 *
 * Nothing here takes or releases the room: a mode set while SPECTRA does
 * not hold the room is recorded and applies on take-back, and the Now panel
 * says exactly that. Every field is also reachable through Sonic (the 💬). */
import { useCallback, useEffect, useState } from 'react';
import { apiDel, apiGet, apiPost } from '../api/client';
import HelpLink from '../help/HelpLink';
import SonicChatPopover from '../components/SonicChatPopover';
import { useToast } from '../components/Toast';
import { useEngineStatus, useScenes, useSpotColorSets } from '../queries';
import {
  blankMode, kelvinToHex, manualLine, MUSIC_HUE_WORDS, MUSIC_WORDS, phaseLine, seamLines, sourceWord,
} from './houseSummary';
import type {
  FixtureHook, HouseMode, HouseModesResponse, HouseTargets, HueLook, LightingStatus,
  SetModeResponse,
} from './types';

const NEW_ID = '__new__';

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}

function num(v: string): number | null {
  return v === '' ? null : Number(v);
}

export default function HousePage() {
  const toast = useToast();
  const { data: engine, refetch } = useEngineStatus();
  const lighting = (engine as { lighting?: LightingStatus } | undefined)?.lighting;
  const [lib, setLib] = useState<HouseModesResponse | null>(null);
  const [targets, setTargets] = useState<HouseTargets | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<HouseMode | null>(null);
  const [dirty, setDirty] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    const r = await apiGet<HouseModesResponse>('/house/modes');
    setLib(r);
    return r;
  }, []);

  useEffect(() => {
    void reload().then((r) => setSelected((s) => s ?? r.current_mode_id ?? r.modes[0]?.id ?? null))
      .catch((e) => toast(String(e), 'error'));
    void apiGet<HouseTargets>('/house/targets').then(setTargets).catch(() => undefined);
  }, [reload, toast]);

  useEffect(() => {
    if (selected === NEW_ID) return;
    const m = lib?.modes.find((x) => x.id === selected);
    setDraft(m ? clone(m) : null);
    setDirty(false);
    setWarnings([]);
  }, [selected, lib]);

  const edit = (fn: (d: HouseMode) => void) => {
    setDraft((d) => {
      if (!d) return d;
      const next = clone(d);
      fn(next);
      return next;
    });
    setDirty(true);
  };

  const save = async () => {
    if (!draft) return;
    setBusy(true);
    try {
      const r = await apiPost<{ mode: HouseMode; warnings: string[] }>('/house/modes', draft);
      setWarnings(r.warnings);
      const lib2 = await reload();
      setSelected(r.mode.id ?? null);
      setDraft(clone(lib2.modes.find((m) => m.id === r.mode.id) ?? r.mode));
      setDirty(false);
      toast(`Saved ${r.mode.name}`, 'success');
    } catch (e) {
      toast(String(e), 'error');
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!draft?.id || !window.confirm(`Delete the mode "${draft.name}"?`)) return;
    await apiDel(`/house/modes/${draft.id}`).catch((e) => toast(String(e), 'error'));
    const r = await reload();
    setSelected(r.modes[0]?.id ?? null);
  };

  const switchTo = async (modeId: string | null) => {
    setBusy(true);
    try {
      const r = await apiPost<SetModeResponse>('/house/mode',
        modeId ? { mode: modeId, source: 'spectra' } : { clear: true, source: 'spectra' });
      toast(r.status === 'cleared' ? 'Mode cleared' : `${r.lighting.mode?.name ?? 'Mode'}: ${r.status}`,
        'success');
      await refetch();
      await reload();
    } catch (e) {
      toast(String(e), 'error');
    } finally {
      setBusy(false);
    }
  };

  const current = lib?.current_mode_id ?? null;

  return (
    <div className="house-page">
      <div className="house-head">
        <h2>House lighting <HelpLink topic="house" /></h2>
        <span className="muted">The room&apos;s resting look — music and the Light Show play on top of it. <HelpLink topic="house-page" title="How this page works" /></span>
      </div>

      <NowPanel lighting={lighting} busy={busy} areas={targets?.hue_areas ?? []}
        onClear={() => void switchTo(null)} />

      <div className="house-layout">
        <div className="card house-modes">
          <div className="house-modes-head">
            <strong>Modes</strong> <HelpLink topic="house-modes" />
            <button onClick={() => {
              if (dirty && !window.confirm('Discard unsaved changes?')) return;
              setSelected(NEW_ID);
              setDraft(blankMode('New mode'));
              setDirty(true);
            }}>+ New</button>
          </div>
          {lib && lib.modes.length === 0 && (
            <p className="muted">No modes yet. A mode needs a scene, colours and fixture settings to give it a look.</p>
          )}
          <ul>
            {(lib?.modes ?? []).map((m) => (
              <li key={m.id}>
                <button className={m.id === selected ? 'active' : ''} onClick={() => {
                  if (dirty && !window.confirm('Discard unsaved changes?')) return;
                  setSelected(m.id ?? null);
                }}>
                  {m.id === current && <span className="house-now-dot" title="The mode that is set">● </span>}
                  {m.name}
                  {m.ha_aliases.length > 0 && <span className="muted"> · {m.ha_aliases.join(', ')}</span>}
                </button>
                <button className="house-switch" disabled={busy || m.id === current}
                  onClick={() => void switchTo(m.id ?? null)}
                  title="Switch to this mode now — holds until Home Assistant's lighting mode next changes">
                  {m.id === current ? 'Set' : 'Switch to'}
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="card house-editor">
          {!draft && <p className="muted">Choose a mode, or make a new one.</p>}
          {draft && (
            <ModeEditor draft={draft} edit={edit} targets={targets} dirty={dirty} busy={busy}
              warnings={warnings} onSave={() => void save()} onDelete={() => void remove()} />
          )}
        </div>
      </div>
      <SonicChatPopover helpTopic="sonic-house" />
    </div>
  );
}

function NowPanel({ lighting, busy, areas, onClear }: {
  lighting: LightingStatus | undefined; busy: boolean;
  areas: { id: string; name: string }[]; onClear: () => void;
}) {
  const areaName = (id: string) => (id === '*' ? 'every area' : areas.find((a) => a.id === id)?.name ?? id);
  const manual = manualLine(lighting);
  return (
    <div className={`card house-now house-phase-${lighting?.phase ?? 'inactive'}`}>
      <div className="house-now-head">
        <strong>Now</strong> <HelpLink topic="house-now" />
        {lighting?.mode && (
          <button disabled={busy} onClick={onClear}
            title="Clear the mode — the room behaves as it always has. Holds until Home Assistant's lighting mode next changes.">
            Clear mode
          </button>
        )}
      </div>
      {!lighting && <p className="muted">Reading…</p>}
      {lighting && (
        <ul>
          <li>
            Mode: <b>{lighting.mode?.name ?? 'none'}</b>
            {lighting.mode && <> · set by {sourceWord(lighting.source)}</>}
            {lighting.since_ms && <span className="muted"> · since {new Date(lighting.since_ms).toLocaleTimeString()}</span>}
          </li>
          <li>{phaseLine(lighting)}</li>
          {manual && <li className="muted">{manual}</li>}
          {lighting.ha_value && (
            <li className="muted">
              Home Assistant last said &quot;{lighting.ha_value}&quot;
              {lighting.ha_mapped_mode ? ` (→ ${lighting.ha_mapped_mode})` : ' — no mode answers to it'}
              <HelpLink topic="house-ha" />
            </li>
          )}
          {lighting.scene && lighting.active && <li>Scene: {lighting.scene.name}
            {lighting.next_scene_in_s != null && <span className="muted"> · next in {Math.ceil(lighting.next_scene_in_s / 60)} min</span>}
          </li>}
          {lighting.fixtures && Object.keys(lighting.fixtures.levels).length > 0 && (
            <li className="muted">Levels: {Object.entries(lighting.fixtures.levels).map(([d, v]) => `${d} ${v}%`).join(' · ')}</li>
          )}
          {lighting.fixtures && lighting.fixtures.off.length > 0 && (
            <li className="muted">Off: {lighting.fixtures.off.join(', ')}</li>
          )}
          {lighting.fixtures && Object.keys(lighting.fixtures.caps).length > 0 && (
            <li className="muted">Frame-rate caps: {Object.entries(lighting.fixtures.caps).map(([d, v]) => `${d} ${v} fps`).join(' · ')}</li>
          )}
          {lighting.hue && lighting.hue.looks.length > 0 && (
            <li className="muted">Hue Hold: {lighting.hue.looks.map((l) => `${areaName(l.area)} ${l.look}${l.mirek ? ` ${Math.round(1e6 / l.mirek)} K` : l.color ? ` ${l.color}` : ''}`).join(' · ')}</li>
          )}
          {lighting.problems.map((p) => <li key={p} className="house-problem">⚠ {p}</li>)}
          {lighting.clock_mode && lighting.mode && lighting.clock_mode.id !== lighting.mode.id && (
            <li className="muted">Underneath: {lighting.clock_mode.name} — it returns when the media centre stops.</li>
          )}
        </ul>
      )}
      {lighting && <SeamLines lighting={lighting} />}
    </div>
  );
}

/** What Home Assistant has told Spectra about the fixtures (phase 2): the
 * TV strip lent to Hyperion, the media centre, Serenity's voice, a fixture
 * switched off, a brightness Spectra had to put back. Read-only — Home
 * Assistant and its buttons are the controls. */
function SeamLines({ lighting }: { lighting: LightingStatus }) {
  const lines = seamLines(lighting);
  if (!lines.length) return null;
  return (
    <div className="house-seam">
      <strong>From Home Assistant</strong> <HelpLink topic="house-ha-seam" />
      <ul>{lines.map((l) => <li key={l} className="muted">{l}</li>)}</ul>
    </div>
  );
}

function ModeEditor({ draft, edit, targets, dirty, busy, warnings, onSave, onDelete }: {
  draft: HouseMode; edit: (fn: (d: HouseMode) => void) => void; targets: HouseTargets | null;
  dirty: boolean; busy: boolean; warnings: string[]; onSave: () => void; onDelete: () => void;
}) {
  const scenes = useScenes().data ?? [];
  const colorSets = useSpotColorSets().data ?? [];
  const [aliases, setAliases] = useState(draft.ha_aliases.join(', '));
  useEffect(() => setAliases(draft.ha_aliases.join(', ')), [draft.id]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="house-editor-body">
      <div className="house-editor-head">
        <input type="text" aria-label="Mode name" value={draft.name}
          onChange={(e) => edit((d) => { d.name = e.target.value; })} />
        <button className="primary" disabled={!dirty || busy} onClick={onSave}>Save</button>
        {draft.id && <button className="danger" disabled={busy} onClick={onDelete}>Delete</button>}
      </div>
      {warnings.length > 0 && <ul className="house-warnings">{warnings.map((w) => <li key={w}>⚠ {w}</li>)}</ul>}

      <section className="house-section">
        <h4>Home Assistant <HelpLink topic="house-ha" /></h4>
        <label className="house-field">
          <span>Lighting-mode words this answers to</span>
          <input type="text" value={aliases} placeholder="e.g. Daytime"
            onChange={(e) => {
              setAliases(e.target.value);
              edit((d) => { d.ha_aliases = e.target.value.split(',').map((s) => s.trim()).filter(Boolean); });
            }} />
        </label>
      </section>

      <section className="house-section">
        <h4>Scenes <HelpLink topic="house-scenes-colours" /></h4>
        {draft.scenes.map((p, i) => (
          <div key={i} className="house-row">
            <select value={p.scene_id} aria-label="Scene"
              onChange={(e) => edit((d) => { d.scenes[i].scene_id = e.target.value; })}>
              {!scenes.some((s) => s.id === p.scene_id) && <option value={p.scene_id}>(missing scene)</option>}
              {scenes.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <label className="house-inline">weight
              <input type="number" min={0} max={100} step={0.5} value={p.weight}
                onChange={(e) => edit((d) => { d.scenes[i].weight = Number(e.target.value); })} />
            </label>
            <button aria-label="Remove scene" onClick={() => edit((d) => { d.scenes.splice(i, 1); })}>✕</button>
          </div>
        ))}
        <div className="house-row">
          <select value="" aria-label="Add a scene" onChange={(e) => {
            const id = e.target.value;
            if (id) edit((d) => { d.scenes.push({ scene_id: id, weight: 1 }); });
          }}>
            <option value="">+ Add a scene…</option>
            {scenes.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <label className="house-inline">change every
            <input type="number" min={0} max={1440} value={draft.flow.scene_every_min}
              onChange={(e) => edit((d) => { d.flow.scene_every_min = Number(e.target.value); })} /> min
          </label>
        </div>
      </section>

      <section className="house-section">
        <h4>Colours <HelpLink topic="house-scenes-colours" /></h4>
        {draft.color_sets.map((p, i) => (
          <div key={i} className="house-row">
            <select value={p.card_id} aria-label="Colour set or group"
              onChange={(e) => edit((d) => { d.color_sets[i].card_id = e.target.value; })}>
              {!colorSets.some((c) => c.id === p.card_id) && <option value={p.card_id}>(missing colour set)</option>}
              {colorSets.map((c) => <option key={c.id} value={c.id}>{c.kind === 'group' ? '▣ ' : ''}{c.name}</option>)}
            </select>
            <label className="house-inline">weight
              <input type="number" min={0} max={100} step={0.5} value={p.weight}
                onChange={(e) => edit((d) => { d.color_sets[i].weight = Number(e.target.value); })} />
            </label>
            <button aria-label="Remove colour" onClick={() => edit((d) => { d.color_sets.splice(i, 1); })}>✕</button>
          </div>
        ))}
        <div className="house-row">
          <select value="" aria-label="Add colours" onChange={(e) => {
            const id = e.target.value;
            if (id) edit((d) => { d.color_sets.push({ card_id: id, weight: 1 }); });
          }}>
            <option value="">+ Add a colour set or group…</option>
            {colorSets.map((c) => <option key={c.id} value={c.id}>{c.kind === 'group' ? '▣ ' : ''}{c.name}</option>)}
          </select>
          <label className="house-inline">drift
            <input type="number" min={0} max={360} value={draft.flow.journey_deg_per_min}
              onChange={(e) => edit((d) => { d.flow.journey_deg_per_min = Number(e.target.value); })} /> °/min
          </label>
        </div>
      </section>

      <section className="house-section">
        <h4>Fixtures <HelpLink topic="house-fixtures" /></h4>
        {draft.fixtures.map((h, i) => (
          <FixtureRow key={i} hook={h} targets={targets}
            onChange={(next) => edit((d) => { d.fixtures[i] = next; })}
            onRemove={() => edit((d) => { d.fixtures.splice(i, 1); })} />
        ))}
        <button onClick={() => edit((d) => {
          d.fixtures.push({ target: { kind: 'everything', id: null }, level: null, motion: null, fps: null, off: false, music_level: null });
        })}>+ Add a fixture setting</button>
        {targets && !targets.live && <p className="muted">The live room is down — fixture names are unknown until SPECTRA holds the room.</p>}
      </section>

      <section className="house-section">
        <h4>Hue Hold <HelpLink topic="house-hue" /></h4>
        {draft.hue.length === 0 && <p className="muted">No Hue looks — Hue follows the Hue Hold switch on the room bar, as it does today.</p>}
        {draft.hue.map((lk, i) => (
          <HueRow key={i} look={lk} areas={targets?.hue_areas ?? []}
            onChange={(next) => edit((d) => { d.hue[i] = next; })}
            onRemove={() => edit((d) => { d.hue.splice(i, 1); })} />
        ))}
        <button onClick={() => edit((d) => {
          d.hue.push({ area: d.hue.some((x) => x.area === '*') ? (targets?.hue_areas[0]?.id ?? '*') : '*',
            look: 'hold', kelvin: 2700, color: null, brightness: 100 });
        })}>+ Add a Hue look</button>
      </section>

      <section className="house-section">
        <h4>Music <HelpLink topic="house-music" /></h4>
        <label className="house-field">
          <span>When music plays</span>
          <select value={draft.music} onChange={(e) => edit((d) => { d.music = e.target.value as HouseMode['music']; })}>
            {Object.entries(MUSIC_WORDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="house-field">
          <span>Hue during music</span>
          <select value={draft.music_hue} onChange={(e) => edit((d) => { d.music_hue = e.target.value as HouseMode['music_hue']; })}>
            {Object.entries(MUSIC_HUE_WORDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="house-field">
          <span>Scenes resolved at intensity</span>
          <input type="number" min={0} max={1} step={0.05} value={draft.flow.intensity}
            onChange={(e) => edit((d) => { d.flow.intensity = Number(e.target.value); })} />
        </label>
      </section>

      <section className="house-section">
        <h4>Changes <HelpLink topic="house-transitions" /></h4>
        <div className="house-grid">
          <label className="house-field"><span>From Home Assistant&apos;s clock (s)</span>
            <input type="number" min={0} max={600} value={draft.transitions.clock_glide_s}
              onChange={(e) => edit((d) => { d.transitions.clock_glide_s = Number(e.target.value); })} /></label>
          <label className="house-field"><span>On a press (s)</span>
            <input type="number" min={0} max={600} value={draft.transitions.button_glide_s}
              onChange={(e) => edit((d) => { d.transitions.button_glide_s = Number(e.target.value); })} /></label>
          <label className="house-field"><span>Back from music after (s quiet)</span>
            <input type="number" min={0} max={900} value={draft.transitions.music_debounce_s}
              onChange={(e) => edit((d) => { d.transitions.music_debounce_s = Number(e.target.value); })} /></label>
          <label className="house-field"><span>…gliding over (s)</span>
            <input type="number" min={0} max={600} value={draft.transitions.music_return_glide_s}
              onChange={(e) => edit((d) => { d.transitions.music_return_glide_s = Number(e.target.value); })} /></label>
        </div>
      </section>

      <section className="house-section">
        <h4>Notes</h4>
        <textarea rows={2} value={draft.notes} onChange={(e) => edit((d) => { d.notes = e.target.value; })} />
      </section>
    </div>
  );
}

function FixtureRow({ hook, targets, onChange, onRemove }: {
  hook: FixtureHook; targets: HouseTargets | null;
  onChange: (h: FixtureHook) => void; onRemove: () => void;
}) {
  const set = (patch: Partial<FixtureHook>) => onChange({ ...hook, ...patch });
  const t = hook.target;
  return (
    <div className="house-row house-fixture-row">
      <select value={t.kind} aria-label="Target"
        onChange={(e) => set({ target: { kind: e.target.value as FixtureHook['target']['kind'], id: null } })}>
        <option value="everything">Everything</option>
        <option value="category">Category</option>
        <option value="fixture">Fixture</option>
      </select>
      {t.kind === 'category' && (
        <select value={t.id ?? ''} aria-label="Category" onChange={(e) => set({ target: { kind: 'category', id: e.target.value || null } })}>
          <option value="">— choose —</option>
          {t.id && !(targets?.categories ?? []).some((c) => c.name === t.id) && <option value={t.id}>{t.id}</option>}
          {(targets?.categories ?? []).map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
      )}
      {t.kind === 'fixture' && (
        <select value={t.id ?? ''} aria-label="Fixture" onChange={(e) => set({ target: { kind: 'fixture', id: e.target.value || null } })}>
          <option value="">— choose —</option>
          {t.id && !(targets?.fixtures ?? []).some((f) => f.id === t.id) && <option value={t.id}>{t.id}</option>}
          {(targets?.fixtures ?? []).map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
        </select>
      )}
      <label className="house-inline" title="Brightness of the picture on this fixture; 100 = unchanged">level
        <input type="number" min={0} max={200} placeholder="—" value={hook.level ?? ''}
          onChange={(e) => set({ level: num(e.target.value) })} />%
      </label>
      <label className="house-inline" title="Resting speed with no music: 0 = the effect's slowest, 100 = its fastest">motion
        <input type="number" min={0} max={100} placeholder="—"
          value={hook.motion == null ? '' : Math.round(hook.motion * 100)}
          onChange={(e) => { const v = num(e.target.value); set({ motion: v == null ? null : v / 100 }); }} />%
      </label>
      <label className="house-inline" title="Frame-rate cap — only ever lowers the fixture's own rate">cap
        <input type="number" min={1} max={60} placeholder="—" value={hook.fps ?? ''}
          onChange={(e) => set({ fps: num(e.target.value) })} />fps
      </label>
      <label className="house-inline" title="Brightness while the music show has the room; empty = the picture's own (100%). Spectra holds each WLED's own brightness at full, so this is the music level.">music
        <input type="number" min={0} max={200} placeholder="—" value={hook.music_level ?? ''}
          onChange={(e) => set({ music_level: num(e.target.value) })} />%
      </label>
      <label className="house-inline"><input type="checkbox" checked={hook.off}
        onChange={(e) => set({ off: e.target.checked })} />off</label>
      <button aria-label="Remove fixture setting" onClick={onRemove}>✕</button>
    </div>
  );
}

function HueRow({ look, areas, onChange, onRemove }: {
  look: HueLook; areas: { id: string; name: string }[];
  onChange: (l: HueLook) => void; onRemove: () => void;
}) {
  const set = (patch: Partial<HueLook>) => onChange({ ...look, ...patch });
  const usesKelvin = look.kelvin != null || look.color == null;
  return (
    <div className="house-row">
      <select value={look.area} aria-label="Hue area" onChange={(e) => set({ area: e.target.value })}>
        <option value="*">Every area</option>
        {look.area !== '*' && !areas.some((a) => a.id === look.area) && <option value={look.area}>{look.area}</option>}
        {areas.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
      </select>
      <select value={look.look} aria-label="Look" onChange={(e) => set({ look: e.target.value as HueLook['look'] })}>
        <option value="hold">hold</option>
        <option value="off">off</option>
        <option value="show">follow the show</option>
      </select>
      {look.look === 'hold' && (
        <>
          <select value={usesKelvin ? 'kelvin' : 'color'} aria-label="Colour temperature or colour"
            onChange={(e) => set(e.target.value === 'kelvin'
              ? { kelvin: 2700, color: null } : { kelvin: null, color: '#ff8a3d' })}>
            <option value="kelvin">white (K)</option>
            <option value="color">colour</option>
          </select>
          {usesKelvin ? (
            <label className="house-inline">
              <span className="house-swatch" style={{ background: kelvinToHex(look.kelvin ?? 2700) }} />
              <input type="number" min={2000} max={6500} step={50} value={look.kelvin ?? 2700}
                onChange={(e) => set({ kelvin: Number(e.target.value) })} />K
            </label>
          ) : (
            <input type="color" value={look.color ?? '#ff8a3d'} aria-label="Colour"
              onChange={(e) => set({ color: e.target.value })} />
          )}
          <label className="house-inline">
            <input type="number" min={1} max={100} value={look.brightness}
              onChange={(e) => set({ brightness: Number(e.target.value) })} />%
          </label>
        </>
      )}
      <button aria-label="Remove Hue look" onClick={onRemove}>✕</button>
    </div>
  );
}
