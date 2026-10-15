/** Pure helpers for the one bar's redrawn slots (design-fidelity pass,
 * 2026-10-14 — the approved mockup's own `.sp .nb` / `.sp .dm` drawing,
 * data/ui-layout-plan/explainer-final.html). Kept DOM-free so
 * `scripts/check_ui_fidelity.py`'s own measurable assertions and any
 * future `.mjs` check can drive them with no browser — the
 * `components/songStrip.ts` convention. */
import type { ColorSetCard } from '../api/queries';

/** The Colour slot's 18px swatch: "a tiny swatch of the SET'S OWN
 * colours" (audit B4 — the one visual cue that tells Colour from Scenes
 * at a glance). Real data, never the mockup's hard-coded cyan ramp: a
 * set's first entry's own `color_value` (a solid or a full
 * `linear-gradient(...)` string, exactly as authored), else the card's
 * own display `color`, else a neutral placeholder for "no set resolved".
 *
 * Returns a CSS `background` value, so a gradient entry paints as that
 * gradient and a solid paints flat. */
export const NO_SET_SWATCH = '#2a1f3d';

export function colourSwatchBackground(card: ColorSetCard | null | undefined): string {
  if (!card) return NO_SET_SWATCH;
  const entries = card.entries as Array<{ color_value?: unknown }> | undefined;
  for (const e of entries ?? []) {
    if (typeof e?.color_value === 'string' && e.color_value.trim() !== '') return e.color_value;
  }
  const own = card.color;
  if (typeof own === 'string' && own.trim() !== '') return own;
  return NO_SET_SWATCH;
}

export type DisplayModeKey = 'default' | 'dark' | 'light';

/** The display-mode disc's own class suffix — the mockup draws ONE 16px
 * disc whose fill IS the mode (half/black/white = Hybrid/Dark/Light),
 * inside a 36px square with a 2px accent border, replacing the old empty
 * black 64x30 rectangle the artifact itself listed under "Was" (audit
 * B2). */
export function displayModeDiscClass(mode: string): string {
  if (mode === 'dark') return 'display-mode-disc display-mode-disc-dark';
  if (mode === 'light') return 'display-mode-disc display-mode-disc-light';
  return 'display-mode-disc display-mode-disc-hybrid';
}
