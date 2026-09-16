/**
 * Executable spec for how the debug page names an `xcorr_spike`.
 *
 * Transpiles the REAL frontend modules — web/src/debug/spikeLine.ts and its
 * ported twin spectra/web/src/debug/spikeLine.ts — with esbuild and drives
 * them, so this cannot drift from what ships and the two stacks cannot drift
 * from each other. Zero network: nothing here can reach his running apps.
 *
 * Two things send a spike: the post-lock drift monitor, after it CONFIRMED a
 * mismatch (no `source`), and the keep-searching sweep on a song that never
 * locked (`source: "keep_searching"`). The page used to print every one under
 * "Mismatch spikes (recovery windows)", so a song still searching read as a
 * confirmed mismatch that fired a recovery.
 *
 * Proves, for BOTH copies:
 *   ONE   — a monitor spike reads exactly as it did before: its line is the
 *           pre-change formula (carried below verbatim from useDebugFeeds.ts)
 *           and the panel keeps "Mismatch spikes (recovery windows)".
 *   TWO   — a keep-searching spike reads differently and accurately: it says
 *           it is the keep-searching sweep and that no mismatch was confirmed,
 *           and a panel holding one never claims to hold recovery windows only.
 *   THREE — a mixed log, and a spike from a source this page does not know,
 *           never borrow the monitor's heading.
 *   FOUR  — the two copies agree on every input.
 *
 * Run: node scripts/check_debug_spike_lines.mjs
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const COPIES = {
  web: path.join(REPO, 'web/src/debug/spikeLine.ts'),
  spectra: path.join(REPO, 'spectra/web/src/debug/spikeLine.ts'),
};

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};
const eq = (got, want, msg) => ok(got === want, `${msg}  (got ${JSON.stringify(got)})`);

const tmp = mkdtempSync(path.join(tmpdir(), 'spikeline-'));
const mods = {};
for (const [name, ts] of Object.entries(COPIES)) {
  const js = path.join(tmp, `${name}.mjs`);
  execFileSync('npx', ['esbuild', ts, '--format=esm', `--outfile=${js}`], {
    cwd: path.join(REPO, 'web'), stdio: ['ignore', 'ignore', 'inherit'],
  });
  mods[name] = await import(js);
}

/* ── The line as it shipped BEFORE this change, verbatim from useDebugFeeds.ts ── */
const preChangeLine = (msg) =>
  `spike @${msg.spike_ms}ms → window [${msg.win_start}-${msg.win_end}] ` +
  `strength=${Number(msg.strength ?? 0).toFixed(2)}`;
const PRE_CHANGE_HEADING = { title: 'Mismatch spikes', note: '(recovery windows)' };

const URI = 'spotify:track:mayday';
const monitorSpike = {
  type: 'xcorr_spike', uri: URI, t_ms: 90_000, spike_ms: 86_000,
  win_start: 83_500, win_end: 88_500, strength: 0.8,
};
const searchSpike = { ...monitorSpike, source: 'keep_searching' };
const strangerSpike = { ...monitorSpike, source: 'something_new' };
const noStrength = { type: 'xcorr_spike', uri: URI, spike_ms: 40_000, win_start: 37_500, win_end: 42_500 };

for (const [name, m] of Object.entries(mods)) {
  const heading = (msgs) => m.spikeHeading(msgs.map((msg) => m.spikeKind(msg)));

  console.log(`\nONE — a monitor spike reads exactly as before (${name})`);
  for (const msg of [monitorSpike, noStrength, { ...monitorSpike, source: null }]) {
    eq(m.spikeLine(msg), preChangeLine(msg), 'the line is the pre-change formula');
  }
  eq(m.spikeLine(monitorSpike), 'spike @86000ms → window [83500-88500] strength=0.80', 'literally');
  eq(JSON.stringify(heading([monitorSpike, noStrength])), JSON.stringify(PRE_CHANGE_HEADING),
    'the panel is still "Mismatch spikes (recovery windows)"');
  eq(JSON.stringify(heading([])), JSON.stringify(PRE_CHANGE_HEADING),
    'and so is an empty panel');

  console.log(`\nTWO — a keep-searching spike reads as what it is (${name})`);
  const searchLine = m.spikeLine(searchSpike);
  ok(searchLine !== m.spikeLine(monitorSpike), `differs from the monitor line  (${searchLine})`);
  ok(searchLine.includes('keep-searching'), 'names the keep-searching sweep');
  ok(searchLine.includes('no mismatch confirmed'), 'says no mismatch was confirmed');
  ok(searchLine.includes('@86000ms → window [83500-88500] strength=0.80'), 'keeps the numbers');
  const searchHeading = heading([searchSpike]);
  ok(searchHeading.title !== PRE_CHANGE_HEADING.title && searchHeading.note !== PRE_CHANGE_HEADING.note,
    `the panel does not claim mismatch/recovery  (${searchHeading.title} ${searchHeading.note})`);
  ok(searchHeading.note.includes('no mismatch confirmed'), 'the panel says no mismatch was confirmed');

  console.log(`\nTHREE — mixed and unknown sources never borrow the monitor's heading (${name})`);
  for (const [label, msgs] of [
    ['mixed', [searchSpike, monitorSpike]],
    ['unknown source', [strangerSpike]],
    ['unknown + monitor', [monitorSpike, strangerSpike]],
  ]) {
    const h = heading(msgs);
    ok(h.title !== PRE_CHANGE_HEADING.title && h.note !== PRE_CHANGE_HEADING.note,
      `${label}: ${h.title} ${h.note}`);
  }
  const strangerLine = m.spikeLine(strangerSpike);
  ok(strangerLine !== m.spikeLine(monitorSpike) && strangerLine.includes('something_new'),
    `an unknown source is named, not passed off as recovery  (${strangerLine})`);
}

console.log('\nFOUR — the web and spectra copies agree');
const inputs = [monitorSpike, searchSpike, strangerSpike, noStrength];
for (const msg of inputs) {
  eq(mods.spectra.spikeLine(msg), mods.web.spikeLine(msg), `line for source=${msg.source ?? '∅'}`);
}
for (const kinds of [[], ['recovery'], ['keep_searching'], ['recovery', 'keep_searching'], ['other']]) {
  eq(JSON.stringify(mods.spectra.spikeHeading(kinds)), JSON.stringify(mods.web.spikeHeading(kinds)),
    `heading for [${kinds.join(', ')}]`);
}

rmSync(tmp, { recursive: true, force: true });
console.log(failures ? `\n${failures} FAILED` : '\nall passed');
process.exit(failures ? 1 : 0);
