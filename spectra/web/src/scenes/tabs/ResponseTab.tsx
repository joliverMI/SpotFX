/** Response tabs — Flares (one class) and Charges/Lulls/Drops (three).
 * The item-8 doctrine: the scene DECLARES named flare kinds (readable
 * cards below — tap/double-click one to rename, delete, or copy it; type/
 * params/gain/hold stay agent-adjustable, no settings forms); the band
 * strip stays the graphical piece, and each band SELECTS AND SCALES kinds
 * via a small vertical LANE RACK — drag a kind card into a lane to attach
 * it there (2 lanes by default, up to 4), ✕ to detach. Every lane fires
 * together; a lane holding SEVERAL kinds is a pool of alternatives the
 * engine picks ONE from per fire (owner ask 2026-08-21, even weights —
 * FlareBand.kind_lanes, scene_response.resolve_lane_picks): drop a kind ON
 * an occupied lane to pool it there, or on the slim strip before a lane /
 * an empty lane for a lane of its own (the position still matters —
 * same-param precedence in scene_response.py's fixed execution order; see
 * flareKindOps.ts's header). Copy/Paste ports a kind's own declaration to
 * any other scene (never a live link — see lib/flareClipboard.ts). */
import { useRef, useState } from 'react';
import BandStrip from '../../components/BandStrip';
import FlareLaneRack from '../../components/FlareLaneRack';
import HelpLink from '../../help/HelpLink';
import { useToast } from '../../components/Toast';
import { readFlareClipboard } from '../../lib/flareClipboard';
import type { FlareKind, ResponseClass, ResponseSpec, SceneV2 } from '../../types';
import { emptyBand, emptyResponse } from '../../types';
import FlareKindEditDialog from './FlareKindEditDialog';
import FlarePreviewOverlay from './FlarePreviewOverlay';
import {
  bandPools, deleteFlareKind, moveKindToLane, pasteKind, prunedLanes,
  renameFlareKind, setKindTriggerOffset,
} from './flareKindOps';
import type { LaneRef } from './flareKindOps';

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
    : k.type === 'color_rotate' ? '🔄'
      : k.type === 'firework_burst' ? '🎆'
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
  color_rotate: 'Rotates the live foreground colour\'s hue and returns it — degrees, ramp-in, dwell, and fade-back all scale from the fire\'s intensity; no knobs of its own.',
  firework_burst: 'Explodes extra payoff rockets the instant the flare fires, on every live fireworks effect — 3 rockets at intensity 0 up to 6 at intensity 1, on top of whatever the scene is already launching; no knobs of its own.',
};

interface DragState {
  name: string;
  source: { cls: ResponseClass; bandIdx: number } | null;
  x: number;
  y: number;
  over: LaneRef | null;
}

