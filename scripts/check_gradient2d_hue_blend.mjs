/** Parity spec for the 2D drift gradient's hue-path blend: the square
 * preview (spectra/web/src/lib/gradient2dSample.ts) must draw the SAME
 * colours the room is driven with (spectra/models/gradient2d.py). Transpiles
 * the REAL frontend module with esbuild and compares it, sample by sample,
 * against the Python implementation run over the same grid — so either side
 * drifting (or falling back to an RGB mix) goes red here.
 *
 * Run: node scripts/check_gradient2d_hue_blend.mjs
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'spectra/web/src/lib/gradient2dSample.ts');
const out = mkdtempSync(path.join(tmpdir(), 'grad2d-'));
const js = path.join(out, 'gradient2dSample.mjs');
execFileSync('npx', ['esbuild', TS, '--format=esm', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const fe = await import(js);

// His live "Normal" gradient (storage/spectra/gradients2d.json, 2026-09-26)
// plus a few edge cases (achromatic ends, complementary pairs).
const CASES = [
  ['linear-gradient(90deg, #ff1e00 0.00%,#ffe300 12.00%,#0cff00 31.00%,#00ffeb 46.00%,#0060ff 62.00%,#b000ff 77.00%,#ff00a8 100.00%)',
   'linear-gradient(90deg, #006cff 0.00%,#9100ff 100.00%)'],
  ['#ffff00', '#0000ff'], ['#ff0000', '#00ffff'], ['#ffffff', '#ff0000'],
  ['#000000', '#00ff00'],
];
const grid = [];
for (const [top, bottom] of CASES) {
  for (let xi = 0; xi <= 10; xi++) {
    for (let yi = 0; yi <= 10; yi++) grid.push([top, bottom, xi / 10, yi / 10]);
  }
}
const py = JSON.parse(execFileSync(path.join(REPO, '.venv/bin/python'), ['-c', `
import json, sys
sys.path.insert(0, ${JSON.stringify(REPO)})
from spectra.models.gradient2d import sample
grid = json.loads(sys.stdin.read())
print(json.dumps([sample(t, b, x, y) for t, b, x, y in grid]))
`], { input: JSON.stringify(grid) }).toString());

let mismatches = 0;
const channelDiff = (a, b) => Math.max(...[1, 3, 5].map(
  (i) => Math.abs(parseInt(a.slice(i, i + 2), 16) - parseInt(b.slice(i, i + 2), 16))));
grid.forEach(([t, b, x, y], i) => {
  const ts = fe.sample2d(t, b, x, y);
  if (ts === null || py[i] === null ? ts !== py[i] : channelDiff(ts, py[i]) > 1) {
    mismatches += 1;
    if (mismatches <= 5) console.log(`  ✗ (${x}, ${y}) ts=${ts} py=${py[i]}`);
  }
});
console.log(mismatches === 0
  ? `  ✓ ${grid.length} samples: preview and room agree (±1 per channel)`
  : `  ✗ ${mismatches}/${grid.length} samples disagree`);
process.exit(mismatches === 0 ? 0 : 1);
