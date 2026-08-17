/** Scenes — SPECTRA's tabbed scene editor. Desktop: two panes — scene list
 * (search, create) and the editor. Phone portrait (the owner's in-room
 * surface): a first-class single-pane arrangement — the editor owns the
 * full width, and the scene picker collapses into a top selector that
 * opens a full-screen drawer (with no selection, the list IS the page).
 * Horizontal tabs replace the legacy long scroll: Summary · Initial Set ·
 * Drift · Flares · Phase Choreography · Sequencing · Colour Sets ·
 * Charges/Lulls/Drops. Edits live in local drafts until Save; the
 * toolbar's intensity slider drives Test Fire (dry-run compile — shows
 * resolved bindings + writes) and the owner's real Fire button. */
import { useEffect, useMemo, useState } from 'react';
import ModeAvailabilityToggle from '../components/ModeAvailabilityToggle';
import SonicChatPopover from '../components/SonicChatPopover';
import { useToast } from '../components/Toast';
import HelpLink from '../help/HelpLink';
import { uuid } from '../lib/uid';
import useIsPhone from '../lib/useIsPhone';
import { setUnsavedGuard } from '../lib/unsavedGuard';
import { fireScene, useDeleteScene, useRegistry, useSaveScene, useScenes } from '../queries';
import type { FireResult, SceneV2 } from '../types';
import { newScene, sceneDiceLetters } from '../types';
import SummaryTab from './tabs/SummaryTab';
import InitialSetTab from './tabs/InitialSetTab';
import DriftTab from './tabs/DriftTab';
import ResponseTab from './tabs/ResponseTab';
import PhaseTab from './tabs/PhaseTab';
import SequencingTab from './tabs/SequencingTab';
import ColorSetsTab from './tabs/ColorSetsTab';
import EngineStatusStrip from './EngineStatusStrip';
import SequencerStatusStrip from './SequencerStatusStrip';

const TABS = [
  'Summary', 'Initial Set', 'Drift', 'Flares', 'Phase Choreography',
  'Sequencing', 'Colour Sets', 'Charges/Lulls/Drops',
] as const;
export type TabName = (typeof TABS)[number];

