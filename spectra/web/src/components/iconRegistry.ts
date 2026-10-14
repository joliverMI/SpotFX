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

export const ICONS = {
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
  /** Gear outline — "open this fixture's settings" from the device-preview
   * strip's expanded stage (icon-only; his "take all the text out of the
   * preview window" ask, 2026-10-06, replaced the old "Open settings" text
   * button). */
  settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM19.4 13a7.4 7.4 0 0 0 0-2l2-1.5-2-3.4-2.3.9a7.4 7.4 0 0 0-1.7-1l-.3-2.5h-4l-.3 2.5a7.4 7.4 0 0 0-1.7 1l-2.3-.9-2 3.4L6.6 11a7.4 7.4 0 0 0 0 2l-2 1.5 2 3.4 2.3-.9c.5.4 1.1.75 1.7 1l.3 2.5h4l.3-2.5c.6-.25 1.2-.6 1.7-1l2.3.9 2-3.4Z',
  /** Padlock outline — the Scenes/Colour top-bar buttons' "this is being
   * forced" marker (his ask 2026-10-07: "show a lock icon if it's being
   * forced, and nothing otherwise"), replacing the generic purple dot
   * those two buttons used for the same state. Body + shackle, two
   * subpaths in one `d` (legal SVG, keeps this file framework-free — see
   * the module docstring above). */
  lock: 'M5 11H19A2 2 0 0 1 21 13V20A2 2 0 0 1 19 22H5A2 2 0 0 1 3 20V13A2 2 0 0 1 5 11ZM7 11V7A5 5 0 0 1 17 7V11',
  /** Lightning bolt — "fire now" (his ask, 2026-10-08: the Light Show
   * Run view's "Sets — tap to run" row of per-timing icon buttons). */
  bolt: 'M13 2L3 14H12L11 22L21 10H12L13 2Z',
  /** Bunny — "at the next scene change" (his own named glyph for this
   * timing, same ask). Two long ears plus a round head; stroke-only like
   * every other icon here, not a literal rabbit illustration. */
  rabbit: 'M9 10Q7 5 8 2Q10 2 10 6Q10 8 9 10Z M15 10Q17 5 16 2Q14 2 14 6Q14 8 15 10Z M7 15A5 5 0 1 0 17 15A5 5 0 1 0 7 15Z',
  /** Up arrow — "on the next High Trigger" (same ask). */
  arrowUp: 'M12 19V5M5 12L12 5L19 12',
  /** Down arrow — "on the next Low Trigger" (same ask). */
  arrowDown: 'M12 5V19M19 12L12 19L5 12',
  /** Clipboard — "copy" (the Light Show builders' copy-to-clipboard, the
   * legacy SpotFX editor's 📋, 2026-10-11). */
  copy: 'M9 4H7A2 2 0 0 0 5 6V20A2 2 0 0 0 7 22H17A2 2 0 0 0 19 20V6A2 2 0 0 0 17 4H15M9 2H15V6H9Z',
  /** Two overlapping squares — "duplicate in place" (legacy ⧉). */
  duplicate: 'M8 8H20V20H8ZM16 8V4H4V16H8',
  /** Clipboard with an arrow in — "paste". */
  paste: 'M9 4H7A2 2 0 0 0 5 6V20A2 2 0 0 0 7 22H17A2 2 0 0 0 19 20V6A2 2 0 0 0 17 4H15M9 2H15V6H9ZM12 10V17M9 14L12 17L15 14',
  /** Box with an arrow out — "open the referenced thing" (legacy ↗). */
  open: 'M14 4H20V10M20 4L11 13M18 14V19A1 1 0 0 1 17 20H5A1 1 0 0 1 4 19V7A1 1 0 0 1 5 6H10',
  /** Bin — "delete". */
  trash: 'M4 7H20M9 7V4H15V7M6 7L7 20H17L18 7M10 11V16M14 11V16',
  /** Chevron pointing right — a collapsed row's caret (rotated when open). */
  chevron: 'M9 6L15 12L9 18',
  /** Nested boxes — "run another set" (a set reference). */
  callSet: 'M3 5H13V11H3ZM11 13H21V19H11ZM8 11V16H11',
  /** A framed picture with sunbeams — "scene change" (the song-layout-
   * plan's global/Home song timeline next-event box, and the Scenes
   * button, data/ui-layout-plan/report.md §4/§13 decision 6: no icon on
   * the button itself, but the timeline's per-event type icon still
   * needs one). */
  scene: 'M3 5H21V19H3Z M3 15L8 10L13 15L16 12L21 17 M8.5 8A1.5 1.5 0 1 0 8.5 5A1.5 1.5 0 0 0 8.5 8Z',
  /** One pulse spike — the generic "drop-sequence phase" glyph (charge /
   * lull / drop all share it; the next-event box's own text distinguishes
   * them, e.g. "Charge · drop 1" vs "Drop 1" — song-layout-plan §4). */
  pulse: 'M3 12H8L10 6L14 18L16 12H21',
  /** Dashboard grid — the top menu's Home item (2026-10-14 UI declutter
   * plan): deliberately NOT a house glyph, which stays reserved for house
   * lighting (ModeChip.tsx's icon, "home" below). */
  dash: 'M3 3H11V13H3ZM13 3H21V9H13ZM13 11H21V21H13ZM3 15H11V21H3Z',
  /** Stacked cube — the top menu's "Artifacts ▾" group (Scenes, Colours,
   * Devices, Rooms, Room FX, Light Show). */
  cube: 'M12 2L21 7V17L12 22L3 17V7Z M3 7L12 12L21 7 M12 12V22',
  /** Speed gauge — the top menu's "Engine ▾" group (Debug, Status, Timing,
   * Review, AV Sync, House, Test Bed, Timeline, Feedback). */
  gauge: 'M3.5 17.5A9 9 0 1 1 20.5 17.5 M12 14L16.5 9.5 M12 15.5A1.5 1.5 0 1 0 12 12.5A1.5 1.5 0 0 0 12 15.5Z',
  /** Electrical plug — the panic-release control's icon (replaces the
   * house glyph there, 2026-10-14: a house glyph now means house
   * lighting, so releasing the room to Home Assistant needed its own). */
  plug: 'M9 2V8 M15 2V8 M6 8H18V12A6 6 0 0 1 6 12Z M12 18V22',
  /** Downward chevron — a closed dropdown group's own caret (flips to
   * point up while its menu is open). */
  chevronDown: 'M6 9L12 15L18 9',
  /** Circled "i" — InfoTip.tsx's own trigger (a rich tooltip, hover/
   * long-press, replacing a bare "?" wherever a control deserves its own
   * short description plus a Help link). */
  info: 'M12 22A10 10 0 1 0 12 2A10 10 0 0 0 12 22Z M12 16V11 M12 8H12.01',
  /** A waveform trace — the test bed's own waveform-lane visibility
   * toggle (IconToggle.tsx's first adoption site). */
  wave: 'M2 12H5L7 5L11 19L14 9L16 15L18 10L20 14L22 12',
  /** Hourglass — the Light Show bar slot's "Wait" item kind (a sequence
   * step waiting on a duration/song count, not a trigger). */
  wait: 'M6 2H18 M6 22H18 M6 2C6 8 10 10 12 12C14 14 18 16 18 22 M18 2C18 8 14 10 12 12C10 14 6 16 6 22',
} satisfies Record<string, string>;

export type IconName = keyof typeof ICONS;
