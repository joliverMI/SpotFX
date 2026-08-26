// Browser-free, network-free proof of ColorGradientPicker's gradient-angle
// canonicalization — the EMIT half and the DISPLAY half are the same pure
// function, so proving it once proves both.
//
// The function is not copied here: it is EXTRACTED VERBATIM from
// spectra/web/src/components/ColorGradientPicker.tsx at run time (the TSX
// block is plain JS apart from its type annotations, which are stripped by
// a single narrow substitution), so this check cannot drift from the
// shipped source the way a hand-copied twin would.
//
// Run: node scripts/check_gradient_angle_canonicalization.mjs
//
// Live measurement this encodes (2026-08-25, real react-gcolor-picker
// widget driven over CDP, no backend): with the angle dial hidden by
// PR #171, choosing one of the picker's built-in quick-pick gradients
// emitted "linear-gradient(315deg, …)" from a solid value and
// "linear-gradient(270deg, …)" while editing an existing 90deg value —
// the pre-fix normalizer left both alone, and the edge strip painted
// across the bar instead of along it.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(
  resolve(here, '../spectra/web/src/components/ColorGradientPicker.tsx'), 'utf8');

const start = src.indexOf("const CANONICAL_ANGLE");
const end = src.indexOf('export interface ColorGradientPickerProps');
if (start < 0 || end < 0) { console.error('FAIL: could not locate the canonicalization block'); process.exit(1); }
const block = src.slice(start, end)
  .replace('export function normalizeGradientAngle(value: string): string {',
           'function normalizeGradientAngle(value) {');
if (block.includes(': string')) { console.error('FAIL: unstripped type annotation in extracted block'); process.exit(1); }
const normalizeGradientAngle = new Function(`${block}\nreturn normalizeGradientAngle;`)();

let failed = 0;
function eq(actual, expected, label) {
  const ok = actual === expected;
  if (!ok) { failed++; console.error(`FAIL: ${label}\n  expected: ${expected}\n  actual:   ${actual}`); }
  else console.log(`ok: ${label}`);
}

// ── 1. A WRONG angle is REWRITTEN (the defect his report names) ───────────
eq(normalizeGradientAngle('linear-gradient(315deg, #96e6a1 8.00%,#d4fc79 92.00%)'),
   'linear-gradient(90deg, #96e6a1 8.00%,#d4fc79 92.00%)',
   'a 315deg quick-pick gradient is canonicalized to 90deg');
eq(normalizeGradientAngle('linear-gradient(270deg, #fbab7e 8.00%,#f7ce68 92.00%)'),
   'linear-gradient(90deg, #fbab7e 8.00%,#f7ce68 92.00%)',
   'a 270deg quick-pick gradient is canonicalized to 90deg');
eq(normalizeGradientAngle('linear-gradient(180deg, rgba(6, 6, 6, 1) 0.0%, rgba(183, 80, 174, 0.92) 100.0%)'),
   'linear-gradient(90deg, rgba(6, 6, 6, 1) 0.0%, rgba(183, 80, 174, 0.92) 100.0%)',
   "the widget's own solid->gradient 180deg default is canonicalized");
eq(normalizeGradientAngle('linear-gradient(0deg, rgb(255, 177, 153) 0%, rgb(255, 8, 68) 100%)'),
   'linear-gradient(90deg, rgb(255, 177, 153) 0%, rgb(255, 8, 68) 100%)',
   'rgb() stops survive the rewrite unchanged');
eq(normalizeGradientAngle('linear-gradient(-45deg, #000 0%, #fff 100%)'),
   'linear-gradient(90deg, #000 0%, #fff 100%)',
   'a signed angle is rewritten, not treated as a colour stop');
eq(normalizeGradientAngle('linear-gradient(.5turn, #000 0%, #fff 100%)'),
   'linear-gradient(90deg, #000 0%, #fff 100%)',
   'a turn-unit angle is rewritten');

