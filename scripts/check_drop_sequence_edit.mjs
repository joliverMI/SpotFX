/** No-DOM proof for EDITING drop sequences on the Timeline (drop-detection
 * plan, phase 4): spectra/web/src/timeline/dropEdit.ts (snap, step, the
 * order clamp, the whole-sequence move, the ghost, the add placement, the
 * undo stack, the undo/redo single-flight guard and the keyboard map) and
 * what the canvas layer draws while a hand is on it
 * (spectra/web/src/timeline/canvas/dropSeqLayer.ts — the ghost, the lit
 * snap target, the add preview), all transpiled from the REAL modules with
 * esbuild. Synthetic data; never his storage.
 *
 * §11-§19: THE PRE-DROP (predrop plan step 4) — snapping to the rail of its
 * kind (a spike to a hit, a vocal intro to a vocal entry), stepping along
 * it, the order/range clamp, a placed pre-drop holding the drop back and an
 * automatic one left out, the whole-sequence move carrying it, the R and K
 * keys; then the REAL hook (a drag, a Shift-drag, the keyboard: one save
 * each) and the REAL review card with the REAL editor (on/off, back to
 * detected, ＋ Pre-drop, the kind switch, undo — the requests they send),
 * under jsdom.
 *
 * Run: node scripts/check_drop_sequence_edit.mjs
 */
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';

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
const [noOpSt, noOpChanged] = E.pushEditChanged(st, { ...entry(99), revAfter: 'r99' });
ok(noOpSt === st && noOpChanged === false, 'pushEditChanged says so too — the "it worked" note must not show');
const [changedSt, didChange] = E.pushEditChanged(st, entry(300));
ok(changedSt !== st && didChange === true, 'a real change is reported as one');
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

// ── THE PRE-DROP (predrop plan step 4) ─────────────────────────────────────
const preRails = {
  ...rails,
  // a hit cluster before the drop at 48000, a vocal entry sitting among them
  hits: [[46000, 0.6], [47100, 0.5], [47400, 0.8], [47700, 0.4]],
  entries: [[45200, 0.6], [47550, 0.9]],
};

console.log('§11 the pre-drop snaps to the rail of its kind');
g = E.snapPreDrop('spike', 47560, preRails, 140);
ok(g.ms === 47700 && g.rail === 'hit' && g.what === 'hit',
  'a spike snaps to a hit — never to the vocal entry right under it');
g = E.snapPreDrop('intro', 47560, preRails, 140);
ok(g.ms === 47550 && g.rail === 'entry' && g.what === 'vocal entry',
  'a vocal intro snaps to a vocal entry — never to a hit');
g = E.snapPreDrop('spike', 46600, preRails, 140);
ok(g.rail === 'free' && g.ms === 46600, 'nothing that near: the 20 ms grid');
g = E.snapPreDrop('spike', 47386, preRails, 140, true);
ok(g.rail === 'free' && g.ms === 47380, 'Alt places freely, on the 20 ms grid — even on top of a hit');
ok(E.snapPreDrop('intro', 47560, { spikes: [], beats: [] }, 140).rail === 'free'
  && E.snapPreDrop('spike', 47560, null, 140).rail === 'free', 'an older server (no hits or entries) or no rails: free, never a throw');
ok(JSON.stringify(E.preDropRail('spike', preRails)) === JSON.stringify(preRails.hits)
  && JSON.stringify(E.preDropRail('intro', preRails)) === JSON.stringify(preRails.entries), 'the rail per kind');

console.log('§12 ← → step the pre-drop along its own rail');
g = E.stepPreDrop('spike', 47400, 1, preRails);
ok(g.ms === 47700 && g.rail === 'hit', 'a spike steps hit to hit');
g = E.stepPreDrop('intro', 47550, -1, preRails);
ok(g.ms === 45200 && g.rail === 'entry', 'a vocal intro steps entry to entry');
ok(E.stepPreDrop('spike', 47700, 1, preRails) === null, 'nothing further: no step');
g = E.stepPreDrop('spike', 47400, -1, preRails, true);
ok(g.ms === 47390 && g.what.includes('10 ms'), 'Shift nudges 10 ms');

console.log('§13 held inside its kind\'s lead range, at least 200 ms before the drop');
ok(E.clampPreDrop('spike', 48000, 47950) === 47750, 'a spike stops 250 ms before the drop');
ok(E.clampPreDrop('spike', 48000, 40000) === 45000, '...and no more than 3 s before it');
ok(E.clampPreDrop('intro', 48000, 47900) === 47650 && E.clampPreDrop('intro', 48000, 40000) === 43500,
  'a vocal intro: 350 ms to 4.5 s before the drop');
