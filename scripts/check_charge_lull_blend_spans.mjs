/** Executable spec for the charge/lull blend the timeline now draws.
 *
 * The graph's numbers must be the ENGINE's numbers. This script does not
 * re-derive them: it transpiles the REAL frontend module
 * (spectra/web/src/timeline/phaseBlend.ts) with esbuild and drives it, then
 * re-implements scene_response._phase_ramp_ms's arithmetic from the
 * constants read out of the Python source itself and asserts the two agree
 * on every case — so a constant drifting on either side goes red here.
 *
 * WHERE A BUILD ENDS (2026-10-06, the PHASE PARTNER rule — spectra/services/
 * phase_partner.py): phaseBlend.ts mirrors phase_partner.build_target. That
 * mirror is held by running the REAL Python function over the same inputs —
 * fixed vectors in §4, and every charge/lull in his corpus in §6 — and
 * requiring the two answers to be identical, plus the rule's reach and
 * class order read out of the Python source. §5 drives both Timeline
 * surfaces that draw it (the SPECTRA trigger bar and the legacy canvas's
 * blend layer), bundled from their real modules.
 *
 * Read-only. Optionally sweeps his real trigger corpus
 * (storage/spectra/triggers.json) when one is reachable, to report how many
 * charge/lull spans the graph now draws, and how many the partner rule
 * moved out to their own lull or drop.
 *
 * Run: node scripts/check_charge_lull_blend_spans.mjs [path/to/triggers.json]
 */
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'spectra/web/src/timeline/phaseBlend.ts');
const PY = path.join(REPO, 'spectra/services/scene_response.py');
const PY_PARTNER = path.join(REPO, 'spectra/services/phase_partner.py');
const PY_HANDOFF = path.join(REPO, 'fx/effects/particle_handoff.py');
const VENV_PY = path.join(REPO, '.venv/bin/python');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