export default function ResponseTab({ scene, setScene, classes, helpTopic }: {
  scene: SceneV2;
  setScene: (s: SceneV2) => void;
  classes: ResponseClass[];
  helpTopic: string;
}) {
  const toast = useToast();
  const kinds = scene.flare_kinds ?? [];
  const kindsByName = Object.fromEntries(kinds.map((k) => [k.name, k]));

  const [editingKind, setEditingKind] = useState<FlareKind | null>(null);
  const [previewingKind, setPreviewingKind] = useState<FlareKind | null>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const [laneExtra, setLaneExtra] = useState<Record<string, number>>({});

  const clipboard = readFlareClipboard();

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
          missing.push({ name, type: 'drift_jump', jump, params: {}, gain: 1, hold_ms: null, trigger_offset_ms: 0 });
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
        if (scale === null) {
          // Detach also leaves its lane pool; a pool shrunk to one member
          // is pruned so the stored map stays canonical (flareKindOps.ts).
          delete next[name];
          const { [name]: _omit, ...lanes } = b.kind_lanes ?? {};
          return { ...b, kinds: next, kind_lanes: prunedLanes(next, lanes) };
        }
        next[name] = scale;
        return { ...b, kinds: next };
      }),
    });
  };

  // ── drag: a card (palette or an occupied lane) tracks the pointer across
  // the WHOLE page — any band's rack, in any class section below, is a
  // valid drop target — and drops via document.elementFromPoint hit-testing
  // against each lane's data attributes (FlareLaneRack.tsx). An unmoved
  // release is a TAP: opens the edit box, the same one double-click opens,
  // so this also covers touch where a real double-tap is unreliable. ──
  const startDrag = (name: string, source: { cls: ResponseClass; bandIdx: number } | null) =>
    (e: React.PointerEvent) => {
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      e.stopPropagation();
      (e.currentTarget as Element).setPointerCapture(e.pointerId);
      const startX = e.clientX;
      const startY = e.clientY;
      let moved = false;
      const initial: DragState = { name, source, x: startX, y: startY, over: null };
      dragRef.current = initial;
      setDrag(initial);

      const move = (ev: PointerEvent) => {
        if (!moved && (Math.abs(ev.clientX - startX) > 5 || Math.abs(ev.clientY - startY) > 5)) moved = true;
        const el = document.elementFromPoint(ev.clientX, ev.clientY) as HTMLElement | null;
        const laneEl = el?.closest('[data-lane]') as HTMLElement | null;
        const over: LaneRef | null = laneEl ? {
          cls: laneEl.dataset.cls as ResponseClass,
          bandIdx: Number(laneEl.dataset.band),
          mode: laneEl.dataset.laneMode === 'join' ? 'join' : 'insert',
          anchor: laneEl.dataset.laneAnchor || null,
        } : null;
        const next = { ...initial, x: ev.clientX, y: ev.clientY, over };
        dragRef.current = next;
        setDrag(next);
      };
      const up = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        const final = dragRef.current;
        dragRef.current = null;
        setDrag(null);
        if (!final) return;
        if (moved) {
          if (final.over) setScene(moveKindToLane(scene, final.name, final.over, final.source));
        } else {
          const k = kindsByName[final.name];
          if (k) setEditingKind(k);
        }
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    };

  const doPaste = () => {
    if (!clipboard) return;
    const before = new Set(kinds.map((k) => k.name));
    const next = pasteKind(scene, clipboard.kind);
    setScene(next);
    const pastedName = next.flare_kinds.find((k) => !before.has(k.name))!.name;
    toast(`Pasted "${pastedName}" from "${clipboard.sourceSceneName}" — drag it into a lane to use it`, 'success');
  };

  return (
    <div>
      <div style={{ marginBottom: 18 }}>
        <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          Flare kinds <HelpLink topic="flare-kinds" />
          <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 'normal' }}>
            tap/double-click a kind to rename, delete, or copy — drag it into a lane below to attach it
          </span>
          {clipboard && (
            <button style={{ fontSize: 11, padding: '2px 8px', marginLeft: 'auto' }}
              title={`Paste "${clipboard.kind.name}" (copied from "${clipboard.sourceSceneName}") as a new kind on this scene`}
              onClick={doPaste}>
              📋 Paste "{clipboard.kind.name}"
            </button>
          )}
        </div>
        {kinds.length === 0 && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            No kinds declared yet — adding a Flares response seeds the two drift-jumps, tell the agent what this scene should do when the music hits, or paste a kind copied from another scene.
          </div>
        )}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {kinds.map((k) => (
            <div key={k.name} className="card"
              onPointerDown={startDrag(k.name, null)}
              style={{ padding: '6px 10px', maxWidth: 260, cursor: 'grab', userSelect: 'none',
                       touchAction: 'none', opacity: drag?.name === k.name ? 0.4 : 1 }}
              title={`${TYPE_HINT[k.type]}\nTap to rename/delete/copy. Drag onto a lane to attach. Type/params/gain/hold are agent-adjustable.`}>
              <div style={{ fontSize: 12, fontWeight: 600, display: 'flex', alignItems: 'center' }}>
                {kindIcon(k)} {k.name}
                <span className="chip" style={{ marginLeft: 6 }}>{kindTypeLabel(k)}</span>
                {scene.update_kind === k.name && (
                  <span className="chip" style={{ marginLeft: 4 }} title="Reserved for a future Update effect — not read today. A dwell hold or fire_scene_update trigger currently fires this scene's Flare response at double intensity instead; see the Update effect help topic.">
                    ⚓ UPDATE
                  </span>
                )}
                <button style={{ marginLeft: 'auto', fontSize: 11, padding: '1px 6px' }}
                  title="Open the scrubbing preview timeline for this kind"
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={(e) => { e.stopPropagation(); setPreviewingKind(k); }}>
                  ▶ Preview
                </button>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{kindContent(k)}</div>
            </div>
          ))}
        </div>

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, fontSize: 12 }}
          title="Reserved for a future, purpose-built Update effect — not read by fire_scene_update or a dwell hold today. Right now both fire this scene's own Flare response at double intensity instead, whatever's attached to its bands; see the Update effect help topic.">
          <span style={{ color: 'var(--text-muted)' }}>Update kind (reserved)</span>
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

      {classes.includes('charge') && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 10 }}>
          What each effect actually looks like on charge/lull/drop <HelpLink topic="response-families" />
        </div>
      )}

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
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>
                  Lanes <HelpLink topic="tab-flares-lanes" />
                </div>
                {[...spec.bands]
                  .map((b, i) => ({ b, i }))
                  .sort((a, z) => a.b.intensity_min - z.b.intensity_min)
                  .map(({ b, i }) => {
                    const laneKey = `${cls}:${i}`;
                    const laneCount = bandPools(b).length;
                    const visibleLanes = Math.max(2 + (laneExtra[laneKey] ?? 0), laneCount);
                    const canAddLane = visibleLanes < 4;
                    const overTarget = drag?.over && drag.over.cls === cls && drag.over.bandIdx === i
                      ? { mode: drag.over.mode, anchor: drag.over.anchor } : null;
                    return (
                      <div key={i} style={{ marginBottom: 10 }}>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4,
                                      fontVariantNumeric: 'tabular-nums' }}>
                          [{b.intensity_min.toFixed(2)}–{b.intensity_max.toFixed(2)})
                        </div>
                        {kinds.length === 0 ? (
                          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>no kinds declared yet</div>
                        ) : (
                          <FlareLaneRack cls={cls} bandIdx={i} band={b}
                            visibleLanes={visibleLanes} canAddLane={canAddLane}
                            kindsByName={kindsByName}
                            draggingName={drag?.name ?? null}
                            overTarget={overTarget}
                            onAddLane={() => setLaneExtra((m) => ({
                              ...m, [laneKey]: Math.min(2, (m[laneKey] ?? 0) + 1),
                            }))}
                            onStartDrag={startDrag}
                            onDetach={(name) => setBandKind(cls, i, name, null)}
                            onSetScale={(name, v) => setBandKind(cls, i, name, v)}
                          />
                        )}
                      </div>
                    );
                  })}
              </>
            )}
          </div>
        );
      })}

      {editingKind && (
        <FlareKindEditDialog
          scene={scene}
          sceneName={scene.name}
          kind={editingKind}
          onClose={() => setEditingKind(null)}
          onRename={(newName) => {
            if (newName !== editingKind.name && kinds.some((k) => k.name === newName)) {
              return `Another kind is already named "${newName}"`;
            }
            setScene(renameFlareKind(scene, editingKind.name, newName));
            return null;
          }}
          onDelete={() => setScene(deleteFlareKind(scene, editingKind.name))}
        />
      )}

      {previewingKind && (
        <FlarePreviewOverlay
          sceneId={scene.id}
          kind={kindsByName[previewingKind.name] ?? previewingKind}
          onClose={() => setPreviewingKind(null)}
          onTriggerOffsetChange={(ms) => setScene(setKindTriggerOffset(scene, previewingKind.name, ms))}
        />
      )}

      {drag && (
        <div style={{ position: 'fixed', left: drag.x + 14, top: drag.y + 10, zIndex: 200,
                      pointerEvents: 'none', background: 'var(--accent)', color: '#14061f',
                      fontSize: 11, fontWeight: 600, padding: '3px 9px', borderRadius: 5,
                      boxShadow: '0 2px 10px rgba(0,0,0,0.5)', whiteSpace: 'nowrap' }}>
          {kindsByName[drag.name] ? kindIcon(kindsByName[drag.name]) : ''} {drag.name}
        </div>
      )}
    </div>
  );
}
