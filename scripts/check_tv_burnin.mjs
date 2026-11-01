/**
 * Executable spec for burn-in safety (spectra/web/src/tv/burnIn.ts,
 * data/tv-display-plan/plan.html PR 1.5, §2.4: "the whole layout drifts
 * up to +-16px over 8 minutes; the QR swaps corners every 10 minutes...
 * nothing static for hours"). No DOM, no browser — pure functions of
 * elapsed time, sampled over simulated time.
 *
 * Proves:
 *   ONE   — the drift offset is never constant across any real 10-minute
 *           (600,000ms) window, sampled at a cadence finer than a single
 *           rendered frame would ever hold still for.
 *   TWO   — the QR corner changes within any 10-minute window (its own
 *           swap period is exactly 10 minutes, so a window starting
 *           anywhere still crosses at least one swap boundary — checked
 *           directly, not assumed).
 *   THREE — the Attract card (join/top/now) cycles many times within any
 *           10-minute window (15s cadence).
 *   FOUR  — the drift amplitude/period and QR swap period match the
 *           plan's own stated numbers (16px, 8 min, 10 min) — a constant
 *           drifting out of sync with this spec would still "pass" ONE
 *           above at some other amplitude, so the exact values are
 *           checked too.
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'spectra/web/src/tv/burnIn.ts');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const tmp = mkdtempSync(path.join(tmpdir(), 'tv-burnin-'));
const js = path.join(tmp, 'burnIn.mjs');
execFileSync('npx', ['esbuild', TS, '--bundle', '--format=esm', '--platform=node',
  '--log-level=error', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const {
  driftOffsetPx, qrCorner, attractCard,
  DRIFT_PERIOD_MS, DRIFT_AMPLITUDE_PX, QR_SWAP_PERIOD_MS,
  ATTRACT_CARD_MS, ATTRACT_CARDS,
} = await import(js);

const TEN_MIN_MS = 10 * 60 * 1000;
// The acceptance bar is "no element static for MORE than 10 minutes" — a
// window of exactly 10 minutes, aligned exactly to a swap/period boundary,
// can legitimately show zero change (it changes once, right at the start,
// then holds for precisely the window's own length). So every window
// checked here is 10 minutes PLUS ONE STEP: a window that length can never
// align perfectly with a period that divides 10 minutes evenly.
const SAMPLE_STEP_MS = 1000; // finer than any real rendered frame would hold still for
const WINDOW_MS = TEN_MIN_MS + SAMPLE_STEP_MS;

console.log('ONE — drift offset is never constant for more than 10 minutes');
{
  // Sample several windows starting at different phases, including ones
  // not aligned to the drift's own period, so this can't pass by accident
  // of picking a window that happens to start at a peak/trough.
  const starts = [0, 12_345, 4 * 60 * 1000 + 7_000, DRIFT_PERIOD_MS - 1, 37 * 60 * 1000];
  for (const start of starts) {
    const dxs = new Set();
    const dys = new Set();
    for (let t = start; t < start + WINDOW_MS; t += SAMPLE_STEP_MS) {
      const { dx, dy } = driftOffsetPx(t);
      dxs.add(Math.round(dx * 100));
      dys.add(Math.round(dy * 100));
    }
    ok(dxs.size > 1, `dx varies over a 10-minute window starting at ${start}ms (saw ${dxs.size} distinct values)`);
    ok(dys.size > 1, `dy varies over a 10-minute window starting at ${start}ms (saw ${dys.size} distinct values)`);
  }
  // And the x/y phases genuinely differ (offset by a third of the period) —
  // a diagonal-only drift would still read as "one position" along the
  // other axis at some instant within the window. dy(t) is defined as
  // dx(t + period/3), so dy at 0 should equal dx at period/3.
  const atZero = driftOffsetPx(0);
  const atThird = driftOffsetPx(DRIFT_PERIOD_MS / 3);
  ok(Math.abs(atZero.dy - atThird.dx) < 0.5, 'dy(0) equals dx(period/3), as documented (y leads x by a third of the period)');
}

console.log('TWO — the QR corner changes within any stretch longer than 10 minutes');
{
  const starts = [0, 1, 299_999, 300_000, 599_999, 600_000, 12 * 60 * 1000 + 3_333];
  for (const start of starts) {
    const corners = new Set();
    for (let t = start; t < start + WINDOW_MS; t += SAMPLE_STEP_MS) {
      corners.add(qrCorner(t));
    }
    ok(corners.size >= 2, `the QR corner changes within [${start}, ${start + WINDOW_MS})ms (saw ${corners.size} distinct corners)`);
  }
  ok(QR_SWAP_PERIOD_MS === TEN_MIN_MS, 'the swap period equals the acceptance window, so the corner never holds for MORE than 10 minutes');
}

console.log('THREE — the Attract card cycles many times within a 10-minute window');
{
  const cards = new Set();
  for (let t = 0; t < TEN_MIN_MS; t += SAMPLE_STEP_MS) cards.add(attractCard(t));
  ok(cards.size === ATTRACT_CARDS.length, `all ${ATTRACT_CARDS.length} cards are reached within 10 minutes`);
  const expectedRotations = Math.floor(TEN_MIN_MS / ATTRACT_CARD_MS / ATTRACT_CARDS.length);
  ok(expectedRotations >= 10, `the deck completes at least 10 full rotations in 10 minutes (computed ${expectedRotations})`);
}

console.log('FOUR — the plan\'s own stated numbers');
{
  ok(DRIFT_PERIOD_MS === 8 * 60 * 1000, 'drift period is 8 minutes, per §2.4');
  ok(DRIFT_AMPLITUDE_PX === 16, 'drift amplitude is +-16px, per §2.4');
  ok(QR_SWAP_PERIOD_MS === 10 * 60 * 1000, 'QR swap period is 10 minutes, per §2.4');
  ok(DRIFT_PERIOD_MS < TEN_MIN_MS, 'the drift period is strictly shorter than the acceptance window — the structural reason ONE always passes');
  // At a full drift period the offset returns to (approximately) where it
  // started — proving the amplitude is actually bounded, not a runaway.
  const start = driftOffsetPx(0);
  const afterOnePeriod = driftOffsetPx(DRIFT_PERIOD_MS);
  ok(Math.abs(start.dx - afterOnePeriod.dx) < 0.01, 'the drift is periodic (dx repeats after one full period)');
  ok(Math.abs(start.dy - afterOnePeriod.dy) < 0.01, 'the drift is periodic (dy repeats after one full period)');
  let maxAbs = 0;
  for (let t = 0; t < DRIFT_PERIOD_MS; t += SAMPLE_STEP_MS) {
    const { dx, dy } = driftOffsetPx(t);
    maxAbs = Math.max(maxAbs, Math.abs(dx), Math.abs(dy));
  }
  ok(maxAbs <= DRIFT_AMPLITUDE_PX + 0.01, `drift never exceeds the stated +-${DRIFT_AMPLITUDE_PX}px amplitude (max |offset| seen: ${maxAbs.toFixed(2)}px)`);
}

rmSync(tmp, { recursive: true, force: true });

if (failures > 0) {
  console.error(`\n${failures} check(s) failed`);
  process.exit(1);
}
console.log('\nall checks passed');