// ── 2. A KEYWORD direction is rewritten, never prefixed ───────────────────
// Pre-fix this produced "linear-gradient(90deg, to right, …)" — a broken
// string every downstream parser would have mis-read.
eq(normalizeGradientAngle('linear-gradient(to bottom, #000 0%, #fff 100%)'),
   'linear-gradient(90deg, #000 0%, #fff 100%)',
   '"to bottom" is REPLACED by 90deg (never prefixed into a broken string)');
eq(normalizeGradientAngle('linear-gradient(to right bottom, #000 0%, #fff 100%)'),
   'linear-gradient(90deg, #000 0%, #fff 100%)',
   '"to right bottom" is replaced by 90deg');

// ── 3. A MISSING angle is still SUPPLIED (the original guard, kept) ───────
eq(normalizeGradientAngle('linear-gradient(#000 0%, #fff 100%)'),
   'linear-gradient(90deg, #000 0%, #fff 100%)',
   'an angle-less gradient gains 90deg without losing its first stop');
eq(normalizeGradientAngle('linear-gradient(rgb(1, 2, 3) 0%, #fff 100%)'),
   'linear-gradient(90deg, rgb(1, 2, 3) 0%, #fff 100%)',
   'an angle-less gradient whose first stop is rgb() keeps that stop');

// ── 4. An already-canonical value is byte-identical (his stored data) ─────
const normal_top = 'linear-gradient(90deg, #ff1e00 0.00%,#ffe300 12.00%,#0cff00 31.00%,#00ffeb 46.00%,#0060ff 62.00%,#b000ff 77.00%,#ff00a8 100.00%)';
eq(normalizeGradientAngle(normal_top), normal_top,
   'his stored 2D gradient "Normal" top edge is returned byte-identical');
eq(normalizeGradientAngle('linear-gradient(90deg, #006cff 0.00%,#9100ff 100.00%)'),
   'linear-gradient(90deg, #006cff 0.00%,#9100ff 100.00%)',
   'his stored "Normal" bottom edge is returned byte-identical');

// ── 5. Solid colours and non-gradients pass through untouched ─────────────
for (const v of ['#001cff', '#ff0000', 'rgb(1, 2, 3)', 'transparent', '', 'radial-gradient(circle at center, #000 0%, #fff 100%)']) {
  eq(normalizeGradientAngle(v), v, `passthrough untouched: ${JSON.stringify(v)}`);
}
eq(normalizeGradientAngle('linear-gradient(90deg #000 0% #fff 100%)'),
   'linear-gradient(90deg #000 0% #fff 100%)',
   'a comma-less malformed value is left alone rather than mangled');

// ── 6. Idempotent (it runs on both emit and display, so it runs twice) ────
for (const v of [normal_top, 'linear-gradient(315deg, #000 0%, #fff 100%)', 'linear-gradient(to bottom, #000 0%, #fff 100%)', '#001cff']) {
  eq(normalizeGradientAngle(normalizeGradientAngle(v)), normalizeGradientAngle(v),
     `idempotent: ${v.slice(0, 34)}`);
}

// ── 7. The DISPLAY half: what the swatch paints is a 90deg copy, and the
//      value it was given is not mutated (storage never moves) ────────────
{
  const stored = 'linear-gradient(315deg, #96e6a1 8.00%,#d4fc79 92.00%)';
  const painted = normalizeGradientAngle(stored);
  eq(painted, 'linear-gradient(90deg, #96e6a1 8.00%,#d4fc79 92.00%)',
     'display: a stray vertical stored value paints ALONG the bar');
  eq(stored, 'linear-gradient(315deg, #96e6a1 8.00%,#d4fc79 92.00%)',
     'display: the stored string itself is unchanged (no data moves)');
}

if (failed) { console.error(`\n${failed} check(s) FAILED`); process.exit(1); }
console.log('\nALL CHECKS PASSED');
