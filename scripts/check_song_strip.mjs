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
 *   FIVE  — drawShapeMarkers (Home's audio-shape canvas overlay, added for
 *           the responsiveness+markers build) draws the SAME shape/colour
 *           per kind as the SVG strip above it, at the caller's own
 *           window-mapped x, and skips anything the mapping puts off the
 *           visible canvas — proven against a recording fake ctx, no real
 *           <canvas>.
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
       xFraction, FINAL_STRETCH_MS, NEXT_EVENT_BOX_WIDTH, drawShapeMarkers, KIND_COLOR } = mod;

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

console.log('FIVE — drawShapeMarkers: same shape/colour per kind, windowed, off-canvas skipped');
{
  // A recording fake ctx — records every call so we can assert on shape
  // without needing a real <canvas> 2D context (jsdom has none).
  const makeCtx = () => {
    const calls = [];
    return {
      calls,
      get fillStyle() { return this._fill; }, set fillStyle(v) { this._fill = v; calls.push(['fillStyle', v]); },
      get strokeStyle() { return this._stroke; }, set strokeStyle(v) { this._stroke = v; calls.push(['strokeStyle', v]); },
      get globalAlpha() { return this._alpha; }, set globalAlpha(v) { this._alpha = v; calls.push(['globalAlpha', v]); },
      set lineWidth(v) { calls.push(['lineWidth', v]); },
      fillRect(...a) { calls.push(['fillRect', ...a]); },
      beginPath() { calls.push(['beginPath']); },
      arc(...a) { calls.push(['arc', ...a]); },
      fill() { calls.push(['fill']); },
      moveTo(...a) { calls.push(['moveTo', ...a]); },
      lineTo(...a) { calls.push(['lineTo', ...a]); },
      stroke() { calls.push(['stroke']); },
    };
  };
  const xAt = (ms) => ms / 100; // 1 canvas px per 100 song-ms, for a deterministic mapping

  const scene = { ms: 10000, kind: 'scene', rank: 1, rank_of: 3, source: 'planned' };
  const flare = { ms: 20000, kind: 'flare', rank: null, rank_of: null, source: 'analysed' };
  const drop = { ms: 30000, kind: 'drop', rank: null, rank_of: null, source: 'drop_sequence', num: 1 };
  const charge = { ms: 25000, kind: 'charge', rank: null, rank_of: null, source: 'drop_sequence', num: 1 };
  const high = { ms: 5000, kind: 'high', rank: null, rank_of: null, source: 'show_cue' };

  {
    const ctx = makeCtx();
    drawShapeMarkers(ctx, [scene], xAt, 1000);
    ok(ctx.calls.some((c) => c[0] === 'fillStyle' && c[1] === KIND_COLOR.scene),
      'scene marker fills with KIND_COLOR.scene — the SAME colour the SVG strip uses');
    ok(ctx.calls.some((c) => c[0] === 'fillRect'), 'scene marker is a filled rect (a square), not a circle/line');
  }
  {
    const ctx = makeCtx();
    drawShapeMarkers(ctx, [flare], xAt, 1000);
    ok(ctx.calls.some((c) => c[0] === 'fillStyle' && c[1] === KIND_COLOR.flare), 'flare marker uses KIND_COLOR.flare');
    ok(ctx.calls.some((c) => c[0] === 'arc'), 'flare marker is drawn with arc() — a circle, not a rect');
  }
  {
    const ctx = makeCtx();
    drawShapeMarkers(ctx, [drop, charge], xAt, 1000);
    ok(ctx.calls.filter((c) => c[0] === 'fillRect').length === 2, 'drop and charge both draw a bar (fillRect)');
    const dropRect = ctx.calls.find((c) => c[0] === 'fillRect' && Math.abs(c[1] - (xAt(30000) - 2)) < 1e-6);
    ok(dropRect && dropRect[3] === 4, 'the drop bar is narrower (4px) than a charge/lull bar (10px)');
  }
  {
    const ctx = makeCtx();
    drawShapeMarkers(ctx, [high], xAt, 1000);
    ok(ctx.calls.some((c) => c[0] === 'strokeStyle' && c[1] === KIND_COLOR.high), 'a Light Show trigger uses KIND_COLOR.high');
    ok(ctx.calls.some((c) => c[0] === 'moveTo') && ctx.calls.some((c) => c[0] === 'stroke'),
      'a Light Show trigger is a drawn/stroked flag line, not a filled shape');
  }
  {
    // Off the visible canvas entirely — must draw no shape (only the
    // function's own unconditional globalAlpha=1 reset at the end).
    const ctx = makeCtx();
    drawShapeMarkers(ctx, [{ ...scene, ms: 999999 }], xAt, 100);
    const drewAShape = ctx.calls.some((c) => ['fillRect', 'arc', 'moveTo', 'stroke'].includes(c[0]));
    ok(!drewAShape, 'an event mapped well outside the canvas width draws no shape');
  }
  {
    // globalAlpha is always restored to 1 afterwards, so a later caller
    // drawing something else (the trace itself) is never left faded.
    const ctx = makeCtx();
    drawShapeMarkers(ctx, [scene], xAt, 1000);
    ok(ctx.calls.at(-1)[0] === 'globalAlpha' && ctx.calls.at(-1)[1] === 1,
      'globalAlpha is reset to 1 as the very last call');
  }
}

rmSync(tmp, { recursive: true, force: true });
console.log(failures === 0 ? '\nALL OK' : `\n${failures} FAILURE(S)`);
process.exit(failures === 0 ? 0 : 1);
