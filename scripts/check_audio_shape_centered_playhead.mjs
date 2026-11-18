/** Executable spec: the audio shape graph's playhead is ALWAYS centred
 * horizontally (the Admiral, 2026-11-18, verbatim: "on the audio shape
 * graph on home (and others), the playhead is always centered. That might
 * just be a settings change").
 *
 * It was: in follow mode the window was [anchor + future − window, anchor +
 * future] (hooks/followWindow.ts's `followWindowFor`), which only centres
 * the playhead when `future === window / 2` — the shipped defaults (a 30 s
 * window, a 10 s future buffer) put it at 2/3 of the way across, not centre.
 * `centeredWindowFor` is the fix: [anchor − window/2, anchor + window/2],
 * always, with no `clampWin` at the song's edges (clamping there would
 * shove the window off-centre right when it matters) — this script checks
 * that it is centred at the very start and end of a song too, not only in
 * the middle, and that `useFollowWindow`'s own `centered` option wires it
 * in only where asked (Home's shared window / Now Playing), leaving the
 * Timeline builder's and the Debug page's own draggable look-ahead window
 * untouched.
 *
 * This script transpiles the REAL pure module with esbuild and drives it
 * with no DOM, the same convention `check_timeline_follow_playhead.mjs`
 * (which this centred mode sits beside) already uses.
 *
 * Run: node scripts/check_audio_shape_centered_playhead.mjs
 */
import { execFileSync } from 'node:child_process';
import { readFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const APPS = [
  { name: 'spectra/web', dir: 'spectra/web', base: 'spectra/web/src/timeline' },
  { name: 'web (spot-effects twin)', dir: 'web', base: 'web/src/builder' },
];

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const WINDOW_S = 30;
const DURATION_MS = 196056;

const out = mkdtempSync(path.join(tmpdir(), 'centeredwin-'));
for (const app of APPS) {
  const ts = path.join(REPO, app.base, 'hooks/followWindow.ts');
  const js = path.join(out, `${app.dir.replace('/', '_')}.mjs`);
  execFileSync('npx', ['esbuild', ts, '--format=esm', `--outfile=${js}`], {
    cwd: path.join(REPO, app.dir), stdio: ['ignore', 'ignore', 'inherit'],
  });
  const fe = await import(js);

  console.log(`\n§1 ${app.name}: CENTRED MID-SONG`);
  const anchor = 90000;
  const mid = fe.centeredWindowFor(anchor, WINDOW_S);
  ok(mid.endMs - anchor === anchor - mid.startMs,
    `equal look-behind and look-ahead around ${anchor} ms: [${mid.startMs}, ${mid.endMs}]`);
  ok(mid.endMs - mid.startMs === WINDOW_S * 1000, 'the full window size, not a clamped-down span');

  console.log(`\n§2 ${app.name}: CENTRED AT THE SONG'S START (no clamp-driven jump)`);
  const head = fe.centeredWindowFor(0, WINDOW_S);
  ok(head.startMs === -(WINDOW_S * 1000) / 2, `window starts before 0: ${head.startMs} ms — blank padding, not a shove-forward clamp`);
  ok(head.endMs - 0 === 0 - head.startMs, 'still centred exactly on the playhead at 0:00');

  console.log(`\n§3 ${app.name}: CENTRED AT THE SONG'S END`);
  const tail = fe.centeredWindowFor(DURATION_MS, WINDOW_S);
  ok(tail.endMs === DURATION_MS + (WINDOW_S * 1000) / 2, `window runs past the song's end: ${tail.endMs} ms — blank padding, not a shove-back clamp`);
  ok(DURATION_MS - tail.startMs === tail.endMs - DURATION_MS, 'still centred exactly on the playhead at the last moment');

  console.log(`\n§4 ${app.name}: THE RED CONTROL — the old anchor+future−window shape is NOT centred at the shipped defaults`);
  const old = fe.followWindowFor(anchor, WINDOW_S, 10, DURATION_MS);
  ok(old.endMs - anchor !== anchor - old.startMs,
    `the old formula leaves the playhead off-centre at the shipped 30s/10s defaults: [${old.startMs}, ${old.endMs}]`);
}

console.log('\n§5 THE TWO TIMELINE TWINS STAY BYTE-IDENTICAL on this hook');
for (const f of ['hooks/followWindow.ts', 'hooks/useFollowWindow.ts']) {
  const a = readFileSync(path.join(REPO, APPS[0].base, f), 'utf8');
  const b = readFileSync(path.join(REPO, APPS[1].base, f), 'utf8');
  ok(a === b, `${f} identical in both apps`);
}

console.log(failures ? `\n${failures} FAILED` : '\nALL OK');
process.exit(failures ? 1 : 0);
