/** Pure SceneV2 edits behind the Flares tab's edit box / paste / lanes —
 * split out of ResponseTab.tsx so the mutation logic is one place, easy to
 * read independent of the drag/pointer plumbing.
 *
 * A flare kind's identity is its NAME, scoped to one scene's flare_kinds
 * list (models/scene.py) — there is no cross-scene id. Rename/delete here
 * cascade into every response class's band.kinds references (dict keys),
 * band.kind_lanes (the lane-pool membership map, below) and update_kind,
 * keeping the scene internally consistent so a save never trips SceneV2's
 * own "band references undeclared kind" / "kind_lanes entry references a
 * kind not attached" validation.
 * band.kinds key ORDER is load-bearing (spectra/services/scene_response.py:
 * within same-type kinds attached to a band, the later dict entry wins a
 * shared-param conflict — see ResponseEngine.on_event's fixed execution
 * order) — every mutation below preserves or deliberately repositions that
 * order, never reorders it as a side effect of an unrelated edit.
 *
 * LANES (owner ask, 2026-08-21): band.kind_lanes maps kind name → lane
 * name; kinds sharing a lane name are a POOL OF ALTERNATIVES the engine
 * picks exactly ONE from per fire (even weights — scene_response.
 * resolve_lane_picks). A kind absent from the map is its own one-member
 * lane, so every pre-lanes band fires all of its kinds unchanged. The UI
 * keeps the stored map CANONICAL: only genuine (≥2-member) pools are ever
 * persisted — a pool shrinking to one member has its leftover entry
 * pruned (prunedLanes below), so "no entry" is the one representation of
 * "fires every time". Lane membership never affects execution ORDER —
 * that stays band.kinds' own insertion order; lanes only decide WHO fires. */
import type { FlareBand, FlareKind, ResponseClass, SceneV2 } from '../../types';

export function dedupeKindName(existingNames: string[], base: string): string {
  if (!existingNames.includes(base)) return base;
  let n = 2;
  while (existingNames.includes(`${base} (${n})`)) n += 1;
  return `${base} (${n})`;
}

function mapBands(
  responses: SceneV2['responses'],
  fn: (band: FlareBand) => FlareBand,
): SceneV2['responses'] {
  const out: SceneV2['responses'] = {};
  for (const [cls, spec] of Object.entries(responses)) {
    if (!spec) continue;
    out[cls as ResponseClass] = { ...spec, bands: spec.bands.map(fn) };
  }
  return out;
}

function mapBandKinds(
  responses: SceneV2['responses'],
  fn: (kinds: Record<string, number>) => Record<string, number>,
  laneFn?: (lanes: Record<string, string>) => Record<string, string>,
): SceneV2['responses'] {
  return mapBands(responses, (b) => ({
    ...b,
    kinds: fn(b.kinds ?? {}),
    kind_lanes: laneFn ? laneFn(b.kind_lanes ?? {}) : (b.kind_lanes ?? {}),
  }));
}

/** Drop kind_lanes entries whose pool no longer has ≥2 members attached to
 * this band — a one-member pool behaves identically to no entry (the
 * engine's pick-one over a pool of one is that one), so the pruned form is
 * the single canonical representation of "fires every time". */
export function prunedLanes(
  kinds: Record<string, number>,
  lanes: Record<string, string>,
): Record<string, string> {
  const counts: Record<string, number> = {};
  for (const [n, lane] of Object.entries(lanes)) {
    if (n in kinds) counts[lane] = (counts[lane] ?? 0) + 1;
  }
  return Object.fromEntries(Object.entries(lanes).filter(
    ([n, lane]) => n in kinds && counts[lane] >= 2));
}

export interface BandPool { lane: string | null; members: string[]; }

/** The band's lanes as the rack renders them: one entry per pool, ordered
 * by each pool's FIRST member's position in band.kinds' own insertion
 * order (execution order — untouched by pooling), members in kinds order.
 * lane === null is a solo (implicit one-member lane). */
export function bandPools(band: FlareBand): BandPool[] {
  const laneOf = band.kind_lanes ?? {};
  const out: BandPool[] = [];
  const byLane = new Map<string, BandPool>();
  for (const n of Object.keys(band.kinds ?? {})) {
    const lane = laneOf[n];
    if (lane === undefined) { out.push({ lane: null, members: [n] }); continue; }
    const existing = byLane.get(lane);
    if (existing) existing.members.push(n);
    else { const p: BandPool = { lane, members: [n] }; byLane.set(lane, p); out.push(p); }
  }
  return out;
}

