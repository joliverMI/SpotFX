/**
 * Executable spec for the Party screen's pure logic (spectra/web/src/tv/
 * partyLogic.ts, data/tv-display-plan/plan.html PR 1.4) — no DOM, no
 * network.
 *
 * Proves:
 *   ONE   — progress interpolation advances only while playing, and is
 *           clamped at the song's own length.
 *   TWO   — the up-next callout's 30s-before-the-end rule, and that it
 *           never fires with no next song (even inside the window).
 *   THREE — fmtMMSS/progressFraction/byWords match the plan's own
 *           mockup wording and arithmetic.
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'spectra/web/src/tv/partyLogic.ts');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const tmp = mkdtempSync(path.join(tmpdir(), 'tv-party-'));
const js = path.join(tmp, 'partyLogic.mjs');
execFileSync('npx', ['esbuild', TS, '--bundle', '--format=esm', '--platform=node',
  '--log-level=error', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const { interpolatedProgressMs, remainingMs, showCallout, fmtMMSS, progressFraction,
       byWords } = await import(js);

const NOW = { uri: 'spotify:track:x', title: 'Dancing Queen', artist: 'ABBA',
             image: '', thumb: '', open_url: '', by: { kind: 'guest', name: 'Ana' },
             up: 3, down: 0, duration_ms: 231000, progress_ms: 127000, is_playing: true };

console.log('ONE — progress interpolation');
{
  ok(interpolatedProgressMs(NOW, 100000, 100000) === 127000, 'no drift at the receipt instant');
  ok(interpolatedProgressMs(NOW, 100000, 101500) === 128500, 'advances 1:1 with client time while playing');
  const paused = { ...NOW, is_playing: false };
  ok(interpolatedProgressMs(paused, 100000, 105000) === 127000, 'frozen while not playing');
  ok(interpolatedProgressMs(NOW, null, 999999999) === 127000, 'no receipt timestamp yet: use the raw snapshot');
  const nearEnd = { ...NOW, progress_ms: 230000 };
  ok(interpolatedProgressMs(nearEnd, 100000, 999999999) === NOW.duration_ms,
    'clamped at the song\'s own length, never past it');
}

console.log('TWO — the up-next callout');
{
  const next = [{ uri: 'y', title: 'Mr. Brightside', artist: '', image: '', thumb: '',
                  by: { kind: 'guest', name: 'Sunny Fox' }, starts_in_ms: 5000 }];
  ok(showCallout(NOW, next, 201000) === true, 'inside the last 30s with a known next song');
  ok(showCallout(NOW, next, 150000) === false, 'too early in the song');
  ok(showCallout(NOW, [], 225000) === false, 'never fires with no next song, even inside the window');
  ok(showCallout(null, next, 0) === false, 'never fires with nothing playing');
  ok(remainingMs(NOW, 231000) === 0, 'remaining never goes negative');
}

console.log('THREE — formatting, matching the plan\'s own mockup');
{
  ok(fmtMMSS(127000) === '2:07', `127000ms -> "2:07" (got ${fmtMMSS(127000)})`);
  ok(fmtMMSS(231000) === '3:51', `231000ms -> "3:51" (got ${fmtMMSS(231000)})`);
  ok(fmtMMSS(8000) === '0:08', 'single-digit seconds are zero-padded');
  ok(Math.abs(progressFraction(NOW, 115500) - 0.5) < 0.001, 'progressFraction is linear 0..1');
  ok(progressFraction({ ...NOW, duration_ms: 0 }, 1000) === 0, 'a zero-length song never divides by zero');
  ok(byWords({ kind: 'set', name: '' }) === "the host's set", 'set songs');
  ok(byWords({ kind: 'host', name: '' }) === 'added by the host', 'the host\'s own adds');
  ok(byWords({ kind: 'guest', name: 'Sunny Fox' }) === 'added by Sunny Fox', 'a guest, by name');
}

rmSync(tmp, { recursive: true, force: true });

if (failures > 0) {
  console.error(`\n${failures} check(s) failed`);
  process.exit(1);
}
console.log('\nall checks passed');
