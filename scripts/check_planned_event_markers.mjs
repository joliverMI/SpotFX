/**
 * Executable spec for the debug page's planned-event markers
 * (spectra/web/src/debug/plannedEvents.ts).
 *
 * Transpiles the REAL module with esbuild and drives it, zero network.
 *
 * Proves:
 *   ONE   — THE ALIGNMENT: simulate the trigger clock and the canvas playhead
 *           from the same raw position; at the tick the trigger clock reaches
 *           an event's song time, the canvas playhead sits exactly on that
 *           event's marker (both signs of lead/shift, with and without a
 *           bridge shape offset).
 *   TWO   — two kinds, both lists, sorted by time.
 *   THREE — a plan that does not apply (Transitions only / an authored song)
 *           draws nothing; a missing plan draws nothing.
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'spectra/web/src/debug/plannedEvents.ts');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const tmp = mkdtempSync(path.join(tmpdir(), 'plannedev-'));
const js = path.join(tmp, 'plannedEvents.mjs');
execFileSync('npx', ['esbuild', TS, '--format=esm', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const { plannedMarkerMs, plannedMarkers } = await import(js);

console.log('ONE — the playhead crosses a marker when the event fires');
for (const [lead, buf, bridgeShape, latency, trim, canvasShape] of [
  [0, 0, 0, 0, 0, 0],
  [120, 0, 300, 150, 0, 300],
  [-80, 250, 7052, 150, 40, 7052],
  [200, 500, 0, 150, -60, 900], // bridge has no lock, canvas uses meta offset
]) {
  const S = lead - buf;                                  // show_clock − effective
  const canvasShift = -latency + canvasShape - trim;     // DebugPage playheadShift
  const T = 60_000;
  // Find the raw position at which the trigger clock reaches T.
  const raw = T - S - bridgeShape;
  const showClock = raw + bridgeShape + S;
  const canvasNow = raw + canvasShift;
  const marker = plannedMarkerMs(T, S, canvasShift, bridgeShape);
  ok(showClock === T && canvasNow === marker,
    `lead=${lead} buf=${buf} bridgeShape=${bridgeShape} → marker ${marker} == playhead ${canvasNow}`);
}

console.log('TWO — both kinds, sorted');
const plan = {
  uri: 'u', applies: true, reason: null, effective_mode: 'analysed', has_authored: false,
  scene_source: 'stored', show_clock_shift_ms: 100,
  scene_changes: [{ timestamp_ms: 30_000, intensity: 0.5 }, { timestamp_ms: 10_000, intensity: 0.5 }],
  flares: [{ timestamp_ms: 20_000, intensity: 0.3 }],
};
const m = plannedMarkers(plan, 0, 0);
ok(JSON.stringify(m) === JSON.stringify([
  { ms: 9_900, kind: 'scene' }, { ms: 19_900, kind: 'flare' }, { ms: 29_900, kind: 'scene' },
]), `markers ${JSON.stringify(m)}`);

console.log('THREE — nothing drawn when analysed events do not apply');
ok(plannedMarkers({ ...plan, applies: false }, 0, 0).length === 0, 'applies=false → no markers');
ok(plannedMarkers(null, 0, 0).length === 0, 'no plan → no markers');

rmSync(tmp, { recursive: true, force: true });
if (failures) { console.log(`\n${failures} FAILED`); process.exit(1); }
console.log('\nALL CHECKS PASSED');