// ── load the REAL frontend module ────────────────────────────────────────
const out = mkdtempSync(path.join(tmpdir(), 'phaseblend-'));
const js = path.join(out, 'phaseBlend.mjs');
execFileSync('npx', ['esbuild', TS, '--format=esm', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const fe = await import(js);

// ── read the engine's own constants out of the Python source ─────────────
const py = readFileSync(PY, 'utf8');
const num = (re, name) => {
  const m = py.match(re);
  if (!m) { console.log(`  ✗ could not read ${name} from scene_response.py`); failures += 1; return NaN; }
  return Number(m[1]);
};
const PY_CHARGE = num(/PHASE_RAMP_MS = \{"charge": (\d+)/, 'PHASE_RAMP_MS[charge]');
const PY_LULL = num(/PHASE_RAMP_MS = \{"charge": \d+, "lull": (\d+)/, 'PHASE_RAMP_MS[lull]');
const PY_DROP = num(/PHASE_RAMP_MS = \{"charge": \d+, "lull": \d+, "drop": (\d+)/, 'PHASE_RAMP_MS[drop]');
const PY_HANG = num(/PHASE_RAMP_HANG_FRACTION = ([\d.]+)/, 'PHASE_RAMP_HANG_FRACTION');
const PY_MIN = num(/PHASE_RAMP_MIN_MS = (\d+)/, 'PHASE_RAMP_MIN_MS');
const PY_STRETCH = (py.match(/PHASE_RAMP_STRETCH_CLASSES = \(([^)]*)\)/) || [, ''])[1]
  .split(',').map((s) => s.trim().replace(/["']/g, '')).filter(Boolean);

console.log('\n§1 THE GRAPH USES THE ENGINE\'S OWN CONSTANTS');
ok(fe.PHASE_RAMP_MS.charge === PY_CHARGE, `charge default ${PY_CHARGE}ms`);
ok(fe.PHASE_RAMP_MS.lull === PY_LULL, `lull default ${PY_LULL}ms`);
ok(fe.PHASE_RAMP_MS.drop === PY_DROP, `drop default ${PY_DROP}ms`);
ok(fe.PHASE_RAMP_HANG_FRACTION === PY_HANG, `hang fraction ${PY_HANG}`);
ok(fe.PHASE_RAMP_MIN_MS === PY_MIN, `ramp floor ${PY_MIN}ms`);
ok(PY_STRETCH.length === 2 && PY_STRETCH.includes('charge') && PY_STRETCH.includes('lull'),
   'the engine stretches charge and lull, and only those');
ok(fe.isPhaseStretchClass('charge') && fe.isPhaseStretchClass('lull'), 'the graph agrees: charge/lull stretch');
ok(!fe.isPhaseStretchClass('drop') && !fe.isPhaseStretchClass('flare'),
   'the graph agrees: drop and flare never stretch');

// The partner rule's own numbers: the reach is the effects' charge/lull cap,
// and the class order is phase_partner.PHASE_ORDER.
const handoff = readFileSync(PY_HANDOFF, 'utf8');
const holdMax = Number((handoff.match(/PHASE_HOLD_MAX_S = ([\d.]+)/) || [])[1]);
ok(fe.PHASE_PARTNER_REACH_MS === Math.round(holdMax * 1000),
   `partner reach ${fe.PHASE_PARTNER_REACH_MS}ms = the effects' own ${holdMax}s charge/lull cap`);
const partnerSrc = readFileSync(PY_PARTNER, 'utf8');
ok(/PARTNER_REACH_MS: int = round\(PHASE_HOLD_MAX_S \* 1000\)/.test(partnerSrc),
   'the engine derives its reach from the same cap');
const pyOrder = Object.fromEntries([...(partnerSrc.match(/PHASE_ORDER[^=]*= \{([^}]*)\}/) || [, ''])[1]
  .matchAll(/"(\w+)": (\d+)/g)].map((m) => [m[1], Number(m[2])]));
ok(JSON.stringify(pyOrder) === JSON.stringify(fe.PHASE_ORDER),
   `class order ${JSON.stringify(fe.PHASE_ORDER)} matches phase_partner.PHASE_ORDER`);

// The REAL Python rule, run over a batch of cases — the mirror is held by
// answers, not by reading its source.
const pyTargets = (cases) => {
  const dir = mkdtempSync(path.join(tmpdir(), 'phasepartner-'));
  const inp = path.join(dir, 'cases.json');
  writeFileSync(inp, JSON.stringify(cases));
  const py = existsSync(VENV_PY) ? VENV_PY : 'python3';
  const code = [
    'import json, sys',
    `sys.path.insert(0, ${JSON.stringify(REPO)})`,
    'from spectra.services import phase_partner as pp',
    'cases = json.load(open(sys.argv[1]))',
    'out = []',
    'for c in cases:',
    '    t = pp.build_target(c["cls"], c["start"], [(m[0], m[1]) for m in c["later"]])',
    '    out.append({"ms": t.ms, "reason": t.reason, "targetClass": t.target_class})',
    'print(json.dumps(out))',
  ].join('\n');
  return JSON.parse(execFileSync(py, ['-c', code, inp], { encoding: 'utf8', maxBuffer: 1 << 28 }));
};
const tsTarget = (c) => fe.phaseBuildTarget(c.cls, c.start,
  c.later.map(([ms, phaseClass]) => ({ ms, phaseClass })));
const firstDisagreement = (cases, py) => {
  for (let i = 0; i < cases.length; i += 1) {
    const a = tsTarget(cases[i]);
    if (a.ms !== py[i].ms || a.reason !== py[i].reason || a.targetClass !== py[i].targetClass) {
      return `${JSON.stringify(cases[i])}: graph ${JSON.stringify(a)} vs engine ${JSON.stringify(py[i])}`;
    }
  }
  return null;
};

// ── §2: the ramp length, swept against a mirror of _phase_ramp_ms ────────
const engineRamp = (cls, gap) => (PY_STRETCH.includes(cls) && gap !== null && gap > 0
  ? Math.max(PY_MIN, Math.round(gap * (1 - PY_HANG)))
  : { charge: PY_CHARGE, lull: PY_LULL, drop: PY_DROP }[cls]);

console.log('\n§2 RAMP LENGTH MATCHES _phase_ramp_ms ACROSS THE WHOLE RANGE');
let mismatch = null;
for (const cls of ['charge', 'lull', 'drop']) {
  for (const gap of [null, 0, 1, 50, 199, 222, 223, 900, 2500, 6040, 60000, 300000]) {
    const a = fe.phaseRampMs(cls, gap);
    const b = engineRamp(cls, gap);
    if (a !== b && mismatch === null) mismatch = `${cls} gap=${gap}: graph ${a} vs engine ${b}`;
  }
}
ok(mismatch === null, mismatch ?? '36 (class, gap) cases agree exactly');
ok(fe.phaseRampMs('charge', 100) === PY_MIN,
   `a degenerate gap floors at ${PY_MIN}ms rather than a near-zero glide`);
ok(fe.phaseRampMs('lull', null) === PY_LULL,
   'an unknowable gap falls back to the flat class default, not a guess');

// ── §3: the drawn span ───────────────────────────────────────────────────
console.log('\n§3 THE DRAWN SPAN IS THE REAL STRETCH, NOT A NOMINAL WIDTH');
const his = fe.phaseBlendSpan('lull', 10_000, 16_040);   // his real 6040ms Dopamine lull
ok(his.endMs === 16_040, 'the span ends exactly at the next trigger (6040ms gap)');
ok(his.rampEndMs === 10_000 + 5436, 'the ramp is ~90% of the real gap (5436ms)');
ok(his.endMs - his.rampEndMs === 604, 'the hang is the remaining ~10% (604ms)');
ok(his.stretched === true, 'and it reports itself stretched');

const short = fe.phaseBlendSpan('lull', 0, 900);          // his other real lull, same song
ok(short.endMs === 900 && short.rampEndMs === 810,
   'the SAME class on the SAME song draws 900ms, not the 2500ms constant — the whole point');

const last = fe.phaseBlendSpan('charge', 200_000, null);
ok(last.endMs - last.startMs === PY_CHARGE,
   `a charge with no next trigger draws its flat ${PY_CHARGE}ms default`);
ok(last.rampEndMs === last.endMs && last.stretched === false,
   'and draws NO hang, and says it was not stretched — never a span to the song\'s end');

// ── §4: the partner rule, fixed vectors ─────────────────────────────────
console.log('\n§4 A BUILD RUNS TO ITS OWN LULL OR DROP, WHATEVER SITS BETWEEN');
const vectors = [
  { name: 'a flare inside a charge', cls: 'charge', start: 1000,
    later: [[3000, null], [8000, 'lull'], [9000, 'drop']], want: [8000, 'partner'] },
  { name: 'a scene change inside a charge', cls: 'charge', start: 1000,
    later: [[3500, null], [7000, 'drop']], want: [7000, 'partner'] },
  { name: 'a lull with an intervening flare', cls: 'lull', start: 2000,
    later: [[2500, null], [4000, 'drop']], want: [4000, 'partner'] },
  { name: 'no partner ahead: the next trigger, as before', cls: 'charge', start: 1000,
    later: [[3000, null], [5000, null]], want: [3000, 'next_trigger'] },
  { name: 'nothing ahead: the flat default', cls: 'lull', start: 1000,
    later: [], want: [null, 'none'] },
  { name: 'a later charge restarts, it is no partner', cls: 'charge', start: 1000,
    later: [[2000, null], [5000, 'charge'], [9000, 'drop']], want: [2000, 'next_trigger'] },
  { name: 'a charge restarts a lull', cls: 'lull', start: 1000,
    later: [[1500, null], [2000, 'charge'], [3000, 'drop']], want: [1500, 'next_trigger'] },
  { name: 'a partner exactly at the reach', cls: 'charge', start: 0,
    later: [[5000, null], [60000, 'drop']], want: [60000, 'partner'] },
  { name: 'a partner past the reach', cls: 'charge', start: 0,
    later: [[5000, null], [60001, 'drop']], want: [5000, 'next_trigger'] },
  { name: 'unsorted, with earlier moments', cls: 'charge', start: 5000,
    later: [[9000, 'drop'], [1000, 'lull'], [5000, 'lull'], [6000, null]], want: [9000, 'partner'] },
  { name: 'a drop never builds', cls: 'drop', start: 0, later: [[100, null]], want: [null, 'none'] },
];
const pyVec = pyTargets(vectors);
for (const v of vectors) {
  const t = tsTarget(v);
  ok(t.ms === v.want[0] && t.reason === v.want[1], `${v.name} → ${t.reason} @ ${t.ms}`);
}
const vecMismatch = firstDisagreement(vectors, pyVec);
ok(vecMismatch === null, vecMismatch ?? `the graph and the engine's own phase_partner.build_target agree on all ${vectors.length} vectors`);
const flareInCharge = fe.phaseBlendSpanFor('charge', 1000, [{ ms: 3000, phaseClass: null },
  { ms: 9000, phaseClass: 'drop' }]);
ok(flareInCharge.endMs === 9000 && flareInCharge.rampEndMs === 1000 + 7200
   && flareInCharge.buildsTo.reason === 'partner',
   'the drawn span runs 8000ms to the drop (ramp 7200, hang 800), not 2000ms to the flare');

// ── §5: the two Timeline surfaces that draw it ───────────────────────────
// Both callers bundled from their REAL modules and driven with a flare inside
// a charge — the SPECTRA trigger bar and the legacy canvas's blend layer.
console.log('\n§5 BOTH TIMELINE SURFACES DRAW THE PARTNER SPAN');
const bundle = (rel, name) => {
  const outfile = path.join(out, name);
  execFileSync('npx', ['esbuild', path.join(REPO, rel), '--bundle', '--format=esm',
    '--platform=node', '--log-level=error', `--outfile=${outfile}`], {
    cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
  });
  return import(outfile);
};
const bar = await bundle('spectra/web/src/timeline/components/SpectraTriggerBar.tsx', 'bar.mjs');
const resp = (id, ms, cls, enabled = true) => ({ id, timestamp_ms: ms, enabled,
  action: { kind: 'fire_response', event_class: cls, intensity: 0.5 } });
const barSong = [resp('c', 1000, 'charge'), resp('f', 3000, 'flare'),
  { id: 's', timestamp_ms: 5000, enabled: true, action: { kind: 'fire_scene', scene_id: null, intensity: 0.5 } },
  resp('l', 8000, 'lull'), resp('d', 9000, 'drop'), resp('x', 12000, 'charge'), resp('y', 13000, 'flare')];
const barSpans = Object.fromEntries(bar.phaseBlendSpans(barSong).map((b) => [b.triggerId, b]));
ok(barSpans.c.endMs === 8000 && barSpans.c.buildsTo.reason === 'partner',
   'trigger bar: the charge spans to its own lull at 8000ms, past the flare and the scene change');
ok(barSpans.l.endMs === 9000, 'trigger bar: the lull spans to its own drop');
ok(barSpans.x.endMs === 13000 && barSpans.x.buildsTo.reason === 'next_trigger',
   'trigger bar: a lone charge still spans to the next trigger, as before');
ok(bar.blendNote(barSpans.c).includes('to its lull')
   && bar.blendNote(barSpans.x).includes('to the next trigger'),
   'the hover note names what each build ends on');

const canvas = await bundle('spectra/web/src/timeline/canvas/data.ts', 'canvasdata.mjs');
const ev = { ec: 'charge', ef: 'single', el: 'lull', ed: 'drop' };
const mt = (id, ms, eventId) => ({ id, timestamp_ms: ms, event_id: eventId, enabled: true });
const legacy = [mt('a', 1000, 'ec'), mt('b', 2500, 'ef'), mt('c', 6000, 'ed')];
const cspans = canvas.computeBlendSpans(legacy, 200000, (id) => ev[id]);
ok(cspans.length === 1 && cspans[0].endMs === 6000 && cspans[0].source === 'phase',
   'legacy canvas: the charge spans 5000ms to its own drop, not 1500ms to the single event');

// ── §6: his real corpus, when reachable ──────────────────────────────────
console.log('\n§6 AGAINST HIS REAL TRIGGER CORPUS');
const store = process.argv[2] || path.join(process.env.HOME || '', 'SpotFX/storage/spectra/triggers.json');
if (!existsSync(store)) {
  console.log(`  – skipped: no trigger store at ${store} (pass one as argv[1])`);
} else {
  const data = JSON.parse(readFileSync(store, 'utf8'));
  const phaseOf = (t) => {
    const a = t.action || {};
    return a.kind === 'fire_response' && fe.isPhaseClass(a.event_class) ? a.event_class : null;
  };
  let phase = 0, stretched = 0, flat = 0, minGap = Infinity, maxGap = 0, moved = 0;
  const cases = [];
  for (const rows of Object.values(data)) {
    const enabled = rows.filter((t) => t.enabled).sort((a, b) => a.timestamp_ms - b.timestamp_ms);
    for (const t of enabled) {
      const a = t.action || {};
      if (a.kind !== 'fire_response' || !fe.isPhaseStretchClass(a.event_class)) continue;
      const later = enabled.filter((n) => n.id !== t.id)
        .map((n) => ({ ms: n.timestamp_ms, phaseClass: phaseOf(n) }));
      cases.push({ cls: a.event_class, start: t.timestamp_ms, later: later.map((m) => [m.ms, m.phaseClass]) });
      const s = fe.phaseBlendSpanFor(a.event_class, t.timestamp_ms, later);
      const next = enabled.find((n) => n.timestamp_ms > t.timestamp_ms);
      const old = fe.phaseBlendSpan(a.event_class, t.timestamp_ms, next ? next.timestamp_ms : null);
      if (old.endMs !== s.endMs) moved += 1;
      phase += 1;
      if (s.stretched) {
        stretched += 1;
        minGap = Math.min(minGap, s.endMs - s.startMs);
        maxGap = Math.max(maxGap, s.endMs - s.startMs);
      } else flat += 1;
    }
  }
  console.log(`  charge/lull spans the graph now draws: ${phase}`
    + ` (${stretched} stretched to a real later trigger, ${flat} on the flat default)`);
  console.log(`  spans the partner rule moved out to their own lull or drop: ${moved}`
    + ' (every enabled trigger counted, as the graph draws them — the engine\'s own'
    + ' per-mode count is scripts/check_phase_partner_library.py)');
  if (stretched) console.log(`  real stretched gaps range ${minGap}ms … ${maxGap}ms`
    + ' — no single constant fits that, which is why there is no knob');
  ok(phase > 0, 'his corpus really does carry charge/lull spans to draw');
  const corpusMismatch = firstDisagreement(cases, pyTargets(cases));
  ok(corpusMismatch === null, corpusMismatch
    ?? `the graph and the engine's own rule agree on every one of his ${cases.length} charge/lull builds`);
}

console.log(failures ? `\nFAILED (${failures})` : '\nOK');
process.exit(failures ? 1 : 0);