/** A fresh lane name unused by this band — "lane 1", "lane 2", … Lane
 * names are stored strings (a future rename/weighting hook) but the rack
 * shows position; generated names just need to be unique per band. */
function freshLaneName(lanes: Record<string, string>): string {
  const used = new Set(Object.values(lanes));
  let n = 1;
  while (used.has(`lane ${n}`)) n += 1;
  return `lane ${n}`;
}

/** Rename cascades to every band.kinds reference and update_kind — the key
 * SWAP preserves dict order (delete+re-add would silently move a rename to
 * the back of the lane order, changing same-param precedence as a side
 * effect). Caller validates uniqueness first (a collision is a product
 * decision — reject and tell the human — not something to silently
 * dedupe-suffix the way paste does). */
export function renameFlareKind(scene: SceneV2, oldName: string, newName: string): SceneV2 {
  const trimmed = newName.trim();
  if (!trimmed || trimmed === oldName) return scene;
  return {
    ...scene,
    flare_kinds: scene.flare_kinds.map((k) => (k.name === oldName ? { ...k, name: trimmed } : k)),
    responses: mapBandKinds(
      scene.responses,
      (kinds) =>
        oldName in kinds
          ? Object.fromEntries(Object.entries(kinds).map(([k, v]) => [k === oldName ? trimmed : k, v]))
          : kinds,
      (lanes) =>
        oldName in lanes
          ? Object.fromEntries(Object.entries(lanes).map(([k, v]) => [k === oldName ? trimmed : k, v]))
          : lanes),
    update_kind: scene.update_kind === oldName ? trimmed : scene.update_kind,
  };
}

/** How many places (bands + update_kind) reference this kind — shown in the
 * delete confirm so removing a widely-attached kind isn't a surprise. */
export function countKindUsages(scene: SceneV2, name: string): number {
  let n = 0;
  for (const spec of Object.values(scene.responses)) {
    if (!spec) continue;
    for (const b of spec.bands) if (name in (b.kinds ?? {})) n += 1;
  }
  if (scene.update_kind === name) n += 1;
  return n;
}

/** Delete cascades the same way rename does — every band reference and a
 * matching update_kind are cleared so the scene never saves with a
 * dangling kind reference. */
export function deleteFlareKind(scene: SceneV2, name: string): SceneV2 {
  return {
    ...scene,
    flare_kinds: scene.flare_kinds.filter((k) => k.name !== name),
    responses: mapBands(scene.responses, (b) => {
      if (!(name in (b.kinds ?? {}))) return b;
      const { [name]: _omit, ...kinds } = b.kinds;
      const { [name]: _omitLane, ...lanes } = b.kind_lanes ?? {};
      return { ...b, kinds, kind_lanes: prunedLanes(kinds, lanes) };
    }),
    update_kind: scene.update_kind === name ? null : scene.update_kind,
  };
}

/** Paste = a genuine PORT: a fresh, independent flare_kinds entry on the
 * TARGET scene (which may be the same scene, a plain duplicate) carrying
 * the copied type/jump/params/gain/hold_ms verbatim. Never auto-attached to
 * a band — the source scene's band attachment is a per-scene relationship
 * that has no natural target band here; the human attaches it via a lane
 * like any other kind. A name collision gets the same "(2)" suffix
 * convention the backend's own auto-naming uses
 * (models/scene.py _migrate_flare_kinds.declare). A pasted kind's params
 * may name a param the target scene's devices don't carry — harmless: the
 * engine's name-broadcast targeting (scene_response._move_params) already
 * skips virtuals whose live effect has no such param. */
export function pasteKind(scene: SceneV2, incoming: FlareKind): SceneV2 {
  const name = dedupeKindName(scene.flare_kinds.map((k) => k.name), incoming.name);
  return { ...scene, flare_kinds: [...scene.flare_kinds, { ...incoming, name }] };
}

/** The scrubbing preview's trigger-alignment marker writes here — a real
 * scene-draft edit (Save persists it), not a preview-only value. Clamped
 * to the model's own [-60000, 60000] range (models/scene.py FlareKind). */
export function setKindTriggerOffset(scene: SceneV2, name: string, ms: number): SceneV2 {
  const clamped = Math.max(-60_000, Math.min(60_000, Math.round(ms)));
  return {
    ...scene,
    flare_kinds: scene.flare_kinds.map((k) =>
      k.name === name ? { ...k, trigger_offset_ms: clamped } : k),
  };
}

/** The flare bar's power button writes here — a real scene-draft edit
 * (Save persists it), the same shape setKindTriggerOffset uses. Stored on
 * the KIND, not the band, so switching a kind off silences it everywhere
 * it is attached at once — which is what "disable this flare" means. */
