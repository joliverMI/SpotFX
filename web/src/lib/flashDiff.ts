/** Work out which action cards an edit touched, so the UI can flash them.
 *
 * Relies on immer structural sharing: after produce(), every object on a
 * modified path has a new reference while untouched subtrees keep the old
 * one. So "changed block" = action whose reference differs (or is new).
 */

/** How long a flashed card stays highlighted (ms). */
export const FLASH_MS = 5000;

/** Actions are the only nodes with a `type` discriminant plus `labels`
 * (steps use `step_type`, lanes/options/children have no `type`). */
const isBlock = (o: Record<string, unknown>): boolean =>
  typeof o._uid === 'string' && typeof o.type === 'string' && Array.isArray(o.labels);

function collectBlocks(root: unknown): Map<string, unknown> {
  const map = new Map<string, unknown>();
  const walk = (v: unknown): void => {
    if (Array.isArray(v)) {
      v.forEach(walk);
    } else if (v && typeof v === 'object') {
      const o = v as Record<string, unknown>;
      if (isBlock(o)) map.set(o._uid as string, o);
      for (const val of Object.values(o)) walk(val);
    }
  };
  walk(root);
  return map;
}

/**
 * Uids of the blocks to highlight after an edit:
 * - a newly created block (but not its auto-created descendants), and
 * - the deepest updated block — ancestors that only changed because a
 *   descendant did are skipped, so a field edit flashes just that card.
 * Call with uids already attached to `next`.
 */
export function diffChangedBlocks(prev: unknown, next: unknown): string[] {
  const before = collectBlocks(prev);
  const keep = new Set<string>();
  type Frame = { uid: string; added: boolean; updated: boolean };
  const walk = (v: unknown, stack: Frame[]): void => {
    if (Array.isArray(v)) {
      v.forEach((x) => walk(x, stack));
      return;
    }
    if (!v || typeof v !== 'object') return;
    const o = v as Record<string, unknown>;
    let frames = stack;
    if (isBlock(o)) {
      const uid = o._uid as string;
      const added = !before.has(uid);
      const updated = !added && before.get(uid) !== o;
      if (added || updated) {
        for (const anc of stack) if (anc.updated) keep.delete(anc.uid);
        if (!(added && stack.some((a) => a.added))) keep.add(uid);
      }
      frames = [...stack, { uid, added, updated }];
    }
    for (const val of Object.values(o)) walk(val, frames);
  };
  walk(next, []);
  return [...keep];
}
