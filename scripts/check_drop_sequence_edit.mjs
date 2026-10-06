/** No-DOM proof for EDITING drop sequences on the Timeline (drop-detection
 * plan, phase 4): spectra/web/src/timeline/dropEdit.ts (snap, step, the
 * order clamp, the whole-sequence move, the ghost, the add placement, the
 * undo stack, the undo/redo single-flight guard and the keyboard map) and
 * what the canvas layer draws while a hand is on it
 * (spectra/web/src/timeline/canvas/dropSeqLayer.ts — the ghost, the lit
 * snap target, the add preview), all transpiled from the REAL modules with
 * esbuild. Synthetic data; never his storage.
 *
 * Run: node scripts/check_drop_sequence_edit.mjs
 */
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const WEB = path.join(REPO, 'spectra/web');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const tmp = mkdtempSync(path.join(tmpdir(), 'drop-seq-edit-'));
const build = (rel, name) => {
  const out = path.join(tmp, name);
  execFileSync('npx', ['esbuild', path.join(WEB, rel), '--bundle', '--format=esm',
    '--platform=neutral', '--log-level=warning', `--outfile=${out}`], { cwd: WEB, stdio: ['ignore', 'ignore', 'inherit'] });
  return out;
};
const E = await import(build('src/timeline/dropEdit.ts', 'dropEdit.mjs'));
const v = await import(build('src/timeline/dropSequences.ts', 'dropSequences.mjs'));
const L = await import(build('src/timeline/canvas/dropSeqLayer.ts', 'dropSeqLayer.mjs'));

const rails = {
  status: 'ok', beat_ms: 500, captured_from_ms: 0,
  // a hard spike at 48000, a faint one at 47940, one at 41000
  spikes: [[48000, 0.9], [47940, 0.1], [41000, 0.5]],
  // beats every 500 ms from 30000, a downbeat every 4
  beats: Array.from({ length: 50 }, (_, i) => [30000 + i * 500, i % 4 === 0 ? 1 : 0]),
};

console.log('§1 snapping: each handle snaps to what it belongs on');
let g = E.snapHandle('drop', 47990, rails, 100);
ok(g.ms === 48000 && g.what === 'bass spike' && g.rail === 'spike', 'the drop snaps to the hard spike, not the faint nearer one');
g = E.snapHandle('drop', 47750, rails, 100);
ok(g.rail === 'free' && g.ms === 47760, 'the drop never snaps to a beat — nothing near: free on the 20 ms grid');
g = E.snapHandle('lull', 40990, rails, 60);
ok(g.ms === 41000 && g.rail === 'spike', 'the lull takes a spike');
g = E.snapHandle('lull', 40520, rails, 60);
ok(g.ms === 40500 && g.what === 'beat', 'or a beat');
g = E.snapHandle('charge', 32020, rails, 100);
ok(g.ms === 32000 && g.what === 'downbeat', 'the charge prefers a downbeat');
g = E.snapHandle('charge', 32480, rails, 100);
ok(g.ms === 32500 && g.what === 'beat', 'else a beat');
g = E.snapHandle('drop', 47985, rails, 100, true);
ok(g.ms === 47980 && g.rail === 'free', 'Alt places freely on the 20 ms grid');
ok(E.snapHandle('drop', 47990, null, 100).rail === 'free', 'no rails: free placement, never a throw');
ok(Math.abs(E.snapRadiusMs(1000, 0, 20000) - 280) < 1e-9, 'the snap radius is 14 px at the current zoom');

console.log('§2 stepping with ← → walks the handle\'s own rail');
g = E.stepHandle('drop', 41000, 1, rails);
ok(g.ms === 47940, 'the drop steps spike to spike');
ok(E.stepHandle('drop', 48000, 1, rails) === null, 'nothing further: no step');
g = E.stepHandle('lull', 41000, -1, rails);
ok(g.ms === 40500 && g.what === 'beat', 'the lull steps through spikes and beats');
g = E.stepHandle('charge', 32000, 1, rails);
ok(g.ms === 32500, 'the charge steps beat to beat');
g = E.stepHandle('charge', 32000, -1, rails, true);
ok(g.ms === 31990 && g.what.includes('10 ms'), 'Shift nudges 10 ms');

