/** Pure SceneV2 edits behind the Flares tab's edit box / paste / lanes —
 * split out of ResponseTab.tsx so the mutation logic is one place, easy to
 * read independent of the drag/pointer plumbing.
 *
 * A flare kind's identity is its NAME, scoped to one scene's flare_kinds
 * list (models/scene.py) — there is no cross-scene id. Rename/delete here
 * cascade into every response class's band.kinds references (dict keys)
 * and update_kind, keeping the scene internally consistent so a save never
 * trips SceneV2's own "band references undeclared kind" validation.
 * band.kinds key ORDER is load-bearing (spectra/services/scene_response.py:
 * within same-type kinds attached to a band, the later dict entry wins a
 * shared-param conflict — see ResponseEngine.on_event's fixed execution
 * order) — every mutation below preserves or deliberately repositions that
 * order, never reorders it as a side effect of an unrelated edit. */
import type { FlareKind, ResponseClass, SceneV2 } from '../../types';

export function dedupeKindName(existingNames: string[], base: string): string {
  if (!existingNames.includes(base)) return base;
  let n = 2;
  while (existingNames.includes(`${base} (${n})`)) n += 1;
  return `${base} (${n})`;
}

function mapBandKinds(
  responses: SceneV2['responses'],
  fn: (kinds: Record<string, number>) => Record<string, number>,
): SceneV2['responses'] {
  const out: SceneV2['responses'] = {};
  for (const [cls, spec] of Object.entries(responses)) {
    if (!spec) continue;
    out[cls as ResponseClass] = {
      ...spec,
      bands: spec.bands.map((b) => ({ ...b, kinds: fn(b.kinds ?? {}) })),
    };
  }
  return out;
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
    responses: mapBandKinds(scene.responses, (kinds) =>
      oldName in kinds
        ? Object.fromEntries(Object.entries(kinds).map(([k, v]) => [k === oldName ? trimmed : k, v]))
        : kinds),
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
    responses: mapBandKinds(scene.responses, (kinds) => {
      if (!(name in kinds)) return kinds;
      const { [name]: _omit, ...rest } = kinds;
      return rest;
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

export interface LaneRef { cls: ResponseClass; bandIdx: number; laneIdx: number; }

/** Attach/reorder/move a kind to a specific lane (= a position in the
 * target band's kinds dict). `source` set = this drag started FROM an
 * already-attached lane cell (a MOVE: detach there, attach here, carrying
 * its scale); `source` null = a drag from the palette or a fresh paste (an
 * ADD — the kind may already be attached to other bands too, by design
 * unchanged; this only ever touches the target band). Insertion SHIFTS
 * later lanes rather than swapping the occupant, so nothing is ever
 * silently dropped — a lane pushed past what's currently visible just
 * shows up once the rack's own auto-grow (attachedCount) renders it. */
export function moveKindToLane(
  scene: SceneV2,
  name: string,
  target: LaneRef,
  source: { cls: ResponseClass; bandIdx: number } | null,
): SceneV2 {
  const targetSpec = scene.responses[target.cls];
  if (!targetSpec || !targetSpec.bands[target.bandIdx]) return scene;

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
            const { [name]: _omit, ...rest } = b.kinds;
            return { ...b, kinds: rest };
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
        const names = Object.keys(b.kinds ?? {}).filter((n) => n !== name);
        names.splice(Math.min(target.laneIdx, names.length), 0, name);
        const kinds: Record<string, number> = {};
        for (const n of names) kinds[n] = n === name ? scale : (b.kinds ?? {})[n];
        return { ...b, kinds };
      }),
    },
  };
  return { ...scene, responses };
}
