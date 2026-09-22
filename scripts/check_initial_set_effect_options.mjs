// Executable spec for the scene editor's Initial Set effect dropdown —
// transpiles the REAL frontend module (spectra/web/src/scenes/
// effectOptions.ts) with esbuild and drives it against REAL catalogue data
// (this repo's own storage/device_categories.json + config/
// effect_params.json), so this can't drift from what ships.
//
// The defect (2026-09-22, the Admiral: "I want to copy the strips initial
// set from fireworks to fish, so that the strips do the fireworks effect
// 1d instead of orbits 1d. The problem was that the fireworks effect didn't
// show as an option when I wanted to change it"): `fireworks1d` is a real,
// registered effect (config/effect_params.json) that no category's
// hand-curated `effects` list in storage/device_categories.json ever
// named — so a category-target scene entry's effect dropdown, sourced from
// that curated list alone, could never offer it. The Eye V2 scene's own
// stored Matrix entry (effect_type `eye`) has the identical gap.
//
// Fixed at fx.device_model.category_effect_options (Python): a category's
// served `effects` list is now the curated names PLUS every registered
// effect whose own device dimension (1D/2D, via fx.effects.twod.Twod
// class inheritance) matches the category's — see that function's own
// docstring. This script proves the frontend consumes that widened list
// correctly, and that a stored/stepped effect is never silently dropped
// from view even when it's missing from the options.
//
// Proves:
//   ONE   — OLD /api/registry shape (raw curated-only effects, what this
//           repo's real storage/device_categories.json contains today):
//           `fireworks1d` is NOT offered for Strips, and `eye` is NOT
//           offered for Matrix — the reported defect, reproduced against
//           real data.
//   TWO   — NEW /api/registry shape (curated names widened by the real
//           Python fx.device_model.category_effect_options, run as a
//           subprocess against the same real storage/config files):
//           `fireworks1d` IS offered for Strips and `eye` IS offered for
//           Matrix, with the curated names still leading in their curated
//           order.
//   THREE — selectableEffectOptions never drops a stored effect from the
//           dropdown even when the (possibly still-lagging, or simply
//           unknown-category) options list doesn't name it.
//
// Run: node scripts/check_initial_set_effect_options.mjs
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'spectra/web/src/scenes/effectOptions.ts');
const CATEGORIES_FILE = path.join(REPO, 'storage/device_categories.json');
const EFFECT_PARAMS_FILE = path.join(REPO, 'config/effect_params.json');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const tmp = mkdtempSync(path.join(tmpdir(), 'initialset-effects-'));
const js = path.join(tmp, 'effectOptions.mjs');
execFileSync('npx', ['esbuild', TS, '--format=esm', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const { effectOptionsFor, selectableEffectOptions } = await import(js);

const rawCategories = JSON.parse(readFileSync(CATEGORIES_FILE, 'utf8'));
const effectParams = JSON.parse(readFileSync(EFFECT_PARAMS_FILE, 'utf8'));
const allEffectNames = Object.keys(effectParams.effects ?? {});
const effectsShape = Object.fromEntries(allEffectNames.map((e) => [e, {}]));

function registryFrom(effectsByCategoryName) {
  const categories = {};
  for (const cat of Object.values(rawCategories)) {
    categories[cat.name] = {
      id: cat.id,
      parent_id: cat.parent_id ?? null,
      virtuals: cat.virtuals ?? [],
      effects: effectsByCategoryName[cat.name] ?? [],
    };
  }
  return { categories, effects: effectsShape };
}

// ── ONE: the OLD /api/registry shape — raw curated lists, verbatim ───────
const oldEffectsByCategory = {};
for (const cat of Object.values(rawCategories)) {
  oldEffectsByCategory[cat.name] = cat.effects ?? [];
}
const oldRegistry = registryFrom(oldEffectsByCategory);

console.log('ONE — old (curated-only) registry reproduces the reported gap:');
ok(!effectOptionsFor(oldRegistry, 'category', 'Strips').includes('fireworks1d'),
  'fireworks1d is NOT offered for Strips under the old curated-only list');
ok(!effectOptionsFor(oldRegistry, 'category', 'Matrix').includes('eye'),
  'eye is NOT offered for Matrix under the old curated-only list');

// ── TWO: the NEW /api/registry shape — device_model.category_effect_options ──
const pyScript = `
import json, sys
sys.path.insert(0, ${JSON.stringify(REPO)})
from fx import device_model
out = {c["name"]: device_model.category_effect_options(c["name"]) for c in device_model.list_categories()}
print(json.dumps(out))
`;
const newEffectsByCategory = JSON.parse(
  execFileSync(path.join(REPO, '.venv/bin/python'), ['-c', pyScript], { encoding: 'utf8' }),
);
const newRegistry = registryFrom(newEffectsByCategory);

console.log('TWO — new (device-kind-widened) registry fixes it:');
const strips = effectOptionsFor(newRegistry, 'category', 'Strips');
ok(strips.includes('fireworks1d'), 'fireworks1d IS offered for Strips under the widened list');
ok(strips[0] === 'melt' && strips[1] === 'power',
  'curated names still lead, in their curated order (additive, never reordering)');
const matrix = effectOptionsFor(newRegistry, 'category', 'Matrix');
ok(matrix.includes('eye'), 'eye IS offered for Matrix under the widened list');
ok(matrix.includes('fish'), 'fish (another uncurated registered effect) IS offered for Matrix too');
ok(!strips.includes('eye') && !strips.includes('radial'),
  'a 2D-only effect never leaks into the 1D Strips list');
ok(!matrix.includes('melt') && !matrix.includes('power'),
  'a 1D-only effect never leaks into the 2D Matrix list');

// ── THREE: a stored effect is never silently dropped from the dropdown ───
console.log('THREE — a stored/stepped effect stays visible even when unlisted:');
ok(selectableEffectOptions(oldRegistry, 'category', 'Strips', 'fireworks1d')
    .includes('fireworks1d'),
  "the Fish scene's own stored fireworks1d Strips entry stays selectable/visible " +
  'even against the old, gap-carrying registry');
ok(selectableEffectOptions(newRegistry, 'category', 'no-such-category', 'some-retired-effect')
    .includes('some-retired-effect'),
  'an effect the registry no longer names at all (unknown category / retired effect) ' +
  'is still never silently blanked');

if (failures > 0) {
  console.error(`\n${failures} check(s) failed`);
  rmSync(tmp, { recursive: true, force: true });
  process.exit(1);
}
rmSync(tmp, { recursive: true, force: true });
console.log('\nall Initial Set effect-option checks passed');
