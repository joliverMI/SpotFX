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
//   2. `.scenes-group-btn .top-bar-group-btn-value` sets `max-width: 100%`
//      (never a fixed px value that could itself race the button's own
//      width at a different breakpoint).
//   3. Energy/Mark/countdown-bearing values carry `font-variant-numeric:
//      tabular-nums` (so a digit changing width, e.g. "0.9" -> "0.97",
//      "9:59" -> "10:00", never reflows the row either).
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
  ok(!!body && /width:\s*132px/.test(body), 'declares an explicit `width: 132px` (not only min-width)');
  ok(!!body && !/max-width/.test(body), 'the button rule itself carries no competing max-width');
}

console.log('§2 the value span fills the fixed button, truncating instead of widening it');
{
  const re = /(?:^|\n)\.scenes-group-btn \.top-bar-group-btn-value\s*\{([^}]*)\}/m;
  const m = css.match(re);
  ok(!!m, '.scenes-group-btn .top-bar-group-btn-value has its own rule');
  const body = m ? m[1] : '';
  ok(/max-width:\s*100%/.test(body), 'sets max-width: 100% (fills the fixed parent, never forces it wider)');
}

console.log('§3 numeric readouts use tabular digits so a value changing width never reflows');
{
  for (const sel of ['.energy-readout-value', '.intensity-mark-value', '.light-show-item-when']) {
    const body = soleClassRule(css, sel);
    ok(!!body && /font-variant-numeric:\s*tabular-nums/.test(body),
      `${sel} carries font-variant-numeric: tabular-nums`);
  }
}

console.log('§4 the one-bar never wraps on tablet/desktop (only the bar\'s own media query may re-enable it)');
{
  const body = soleClassRule(css, '.one-bar');
  ok(!!body && /flex-wrap:\s*nowrap/.test(body), '.one-bar is flex-wrap: nowrap by default');
  const phoneBlock = css.match(/@media \(max-width: 520px\)\s*\{\s*\.one-bar\s*\{([^}]*)\}/);
  ok(!!phoneBlock && /flex-wrap:\s*wrap/.test(phoneBlock[1]),
    'only the phone (<=520px) media query re-enables wrapping — a deliberate second row, not a side effect');
}

console.log(failures === 0 ? '\nPASS' : `\nFAIL (${failures})`);
process.exit(failures === 0 ? 0 : 1);
