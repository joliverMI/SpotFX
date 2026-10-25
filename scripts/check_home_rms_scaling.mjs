/** Executable spec: the Home page's RMS bands use the SAME scale
 * multipliers as the Timeline page (the Admiral, 2026-10-25: "I don't
 * like the scalings of all the rms values on the home page. Match it to
 * what I have right now in the timeline graph.").
 *
 * `spectra/web/src/timeline/BuilderPage.tsx` (the Timeline page) seeds its
 * sticky `scales` state from `shape_scale_total`/`_bass`/`_mid`/`_high`
 * (SpotFX settings he tunes, or hand-adjusts via its own sliders — both
 * land in the SAME `spotfx.builder.v1.scales` localStorage key).
 * `spectra/web/src/home/HomeTimeline.tsx` used to hardcode
 * `{ total: 1, bass: 1, mid: 1, high: 1 }`, ignoring that entirely, so the
 * same song's Total/Bass/Mid/High RMS fill bands drew at a different
 * height on Home than on the Timeline page. The fix is
 * `spectra/web/src/lib/shapeScales.ts` — one seed function both pages'
 * `useSticky('scales', ...)` calls can share — and this script transpiles
 * that pure module with esbuild and drives it directly, with no DOM and no
 * browser.
 *
 * Run: node scripts/check_home_rms_scaling.mjs
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SRC = path.join(REPO, 'spectra/web/src/lib/shapeScales.ts');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const out = mkdtempSync(path.join(tmpdir(), 'shapescales-'));
const js = path.join(out, 'shapeScales.mjs');
execFileSync('npx', ['esbuild', SRC, '--format=esm', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const mod = await import(js);

console.log('\n§1 DEFAULT_SHAPE_SCALES is unscaled — the Timeline page\'s own useSticky default');
ok(JSON.stringify(mod.DEFAULT_SHAPE_SCALES) === JSON.stringify({ total: 1, bass: 1, mid: 1, high: 1 }),
  'default scales are all 1');

console.log('\n§2 NO SETTINGS YET -> NO SEED (async-arrival contract useSticky relies on)');
ok(mod.shapeScalesSeed(undefined) === undefined, 'undefined settings yields undefined seed');

console.log('\n§3 A STORED SETTING SEEDS EXACTLY THAT BAND');
const tuned = mod.shapeScalesSeed({
  shape_scale_total: 1.4, shape_scale_bass: 2.0, shape_scale_mid: 0.8, shape_scale_high: 1.1,
});
ok(tuned.total === 1.4, 'total carries the stored shape_scale_total verbatim');
ok(tuned.bass === 2.0, 'bass carries the stored shape_scale_bass verbatim');
ok(tuned.mid === 0.8, 'mid carries the stored shape_scale_mid verbatim');
ok(tuned.high === 1.1, 'high carries the stored shape_scale_high verbatim');

console.log('\n§4 A MISSING BAND IN THE SETTINGS OBJECT FALLS BACK TO 1 — BYTE FOR BYTE WITH THE');
console.log('   TIMELINE PAGE\'S OWN INLINE SEED (BuilderPage.tsx: `Number(settings.shape_scale_X ?? 1)`)');
const partial = mod.shapeScalesSeed({ shape_scale_bass: 3 });
ok(partial.total === 1 && partial.mid === 1 && partial.high === 1,
  'every unset band defaults to 1, matching the Timeline page\'s own `?? 1` fallback');
ok(partial.bass === 3, 'the one set band is still honoured');

console.log('\n§5 A STRING FROM THE WIRE COERCES THE SAME WAY `Number(...)` ALREADY DOES');
const stringy = mod.shapeScalesSeed({ shape_scale_total: '1.5' });
ok(stringy.total === 1.5, 'a numeric string coerces to its number, not NaN');

console.log('\n§6 SETTINGS THAT GENUINELY DISABLE SCALING (ALL 1s) REPRODUCE WHAT HOME ALREADY DID');
const neutral = mod.shapeScalesSeed({
  shape_scale_total: 1, shape_scale_bass: 1, shape_scale_mid: 1, shape_scale_high: 1,
});
ok(JSON.stringify(neutral) === JSON.stringify(mod.DEFAULT_SHAPE_SCALES),
  'a neutral settings object seeds the same shape as the unscaled default — Home never regresses when he has not tuned anything');

console.log(failures ? `\n${failures} FAILED` : '\nALL OK');
process.exit(failures ? 1 : 0);
