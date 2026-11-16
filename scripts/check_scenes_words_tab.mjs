/** Executable spec for the Scenes page's WORDS tab (Word Shapes row W2.1):
 * the five-versus-four response-class lists, the preview's shape picker and
 * its ruler marks, the no-knobs Word Shape kind, and the help topic the tab
 * links. No network, no browser — the pure modules are evaluated for real
 * (esbuild bundle, the scripts/check_sung_labels_page.mjs shape) and the
 * three COMPONENT WIRINGS that cannot be read off a pure module are
 * asserted against their own source text:
 *
 *   - ScenesPage's tab list carries 'Words' and mounts ResponseTab on
 *     classes={['word']} with helpTopic="tab-words";
 *   - the TWO TRIGGER PICKERS (SpectraTriggerDialog, PromotionReviewDialog)
 *     still map RESPONSE_CLASSES — the FOUR — so a trigger can never offer
 *     `word`: a sung word is the only way into the Words section
 *     (spectra/models/scene.py's TRIGGER_RESPONSE_CLASSES, proven on the
 *     backend by tests/test_word_shape_contract.py::
 *     test_a_trigger_can_never_name_the_word_class);
 *   - SummaryTab lists SCENE_RESPONSE_CLASSES — the FIVE.
 *
 * It also renders the REAL ResponseTab on the word class with
 * react-dom/server (no browser, no providers but a MemoryRouter for the
 * HelpLinks) and reads the markup: the section title, the hint, the add
 * button, the 💟 card, its ▶ Preview, and the save's inline note.
 *
 * Run: node scripts/check_scenes_words_tab.mjs
 */
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
const web = join(repo, 'spectra/web');
const require = createRequire(join(web, 'package.json'));
const esbuild = require('esbuild');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ok ${msg}`);
  else { console.log(`  FAIL ${msg}`); failures += 1; }
};
const src = (rel) => readFileSync(join(web, 'src', rel), 'utf8');

const entry = `
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import ResponseTab from './spectra/web/src/scenes/tabs/ResponseTab';
export * as types from './spectra/web/src/types';
export * as preview from './spectra/web/src/scenes/tabs/wordShapePreview';
export * as kindOps from './spectra/web/src/scenes/tabs/flareKindOps';
export * as help from './spectra/web/src/help/helpContent';
export function renderTab(props) {
  // HelpLink deep-links through useNavigate, so the tab needs a router
  // around it — nothing else here touches one. React warns once per
  // HelpLink that useLayoutEffect does nothing on the server (true, and
  // irrelevant to markup), so the render is quiet on purpose.
  const warn = console.error;
  console.error = () => {};
  try {
    return renderToStaticMarkup(React.createElement(
      MemoryRouter, null, React.createElement(ResponseTab, props)));
  } finally {
    console.error = warn;
  }
}
`;
const built = await esbuild.build({
  stdin: { contents: entry, resolveDir: repo, loader: 'tsx' },
  bundle: true, format: 'cjs', platform: 'node', write: false, jsx: 'automatic',
  nodePaths: [join(web, 'node_modules')], logLevel: 'error',
});
const out = join(mkdtempSync(join(tmpdir(), 'words-tab-')), 'bundle.cjs');
writeFileSync(out, built.outputFiles[0].text);
const { types, preview, kindOps, help, renderTab } = createRequire(import.meta.url)(out);

console.log('the five sections versus the four a trigger may name');
ok(JSON.stringify(types.RESPONSE_CLASSES) === '["flare","charge","lull","drop"]',
  'RESPONSE_CLASSES is exactly the four trigger classes');
ok(!types.RESPONSE_CLASSES.includes('word'),
  'and never includes word — no trigger may name the Words section');
ok(JSON.stringify(types.SCENE_RESPONSE_CLASSES)
   === '["flare","charge","lull","drop","word"]',
  'SCENE_RESPONSE_CLASSES is the five a scene may declare, word last');
ok(types.WORD_RESPONSE_CLASS === 'word', 'the word class is named once');
for (const file of ['timeline/components/SpectraTriggerDialog.tsx',
                    'testbed/components/PromotionReviewDialog.tsx']) {
  const text = src(file);
  ok(/RESPONSE_CLASSES\.map\(\(c\) => <option/.test(text),
    `${file} offers RESPONSE_CLASSES in its class picker`);
  ok(!text.includes('SCENE_RESPONSE_CLASSES'),
    `${file} never reaches for the five-class list`);
}
ok(src('scenes/tabs/SummaryTab.tsx').includes('SCENE_RESPONSE_CLASSES.map'),
  'SummaryTab lists all five of a scene\'s sections');

console.log('\nthe Words tab itself');
const page = src('scenes/ScenesPage.tsx');
ok(/'Charges\/Lulls\/Drops', 'Words',/.test(page),
  'the tab list carries Words, after Charges/Lulls/Drops (the plan\'s own order)');
ok(/classes=\{\['word'\]\}[\s\S]{0,80}helpTopic="tab-words"/.test(page),
  'the Words tab mounts ResponseTab on the word class, help topic tab-words');
ok(page.includes('scene.responses.word?.bands.length'),
  'its badge is the Words band count');
ok(page.includes('res?.warnings ?? []'),
  'the save\'s advisory warnings are kept, not dropped');
const tab = src('scenes/tabs/ResponseTab.tsx');
ok(tab.includes('warningsForKind(warnings, k.name)'),
  'each kind card shows the warnings that name it');
ok(tab.includes('newWordShapeKind'),
  'the Words tab can declare a Word Shape kind');

console.log('\nthe Word Shape kind has no knobs');
const kind = kindOps.newWordShapeKind([]);
ok(kind.type === 'word_shape' && kind.name === 'Word Shape', 'declared by type and name');
ok(kind.jump === null && Object.keys(kind.params).length === 0
   && kind.gain === 1 && kind.hold_ms === null,
  'no jump, no params, gain 1, no hold — the model refuses all four');
ok(kind.enabled === true && kind.trigger_offset_ms === 0,
  'it keeps enabled and trigger_offset_ms (0: inert in the Words section)');
ok(kindOps.newWordShapeKind(['Word Shape']).name === 'Word Shape (2)',
  'a second one gets the engine\'s own "(2)" suffix');

console.log('\nthe preview\'s shape picker');
const rows = [{ id: 'heart', name: 'Heart', labels: [] },
               { id: 'star', name: 'Star', labels: [] },
               { id: 'diamond', name: 'Diamond', labels: [] }];
const options = preview.shapePickerOptions(rows);
ok(options.map((o) => o.id).join() === 'heart,star,diamond',
  'the options are the library\'s rows, in its own declaration order');
ok(preview.shapePickerOptions(undefined).length === 0, 'no library, no options');
ok(preview.shapePickerOptions([{ id: '', name: 'x', labels: [] }]).length === 0,
  'a row with no id is not an option');
ok(preview.pickDefaultShape(options) === 'heart', 'heart is preselected');
ok(preview.pickDefaultShape(options.slice(1)) === 'star',
  'with no heart in the library, the first shape it does have');
ok(preview.pickDefaultShape([]) === null,
  'and nothing to pick sends no shape (the server picks its own default)');
ok(preview.PREFERRED_PREVIEW_SHAPE === 'heart',
  'the preferred id matches scene_response.PREVIEW_SHAPE');

console.log('\nthe ruler\'s three marks');
const timeline = (over = {}) => ({
  kind_name: 'Word Shape', kind_type: 'word_shape', intensity: 0.8, result: 'applied',
  animation_start_s: null, animation_end_s: null, duration_s: 6,
  animation_anchor_s: 2, trigger_mark_s: 2, lead_ms: 540, anchor_rule: 'switch_end',
  attached_classes: ['word'], fire_at_s: 1.46, effect_animation_ms: 3390,
  word_shape: { shape: 'heart', form_s: 0.54, hold_s: 1.2, release_s: 0.81 },
  writes: [], ...over,
});
const marks = preview.wordShapeMarks(timeline());
ok(marks !== null, 'a word_shape timeline has marks');
ok(marks.start_s === 1.46 && marks.word_s === 2,
  'the write is read from fire_at_s and the word from the trigger mark');
ok(marks.spans.map((s) => s.label).join() === 'forms,holds,releases',
  'the three spans are his words, in order');
ok(marks.spans[0].from_s === marks.start_s && marks.spans[0].to_s === marks.word_s,
  'FORMS runs from the write to the word — it completes ON the word');
ok(Math.abs(marks.hold_end_s - 3.2) < 1e-9 && Math.abs(marks.end_s - 4.01) < 1e-9,
  'holds then releases run past the word by the room\'s own two times');
ok(marks.needed_duration_s > marks.end_s,
  'the ruler it needs is a little longer than the whole envelope');
ok(preview.wordShapeMarks(timeline({ kind_type: 'momentary' })) === null,
  'every other kind type keeps the ordinary start/end markers');
ok(preview.wordShapeMarks(timeline({ word_shape: null })) === null,
  'and so does a word_shape timeline from a server that sent no envelope');
ok(preview.wordShapeMarks(null) === null, 'no timeline, no marks');
const zero = preview.wordShapeMarks(timeline({
  word_shape: { shape: 'star', form_s: 0, hold_s: 0, release_s: 0 }, fire_at_s: 2 }));
ok(zero.spans.length === 0, 'a zero envelope draws no spans rather than slivers');
ok(preview.wordShapeSentence(marks, 'Heart').startsWith('The Heart forms over 540 ms'),
  'the sentence reads the envelope out loud');

console.log('\nthe save\'s advisory notes');
const warnings = [
  "flare kind 'Word Shape' is a word_shape — only the Words section fires a shape, so its attachment to flare does nothing",
  "flare kind 'Spin' carries trigger_offset_ms -250 and is attached to the Words section, which fires its band on the word itself — the offset is not applied there",
];
ok(preview.warningsForKind(warnings, 'Word Shape').length === 1,
  'a kind card shows the note that names it');
ok(preview.warningsForKind(warnings, 'Spin')[0].includes('not applied there'),
  'and the offset note lands on the kind carrying the offset');
ok(preview.warningsForKind(warnings, 'Nobody').length === 0, 'and nothing else');
ok(preview.warningsNamingNoKind(warnings, ['Word Shape', 'Spin']).length === 0,
  'every note here names a declared kind');
ok(preview.warningsNamingNoKind(warnings, ['Spin']).length === 1,
  'a note naming no declared kind is still shown, once, rather than dropped');
ok(preview.warningsForKind(undefined, 'Word Shape').length === 0,
  'no save yet, no notes');

console.log('\nthe real Words tab, rendered');
// The REAL component (react-dom/server, no browser): ResponseTab holds no
// data hooks of its own — useToast is a plain context with a default and
// the flare clipboard read is try/caught — so it renders as-is.
const sceneWith = (responses, kinds) => ({
  id: 's1', name: 'Scene', labels: [], devices: [], flare_kinds: kinds,
  responses, update_kind: null,
  color_journey: { mode: 'inherit', pace_factor: 1, journey: null },
  choreography: { enabled: false, transition_ms: 800, transition_mode: 'Add', anchor_frac: 0.45 },
  entry_ramp_ms: 0, trigger_offset_ms: 0, accept_all_sets: true, accepted_set_ids: [],
  display_availability: 'default', preferred_color_set_mode: 'default', disabled: false,
  dwell_curve: null, drop_shock_enabled: true, drop_timing_offset_ms: null,
});
const band = { intensity_min: 0, intensity_max: 1, curve: 'linear', gain: 1,
                param_patch: {}, kinds: { 'Word Shape': 1 }, kind_lanes: {} };
const bare = renderTab({ scene: sceneWith({}, []), setScene: () => {},
                         classes: ['word'], helpTopic: 'tab-words' });
ok(bare.includes('Words'), 'the section is titled Words');
ok(bare.includes('respond to words'),
  'a scene with no Words section offers to add one');
ok(bare.includes('A sung word that reaches a shape fires this section'),
  'and the hint says what fires it — and that nothing else does');
ok(bare.includes('💟 + Word Shape kind'),
  'the Words tab offers to declare the kind');
const full = renderTab({
  scene: sceneWith({ word: { bands: [band], reroll_dice: false, color_set_jump: false } },
                   [kindOps.newWordShapeKind([])]),
  setScene: () => {}, classes: ['word'], helpTopic: 'tab-words',
  warnings: [warnings[0]],
});
ok(full.includes('💟'), 'the kind card carries the Word Shape glyph');
ok(full.includes('word_shape'), 'and names its type');
ok(full.includes('▶ Preview'), 'with the Preview button that opens the picker');
ok(full.includes('shape forms, holds and releases'), 'and says what it does');
ok(full.includes('only the Words section fires a shape'),
  'the save\'s note about this kind is shown on its card');
ok(!full.includes('respond to words'),
  'a scene that HAS the section is not asked to add it again');
const flares = renderTab({ scene: sceneWith({}, []), setScene: () => {},
                           classes: ['flare'], helpTopic: 'tab-flares' });
ok(!flares.includes('💟 + Word Shape kind'),
  'the Flares tab never offers to declare one — the type does nothing there');
ok(!flares.includes('respond to words') && flares.includes('respond to flares'),
  'and it still offers only its own section');

console.log('\nthe help topics');
const ids = new Set();
for (const section of help.HELP_SECTIONS) {
  ids.add(section.id);
  for (const e of section.entries ?? []) ids.add(e.id);
  for (const sub of section.subsections ?? []) {
    ids.add(sub.id);
    for (const e of sub.entries ?? []) ids.add(e.id);
  }
}
for (const topic of ['tab-words', 'word-shapes', 'flare-kinds', 'flare-kind-edit-box']) {
  ok(ids.has(topic), `"${topic}" is a real section/entry in HELP_SECTIONS`);
}
const entryById = (id) => {
  for (const section of help.HELP_SECTIONS) {
    for (const e of section.entries ?? []) if (e.id === id) return e;
    for (const sub of section.subsections ?? []) {
      for (const e of sub.entries ?? []) if (e.id === id) return e;
    }
  }
  return null;
};
const words = entryById('tab-words');
ok((words.body ?? []).length >= 2, 'tab-words says at least two sentences');
ok((words.body ?? []).join(' ').includes('fifth response section'),
  'and names what the section is');
ok((entryById('flare-kinds').body ?? []).join(' ').includes('WORD SHAPE'),
  'flare-kinds lists the new type');

if (failures) {
  console.log(`\n${failures} FAILURE(S)`);
  process.exit(1);
}
console.log('\nALL OK');
