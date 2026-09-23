/** The `edges` engine's two knobs (spectra/services/rhythmic_edges.py) —
 * kept as a pure module (report/AGENTS.md convention: the frontend recomputes
 * locally on every drag, so a `.mjs` proof can transpile and drive this
 * directly, same as testbed/metrics.ts and testbed/songSearch.ts). */

export const DEFAULT_WINDOW_BEATS = 8;
export const DEFAULT_SENSITIVITY = 0.5;
export const MIN_WINDOW_BEATS = 1;
export const MAX_WINDOW_BEATS = 16;
export const MIN_SENSITIVITY = 0.2;
export const MAX_SENSITIVITY = 1.5;

export function clampWindowBeats(v: number): number {
  if (!Number.isFinite(v)) return DEFAULT_WINDOW_BEATS;
  return Math.max(MIN_WINDOW_BEATS, Math.min(MAX_WINDOW_BEATS, Math.round(v)));
}

export function clampSensitivity(v: number): number {
  if (!Number.isFinite(v)) return DEFAULT_SENSITIVITY;
  return Math.max(MIN_SENSITIVITY, Math.min(MAX_SENSITIVITY, v));
}

/** Whether the window/sensitivity knobs have any live effect on the
 * currently active A/B engines — shown only while an `edges` lane is
 * selected in either slot (report section 4: "only shown while a
 * generator:rule or edges:* lane is active" — generator:rule is a
 * future task, so today this reduces to `edges` alone). Showing the
 * knobs for an engine they don't touch would imply a control that does
 * nothing. */
export function knobsRelevant(engines: (string | null | undefined)[]): boolean {
  return engines.includes('edges');
}
