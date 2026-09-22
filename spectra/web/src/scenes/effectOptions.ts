/** A device entry's effect dropdown options — extracted out of
 * InitialSetTab.tsx as a pure module so it can be driven directly (no
 * React, no DOM) by scripts/check_initial_set_effect_options.mjs against
 * real catalogue data, the same "transpile the real module" discipline
 * scripts/check_lock_badge_states.mjs already uses for lockBadge.ts.
 *
 * A category target fires its whole subtree, so its effect options are
 * the subtree's union of each category's own `effects` list — which the
 * backend (fx.device_model.category_effect_options) already widens past
 * a hand-curated shortlist to every registered effect the engine
 * supports for that category's device kind (1D for Strips, 2D for
 * Matrix, etc.) — see that function's own docstring for why the
 * shortlist alone isn't enough. This module does not re-derive that
 * widening; it only walks the subtree the backend already served. */
import type { Registry } from '../types';

export function subtreeEffects(
  registry: Registry | undefined,
  targetKind: string,
  target: string,
): string[] {
  if (targetKind !== 'category') return [];
  const cats = Object.values(registry?.categories ?? {});
  const root = registry?.categories[target];
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
}

export function effectOptionsFor(
  registry: Registry | undefined,
  targetKind: string,
  target: string,
): string[] {
  const allEffects = Object.keys(registry?.effects ?? {});
  const subtree = subtreeEffects(registry, targetKind, target);
  return targetKind === 'category' && subtree.length ? subtree : allEffects;
}

/** effectOptionsFor(), with the currently-selected/stepped effect kept
 * visible up front even when the options list doesn't name it — a scene
 * must never silently lose its stored effect_type just because a
 * category's options happened not to include it. */
export function selectableEffectOptions(
  registry: Registry | undefined,
  targetKind: string,
  target: string,
  currentEffect: string,
): string[] {
  const options = effectOptionsFor(registry, targetKind, target);
  if (currentEffect && !options.includes(currentEffect)) {
    return [currentEffect, ...options];
  }
  return options;
}
