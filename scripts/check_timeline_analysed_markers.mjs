/**
 * Executable spec for the Timeline (Builder) page's analysed-event markers
 * (spectra/web/src/debug/plannedEvents.ts's `songPositionMarkers`, reused
 * by spectra/web/src/timeline/BuilderPage.tsx — see that module's own
 * docstring for why the Timeline's placement differs from the debug page's
 * clock-shifted `plannedMarkers`).
 *
 * Transpiles the REAL module with esbuild and drives it, zero network.
 *
 * Proves:
 *   ONE   — an event lands at its RAW song-time timestamp_ms, unshifted —
 *           no show_clock_shift_ms, no bridge/canvas clock terms at all.
 *   TWO   — two kinds, both lists, sorted by time (matches debug's own
 *           ordering rule).
 *   THREE — a plan that does not apply (Transitions only / an authored
 *           song) draws nothing; a missing plan draws nothing.
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

const tmp = mkdtempSync(path.join(tmpdir(), 'timeline-analysed-'));
const js = path.join(tmp, 'plannedEvents.mjs');
execFileSync('npx', ['esbuild', TS, '--format=esm', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const { songPositionMarkers } = await import(js);

console.log('ONE — markers land at the raw song-time timestamp, no clock shift');
{
  const plan = {
    uri: 'u', applies: true, reason: null, effective_mode: 'analysed', has_authored: false,
    scene_source: 'stored',
    // A large show_clock_shift_ms must have NO effect on Timeline placement —
    // that term only matters to a canvas whose axis is the live playhead.
    show_clock_shift_ms: 123_456,
    scene_changes: [{ timestamp_ms: 30_000, intensity: 0.5 }],
    flares: [{ timestamp_ms: 20_000, intensity: 0.3 }],
  };
  const m = songPositionMarkers(plan);
  ok(JSON.stringify(m) === JSON.stringify([
    { ms: 20_000, kind: 'flare' }, { ms: 30_000, kind: 'scene' },
  ]), `markers ${JSON.stringify(m)} == raw song-time positions`);
}

console.log('TWO — both kinds, sorted by time regardless of input order');
{
  const plan = {
    uri: 'u', applies: true, reason: null, effective_mode: 'analysed', has_authored: false,
    scene_source: 'planned', show_clock_shift_ms: 0,
    scene_changes: [{ timestamp_ms: 30_000, intensity: 0.5 }, { timestamp_ms: 10_000, intensity: 0.5 }],
    flares: [{ timestamp_ms: 20_000, intensity: 0.3 }],
  };
  const m = songPositionMarkers(plan);
  ok(JSON.stringify(m) === JSON.stringify([
    { ms: 10_000, kind: 'scene' }, { ms: 20_000, kind: 'flare' }, { ms: 30_000, kind: 'scene' },
  ]), `markers ${JSON.stringify(m)}`);
}

console.log('THREE — nothing drawn when analysed events do not apply');
{
  const base = {
    uri: 'u', applies: false, reason: 'this song has your own triggers — analysed events are off for it',
    effective_mode: 'triggers_only', has_authored: true, scene_source: null,
    show_clock_shift_ms: 0, scene_changes: [], flares: [],
  };
  ok(songPositionMarkers(base).length === 0, 'applies=false (my triggers only) → no markers');
  ok(songPositionMarkers({ ...base, effective_mode: 'transitions', reason: 'transitions only — analysed events never fire' }).length === 0,
    'applies=false (transitions only) → no markers');
  ok(songPositionMarkers(null).length === 0, 'no plan → no markers');
  ok(songPositionMarkers(undefined).length === 0, 'undefined plan → no markers');
}

rmSync(tmp, { recursive: true, force: true });
if (failures) { console.log(`\n${failures} FAILED`); process.exit(1); }
console.log('\nALL CHECKS PASSED');
