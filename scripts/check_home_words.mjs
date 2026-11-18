// Executable spec for THE WORD TRIGGER POINTS ON HOME'S AUDIO SHAPE (Word
// Shapes W5.2 — the Admiral, 2026-11-18: "Show the word/effect details on
// the audio shape on home page. Put the trigger point on the audio shape,
// not just to top ticker. i should be able to tap the audio shape to learn
// more. make it clean").
//
//   ONE   — PURE: the layer and the card, bundled from their REAL sources
//           with esbuild and driven with a recording fake 2D context and
//           no DOM. The markers stand at THE TICKER'S OWN TIMES
//           (`eventFireMs`) mapped through the frame's own `timeToX`, in
//           the ticker's own colours/glyphs; a played one is dimmed to
//           the ticker's own 0.28; the hit test answers within ±6 px and
//           not outside it, and answers NOTHING on a canvas with no word
//           rows (every surface but Home) — the guard that keeps this
//           layer, which deliberately sits above the drop-sequence
//           layer's z, from stealing a tap anywhere else; `doesLine`
//           speaks only from fields `/api/upcoming` really sends; the
//           card's position keeps the 16 px phone gutter.
//   TWO   — THE TICKER AND THE SHAPE AGREE: the SAME filter
//           (`wordRowsOf`) picks the rows, and for every one of them the
//           layer's drawn x is the x the shared `eventFireMs` gives —
//           proved against the ticker's own `drawShapeMarkers` placing
//           the same rows on the same mapping.
//   THREE — BEHAVIOURAL: the REAL HomeTimeline.tsx, mounted beside the
//           REAL SongStrip under the shared view state in jsdom, with
//           `/api/upcoming` serving a shape word, a colour word and an
//           imprint. The canvas draws all three; a pointerdown on the
//           shape word's own x opens the details card with its three
//           lines and its countdown; a pointerdown elsewhere dismisses
//           it; Escape dismisses it; and THE DROP-SELECT TAP STILL
//           SELECTS — the word's own gesture consumes its click, every
//           other one does not.
//   FOUR  — the help topic `home-page` is linked from the audio shape's
//           InfoTip (one orphan fewer) and says what the markers are.
//
// Run: node scripts/check_home_words.mjs
//   (THREE needs the dev-only jsdom: cd spectra/web && npm install --no-save jsdom)
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
const webDir = join(repo, 'spectra/web');
const require = createRequire(join(webDir, 'package.json'));
const esbuild = require('esbuild');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const tmp = mkdtempSync(join(tmpdir(), 'home-words-'));
// `./songStrip` beside `SongStrip.tsx`: esbuild matches the extension-less
// import case-insensitively and fails (AGENTS.md's own note — every sibling
// check carries these two lines). Vite resolves it fine.
const songStripFix = {
  name: 'songstrip-case-fix',
  setup(b) {
    b.onResolve({ filter: /(^|\/)songStrip$/ }, () => (
      { path: join(webDir, 'src/components/songStrip.ts') }
    ));
  },
};

// ── the rows, exactly as spectra/api/upcoming.py sends them ──────────────
// A SHAPE word (lyric_events.word_marks + upcoming._shape_rows), a COLOUR
// word firing alone with a reading (W5.3's `label`) and `momentary: false`,
// an IMPRINT (a scene row carrying the word fields), and two rows no word
// touches — which must stay out of the layer's own list.
const SHAPE_WORD = {
  ms: 30000, end_ms: 30400, kind: 'word', rank: null, rank_of: null, source: 'word',
  id: 'lyric:heart@30000', word: 'my heart', word_ms: 30000, swatch: '#ff4d6d',
  word_key: 'heart@30000', momentary: true, shape: 'heart', shape_name: 'heart',
  words: 'Draws the heart shape: it forms over 1.2 s, finishing on the word, '
    + 'holds 0.8 s and releases over 1.1 s.',
};
const COLOUR_WORD = {
  ms: 60000, end_ms: 60300, kind: 'word', rank: null, rank_of: null, source: 'word',
  id: 'lyric:red@60000', word: 'paint it red', word_ms: 60000, swatch: '#e11d48',
  word_key: 'red@60000', momentary: false, shape: null, label: 'red',
};
const IMPRINT = {
  ms: 90000, kind: 'scene', rank: 2, rank_of: 5, source: 'planned', id: 'scene:90000',
  word: 'the sky', word_ms: 89200, swatch: '#38bdf8', word_key: 'sky@89200', label: 'sky blue',
};
const PLAIN_FLARE = { ms: 45000, kind: 'flare', rank: null, rank_of: null, source: 'analysed', id: 'flare:45000' };
const PLAIN_DROP = { ms: 120000, kind: 'drop', rank: null, rank_of: null, source: 'drop_sequence', num: 1, id: 'drop:1:drop', fire_ms: 120250 };
const WIRE = [SHAPE_WORD, PLAIN_FLARE, COLOUR_WORD, IMPRINT, PLAIN_DROP];

