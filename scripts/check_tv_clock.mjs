/**
 * Executable spec for the TV app's clock math (spectra/web/src/tv/
 * clock.ts, data/tv-display-plan/plan.html PR 1.2) — pure, no DOM, no
 * network. Bundles the real module with esbuild and drives it with
 * synthetic timestamps.
 *
 * Proves:
 *   ONE   — the NTP offset formula recovers a known clock skew on a
 *           symmetric loopback round trip.
 *   TWO   — "keep the fastest of the last 8" (the plan's own §5.1 rule):
 *           a slow, noisy sample never wins over a fast, clean one, and
 *           the 9th sample evicts the 1st.
 *   THREE — interpolateShowClockMs advances only while playing, and
 *           passes a null show clock through untouched.
 *   FOUR  — build.ts's shouldReload() (the server's `config.build_id`
 *           half of "build-id reload") only fires on a genuine mismatch,
 *           never on "the server hasn't said yet".
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'spectra/web/src/tv/clock.ts');
const BUILD_TS = path.join(REPO, 'spectra/web/src/tv/build.ts');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const tmp = mkdtempSync(path.join(tmpdir(), 'tv-clock-'));
const js = path.join(tmp, 'clock.mjs');
execFileSync('npx', ['esbuild', TS, '--bundle', '--format=esm', '--platform=node',
  '--log-level=error', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const { NtpClock, interpolateShowClockMs } = await import(js);

const buildJs = path.join(tmp, 'build.mjs');
execFileSync('npx', ['esbuild', BUILD_TS, '--bundle', '--format=esm', '--platform=node',
  '--log-level=error', '--define:__TV_BUILD_ID__="this-build"', `--outfile=${buildJs}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const { shouldReload, TV_BUILD_ID } = await import(buildJs);

console.log('ONE — the NTP offset formula recovers a known clock skew');
{
  // Server clock is 500ms AHEAD of the client's. Symmetric 20ms network
  // each way, with a deliberate 300ms server-side processing gap.
  const SKEW_MS = 500;
  const clockClient = new NtpClock();
  const clientSend = 1_000_000;
  const serverRecv = clientSend + SKEW_MS + 20;
  const serverSend = serverRecv + 300; // the "stall"
  const clientRecv = clientSend + 20 + 300 + 20;
  clockClient.record(clientSend, serverRecv, serverSend, clientRecv);
  const offset = clockClient.offsetMs();
  ok(offset !== null && Math.abs(offset - SKEW_MS) < 1,
    `offset ~= ${SKEW_MS}ms despite a 300ms stall (got ${offset})`);
}

console.log('TWO — keep the fastest of the last 8');
{
  const clock = new NtpClock();
  // A slow, badly-skewed-looking sample first (large RTT).
  clock.record(0, 1000, 1500, 2000); // rtt=(2000-0)-(1500-1000)=1500
  ok(Math.abs((clock.offsetMs() ?? 0) - 250) < 1, 'first (only) sample used');

  // A fast, clean sample (rtt=90ms, offset=15ms) — must win even though
  // it arrives second, over the first sample's rtt=1500ms/offset=250ms.
  clock.record(10000, 10060, 10070, 10100);
  const fastOffset = clock.offsetMs();
  ok(Math.abs((fastOffset ?? -1) - 15) < 1, `the fast sample's offset wins (got ${fastOffset})`);
  ok((clock.bestRttMs() ?? -1) < 200, 'bestRttMs reports the fast sample\'s rtt');

  // Push 7 more slow samples (9 total) — the original slow 1500ms-rtt
  // sample must have been evicted (maxlen 8), but the fast one survives
  // since it is never the oldest AND never the worst.
  for (let i = 0; i < 7; i++) clock.record(0, 1000, 1500, 2000);
  ok(clock.sampleCount() === 8, `sample count capped at 8 (got ${clock.sampleCount()})`);
  ok(Math.abs((clock.offsetMs() ?? -1) - 15) < 1,
    'the fast sample still wins after the buffer wraps past it');
}

console.log('THREE — interpolateShowClockMs');
{
  const anchor = { showClockMs: 5000, serverMsAtReceipt: 100000, isPlaying: true };
  ok(interpolateShowClockMs(anchor, 100000) === 5000, 'no drift at the anchor instant');
  ok(interpolateShowClockMs(anchor, 100750) === 5750, 'advances 1:1 with server time while playing');

  const paused = { ...anchor, isPlaying: false };
  ok(interpolateShowClockMs(paused, 101000) === 5000, 'frozen while not playing');

  const unknown = { showClockMs: null, serverMsAtReceipt: 100000, isPlaying: true };
  ok(interpolateShowClockMs(unknown, 101000) === null, 'a null show clock passes through untouched');
}

console.log('FOUR — shouldReload');
{
  ok(TV_BUILD_ID === 'this-build', `TV_BUILD_ID reflects the --define (got ${TV_BUILD_ID})`);
  ok(shouldReload('this-build') === false, 'the same build id never triggers a reload');
  ok(shouldReload('a-newer-build') === true, 'a differing build id triggers a reload');
  ok(shouldReload(null) === false, 'the server not having said yet is not a mismatch');
  ok(shouldReload(undefined) === false, 'undefined is treated the same as not having said yet');
  ok(shouldReload('') === false, 'an empty string is not a real build id either');
}

rmSync(tmp, { recursive: true, force: true });

if (failures > 0) {
  console.error(`\n${failures} check(s) failed`);
  process.exit(1);
}
console.log('\nall checks passed');