export function setKindEnabled(scene: SceneV2, name: string, enabled: boolean): SceneV2 {
  return {
    ...scene,
    flare_kinds: scene.flare_kinds.map((k) =>
      k.name === name ? { ...k, enabled } : k),
  };
}

export interface LaneRef {
  cls: ResponseClass;
  bandIdx: number;
  /** 'insert' = land as its OWN new lane; 'join' = enter the anchor's
   * pool of alternatives (the fire-time pick-one lane). */
  mode: 'insert' | 'join';
  /** Kind name identifying the drop position: for 'join', a member of the
   * target pool (its first, as rendered); for 'insert', the first member
   * of the pool the drop lands before. null = at the end. Anchoring by
   * NAME rather than lane index keeps a same-band move stable — removing
   * the dragged kind can renumber pools, but never renames the others. */
  anchor: string | null;
}

/** Attach/reorder/move a kind onto a band's lane rack. `source` set = this
 * drag started FROM an already-attached lane cell (a MOVE: detach there,
 * attach here, carrying its scale); `source` null = a drag from the
 * palette or a fresh paste (an ADD — the kind may already be attached to
 * other bands too, by design unchanged; this only ever touches the target
 * band). mode 'insert' lands the kind as its own lane at the anchor's
 * position, SHIFTING later lanes rather than swapping — nothing is ever
 * silently dropped; mode 'join' pools it with the anchor's lane (minting a
 * fresh lane name when the anchor was solo) so the engine picks ONE of
 * them per fire, placing it right after the pool's last member so pools
 * stay contiguous in the rack. Every path prunes one-member pools
 * (prunedLanes) so the stored map stays canonical. */
export function moveKindToLane(
  scene: SceneV2,
  name: string,
  target: LaneRef,
  source: { cls: ResponseClass; bandIdx: number } | null,
): SceneV2 {
  const targetSpec = scene.responses[target.cls];
  if (!targetSpec || !targetSpec.bands[target.bandIdx]) return scene;
  if (target.mode === 'join' && target.anchor === name) return scene;

  let scale = 1;
  const sourceBand = source ? scene.responses[source.cls]?.bands[source.bandIdx] : undefined;
  if (sourceBand && name in (sourceBand.kinds ?? {})) scale = sourceBand.kinds[name];
  else if (name in (targetSpec.bands[target.bandIdx].kinds ?? {})) {
    scale = targetSpec.bands[target.bandIdx].kinds[name];
  }

  const sameBand = source && source.cls === target.cls && source.bandIdx === target.bandIdx;
  let responses = scene.responses;
  if (source && !sameBand) {
    const srcSpec = responses[source.cls];
    if (srcSpec) {
      responses = {
        ...responses,
        [source.cls]: {
          ...srcSpec,
          bands: srcSpec.bands.map((b, i) => {
            if (i !== source.bandIdx || !(name in (b.kinds ?? {}))) return b;
            const { [name]: _omit, ...kinds } = b.kinds;
            const { [name]: _omitLane, ...lanes } = b.kind_lanes ?? {};
            return { ...b, kinds, kind_lanes: prunedLanes(kinds, lanes) };
          }),
        },
      };
    }
  }

  const spec = responses[target.cls]!;
  responses = {
    ...responses,
    [target.cls]: {
      ...spec,
      bands: spec.bands.map((b, i) => {
        if (i !== target.bandIdx) return b;
        const kinds0: Record<string, number> = { ...(b.kinds ?? {}) };
        const lanes0: Record<string, string> = { ...(b.kind_lanes ?? {}) };
        delete kinds0[name];
        delete lanes0[name];
        const names = Object.keys(kinds0);
        let at = names.length;
        if (target.mode === 'join' && target.anchor && target.anchor in kinds0) {
          const laneName = lanes0[target.anchor] ?? freshLaneName(lanes0);
          lanes0[target.anchor] = laneName;
          lanes0[name] = laneName;
          at = names.reduce((acc, n, idx) => (lanes0[n] === laneName ? idx + 1 : acc), 0);
        } else if (target.mode === 'insert' && target.anchor && target.anchor in kinds0) {
          at = names.indexOf(target.anchor);
        }
        names.splice(at, 0, name);
        const kinds: Record<string, number> = {};
        for (const n of names) kinds[n] = n === name ? scale : kinds0[n];
        return { ...b, kinds, kind_lanes: prunedLanes(kinds, lanes0) };
      }),
    },
  };
  return { ...scene, responses };
}