const recordingCtx = () => {
  const calls = [];
  const c = {
    calls,
    set fillStyle(v) { calls.push(['fillStyle', v]); },
    set strokeStyle(v) { calls.push(['strokeStyle', v]); },
    set globalAlpha(v) { calls.push(['globalAlpha', v]); },
    set lineWidth(v) {}, set font(v) { calls.push(['font', v]); },
    set textAlign(v) {}, set textBaseline(v) {},
    save() {}, restore() {}, setLineDash() {},
    beginPath() {}, closePath() {},
    fillRect(...a) { calls.push(['fillRect', ...a]); },
    fillText(...a) { calls.push(['fillText', ...a]); },
    arc(...a) { calls.push(['arc', ...a]); },
    fill() {}, moveTo(...a) { calls.push(['moveTo', ...a]); },
    lineTo(...a) { calls.push(['lineTo', ...a]); },
    stroke() {},
  };
  return c;
};

const WIN = { startMs: 0, endMs: 200000 };
const W = 800;
const frameFor = (words, { nowMs = null, selected = null, w = W } = {}) => ({
  ctx: recordingCtx(), w, h: 230, mainH: 230, railH: 0, stripH: 21, stripCount: 0,
  win: WIN,
  timeToX: (ms) => ((ms - WIN.startMs) / (WIN.endMs - WIN.startMs)) * w,
  xToTime: (x) => WIN.startMs + (x / w) * (WIN.endMs - WIN.startMs),
  nowMs,
  data: { words, wordSelected: selected },
  view: {},
});