console.log('§3 order is kept: charge < lull < drop, 200 ms apart, never pushed');
const t = { charge: 35000, lull: 41000, drop: 48000 };
ok(E.clampHandle(t, 'lull', 47950) === 47800, 'a lull dragged into the drop stops 200 ms short');
ok(E.clampHandle(t, 'lull', 34000) === 35200, 'and 200 ms after the charge');
ok(E.clampHandle(t, 'charge', 42000) === 40800, 'a charge stops 200 ms before the lull');
ok(E.clampHandle(t, 'drop', 40000) === 41200, 'a drop stops 200 ms after the lull');
ok(E.clampHandle({ charge: null, lull: null, drop: 48000 }, 'drop', 100) === 100, 'a bare drop moves freely');
ok(E.clampHandle({ charge: 35000, lull: null, drop: 48000 }, 'charge', 47950) === 47800, 'a charge with no lull stops before the drop');
ok(E.clampHandle({ charge: null, lull: null, drop: 100 }, 'drop', -50) === 0, 'never before the song starts');

console.log('§4 Shift-drag moves the whole sequence; one save carries only what changed');
const sh = E.shiftTimes(t, 500);
ok(sh.charge === 35500 && sh.lull === 41500 && sh.drop === 48500, 'every handle by the same amount');
const early = E.shiftTimes({ charge: 300, lull: null, drop: 900 }, -1000);
ok(early.charge === 0 && early.drop === 600 && early.lull === null, 'held at the song start, absent stays absent');
const ch = E.changedHandles(t, { ...t, lull: 41500 });
ok(JSON.stringify(ch) === '{"lull":41500}', 'only the moved handle is saved');
ok(Object.keys(E.changedHandles(t, t)).length === 0, 'a click that moved nothing saves nothing');

console.log('§5 the ghost: what is drawn while a hand is on it');
const view = (o) => ({
  key: `drop:${o.drop_ms}`, origin: 'detected', state: 'confident', charge_ms: null, lull_ms: null,
  drop_ms: 0, tier: 'confident', detected_key: `drop:${o.drop_ms}`, moved: {},
  lull_off: false, charge_off: false, score: 1.2, break_beats: 3.3, step: 0.65, rise: 0.7,
  path: 'step', loud_before: true, capped: false, notes: [], needs_review: false,
  detection_lost: false, matches: [], his_marks_near: [], ...o,
  auto: o.auto ?? { charge_ms: o.charge_ms ?? null, lull_ms: o.lull_ms ?? null, drop_ms: o.drop_ms },
});
const resp = {
  uri: 'spotify:track:x', status: 'ok', reason: null,
  detector: { version: '1', stamp: 's', detected_at: 1, confident_score: 1, suggested_score: 0.7 },
  song: { tempo_bpm: 120, beat_ms: 500, captured_from_ms: 0, captured_to_ms: 200000, duration_ms: 200000 },
  sequences: [
    view({ drop_ms: 48000, lull_ms: 41000, charge_ms: 35000 }),
    { ...view({ drop_ms: 90000, lull_ms: 88000, state: 'added' }), key: 'added:a1', origin: 'added', auto: null, tier: null },
  ],
  excluded: [], counts: {}, authored: [], authored_lone: [],
};
let seqs = v.buildDisplay(resp, { showDismissed: false, analysedApplies: true });
const ghosted = E.withGhost(seqs, { key: 'drop:48000', times: { charge: 35000, lull: 41500, drop: 48000 } });
const gs = ghosted.find((s) => s.key === 'drop:48000');
ok(gs.lull === 41500 && gs.look === 'edited', 'a moved detection reads as edited, as it will once saved');
ok(gs.analysisHad.lull === 41000 && gs.analysisHad.drop === undefined, 'with the dotted line where the analysis had the moved handle only');
ok(seqs.find((s) => s.key === 'drop:48000').lull === 41000, 'the saved list itself is untouched');
const back = E.withGhost(seqs, { key: 'drop:48000', times: { charge: 35000, lull: 41000, drop: 48000 } });
ok(back.find((s) => s.key === 'drop:48000').look === 'confident', 'dragged back onto the analysis: not edited');
const ga = E.withGhost(seqs, { key: 'added:a1', times: { charge: null, lull: 87000, drop: 90000 } }).find((s) => s.key === 'added:a1');
ok(ga.look === 'added' && ga.lull === 87000, 'an added one stays "added"');
ok(E.withGhost(seqs, null) === seqs, 'no ghost: the very same list');
ok(E.editable(seqs[0]) && !E.editable({ look: 'mine', fire: 'fires' })
  && !E.editable({ look: 'dismissed', fire: 'dismissed' }) && !E.editable({ look: 'confident', fire: 'stands_down' }),
  'his own triggers, a dismissed one and one standing down are not dragged here');