ok(E.clampPreDrop('spike', 48000, 46200) === 46200, 'inside the range: left where it is');
ok(E.clampPreDrop('spike', 48000, 47999, 400) === 47600, 'never closer than the ramp floor, should it ever exceed the range');
ok(E.clampPreDrop('spike', 1000, -500) === 0, 'never before the song starts');
// the clamp never consults the lull: with a lull at 0:46.0, a vocal intro
// at 0:43.6 stays there — before the lull starts
ok(E.clampPreDrop('intro', 48000, 43600) === 43600 && 43600 < 46000, 'it may sit before the lull starts');
ok(E.preDropKindFits('intro', 600) && !E.preDropKindFits('intro', 300) && E.preDropKindFits('spike', 300)
  && !E.preDropKindFits('spike', 3500) && E.preDropKindFits('intro', 3500),
  'the kind switch\'s own test: a lead fits a kind\'s range or not');
ok(E.OTHER_PRE_DROP_KIND.spike === 'intro' && E.OTHER_PRE_DROP_KIND.intro === 'spike', 'spike ⇄ vocal intro');

console.log('§14 the drop and the pre-drop: a placed one holds the drop back, an automatic one is left out');
const tp = { charge: 35000, lull: 41000, drop: 48000, pre_drop: 47400 };
ok(E.clampHandle(E.clampBasis(tp, true), 'drop', 47000) === 47600, 'a pre-drop he placed holds the drop 200 ms after it');
ok(E.clampHandle(E.clampBasis(tp, false), 'drop', 47000) === 47000, 'an automatic one does not hold it');
ok(E.clampHandle({ charge: 35000, lull: 41000, drop: 48000 }, 'drop', 47000) === 47000,
  'no pre-drop given (Home\'s editor): exactly as before');
ok(E.clampBasis(tp, false).pre_drop === null && E.clampBasis(tp, true) === tp, 'the basis drops only an automatic one');
const pview = (o) => ({ ...view(o), pre_drop_ms: null, pre_drop_kind: null, pre_drop_auto: null, pre_drop_tier: null,
  pre_drop_score: null, pre_drop_off: false, pre_drop_was: null, ...o });
const presp = {
  ...resp,
  sequences: [
    pview({ drop_ms: 48000, lull_ms: 41000, charge_ms: 35000, pre_drop_ms: 47400, pre_drop_kind: 'spike',
      pre_drop_auto: 47400, pre_drop_tier: 'confident', pre_drop_score: 1.2,
      parts: { charge: 'waiting', lull: 'waiting', pre_drop: 'waiting', drop: 'waiting' } }),
  ],
  authored: [{ charge: null, lull: { id: 'h-l', kind: 'lull', timestamp_ms: 96000 },
    drop: { id: 'h-d', kind: 'drop', timestamp_ms: 100000 },
    pre_drop: { ms: 99400, kind: 'spike', auto: 99400, off: false, was: null, moved: false, lead_ms: 600,
      score: 1.1, tier: 'confident', part: 'waiting' } }],
};
const pseqs = v.buildDisplay(presp, { showDismissed: false, analysedApplies: true });
const p48 = pseqs.find((s) => s.key === 'drop:48000');
const pHis = pseqs.find((s) => s.key === 'his:h-d');
let gd = E.withGhost(pseqs, { key: 'drop:48000', times: { ...E.timesOf(p48), drop: 47300 } }).find((s) => s.key === 'drop:48000');
ok(gd.pre_drop === null && gd.drop === 47300, 'a drop dragged back past an automatic pre-drop leaves it out, as the saved view will');
gd = E.withGhost(pseqs, { key: 'drop:48000', times: { ...E.timesOf(p48), pre_drop: 47700 } }).find((s) => s.key === 'drop:48000');
ok(gd.pre_drop === 47700 && gd.analysisHad.pre_drop === 47400 && gd.look === 'edited',
  'a moved pre-drop: drawn where the ghost has it, dotted where the rules put it, read as edited');
gd = E.withGhost(pseqs, { key: 'his:h-d', times: { ...E.timesOf(pHis), pre_drop: 99100 } }).find((s) => s.key === 'his:h-d');
ok(gd.look === 'mine' && gd.pre_drop === 99100 && gd.analysisHad.pre_drop === 99400
  && gd.analysisHad.drop === undefined && gd.analysisHad.lull === undefined,
  'on his own sequence only the pre-drop moves; his triggers get no dotted line');
