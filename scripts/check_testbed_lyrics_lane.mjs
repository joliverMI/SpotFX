/** Executable spec for the Sung words lane's frontend: the pure helpers in
 * spectra/web/src/testbed/lyricsLane.ts and the real LyricsLane component,
 * bundled with esbuild over its real imports and rendered with
 * react-dom/server (the check_testbed_predrop_lane.mjs pattern: real source,
 * no copy).
 *
 * Asserted:
 *   1. One scale: every lane reads viewPct, so a word and a flare at the same
 *      time share a position at any zoom, and zooming keeps the window inside
 *      the song.
 *   2. Labels: the strongest words keep their printed name when the lane is
 *      crowded, nothing overlaps, and everything stays in the lane.
 *   3. The lane: every word faint, emphasized ones marked with the word, his
 *      marks as guide lines, and the chip's place on a mark.
 *   4. A flagged song draws no guides and says why; a song with no usable
 *      words says which reason it is; nothing on the lane is clickable.
 *   5. The roll (spectra/web/src/testbed/lyricEvents.ts, 2026-11-12): a chip
 *      carries its chance, a word sitting out says so, the roll line names
 *      the play, and the Always / Chance / Never control marks the one on.
 *   6. WORD SHAPES (row W2.3): a drawing word's chip is "love -> heart" with
 *      its chance, a shaped word doing its colour says why it is, the Word
 *      events row carries the shape so it can draw the glyph, and the live
 *      pulse says what became of the shape.
 *
 * Run: node scripts/check_testbed_lyrics_lane.mjs
 */
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
const require = createRequire(join(repo, 'spectra/web/package.json'));
const esbuild = require('esbuild');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const entry = `
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import LyricsLane from './spectra/web/src/testbed/components/LyricsLane';
import PinControl from './spectra/web/src/testbed/components/PinControl';
export * from './spectra/web/src/testbed/lyricsLane';
export * as events from './spectra/web/src/testbed/lyricEvents';
export * as strip from './spectra/web/src/components/songStrip';
export * as pulse from './spectra/web/src/lib/wordColourPush';
export function render(props) { return renderToStaticMarkup(React.createElement(LyricsLane, props)); }
export function renderPin(props) { return renderToStaticMarkup(React.createElement(PinControl, props)); }
`;
const built = await esbuild.build({
  stdin: { contents: entry, resolveDir: repo, loader: 'tsx' },
  bundle: true, format: 'cjs', platform: 'node', write: false, jsx: 'automatic',
  // `.ts` BEFORE `.tsx`, deliberately: `components/songStrip.ts` (the
  // drawing rules the chips and the pulse now share) sits beside
  // `components/SongStrip.tsx`, and esbuild's own directory cache matches
  // `songStrip.tsx` to that component's file before failing to read it.
  // Vite resolves the same import fine; this is the bundler used here only.
  resolveExtensions: ['.ts', '.tsx', '.mjs', '.js', '.jsx', '.json'],
  nodePaths: [join(repo, 'spectra/web/node_modules')],
  logLevel: 'error',
});
const out = join(mkdtempSync(join(tmpdir(), 'lyrics-lane-')), 'lane.cjs');
writeFileSync(out, built.outputFiles[0].text);
const lib = createRequire(import.meta.url)(out);

const VIEW = lib.wholeSong(100_000);
const words = [
  { word: 'we', line: 0, ms: 10_000, end_ms: 10_200, score: 0.1 },
  { word: 'red', line: 0, ms: 20_000, end_ms: 20_800, score: 0.7 },
  { word: 'light', line: 0, ms: 30_000, end_ms: 30_300, score: 0.2 },
];
const clock = { lane_clock: 'capture_label', max_slip_ms: 5, flagged: false, note: null };
const data = {
  uri: 'u', status: 'ok', note: null, lang: 'eng', provenance: 'lrclib_synced', mode: 'line_anchored',
  clock, default_sensitivity: 0.6, words,
};
const estimate = [{
  time_ms: 20_000, label: 'red', score: 0.7,
  detail: { end_ms: 20_800, line: 0, features: { loud: 0.5, held: 1, beat: 0, line_end: 1, hook: 0.4 }, matched_label: null },
}];
// The engine's own word events as guide lines (TestbedLaneBar's Word events
// row, 2026-11-12): a scene change a word imprints on, in the word's colour,
// and a flare no word reaches.
const guides = [
  { id: 'analysed-scene:k', ms: 20_000, cls: 'scene', halo: '#c81e1e' },
  { id: 'analysed-flare:k', ms: 5000, cls: 'flare', halo: null },
];
const lane = (over = {}) => lib.render({
  label: 'Sung words', data, estimate, view: VIEW, metrics: null, guides, ...over,
});

