/** The audio-shape canvas's per-band RMS scale multipliers (Total / Bass /
 * Mid / High) — ONE definition shared by every reader of
 * `useSticky('scales', ...)`'s `spotfx.builder.v1.scales` key, so a future
 * change to how they're seeded can't drift between pages that draw the
 * same shape.
 *
 * `spectra/web/src/timeline/BuilderPage.tsx` (the Timeline page) already
 * reads this sticky key, seeded from the SpotFX settings
 * (`shape_scale_total`/`_bass`/`_mid`/`_high`) the Admiral tunes on
 * `web/src/settings/SettingsPage.tsx` — but ALSO hand-adjustable there via
 * `ShapeControls`' own sliders, which persist to the same key and outlive
 * the settings seed. `spectra/web/src/home/HomeTimeline.tsx` used to
 * hardcode `{ total: 1, bass: 1, mid: 1, high: 1 }`, so the Home page's
 * RMS bands rendered at a DIFFERENT height than the Timeline's — his own
 * 2026-10-25 report: "I don't like the scalings of all the rms values on
 * the home page. Match it to what I have right now in the timeline
 * graph." Reading the SAME sticky key with the SAME seed (both pages
 * share one browser origin, so `spotfx.builder.v1.scales` is one value)
 * is what "right now" means — not just the server default, whatever he
 * has actually dialed in on the Timeline page at the moment he looks at
 * Home.
 *
 * The Timeline page's own inline seed (BuilderPage.tsx) is left exactly
 * as it was — this module only gives Home (and any future caller) the
 * same seed logic without copying its constants by hand. */

export interface ShapeScales {
  total: number;
  bass: number;
  mid: number;
  high: number;
}

/** Unscaled — byte-identical to the Timeline page's own `useSticky`
 * default, and to what Home rendered before this fix existed. */
export const DEFAULT_SHAPE_SCALES: ShapeScales = { total: 1, bass: 1, mid: 1, high: 1 };

/** The `useSticky('scales', DEFAULT_SHAPE_SCALES, seed)` seed, applied the
 * first time that key is ever written in a browser — mirrors the
 * Timeline page's own inline seed exactly. `undefined` while `settings`
 * hasn't loaded yet (or doesn't exist), so `useSticky`'s "seed arrives
 * async" handling applies unchanged and the caller keeps showing
 * `DEFAULT_SHAPE_SCALES` (or an already-stuck value) until it does. */
export function shapeScalesSeed(
  settings: Record<string, unknown> | undefined,
): ShapeScales | undefined {
  if (!settings) return undefined;
  return {
    total: Number(settings.shape_scale_total ?? 1),
    bass: Number(settings.shape_scale_bass ?? 1),
    mid: Number(settings.shape_scale_mid ?? 1),
    high: Number(settings.shape_scale_high ?? 1),
  };
}
