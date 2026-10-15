// CHEAP SMOKE TEST ONLY — not the primary proof. This reads tokens.css as
// text and regex-matches a few declarations; a source match can be dead
// code (exactly what happened to `.top-bar-strip`'s own `flex-wrap: wrap`
// once that div went `display: contents` under `.one-bar`) or overridden
// by a higher-specificity rule elsewhere, so a green run here proves
// intent, never behaviour. The ACTUAL "pixels don't move when text does"
// proof is the live-browser measurement in check_onebar_layout.py (it
// mutates the Scenes/Colour value text in a real rendered page and
// measures a sibling's position before/after) — read that one first.
//
// Historical context this still documents: the no-jumping fix (UI
// declutter plan §6) — Scenes and Colour used to size between 64-126px
// depending on the current scene/colour-set NAME (`min-width: 64px` on
// `.top-bar-group-btn` racing `.top-bar-group-btn-value`'s own
// `max-width: 100px`), moving the control after them by up to 61px over
// 90s of ordinary playing (the plan's own measurement).
//
// Three rules, each a plain regex read of the real stylesheet:
//   1. `.scenes-group-btn` (the class BOTH Scenes and Colour share) has an
//      explicit `width:` declaration, not just `min-width`.
//   2. `.scenes-group-btn .bar-slot-name` sets `max-width: 100%`
//      (never a fixed px value that could itself race the button's own
//      width at a different breakpoint).
//   3. Every numeric readout in the bar/strip gets tabular digits (so a
//      digit changing width, e.g. "0.9" -> "0.97", "9:59" -> "10:00",
//      never reflows the row either) — EITHER by its own
//      `font-variant-numeric` declaration or through the shared
//      `.tabular-nums` utility class its element carries. The 2026-10-14
//      design-fidelity pass added that utility, which until then was
//      applied as a className in SongStrip.tsx/HomeTimeline.tsx and
//      DEFINED NOWHERE (audit T5/N3), so this section now asserts the
//      utility exists as well as the per-selector declarations.
//
// Run: node scripts/check_onebar_fixed_widths.mjs
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const css = readFileSync(path.join(REPO, 'spectra/web/src/styles/tokens.css'), 'utf8');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

// Anchored to the START of a rule (preceded by a newline or the start of
// the file) so a COMPOUND selector elsewhere (e.g. `.one-bar
// .scenes-group-btn { order: 4; }`) can never be mistaken for the bare
// class's own rule — found the hard way: the unanchored version matched
// that order-only rule instead of the real width declaration.
function soleClassRule(css, cls) {
  const re = new RegExp(`(?:^|\\n)${cls.replace(/\./g, '\\.')}\\s*\\{([^}]*)\\}`, 'm');
  const m = css.match(re);
  return m ? m[1] : null;
}

console.log('§1 Scenes/Colour (.scenes-group-btn) has a FIXED width, no min/max race');
{
  const body = soleClassRule(css, '.scenes-group-btn');
  ok(body !== null, '.scenes-group-btn has its own (non-compound) rule block');
  // 156px since the design-fidelity pass (the approved mockup's own
  // `.sp .nb` flex-basis); the PROPERTY under test is "an explicit width,
  // not a min/max race", never the particular number.
  ok(!!body && /(?:^|[^-])width:\s*156px/.test(body), 'declares an explicit `width: 156px` (not only min-width)');
  ok(!!body && !/max-width/.test(body), 'the button rule itself carries no competing max-width');
}

console.log('§2 the value span fills the fixed button, truncating instead of widening it');
{
  // `.bar-slot-name` since the design-fidelity pass — the name slot's own
  // left-aligned bold name replaced the centred `.top-bar-group-btn-value`
  // (audit B4). Its `max-width: 100%` + ellipsis is the same property.
  const body = soleClassRule(css, '.bar-slot-name');
  ok(body !== null, '.bar-slot-name has its own rule');
  ok(!!body && /max-width:\s*100%/.test(body), 'sets max-width: 100% (fills the fixed parent, never forces it wider)');
  ok(!!body && /text-overflow:\s*ellipsis/.test(body), 'truncates with an ellipsis rather than widening');
}

console.log('§3 numeric readouts use tabular digits so a value changing width never reflows');
{
  const util = soleClassRule(css, '.tabular-nums');
  ok(!!util && /font-variant-numeric:\s*tabular-nums/.test(util),
    '.tabular-nums IS defined (it was used as a className and defined nowhere — audit T5/N3)');
  for (const sel of ['.energy-readout-value', '.intensity-mark-value']) {
    const body = soleClassRule(css, sel);
    ok(!!body && /font-variant-numeric:\s*tabular-nums/.test(body),
      `${sel} carries font-variant-numeric: tabular-nums`);
  }
  // The Light Show slot's countdown, the strip's own count/progress, and
  // Home's own clock readout carry the shared utility on the ELEMENT
  // instead (they are rewritten every frame by a rAF loop, so the class
  // travels with the markup) — proven behaviourally (getComputedStyle, a
  // live-rendered DOM), not by reading source text, in
  // scripts/check_ui_fidelity.py: `.song-strip-next-count`/
  // `.song-strip-time` in section FOUR, `.light-show-act-when` (the
  // Light Show slot's current countdown) in the same section, and
  // `.home-timeline-clock` in FOUR-C.
}

console.log('§4 the one-bar never wraps on tablet/desktop (only the bar\'s own media query may re-enable it)');
{
  const body = soleClassRule(css, '.one-bar');
  ok(!!body && /flex-wrap:\s*nowrap/.test(body), '.one-bar is flex-wrap: nowrap by default');
  const phoneBlock = css.match(/@media \(max-width: 520px\)\s*\{\s*\.one-bar\s*\{([^}]*)\}/);
  ok(!!phoneBlock && /flex-wrap:\s*wrap/.test(phoneBlock[1]),
    'the phone (<=520px) media query re-enables wrapping — a deliberate second row, not a side effect');
  // The Admiral's own "do C" band (521-1100px) wraps too, deliberately —
  // see tokens.css's own `.one-bar::before` rule. Asserted here so a
  // future edit cannot remove it silently.
  const tabletBlock = css.match(/@media \(min-width: 521px\) and \(max-width: 1100px\)\s*\{\s*\.one-bar\s*\{([^}]*)\}/);
  ok(!!tabletBlock && /flex-wrap:\s*wrap/.test(tabletBlock[1]),
    'the 521-1100px band wraps too (his own deliberate two rows), and nothing between 1101-1180 does');
  ok(!/@media \(min-width: 1181px\)[^}]*flex-wrap:\s*wrap/.test(css),
    'nothing above 1180px re-enables wrapping');
}

console.log(failures === 0 ? '\nPASS' : `\nFAIL (${failures})`);
process.exit(failures === 0 ? 0 : 1);
