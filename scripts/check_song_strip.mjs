/**
 * Executable spec for the global song timeline's pure helpers
 * (spectra/web/src/components/songStrip.ts — song-layout-plan,
 * data/ui-layout-plan/report.md §4). Bundles the REAL module with esbuild
 * (it pulls runtime values from debug/plannedEvents.ts and
 * timeline/dropSequences.ts, so --bundle is required, unlike a pure
 * type-only import) and drives it with no DOM.
 *
 * Proves:
 *   ONE   — countdown formatting: "s" under a minute, "m:ss.s" over it.
 *   TWO   — eventLabel matches the report's own examples verbatim.
 *   THREE — pickNext finds the soonest event strictly ahead of now, and
 *           returns null once nothing is left.
 *   FOUR  — rank-based marker sizing/opacity delegates to the SAME
 *           debug/plannedEvents.ts functions the Timeline/debug canvases
 *           already use — never a second idea of "strong".
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'spectra/web/src/components/songStrip.ts');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const tmp = mkdtempSync(path.join(tmpdir(), 'song-strip-'));
const js = path.join(tmp, 'songStrip.mjs');
execFileSync('npx', ['esbuild', TS, '--bundle', '--format=esm', '--platform=node',
  '--log-level=error', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const mod = await import(js);
const { fmtCountdown, fmtMMSS, eventLabel, pickNext, markerSizePx, markerOpacity,
       xFraction, FINAL_STRETCH_MS, NEXT_EVENT_BOX_WIDTH } = mod;

console.log('ONE — countdown formatting');
{
  ok(fmtCountdown(12400) === '12.4s', `12400ms -> "12.4s" (got ${fmtCountdown(12400)})`);
  ok(fmtCountdown(64200) === '1:04.2', `64200ms -> "1:04.2" (got ${fmtCountdown(64200)})`);
  ok(fmtCountdown(-500) === '0.0s', 'never negative');
  ok(fmtMMSS(189258) === '3:09', `189258ms duration -> "3:09" (got ${fmtMMSS(189258)})`);
}

console.log('TWO — eventLabel matches the report\'s own examples');
{
  ok(eventLabel({ kind: 'scene', rank: 7, rank_of: 15 }) === 'Scene · 7 of 15',
    `got ${eventLabel({ kind: 'scene', rank: 7, rank_of: 15 })}`);
  ok(eventLabel({ kind: 'flare', rank: null, rank_of: null }) === 'Flare');
  ok(eventLabel({ kind: 'charge', num: 1 }) === 'Charge · drop 1');
  ok(eventLabel({ kind: 'drop', num: 1 }) === 'Drop 1');
  ok(eventLabel({ kind: 'high' }) === 'High trigger');
}

console.log('THREE — pickNext / FINAL_STRETCH_MS / box width');
{
  const events = [
    { ms: 1000, kind: 'scene', rank: null, rank_of: null, source: 'x' },
    { ms: 5000, kind: 'flare', rank: null, rank_of: null, source: 'x' },
  ];
  ok(pickNext(events, 0).ms === 1000, 'the soonest event ahead of now');
  ok(pickNext(events, 1000).ms === 5000, 'strictly ahead — the passed one is excluded');
  ok(pickNext(events, 5000) === null, 'nothing left once the last event has passed');
  ok(pickNext([], 0) === null, 'empty list -> null, never a crash');
  ok(FINAL_STRETCH_MS === 3000, 'the glow/fill window is 3 seconds (report §4)');
  ok(NEXT_EVENT_BOX_WIDTH === 96, 'the next-event box is a fixed 96px (decision)');
}

console.log('FOUR — rank sizing/opacity reuse debug/plannedEvents.ts verbatim');
{
  ok(markerSizePx('scene', 1, 3) > markerSizePx('scene', 3, 3),
    'the strongest-ranked scene tab is the widest');
  ok(markerOpacity(1, 3) > markerOpacity(3, 3),
    'the strongest-ranked event is the most opaque');
  ok(markerOpacity(null, null) === 0.7, 'an unranked event gets the neutral 0.7 fallback');
  ok(xFraction(0, 100000) === 0 && xFraction(100000, 100000) === 1
     && xFraction(200000, 100000) === 1,
     'xFraction clamps to [0, 1]');
}

rmSync(tmp, { recursive: true, force: true });
console.log(failures === 0 ? '\nALL OK' : `\n${failures} FAILURE(S)`);
process.exit(failures === 0 ? 0 : 1);
