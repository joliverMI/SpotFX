/** A held Hue fixture draws its real colour, never the stream — the
 * defect spectra/services/hue_preview_colour.py's module docstring
 * describes (the Admiral, 2026-10-06: "the hues are showing a yellow
 * green, despite being set to a white (k) setting... I am looking at the
 * preview, not the actual lights").
 *
 * This drives the REAL frontend modules (positions.ts::withHeldOverlay,
 * stage.ts's pushFrame/draw) via esbuild, exactly as check_live_view.mjs
 * does — no DOM, no browser.
 *
 * Run: node scripts/check_hue_preview_colour.mjs
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SRC = path.join(REPO, 'spectra/web/src/live');
const out = mkdtempSync(path.join(tmpdir(), 'hue-preview-colour-'));
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

const { layoutPositions, withHeldOverlay } = await load('positions');
const { LiveStage } = await load('stage');

// His real shape: ONE shared-pixel "hues" virtual, two separate Hue AREAS
// (living/dining) each its own fixture — exactly tests/test_preview_layout.py's
// "hue-lights"/"dining-hues" fixture, scaled down to 1 bulb each.
const LIVING_HELD = '#4a2e08';   // the server's own held hex for this test
const layoutFor = (livingHeld, diningHeld) => ({
  source: 'live',
  virtuals: [
    { id: 'hues', name: 'Hues', rows: 1, cols: 1, cells: 1, mapping: 'copy', hex_lattice: false,
      held: livingHeld && livingHeld === diningHeld ? livingHeld : null,
      fixtures: [
        { device_id: 'hue-lights', name: 'Hue Lights', type: 'hue', kind: 'bulbs', orient: 'h',
          count: 1, src: [0], grid: null, held: livingHeld },
        { device_id: 'dining-hues', name: 'Dining Hues', type: 'hue', kind: 'bulbs', orient: 'h',
          count: 1, src: [0], grid: null, held: diningHeld },
      ] },
  ],
});

console.log('ONE — the position table carries a held colour per fixture, never per cell');
{
  const layout = layoutFor(LIVING_HELD, '#30221a');
  const plan = withHeldOverlay(layoutPositions(layout, true), layout);
  ok(!!plan.held, 'the plan carries an overlay when any fixture is held');
  const living = plan.fixtures.find((f) => f.deviceId === 'hue-lights');
  const dining = plan.fixtures.find((f) => f.deviceId === 'dining-hues');
  ok(plan.held.mask[living.first] === 1 && plan.held.mask[dining.first] === 1,
    'both held fixtures are masked');
  const hex = (p) => `#${[0, 1, 2].map((k) => plan.held.rgb[p * 3 + k].toString(16).padStart(2, '0')).join('')}`;
  ok(hex(living.first) === LIVING_HELD, 'living reads its OWN held colour');
  ok(hex(dining.first) === '#30221a', 'dining reads ITS OWN held colour — not living\'s');
  ok(hex(living.first) !== hex(dining.first),
    'two areas sharing one effect pixel still preview as two different colours');
}

console.log('TWO — with no hold, the overlay is absent and nothing is allocated');
{
  const layout = layoutFor(null, null);
  const base = layoutPositions(layout, true);
  const plan = withHeldOverlay(base, layout);
  ok(plan === base, 'an un-held plan is returned unchanged (byte-identical reference)');
  ok(plan.held === undefined, 'no overlay object exists');
}

console.log('THREE — the held colour wins over whatever the virtual is actually rendering');
{
  // The room's live show happens to be painting this virtual a literal
  // yellow-green (200, 230, 40) — exactly the Admiral's own report — while
  // dining is HELD at a warm colour via Hue Hold.
  const layout = layoutFor(null, '#ffb347');
  const plan = withHeldOverlay(layoutPositions(layout, true), layout);
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
  const stage = new LiveStage(canvas, true);
  stage.setSmooth(false);
  stage.setPlan(plan);
  stage.pushFrame({ visId: 'hues', kind: 'full', rows: 1, cols: 1, cellIndex: null,
    rgb: new Uint8Array([200, 230, 40]), frameSeq: 0, ageMs: 0 }, 1000);
  stage.draw(1000);
  const living = plan.fixtures.find((f) => f.deviceId === 'hue-lights');
  const dining = plan.fixtures.find((f) => f.deviceId === 'dining-hues');
  // fills[0] is the background clear; each point's own draw follows in order.
  const colorOf = (p) => fills[1 + p];
  ok(colorOf(living.first) === 'rgb(200,230,40)',
    'the un-held area still shows whatever the show is actually rendering');
  ok(colorOf(dining.first) === 'rgb(255,179,71)',
    'the HELD area shows its real held colour, not the shared effect pixel');
  ok(colorOf(dining.first) !== colorOf(living.first),
    'one virtual, one shared pixel, two different previewed colours');
}

process.exit(failures ? 1 : 0);
