/**
 * Executable spec for the Light Show's High/Low flags on the Timeline
 * (spectra/web/src/lightshow/cueFlags.ts). Transpiles the REAL module with
 * esbuild, zero network.
 *
 *   ONE   — one flag per level, automatic / drop-seeded / moved told apart,
 *           and the automatic position kept for the "auto" ghost.
 *   TWO   — a drag snaps to 20 ms and never leaves the song.
 *   THREE — a drag snaps to the nearest beat within its pixel radius
 *           first, falling back to the 20 ms grid (2026-10-08, the
 *           Admiral: "snap-to-beat as the mouse has").
 *   FOUR  — rawMsAt is unsnapped (the "no jump" grab-offset arithmetic).
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'spectra/web/src/lightshow/cueFlags.ts');
let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};
const tmp = mkdtempSync(path.join(tmpdir(), 'cueflags-'));
const js = path.join(tmp, 'cueFlags.mjs');
execFileSync('npx', ['esbuild', TS, '--format=esm', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const { cueFlags, dragMs, rawMsAt, snapCueMs } = await import(js);

console.log('ONE — the flags');
const cue = (level, extra) => ({ level, timestamp_ms: 60_000, source: 'auto', shift: 0.3,
  auto_ms: 60_000, auto_shift: 0.3, drop_mark_ms: null, runner_up_close: false,
  alternates: [{ timestamp_ms: 90_000, shift: 0.28, close: true }], moved_ms: null, ...extra });
ok(cueFlags(null).length === 0, 'no cues, no flags');
const f = cueFlags({ uri: 'x', reason: null, duration_ms: 200_000, high: cue('high'), low: cue('low', { shift: -0.4 }) });
ok(f.length === 2 && f[0].level === 'high' && f[1].level === 'low', 'one High and one Low');
ok(f[0].title.includes('biggest rise') && f[1].title.includes('biggest fall'), f[1].title);
ok(f[0].alternates[0].close === true, 'a close runner-up is offered');
const moved = cueFlags({ high: cue('high', { source: 'moved', timestamp_ms: 70_000, moved_ms: 70_000 }) })[0];
ok(moved.moved && moved.ms === 70_000 && moved.autoMs === 60_000, 'a moved flag keeps its automatic ghost');
ok(cueFlags({ high: cue('high', { source: 'drop_mark' }) })[0].title.includes('drop mark'), 'drop-seeded says so');

console.log('TWO — a drag');
const rect = { left: 100, width: 1000 };
ok(dragMs(600, rect, 200_000) === 100_000, 'middle of the bar is the middle of the song');
ok(dragMs(50, rect, 200_000) === 0 && dragMs(5000, rect, 200_000) === 200_000, 'clamped to the song');
ok(dragMs(601, rect, 200_000) % 20 === 0, 'snapped to 20 ms');

console.log('THREE — beat snap');
const beats = [{ ms: 100_050 }, { ms: 100_550 }]; // ~500ms apart
// width 1000px over 200_000ms span = 200ms/px; BEAT_SNAP_PX=10 -> 2000ms
// radius at THIS bar's zoomed-all-the-way-out scale (a full-song bar, not
// the zoomed canvas window — the same formula canvas/data.ts's
// snapTimestamp uses, just at a very different span/width ratio).
ok(snapCueMs(100_070, 200_000, 1000, beats) === 100_050,
  'within the pixel-radius-converted-to-ms snaps to the nearest beat');
ok(snapCueMs(100_070, 200_000, 1000) === 100_080,
  'with no beats given, falls back to the flat 20ms grid (unchanged)');
ok(snapCueMs(150_011, 200_000, 1000, beats) === 150_020,
  'far outside the radius: falls back to the grid, never a wrong beat');
ok(snapCueMs(-500, 200_000, 1000, beats) >= 0 && snapCueMs(500_000, 200_000, 1000, beats) <= 200_000,
  'still clamped to the song either way');

console.log('FOUR — rawMsAt is unsnapped (the no-jump grab-offset arithmetic)');
ok(rawMsAt(601, rect, 200_000) === 100_200, 'not rounded to any grid');
ok(rawMsAt(50, rect, 200_000) === 0 && rawMsAt(5000, rect, 200_000) === 200_000,
  'still clamped to the song');
{
  // The actual "no jump" property: grab 30ms off-centre from a flag at
  // 100_000, drag the pointer by +200ms worth of pixels, and the flag's
  // new position must be ITS OWN old position plus that same +200ms —
  // never the pointer's raw position (which would read as 100_000 + 30 +
  // 200 = different only by construction here, but a snap-sensitive case
  // like this one is exactly where a jump used to show up).
  const flagMs = 100_000;
  const grabX = 620; // rawMsAt(620, rect, 200_000) = 104_000, i.e. +4000ms off
  const grabMs = flagMs - rawMsAt(grabX, rect, 200_000);
  const moveX = grabX + 40; // +40px = +8000ms at this scale
  const tracked = rawMsAt(moveX, rect, 200_000) + grabMs;
  ok(Math.round(tracked) === flagMs + 8000,
    'the flag tracks the finger by the drag delta, not the finger\'s raw position');
}

if (failures) { console.log(`\n${failures} FAILED`); process.exit(1); }
console.log('\nall passed');