const landedView = { ...p48, drop: 47300, pre_drop: null };
ok(E.ghostLanded(landedView, { key: 'drop:48000', times: { ...E.timesOf(p48), drop: 47300 } }),
  'a ghost lands once the saved view draws the same — the left-out pre-drop included');
ok(!E.ghostLanded(p48, { key: 'drop:48000', times: { ...E.timesOf(p48), pre_drop: 47700 } }),
  'not before the saved view has the pre-drop where he left it');

console.log('§15 a whole-sequence move carries the pre-drop; one save, only what changed');
const shp = E.shiftTimes(tp, -500);
ok(shp.charge === 34500 && shp.lull === 40500 && shp.drop === 47500 && shp.pre_drop === 46900,
  'every handle — the pre-drop too — by the same amount');
const shEarly = E.shiftTimes({ charge: 700, lull: 900, drop: 1400, pre_drop: 300 }, -1000);
ok(shEarly.pre_drop === 0 && shEarly.charge === 400, 'held at the song start by its earliest handle, the pre-drop');
ok(JSON.stringify(E.changedHandles(tp, shp)) === '{"charge":34500,"lull":40500,"pre_drop":46900,"drop":47500}',
  'the save carries the pre-drop with the rest');
ok(JSON.stringify(E.changedHandles(tp, { ...tp, pre_drop: 47700 })) === '{"pre_drop":47700}', 'a pre-drop drag saves the pre-drop alone');
ok(E.timesOf({ charge: 1, lull: 2, drop: 3 }).pre_drop === null, 'times of a sequence with none: pre_drop null');
ok(!('pre_drop' in E.changedHandles({ charge: 1, lull: 2, drop: 3 }, { charge: 1, lull: 5, drop: 3 })),
  'a caller with no pre-drop (Home\'s editor) never sends one');

console.log('§16 which handles a hand moves');
ok(E.editableHandle(pHis, 'pre_drop') && !E.editableHandle(pHis, 'drop') && !E.editable(pHis),
  'his own sequence: its pre-drop moves here, his triggers do not');
ok(E.editableHandle(p48, 'pre_drop') && E.editableHandle(p48, 'lull'), 'a detection: every handle');
ok(!E.editableHandle({ look: 'dismissed', fire: 'dismissed' }, 'pre_drop')
  && !E.editableHandle({ look: 'confident', fire: 'stands_down' }, 'pre_drop'),
  'a dismissed one, or one standing down: not even its pre-drop');

console.log('§17 the keyboard: R selects the pre-drop, K switches its kind');
ok(k('r').kind === 'select' && k('r').handle === 'pre_drop' && k('R').handle === 'pre_drop', 'R selects the pre-drop');
ok(k('k').kind === 'pre_drop_kind' && k('K').kind === 'pre_drop_kind', 'K switches its kind');
ok(k('n').kind === 'sequence' && k('p').kind === 'sequence' && k('c').handle === 'charge' && k('l').handle === 'lull'
  && k('d').handle === 'drop', 'no clash: C L D N P keep their meaning');
ok(k('r', { ctrlKey: true }) === null && k('k', { altKey: true }) === null, 'with a modifier they are the page\'s');
ok(k('q') === null && k('e') === null, 'every other key is still left to the page');

