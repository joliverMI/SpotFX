/** Executable spec: the screens draw ENERGY the way the Admiral asked
 * (2026-10-28, the Energy plan, https://claude.ai/artifact/2Dy1SnUgNQ2fJQomhk4dkh;
 * spectra/services/energy.py is the binding statement).
 *
 *  ONE   lib/energyAt.ts — the top bar's lookup: the section holding a
 *        song-time moment, gaps to the nearer one, no math of its own.
 *  TWO   the song strip's terrain (components/songStrip.ts::terrainPath):
 *        FULL HEIGHT — 0 is an empty strip, 1.0 (or more) reaches the
 *        panel's top edge. Red control: the old 0.15-floored, 14 px terrain.
 *  THREE the audio shape's 'section' background (timeline/canvas/layers.ts
 *        intensityBackground): 1.0 fills the plot to its very top (y 0, not
 *        the old 10% below it, under the markers), 0 draws nothing, and the
 *        blocks sit in SONG time with no librosa offset added.
 *
 * Run: node scripts/check_energy_screens.mjs
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SRC = path.join(REPO, 'spectra/web/src');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const out = mkdtempSync(path.join(tmpdir(), 'energy-screens-'));
const entry = path.join(out, 'entry.ts');
writeFileSync(entry, [
  `export { energyAt, energyFill } from ${JSON.stringify(path.join(SRC, 'lib/energyAt.ts'))};`,
  `export { terrainPath, TRACK_HEIGHT } from ${JSON.stringify(path.join(SRC, 'components/songStrip.ts'))};`,
  `export { intensityBackground } from ${JSON.stringify(path.join(SRC, 'timeline/canvas/layers.ts'))};`,
].join('\n'));
const js = path.join(out, 'bundle.mjs');
execFileSync('npx', ['esbuild', entry, '--bundle', '--format=esm', '--platform=node',
  '--log-level=error', `--outfile=${js}`],
  { cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'] });
const M = await import(pathToFileURL(js).href);

const SECS = [
  { start_ms: 5_000, end_ms: 25_000, raw: 0.4, normalized: 0, energy: 0 },
  { start_ms: 25_000, end_ms: 45_000, raw: 1.0, normalized: 1, energy: 0.8 },
  { start_ms: 47_000, end_ms: 65_000, raw: 0.7, normalized: 0.5, energy: 1.0 },
];

console.log('\nONE  the top bar\'s lookup');
ok(M.energyAt(SECS, 10_000) === 0 && M.energyAt(SECS, 30_000) === 0.8, 'the section holding the moment');
ok(M.energyAt(SECS, 1_000) === 0 && M.energyAt(SECS, 99_000) === 1.0, 'before the first / after the last');
ok(M.energyAt(SECS, 45_500) === 0.8 && M.energyAt(SECS, 46_500) === 1.0, 'a gap reads the nearer section');
ok(M.energyAt(null, 1) === null && M.energyAt(SECS, null) === null, 'nothing to read is null, never a guess');
ok(M.energyFill(1.4) === 1 && M.energyFill(-0.2) === 0 && M.energyFill(0.5) === 0.5, 'a fill is clamped to the bar');

console.log('\nTWO  the song strip\'s terrain fills the strip');
const H = M.TRACK_HEIGHT;
const ys = (d) => [...d.matchAll(/L[\d.]+ ([\d.]+)/g)].map((m) => Number(m[1]));
const terrain = M.terrainPath(SECS, 65_000, 400, H);
const levels = ys(terrain);
ok(levels.includes(1), `Energy 1.0 reaches the panel's top edge (y 1), got ${Math.min(...levels)}`);
ok(levels.includes(H - 1), 'Energy 0 is an empty strip (the floor, y 38)');
const loud = M.terrainPath([{ ...SECS[0], energy: 3 }], 65_000, 400, H);
ok(ys(loud).includes(1), 'over 1.0 still stops at the top');
// the old rule, as a red control: energy floored at 0.15, 14 px tall
const old = (e) => (H - 2) - Math.max(0.15, Math.min(1, e)) * 14;
ok(old(1.0) === 23 && old(0) > 33, 'red control: the old terrain topped out at y 23 and never emptied');

console.log('\nTHREE the audio shape\'s Energy background fills the plot');
const rects = [];
const ctx = new Proxy({}, {
  get: (_t, k) => (k === 'fillRect' ? (x, y, w, h) => rects.push({ x, y, w, h }) : () => {}),
  set: () => true,
});
const mainH = 200;
const frame = {
  ctx, w: 650, mainH,
  view: { intensityMode: 'section', librosaOffsetMs: 9_999 },
  timeToX: (ms) => ms / 100,
  data: { energy: { status: 'ok', sections: SECS } },
};
M.intensityBackground.draw(frame);
const byX = new Map(rects.map((r) => [Math.round(r.x), r]));
const at = (ms) => byX.get(Math.round(ms / 100));
ok(at(47_000)?.y === 0, `Energy 1.0 fills to the very top (y 0), got ${at(47_000)?.y}`);
ok(Math.abs(at(25_000)?.y - mainH * 0.2) < 1e-9, 'Energy 0.8 fills 80% of the plot');
ok(at(5_000)?.h === 0, 'Energy 0 draws an empty block');
ok(rects.every((r) => Math.round(r.x) !== Math.round((5_000 + 9_999) / 100)),
  'blocks sit in song time: no librosa offset is added');
frame.view.intensityMode = 'triggers';
rects.length = 0;
M.intensityBackground.draw(frame);
ok(rects.length === SECS.length, 'a saved "trigger values" choice draws Energy, not stored values');

console.log(failures ? `\n${failures} FAILED` : '\nALL OK');
process.exit(failures ? 1 : 0);