console.log('§6 adding a drop goes to the nearest bass spike');
g = E.addPlacement(47100, rails, 500);
ok(g.ms === 47940 && g.rail === 'spike', 'the nearest spike within two beats');
g = E.addPlacement(60000, rails, 500);
ok(g.rail === 'free' && g.ms === 60000, 'none that near: exactly where clicked');

console.log('§7 undo / redo: one step per save, at least 20 kept, a new edit clears redo');
const ed = (n) => ({ overrides: { [`drop:${n}`]: { state: 'confirmed' } }, added: [] });
const entry = (i) => ({ label: `e${i}`, before: ed(i), after: ed(i + 1), revBefore: `r${i}`, revAfter: `r${i + 1}`, key: null });
let st = E.EMPTY_STACKS;
for (let i = 0; i < 60; i += 1) st = E.pushEdit(st, entry(i));
ok(st.undo.length === E.UNDO_DEPTH && E.UNDO_DEPTH >= 20 && st.undo[0].label === 'e10', `capped at ${E.UNDO_DEPTH}, oldest dropped`);
ok(E.pushEdit(st, { ...entry(99), revAfter: 'r99' }) === st, 'a save that changed nothing adds no step');
st = E.afterUndo(st);
ok(st.redo.length === 1 && st.redo[0].label === 'e59' && st.undo.length === E.UNDO_DEPTH - 1, 'undo moves the step to redo');
const u = E.undoRequest(st.redo[0]);
ok(u.edits === st.redo[0].before && u.expect === 'r60', 'an undo puts "before" back, only if his edits are still "after"');
const r = E.redoRequest(st.redo[0]);
ok(r.edits === st.redo[0].after && r.expect === 'r59', 'a redo the other way round');
st = E.afterRedo(st);
ok(st.redo.length === 0 && st.undo[st.undo.length - 1].label === 'e59', 'redo moves it back');
st = E.afterUndo(st);
st = E.pushEdit(st, entry(200));
ok(st.redo.length === 0, 'a new edit clears redo');

console.log('§8 the keyboard');
const k = (key, mods = {}) => E.dropKeyAction({ key, ...mods });
ok(k('c').kind === 'select' && k('c').handle === 'charge' && k('L').handle === 'lull' && k('d').handle === 'drop', 'C L D pick a handle');
ok(k('ArrowRight').dir === 1 && !k('ArrowRight').nudge && k('ArrowLeft', { shiftKey: true }).nudge, '← → step, Shift nudges');
ok(k('Enter').kind === 'confirm' && k('Delete').kind === 'dismiss' && k('Backspace').kind === 'dismiss', 'Enter confirms, Delete dismisses');
ok(k('n').dir === 1 && k('p').dir === -1, 'N P next/previous sequence');
ok(k('z', { ctrlKey: true }).kind === 'undo' && k('y', { metaKey: true }).kind === 'redo'
  && k('z', { ctrlKey: true, shiftKey: true }).kind === 'redo', 'Ctrl/Cmd+Z undo, Ctrl+Y or Shift+Z redo');
ok(k('Escape').kind === 'escape', 'Escape lets go');
ok(k('q') === null && k('1') === null && k('c', { altKey: true }) === null && k('a', { ctrlKey: true }) === null,
  'every other key is left to the page (palette keys, Ctrl+A)');
ok(E.editErrorText(new Error('POST /spectra/api/drop-sequences/handles → 422: lull must sit at least 200 ms before drop'))
  === 'lull must sit at least 200 ms before drop', 'a refused edit shows the server\'s own sentence');

console.log('§9 the layer while a hand is on it');
function fakeCtx() {
  const calls = [];
  const rec = (name) => (...a) => { calls.push([name, ...a]); };
  return {
    calls, globalAlpha: 1, fillStyle: '', strokeStyle: '', lineWidth: 1, font: '', textAlign: 'left',
    save: rec('save'), restore: rec('restore'), beginPath: rec('beginPath'), closePath: rec('closePath'),
    moveTo: rec('moveTo'), lineTo: rec('lineTo'), fill: rec('fill'), stroke: rec('stroke'),
    fillRect: (...a) => { calls.push(['fillRect', ...a, String(calls.fill ?? '')]); },
    rect: rec('rect'), clip: rec('clip'), arc: rec('arc'),
    roundRect: rec('roundRect'), setLineDash: rec('setLineDash'),
    fillText: (...a) => { calls.push(['fillText', ...a]); },
    measureText: (s) => ({ width: String(s).length * 6 }),
    createLinearGradient: () => ({ addColorStop: () => {} }),
  };
}
const W = 1000;
const win = { startMs: 30000, endMs: 55000 };
const frame = (extra) => {
  const ctx = fakeCtx();
  const span = win.endMs - win.startMs;
  return {
    ctx, w: W, h: 300, mainH: 260, railH: 36, stripH: 21, stripCount: 0, win,
    timeToX: (ms) => ((ms - win.startMs) / span) * W,
    xToTime: (x) => win.startMs + (x / W) * span,
    nowMs: null, view: {},
    data: { dropSeq: { seqs, rails, selectedKey: 'drop:48000', hover: null, capturedFromMs: 0, beatMs: 500, ...extra } },
  };
};
const live = { current: { ghost: { key: 'drop:48000', times: { charge: 35000, lull: 41500, drop: 48000 } },
  guide: { ms: 41000, what: 'bass spike', rail: 'spike' }, addAt: null } };
