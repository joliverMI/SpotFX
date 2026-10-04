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
 *   FOUR  — RANK (2026-10-04): rank/rank_of reach each marker; size by
 *           rank third, opacity by rank, an unranked marker drawn as before,
 *           and the hover text.
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
const {
  plannedMarkerMs, plannedMarkers, rankTier, rankOpacity, markerTooltip,
  SCENE_TAB_HALF_WIDTH, FLARE_DOT_RADIUS,
} = await import(js);

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
const unranked = { rank: null, rankOf: null };
ok(JSON.stringify(m) === JSON.stringify([
  { ms: 9_900, kind: 'scene', ...unranked }, { ms: 19_900, kind: 'flare', ...unranked },
  { ms: 29_900, kind: 'scene', ...unranked },
]), `markers ${JSON.stringify(m)}`);

console.log('THREE — nothing drawn when analysed events do not apply');
ok(plannedMarkers({ ...plan, applies: false }, 0, 0).length === 0, 'applies=false → no markers');
ok(plannedMarkers(null, 0, 0).length === 0, 'no plan → no markers');

console.log('FOUR — rank: carried onto the marker, drawn by thirds and brightness, named on hover');
const ranked = plannedMarkers({
  ...plan,
  scene_changes: [{ timestamp_ms: 30_000, intensity: 0.5, rank: 2, rank_of: 21 }],
  flares: [{ timestamp_ms: 20_000, intensity: 0.3, rank: 21, rank_of: 21 }],
}, 0, 0);
ok(ranked[1].rank === 2 && ranked[1].rankOf === 21 && ranked[0].rank === 21,
  'rank and rank_of travel from the API onto each marker');
ok(rankTier(1, 21) === 2 && rankTier(7, 21) === 2 && rankTier(8, 21) === 1
  && rankTier(15, 21) === 0 && rankTier(21, 21) === 0,
  'top / middle / bottom third of 21 → tiers 2 / 1 / 0');
ok(rankTier(null, 21) === null && rankTier(3, null) === null, 'no rank → no tier (original size)');
ok(SCENE_TAB_HALF_WIDTH[0] * 2 === 6 && SCENE_TAB_HALF_WIDTH[1] * 2 === 10 && SCENE_TAB_HALF_WIDTH[2] * 2 === 14,
  'scene tab 6 / 10 / 14 px by third (the middle third keeps today\'s 10 px)');
ok(FLARE_DOT_RADIUS[0] === 2.5 && FLARE_DOT_RADIUS[1] === 3.5 && FLARE_DOT_RADIUS[2] === 4.5,
  'flare dot 2.5 / 3.5 / 4.5 px by third');
ok(Math.abs(rankOpacity(1, 21, 0.9) - 0.95) < 1e-9 && Math.abs(rankOpacity(21, 21, 0.9) - 0.45) < 1e-9
  && rankOpacity(11, 21, 0.9) > 0.45 && rankOpacity(11, 21, 0.9) < 0.95,
  'opacity 0.95 for the strongest → 0.45 for the weakest, linear between');
ok(rankOpacity(null, null, 0.9) === 0.9 && rankOpacity(1, 1, 0.9) === 0.95,
  'unranked keeps the original opacity; a lone moment is the strongest');
ok(markerTooltip(ranked[1]) === '#2 of 21 · section-energy change · scene change'
  && markerTooltip(ranked[0]) === '#21 of 21 · section-energy change · flare',
  `tooltip names it: "${markerTooltip(ranked[1])}"`);
ok(markerTooltip({ ms: 0, kind: 'scene', rank: null, rankOf: null }).includes('not ranked'),
  'an unranked marker says so rather than inventing a rank');

rmSync(tmp, { recursive: true, force: true });
if (failures) { console.log(`\n${failures} FAILED`); process.exit(1); }
console.log('\nALL CHECKS PASSED');