export default function ScenesPage() {
  const toast = useToast();
  const { data: serverScenes = [], isLoading } = useScenes();
  const { data: registry } = useRegistry();
  const saveMut = useSaveScene();
  const delMut = useDeleteScene();

  const isPhone = useIsPhone();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [drafts, setDrafts] = useState<Record<string, SceneV2>>({});
  const [fireResult, setFireResult] = useState<FireResult | null>(null);
  const [intensity, setIntensity] = useState(0.7);
  // Per-scene sticky tab: switching scenes returns you to that scene's tab.
  const [tabs, setTabs] = useState<Record<string, TabName>>({});

  const scenes = useMemo(() => {
    const merged = serverScenes.map((s) => drafts[s.id] ?? s);
    const serverIds = new Set(serverScenes.map((s) => s.id));
    for (const d of Object.values(drafts)) if (!serverIds.has(d.id)) merged.push(d);
    return merged;
  }, [serverScenes, drafts]);

  const scene = scenes.find((s) => s.id === selectedId) ?? null;
  const setScene = (next: SceneV2) => setDrafts((d) => ({ ...d, [next.id]: next }));
  const tab: TabName = (scene && tabs[scene.id]) || 'Summary';
  const setTab = (t: TabName) => scene && setTabs((m) => ({ ...m, [scene.id]: t }));

  const draftCount = Object.keys(drafts).length;
  useEffect(() => {
    setUnsavedGuard(draftCount
      ? `${draftCount} scene${draftCount === 1 ? ' has' : 's have'} unsaved changes — leave and discard them?`
      : null);
    return () => setUnsavedGuard(null);
  }, [draftCount]);

  const visible = useMemo(() => {
    const q = search.toLowerCase();
    return scenes.filter((s) =>
      s.name.toLowerCase().includes(q) || (s.labels ?? []).some((l) => l.toLowerCase().includes(q)));
  }, [scenes, search]);

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

  /** Test-fire = save, then resolve+compile at the chosen intensity WITHOUT
   * device contact; the resolved bindings and writes render below.
   * NO CONFIRM on the live fire — DELIBERATE ASYMMETRY (owner's order,
   * 2026-08-13): the press IS the consent; it fires the single scene he
   * chose and is looking at, and an extra tap doubly hurts on the phone.
   * The confirm on the GLOBAL colour-set opt-out (ColorSetsTab) STAYS —
   * that one silently changes every scene in the house. Do not "tidy"
   * either side of this asymmetry. */
  const testFire = async (dryRun: boolean) => {
    if (!scene) return;
    if (!(await save())) return;
    try {
      const res = await fireScene(scene.id, intensity, dryRun);
      setFireResult(res);
      toast(dryRun
        ? `Compiled ${res.writes.length} write${res.writes.length === 1 ? '' : 's'} (dry run)`
        : `Fired ${res.writes.length} write${res.writes.length === 1 ? '' : 's'} live`,
        'success');
    } catch (e) {
      toast(`${dryRun ? 'Test fire' : 'Fire'} failed: ${e}`, 'error');
    }
  };

  const create = () => {
    const s = newScene(uuid());
    setDrafts((d) => ({ ...d, [s.id]: s }));
    setSelectedId(s.id);
    setFireResult(null);
  };

  const tabBadge = (t: TabName): string | null => {
    if (!scene) return null;
    if (t === 'Initial Set') return scene.devices.length ? String(scene.devices.length) : null;
    if (t === 'Flares') return scene.responses.flare?.bands.length ? String(scene.responses.flare.bands.length) : null;
    if (t === 'Drift') {
      const n = scene.devices.reduce((k, d) => k + Object.keys(d.drift ?? {}).length, 0)
        + (scene.color_journey.mode === 'override' ? 1 : 0);
      return n ? String(n) : null;
    }
    if (t === 'Charges/Lulls/Drops') {
      const n = (['charge', 'lull', 'drop'] as const).reduce(
        (k, c) => k + (scene.responses[c]?.bands.length ?? 0), 0);
      return n ? String(n) : null;
    }
    return null;
  };

  // The list body renders in the desktop pane OR the phone drawer/page —
  // one place, one behavior (picking closes the drawer when one is open).
  const sceneList = (
    <>
      <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        Scenes <HelpLink topic="scenes-page" />
        <button className="primary" style={{ marginLeft: 'auto', fontSize: 11, padding: '3px 10px' }}
          onClick={() => { create(); setPickerOpen(false); }}>
          + Scene
        </button>
        {isPhone && pickerOpen && (
          <button style={{ fontSize: 12 }} onClick={() => setPickerOpen(false)}>✕</button>
        )}
      </div>
      <div className="field">
        <input type="text" placeholder="Search…" value={search} style={{ width: '100%' }}
          onChange={(e) => setSearch(e.target.value)} />
      </div>
      <div style={{ overflowY: 'auto', flex: 1, minHeight: 0 }}>
        {isLoading && <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: 10 }}>Loading…</div>}
        {!isLoading && !visible.length && (
          <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: 10 }}>
            No scenes yet — create one, or run scripts/seed_spectra_from_v2.py to migrate the SceneV2 world.
          </div>
        )}
        {visible.map((s) => {
          const dice = sceneDiceLetters(s);
          return (
            <div key={s.id} className={`pane-row${s.id === selectedId ? ' selected' : ''}`}
              onClick={() => { setSelectedId(s.id); setFireResult(null); setPickerOpen(false); }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500 }}>
                  {s.name}
                  {drafts[s.id] && <span title="Unsaved changes" style={{ color: 'var(--accent2)' }}> •</span>}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  {s.devices.length} entr{s.devices.length === 1 ? 'y' : 'ies'}
                  {dice.length > 0 && ` · 🎲 ${dice.map((l) => l.toUpperCase()).join(' ')}`}
                  {s.color_journey.mode === 'override' && ' · journey override'}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </>
  );

  return (
    <div style={{ display: 'grid', gridTemplateColumns: isPhone ? '1fr' : '250px 1fr',
                  gap: isPhone ? 10 : 16, alignItems: 'start' }}>
      <SonicChatPopover />
      <SequencerStatusStrip scenes={scenes} />
      <EngineStatusStrip />

      {/* ── Scene list: desktop pane, or the whole page on a phone with no
             selection (the editor owns the width once a scene is open) ── */}
      {(!isPhone || !scene) && (
        <div className="card" style={{ minWidth: 0, display: 'flex', flexDirection: 'column',
                                       maxHeight: isPhone ? 'none' : 'calc(100vh - 80px)' }}>
          {sceneList}
        </div>
      )}

      {/* ── Phone: compact scene selector above the editor; opens the drawer ── */}
      {isPhone && scene && (
        <button onClick={() => setPickerOpen(true)} title="Choose another scene"
          style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%',
                   textAlign: 'left', padding: '10px 12px', background: 'var(--surface)',
                   border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
          <span style={{ color: 'var(--accent)' }}>☰</span>
          <span style={{ fontWeight: 600, fontSize: 14, overflow: 'hidden',
                         textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {scene.name}{drafts[scene.id] ? ' •' : ''}
          </span>
          <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-muted)', flex: 'none' }}>
            scenes ▾
          </span>
        </button>
      )}
      {isPhone && pickerOpen && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 50, background: 'var(--bg)',
                      padding: 10, display: 'flex', flexDirection: 'column' }}>
          <div className="card" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
            {sceneList}
          </div>
        </div>
      )}

      {/* ── Editor ── */}
      {scene ? (
        <div className="card" style={{ minWidth: 0,
                                       maxHeight: isPhone ? 'none' : 'calc(100vh - 80px)',
                                       overflowY: isPhone ? 'visible' : 'auto' }}>
          {/* Toolbar */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <input type="text" value={scene.name} style={{ fontSize: 15, fontWeight: 600, width: 220 }}
              onChange={(e) => setScene({ ...scene, name: e.target.value })} />
            <button className="primary" onClick={() => void save()}>
              Save{drafts[scene.id] ? ' •' : ''}
            </button>
            <button style={{ fontSize: 12 }} onClick={duplicate}>⧉ Duplicate</button>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginLeft: 8 }}
              title="The intensity a fire resolves ⚡ bindings against — preview the scene anywhere on the axis">
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>intensity</span>
              <input type="range" min={0} max={1} step={0.01} value={intensity} style={{ width: 110 }}
                onChange={(e) => setIntensity(Number(e.target.value))} />
              <span style={{ fontSize: 12, fontVariantNumeric: 'tabular-nums', width: 34 }}>{intensity.toFixed(2)}</span>
            </span>
            <ModeAvailabilityToggle value={scene.display_availability ?? 'default'}
              onChange={(v) => setScene({ ...scene, display_availability: v })} />
            <button style={{ fontSize: 12, borderColor: 'var(--accent)' }}
              title="Really fire this scene through the live LedFX service"
              onClick={() => void testFire(false)}>
              ⚡ Fire
            </button>
            <button className="danger" style={{ fontSize: 12, marginLeft: 'auto' }} onClick={() => void del()}>✕ Delete</button>
          </div>

          {/* Tab bar */}
          <div className="tab-bar">
            {TABS.map((t) => (
              <button key={t} className={t === tab ? 'active' : ''} onClick={() => setTab(t)}>
                {t}
                {tabBadge(t) && <span className="tab-badge">{tabBadge(t)}</span>}
              </button>
            ))}
          </div>

          {tab === 'Summary' && <SummaryTab scene={scene} setScene={setScene} goTo={setTab} />}
          {tab === 'Initial Set' && <InitialSetTab scene={scene} setScene={setScene} registry={registry} />}
          {tab === 'Drift' && <DriftTab scene={scene} setScene={setScene} />}
          {tab === 'Flares' && (
            <ResponseTab scene={scene} setScene={setScene} classes={['flare']} helpTopic="tab-flares" />
          )}
          {tab === 'Phase Choreography' && <PhaseTab scene={scene} />}
          {tab === 'Sequencing' && <SequencingTab scene={scene} scenes={scenes} />}
          {tab === 'Colour Sets' && <ColorSetsTab scene={scene} setScene={setScene} />}
          {tab === 'Charges/Lulls/Drops' && (
            <ResponseTab scene={scene} setScene={setScene} classes={['charge', 'lull', 'drop']}
              helpTopic="tab-responses" />
          )}

          {/* Compiled result from the last (test) fire */}
          {fireResult && (
            <div style={{ marginTop: 14 }}>
              <div className="card-title">
                {fireResult.dry_run ? 'Test fire' : 'LIVE fire'} @ intensity {fireResult.intensity.toFixed(2)}
                {' '}— {fireResult.writes.length} virtual write{fireResult.writes.length === 1 ? '' : 's'}
                {fireResult.dry_run && ' (dry run, nothing sent)'}
              </div>
              {fireResult.resolved_bindings.length > 0 && (
                <table style={{ fontSize: 12, marginBottom: 8, borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ color: 'var(--text-muted)', textAlign: 'left' }}>
                      <th style={{ paddingRight: 14 }}>entry</th>
                      <th style={{ paddingRight: 14 }}>param</th>
                      <th style={{ paddingRight: 14 }}>source</th>
                      <th>resolved</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fireResult.resolved_bindings.map((r, i) => (
                      <tr key={i}>
                        <td style={{ paddingRight: 14 }}>{r.entry}</td>
                        <td style={{ paddingRight: 14 }}>{r.param}</td>
                        <td style={{ paddingRight: 14, color: 'var(--text-muted)' }}>
                          {r.signal === 'random' ? `🎲${r.dice ? ` dice ${r.dice.toUpperCase()}` : ''}` : `⚡ ${r.signal}`}
                        </td>
                        <td style={{ fontWeight: 600 }}>{r.value === null ? '— unset' : String(r.value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {!fireResult.writes.length && (
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  Nothing compiled — check that entries have a target and an effect, and that categories contain virtuals.
                </div>
              )}
              <pre style={{ fontSize: 11, background: 'var(--surface2)', padding: 8, borderRadius: 'var(--radius)', overflowX: 'auto', maxHeight: 300 }}>
                {JSON.stringify(fireResult.writes, null, 2)}
              </pre>
            </div>
          )}
        </div>
      ) : (
        !isPhone && (
          <div className="card" style={{ color: 'var(--text-muted)', fontSize: 13 }}>
            Select a scene on the left, or create one. A SPECTRA scene states what every
            device shows — every value fixed, ⚡ intensity-mapped, or 🎲 rolled — plus its
            declared mechanisms: drift, responses, and the colour journey. <HelpLink topic="overview" />
          </div>
        )
      )}
    </div>
  );
}
