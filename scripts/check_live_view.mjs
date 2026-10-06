/** The Live view's three DOM-free parts, driven as the real modules
 * (transpiled with esbuild): the position table (spectra/web/src/live/
 * positions.ts), the playout between frames (stage.ts, through its 2D-canvas
 * path against a stub canvas) and the link meter (linkMeter.ts).
 *
 * The end-to-end proof — a real browser, real WebGL, drawn frames a second —
 * is scripts/preview_perf/run_preview_perf.py with a ":live" system.
 *
 * Run: node scripts/check_live_view.mjs
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SRC = path.join(REPO, 'spectra/web/src/live');
const out = mkdtempSync(path.join(tmpdir(), 'live-view-'));
const load = async (name) => {
  const js = path.join(out, `${name}.mjs`);
  execFileSync('npx', ['esbuild', path.join(SRC, `${name}.ts`), '--format=esm', `--outfile=${js}`], {
    cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
  });
  return import(pathToFileURL(js).href);
};

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const { layoutPositions } = await load('positions');
const { LiveStage } = await load('stage');
const { LinkMeter } = await load('linkMeter');

// A small room: a 4x3 hex matrix with 6 real cells, a strip copied from a
// 10-cell effect, two bulbs fed by one cell.
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

console.log('ONE — the position table');
for (const wide of [true, false]) {
  const plan = layoutPositions(layout, wide);
  const label = wide ? 'wide' : 'phone';
  ok(plan.pointCount === 22 && plan.xy.length === 44 && plan.src.length === 22,
    `${label}: one point per fixture pixel (22)`);
  ok(plan.groups.map((g) => `${g.visId}:${g.first}+${g.count}`).join(' ')
    === 'matrix:0+6 strips:6+14 hues:20+2', `${label}: points are grouped by stream device, contiguous`);
  let inside = true;
  for (let p = 0; p < plan.pointCount; p++) {
    const x = plan.xy[p * 2], y = plan.xy[p * 2 + 1];
    if (!(x >= 0 && x <= plan.width && y >= 0 && y <= plan.height)) inside = false;
  }
  ok(inside, `${label}: every point is inside the stage`);
  const boxes = plan.fixtures;
  let overlap = false;
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i], b = boxes[j];
    if (a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h) overlap = true;
  }
  ok(!overlap, `${label}: no two fixtures overlap`);
  const sconce = boxes.find((f) => f.deviceId === 'sconce');
  ok([...plan.src.slice(sconce.first, sconce.first + 4)].join() === '0,3,6,9',
    `${label}: a copied strip keeps its own source cells`);
}
{
  const plan = layoutPositions(layout, true);
  // hex: cells 0 and 2 share row 0, two columns apart = one pitch; cell 5 is
  // row 1 col 1, half a pitch across and sqrt(3)/2 down.
  const pitch = plan.xy[2] - plan.xy[0];
  const dx = plan.xy[4] - plan.xy[0], dy = plan.xy[5] - plan.xy[1];
  ok(Math.abs(dx - pitch / 2) < 1e-4 && Math.abs(dy - pitch * 0.8660254) < 1e-4,
    'a hex lattice is drawn as one: half a pitch across, sqrt(3)/2 down');
  const tv = plan.fixtures.find((f) => f.deviceId === 'tv');
  const xs = [], ys = [];
  for (let i = 0; i < tv.count; i++) { xs.push(plan.xy[(tv.first + i) * 2]); ys.push(plan.xy[(tv.first + i) * 2 + 1]); }
  const onEdge = xs.every((x, i) => {
    const l = Math.min(...xs), r = Math.max(...xs), t = Math.min(...ys), b = Math.max(...ys);
    return [x - l, r - x, ys[i] - t, b - ys[i]].some((d) => Math.abs(d) < 1e-3);
  });
  ok(onEdge, 'a frame puts every LED on the rectangle\'s edge');
}

console.log('TWO — playout between frames');
const fills = [];
const canvas = {
  width: 100, height: 50, clientWidth: 100, clientHeight: 50,
  addEventListener() {}, removeEventListener() {},
  getContext: (kind) => (kind === '2d' ? {
    set fillStyle(v) { this._fill = v; }, get fillStyle() { return this._fill; },
    fillRect() { fills.push(this._fill); }, beginPath() {}, arc() {}, fill() { fills.push(this._fill); },
  } : null),
};
globalThis.window = { devicePixelRatio: 1 };
const plan = layoutPositions(layout, true);
const hues = plan.groups.find((g) => g.visId === 'hues');
const frame = (r) => ({ visId: 'hues', kind: 'full', rows: 1, cols: 1, cellIndex: null,
                        rgb: new Uint8Array([r, 0, 0]), frameSeq: 0, ageMs: 0 });
const bulbColor = () => fills[fills.length - 1];
{
  const stage = new LiveStage(canvas, true);
  ok(stage.mode === 'canvas', 'with no WebGL2 the stage draws with a plain canvas');
  stage.setPlan(plan);
  ok(stage.draw(0) === true && stage.draw(1) === false,
    'an unchanged picture is drawn once, then not again');
  stage.pushFrame(frame(0), 1000);
  stage.draw(1033);
  stage.pushFrame(frame(200), 1033);      // frames 33 ms apart: a 33 ms ease
  ok(stage.draw(1033) && bulbColor() === 'rgb(15,14,19)', 'a new frame starts from what is on screen');
  stage.draw(1033 + 16.5);
  const mid = Number(/rgb\((\d+)/.exec(bulbColor())[1]);
  ok(mid > 80 && mid < 120, `half an interval later it is half way (${mid} of 200)`);
  stage.draw(1033 + 40);
  ok(bulbColor() === 'rgb(200,14,19)' && stage.draw(1200) === false,
    'after one interval it has arrived, and the stage rests');
  ok(Math.abs(stage.holdMs() - 33) < 20, 'smoothing reports about one frame of delay');

  stage.setSmooth(false);
  stage.pushFrame(frame(90), 2000);
  stage.draw(2000);
  ok(bulbColor() === 'rgb(90,14,19)' && stage.holdMs() === 0,
    'smoothing off: the frame shows at once, and no delay is reported');

  const sconce = plan.fixtures.find((f) => f.deviceId === 'sconce');
  stage.setSolo({ first: sconce.first, count: sconce.count });
  stage.draw(2001);
  ok(bulbColor() === 'rgb(15,14,19)', 'solo dims every other fixture (90 red -> 14, floored)');
  stage.setSolo(null);
  stage.blank();
  stage.draw(2002);
  ok(bulbColor() === 'rgb(15,14,19)', 'blank() takes the picture to dark');
  // a frame for a device the plan does not draw, or a summary frame, is ignored
  stage.pushFrame({ ...frame(255), visId: 'elsewhere' }, 2003);
  stage.pushFrame({ ...frame(255), kind: 'summary' }, 2003);
  ok(stage.draw(2004) === false, 'frames the plan has no points for change nothing');
  ok(hues.count === 2, '(two bulbs, one source cell)');
  stage.pushFrame({ ...frame(255), rgb: new Uint8Array(6) }, 2005);
  ok(stage.stale === true && stage.draw(2006) === false,
    'a frame with a different cell count than the plan is not drawn, and says the layout is stale');
}

console.log('THREE — the link meter');
{
  globalThis.performance = { timeOrigin: 5_000_000, now: () => 0 };
  const meter = new LinkMeter();
  const reading = { fps: 0, delayMs: null, kbps: 0, rateFps: 0 };
  ok(meter.read(0, 0, reading).delayMs === null && reading.fps === 0, 'nothing received: no reading');
  // The server's clock is 7 s ahead of this browser's; the link takes 40 ms
  // one way, and every message is 1000 bytes, 30 a second, for 3 s.
  const stats = { rateFps: 30, srttMs: 80, sentMs: 0, seq: 0 };
  for (let i = 0; i < 90; i++) {
    const at = i * (1000 / 30);
    stats.sentMs = 5_000_000 + at - 40 + 7000;
    meter.note(1000, stats, 10, at);
  }
  meter.read(3000, 33, reading);
  ok(Math.abs(reading.fps - 30) < 1.5, `30 messages a second reads ${reading.fps.toFixed(1)} fps`);
  ok(Math.abs(reading.kbps - 240) < 12, `30 x 1000 bytes reads ${reading.kbps.toFixed(0)} kbit/s`);
  ok(Math.abs(reading.delayMs - (40 + 10 + 33)) < 3,
    `delay = one way 40 + server wait 10 + hold 33, clock difference cancelled (${reading.delayMs.toFixed(0)} ms)`);
  // the link gets 60 ms slower: lateness shows up on top
  for (let i = 90; i < 180; i++) {
    const at = i * (1000 / 30);
    stats.sentMs = 5_000_000 + at - 100 + 7000;
    meter.note(1000, stats, 10, at);
  }
  meter.read(6000, 33, reading);
  ok(reading.delayMs > 130 && reading.delayMs < 150,
    `messages arriving 60 ms later than the link's best add 60 ms (${reading.delayMs.toFixed(0)} ms)`);
}

console.log(failures ? `\n${failures} FAILED` : '\nall passed');
process.exit(failures ? 1 : 0);
