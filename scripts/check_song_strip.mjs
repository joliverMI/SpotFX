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
 *   SIX   — WORD COLOURS (option A): the halo, the fire-alone diamond and
 *           the next-event box's own glyph.
 *   SEVEN — WORD SHAPES (row W2.3): a word that DRAWS a shape is that
 *           shape's own glyph, from its id, in the word's colour — on the
 *           canvas, in the next-event box's glyph and in its hover label —
 *           and an id with no glyph yet falls back to the colour diamond.
 *   EIGHT — WHAT THE COUNTDOWN BOX SAYS (row W5.3, the Admiral
 *           2026-11-18): the box's three texts — a colour word's
 *           reading, a shape word's shape, and both pooled — plus the
 *           older-server fallback, and that NONE of them is the phrase.
 *
 * The original stretched-icon fix (the Admiral's report, 2026-10-14) was a
 * per-axis `axisScale`/`compensate` compensation over a stretched
 * `viewBox="0 0 100 39"`; the TRACK'S OWN DRAWING rewrite superseded it
 * with a 1:1 viewBox (`trackPainter.paintTrack`, songStrip.ts's own
 * `trackX` docstring), which removes the stretch at its source rather
 * than compensating for it — `axisScale`/`compensate` are gone, and so is
 * the section here that drove them.
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
       xFraction, FINAL_STRETCH_MS, NEXT_EVENT_BOX_WIDTH, drawShapeMarkers, KIND_COLOR,
       wordColour, kindGlyphSvg, HALO_GAP, SHAPE_GLYPH, SHAPE_GLYPH_PX, shapeGlyph,
       shapeName, shapeWords, wordReading } = mod;

