/** Executable spec for the charge/lull blend the timeline now draws.
 *
 * The graph's numbers must be the ENGINE's numbers. This script does not
 * re-derive them: it transpiles the REAL frontend module
 * (spectra/web/src/timeline/phaseBlend.ts) with esbuild and drives it, then
 * re-implements scene_response._phase_ramp_ms's arithmetic from the
 * constants read out of the Python source itself and asserts the two agree
 * on every case — so a constant drifting on either side goes red here.
 *
 * Read-only. Optionally sweeps his real trigger corpus
 * (storage/spectra/triggers.json) when one is reachable, to report how many
 * charge/lull spans the graph now draws that it previously drew as nothing.
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

// ── §4: his real corpus, when reachable ──────────────────────────────────
console.log('\n§4 AGAINST HIS REAL TRIGGER CORPUS');
const store = process.argv[2] || path.join(process.env.HOME || '', 'SpotFX/storage/spectra/triggers.json');
if (!existsSync(store)) {
  console.log(`  – skipped: no trigger store at ${store} (pass one as argv[1])`);
} else {
  const data = JSON.parse(readFileSync(store, 'utf8'));
  let phase = 0, stretched = 0, flat = 0, minGap = Infinity, maxGap = 0;
  for (const rows of Object.values(data)) {
    const enabled = rows.filter((t) => t.enabled).sort((a, b) => a.timestamp_ms - b.timestamp_ms);
    for (const t of enabled) {
      const a = t.action || {};
      if (a.kind !== 'fire_response' || !fe.isPhaseStretchClass(a.event_class)) continue;
      const next = enabled.find((n) => n.timestamp_ms > t.timestamp_ms);
      const s = fe.phaseBlendSpan(a.event_class, t.timestamp_ms, next ? next.timestamp_ms : null);
      phase += 1;
      if (s.stretched) {
        stretched += 1;
        minGap = Math.min(minGap, s.endMs - s.startMs);
        maxGap = Math.max(maxGap, s.endMs - s.startMs);
      } else flat += 1;
    }
  }
  console.log(`  charge/lull spans the graph now draws: ${phase}`
    + ` (${stretched} stretched to a real next trigger, ${flat} on the flat default)`);
  if (stretched) console.log(`  real stretched gaps range ${minGap}ms … ${maxGap}ms`
    + ' — no single constant fits that, which is why there is no knob');
  ok(phase > 0, 'his corpus really does carry charge/lull spans to draw');
}

console.log(failures ? `\nFAILED (${failures})` : '\nOK');
process.exit(failures ? 1 : 0);