console.log('ONE — pure: the layer and the card, driven with a fake context');
{
  const out = join(tmp, 'pure.mjs');
  const entry = join(tmp, 'pure-entry.mjs');
  writeFileSync(entry, `
export * from ${JSON.stringify(join(webDir, 'src/timeline/canvas/wordsLayer.ts'))};
export * as card from ${JSON.stringify(join(webDir, 'src/home/WordDetailsCard.tsx'))};
export * as strip from ${JSON.stringify(join(webDir, 'src/components/songStrip.ts'))};
`);
  const build = await esbuild.build({
    entryPoints: [entry], bundle: true, format: 'esm', platform: 'node', jsx: 'automatic',
    outfile: out, nodePaths: [join(webDir, 'node_modules')], logLevel: 'silent',
    loader: { '.css': 'empty' }, plugins: [songStripFix],
    // React and react-dom are BUNDLED, not externalized: the bundle lands
    // in a temp dir, from which node cannot resolve a bare 'react'
    // specifier against spectra/web/node_modules. Nothing in this section
    // renders — only the card's pure exports are driven — so the cost is
    // bundle size alone.
    define: { 'process.env.NODE_ENV': '"production"' },
  });
  ok(build.errors.length === 0, build.errors.length === 0
    ? 'the real layer and card bundle cleanly'
    : `bundle failed: ${build.errors.map((e) => e.text).join('; ')}`);
  const L = await import(out);
  const { card, strip } = L;

  // ── which rows the layer owns ──────────────────────────────────────────
  const rows = L.wordRowsOf(WIRE);
  ok(rows.length === 3 && rows.includes(SHAPE_WORD) && rows.includes(COLOUR_WORD)
     && rows.includes(IMPRINT),
    `wordRowsOf picks the two words firing alone and the one imprint, and nothing else `
    + `(${rows.length} of ${WIRE.length})`);
  ok(!rows.includes(PLAIN_FLARE) && !rows.includes(PLAIN_DROP),
    'an analysed flare and a drop no word touches are NOT word markers');

  // ── the markers stand at the ticker's own times ────────────────────────
  const f = frameFor(rows);
  L.wordMarkers.draw(f);
  const fillTexts = f.ctx.calls.filter((c) => c[0] === 'fillText');
  ok(fillTexts.length === 1 && fillTexts[0][1] === '♥'
     && Math.abs(fillTexts[0][2] - f.timeToX(strip.eventFireMs(SHAPE_WORD))) < 0.01,
    `the shape word draws its own ♥ glyph at the ticker's eventFireMs x `
    + `(${JSON.stringify(fillTexts[0])}, expected x ${f.timeToX(30000).toFixed(2)})`);
  const diamondApex = f.ctx.calls.filter((c) => c[0] === 'moveTo'
    && Math.abs(c[2] - (L.WORD_ROW_CY - strip.WORD_DIAMOND_R)) < 0.01);
  ok(diamondApex.length === 1
     && Math.abs(diamondApex[0][1] - f.timeToX(strip.eventFireMs(COLOUR_WORD))) < 0.01,
    `the colour word draws the ticker's own diamond (WORD_DIAMOND_R ${strip.WORD_DIAMOND_R}) at its `
    + `own x (${JSON.stringify(diamondApex[0])})`);
  const ticks = f.ctx.calls.filter((c) => c[0] === 'fillRect');
  ok(ticks.length === 1
     && Math.abs(ticks[0][1] - (f.timeToX(strip.eventFireMs(IMPRINT)) - 1)) < 0.01
     && ticks[0][3] === 2,
    `the imprint draws a 2px colour tick at ITS event's x (${JSON.stringify(ticks[0])})`);
  const colours = f.ctx.calls.filter((c) => c[0] === 'fillStyle').map((c) => c[1]);
  ok(colours.includes(SHAPE_WORD.swatch) && colours.includes(COLOUR_WORD.swatch)
     && colours.includes(IMPRINT.swatch),
    `each marker wears the ticker's own wordColour(row) (${colours.join(', ')})`);
  ok(f.ctx.calls.some((c) => c[0] === 'lineTo' && c[2] === f.mainH),
    'each marker stands on a stem reaching the waveform floor — "the trigger point"');

  // ── a played word is dimmed exactly as the ticker dims one ─────────────
  const played = frameFor(rows, { nowMs: 70000 });
  L.wordMarkers.draw(played);
  const alphas = played.ctx.calls.filter((c) => c[0] === 'globalAlpha').map((c) => c[1]);
  ok(alphas.includes(L.WORD_PAST_ALPHA) && L.WORD_PAST_ALPHA === 0.28,
    `a word already played is dimmed to the ticker's own 0.28 (.song-strip-mk-past) `
    + `— measured ${L.WORD_PAST_ALPHA}`);
  const fresh = frameFor([IMPRINT], { nowMs: 0 });
  L.wordMarkers.draw(fresh);
  ok(!fresh.ctx.calls.filter((c) => c[0] === 'globalAlpha').map((c) => c[1])
    .includes(L.WORD_PAST_ALPHA),
    'and a word still ahead of the playhead is not dimmed');

  // ── the selected ring ─────────────────────────────────────────────────
  const sel = frameFor(rows, { selected: L.wordRowKey(COLOUR_WORD) });
  L.wordMarkers.draw(sel);
  const ring = sel.ctx.calls.filter((c) => c[0] === 'arc');
  ok(ring.length === 1
     && Math.abs(ring[0][1] - sel.timeToX(60000)) < 0.01
     && Math.abs(ring[0][3] - (strip.WORD_DIAMOND_R + strip.HALO_GAP)) < 0.01,
    `the row the card is open on wears a ring at the ticker's own halo gap (${JSON.stringify(ring[0])})`);
  ok(frameFor(rows).ctx && (() => {
    const none = frameFor(rows);
    L.wordMarkers.draw(none);
    return none.ctx.calls.filter((c) => c[0] === 'arc').length === 0;
  })(), 'and no ring is drawn with no card open');

  // ── the hit test ──────────────────────────────────────────────────────
  const hf = frameFor(rows);
  const xOf = (row) => hf.timeToX(strip.eventFireMs(row));
  const hit = (x, y = 100) => L.wordMarkers.hitTest(x, y, hf);
  ok(L.WORD_HIT_PX === 6, `the hit tolerance is the spec's ±6 px (${L.WORD_HIT_PX})`);
  const h1 = hit(xOf(SHAPE_WORD));
  ok(h1 && h1.kind === 'word-marker' && h1.key === 'lyric:heart@30000' && h1.ms === 30000,
    `a tap on the shape word's own x hits it, naming its row and its moment (${JSON.stringify(h1)})`);
  ok(hit(xOf(COLOUR_WORD) + 5.9)?.key === 'lyric:red@60000',
    'a tap 5.9 px off still hits — the whole stem column is grabbable');
  ok(hit(xOf(COLOUR_WORD) + 6.1) === null,
    'a tap 6.1 px off hits nothing — the tolerance is a tolerance, not a region');
  ok(hit(xOf(IMPRINT))?.key === 'scene:90000',
    'an imprint tick is tappable too, under its own event id');
  ok(hit(xOf(SHAPE_WORD), 231) === null, 'a tap below the waveform area hits nothing');
  // THE GUARD that lets this layer sit above the drop-sequence layer's z
  // without stealing a tap on any other canvas: with no word rows in the
  // bag it answers nothing at all. (TimelineCanvas.hitTest does not
  // consult `visible`.)
  const empty = frameFor(undefined);
  ok(L.wordMarkers.hitTest(xOf(SHAPE_WORD), 100, empty) === null
     && L.wordMarkers.hitTest(xOf(SHAPE_WORD), 100, frameFor([])) === null,
    'on a canvas with no word rows (every surface but Home) the layer hit-tests NOTHING, '
    + 'so its z above the drop-sequence layer can never steal a tap there');
  ok(L.wordMarkers.z > 65 && L.wordMarkers.z < 70,
    `and its z sits above dropSeqLayer's own 65 so a word beats a drop handle's scan-line `
    + `(z ${L.wordMarkers.z})`);
  ok(L.wordMarkers.visible(frameFor(rows)) && !L.wordMarkers.visible(frameFor([])),
    'it is visible only where there are word rows to draw');

  // ── the card's three lines ────────────────────────────────────────────
  ok(strip.wordReading(SHAPE_WORD) === 'heart', 'the shape word reads as "heart" (W5.3\'s own helper)');
  ok(strip.wordReading(COLOUR_WORD) === 'red', 'the colour word reads as "red", never its phrase');
  ok(strip.wordReading(IMPRINT) === 'sky blue', 'the imprint reads as "sky blue"');
  ok(card.doesLine(SHAPE_WORD) === SHAPE_WORD.words,
    'what fires, for a shape word, is the API\'s OWN sentence (lyric_events.describe)');
  ok(/holds until the next scene change/.test(card.doesLine(COLOUR_WORD)),
    `a momentary:false colour word says its colour HOLDS (${card.doesLine(COLOUR_WORD)})`);
  ok(/for a moment/.test(card.doesLine({ ...COLOUR_WORD, momentary: true })),
    'and a momentary one says it arrives for a moment');
  ok(card.doesLine({ ...COLOUR_WORD, momentary: undefined }) === null,
    'an older server that sends no `momentary` leaves the line OUT rather than guessing');
  ok(card.doesLine(IMPRINT) === 'Gives its colour to the scene at 1:30.',
    `an imprint names the event it lends its colour to, and when (${card.doesLine(IMPRINT)})`);
  ok(card.awayLine(COLOUR_WORD, 47600) === '12.4s away'
     && card.awayLine(COLOUR_WORD, 60000 + 100000) === '1:40 ago',
    'the countdown is countdownParts, the ticker\'s own rule — tenths, then m:ss, away or ago');
  ok(card.awayLine(COLOUR_WORD, null) === null, 'and nothing at all with no clock');
  // NO CHANCE LINE: `chance` is not a field /api/upcoming sends (see the
  // card's docstring), and W5.2's own rule is to leave such a line out.
  const cardSrc = readFileSync(join(webDir, 'src/home/WordDetailsCard.tsx'), 'utf8');
  ok(!/row\.chance|\bchance\s*\?/.test(cardSrc),
    'the card reads no `chance` off the row — the field is not on /api/upcoming, so the '
    + 'line is left out rather than invented (the Test Bed is where a roll is read)');

  // ── the phone gutter ──────────────────────────────────────────────────
  const phone = card.cardPosition({ x: 20, y: 40 }, { w: 390, h: 844 });
  ok(phone.left === card.VIEWPORT_GUTTER && card.VIEWPORT_GUTTER === 16,
    `a marker near the left edge keeps the 16 px gutter (left ${phone.left})`);
  const right = card.cardPosition({ x: 380, y: 40 }, { w: 390, h: 844 });
  ok(right.left + right.width === 390 - card.VIEWPORT_GUTTER,
    `and one near the right edge stays inside it too (left ${right.left}, width ${right.width})`);
  const narrow = card.cardPosition({ x: 100, y: 40 }, { w: 240, h: 844 });
  ok(narrow.width === 240 - 32 && narrow.left === 16,
    `on a screen narrower than the card, the card narrows to fit the gutters (${JSON.stringify(narrow)})`);
  const mid = card.cardPosition({ x: 500, y: 60 }, { w: 1440, h: 900 });
  ok(Math.abs(mid.left + mid.width / 2 - 500) < 0.01 && mid.top === 60 + card.MARKER_GAP,
    `with room, the card is centred UNDER ITS MARKER (${JSON.stringify(mid)})`);

  console.log('TWO — the shape and the ticker place the same rows on the same times');
  {
    const tickerCtx = recordingCtx();
    const xAt = (ms) => f.timeToX(ms);
    // The ticker's own canvas painter, handed the same rows.
    strip.drawShapeMarkers(tickerCtx, [SHAPE_WORD, COLOUR_WORD], xAt, W);
    const tickerGlyph = tickerCtx.calls.find((c) => c[0] === 'fillText');
    ok(tickerGlyph && tickerGlyph[1] === '♥'
       && Math.abs(tickerGlyph[2] - fillTexts[0][2]) < 0.01,
      `the ticker's own drawShapeMarkers puts the ♥ at the SAME x the shape's layer does `
      + `(${tickerGlyph[2].toFixed(2)} vs ${fillTexts[0][2].toFixed(2)})`);
    const tickerColours = tickerCtx.calls.filter((c) => c[0] === 'fillStyle').map((c) => c[1]);
    ok(tickerColours.includes(SHAPE_WORD.swatch) && tickerColours.includes(COLOUR_WORD.swatch),
      'and in the same colours — one `wordColour`, one `shapeGlyph`, two surfaces');
    for (const row of rows) {
      ok(Math.abs(f.timeToX(strip.eventFireMs(row)) - xAt(strip.eventFireMs(row))) < 1e-9,
        `${row.id}: one shared eventFireMs, one shared mapping — the two can never disagree`);
    }
  }
}