// THE BOUNDARY IS 99.95s, THE APPROVED MOCKUP'S OWN (`cd()`), not 60s —
// changed in the 2026-10-14 design-fidelity pass. It is what makes
// "99.9s" the widest string the next-event box can hold, which is what
// its own fixed `4.4ch` count field is sized for; the first build
// switched to m:ss at 60s AND kept a tenth after it ("1:04.2"), which is
// both wider than the field and a digit that changes ten times a second
// for minutes on end.
console.log('ONE — countdown formatting (the mockup\'s own cd() rule)');
{
  ok(fmtCountdown(12400) === '12.4s', `12400ms -> "12.4s" (got ${fmtCountdown(12400)})`);
  ok(fmtCountdown(64200) === '64.2s', `64200ms -> "64.2s" (got ${fmtCountdown(64200)})`);
  ok(fmtCountdown(99900) === '99.9s', `99900ms -> "99.9s" — the widest the box holds (got ${fmtCountdown(99900)})`);
  ok(fmtCountdown(128000) === '2:08', `128000ms -> "2:08", no tenth (got ${fmtCountdown(128000)})`);
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
console.log('SIX — word colours (data/word-effect-highlight-options, option A): halo, diamond, box glyph');
{
  const makeCtx = () => {
    const calls = [];
    const rec = (name) => (...a) => { calls.push([name, ...a]); };
    return {
      calls,
      set fillStyle(v) { calls.push(['fillStyle', v]); }, set strokeStyle(v) { calls.push(['strokeStyle', v]); },
      set globalAlpha(v) { calls.push(['globalAlpha', v]); }, set lineWidth(v) { calls.push(['lineWidth', v]); },
      fillRect: rec('fillRect'), beginPath: rec('beginPath'), arc: rec('arc'), fill: rec('fill'),
      moveTo: rec('moveTo'), lineTo: rec('lineTo'), closePath: rec('closePath'), stroke: rec('stroke'),
    };
  };
  const scene = { ms: 10_000, kind: 'scene', rank: 1, rank_of: 10, source: 'analysed', id: 'analysed-scene:k',
                  word: 'smoke', label: 'red', word_ms: 9600, swatch: '#5a14b4' };
  const plain = { ms: 20_000, kind: 'flare', rank: 1, rank_of: 10, source: 'analysed', id: 'analysed-flare:k' };
  const word = { ms: 30_000, kind: 'word', rank: null, rank_of: null, source: 'word', id: 'lyric:300-300',
                 word: 'roses', label: 'red', word_ms: 30_000, swatch: '#ff0000' };
  ok(wordColour(scene) === '#5a14b4', 'an imprinted event lends its word\'s swatch');
  ok(wordColour(plain) === null, 'an event no word reaches lends nothing');
  ok(wordColour(word) === '#ff0000' && wordColour({ ...word, swatch: null }) === KIND_COLOR.word,
    'a word marker wears its swatch, else the kind\'s fallback');
  ok(eventLabel(scene) === 'Scene · 1 of 10 · red' && eventLabel(word) === 'Word · red',
    'the box\'s label names WHAT THE WORD WAS READ AS (W5.3), never the phrase');
  ok(pickNext([scene, word], 25_000) === word, 'a fire-alone word can be "next" like any other event');
  {
    const ctx = makeCtx();
    drawShapeMarkers(ctx, [scene], (ms) => ms / 100, 1000);
    const r = markerSizePx('scene', 1, 10);
    ok(ctx.calls.some((c) => c[0] === 'strokeStyle' && c[1] === '#5a14b4')
      && ctx.calls.some((c) => c[0] === 'arc' && Math.abs(c[3] - (r + HALO_GAP)) < 1e-9),
      'the canvas halo is a ring in the word\'s colour, HALO_GAP outside the marker');
    ok(ctx.calls.some((c) => c[0] === 'fillStyle' && c[1] === KIND_COLOR.scene), 'and the marker keeps its own colour');
  }
  {
    const ctx = makeCtx();
    drawShapeMarkers(ctx, [plain], (ms) => ms / 100, 1000);
    ok(!ctx.calls.some((c) => c[0] === 'strokeStyle'), 'no halo where no word reaches');
  }
  {
    const ctx = makeCtx();
    drawShapeMarkers(ctx, [word], (ms) => ms / 100, 1000);
    ok(ctx.calls.some((c) => c[0] === 'fillStyle' && c[1] === '#ff0000')
      && ctx.calls.filter((c) => c[0] === 'lineTo').length === 3 && ctx.calls.some((c) => c[0] === 'closePath'),
      'a fire-alone word is a filled diamond in its colour');
  }
  const haloed = kindGlyphSvg('scene', null, '#5a14b4');
  ok(haloed.includes('stroke="#5a14b4"') && haloed.includes(`fill="${KIND_COLOR.scene}"`),
    'the box glyph rings the kind\'s own square in the word\'s colour — no second swatch');
  ok(!kindGlyphSvg('scene', null, null).includes('stroke='), 'and draws no ring without a word');
  ok(kindGlyphSvg('word', null, '#ff0000').includes('fill="#ff0000"') && kindGlyphSvg('word').includes(`fill="${KIND_COLOR.word}"`),
    'a word\'s glyph is a diamond in its colour, falling back to the kind\'s');
}

// WORD SHAPES (row W2.3): the one drawing rule for a word that DRAWS — the
// shape's own glyph from its id, in the word's colour, in all three places
// the colour diamond is drawn today.
console.log('SEVEN — word shapes (Word Shapes plan W2.3): the glyph, the label, the box');
{
  const makeCtx = () => {
    const calls = [];
    const rec = (name) => (...a) => { calls.push([name, ...a]); };
    return {
      calls,
      set fillStyle(v) { calls.push(['fillStyle', v]); }, set strokeStyle(v) { calls.push(['strokeStyle', v]); },
      set globalAlpha(v) { calls.push(['globalAlpha', v]); }, set lineWidth(v) { calls.push(['lineWidth', v]); },
      set font(v) { calls.push(['font', v]); }, set textAlign(v) { calls.push(['textAlign', v]); },
      set textBaseline(v) { calls.push(['textBaseline', v]); },
      fillRect: rec('fillRect'), beginPath: rec('beginPath'), arc: rec('arc'), fill: rec('fill'),
      moveTo: rec('moveTo'), lineTo: rec('lineTo'), closePath: rec('closePath'), stroke: rec('stroke'),
      fillText: rec('fillText'),
    };
  };
  const shaped = (over = {}) => ({
    ms: 30_000, kind: 'word', rank: null, rank_of: null, source: 'word',
    id: 'lyric:300-300', word: 'love', label: 'red', word_ms: 30_000, swatch: '#ff0000',
    shape: 'heart', shape_name: 'Heart', ...over,
  });

  ok(SHAPE_GLYPH.heart === '♥' && SHAPE_GLYPH.star === '★' && SHAPE_GLYPH.diamond === '◆',
    'one glyph per shape in the library');
  ok(shapeGlyph('heart') === '♥' && shapeGlyph('cloud') === null && shapeGlyph(null) === null,
    'the glyph is looked up by id; an unknown one has none');
  ok(shapeName('heart') === 'heart' && shapeName('heart', 'Heart') === 'heart'
    && shapeName('cloud', null) === 'cloud',
    'the name is the row\'s own when it carries one, else the library\'s');
  ok(shapeWords('love', 'heart', 'Heart') === 'love → ♥ heart'
    && shapeWords(null, 'heart') === '♥ heart' && shapeWords('love', null) === null,
    'the word and the shape, one string');

  ok(eventLabel(shaped()) === 'Word · heart · red',
    'the box\'s hover label names the shape and the colour it was read as');
  ok(eventLabel(shaped({ shape: null, shape_name: null })) === 'Word · red',
    'a colour word\'s label is its reading');

  {
    const ctx = makeCtx();
    drawShapeMarkers(ctx, [shaped()], (ms) => ms / 100, 1000);
    const text = ctx.calls.find((c) => c[0] === 'fillText');
    ok(text && text[1] === '♥' && Math.abs(text[2] - 300) < 1e-9,
      'on the canvas a shaped word is its glyph, at the word\'s own x');
    ok(ctx.calls.some((c) => c[0] === 'fillStyle' && c[1] === '#ff0000'),
      'in the word\'s own colour');
    ok(!ctx.calls.some((c) => c[0] === 'closePath'), 'and no diamond is drawn as well');
    ok(ctx.calls.some((c) => c[0] === 'font' && c[1].startsWith(`${SHAPE_GLYPH_PX}px`)),
      'at the one shared glyph size');
  }
  {
    const ctx = makeCtx();
    drawShapeMarkers(ctx, [shaped({ shape: 'cloud' })], (ms) => ms / 100, 1000);
    ok(!ctx.calls.some((c) => c[0] === 'fillText') && ctx.calls.some((c) => c[0] === 'closePath'),
      'a shape with no glyph falls back to the diamond rather than drawing nothing');
  }
  for (const [id, glyph] of Object.entries(SHAPE_GLYPH)) {
    const svg = kindGlyphSvg('word', null, '#ff0000', id);
    ok(svg.includes(glyph) && svg.includes('fill="#ff0000"') && svg.includes('<text'),
      `the box glyph for "${id}" is ${glyph} in the word's colour`);
  }
  ok(kindGlyphSvg('word', null, '#ff0000', null).includes('<path'),
    'and a colour word keeps its diamond path');
  ok(kindGlyphSvg('scene', null, '#5a14b4', 'heart').includes(`fill="${KIND_COLOR.scene}"`)
    && !kindGlyphSvg('scene', null, '#5a14b4', 'heart').includes('♥'),
    'a shape never replaces another kind\'s own glyph');
}

// ── EIGHT — WHAT THE COUNTDOWN BOX SAYS A WORD IS (row W5.3) ───────────────
// The Admiral, 2026-11-18: "In the countdown box, don't show the triggering
// phrase or word, just say 'red' or 'sky blue' or whatever it is getting
// interpreted as." `wordReading` is the one function both the box's printed
// line (SongNextBox.tsx) and its hover (eventLabel) read, so the two can
// never say different things about the same row.
console.log('EIGHT — the countdown box says what the word was READ AS');
{
  const row = (over = {}) => ({
    ms: 30_000, kind: 'word', rank: null, rank_of: null, source: 'word',
    id: 'lyric:300-300', word: 'roses are red', word_ms: 30_000, swatch: '#ff0000',
    label: 'red', shape: null, shape_name: null, ...over,
  });

  // the three box texts
  ok(wordReading(row()) === 'red', `a colour word is its reading, got ${wordReading(row())}`);
  ok(wordReading(row({ label: 'Sky Blue' })) === 'sky blue',
    'a two-word reading is printed whole, lower-cased');
  ok(wordReading(row({ label: undefined, shape: 'heart', shape_name: 'Heart' })) === 'heart',
    'a shape word is its shape name');
  const both = row({ shape: 'heart', shape_name: 'Heart' });
  ok(wordReading(both) === 'heart · red',
    `a shape word with a colour kind pooled says both, shape first, got ${wordReading(both)}`);

  // the older-server fallback: never the phrase
  ok(wordReading(row({ label: undefined })) === null,
    'a colour row from a server with no `label` says nothing rather than the phrase');
  ok(eventLabel(row({ label: undefined })) === 'Word',
    'and the box falls back to the kind word alone');
  ok(wordReading(row({ label: undefined, shape: 'heart' })) === 'heart',
    'an older server\'s shape row still falls back to the shape name');
  ok(eventLabel({ kind: 'scene', rank: 1, rank_of: 10, word: 'roses are red' })
    === 'Scene · 1 of 10 · word',
    'an imprinted event from an older server says a word reaches it, not which');

  // THE RULE ITSELF: the phrase never reaches the box
  const phrase = 'roses are red';
  for (const r of [row(), row({ shape: 'heart', shape_name: 'Heart' }),
                   row({ label: undefined, shape: 'heart', shape_name: 'Heart' }),
                   row({ label: undefined })]) {
    ok(!(wordReading(r) ?? '').includes(phrase) && !eventLabel(r).includes(phrase),
      'neither the box\'s line nor its hover ever prints the phrase');
  }
  ok(eventLabel({ kind: 'drop', num: 2, word: phrase, label: 'gold' }) === 'Drop 2 · gold',
    'an event a word imprints on says "· gold" the same way');
}

console.log(failures === 0 ? '\nALL OK' : `\n${failures} FAILURE(S)`);
process.exit(failures === 0 ? 0 : 1);
