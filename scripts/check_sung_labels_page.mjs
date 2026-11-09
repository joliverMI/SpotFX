/** Executable spec for the Sung labels page and the Word matches row's pure
 * parts: spectra/web/src/sunglabels/sungLabels.ts and testbed/lyricMatches.ts,
 * and the real LyricMatchesRow component rendered with react-dom/server. No
 * network, no browser (scripts/render_sung_labels.py does the browser half).
 *
 * Run: node scripts/check_sung_labels_page.mjs
 */
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
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
import LyricMatchesRow from './spectra/web/src/testbed/components/LyricMatchesRow';
export * as labels from './spectra/web/src/sunglabels/sungLabels';
export * as matches from './spectra/web/src/testbed/lyricMatches';
export { wholeSong } from './spectra/web/src/testbed/lyricsLane';
export function renderRow(props) { return renderToStaticMarkup(React.createElement(LyricMatchesRow, props)); }
`;
const built = await esbuild.build({
  stdin: { contents: entry, resolveDir: repo, loader: 'tsx' },
  bundle: true, format: 'cjs', platform: 'node', write: false, jsx: 'automatic',
  nodePaths: [join(repo, 'spectra/web/node_modules')], logLevel: 'error',
});
const out = join(mkdtempSync(join(tmpdir(), 'sung-labels-')), 'bundle.cjs');
writeFileSync(out, built.outputFiles[0].text);
const lib = createRequire(import.meta.url)(out);

console.log('the correction page');
const card = (id, over = {}) => ({
  id, name: id, kind: 'set', disabled: false, swatch: '#f00', has_colours: true, labels: [],
  meanings: { things: [], moods: [], places: [] }, drafted_ms: null, draft_model: null, ...over,
});
const a = card('a', { labels: [{ text: 'red', source: 'seed' }] });
const b = card('b', { drafted_ms: 5, meanings: { things: [{ text: 'volcano', source: 'claude' }], moods: [], places: [] } });
const c = card('c', { has_colours: false });
const { labels, matches } = lib;

ok(labels.filterCards([a, b], 'VOLC', false).map((x) => x.id).join() === 'b', 'search reaches meanings');
ok(labels.filterCards([a, b, c], '', true).map((x) => x.id).join() === 'a', 'the filter leaves only sets waiting for a draft');
ok(labels.undraftedIds([a, b, c]).join() === 'a', 'a card with no colours is not waiting for a draft');
ok(labels.draftableIds([a, b, c]).join() === 'a,b', 'a re-draft leaves a card with no colours out');
ok(JSON.stringify(labels.batches([1, 2, 3, 4, 5], 2)) === '[[1,2],[3,4],[5]]', 'drafting goes a batch at a time');
ok(labels.draftButtonWords(1, 3) === 'Draft meanings for 1 colour set', 'the button says how many are waiting');
ok(labels.draftButtonWords(0, 3) === 'Draft all 3 again', 'and offers a re-draft when none are');
ok(labels.draftButtonWords(5, 10, 2) === 'Retry 2 colour sets that failed', 'a pending retry takes priority over either other wording');

console.log('drafting through a failed batch');
{
  const calls = [];
  const draftBatch = async (ids) => {
    calls.push(ids);
    if (ids.includes('c')) { const err = new Error('boom'); err.status = 502; throw err; }
    return { drafted: ids.length, ids, skipped: [] };
  };
  const outcome = await labels.runDraftQueue(['a', 'b', 'c', 'd', 'e'], 2, draftBatch);
  ok(calls.length === 3, 'a failed batch does not stop the ones after it');
  ok(outcome.draftedIds.join() === 'a,b,e', 'the batches that succeeded are reported drafted');
  ok(outcome.failedIds.join() === 'c,d', 'only the failed batch\'s ids are reported failed, not redrafted ones');
  ok(labels.isDraftTimeoutError(outcome.errors[0]), 'a 502 is recognised as a timeout, not a rejection');
  const msg = labels.draftOutcomeMessage(outcome, 5);
  ok(/3 of 5/.test(msg) && /took too long/.test(msg) && !/spectra\.service/.test(msg),
     `the summary is truthful and never blames the process (${msg})`);
  ok(labels.draftOutcomeMessage({ draftedIds: ['a'], failedIds: [], errors: [] }, 1) === null,
     'no failures means no message');
}
{
  const draftBatch = async (ids) => ({ drafted: 0, ids: [], skipped: ids });
  const outcome = await labels.runDraftQueue(['x'], 4, draftBatch);
  ok(outcome.failedIds.join() === 'x' && outcome.errors.length === 0, 'a rejected (not errored) batch is still a failure');
  ok(/some sets could not be drafted/.test(labels.draftOutcomeMessage(outcome, 1)), 'a plain rejection gets a plain reason');
}

console.log('the matches');
const m = (over) => ({
  id: 'g', source: 'claude', provenance: 'claude_guess', first_word: 3, last_word: 4, phrase: 'red light',
  label: 'red', confidence: 0.9, why: 'x', targets: [{ kind: 'color_set', id: 'c', name: 'Blood Red', swatch: '#f00' }],
  n_targets: 1, targets_missing: 0, ms: 20_000, end_ms: 21_000, score: 0.5, ...over,
});
ok(matches.chipText(m({})) === 'red light → red', 'a chip says the words and what they mean');
ok(matches.chipText(m({ phrase: 'Red', label: 'red' })) === 'Red', 'a word that is its label prints once');
ok(matches.isEmphasized(m({ score: 0.5 }), 0.6), 'a match at a high enough score is emphasized');
ok(!matches.isEmphasized(m({ score: 0.3 }), 0.6), 'below the sensitivity it is not');
ok(matches.provenanceWords(m({})) === "Claude's guess, confidence 0.90", "a guess says it is one");
ok(matches.provenanceWords(m({ source: 'his', confidence: null })) === 'Added by you', 'and his says it is his');
ok(matches.targetsWords(m({ n_targets: 4 })) === 'Blood Red, and 3 more', 'it says who it would reach');
ok(/deleted/.test(matches.targetsWords(m({ targets: [], n_targets: 0, targets_missing: 1 }))), 'and says when the target is gone');

const view = lib.wholeSong(100_000);
const narrow = matches.layoutMatches(
  [m({ id: 'weak', confidence: 0.6, ms: 20_000 }), m({ id: 'strong', confidence: 0.95, ms: 20_100 }),
   m({ id: 'third', confidence: 0.7, ms: 20_200 }), m({ id: 'mine', source: 'his', confidence: null, ms: 20_300 })],
  view, 200);
const placed = Object.fromEntries(narrow.map((c) => [c.match.id, c.placement]));
ok(placed.mine && placed.strong, 'when crowded, his and the strongest guess keep their text');
ok(placed.third === null && placed.weak === null, 'and the weakest give way');

const words = [{ word: 'a', ms: 1000, end_ms: 1100 }, { word: 'b', ms: 50_000, end_ms: 50_100 }];
ok(matches.pickableWords(words, { startMs: 40_000, endMs: 60_000 }).map((p) => p.index).join() === '1',
   'the add panel offers the words in view, with their place in the song');
let pick = { first: null, last: null };
pick = matches.nextPick(pick, 5);
ok(pick.first === 5 && pick.last === 5, 'the first tap starts a phrase');
pick = matches.nextPick(pick, 7);
ok(pick.first === 5 && pick.last === 7, 'a later tap extends it');
pick = matches.nextPick(pick, 6);
ok(pick.first === 6 && pick.last === 6, 'a third tap starts again');
ok(matches.pickedPhrase([{ word: 'x' }, { word: 'red' }, { word: 'light' }], { first: 1, last: 2 }) === 'red light', 'it reads back the phrase');

const nowMs = 1_000_000_000;
ok(matches.readingWords({ state: 'none', reading: null, matches: [] }, nowMs) === 'Claude has not read this song.', 'no reading says so');
const fresh = matches.readingWords({ state: 'fresh', reading: { at_ms: nowMs - 180_000 }, matches: [m({})] }, nowMs);
ok(fresh === 'Read 3 min ago, 1 guess.', `a fresh reading says when (${fresh})`);
ok(/labels have changed/.test(matches.readingWords({ state: 'labels_changed', reading: { at_ms: nowMs }, matches: [] }, nowMs)),
   'a stale one says the labels changed');
ok(matches.readButtonWords('none') === 'Read this song' && matches.readButtonWords('fresh') === 'Read again', 'the button matches');

console.log('the row');
const row = lib.renderRow({ matches: [m({ source: 'his', confidence: null, id: 'h1' }), m({ id: 'g2', ms: 40_000, end_ms: 41_000, score: 0.1 })],
                            view, sensitivity: 0.6, selectedId: 'g2', onSelect: () => {} });
ok(row.includes('testbed-match his'), 'his chip is marked');
ok(/testbed-match claude[^"]*dim[^"]*selected/.test(row), 'a guess below the sensitivity is dimmed, and selection shows');
ok(row.includes('red light → red'), 'a chip prints its words');
ok(row.includes('Word matches'), 'the row is labelled');
const empty = lib.renderRow({ matches: [], view, sensitivity: 0.6, selectedId: null, onSelect: () => {} });
ok(empty.includes('No matches here'), 'an empty row says so');

console.log('the wiring');
const help = readFileSync(join(repo, 'spectra/web/src/help/helpContent.ts'), 'utf8');
const page = readFileSync(join(repo, 'spectra/web/src/sunglabels/SungLabelsPage.tsx'), 'utf8');
const section = readFileSync(join(repo, 'spectra/web/src/testbed/components/LyricMatchesSection.tsx'), 'utf8');
for (const topic of ['sung-labels', 'sung-labels-page', 'sung-labels-reading']) {
  ok(help.includes(`id: '${topic}'`) && page.includes(`topic="${topic}"`), `help topic ${topic} exists and is linked from the page`);
}
ok(help.includes("id: 'testbed-lyric-matches'") && section.includes('topic="testbed-lyric-matches"'), 'the lane\'s help topic exists and is linked');
const routes = readFileSync(join(repo, 'spectra/web/src/help/routeTopics.ts'), 'utf8');
ok(routes.includes("['/sung-labels', 'sung-labels']"), 'the page\'s "?" deep-links to its section');

console.log(failures ? `\nFAIL: ${failures}` : '\nPASS');
process.exit(failures ? 1 : 0);