// ── §18-§19: the REAL hook and the REAL review card, under jsdom ───────────
// The real useDropSeqInteractions (a drag, a Shift-drag, the keyboard) with a
// recording editor, then the real DropSequencesCard with the real
// useDropEditor and a recording fake of the routes — the requests a hand
// on the pre-drop sends. jsdom is a dev-only install; without it these two
// sections say so and are skipped (the pure sections above still ran).
const requireWeb = createRequire(path.join(WEB, 'package.json'));
let JSDOM = null;
try { ({ JSDOM } = requireWeb('jsdom')); } catch { /* reported below */ }
if (!JSDOM) {
  console.log('§18-§19 skipped: jsdom is not installed in spectra/web/node_modules (dev-only) — '
    + '`cd spectra/web && npm install --no-save jsdom` to run them');
} else {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' });
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });
  globalThis.HTMLElement = dom.window.HTMLElement;
  globalThis.Node = dom.window.Node;
  globalThis.localStorage = dom.window.localStorage;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
  dom.window.ResizeObserver = globalThis.ResizeObserver;
  dom.window.HTMLElement.prototype.scrollIntoView = function scrollIntoView() {};
  dom.window.requestAnimationFrame = (fn) => setTimeout(() => fn(Date.now()), 16);
  dom.window.cancelAnimationFrame = (id) => clearTimeout(id);
  globalThis.requestAnimationFrame = dom.window.requestAnimationFrame;
  globalThis.cancelAnimationFrame = dom.window.cancelAnimationFrame;
  dom.window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {} });
  globalThis.matchMedia = dom.window.matchMedia;

  const URI = 'spotify:track:predrop-timeline';
  const P = (o) => ({
    origin: 'detected', state: 'confident', tier: 'confident', detected_key: null, auto: null, moved: {},
    lull_off: false, charge_off: false, score: 1.2, break_beats: 3, step: 0.6, rise: 0.7, path: 'step',
    loud_before: true, capped: false, notes: [], needs_review: false, detection_lost: false, matches: [],
    his_marks_near: [], fires: true, fires_reason: 'analysed_show',
    parts: { charge: 'waiting', lull: 'waiting', pre_drop: 'waiting', drop: 'waiting' },
    pre_drop_ms: null, pre_drop_kind: null, pre_drop_auto: null, pre_drop_tier: null,
    pre_drop_score: null, pre_drop_off: false, pre_drop_was: null, ...o,
  });
  const VIEW = {
    uri: URI, status: 'ok', reason: null,
    detector: { version: '1', stamp: 's', detected_at: 1, confident_score: 1, suggested_score: 0.7 },
    song: { tempo_bpm: 120, beat_ms: 500, captured_from_ms: 0, captured_to_ms: 300000, duration_ms: 300000 },
    sequences: [
      // a confident spike 600 ms out (it fits a vocal intro too)
      P({ key: 'drop:48000', charge_ms: 35000, lull_ms: 41000, drop_ms: 48000,
        auto: { charge_ms: 35000, lull_ms: 41000, drop_ms: 48000 },
        pre_drop_ms: 47400, pre_drop_kind: 'spike', pre_drop_auto: 47400, pre_drop_tier: 'confident', pre_drop_score: 1.2 }),
      // a vocal intro he moved off the rules' place
      P({ key: 'drop:90000', charge_ms: null, lull_ms: 85000, drop_ms: 90000, state: 'edited', moved: { pre_drop: true },
        auto: { charge_ms: null, lull_ms: 85000, drop_ms: 90000 },
        pre_drop_ms: 86500, pre_drop_kind: 'intro', pre_drop_auto: 87000 }),
      // switched off: it comes back at 2:07.50
      P({ key: 'drop:130000', charge_ms: null, lull_ms: 126000, drop_ms: 130000, state: 'edited',
        parts: { charge: 'absent', lull: 'waiting', pre_drop: 'off', drop: 'waiting' },
        auto: { charge_ms: null, lull_ms: 126000, drop_ms: 130000 },
        pre_drop_kind: 'intro', pre_drop_auto: 127500, pre_drop_off: true, pre_drop_was: 127500,
        pre_drop_tier: 'suggested', pre_drop_score: 1.0 }),
      // an added drop with one he placed (the rules found none)
      P({ key: 'added:a1', origin: 'added', state: 'added', tier: null, score: null, charge_ms: null,
        lull_ms: 150000, drop_ms: 160000, auto: null, moved: { pre_drop: true },
        parts: { charge: 'absent', lull: 'on', pre_drop: 'on', drop: 'on' },
        pre_drop_ms: 159500, pre_drop_kind: 'spike' }),
      // none at all
      P({ key: 'drop:200000', charge_ms: null, lull_ms: 196000, drop_ms: 200000,
        auto: { charge_ms: null, lull_ms: 196000, drop_ms: 200000 },
        parts: { charge: 'absent', lull: 'waiting', pre_drop: 'absent', drop: 'waiting' } }),
      // a spike only 300 ms out: too close to be a vocal intro
      P({ key: 'drop:220000', charge_ms: null, lull_ms: 216000, drop_ms: 220000,
        auto: { charge_ms: null, lull_ms: 216000, drop_ms: 220000 },
        pre_drop_ms: 219700, pre_drop_kind: 'spike', pre_drop_auto: 219700, pre_drop_tier: 'confident', pre_drop_score: 1.1 }),
    ],
    excluded: [], counts: {}, authored_lone: [],
    authored: [{ charge: null, lull: { id: 'h-l', kind: 'lull', timestamp_ms: 246000 },
      drop: { id: 'h-d', kind: 'drop', timestamp_ms: 250000 },
      pre_drop: { ms: 249400, kind: 'spike', auto: 249400, off: false, was: null, moved: false, lead_ms: 600,
        score: 1.1, tier: 'confident', part: 'waiting' } }],
    firing: { effective_mode: 'analysed', has_authored: true, analysed_applies: true, his_applies: true, testing: false },
    windows: [],
  };
  const RAILS = {
    uri: URI, status: 'ok', reason: null, beat_ms: 500, captured_from_ms: 0,
    spikes: [[48000, 0.9], [41000, 0.5]], beats: [[40000, 1], [40500, 0]],
    hits: [[46000, 0.6], [47100, 0.5], [47400, 0.8], [47700, 0.4], [86980, 0.9], [249100, 0.5], [249400, 0.8]],
    entries: [[47550, 0.9], [86500, 0.6], [87000, 0.7], [88200, 0.5]],
  };

  const tmpJ = mkdtempSync(path.join(tmpdir(), 'drop-seq-edit-jsdom-'));
  const src = (p) => JSON.stringify(path.join(WEB, 'src', p));
  const entry = path.join(tmpJ, 'entry.mjs');
  writeFileSync(entry, `
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import DropSequencesCard from ${src('timeline/components/DropSequencesCard.tsx')};
import { useDropEditor } from ${src('timeline/hooks/useDropEditor.ts')};
import { useDropSeqInteractions } from ${src('timeline/hooks/useDropSeqInteractions.ts')};
import { useDropSequences } from ${src('timeline/queries.ts')};
import { buildDisplay } from ${src('timeline/dropSequences.ts')};

export const state = { hook: null, setKey: null, steps: [] };
const roots = [];

/** Unmount everything (react-query's refetch timer goes with its observer). */
export async function unmountAll() {
  await act(async () => { roots.splice(0).forEach((r) => r.unmount()); });
}

export async function settle(rounds = 6) {
  for (let i = 0; i < rounds; i += 1) {
    await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
  }
}

export async function mountHook(seqs, rails, editor) {
  const box = document.createElement('div');
  document.body.appendChild(box);
  const root = createRoot(box);
  roots.push(root);
  function H() {
    const [key, setKey] = React.useState(null);
    state.hook = useDropSeqInteractions({ seqs, rails, beatMs: 500, editor, selectedKey: key,
      setSelectedKey: setKey, onJump: () => {}, onShowDetail: () => {} });
    return null;
  }
  await act(async () => { root.render(React.createElement(H)); });
  return root;
}

export async function run(fn) {
  let out;
  await act(async () => { out = fn(); });
  return out;
}

export async function mountCard(uri) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const box = document.createElement('div');
  document.body.appendChild(box);
  const root = createRoot(box);
  roots.push(root);
  function C() {
    const { data: resp } = useDropSequences(uri);
    const editor = useDropEditor(uri);
    const [key, setKey] = React.useState(null);
    const [selHandle, setSelHandle] = React.useState('drop');
    state.setKey = setKey;
    const seqs = React.useMemo(() => buildDisplay(resp, { showDismissed: false, analysedApplies: true }), [resp]);
    return React.createElement(DropSequencesCard, {
      resp, loading: false, error: null, seqs, selectedKey: key, onSelect: setKey, onJump: () => {},
      showDismissed: false, setShowDismissed: () => {}, analysedApplies: true, analysedReason: null,
      editor, selHandle, onSelectHandle: setSelHandle,
      onStep: (h, dir) => { state.steps.push([h, dir]); },
    });
  }
  await act(async () => {
    root.render(React.createElement(QueryClientProvider, { client: qc },
      React.createElement(MemoryRouter, null, React.createElement(C))));
  });
  await settle();
  return box;
}

export async function select(key) {
  await act(async () => { state.setKey(key); });
  await settle();
}

export async function click(el) {
  await act(async () => { el.dispatchEvent(new window.MouseEvent('click', { bubbles: true })); });
  await settle();
}
`);
  const esbuild = requireWeb('esbuild');
  const outFile = path.join(tmpJ, 'out.cjs');
  const built = await esbuild.build({
    entryPoints: [entry], bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
    outfile: outFile, nodePaths: [path.join(WEB, 'node_modules')], loader: { '.css': 'empty' },
    logLevel: 'silent',
  });
  ok(built.errors.length === 0, 'the real hook, card and editor bundle cleanly');
  const H = createRequire(import.meta.url)(outFile);

  // ── §18 the hook: a hand on the pre-drop ──────────────────────────────
  console.log('§18 the real hook: a drag snaps to its kind\'s rail, held in range; one save on release');
  const saves = [];
  const kinds = [];
  // moveHandles answers null: the hook then lets go of its ghost, as it would
  // once a saved view landed (this harness's view never changes)
  const fakeEditor = {
    busy: false, error: null, note: null, canUndo: false, canRedo: false, undoLabel: null, redoLabel: null,
    clearError() {},
    moveHandles: async (key, handles, what) => { saves.push({ key, handles, what }); return null; },
    preDropKind: async (key, kind) => { kinds.push({ key, kind }); return key; },
    confirm: async () => null, dismiss: async () => null, revert: async () => null, member: async () => null,
    fill: async () => null, review: async () => null, add: async () => null, parts: async () => null,
    approve: async () => null, remove: async () => null, switchOn: async () => null,
    confirmAll: async () => [], redetect: async () => true, undo: async () => null, redo: async () => null,
  };
  const hseqs = v.buildDisplay(VIEW, { showDismissed: false, analysedApplies: true });
  await H.mountHook(hseqs, RAILS, fakeEditor);
  const target = { getBoundingClientRect: () => ({ left: 0, top: 0 }) };
  const ev = (x, mods = {}) => ({ clientX: x, clientY: 20, shiftKey: false, altKey: false, target, ...mods });
  const geom = (startMs, endMs) => ({ w: 1000, win: { startMs, endMs }, xToTime: (x) => startMs + (x / 1000) * (endMs - startMs) });
  const xOf = (gm, ms) => ((ms - gm.win.startMs) / (gm.win.endMs - gm.win.startMs)) * 1000;
  const drag = async (gm, key, handle, fromMs, toMs, mods = {}) => {
    const startX = xOf(gm, fromMs);
    await H.run(() => H.state.hook.onHit({ kind: 'drop-seq', key, handle }, ev(startX, mods), gm));
    let moved = false;
    await H.run(() => { moved = H.state.hook.onDragMove(ev(xOf(gm, toMs), mods), gm); });
    const guide = H.state.hook.live.current.guide;
    await H.run(() => H.state.hook.onDragEnd(ev(xOf(gm, toMs), mods), gm));
    return { moved, guide };
  };
  const g40 = geom(40000, 50000);      // 10 s across 1000 px: a 140 ms snap radius
  let d = await drag(g40, 'drop:48000', 'pre_drop', 47400, 47560);
  ok(JSON.stringify(saves.at(-1)) === JSON.stringify({ key: 'drop:48000', handles: { pre_drop: 47700 }, what: 'moved pre-drop' }),
    `a spike dragged beside a vocal entry snaps to the hit — ${JSON.stringify(saves.at(-1))}`);
  ok(d.guide?.rail === 'hit', 'and lights the hit on its rail');
  d = await drag(g40, 'drop:48000', 'pre_drop', 47400, 47990);
  ok(saves.at(-1).handles.pre_drop === 47750 && /held inside its lead range/.test(d.guide?.what ?? ''),
    'dragged into the drop: held 250 ms before it, saying so');
  const g80 = geom(80000, 90000);
  d = await drag(g80, 'drop:90000', 'pre_drop', 86500, 86970);
  ok(JSON.stringify(saves.at(-1)) === JSON.stringify({ key: 'drop:90000', handles: { pre_drop: 87000 }, what: 'moved pre-drop' }),
    `a vocal intro dragged beside a hit snaps to the vocal entry — ${JSON.stringify(saves.at(-1))}`);
  ok(d.guide?.rail === 'entry', 'and lights the entry');
  const n0 = saves.length;
  d = await drag(geom(240000, 250000), 'his:h-d', 'drop', 250000, 249000);
  ok(saves.length === n0 && !d.moved, 'his own drop handle is not dragged here');
  await drag(geom(240000, 250000), 'his:h-d', 'pre_drop', 249400, 249110);
  ok(JSON.stringify(saves.at(-1)) === JSON.stringify({ key: 'his:h-d', handles: { pre_drop: 249100 }, what: 'moved pre-drop' }),
    'his own drop\'s pre-drop is dragged: one save under his key');
  await drag(g40, 'drop:48000', 'drop', 48000, 48500, { shiftKey: true });
  const whole = saves.at(-1);
  const delta = whole.handles.drop - 48000;
  ok(whole.what === 'moved the whole sequence' && delta !== 0
    && whole.handles.pre_drop === 47400 + delta && whole.handles.lull === 41000 + delta && whole.handles.charge === 35000 + delta,
    `a Shift-drag moves the whole sequence and carries the pre-drop — ${JSON.stringify(whole.handles)}`);
  await drag(geom(150000, 162000), 'added:a1', 'drop', 160000, 159000);
  ok(saves.at(-1).handles.drop === 159700, 'a drop dragged back toward the pre-drop he placed is held 200 ms after it');
  await drag(g40, 'drop:48000', 'drop', 48000, 47250);
  ok(JSON.stringify(saves.at(-1).handles) === JSON.stringify({ drop: E.grid(47250) }),
    `past an automatic one it is not held, and the pre-drop is not in the save — ${JSON.stringify(saves.at(-1).handles)}`);

  console.log('§18b the keyboard: R selects it, ← steps it along its rail (one save), K switches its kind');
  await H.run(() => H.state.hook.select('drop:48000'));
  const key = (k2, mods = {}) => ({ key: k2, shiftKey: false, ctrlKey: false, metaKey: false, altKey: false, target: document.body, ...mods });
  let used = false;
  await H.run(() => { used = H.state.hook.onKey(key('r')); });
  ok(used && H.state.hook.selHandle === 'pre_drop', 'R selects the pre-drop');
  const nk = saves.length;
  await H.run(() => { used = H.state.hook.onKey(key('ArrowLeft')); });
  ok(used && H.state.hook.live.current.guide?.ms === 47100 && H.state.hook.live.current.guide?.rail === 'hit',
    '← steps it to the previous hit');
  await new Promise((r) => setTimeout(r, E.KEY_SAVE_IDLE_MS + 120));
  await H.settle(2);
  ok(saves.length === nk + 1 && JSON.stringify(saves.at(-1)) === JSON.stringify({ key: 'drop:48000', handles: { pre_drop: 47100 }, what: 'moved pre-drop (keys)' }),
    `one save after the keys settle — ${JSON.stringify(saves.at(-1))}`);
  await H.run(() => { used = H.state.hook.onKey(key('k')); });
  ok(used && JSON.stringify(kinds.at(-1)) === '{"key":"drop:48000","kind":"intro"}', 'K asks for a vocal intro');
  await H.run(() => H.state.hook.select('his:h-d'));
  await H.run(() => { H.state.hook.onKey(key('k')); });
  ok(JSON.stringify(kinds.at(-1)) === '{"key":"his:h-d","kind":"intro"}', 'on his own drop too, under his key');
  await H.run(() => H.state.hook.select('drop:200000'));
  const nkinds = kinds.length;
  await H.run(() => { used = H.state.hook.onKey(key('k')); });
  ok(used && kinds.length === nkinds, 'a drop with no pre-drop: K is taken, nothing is asked');

  // ── §19 the card: what each pre-drop button sends ─────────────────────
  console.log('§19 the real card with the real editor: on/off, back to detected, ＋ Pre-drop, the kind switch, undo');
  const calls = [];
  let rev = 0;
  const reply = (status, data) => ({ ok: status < 400, status, json: async () => structuredClone(data) });
  globalThis.fetch = async (url, opts = {}) => {
    const u = new URL(url, 'http://localhost');
    const method = (opts.method || 'GET').toUpperCase();
    const body = opts.body ? JSON.parse(opts.body) : undefined;
    const p = u.pathname;
    calls.push({ method, path: p, body });
    if (p === '/spectra/api/drop-sequences' && method === 'GET') return reply(200, VIEW);
    if (p.startsWith('/spectra/api/drop-sequences/') && method === 'POST') {
      rev += 1;
      return reply(200, { result: body.key ?? null, view: VIEW,
        before: { overrides: { n: rev - 1 }, added: [] }, after: { overrides: { n: rev }, added: [] },
        rev_before: `r${rev - 1}`, rev_after: `r${rev}` });
    }
    return reply(404, { detail: `not in this fixture: ${method} ${p}` });
  };
  const box = await H.mountCard(URI);
  const btn = (text) => [...box.querySelectorAll('button')].find((b) => b.textContent.trim() === text);
  const posted = (op) => calls.filter((c) => c.method === 'POST' && c.path === `/spectra/api/drop-sequences/${op}`);
  await H.select('drop:48000');
  ok(box.querySelector('.drop-detail-predrop') && /spike · as detected · 600 ms before the drop/.test(
    box.querySelector('.drop-detail-predrop')?.textContent ?? ''), 'the detail box has its pre-drop row');
  await H.click(btn('Pre-drop off'));
  ok(JSON.stringify(posted('member').at(-1)?.body) === JSON.stringify({ uri: URI, key: 'drop:48000', handle: 'pre_drop', off: true }),
    'Pre-drop off: ONE member call {handle: pre_drop, off: true}');
  const glyph = box.querySelector('.drop-detail-predrop button.drop-predrop-kind');
  ok(glyph && !glyph.disabled && /tap to make it a vocal intro/.test(glyph.title), 'its glyph offers the kind switch');
  await H.click(glyph);
  ok(JSON.stringify(posted('pre-drop-kind').at(-1)?.body) === JSON.stringify({ uri: URI, key: 'drop:48000', kind: 'intro' }),
    'one tap on the glyph: ONE pre-drop-kind call {kind: intro}');
  await H.select('drop:220000');
  const tight = box.querySelector('.drop-detail-predrop button.drop-predrop-kind');
  ok(tight?.disabled && /cannot be a vocal intro: a vocal intro sits 350-4500 ms before its drop, this one 300 ms/.test(tight.title),
    `too close for a vocal intro: no switch, and it says why — ${tight?.title}`);
  await H.select('drop:130000');
  await H.click(btn('Pre-drop on'));
  ok(JSON.stringify(posted('member').at(-1)?.body) === JSON.stringify({ uri: URI, key: 'drop:130000', handle: 'pre_drop', off: false }),
    'Pre-drop on: ONE member call {off: false}');
  await H.select('drop:90000');
  await H.click(btn('↺ Pre-drop back to detected'));
  ok(JSON.stringify(posted('handles').at(-1)?.body) === JSON.stringify({ uri: URI, key: 'drop:90000', handles: { pre_drop: null } }),
    'back to detected: ONE handles call {pre_drop: null}');
  await H.select('added:a1');
  ok(!btn('↺ Pre-drop back to detected') && btn('✕ Remove pre-drop'), 'one he placed where the rules found none is removed instead');
  await H.click(btn('✕ Remove pre-drop'));
  ok(JSON.stringify(posted('handles').at(-1)?.body) === JSON.stringify({ uri: URI, key: 'added:a1', handles: { pre_drop: null } }),
    'remove: the same null');
  await H.select('drop:200000');
  ok(!btn('Pre-drop off') && !btn('Pre-drop on'), 'a drop with none: nothing to switch');
  await H.click(btn('＋ Pre-drop'));
  ok(JSON.stringify(posted('fill').at(-1)?.body) === JSON.stringify({ uri: URI, key: 'drop:200000', handle: 'pre_drop' }),
    '＋ Pre-drop: ONE fill call {handle: pre_drop}');
  await H.select('his:h-d');
  ok(/found before your drop/.test(box.querySelector('.drop-detail-predrop')?.textContent ?? ''),
    'his own drop: the pre-drop row, found before his drop');
  await H.click(btn('Pre-drop off'));
  ok(JSON.stringify(posted('member').at(-1)?.body) === JSON.stringify({ uri: URI, key: 'his:h-d', handle: 'pre_drop', off: true }),
    'his own drop\'s pre-drop switches under his key');
  ok(box.querySelector('.drop-detail-predrop a[href*="pre-drop"]'), 'the row links the pre-drop help topic');
  const undoBtn = btn('↶ Undo');
  ok(undoBtn && !undoBtn.disabled, 'every one of those is an undo step');
  await H.click(undoBtn);
  const restore = posted('restore').at(-1)?.body;
  ok(restore && JSON.stringify(restore.edits) === JSON.stringify({ overrides: { n: rev - 2 }, added: [] })
    && restore.expect === `r${rev - 1}`,
    `undo puts the last one back: ONE restore {edits: before, expect: its rev} — ${JSON.stringify(restore)}`);
  await H.unmountAll();
  dom.window.close();
  rmSync(tmpJ, { recursive: true, force: true });
}

rmSync(tmp, { recursive: true, force: true });
if (failures) {
  console.log(`\nFAILED: ${failures} check(s)`);
  process.exit(1);
}
console.log('\nOK: editing drop sequences behaves as specified.');
// jsdom and react-query leave timers behind; the checks are done
process.exit(0);