console.log('§1 one scale');
{
  const zoomed = lib.laneView(100_000, 10_000, 50_000);
  ok(zoomed.startMs === 45_000 && zoomed.endMs === 55_000, 'a zoom is centred on where you are');
  ok(lib.viewPct(zoomed, 50_000) === 50, 'a time maps to the lane the same for every lane');
  const edge = lib.laneView(100_000, 10_000, 99_000);
  ok(edge.endMs === 100_000 && edge.startMs === 90_000, 'a zoom cannot run off the end of the song');
  const start = lib.laneView(100_000, 10_000, 0);
  ok(start.startMs === 0 && start.endMs === 10_000, 'nor off the start');
  ok(lib.laneView(5000, 10_000, 2000).endMs === 5000, 'a span longer than the song is the whole song');
  ok(lib.laneView(100_000, null, 50_000).startMs === 0, 'no span is the whole song');
  ok(lib.inView(zoomed, 44_000, 46_000), 'a word that crosses the edge still shows');
  ok(!lib.inView(zoomed, 40_000, 44_000), 'one that does not, does not');
}

console.log('§2 printed words');
{
  const crowded = [
    { xPx: 100, text: 'quiet', score: 0.2 },
    { xPx: 102, text: 'loudest', score: 0.9 },
    { xPx: 104, text: 'second', score: 0.8 },
    { xPx: 106, text: 'third', score: 0.7 },
  ];
  const placed = lib.layoutLabelRows(crowded, 1000, 3);
  ok(placed[0] === null, 'the weakest word loses its printed name first');
  ok(placed[1] && placed[2] && placed[3], 'the three strongest keep theirs');
  const rows = placed.filter(Boolean).map((p) => p.row);
  ok(new Set(rows).size === 3, 'one to a row when they would collide');

  const edge = lib.layoutLabelRows([{ xPx: 995, text: 'home', score: 0.5 }], 1000);
  ok(edge[0].leftPx + edge[0].widthPx <= 1000, 'a label at the lane edge stays inside it');

  const spaced = lib.layoutLabelRows([
    { xPx: 0, text: 'aa', score: 0.1 }, { xPx: 500, text: 'bb', score: 0.1 },
  ], 1000);
  ok(spaced[0].row === 0 && spaced[1].row === 0, 'words with room share the top row');

  ok(lib.faintWordFits('we', 40) && !lib.faintWordFits('supercalifragilistic', 40),
    'a faint word is printed only where it fits');
  ok(lib.faintWordReachMs([{ ms: 0 }, { ms: 100 }, { ms: 300 }], 0) === 300,
    'with two rows a word has until the one after next');
  ok(lib.featureWords({ loud: 0.5, held: 0, beat: 0.2, line_end: 1, hook: 0 })
    === 'louder 0.50, on the beat 0.20, end of line', 'the tooltip names only what counted');
}

