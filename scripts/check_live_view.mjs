/** The Live view's DOM-free parts, driven as the real modules (transpiled
 * with esbuild): the position table (spectra/web/src/live/positions.ts), the
 * playout between frames (stage.ts, through its 2D-canvas path against a
 * stub canvas), the link meter (linkMeter.ts), and the room map — the second
 * position table (roomMap.ts) and the glow the stage adds up under it.
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

const { layoutPositions } = await load('positions');
const { LiveStage } = await load('stage');
const { LinkMeter } = await load('linkMeter');
const { roomMapPositions, decodeRoomView, STAGE_W, STAGE_H } = await load('roomMap');

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

console.log('FOUR — the room map: the same renderer, another position table');
{
  // One camera pose of the small room, on a 4x2 glow grid. The matrix is
  // placed whole at its light; half the TV strip is a measured block, the
  // other half has per-pixel positions; the sconce and the bulbs are nobody's.
  const b64 = (bytes) => Buffer.from(Uint8Array.from(bytes)).toString('base64');
  const view = {
    pose_id: 'p', label: 'Pose', rooms: [], captured_at: 0, grid: { w: 4, h: 2 }, aspect: 16 / 9,
    backdrop: b64([0, 0, 0, 0, 100, 100, 100, 100]),
    emitters: [
      { id: 'matrix', label: 'Matrix', room: 'r', weight: 1, centre: [0.5, 0.5], glow: b64([0, 255, 128, 0, 0, 0, 0, 0]),
        pixels: [{ virtual_id: 'matrix', device_id: 'crystal', first: 0, count: 6 }] },
      { id: 'tv:blk0', label: 'TV 0-4', room: 'r', weight: 1, centre: [0.25, 0.25], glow: b64([0, 0, 255, 0, 0, 0, 0, 0]),
        pixels: [{ virtual_id: 'strips', device_id: 'tv', first: 0, count: 5 }] },
    ],
    pieces: [
      { key: 'matrix/crystal:0-5', virtual_id: 'matrix', device_id: 'crystal', first: 0, count: 6, label: 'Crystal',
        source: 'footprint', emitter: 0, at: { x: 0.5, y: 0.5, r: 0.05 }, xy: null, cluster: false, note: '' },
      { key: 'strips/tv:0-4', virtual_id: 'strips', device_id: 'tv', first: 0, count: 5, label: 'TV px 0–4',
        source: 'footprint', emitter: 1, at: { x: 0.25, y: 0.25, r: 0.02 }, xy: null, cluster: true, note: '' },
      { key: 'strips/tv:5-9', virtual_id: 'strips', device_id: 'tv', first: 5, count: 5, label: 'TV px 5–9',
        source: 'decode', emitter: null, at: null, xy: [0.6, 0.1, 0.62, 0.1, 0.64, 0.1, 0.66, 0.1, 0.68, 0.1],
        cluster: false, note: '' },
      { key: 'strips/sconce:0-3', virtual_id: 'strips', device_id: 'sconce', first: 0, count: 4, label: 'Sconce',
        source: 'unseen', emitter: null, at: null, xy: null, cluster: false, note: 'not seen' },
      { key: 'hues/bulbs:0-0', virtual_id: 'hues', device_id: 'bulbs', first: 0, count: 1, label: 'Bulbs lamp 1',
        source: 'unmapped', emitter: null, at: null, xy: null, cluster: false, note: '' },
      { key: 'hues/bulbs:1-1', virtual_id: 'hues', device_id: 'bulbs', first: 1, count: 1, label: 'Bulbs lamp 2',
        source: 'unmapped', emitter: null, at: null, xy: null, cluster: false, note: '' },
    ],
    hand: {}, notes: [], layout_source: 'stored',
  };
  const decoded = decodeRoomView(view);
  const at = (plan, key) => plan.fixtures.find((f) => f.key === key);
  const points = (plan, f) => Array.from({ length: f.count },
    (_, i) => [plan.xy[(f.first + i) * 2], plan.xy[(f.first + i) * 2 + 1], plan.size[f.first + i]]);

  const whole = roomMapPositions(layout, view, decoded, {}, { fit: false });
  ok(whole.width === STAGE_W && whole.height === STAGE_H && whole.pointCount === 22,
    'the stage is the camera\'s 16:9 picture, and EVERY fixture pixel is in the plan (22)');
  ok(whole.groups.map((g) => `${g.visId}:${g.first}+${g.count}`).join(' ')
    === 'matrix:0+6 strips:6+14 hues:20+2', 'points stay grouped by stream device, as the renderer needs');
  ok(whole.tray.map((t) => t.key).join() === 'strips/sconce:0-3,hues/bulbs:0-0,hues/bulbs:1-1'
    && whole.counts.camera === 3 && whole.counts.tray === 3,
    'a piece nobody placed goes to the tray: the unseen sconce and both bulbs');
  let hidden = 0;
  for (let p = 0; p < 22; p++) if (whole.size[p] === 0) hidden++;
  ok(hidden === 6, 'a tray piece keeps its pixels in the plan at size 0 — not drawn, still coloured');

  const crystal = points(whole, at(whole, 'matrix/crystal:0-5'));
  const cx = crystal.reduce((n, p) => n + p[0], 0) / 6, cy = crystal.reduce((n, p) => n + p[1], 0) / 6;
  ok(crystal.every((p) => Math.hypot(p[0] - 0.5 * STAGE_W, p[1] - 0.5 * STAGE_H) <= 0.05 * STAGE_W + 1e-3)
    && Math.abs(cx - 80) < 2 && Math.abs(cy - 45) < 2,
    'a whole fixture keeps its own shape, fitted to the size of its light and centred on it');
  const row0 = crystal[1][0] - crystal[0][0], row1 = crystal[2];
  ok(Math.abs((row1[0] - crystal[0][0]) - row0 / 2) < 1e-3 && row1[1] > crystal[0][1],
    '… still a hex lattice: the next row is half a pitch across');
  const block = points(whole, at(whole, 'strips/tv:0-4'));
  ok(block.every((p) => Math.hypot(p[0] - 40, p[1] - 22.5) <= 0.02 * STAGE_W + 1e-3)
    && new Set(block.map((p) => `${p[0].toFixed(2)},${p[1].toFixed(2)}`)).size === 5,
    'a measured block of a strip is a round cluster at its light — no direction is claimed');
  const exact = points(whole, at(whole, 'strips/tv:5-9'));
  ok(exact.every((p, i) => Math.abs(p[0] - (0.6 + i * 0.02) * STAGE_W) < 1e-3 && Math.abs(p[1] - 9) < 1e-3),
    'per-pixel positions are drawn exactly where they were read');
  ok(at(whole, 'strips/tv:0-4').placedBy === 'camera' && Math.abs(at(whole, 'strips/tv:0-4').placement.x - 0.25) < 1e-9,
    'a camera-placed piece knows where it sits, to start a move by hand from');

  // his hand: a bulb dropped, the sconce placed and turned, the block moved
  const hand = {
    'hues/bulbs:1-1': { x: 0.9, y: 0.2, size: 0.03, angle: 0 },
    'strips/sconce:0-3': { x: 0.75, y: 0.5, size: 0.2, angle: 0 },
    'strips/tv:0-4': { x: 0.1, y: 0.9, size: 0.1, angle: 0 },
  };
  const placed = roomMapPositions(layout, view, decoded, hand, { fit: false });
  const bulb = points(placed, at(placed, 'hues/bulbs:1-1'))[0];
  ok(Math.abs(bulb[0] - 144) < 1e-3 && Math.abs(bulb[1] - 18) < 1e-3 && Math.abs(bulb[2] - 4.8) < 1e-3,
    'a hand-placed lamp sits where he put it, as big as he made it');
  const upright = points(placed, at(placed, 'strips/sconce:0-3'));
  ok(upright.every((p) => Math.abs(p[0] - 120) < 1e-3) && upright[0][1] > upright[3][1]
    && Math.abs(Math.abs(upright[0][1] - upright[3][1]) + upright[0][2] - 32) < 3,
    'a hand-placed strip is that fixture\'s own line (a sconce runs up), about as long as he set (32 units)');
  const turned = points(roomMapPositions(layout, view, decoded,
    { ...hand, 'strips/sconce:0-3': { x: 0.75, y: 0.5, size: 0.2, angle: 90 } }, { fit: false }),
    at(placed, 'strips/sconce:0-3'));
  ok(turned.every((p) => Math.abs(p[1] - 45) < 1e-3) && Math.abs(turned[0][0] - turned[3][0]) > 20,
    'turning it a quarter lays the line across');
  ok(at(placed, 'strips/tv:0-4').placedBy === 'hand' && placed.counts.hand === 3 && placed.counts.tray === 1
    && points(placed, at(placed, 'strips/tv:0-4')).every((p) => Math.hypot(p[0] - 16, p[1] - 81) <= 12),
    'his hand outranks the camera: the block is where he moved it');

  const fitted = roomMapPositions(layout, view, decoded, {}, { fit: true });
  let inside = true;
  for (let p = 0; p < fitted.pointCount; p++) {
    if (fitted.size[p] > 0 && !(fitted.xy[p * 2] >= 0 && fitted.xy[p * 2] <= fitted.width
      && fitted.xy[p * 2 + 1] >= 0 && fitted.xy[p * 2 + 1] <= fitted.height)) inside = false;
  }
  ok(fitted.width < STAGE_W && Math.abs(fitted.width / fitted.height - 16 / 9) < 1e-6 && inside,
    `"Fit lights" shows the part of the picture the lights are in (${fitted.width.toFixed(0)} of ${STAGE_W} wide), same shape`);
  ok(Math.abs(fitted.glow.crop[2] - fitted.glow.crop[0] - fitted.width / STAGE_W) < 1e-6
    && Math.abs(fitted.glow.crop[0] - fitted.frame.x / STAGE_W) < 1e-6,
    '… and the glow is cropped to the same part');
  const pinned = roomMapPositions(layout, view, decoded, hand, { fit: true, frame: fitted.frame });
  ok(pinned.frame.x === fitted.frame.x && pinned.width === fitted.width,
    'a pinned frame holds still while a piece is dragged');

  // the glow: each emitter's footprint times its live colour, added up
  ok([...whole.glow.emitters[0].points].join() === '0,1,2,3,4,5'
    && [...whole.glow.emitters[1].points].join() === '6,7,8,9,10'
    && [...whole.glow.emitters[0].cells].join() === '1,2' && [...whole.glow.emitters[0].weights].join() === '255,128',
    'an emitter is the cells its light reaches and the pixels it lit');
  const stage = new LiveStage(canvas, true);
  stage.setSmooth(false);
  stage.setPlan(whole);
  const paint = (visId, cells, rgb) => stage.pushFrame({
    visId, kind: 'full', rows: 1, cols: cells, cellIndex: null,
    rgb: Uint8Array.from({ length: cells * 3 }, (_, i) => rgb[i % 3]), frameSeq: 0, ageMs: 0 }, 5000);
  const cell = (c) => [...stage.glowPixels().slice(c * 4, c * 4 + 3)];
  stage.draw(5000);
  ok(cell(0).join() === '6,4,11' && cell(4)[0] > 6 && cell(4)[2] > cell(4)[0],
    'with every light dark the picture is the stage\'s dark plus the dim backdrop');
  paint('matrix', 6, [255, 0, 0]);
  stage.draw(5001);
  const red = cell(1), half = cell(2);
  ok(red[0] > 120 && red[1] === 4 && red[2] === 11 && half[0] > 60 && half[0] < red[0],
    `a lit emitter tints its own footprint with its live colour (${red[0]} at its peak, ${half[0]} at half)`);
  paint('strips', 10, [0, 0, 255]);
  stage.draw(5002);
  const both = cell(2);
  ok(both[0] === half[0] && both[2] > 120 && cell(1)[2] === 11,
    'two emitters ADD where their light overlaps, and only there');
  const before = fills.length;
  stage.setSolo({ first: 6, count: 5 });
  stage.draw(5003);
  ok(cell(1)[0] < red[0] / 2 && cell(2)[2] === both[2],
    'solo dims the glow of everything else with its pixels');
  ok(fills.length - before === 1 + 16, 'pixels at size 0 are not drawn (16 of 22 dots, and the clear)');
}

console.log(failures ? `\n${failures} FAILED` : '\nall passed');
process.exit(failures ? 1 : 0);
