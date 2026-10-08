/** Executable spec: single-finger touch panning on the Timeline's audio-
 * shape canvas (the Admiral, 2026-10-08: "i want to be able to drag the
 * audio shape graph somehow on a tablet or phone... single finger if it
 * would work well").
 *
 * Transpiles the REAL pure module (canvas/touchPan.ts) with esbuild and
 * drives its direction-lock/delta arithmetic directly — the
 * followWindow.ts precedent. The DOM wiring that calls it
 * (canvas/TimelineCanvas.tsx's down()/move()) is covered by manual
 * chrome-devtools-axi touch emulation (see the PR notes), since it needs
 * a real pointer-event sequence over a live canvas; this script is the
 * part that can run with no browser.
 *
 * Run: node scripts/check_timeline_touch_pan.mjs
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

const out = mkdtempSync(path.join(tmpdir(), 'touchpan-'));
for (const app of APPS) {
  const ts = path.join(REPO, app.base, 'canvas/touchPan.ts');
  const js = path.join(out, `${app.dir.replace('/', '_')}.mjs`);
  execFileSync('npx', ['esbuild', ts, '--format=esm', `--outfile=${js}`], {
    cwd: path.join(REPO, app.dir), stdio: ['ignore', 'ignore', 'inherit'],
  });
  const fe = await import(js);

  console.log(`\n§1 ${app.name}: UNDECIDED UNTIL THE LOCK THRESHOLD`);
  ok(fe.resolveTouchPanLock(0, 0) === null, 'no movement yet: undecided');
  ok(fe.resolveTouchPanLock(2, 1) === null, 'under the lock threshold either way: still undecided');
  ok(fe.resolveTouchPanLock(fe.TOUCH_PAN_LOCK_PX - 1, 0) === null,
    'one px short of the threshold: still undecided (never locks early)');

  console.log(`\n§2 ${app.name}: HORIZONTAL DOMINANT -> PAN`);
  ok(fe.resolveTouchPanLock(10, 2) === 'pan', 'mostly-horizontal drag resolves to pan');
  ok(fe.resolveTouchPanLock(-10, -2) === 'pan', 'pan resolves in either horizontal direction');
  ok(fe.resolveTouchPanLock(8, 8) === 'pan', 'a tie resolves to pan, never silently to scroll');

  console.log(`\n§3 ${app.name}: VERTICAL DOMINANT -> LEFT TO THE PAGE`);
  ok(fe.resolveTouchPanLock(2, 10) === 'vertical', 'mostly-vertical drag resolves to vertical (page scroll)');
  ok(fe.resolveTouchPanLock(-2, -10) === 'vertical', 'vertical resolves either direction too');

  console.log(`\n§4 ${app.name}: THE PAN DELTA MATCHES THE EXISTING MIDDLE-MOUSE FORMULA`);
  // drag right -> window moves right (the "reversed per user preference"
  // comment in TimelineCanvas.tsx) — same sign, same magnitude, whichever
  // input device drove it.
  const winStart = 60000, winEnd = 80000; // a 20s window
  const canvasW = 1000;
  ok(fe.panDeltaMs(600, 500, canvasW, winStart, winEnd) === 2000,
    'a 100px drag right over a 1000px/20000ms window is a +2000ms delta');
  ok(fe.panDeltaMs(400, 500, canvasW, winStart, winEnd) === -2000,
    'a drag left is the exact negative');
  ok(fe.panDeltaMs(500, 500, canvasW, winStart, winEnd) === 0, 'no movement, no delta');
}

console.log('\n§5 THE TWO TIMELINE TWINS STAY BYTE-IDENTICAL on this module');
for (const f of ['canvas/touchPan.ts']) {
  const a = readFileSync(path.join(REPO, APPS[0].base, f), 'utf8');
  const b = readFileSync(path.join(REPO, APPS[1].base, f), 'utf8');
  ok(a === b, `${f} identical in both apps`);
}

console.log(failures ? `\n${failures} FAILED` : '\nALL OK');
process.exit(failures ? 1 : 0);
