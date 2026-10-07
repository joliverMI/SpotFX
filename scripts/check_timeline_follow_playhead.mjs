/** Executable spec: the Timeline's follow window keeps the DRAWN playhead in
 * view (the Admiral, 2026-10-07, on Pop Off: "the playhead appears to be
 * ahead of the scrolling view on the timeline").
 *
 * The playhead layer draws at the audible clock PLUS the song's stored shape
 * offset; the follow window used to anchor on the RAW progress clock. Pop
 * Off's offset is 14,450 ms against a 10 s future buffer, so the line was
 * drawn past the window's right edge for the whole song. This script
 * transpiles the REAL pure module (hooks/followWindow.ts — the arithmetic
 * the hook and the layer both call) with esbuild and drives it with his real
 * numbers, carries the pre-fix anchoring alongside as its own red control,
 * and asserts at the source level that both Timeline twins hand the hook
 * their drawn-playhead getter and that both playhead layers draw through
 * the same function — so the anchor and the line cannot drift apart again.
 *
 * Run: node scripts/check_timeline_follow_playhead.mjs
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

// Pop Off, read off his real storage on 2026-10-07 (audio_shapes sidecar
// timestamp_offset_ms; settings.json audio_latency_ms / builder_*).
const POP_OFF_OFFSET_MS = 14450;
const DOPAMINE_OFFSET_MS = -453;   // the song that looked right that evening
const AUDIO_LATENCY_MS = 150;
const WINDOW_S = 20;
const FUTURE_S = 10;
const DURATION_MS = 196056;
const RAW_NOW_MS = 60000;

const out = mkdtempSync(path.join(tmpdir(), 'followwin-'));
for (const app of APPS) {
  const ts = path.join(REPO, app.base, 'hooks/followWindow.ts');
  const js = path.join(out, `${app.dir.replace('/', '_')}.mjs`);
  execFileSync('npx', ['esbuild', ts, '--format=esm', `--outfile=${js}`], {
    cwd: path.join(REPO, app.dir), stdio: ['ignore', 'ignore', 'inherit'],
  });
  const fe = await import(js);
  const inWin = (ms, w) => ms >= w.startMs && ms <= w.endMs;

  console.log(`\n§1 ${app.name}: THE WINDOW CONTAINS THE DRAWN PLAYHEAD (Pop Off's numbers)`);
  const canvasNow = RAW_NOW_MS - AUDIO_LATENCY_MS;
  const drawn = fe.drawnPlayheadMs(canvasNow, POP_OFF_OFFSET_MS);
  ok(drawn === canvasNow + POP_OFF_OFFSET_MS, `playhead draws at audible clock + shape offset = ${drawn} ms`);
  const fixed = fe.followWindowFor(drawn, WINDOW_S, FUTURE_S, DURATION_MS);
  ok(inWin(drawn, fixed), `anchored on the drawn playhead: window [${fixed.startMs}, ${fixed.endMs}] holds it`);
  ok(fixed.endMs - drawn === FUTURE_S * 1000, `the playhead sits exactly the ${FUTURE_S} s look-ahead from the right edge`);

  console.log(`\n§2 ${app.name}: THE RED CONTROL — the pre-fix anchoring on the raw clock`);
  const old = fe.followWindowFor(RAW_NOW_MS, WINDOW_S, FUTURE_S, DURATION_MS);
  ok(!inWin(drawn, old), `anchored on the raw clock: window [${old.startMs}, ${old.endMs}] leaves the playhead ${drawn - old.endMs} ms past the right edge`);
  const drawnDop = fe.drawnPlayheadMs(canvasNow, DOPAMINE_OFFSET_MS);
  ok(inWin(drawnDop, old), `Dopamine (offset ${DOPAMINE_OFFSET_MS} ms) looked right on the old anchor — song-specific, not constant`);
  const span = fixed.endMs - fixed.startMs;
  ok(span === WINDOW_S * 1000 && old.endMs - old.startMs === span, 'same window size either way: only the anchor moved');

  console.log(`\n§3 ${app.name}: THE SONG'S EDGES STILL CLAMP`);
  const tail = fe.followWindowFor(DURATION_MS - 1000, WINDOW_S, FUTURE_S, DURATION_MS);
  ok(tail.endMs === DURATION_MS && tail.startMs === DURATION_MS - WINDOW_S * 1000, 'a playhead near the end pins the window to the song end');
  const head = fe.followWindowFor(0, WINDOW_S, FUTURE_S, DURATION_MS);
  ok(head.startMs === 0 && head.endMs === WINDOW_S * 1000, 'a playhead at the start pins the window to 0');

  console.log(`\n§4 ${app.name}: THE WIRING — one function on both sides`);
  const page = readFileSync(path.join(REPO, app.base, 'BuilderPage.tsx'), 'utf8');
  const hookCall = page.match(/useFollowWindow\(\{\s*getNowMs:\s*([A-Za-z]+)/);
  ok(hookCall && hookCall[1] === 'getPlayheadMs', `BuilderPage hands useFollowWindow its drawn-playhead getter (got ${hookCall ? hookCall[1] : 'nothing'})`);
  ok(/const getPlayheadMs = useCallback\([\s\S]*?drawnPlayheadMs\(now, shapeOffsetRef\.current\)/.test(page),
     'that getter is drawnPlayheadMs(audible clock, the shape offset)');
  ok(/shapeOffsetRef\.current = Number\(meta\?\.timestamp_offset_ms \?\? 0\)/.test(page)
     && /offsetMs: Number\(meta\?\.timestamp_offset_ms \?\? 0\)/.test(page),
     'the anchor reads the SAME meta.timestamp_offset_ms the canvas view.offsetMs does');
  const layers = readFileSync(path.join(REPO, app.base, 'canvas/layers.ts'), 'utf8');
  const ph = layers.slice(layers.indexOf("id: 'playhead'"));
  ok(/const ms = drawnPlayheadMs\(f\.nowMs!, f\.view\.offsetMs\);/.test(ph.slice(0, 400)),
     'the playhead layer draws through drawnPlayheadMs too');
  const hook = readFileSync(path.join(REPO, app.base, 'hooks/useFollowWindow.ts'), 'utf8');
  ok(/followWindowFor\(s\.getNowMs\(\) \?\? 0, s\.windowS, s\.futureS, dur\)/.test(hook),
     'the hook builds its follow window with followWindowFor');
}

console.log('\n§5 THE TWO TIMELINE TWINS STAY BYTE-IDENTICAL on this hook');
for (const f of ['hooks/followWindow.ts', 'hooks/useFollowWindow.ts']) {
  const a = readFileSync(path.join(REPO, APPS[0].base, f), 'utf8');
  const b = readFileSync(path.join(REPO, APPS[1].base, f), 'utf8');
  ok(a === b, `${f} identical in both apps`);
}

console.log(failures ? `\n${failures} FAILED` : '\nALL OK');
process.exit(failures ? 1 : 0);
