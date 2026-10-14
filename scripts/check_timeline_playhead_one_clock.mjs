/**
 * Executable spec: the Timeline page's audio-shape canvas playhead and its
 * SPECTRA trigger/drop strips draw the IDENTICAL clock (song-layout-plan,
 * data/ui-layout-plan/report.md §4.1/§7, his own "perfectly matched" ask).
 *
 * Two proofs:
 *   ONE   — SOURCE: BuilderPage.tsx wires the exact same `getStripNowMs`
 *           function (never a second, differently-shifted one) to every
 *           `getNowMs` prop — TimelineBar, SpectraTriggersCard,
 *           DropSequenceStrip AND the audio-shape TimelineCanvas. Proven by
 *           counting call sites in the real source, not by argument.
 *   TWO   — BEHAVIOUR: the real `playhead` canvas layer (canvas/layers.ts,
 *           bundled with esbuild) draws at `f.nowMs` VERBATIM — fed a huge,
 *           deliberately wrong `view.offsetMs`, the drawn line must not
 *           move. This is the legacy shift (`drawnPlayheadMs`) this build
 *           retired; the red control reproduces the OLD formula inline and
 *           shows it WOULD have moved, so this isn't a tautology.
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const BUILDER_PAGE = path.join(REPO, 'spectra/web/src/timeline/BuilderPage.tsx');
const LAYERS = path.join(REPO, 'spectra/web/src/timeline/canvas/layers.ts');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

console.log('ONE — BuilderPage.tsx wires ONE getNowMs function everywhere');
{
  const src = readFileSync(BUILDER_PAGE, 'utf8');
  const sharedHits = (src.match(/getNowMs=\{getStripNowMs\}/g) ?? []).length;
  ok(sharedHits === 4,
    `getStripNowMs is passed to exactly 4 getNowMs props (TimelineBar, ` +
    `SpectraTriggersCard, DropSequenceStrip, the audio-shape canvas) — found ${sharedHits}`);
  // Code-level only (not prose in comments, which still name the retired
  // functions historically): no DECLARATION of either old function, and
  // no live IMPORT of the shift arithmetic they used.
  ok(!/\bconst getCanvasNowMs\b/.test(src) && !/\bconst getPlayheadMs\b/.test(src),
    'the old, separately-shifted getCanvasNowMs/getPlayheadMs are gone — nothing left to disagree with the strips');
  ok(!/^import .*drawnPlayheadMs/m.test(src),
    'BuilderPage.tsx no longer imports the shift arithmetic for its canvas playhead');
}

console.log('\nTWO — the playhead LAYER draws f.nowMs verbatim, ignoring view.offsetMs');
{
  const tmp = mkdtempSync(path.join(tmpdir(), 'playhead-one-clock-'));
  const js = path.join(tmp, 'layers.mjs');
  execFileSync('npx', ['esbuild', LAYERS, '--bundle', '--format=esm', '--platform=node',
    '--log-level=error', `--outfile=${js}`], {
    cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
  });
  const { playhead } = await import(js);

  const fakeFrame = (nowMs, offsetMs) => {
    const moves = [];
    const ctx = {
      save() {}, restore() {}, beginPath() {}, closePath() {}, fill() {}, stroke() {},
      setLineDash() {},
      moveTo(x) { moves.push(x); },
      lineTo(x) { moves.push(x); },
    };
    return {
      ctx, w: 1000, mainH: 100,
      win: { startMs: 0, endMs: 200000 },
      timeToX: (ms) => ms / 200,       // identity-ish, deterministic
      nowMs,
      view: { offsetMs },
      data: {},
      moves,
    };
  };

  const f1 = fakeFrame(74300, 0);
  playhead.draw(f1);
  const f2 = fakeFrame(74300, 999_999); // a deliberately huge, wrong shift
  playhead.draw(f2);
  ok(f1.moves.length > 0 && f2.moves.length > 0, 'the layer actually drew a line in both cases');
  ok(JSON.stringify(f1.moves) === JSON.stringify(f2.moves),
    `a 999999ms view.offsetMs changes nothing: drawn at x=${f1.moves[0]} either way`);
  ok(f1.moves[0] === 74300 / 200, 'the drawn position is exactly timeToX(nowMs), no added term');

  console.log('\n  RED CONTROL — the retired formula WOULD have moved the line');
  const oldFormula = (nowMs, offsetMs) => nowMs + offsetMs; // drawnPlayheadMs, inlined
  const oldX = (ms) => ms / 200;
  ok(oldX(oldFormula(74300, 0)) !== oldX(oldFormula(74300, 999_999)),
    'proving the check is not a tautology: the OLD shifted formula really did disagree across the two offsets');

  rmSync(tmp, { recursive: true, force: true });
}

console.log(failures === 0 ? '\nALL OK' : `\n${failures} FAILURE(S)`);
process.exit(failures === 0 ? 0 : 1);
