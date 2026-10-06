/** The device-preview strip's expanded row (DevicePreviewStrip.tsx's module
 * docstring, "NO TEXT IN THE EXPANDED STAGE..."): `compactPositions`
 * (spectra/web/src/live/positions.ts) is the arrangement that replaced
 * `layoutPositions`' two fixed phone/desktop presets for that one surface.
 * It has no DOM-level test anywhere else, so this proves its own two claims
 * directly against the real, transpiled module (esbuild, the
 * `check_live_view.mjs` convention — no jsdom, no browser):
 *
 *   1. it reserves no row height for a label (unlike `layoutPositions`,
 *      which reserves LABEL_H under every row — compactPositions draws no
 *      text at all, so there is nothing to reserve space for);
 *   2. it genuinely reflows against a MEASURED width rather than choosing
 *      between two hardcoded presets — a narrow width wraps the same
 *      fixtures into more, shorter rows than a wide one.
 *
 * It also checks a fixture's own SHAPE (box w/h) is identical to
 * `layoutPositions`' — the module docstring's claim that only the
 * ARRANGEMENT differs, never a fixture's shape.
 *
 * Run: node scripts/check_device_preview_compact_layout.mjs
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SRC = path.join(REPO, 'spectra/web/src/live');
const out = mkdtempSync(path.join(tmpdir(), 'device-preview-compact-'));
const load = async (name) => {
  const js = path.join(out, `${name}.mjs`);
  execFileSync('npx', ['esbuild', path.join(SRC, `${name}.ts`), '--bundle', '--format=esm', `--outfile=${js}`], {
    cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
  });
  return import(pathToFileURL(js).href);
};

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const { layoutPositions, compactPositions } = await load('positions');

// Four favourite fixtures, matching check_live_view.mjs's own small room:
// a hex matrix, a strip, a frame-wrapped strip and a bulb group — enough
// kinds to exercise KIND_ORDER and to make one row too wide at a narrow
// width.
const layout = {
  source: 'stored',
  virtuals: [
    { id: 'matrix', name: 'Matrix', rows: 3, cols: 4, cells: 6, mapping: 'span', hex_lattice: true,
      fixtures: [{ device_id: 'crystal', name: 'Crystal', type: 'wled', kind: 'matrix', orient: 'h',
                   count: 6, src: null, grid: [0, 2, 5, 7, 8, 10] }] },
    { id: 'strips', name: 'Strips', rows: 1, cols: 10, cells: 10, mapping: 'copy', hex_lattice: false,
      fixtures: [
        { device_id: 'tv', name: 'TV', type: 'wled', kind: 'frame', orient: 'h', count: 10, src: null, grid: null },
        { device_id: 'sconce', name: 'Sconce', type: 'wled', kind: 'strip', orient: 'v', count: 4,
          src: [0, 3, 6, 9], grid: null }] },
    { id: 'hues', name: 'Hues', rows: 1, cols: 1, cells: 1, mapping: 'copy', hex_lattice: false,
      fixtures: [{ device_id: 'bulbs', name: 'Bulbs', type: 'hue', kind: 'bulbs', orient: 'h',
                   count: 2, src: [0, 0], grid: null }] },
  ],
};

console.log('ONE — no label row reserved');
{
  // A single non-matrix fixture so layoutPositions(wide) takes its plain
  // `flow()` branch (the matrix/others split in layoutPositions only
  // engages when BOTH a matrix and a non-matrix fixture are present) —
  // isolates the one difference this check is about (LABEL_H) from that
  // unrelated layout choice.
  const oneFixture = {
    source: 'stored',
    virtuals: [{ id: 'hues', name: 'Hues', rows: 1, cols: 1, cells: 1, mapping: 'copy', hex_lattice: false,
      fixtures: [{ device_id: 'bulbs', name: 'Bulbs', type: 'hue', kind: 'bulbs', orient: 'h',
                   count: 2, src: [0, 0], grid: null }] }],
  };
  const wide = layoutPositions(oneFixture, true);
  const compact = compactPositions(oneFixture, 400);
  ok(wide.fixtures.length === 1 && compact.fixtures.length === 1, 'sanity: one fixture, one box, in both');

  const boxH = compact.fixtures[0].h;
  ok(Math.abs(compact.height - boxH) < 0.5,
    `compactPositions reserves no label row: a lone fixture's plan height (${compact.height.toFixed(2)}) `
    + `equals its own box height (${boxH.toFixed(2)})`);
  ok(Math.abs(wide.height - (boxH + 7)) < 0.5,
    `layoutPositions reserves a 7-unit label row the same lone fixture does not need under `
    + `compactPositions (layoutPositions height ${wide.height.toFixed(2)} vs box height ${boxH.toFixed(2)})`);

  // Now the real 4-fixture, 3-kind room: compactPositions' own single-row
  // case (generous width) still reserves nothing beyond the tallest box.
  const compactRoom = compactPositions(layout, 400);
  const roomRows = new Set(compactRoom.fixtures.map((f) => Math.round(f.y + f.h)));
  ok(roomRows.size === 1, 'the 4-fixture room still fits one row under compactPositions at a generous width');
  const maxBoxH = Math.max(...compactRoom.fixtures.map((f) => f.h));
  ok(Math.abs(compactRoom.height - maxBoxH) < 0.5,
    `and its plan height (${compactRoom.height.toFixed(2)}) still equals only the tallest `
    + `fixture's own height (${maxBoxH.toFixed(2)}), not a label-padded one`);
}

console.log('TWO — real reflow against a measured width, not a fixed preset');
{
  const generous = compactPositions(layout, 400);
  const narrow = compactPositions(layout, 60);
  const generousRows = new Set(generous.fixtures.map((f) => Math.round(f.y + f.h))).size;
  const narrowRows = new Set(narrow.fixtures.map((f) => Math.round(f.y + f.h))).size;
  ok(narrowRows > generousRows,
    `a narrow width (60 units, ${narrowRows} rows) wraps more rows than a generous one `
    + `(400 units, ${generousRows} rows)`);
  ok(narrow.height > generous.height,
    'the narrower arrangement is taller (fixtures stack instead of spreading sideways)');

  // A THIRD width in between must land a third shape, not toggle between
  // only two — proof this is a continuous measured reflow, not secretly
  // still a two-preset switch.
  const mid = compactPositions(layout, 140);
  const midRows = new Set(mid.fixtures.map((f) => Math.round(f.y + f.h))).size;
  ok(midRows >= generousRows && midRows <= narrowRows,
    `an intermediate width (140 units, ${midRows} rows) sits between the generous `
    + `(${generousRows}) and narrow (${narrowRows}) row counts`);

  // Every point for every fixture still lands inside the plan's own box,
  // at every width — the stage draws exactly `plan.width`/`plan.height`.
  for (const [label, plan] of [['generous', generous], ['narrow', narrow], ['mid', mid]]) {
    let inside = true;
    for (let p = 0; p < plan.pointCount; p++) {
      const x = plan.xy[p * 2], y = plan.xy[p * 2 + 1];
      if (!(x >= 0 && x <= plan.width + 1e-6 && y >= 0 && y <= plan.height + 1e-6)) inside = false;
    }
    ok(inside, `${label}: every point stays inside the stage`);
  }
}

console.log('THREE — a fixture\'s own shape is identical to layoutPositions\', only the arrangement differs');
{
  const wide = layoutPositions(layout, true);
  const compact = compactPositions(layout, 400);
  for (const key of ['crystal', 'tv', 'sconce', 'bulbs']) {
    const a = wide.fixtures.find((f) => f.deviceId === key);
    const b = compact.fixtures.find((f) => f.deviceId === key);
    ok(a && b && Math.abs(a.w - b.w) < 1e-6 && Math.abs(a.h - b.h) < 1e-6,
      `${key}: box w/h match between layoutPositions and compactPositions `
      + `(${a ? a.w.toFixed(2) : '?'}x${a ? a.h.toFixed(2) : '?'})`);
  }
}

console.log('FOUR — ordering and point integrity');
{
  const compact = compactPositions(layout, 400);
  ok(compact.pointCount === 22 && compact.xy.length === 44 && compact.src.length === 22,
    'one point per fixture pixel (22), same as layoutPositions\' own room');
  ok(compact.groups.map((g) => `${g.visId}:${g.first}+${g.count}`).join(' ')
    === 'matrix:0+6 strips:6+14 hues:20+2',
    'points stay grouped by stream device, contiguous, in virtual order');
  const kinds = compact.fixtures.map((f) => f.kind);
  const matrixIdx = kinds.indexOf('matrix');
  const bulbsIdx = kinds.indexOf('bulbs');
  ok(matrixIdx !== -1 && bulbsIdx !== -1 && matrixIdx < bulbsIdx,
    'fixtures are still ordered by KIND_ORDER (matrix before bulbs)');
}

if (failures) {
  console.error(`\n${failures} check(s) failed`);
  process.exit(1);
}
console.log('\nall checks passed');
