/**
 * Executable spec for the Light Show's status wording
 * (spectra/web/src/lightshow/showSummary.ts) — the top-bar strip line and
 * the per-run report. Transpiles the REAL module with esbuild, zero network.
 *
 *   ONE   — the strip is ABSENT when the show holds nothing, and names every
 *           kind of thing it holds when it does (and a stand-down).
 *   TWO   — a partly-run set names the step that did not run and why.
 *   THREE — End show's sentence names what was put back AND what was left
 *           as he has it.
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'spectra/web/src/lightshow/showSummary.ts');
let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};
const tmp = mkdtempSync(path.join(tmpdir(), 'showsummary-'));
const js = path.join(tmp, 'showSummary.mjs');
execFileSync('npx', ['esbuild', TS, '--format=esm', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const { stripLine, runSummary, endShowSummary, armLine, armHistoryLine, countdown, cueLine, mmss } = await import(js);

console.log('ONE — the strip');
const idle = { active: false, holds: 0, levels: 0, running_sets: 0, room_effect: null,
  changed_settings: 0, standdown: null, refusal: null };
ok(stripLine(idle) === null, 'absent when the show holds nothing');
ok(stripLine(undefined) === null, 'absent when there is no status yet');
const busy = { ...idle, active: true, holds: 2, levels: 1, room_effect: 'Dim Wave',
  changed_settings: 3, standdown: 'a preview is holding the room' };
const line = stripLine(busy);
ok(line.includes('2 holding') && line.includes('1 level') && line.includes('Dim Wave')
   && line.includes('3 settings changed') && line.includes('standing down'), `names everything: ${line}`);

console.log('TWO — a partial run names the step that did not run');
const run = { name: 'Blackout', state: 'partial', steps: [
  { label: 'Display mode', status: 'applied', detail: '' },
  { label: 'Device state', status: 'failed', detail: "no fixture called 'ghost'" },
  { label: 'Flash', status: 'applied', detail: '' }] };
const s = runSummary(run);
ok(s.includes('2 of 3 ran') && s.includes('Device state did not run') && s.includes('ghost'), s);
ok(runSummary({ ...run, state: 'done' }).includes('all 3 ran'), 'a clean run says so');

console.log('THREE — End show');
const e = endShowSummary({ cancelled_runs: [], room_effect_stopped: true,
  released_devices: ['tv', 'sl'], restored: ['display mode'],
  left_alone: [{ key: 'room:scene_change_mode', label: 'scene change mode', reason: 'changed' }],
  failed: [] });
ok(e.includes('put back: display mode') && e.includes('left as you have it: scene change mode')
   && e.includes('2 fixture(s)') && e.includes('room effect stopped'), e);
ok(endShowSummary({ cancelled_runs: [], room_effect_stopped: false, released_devices: [],
  restored: [], left_alone: [], failed: [] }).includes('nothing to put back'), 'an empty End show says so');

console.log('FOUR — arms and the High/Low countdowns (phase 2)');
ok(stripLine({ ...idle, active: true, armed: 2 }).includes('2 armed'), 'the strip counts arms');
ok(mmss(65_400) === '1:05' && mmss(-5) === '0:00', 'm:ss, never negative');
ok(countdown(70_000, 60_000) === 'in 0:10', 'a countdown');
ok(countdown(50_000, 60_000) === null && countdown(null, 1) === null, 'passed or unknown = none');
const arm = { label: 'Reveal Crystal', on: 'high', repeat: false, fire_count: 0, song_uri: null,
  lead_ms: 2000, due_ms: 118_000, last_outcome: { status: 'waiting', reason: 'a preview is holding the room' } };
const al = armLine(arm, 100_000);
ok(al.includes('next High Trigger') && al.includes('once') && al.includes('2.0 s early')
   && al.includes('in 0:18') && al.includes('waited: a preview'), al);
ok(armLine({ ...arm, repeat: true, fire_count: 3, song_uri: 'x', this_song: true, lead_ms: 0,
  due_ms: null, last_outcome: null, on: 'scene_change' }, 0)
   .includes('repeat (3 so far) · this song only'), 'repeat and song scope');
ok(armHistoryLine({ label: 'X', on: 'low', status: 'missed', end_reason: 'its song ended before the trigger' })
   .includes('missed — its song ended'), 'history names why');
const cue = { level: 'high', timestamp_ms: 129_000, source: 'auto', runner_up_close: true };
ok(cueLine(cue, 120_000) === '2:09 (automatic) · in 0:09 · a runner-up is within 10%', cueLine(cue, 120_000));
ok(cueLine({ ...cue, source: 'moved' }, 130_000).includes('(moved by you) · passed'), 'a moved, passed cue');
ok(cueLine(null, 0) === 'none on this song', 'no cue');

if (failures) { console.log(`\n${failures} FAILED`); process.exit(1); }
console.log('\nall passed');