console.log('§3 the lane');
{
  const html = lane();
  ok((html.match(/testbed-lyric-word"/g) ?? []).length === words.length, 'every word is drawn');
  ok((html.match(/testbed-lyric-mark/g) ?? []).length === 1, 'only the emphasized one is marked');
  ok(html.includes('>red<') || html.includes('>red'), 'the word is printed on its mark');
  ok(html.includes('testbed-lyric-guide scene') && html.includes('testbed-lyric-guide flare'),
    'the word events are guide lines through it');
  ok(html.includes('testbed-lyric-guide scene worded') && html.includes('--halo:#c81e1e'),
    'an event a word gives its colour to draws its guide in the word\'s colour');
  ok(!html.includes('testbed-lyric-guide flare worded'), 'one no word reaches does not');
  ok(html.includes('data-ms="20000"') && (html.match(/data-ms="20000"/g) ?? []).length === 2,
    'a word and a scene change at the same time carry the same time');
  ok(!html.includes('testbed-lyric-chip'), 'no chip until a label is matched');
  const chipped = lane({ estimate: [{ ...estimate[0], detail: { ...estimate[0].detail, matched_label: 'Ember' } }] });
  ok(chipped.includes('testbed-lyric-chip') && chipped.includes('Ember'),
    'a matched label has its place on the mark');
  const matched = lane({ metrics: { matches: [{ ref_index: 0, est_index: 0, abs_offset_ms: 5 }] } });
  ok(matched.includes('testbed-lyric-mark matched'), 'a word that landed near one of his marks is tinted');
  ok(!html.includes('<button') && !html.includes('onclick'), 'nothing on the lane can be clicked');
  const zoomed = lane({ view: lib.laneView(100_000, 8000, 30_000) });
  ok((zoomed.match(/testbed-lyric-word"/g) ?? []).length === 1, 'a word outside the zoom is not drawn');
}

console.log('§4 states');
{
  const flagged = lane({
    data: { ...data, clock: { ...clock, flagged: true, max_slip_ms: 1500, note: 'cannot be compared here' } },
  });
  ok(flagged.includes('cannot be compared here'), 'a flagged song says why');
  ok(flagged.includes('testbed-lyrics-lane flagged'), 'and draws its words as flagged');
  ok(!flagged.includes('testbed-lyric-guide'), 'with no guide lines');
  ok(flagged.includes('testbed-lyric-word'), 'but still its words');
  for (const status of ['none', 'stale', 'invalid']) {
    const html = lane({ data: { ...data, status, note: `the ${status} sentence`, words: [] }, estimate: [] });
    ok(html.includes(`the ${status} sentence`) && !html.includes('testbed-lyrics-lane'),
      `"${status}" says which reason it is and draws no lane`);
  }
}

console.log('§5 the roll');
{
  const ev = lib.events;
  const action = (over = {}) => ({
    key: '1-1', first_word: 1, last_word: 1, phrase: 'gold', label: 'gold', ms: 1000, end_ms: 1300,
    source: 'claude', strength: 0.65, match_id: 'g1', pin: null, chance: 0.65, draw: 0.2, won: true,
    chance_words: '', set_names: ['Gold'], set_ids: ['gold'], swatch: '#d9a441', verdict: 'fire',
    why: null, words: '', energy: 0.3, momentary: false, transition_ms: 1800, blocked_by: null, event: null,
    ...over,
  });
  ok(ev.actionChipLabel(action()) === 'gold · held · 65%', 'a chip carries its chance');
  ok(ev.actionChipLabel(action({ source: 'his', strength: 1, chance: 1 })) === 'gold · held',
    'a word that always plays carries none');
  ok(ev.chanceTag(action({ pin: 'never', chance: 0 })) === 'never', 'a Never word says so');
  const out = action({ verdict: 'nothing', why: 'sat_out', won: false, draw: 0.8 });
  ok(ev.satOut(out) && !ev.satOut(action()), 'a word sitting out is told apart');
  ok(ev.summaryWords([action(), out]) === '1 word fires alone, 0 words imprint, 0 words do nothing, 1 word sits out this play',
    'the summary counts the words sitting out on their own');
  ok(ev.summaryWords([action()]).endsWith('0 words do nothing'), 'and says nothing of them when there are none');
  const roll = { state: 'playing', seed: 0x3a7f, tag: '3a7f', started_ms: 0, kept: false, kept_seed: null,
                 playing: true, n_words: 4, n_won: 3 };
  ok(ev.rollWords(roll) === 'This play #3a7f: 3 of 4 words play.', 'the roll line names this play');
  ok(ev.rollWords({ ...roll, kept_seed: 0x3a7f }).includes('your kept roll #3a7f'), 'and says when it is kept');
  ok(ev.rollWords({ ...roll, state: 'sample', playing: false }).startsWith('Sample play #3a7f'), 'a sample says it is one');
  ok(ev.rollWords({ ...roll, state: 'none', seed: null, tag: null }).includes('as if every word plays'),
    'no play: every word as if it plays');
  const n = ev.samplePlayNumber(() => 0.999999999);
  ok(Number.isInteger(n) && n >= 0 && n <= 0xffffffff, 'a sample number is a 32-bit play number');
  const pin = lib.renderPin({ pin: null, chance: 0.35, busy: false, onPin: () => {} });
  ok(pin.includes('Chance 35%') && (pin.match(/aria-pressed="true"/g) ?? []).length === 1
    && /aria-pressed="true"[^>]*>Chance 35%/.test(pin), 'the pin control is on Chance, with its share');
  const never = lib.renderPin({ pin: 'never', chance: 0.35, busy: false, onPin: () => {} });
  ok(/aria-pressed="true"[^>]*>Never/.test(never), 'and on Never when pinned');
}

console.log('§6 word shapes (row W2.3)');
{
  const ev = lib.events;
  const pulse = lib.pulse;
  const strip = lib.strip;
  const action = (over = {}) => ({
    key: '2-2', first_word: 2, last_word: 2, phrase: 'love', label: 'love', ms: 2000, end_ms: 2400,
    source: 'claude', strength: 0.8, match_id: 'l1', pin: null, chance: 0.8, draw: 0.1, won: true,
    chance_words: '', set_names: ['Rose'], set_ids: ['rose'], swatch: '#ff0000',
    shape: 'heart', shape_name: 'Heart', shape_skipped: null,
    form_s: 0.74, hold_s: 0.8, release_s: 1.11,
    verdict: 'shape', why: null, words: '', energy: 0.3, momentary: false,
    transition_ms: 740, blocked_by: null, event: null, ...over,
  });

  // THE CHIP (spec 1): the word and the shape, with the chance tag every
  // other chip carries, and the `shape` class the CSS colours it by.
  ok(ev.actionChipText(action()) === 'love → ♥ heart', 'a drawing word\'s chip is the word and the shape');
  ok(ev.actionChipLabel(action()) === 'love → ♥ heart · 80%', 'with its chance like every chip');
  ok(ev.actionChipText(action({ shape: 'star', shape_name: 'Star' })) === 'love → ★ star'
    && ev.actionChipText(action({ shape: 'diamond', shape_name: 'Diamond' })) === 'love → ◆ diamond',
    'each shape has its own glyph, from the id');
  ok(ev.actionChipText(action({ shape: 'cloud', shape_name: null })) === 'love → cloud',
    'a shape with no glyph yet still prints its name');

  // A SHAPED WORD DOING ITS COLOUR (spec 1's tail): it says why.
  const skippedDrop = action({ verdict: 'imprint', shape_skipped: 'drop_wins',
    event: { id: 'drop-seq:k:drop', kind: 'drop', ms: 2100, label: 'drop 1', away_ms: 100,
             can_carry: true, why_not: null } });
  ok(ev.actionChipText(skippedDrop) === 'love → drop · ♥ skipped: drop',
    'a word that imprints instead says the shape was skipped for the drop');
  const skippedBand = action({ verdict: 'fire', shape_skipped: 'nothing_can_draw' });
  ok(ev.actionChipText(skippedBand) === 'love · held · ♥ skipped: no Words band',
    'and one firing its colour says no scene could draw one');
  ok(ev.skippedShapeTag(action()) === null, 'a word that is drawing wears no skipped tail');
  ok(ev.summaryWords([action(), skippedBand]).startsWith('1 word draws a shape'),
    'the summary counts the words that draw');
  ok(!ev.summaryWords([skippedBand]).includes('draws a shape'),
    'and says nothing of them when none do');

  // THE MARKER (spec 2): the Word events row carries the shape, so it can
  // draw the glyph in place of the colour diamond.
  const [mark] = ev.wordEvents([action()]);
  ok(mark.kind === 'word' && mark.shape === 'heart' && mark.shape_name === 'Heart',
    'a drawing word is a word mark carrying its shape');
  ok(mark.label === '“love” draws the heart shape', 'whose label names the shape');
  ok(strip.shapeGlyph('heart') === '♥' && strip.shapeGlyph(null) === null
    && strip.shapeGlyph('cloud') === null,
    'the glyph comes from the id, and an unknown id falls back to the diamond');
  ok(ev.wordEvents([skippedBand])[0].shape === null,
    'a word doing its colour draws the colour diamond, not a glyph it will not draw');
  ok(strip.kindGlyphSvg('word', null, '#ff0000', 'heart').includes('♥')
    && !strip.kindGlyphSvg('word', null, '#ff0000', null).includes('♥'),
    'the next-event box glyph is the shape\'s character, else the diamond');
  ok(strip.eventLabel({ kind: 'word', rank: null, rank_of: null, word: 'love',
                        shape: 'heart', shape_name: 'Heart' }) === 'Word “love” → heart',
    'and the box\'s hover label names the shape');

  // THE LIVE PULSE (spec 3).
  const push = (over = {}) => ({ verdict: 'shape', phrase: 'love', shape: 'heart',
                                 result: 'applied', landed: true, set_name: null, ...over });
  ok(pulse.pulseWords(push()) === 'love → ♥ heart · drew', 'the pulse says it drew');
  ok(pulse.pulseWords(push({ result: 'held' })) === 'love → ♥ heart · held',
    'that it was held');
  ok(pulse.pulseWords(push({ result: 'fell_back_to_colour' })) === 'love → ♥ heart · colour instead',
    'that it took its colour instead');
  for (const why of ['no_class', 'no_band', 'no_active_scene']) {
    ok(pulse.pulseWords(push({ result: why })) === 'love → ♥ heart · nothing could draw',
      `and that nothing could draw it (${why})`);
  }
  ok(pulse.pulseWords({ verdict: 'fire', phrase: 'roses', shape: null, result: 'jumped',
                        landed: true, set_name: 'Rose' }) === 'roses · Rose',
    'a colour word\'s pulse still names the set that landed');
}

if (failures) {
  console.log(`\nFAIL: ${failures} check(s)`);
  process.exit(1);
}
console.log('\nPASS');