let f = frame({ live, selectedHandle: 'lull' });
let threw = null;
for (const layer of [L.dropSeqRailBand, L.dropSeqBody, L.dropSeqRail]) {
  try { if (layer.visible(f)) layer.draw(f); } catch (e) { threw = `${layer.id}: ${e}`; }
}
ok(threw === null, threw ?? 'every part draws with a ghost and a snap target');
const xs = (ms) => f.timeToX(ms);
const lullLine = f.ctx.calls.filter((c) => c[0] === 'moveTo' && Math.abs(c[1] - xs(41500)) < 0.01);
ok(lullLine.length > 0, 'the lull is drawn where the ghost has it');
ok(f.ctx.calls.some((c) => c[0] === 'fillText' && String(c[1]).startsWith('snap: bass spike')), 'the snap target is named on the graph');
ok(f.ctx.calls.some((c) => c[0] === 'fillRect' && Math.abs(c[1] - (xs(41000) - 1.5)) < 0.01 && c[3] === 3),
  'the spike it snapped to lights up on the rail');
ok(f.ctx.calls.some((c) => c[0] === 'arc' && Math.abs(c[1] - xs(41500)) < 0.01 && c[3] === 12), 'the selected handle (the lull) is ringed');
// the hit test follows the ghost too
const hit = L.dropSeqBody.hitTest(xs(41500), 120, f);
ok(hit && hit.kind === 'drop-seq' && hit.handle === 'lull', 'the moved line is where a press finds it');
const chip = L.dropSeqRail.hitTest(xs(48000), 17, f);
ok(chip && chip.handle === 'drop' && !chip.chip, 'the drop star is a handle, not a chip');
f = frame({ adding: true, live: { current: { ghost: null, guide: null, addAt: { ms: 47940, what: 'bass spike', rail: 'spike' } } } });
threw = null;
for (const layer of [L.dropSeqRailBand, L.dropSeqBody, L.dropSeqRail]) {
  try { if (layer.visible(f)) layer.draw(f); } catch (e) { threw = `${layer.id}: ${e}`; }
}
ok(threw === null, threw ?? 'adding draws');
ok(f.ctx.calls.some((c) => c[0] === 'fillText' && String(c[1]).startsWith('click a bass spike')), 'adding says what to do');
ok(f.ctx.calls.some((c) => c[0] === 'fillText' && String(c[1]).startsWith('add a drop: bass spike')), 'and where the drop would go');
ok(L.dropSeqBody.hitTest(xs(48000), 120, f) === null && L.dropSeqRail.hitTest(xs(48000), 17, f) === null,
  'while adding, a press on a sequence adds rather than grabs');

console.log('§10 undo/redo single-flight: a second call while one is in flight reads nothing twice');
{
  const flag = { current: false };
  let calls = 0;
  const slow = () => { calls += 1; return new Promise((resolve) => setTimeout(() => resolve('ok'), 20)); };
  const p1 = E.guardInFlight(flag, slow, null);
  ok(flag.current === true, 'the flag is claimed synchronously, before the first call settles');
  const p2 = E.guardInFlight(flag, slow, null);
  const [r1, r2] = await Promise.all([p1, p2]);
  ok(calls === 1, 'a repeat call fired while the first is still running never runs again — the stale-entry race this guards against');
  ok(r1 === 'ok' && r2 === null, 'the first call resolves normally; the repeat resolves to the fallback, not a stale retry');
  ok(flag.current === false, 'the flag clears once the in-flight call settles');
  calls = 0;
  const r3 = await E.guardInFlight(flag, slow, null);
  ok(calls === 1 && r3 === 'ok', 'once clear, a later call runs again normally');
}

rmSync(tmp, { recursive: true, force: true });
if (failures) {
  console.log(`\nFAILED: ${failures} check(s)`);
  process.exit(1);
}
console.log('\nOK: editing drop sequences behaves as specified.');
