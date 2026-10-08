/** The ONE wording for a scene / colour set or group in a searchable picker
 * (components/forms/SearchSelect.tsx). Shared by the top bar's Force Scene /
 * Force Colour pickers and the Light Show editor (the Admiral, 2026-10-08:
 * "make the drop downs ... in the lightshow edit be searchable and match the
 * other ui elements that do this"), so the two can never label the same card
 * differently. Pure — scripts/check_light_show_pickers.mjs drives it. */
import type { SearchOption } from '../components/forms/SearchSelect';

export interface SceneLike { id: string; name: string; disabled?: boolean; labels?: string[] }
export interface ColorCardLike {
  id: string; name: string; kind?: 'set' | 'group'; disabled?: boolean; labels?: string[];
}

/** A disabled scene is prefixed ⛔ (its power button is off). */
export function sceneOptions(scenes: SceneLike[] | null | undefined): SearchOption[] {
  return (scenes ?? []).map((s) => ({
    value: s.id,
    label: s.disabled ? `⛔ ${s.name}` : s.name,
    keywords: (s.labels ?? []).join(' '),
  }));
}

/** Sets AND groups in one list; a group is prefixed ▤, a disabled card ⛔. */
export function colorCardOptions(cards: ColorCardLike[] | null | undefined): SearchOption[] {
  return (cards ?? []).map((c) => ({
    value: c.id,
    label: `${c.disabled ? '⛔ ' : ''}${c.kind === 'group' ? '▤ ' : ''}${c.name}`,
    keywords: [c.kind === 'group' ? 'group' : 'set', ...(c.labels ?? [])].join(' '),
  }));
}

/** Plain id/name pairs (gradients, house modes, categories, fixtures, …). */
export function namedOptions(items: { id: string; name: string; group?: string }[]): SearchOption[] {
  return items.map((i) => ({ value: i.id, label: i.name, group: i.group }));
}
