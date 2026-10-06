/** No-DOM proof for the Timeline's drop-sequence view (drop-detection plan,
 * phase 3): spectra/web/src/timeline/dropSequences.ts (what each sequence
 * IS — its look, whether it fires, its number, its words, its builds) and
 * spectra/web/src/timeline/canvas/dropSeqLayer.ts (what the canvas draws
 * and what a click hits), both transpiled from the REAL modules with
 * esbuild. The canvas is a recording fake: TimelineCanvas swallows a
 * layer's exception (one bad layer must not kill the draw loop), so a
 * layer that throws would draw nothing and say nothing — this is where it
 * would go red instead.
 *
 * Synthetic data shaped like the server's view (spectra/services/
 * drop_sequences.py); never his storage.
 *
 * Run: node scripts/check_drop_sequence_view.mjs
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

const tmp = mkdtempSync(path.join(tmpdir(), 'drop-seq-view-'));
const build = (rel, name) => {
  const out = path.join(tmp, name);
  execFileSync('npx', ['esbuild', path.join(WEB, rel), '--bundle', '--format=esm',
    '--platform=neutral', '--log-level=warning', `--outfile=${out}`], { cwd: WEB, stdio: ['ignore', 'ignore', 'inherit'] });
  return out;
};
const v = await import(build('src/timeline/dropSequences.ts', 'dropSequences.mjs'));
const L = await import(build('src/timeline/canvas/dropSeqLayer.ts', 'dropSeqLayer.mjs'));
const pb = await import(build('src/timeline/phaseBlend.ts', 'phaseBlend.mjs'));

// ── synthetic views, the server's shape ────────────────────────────────────
const mark = (id, kind, ms) => ({ id, kind, timestamp_ms: ms });
const view = (o) => ({
  key: `drop:${o.drop_ms}`, origin: 'detected', state: 'confident', charge_ms: null, lull_ms: null,
  drop_ms: 0, tier: 'confident', detected_key: `drop:${o.drop_ms}`, auto: null, moved: {},
  lull_off: false, charge_off: false, score: 1.2, break_beats: 3.3, step: 0.65, rise: 0.7,
  path: 'step', loud_before: true, capped: false, notes: [], needs_review: false,
  detection_lost: false, matches: [], his_marks_near: [], ...o,
  auto: o.auto ?? { charge_ms: o.charge_ms ?? null, lull_ms: o.lull_ms ?? null, drop_ms: o.drop_ms },
});
const hisDrop = mark('t-d1', 'drop', 66817);
const resp = {
  uri: 'spotify:track:x', status: 'ok', reason: null,
  detector: { version: '1', stamp: 's', detected_at: Date.now(), confident_score: 1, suggested_score: 0.7 },
  song: { tempo_bpm: 126, beat_ms: 476, captured_from_ms: 0, captured_to_ms: 238000, duration_ms: 238000 },
  sequences: [
    view({ drop_ms: 47612, charge_ms: 39915, lull_ms: 46080, state: 'suggested', tier: 'suggested', score: 0.717,
      his_marks_near: [mark('t-f', 'flare', 47580)] }),
    view({ drop_ms: 66803, charge_ms: 62484, lull_ms: 65236, state: 'matches_yours', matches: [hisDrop],
      his_marks_near: [hisDrop] }),
    view({ drop_ms: 87070, charge_ms: 77306, lull_ms: 81962, state: 'confident', score: 1.014 }),
    view({ drop_ms: 158969, charge_ms: 139552, lull_ms: 147551, state: 'suggested', tier: 'suggested',
      his_marks_near: [mark('t-u', 'fire_scene_update', 158975)] }),
    view({ drop_ms: 170486, charge_ms: 166626, lull_ms: 169081, state: 'dismissed', tier: 'suggested' }),
    view({ drop_ms: 189677, charge_ms: 185000, lull_ms: null, state: 'edited', lull_off: true,
      moved: { charge: true }, auto: { charge_ms: 181039, lull_ms: 187889, drop_ms: 189677 } }),
    view({ drop_ms: 200000, charge_ms: 196000, lull_ms: 198500, state: 'matches_yours',
      matches: [mark('lone-c', 'charge', 199900)] }),
    { ...view({ drop_ms: 220000, lull_ms: 218000, state: 'added' }), key: 'added:abc', origin: 'added',
      auto: null, tier: null, score: null, break_beats: null },
  ],
  excluded: [], counts: { suggested: 2, matches_yours: 2, confident: 1, dismissed: 1, edited: 1, added: 1 },
  authored: [
    { charge: mark('t-c1', 'charge', 59143), lull: mark('t-l1', 'lull', 65397), drop: hisDrop },
    { charge: null, lull: null, drop: mark('t-d2', 'drop', 205162) },
  ],
  authored_lone: [mark('lone-c', 'charge', 199900)],
};

console.log('§1 one shape per sequence: his own triggers stand in for the detection they matched');
let seqs = v.buildDisplay(resp, { showDismissed: false, analysedApplies: true });
const byDrop = (ms) => seqs.find((s) => s.drop === ms);
ok(seqs.filter((s) => s.look === 'mine').length === 2, 'both of his groups are drawn (look "mine")');
ok(!seqs.some((s) => s.key === 'drop:66803'), 'the detection on his drop is not drawn a second time');
ok(byDrop(66817).view?.key === 'drop:66803', 'his group carries the detection it matched');
ok(byDrop(205162).view === null, 'a drop of his the analysis missed carries none');
ok(seqs.every((a, i) => i === 0 || seqs[i - 1].drop <= a.drop), 'in drop-time order');

console.log('§2 what fires is numbered, in time order; a suggestion is "?"');
const fired = seqs.filter((s) => s.number != null);
ok(fired.map((s) => s.number).join() === fired.map((_, i) => i + 1).join(), 'numbers run 1..n with no gaps');
ok(byDrop(66817).number === 1 && byDrop(66817).fire === 'fires', 'his own group fires today, number 1');
ok(byDrop(87070).fire === 'fires' && byDrop(87070).badge === String(byDrop(87070).number),
  'a confident detection on an analysed-show song fires: numbered');
ok(byDrop(47612).badge === '?' && byDrop(47612).fire === 'waits', 'a suggestion waits: "?"');
ok(byDrop(189677).fire === 'fires' && byDrop(220000).fire === 'fires',
  'edited and added sequences are his: they fire');

console.log('§3 a confident detection on a song that plays only his triggers is "✦", not numbered');
seqs = v.buildDisplay(resp, { showDismissed: false, analysedApplies: false });
ok(byDrop(87070).fire === 'muted' && byDrop(87070).badge === '✦' && byDrop(87070).number === null,
  'muted, outlined ✦, no number');
ok(byDrop(66817).number === 1, 'his own still number 1');

console.log('§3b the server\'s own answer wins (phase 5: drop_firing.annotate)');
{
  const withFires = JSON.parse(JSON.stringify(resp));
  for (const sv of withFires.sequences) {
    if (sv.drop_ms === 87070) { sv.fires = false; sv.fires_reason = 'analysed_show_off'; }
    if (sv.drop_ms === 220000) { sv.fires = false; sv.fires_reason = 'transitions_only'; }
    if (sv.drop_ms === 189677) { sv.fires = true; sv.fires_reason = 'his'; sv.stood_down = { charge: 'his-c' }; }
  }
  const s3 = v.buildDisplay(withFires, { showDismissed: false, analysedApplies: true });
  const at = (ms) => s3.find((x) => x.drop === ms);
  ok(at(87070).fire === 'muted' && at(87070).number === null,
    'a confident one the server says does not fire here is muted, even with analysedApplies');
  ok(at(220000).fire === 'muted' && at(220000).badge === '✦',
    'one of his under "Transitions only" is muted');
  ok(/Transitions only/.test(v.fireLine(at(220000))), 'and says why');
  ok(at(189677).fire === 'fires' && /left out/.test(v.fireLine(at(189677))),
    'a member standing down on his own trigger is named');
  const onHis = JSON.parse(JSON.stringify(resp));
  for (const sv of onHis.sequences) {
    if (sv.drop_ms === 220000) { sv.fires = false; sv.fires_reason = 'matches_yours'; }
  }
  const s4 = v.buildDisplay(onHis, { showDismissed: false, analysedApplies: true });
  ok(s4.find((x) => x.drop === 220000).fire === 'stands_down',
    'an added sequence on his own trigger stands down, never "muted"');
  ok(!/does not fire yet|once detected drops go live/.test(
    s3.map((x) => v.fireLine(x)).join(' ')), 'no "not live yet" wording remains');
}

console.log('§4 dismissed is hidden unless "show dismissed"');
ok(!seqs.some((s) => s.drop === 170486), 'hidden by default');
seqs = v.buildDisplay(resp, { showDismissed: true, analysedApplies: true });
ok(byDrop(170486)?.look === 'dismissed' && byDrop(170486).badge === '✕' && byDrop(170486).number === null,
  'shown greyed with ✕ and never numbered');

console.log('§5 the dotted "where the analysis had it" line: only handles he changed');
const ed = byDrop(189677);
ok(ed.analysisHad.charge === 181039, 'a moved charge keeps the analysis place');
ok(ed.analysisHad.lull === 187889 && ed.lull === null && ed.off.lull, 'a lull switched off: drawn dotted, not as a member');
ok(ed.analysisHad.drop === undefined, 'an untouched drop has no dotted line');
ok(Object.keys(byDrop(87070).analysisHad).length === 0, 'an untouched detection has none');

console.log('§6 a detection on a LONE phase trigger of his stands down, faded, never numbered');
const sd = byDrop(200000);
ok(sd.fire === 'stands_down' && sd.number === null && sd.badge === '?', 'stands down');
ok(v.reviewStatus(sd).startsWith('stands down'), v.reviewStatus(sd));

console.log('§7 the review list says what of his is already there');
ok(v.reviewStatus(byDrop(66817)) === 'matches your drop', 'matches your drop');
ok(v.reviewStatus(byDrop(47612)) === 'you have a flare here', 'you have a flare here');
ok(v.reviewStatus(byDrop(158969)) === 'you have a scene update here', 'you have a scene update here');
ok(v.reviewStatus(byDrop(205162)) === 'yours · the analysis did not find this drop', 'yours, not found');
ok(v.fmtTenths(66817) === '1:06.8' && v.fmtHundredths(35047) === '0:35.05', 'time formats m:ss.s / m:ss.ss');

console.log('§8 the builds are the engine\'s own arithmetic, each member to its own partner');
const s1 = byDrop(87070);
const b = v.sequenceBuilds(s1);
const want = pb.phaseBlendSpan('charge', 77306, 81962);
ok(b.charge.rampEndMs === want.rampEndMs && b.charge.endMs === 81962, 'charge ramps to its own lull');
ok(Math.abs((b.charge.rampEndMs - 77306) - 0.9 * (81962 - 77306)) <= 1, '...for 90% of the way, then holds');
ok(b.lull.endMs === 87070 && b.lull.startMs === 81962, 'lull ramps to its own drop');
const noLull = v.sequenceBuilds({ charge: 1000, lull: null, drop: 5000 });
ok(noLull.charge.endMs === 5000 && noLull.lull === null, 'a charge with no lull builds to the drop');
const tight = v.sequenceBuilds({ charge: 1000, lull: 1150, drop: 1300 });
ok(tight.charge.rampEndMs === 1150, 'the 200 ms ramp floor never runs past the partner');
ok(v.roomLines(s1)[0].startsWith('Charge builds for 4.2 s, holds 0.5 s'), v.roomLines(s1)[0]);

console.log('§9 jump: two bars before the charge to two bars after the drop');
const z = v.zoomWindow(s1, 476, 238000);
ok(z.startMs === 77306 - 8 * 476 && z.endMs === 87070 + 8 * 476, `${z.startMs}..${z.endMs}`);
const z0 = v.zoomWindow({ charge: 1000, lull: null, drop: 3000 }, 476, 238000);
ok(z0.startMs === 0, 'never before the song starts');
ok(v.zoomWindow({ charge: null, lull: null, drop: 236000 }, 476, 238000).endMs === 238000, 'never past its end');

console.log('§10 the detail box rows');
const rows = v.handleRows(byDrop(66817));
ok(rows[2].note === 'your trigger · analysis: 1:06.80 (+14 ms)', rows[2].note);
const erows = v.handleRows(ed);
ok(erows[0].note === 'analysis: 3:01.04 (+3961 ms)', erows[0].note);
ok(erows[1].note.startsWith('switched off'), erows[1].note);
ok(v.whyFound(s1.view, 1).includes('bass returned after 3.3 quiet beats'), v.whyFound(s1.view, 1));
ok(v.whyFound(null, 1) === null, 'nothing to say for a sequence of his with no detection');

// ── the canvas layer, on a recording fake ─────────────────────────────────
function fakeCtx() {
  const calls = [];
  const rec = (name) => (...a) => { calls.push([name, ...a]); };
  const ctx = {
    calls, globalAlpha: 1, fillStyle: '', strokeStyle: '', lineWidth: 1, font: '', textAlign: 'left',
    save: rec('save'), restore: rec('restore'), beginPath: rec('beginPath'), closePath: rec('closePath'),
    moveTo: rec('moveTo'), lineTo: rec('lineTo'), fill: rec('fill'), stroke: rec('stroke'),
    fillRect: rec('fillRect'), rect: rec('rect'), clip: rec('clip'), arc: rec('arc'),
    roundRect: rec('roundRect'), setLineDash: rec('setLineDash'), fillText: rec('fillText'),
    measureText: (t) => ({ width: String(t).length * 6 }),
    createLinearGradient: () => ({ addColorStop: () => {} }),
  };
  return ctx;
}
const W = 1000;
const frameFor = (seqsIn, win, extra = {}) => {
  const ctx = fakeCtx();
  const span = win.endMs - win.startMs;
  return {
    ctx, w: W, h: 300, mainH: 260, railH: 36, stripH: 21, stripCount: 0, win,
    timeToX: (ms) => ((ms - win.startMs) / span) * W,
    xToTime: (x) => win.startMs + (x / W) * span,
    nowMs: null, view: {},
    data: { dropSeq: { seqs: seqsIn, rails: { status: 'ok', beat_ms: 476, captured_from_ms: 18000,
      spikes: [[87070, 0.9], [80000, 0.2]], beats: [[86000, 1], [86476, 0]] },
      selectedKey: null, hover: null, capturedFromMs: 18000, beatMs: 476, ...extra } },
  };
};

console.log('§11 the layer draws without throwing, every look');
seqs = v.buildDisplay(resp, { showDismissed: true, analysedApplies: true });
const full = { startMs: 0, endMs: 238000 };
let threw = null;
for (const layer of [L.dropSeqRailBand, L.dropSeqBody, L.dropSeqRail]) {
  for (const sel of [null, 'drop:87070', 'drop:189677']) {
    const f = frameFor(seqs, full, { selectedKey: sel, hover: { key: 'drop:87070', handle: 'drop' } });
    try { if (layer.visible(f)) layer.draw(f); } catch (e) { threw = `${layer.id}: ${e}`; }
  }
}
ok(threw === null, threw ?? 'all three parts draw the whole song, selected and hovered');

console.log('§12 the gold wedge is the charge\'s build, exactly');
const zoom = { startMs: 76000, endMs: 92000 };
const fz = frameFor([s1], zoom);
L.dropSeqBody.draw(fz);
const X = (ms) => fz.timeToX(ms);
const moves = fz.ctx.calls.filter((c) => c[0] === 'moveTo' || c[0] === 'lineTo');
const at = (name, x, y) => moves.some((c) => c[0] === name && Math.abs(c[1] - x) < 0.01 && Math.abs(c[2] - y) < 0.01);
ok(at('moveTo', X(77306), 260), 'starts at the charge, on the baseline');
ok(at('lineTo', X(b.charge.rampEndMs), L.RAIL_H + 8), 'rises to the ramp end');
ok(at('lineTo', X(81962), L.RAIL_H + 8), 'then holds flat to the lull');
ok(at('lineTo', X(b.lull.rampEndMs), L.RAIL_H + 26), 'the lull rises to its own ramp end, then hangs');
ok(fz.ctx.calls.some((c) => c[0] === 'fillRect' && Math.abs(c[1] - X(81962)) < 0.01),
  'the blue band starts at the lull');

console.log('§13 the snap rails: spikes taller for harder hits, downbeats taller');
const spikeRects = fz.ctx.calls.filter((c) => c[0] === 'fillRect' && c[3] === 2);
const hard = spikeRects.find((c) => Math.abs(c[1] - (X(87070) - 1)) < 0.01);
ok(hard && Math.abs(hard[4] - (4 + 12 * 0.9)) < 0.01 && hard[2] >= 260, 'a 0.9 spike is 14.8 px, in the rail band');
const beatRects = fz.ctx.calls.filter((c) => c[0] === 'fillRect' && c[3] === 1);
ok(beatRects.some((c) => c[4] === 12) && beatRects.some((c) => c[4] === 8), 'downbeat 12 px, beat 8 px');

console.log('§14 a click: handles in the rail, lines in the graph, nothing above the rail');
const fh = frameFor(seqs, full);
L.dropSeqRail.draw(fh);
const hx = fh.timeToX(87070);
const h1 = L.dropSeqRail.hitTest(hx + 3, 17, fh);
ok(h1?.kind === 'drop-seq' && h1.key === 'drop:87070' && h1.handle === 'drop', 'the drop star selects its sequence');
ok(L.dropSeqRail.hitTest(hx, 4, fh) === null, 'above y 9 is left to his legacy ▼ triangles');
const fb = frameFor([s1], zoom);
const h2 = L.dropSeqBody.hitTest(X(81962) + 2, 150, fb);
ok(h2?.handle === 'lull' && h2.key === 'drop:87070', 'the lull line selects it too');
ok(L.dropSeqBody.hitTest(X(81962) + 30, 150, fb) === null, 'empty graph hits nothing');
ok(L.dropSeqBody.tooltipAt(X(87070), 262, fb)?.startsWith('bass spike · 1:27.07 · rise 0.90'),
  L.dropSeqBody.tooltipAt(X(87070), 262, fb));
const fnc = frameFor([], { startMs: 0, endMs: 60000 });
ok(L.dropSeqBody.tooltipAt(fnc.timeToX(5000), 120, fnc)?.startsWith('not captured'),
  'before a mid-song capture: "not captured"');

console.log('§15 a frame with no drop layer reserves nothing');
ok(!L.dropSeqBody.visible({ data: {} }) && L.dropSeqBody.hitTest(10, 100, { data: {}, mainH: 260, railH: 0 }) === null,
  'invisible and never hit');

rmSync(tmp, { recursive: true, force: true });
if (failures) {
  console.log(`\n${failures} check(s) FAILED`);
  process.exit(1);
}
console.log('\nOK: the drop-sequence view and layer behave as specified.');
