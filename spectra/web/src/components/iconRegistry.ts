/** THE ICON REGISTRY — inline SVG, not a raw Unicode character.
 *
 * Root cause of his "appears as an X" report (2026-10-06, on "Force
 * colour" and "Snap generated cues to beat", among others): every power-
 * toggle in SPECTRA (PowerButton.tsx) rendered a bare U+23FB POWER SYMBOL
 * character ("⏻") and relied on the viewer's font stack to have a glyph
 * for it. That codepoint sits in the Miscellaneous Technical block, which
 * is exactly the kind of character a sans-serif UI font commonly has no
 * glyph for — the browser then falls back to a "missing glyph" box, which
 * on several platforms renders with an X inside it. The fix is structural,
 * not per-site: stop depending on font glyph coverage at all. Every icon
 * in this registry is drawn as inline SVG paths, so it renders identically
 * on every platform regardless of installed fonts.
 *
 * `IconName` is a closed TypeScript union — passing an unregistered name
 * to <Icon name=.../> is a compile error (`npm run build` runs
 * `tsc --noEmit` first), which is the build-time check this exists to
 * provide: a future icon can never silently fall back to a missing glyph
 * the way the raw-Unicode-character approach did. `scripts/
 * check_icon_registry.mjs` is the second, independent check: it scans
 * every .tsx/.ts source file for `<Icon name="...">` usages (a literal
 * string, which covers every real call site in this codebase) and fails
 * if any name used is not a key of ICONS below — a regression net for
 * anyone who bypasses the type system (e.g. `name={x as any}`), and the
 * thing CI actually runs since there is no frontend test runner here (see
 * AGENTS.md's "Tests" section).
 *
 * Each value is a single SVG `<path>` `d` attribute — multiple disjoint
 * subpaths are expressed as multiple "M ..." moves concatenated into one
 * `d` string, which is legal SVG and keeps this file framework-free (no
 * JSX), so it can be imported and checked without a DOM or a React
 * runtime. viewBox is always "0 0 24 24", stroke-based (currentColor),
 * matching a generic 24x24 icon-grid convention (Feather-style) rather
 * than any specific icon library's bundle. */

export const ICONS: Record<string, string> = {
  /** Generic power glyph — PowerButton.tsx's shared enable/disable
   * control, used for scenes, colour sets, flares, and Force Colour. */
  power: 'M12 2L12 12M18.36 6.64a9 9 0 1 1-12.73 0',
  /** Light bulb outline — the room-wide brightness dimmer (replaces the
   * text label "Brightness", his ask 2026-10-06). Deliberately distinct
   * from the Hue Hold button's colour-emoji bulb (💡, a different
   * control) so the two don't read as the same thing side by side. */
  bulb: 'M9 18h6M10 21h4M12 2a7 7 0 0 0-4 12.9c.6.5 1 1.2 1 2.1h6c0-.9.4-1.6 1-2.1A7 7 0 0 0 12 2Z',
  /** Hand the room back to Home Assistant — a house glyph (his own
   * suggestion: "an exit/home glyph"). Used only by the small, long-press
   * release control at the right end of the top bar. */
  home: 'M3 9.5L12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z',
};

export type IconName = keyof typeof ICONS;