console.log('THREE — behavioural: the real HomeTimeline, tapped in jsdom');
let jsdomMod;
try {
  jsdomMod = require('jsdom');
} catch {
  console.log('  jsdom not installed in spectra/web/node_modules (dev-only, not a declared '
    + 'dependency) — skipping THREE. Install with `cd spectra/web && npm install --no-save jsdom`.');
  jsdomMod = null;
}
if (jsdomMod) {
  const { JSDOM } = jsdomMod;
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/', pretendToBeVisual: true,
  });
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });
  globalThis.HTMLElement = dom.window.HTMLElement;
  globalThis.SVGElement = dom.window.SVGElement;
  globalThis.Node = dom.window.Node;
  globalThis.localStorage = dom.window.localStorage;
  globalThis.PointerEvent = dom.window.PointerEvent;
  globalThis.KeyboardEvent = dom.window.KeyboardEvent;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  if (typeof globalThis.ResizeObserver === 'undefined') {
    globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
  }
  dom.window.ResizeObserver = globalThis.ResizeObserver;
  dom.window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {} });
  globalThis.matchMedia = dom.window.matchMedia;

  let rafQueue = [];
  const fakeRaf = (cb) => { rafQueue.push(cb); return rafQueue.length; };
  globalThis.requestAnimationFrame = fakeRaf;
  globalThis.cancelAnimationFrame = () => {};
  dom.window.requestAnimationFrame = fakeRaf;
  dom.window.cancelAnimationFrame = globalThis.cancelAnimationFrame;
  const tickRaf = (n = 1) => {
    for (let i = 0; i < n; i += 1) {
      const cbs = rafQueue;
      rafQueue = [];
      for (const cb of cbs) cb(performance.now());
    }
  };

  // ONE WIDTH EVERYWHERE (800): the canvas's own `clientWidth` (what
  // `TimelineCanvas`'s geom maps with) and the shape box's rect (what the
  // drop-select `onClick` maps with) must agree, or a tap computed for one
  // would land somewhere else for the other.
  const CANVAS_W = 800;
  dom.window.HTMLElement.prototype.getBoundingClientRect = function () {
    return { left: 0, top: 0, right: CANVAS_W, bottom: 230, width: CANVAS_W, height: 230, x: 0, y: 0, toJSON() {} };
  };
  dom.window.SVGElement.prototype.getBoundingClientRect = function () {
    return { left: 0, top: 0, right: CANVAS_W, bottom: 39, width: CANVAS_W, height: 39, x: 0, y: 0, toJSON() {} };
  };

  const canvasCalls = [];
  const fakeCtxProto = {
    set fillStyle(v) { canvasCalls.push(['fillStyle', v]); },
    set strokeStyle(v) { canvasCalls.push(['strokeStyle', v]); },
    set globalAlpha(v) {}, set lineWidth(v) {}, set font(v) {},
    set textAlign(v) {}, set textBaseline(v) {},
    setTransform() {}, clearRect() {}, setLineDash() {}, save() {}, restore() {},
    beginPath() {}, closePath() {}, fill() {}, stroke() {},
  };
  const recCtx = Object.create(fakeCtxProto);
  for (const m of ['fillRect', 'arc', 'moveTo', 'lineTo', 'fillText']) {
    recCtx[m] = (...a) => canvasCalls.push([m, ...a]);
  }
  // jsdom ships no Pointer Capture: a pointerdown that lands on a drop
  // handle takes `TimelineCanvas`'s own drag branch, which captures the
  // pointer. Stubbed so the drop-select section below exercises the real
  // handler rather than dying inside the listener.
  dom.window.Element.prototype.setPointerCapture = function () {};
  dom.window.Element.prototype.releasePointerCapture = function () {};
  const canvasProto = dom.window.HTMLCanvasElement.prototype;
  canvasProto.getContext = function (kind) { return kind === '2d' ? recCtx : null; };
  Object.defineProperty(canvasProto, 'clientWidth', { configurable: true, get() { return CANVAS_W; } });
  Object.defineProperty(canvasProto, 'clientHeight', { configurable: true, get() { return 230; } });
  dom.window.devicePixelRatio = 1;

  const NodeResponse = globalThis.Response;
  const DURATION_MS = 200000;
  const URI = 'spotify:track:w52';
  const TRACK = {
    uri: URI, title: 'Octavian', artist: 'Someone', duration_ms: DURATION_MS,
    is_playing: true, position_ms: 40000, show_clock_ms: 40000,
  };
  // ONE drop sequence, deliberately FAR from every word marker (charge
  // 140 s, drop 150 s vs words at 30/60/90 s), so the drop-select tap this
  // section fires can only ever be a drop-select tap.
  const DROP_VIEW = {
    key: 'det:150000', origin: 'detected', state: 'approved',
    charge_ms: 140000, lull_ms: 146000, drop_ms: 150000, tier: 'confident',
    detected_key: 'det:150000', auto: { charge_ms: 140000, lull_ms: 146000, drop_ms: 150000 },
    moved: {}, lull_off: false, charge_off: false, score: 0.9, break_beats: 8, step: 1,
    rise: 0.4, path: null, loud_before: false, capped: false, notes: [], needs_review: false,
    detection_lost: false, matches: [], his_marks_near: [], fires: true,
  };
  const fakeFetch = async (url) => {
    const u = String(url);
    const json = (b) => new NodeResponse(JSON.stringify(b), { status: 200, headers: { 'Content-Type': 'application/json' } });
    if (u.includes('/api/engine/status')) {
      return json({ dark: false, bridge: { connected: true, track: TRACK, next_track: null, intensity: 0.5 } });
    }
    if (u.includes('/api/upcoming')) {
      return json({ uri: URI, effective_mode: 'analysed', has_authored: false, events: WIRE });
    }
    if (u.includes('/audio-shape/librosa')) return json({ sections: [], beats: [], onsets: [] });
    if (u.includes('/drop-sequences')) {
      return json({ uri: URI, status: 'detected', sequences: [DROP_VIEW], authored: [],
                    song: { captured_from_ms: 0, beat_ms: 500 } });
    }
    if (u.includes('/audio-shape/meta')) {
      return json({ spotify_uri: URI, title: 'x', artist: 'y', duration_ms: DURATION_MS,
                    sample_interval_ms: 200, music_marks: [], capture_complete: true,
                    timestamp_offset_ms: 0, perception_trim_ms: 0, offset_verification: 'auto_verified' });
    }
    if (u.includes('/audio-shape/data')) {
      return json({ timestamps_ms: [], rms_total: [], rms_low: [], rms_mid: [], rms_high: [], avg_rms_1s: null });
    }
    if (u.includes('/analysed-plan')) {
      return json({ uri: URI, applies: false, reason: null, effective_mode: 'full', has_authored: false,
                    scene_source: null, scene_changes: [], flares: [], show_clock_shift_ms: 0,
                    show_cues: { uri: URI, reason: null, duration_ms: DURATION_MS, high: null, low: null } });
    }
    if (u.includes('/light-show/arms')) {
      return json({ armed: [], history: [], song: { uri: null, position_ms: null, cues: null,
                    expected_scene_change_s: null, expected_scene_change_is_floor: false },
                    last_crossed: {}, refusal: null });
    }
    if (u.includes('/api/energy/timeline')) return json({ status: 'missing', sections: [] });
    return json({});
  };
  globalThis.fetch = fakeFetch;
  dom.window.fetch = fakeFetch;

  const entryFile = join(tmp, 'three-entry.mjs');
  writeFileSync(entryFile, `
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import HomeTimeline from ${JSON.stringify(join(webDir, 'src/home/HomeTimeline.tsx'))};
import SongStrip from ${JSON.stringify(join(webDir, 'src/components/SongStrip.tsx'))};
import { SongTimelineViewProvider, useSongTimelineView } from ${JSON.stringify(join(webDir, 'src/components/songTimelineView.tsx'))};
import { useShowClockSeed } from ${JSON.stringify(join(webDir, 'src/queries.ts'))};
import { getShowClockMs } from ${JSON.stringify(join(webDir, 'src/lib/showClock.ts'))};

// THE ONE SHOW CLOCK's own seeder, mounted exactly where the real tree
// mounts it (App.tsx:74) — the card's countdown reads getShowClockMs(),
// and without this the harness would have no clock at all and the line
// would be legitimately absent.
function ClockSeed() { useShowClockSeed(); return null; }

// A probe on the SHARED view state, so "the drop-select tap still selects"
// is observed through the one state Home's Drops panel actually reads
// (selectedDrop), not through a spy of this test's own.
function DropProbe() {
  const { selectedDrop } = useSongTimelineView();
  return React.createElement('span', { className: 'w52-probe' },
    selectedDrop ? String(selectedDrop.ms) : '');
}

const container = document.createElement('div');
document.body.appendChild(container);
const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

export async function settle(rounds = 6) {
  for (let i = 0; i < rounds; i += 1) {
    await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
  }
}
let root = null;
let clockSeed = false;
function tree() {
  return React.createElement(QueryClientProvider, { client: qc },
      React.createElement(MemoryRouter, null,
        React.createElement(SongTimelineViewProvider, null,
          clockSeed ? React.createElement(ClockSeed, null) : null,
          React.createElement(SongStrip, null),
          React.createElement(HomeTimeline, { uri: ${JSON.stringify(URI)}, showAudioShape: true }),
          React.createElement(DropProbe, null))));
}
export async function mount() {
  root = createRoot(container);
  await act(async () => { root.render(tree()); });
  for (let i = 0; i < 60 && !container.querySelector('.home-timeline-shape canvas'); i += 1) {
    await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
  }
  await settle(12);
  return container;
}
// WAIT FOR THE SHOW CLOCK. The seeder's very first run lands before the
// 3 s engine-status poll has data, so it anchors a NULL clock — and
// seedShowClockFromStatus's own backstop rule ("a push that arrived more
// recently than this poll always wins") then ignores the real one for
// 2.5 s. In the app that passes unnoticed; a test that taps inside that
// window would see a legitimately empty countdown line and prove nothing.
export async function waitForClock(maxMs = 5000) {
  // Mounted only NOW, with the status query already in cache, so the
  // seeder's first effect run already carries the real track. Mounted with
  // the rest it would fire once with its data still undefined, anchor a NULL
  // clock, and then be shut out for 2.5 s by its own backstop rule — and
  // the 3 s poll never re-runs the effect, because react-query's
  // structural sharing hands back the same object. The app does not care
  // (its WS clock pushes arrive at 1 Hz; this harness has no socket).
  clockSeed = true;
  await act(async () => { root.render(tree()); });
  const t0 = Date.now();
  while (getShowClockMs() == null && Date.now() - t0 < maxMs) {
    await act(async () => { await new Promise((r) => setTimeout(r, 60)); });
  }
  return getShowClockMs();
}
export async function pointerDownAt(el, clientX, clientY = 100) {
  await act(async () => {
    el.dispatchEvent(new window.PointerEvent('pointerdown', {
      bubbles: true, cancelable: true, button: 0, pointerId: 1, pointerType: 'mouse',
      clientX, clientY,
    }));
  });
  await settle(2);
}
export async function clickAt(el, clientX, clientY = 100) {
  await act(async () => {
    el.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true, clientX, clientY }));
  });
  await settle(2);
}
export async function escape() {
  await act(async () => {
    document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  });
  await settle(2);
}
`);
  const outFile = join(tmp, 'three.cjs');
  const b3 = await esbuild.build({
    entryPoints: [entryFile], bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
    outfile: outFile, nodePaths: [join(webDir, 'node_modules')], logLevel: 'silent',
    loader: { '.css': 'empty' }, plugins: [songStripFix],
  });
  ok(b3.errors.length === 0, b3.errors.length === 0
    ? 'the real HomeTimeline bundles cleanly'
    : `bundle failed: ${b3.errors.map((e) => e.text).join('; ')}`);
  const H = require(outFile);
  const container = await H.mount();
  tickRaf(2);

  const canvas = container.querySelector('.home-timeline-shape canvas');
  const shapeBox = container.querySelector('.home-timeline-shape');
  ok(!!canvas && !!shapeBox, 'the shape canvas is mounted');
  const clock = await H.waitForClock();
  ok(clock != null, `the one show clock has an anchor, so a countdown can be drawn (${clock})`);

  // THE WHOLE SONG, so every fixture moment is on the canvas at a known x.
  // Taken through the control row's own button — the window arithmetic
  // stays the canvas's own `getWin` (PR 542's centred follow window is
  // deliberately unclamped, so a hand-computed window would be wrong).
  const fullSong = [...container.querySelectorAll('.home-timeline-tool')]
    .find((b) => (b.getAttribute('title') || '') === 'Whole song');
  ok(!!fullSong, 'the control row still carries "Whole song"');
  await H.clickAt(fullSong, 0, 0);
  tickRaf(2);
  const xOfMs = (ms) => (ms / DURATION_MS) * CANVAS_W;

  const drew = (pred) => canvasCalls.some(pred);
  ok(drew((c) => c[0] === 'fillText' && c[1] === '♥'
      && Math.abs(c[2] - xOfMs(30000)) < 1.5),
    `the canvas drew the shape word's ♥ at its own moment (x ≈ ${xOfMs(30000).toFixed(1)})`);
  ok(drew((c) => c[0] === 'fillStyle' && c[1] === COLOUR_WORD.swatch),
    'and the colour word in its own swatch');
  ok(drew((c) => c[0] === 'fillRect' && c[3] === 2
      && Math.abs(c[1] - (xOfMs(90000) - 1)) < 1.5),
    'and the imprint tick on the event the word lends its colour to');

  const card = () => document.querySelector('.home-word-card');
  ok(card() === null, 'no card is open before anything is tapped');

  // ── THE TAP ─────────────────────────────────────────────────────────────
  await H.pointerDownAt(canvas, xOfMs(30000));
  await H.clickAt(canvas, xOfMs(30000));
  const c1 = card();
  ok(c1 !== null, 'a tap on the shape word opens the details card');
  if (c1) {
    ok(c1.querySelector('.home-word-card-reading')?.textContent === 'heart',
      `the reading is first and largest, and it is the READING ("${c1.querySelector('.home-word-card-reading')?.textContent}")`);
    ok(c1.querySelector('.home-word-card-phrase')?.textContent?.includes('my heart'),
      'the sung words are under it, in the muted line');
    ok((c1.querySelector('.home-word-card-does')?.textContent || '').startsWith('Draws the heart shape'),
      `and one line of what fires ("${(c1.querySelector('.home-word-card-does')?.textContent || '').slice(0, 40)}…")`);
    const away = c1.querySelector('.home-word-card-away')?.textContent || '';
    ok(/(away|ago)$/.test(away), `and how far away it is ("${away}")`);
    ok(c1.querySelector('.home-word-card-swatch') !== null, 'with the word\'s own swatch beside the reading');
  }
  ok(container.querySelector('.w52-probe')?.textContent === '',
    'and the word\'s own gesture did NOT also select a drop sequence');

  // the selected marker is ringed
  canvasCalls.length = 0;
  tickRaf(2);
  ok(canvasCalls.some((c) => c[0] === 'arc' && Math.abs(c[1] - xOfMs(30000)) < 1.5),
    'the tapped marker is ringed while its card is open');

  // ── A SECOND WORD takes the card over ───────────────────────────────────
  await H.pointerDownAt(canvas, xOfMs(60000));
  await H.clickAt(canvas, xOfMs(60000));
  ok(card()?.querySelector('.home-word-card-reading')?.textContent === 'red',
    'tapping another word moves the card to it (and the outside-tap listener does not eat it)');
  ok(/holds until the next scene change/.test(card()?.querySelector('.home-word-card-does')?.textContent || ''),
    'a low-energy colour word says its colour HOLDS');

  // ── DISMISS: a tap on bare shape ────────────────────────────────────────
  await H.pointerDownAt(canvas, xOfMs(10000));
  await H.clickAt(canvas, xOfMs(10000));
  ok(card() === null, 'a tap anywhere else on the shape dismisses it');

  // ── DISMISS: Escape ─────────────────────────────────────────────────────
  await H.pointerDownAt(canvas, xOfMs(90000));
  await H.clickAt(canvas, xOfMs(90000));
  ok(card()?.querySelector('.home-word-card-reading')?.textContent === 'sky blue',
    'an imprint tick opens the card too, reading as the colour its word was read as');
  await H.escape();
  ok(card() === null, 'Escape dismisses it');

  // ── THE DROP-SELECT TAP IS UNCHANGED ────────────────────────────────────
  const dropX = xOfMs(145000);
  await H.pointerDownAt(canvas, dropX);
  await H.clickAt(canvas, dropX);
  ok(container.querySelector('.w52-probe')?.textContent === '150000',
    `a tap inside a drop sequence still selects it (probe "${container.querySelector('.w52-probe')?.textContent}")`);
  ok(card() === null, 'and opens no word card');
}

console.log('FOUR — the help topic');
{
  const help = readFileSync(join(webDir, 'src/help/helpContent.ts'), 'utf8');
  const home = readFileSync(join(webDir, 'src/home/HomeTimeline.tsx'), 'utf8');
  ok(/topic="home-page"/.test(home),
    'the audio shape\'s InfoTip links the `home-page` topic — one help orphan fewer');
  const intro = help.slice(help.indexOf("id: 'home-page'"), help.indexOf("id: 'song-timeline'"));
  ok(/STANDS ON THE SHAPE at the moment it fires/.test(intro),
    'and `home-page` says the words stand on the shape where they fire');
  ok(/TAP ONE/.test(intro) && /Escape/.test(intro),
    'and that a tap opens the details, and how it goes away');
  ok(/Test Bed/.test(intro),
    'and sends him to the Test Bed for a word\'s odds, which this card does not claim');
}

console.log(failures === 0
  ? '\nALL CHECKS PASSED — the words stand where they fire, a tap says what they do, '
    + 'and the drop-select tap is untouched'
  : `\n${failures} CHECK(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
