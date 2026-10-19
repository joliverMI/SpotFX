/**
 * Executable spec for the ONE phase-arm button's rule
 * (spectra/web/src/lightshow/phaseArmCycle.ts) — his ask, 2026-10-19:
 * "add a button for next drop, lull, and charge. make it one button that
 * cycles through those to reduce clutter. use thr icons and colors from
 * the timeline for those events."
 *
 * Transpiles the REAL module with esbuild (so the cycle order, the
 * icon/colour pairing and the wording are the shipped ones, not a copy),
 * zero DOM, zero network.
 *
 *   ONE   — the cycle is off → drop → lull → charge → off, HIS order, and
 *           it reads its current place from live arms rather than a flag.
 *   TWO   — a tap DISARMS whatever phase the set is on before arming the
 *           next: show_arms only replaces an arm on the SAME trigger, so
 *           without that the set would end up armed on two phases at once.
 *   THREE — the look comes from the TIMELINE: iconRegistry's own generic
 *           phase glyph, and timeline/dropSequences' own PHASE_COLOR.
 *           "Imported, never copied" is proven BEHAVIOURALLY, by bundling
 *           the module against a STUBBED Timeline whose colours are
 *           sentinels and watching the button return them — a copied hex
 *           (even one that happens to match today's value) returns the
 *           real colour there and fails. That is strictly stronger than
 *           the source-text grep this section used to carry: it also
 *           accepts a legitimate re-export through another module, which
 *           a grep for the import path would have failed.
 *   FOUR  — the words name the phase (never the colour alone), say what
 *           the next tap does, and tell "no drop on this song" from
 *           "not worked out yet" without guessing.
 *
 * Run: node scripts/check_phase_arm_cycle.mjs
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'spectra/web/src/lightshow/phaseArmCycle.ts');
const DROP_TS = path.join(REPO, 'spectra/web/src/timeline/dropSequences.ts');
let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};
const tmp = mkdtempSync(path.join(tmpdir(), 'phasearm-'));
const js = path.join(tmp, 'phaseArmCycle.mjs');
execFileSync('npx', ['esbuild', TS, '--bundle', '--format=esm', '--log-level=error', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const {
  PHASE_CYCLE, PHASE_ICON, phaseArmed, nextPhase, cycleActions, phaseButtonLook, phaseNote,
} = await import(js);

const arm = (id, on) => ({ id, on, label: 'Quiet Hues', set_id: 's1' });

console.log('ONE — the cycle, in his order, read off live arms');
ok(JSON.stringify(PHASE_CYCLE) === JSON.stringify(['drop', 'lull', 'charge']),
  `drop, then lull, then charge (${PHASE_CYCLE.join(' → ')})`);
ok(nextPhase(null) === 'drop', 'off → next drop');
ok(nextPhase('drop') === 'lull', 'drop → next lull');
ok(nextPhase('lull') === 'charge', 'lull → next charge');
ok(nextPhase('charge') === null, 'charge → off (the cycle closes)');
ok(nextPhase('scene_change') === 'drop', 'anything unexpected restarts at drop, never throws');
ok(phaseArmed([]) === null, 'no arms: off');
ok(phaseArmed(['scene_change', 'high', 'low']) === null,
  'the other three triggers are NOT this button: still off');
ok(phaseArmed(['lull']) === 'lull', 'a lull arm reads as lull — from `arms`, not a click');
ok(phaseArmed(['charge', 'lull']) === 'lull',
  'armed on two at once (possible from Sonic): the earliest in the cycle wins, so the next tap is defined');

console.log('TWO — a tap disarms the current phase before arming the next');
let act = cycleActions([]);
ok(act.arm === 'drop' && act.disarmIds.length === 0, 'from off: arm drop, nothing to cancel');
act = cycleActions([arm('a-drop', 'drop')]);
ok(act.arm === 'lull' && JSON.stringify(act.disarmIds) === JSON.stringify(['a-drop']),
  'from drop: cancel the drop arm AND arm the lull (never both armed at once)');
act = cycleActions([arm('a-charge', 'charge')]);
ok(act.arm === null && JSON.stringify(act.disarmIds) === JSON.stringify(['a-charge']),
  'from charge: cancel it and arm nothing — the button is off again');
act = cycleActions([arm('a-sc', 'scene_change'), arm('a-hi', 'high'), arm('a-drop', 'drop')]);
ok(act.arm === 'lull' && JSON.stringify(act.disarmIds) === JSON.stringify(['a-drop']),
  'the set\'s OTHER arms (scene change, High) are left completely alone');
act = cycleActions([arm('x1', 'drop'), arm('x2', 'lull')]);
ok(JSON.stringify(act.disarmIds) === JSON.stringify(['x1', 'x2']),
  'a set somehow armed on two phases has BOTH cancelled, so one tap always leaves exactly one');

console.log('THREE — the glyph and the colours are the Timeline\'s own');
ok(PHASE_ICON === 'pulse', `the generic drop-sequence phase glyph (${PHASE_ICON})`);
const dropJs = path.join(tmp, 'dropSequences.mjs');
execFileSync('npx', ['esbuild', DROP_TS, '--bundle', '--format=esm', '--log-level=error', `--outfile=${dropJs}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const { PHASE_COLOR } = await import(dropJs);
for (const p of PHASE_CYCLE) {
  const look = phaseButtonLook([arm('a', p)], 'Quiet Hues');
  ok(look.color === PHASE_COLOR[p],
    `armed on ${p}: the button wears the Timeline's ${p} colour (${look.color})`);
  ok(look.icon === PHASE_ICON, `armed on ${p}: the Timeline's phase glyph`);
}
const off = phaseButtonLook([], 'Quiet Hues');
ok(off.color === undefined && off.phase === null,
  'off: no colour of its own, so it keeps the shared unarmed look');
ok(new Set(PHASE_CYCLE.map((p) => PHASE_COLOR[p])).size === 3,
  'the three colours are genuinely different from each other');

// IMPORTED, NOT COPIED — behaviourally. Rebuild the SAME module with the
// Timeline's own module replaced by a stub whose colours are sentinels:
// a module that reads the Timeline's definition returns the sentinels, and
// one carrying its own copy of the hex values returns those instead. This
// catches a copy that happens to match today's values (which comparing
// against the real PHASE_COLOR above cannot) and, unlike a grep for the
// import path, still passes if PHASE_COLOR is legitimately re-exported
// through another module.
const SENTINEL = { drop: '#010203', lull: '#040506', charge: '#070809' };
const stubPath = path.join(tmp, 'stubDropSequences.mjs');
writeFileSync(stubPath, `export const PHASE_COLOR = ${JSON.stringify(SENTINEL)};\n`);
const stubbedJs = path.join(tmp, 'phaseArmCycle.stubbed.mjs');
// esbuild's --alias only rewrites BARE specifiers, so the swap is an
// onResolve plugin (the JS API) — check_light_show_pickers.mjs's own
// stub-a-module precedent.
const esbuild = createRequire(path.join(REPO, 'spectra/web/package.json'))('esbuild');
const stubBuild = await esbuild.build({
  entryPoints: [TS], bundle: true, format: 'esm', outfile: stubbedJs,
  logLevel: 'silent', absWorkingDir: path.join(REPO, 'spectra/web'),
  plugins: [{
    name: 'stub-timeline-phase-colour',
    setup(b) {
      b.onResolve({ filter: /timeline\/dropSequences$/ }, () => ({ path: stubPath }));
    },
  }],
});
ok(stubBuild.errors.length === 0, 'the module re-bundles against a stubbed Timeline');
const stubbed = await import(stubbedJs);
const viaStub = PHASE_CYCLE.map((p) => stubbed.phaseButtonLook([arm('a', p)], 'X').color);
ok(JSON.stringify(viaStub) === JSON.stringify(PHASE_CYCLE.map((p) => SENTINEL[p])),
  `each colour is READ from the Timeline's module, not copied (stubbed: ${viaStub.join(', ')})`);
ok(!viaStub.some((c) => Object.values(PHASE_COLOR).includes(c)),
  'and none of the real hex values survives the stub — nothing is hardcoded here');

console.log('FOUR — the words');
const dropLook = phaseButtonLook([arm('a', 'drop')], 'Quiet Hues');
ok(dropLook.ariaLabel.includes('Quiet Hues') && dropLook.ariaLabel.includes('next drop'),
  `the accessible label names the set and the phase: "${dropLook.ariaLabel}"`);
ok(!/gold|magenta|sky|blue|colour|color/i.test(dropLook.ariaLabel),
  'and never leans on the colour alone to say which phase it is');
ok(dropLook.title.includes('next lull'), `hover says what the next tap does: "${dropLook.title}"`);
ok(off.title.includes('next drop') && off.ariaLabel.includes('next drop'),
  `off: both say it will arm the next drop ("${off.title}")`);
ok(phaseButtonLook([arm('a', 'charge')], 'X').title.includes('turn it off'),
  'on the last phase, hover says the next tap turns it off');
ok(phaseNote('drop', null) === '' && phaseNote('drop', { known: false, counts: {}, next: {}, reason: 'x' }) === '',
  'phases not worked out yet: no claim at all, never a guessed zero');
ok(phaseNote('drop', { known: true, counts: { drop: 0 }, next: {}, reason: 'x' }).includes('no drop on this song'),
  'worked out and genuinely none: it SAYS the arm will just wait');
ok(phaseNote('drop', { known: true, counts: { drop: 13 }, next: {}, reason: null }).includes('13 drops'),
  'worked out with several: it says how many');
ok(phaseNote('lull', { known: true, counts: { lull: 1 }, next: {}, reason: null }).includes('1 lull on this song'),
  'one is singular, not "1 lulls"');
const noneHere = phaseButtonLook([arm('a', 'drop')], 'Quiet Hues',
  { known: true, counts: { drop: 0 }, next: {}, reason: 'this song has no charge, lull or drop' });
ok(noneHere.title.includes('no drop on this song'),
  `an armed button on a drop-less song says so on hover: "${noneHere.title}"`);

console.log(failures ? `\n${failures} FAILED` : '\nall passed');
process.exit(failures ? 1 : 0);
