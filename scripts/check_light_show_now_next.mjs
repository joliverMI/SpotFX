/** Executable spec for the one bar's Light Show slot (UI declutter plan
 * §3): `showNowNext()` in spectra/web/src/lightshow/showSummary.ts — pure,
 * no DOM, transpiled with esbuild and driven directly (the
 * check_charge_lull_blend_spans.mjs / check_timeline_touch_pan.mjs
 * pattern: real source, no DOM needed).
 *
 * Four rules, each asserted:
 *   1. A running sequence wins: current/next = its own items (by index),
 *      wrapping to the first item on a loop, or "End" at the tail with no
 *      loop.
 *   2. No sequence, arms exist: current/next = the two soonest-`due_ms`
 *      armed actions (nulls last); href = "/show?tab=run".
 *   3. Nothing armed: current/next both null; "Nothing armed" is the
 *      caller's job (LightShowStrip.tsx renders that text when current is
 *      null), not this function's.
 *   4. The holds badge count sums holds/levels/pulse_mods/flare_blocks/
 *      room_effect/running_sets from the brief.
 *
 * Run: node scripts/check_light_show_now_next.mjs
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

const out = mkdtempSync(path.join(tmpdir(), 'shownownext-'));
const js = path.join(out, 'showSummary.mjs');
execFileSync('npx', ['esbuild', TS, '--format=esm', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const { showNowNext } = await import(js);

const BRIEF = (over = {}) => ({
  active: true, holds: 2, levels: 1, pulse_mods: 0, flare_blocks: 0,
  running_sets: 0, room_effect: null, changed_settings: 0, armed: 0,
  playlist: null, standdown: null, refusal: null, ...over,
});

console.log('§1 a running sequence wins');
{
  const run = {
    id: 'r1', sequence_id: 's1', name: 'Seq', loop: false, state: 'running', active: true,
    index: 0, loops_done: 0, started_ms: 0, ended_ms: null, end_reason: '', paused_reason: '',
    awaiting_fire: false, firing: true, waiting_reason: '', wait_count: 0, waiting_for: '', log: [],
    items: [
      { kind: 'set', arm: 'instant', label: 'Boom', title: 'Boom' },
      { kind: 'wait', arm: 'instant', wait: { kind: 'duration', seconds: 30, trigger: 'scene_change', count: 0, songs: [] }, title: 'Wait' },
    ],
  };
  const r = showNowNext(BRIEF(), { armed: [], history: [], song: { uri: null, position_ms: null, cues: null, expected_scene_change_s: null, expected_scene_change_is_floor: false }, last_crossed: {}, refusal: null }, { run });
  ok(r.href === '/show?tab=sequence&sub=run', 'href is the sequence deep link while a sequence runs');
  ok(r.current?.label === 'Boom', 'current = the item at run.index');
  ok(r.next?.label === 'Wait', 'next = the following item');

  const runAtEndNoLoop = { ...run, index: 1 };
  const r2 = showNowNext(BRIEF(), { armed: [], history: [], song: { uri: null, position_ms: null, cues: null, expected_scene_change_s: null, expected_scene_change_is_floor: false }, last_crossed: {}, refusal: null }, { run: runAtEndNoLoop });
  ok(r2.next?.label === 'End', 'the last item of a non-looping sequence names "End" as next');

  const runLoop = { ...run, index: 1, loop: true };
  const r3 = showNowNext(BRIEF(), { armed: [], history: [], song: { uri: null, position_ms: null, cues: null, expected_scene_change_s: null, expected_scene_change_is_floor: false }, last_crossed: {}, refusal: null }, { run: runLoop });
  ok(r3.next?.label === 'Boom', 'a looping sequence wraps its next to item 0');
}

console.log('§2 no sequence, arms exist — soonest two by due_ms, nulls last');
{
  const arms = [
    { id: 'a', set_id: null, action: null, label: 'Late', on: 'high', repeat: false, song_uri: null, source: '', finish_on_mark: false, created_ms: 0, expires_ms: null, status: 'armed', fire_count: 0, ended_ms: null, end_reason: '', last_outcome: null, due_ms: 9000 },
    { id: 'b', set_id: null, action: null, label: 'Soonest', on: 'scene_change', repeat: false, song_uri: null, source: '', finish_on_mark: false, created_ms: 0, expires_ms: null, status: 'armed', fire_count: 0, ended_ms: null, end_reason: '', last_outcome: null, due_ms: 1000 },
    { id: 'c', set_id: null, action: null, label: 'Unknown', on: 'low', repeat: false, song_uri: null, source: '', finish_on_mark: false, created_ms: 0, expires_ms: null, status: 'armed', fire_count: 0, ended_ms: null, end_reason: '', last_outcome: null },
  ];
  const r = showNowNext(BRIEF(), { armed: arms, history: [], song: { uri: 'x', position_ms: 0, cues: null, expected_scene_change_s: null, expected_scene_change_is_floor: false }, last_crossed: {}, refusal: null }, { run: null });
  ok(r.href === '/show?tab=run', 'href is the plain Run page deep link');
  ok(r.current?.label === 'Soonest', 'current = the arm with the smallest due_ms');
  ok(r.next?.label === 'Late', 'next = the second-smallest');
}

console.log('§3 nothing armed');
{
  const r = showNowNext(BRIEF({ active: false, holds: 0, levels: 0 }), { armed: [], history: [], song: { uri: null, position_ms: null, cues: null, expected_scene_change_s: null, expected_scene_change_is_floor: false }, last_crossed: {}, refusal: null }, { run: null });
  ok(r.current === null && r.next === null, 'current and next are both null when nothing is armed');
}

console.log('§4 the holds badge sums the brief');
{
  const r = showNowNext(BRIEF({ holds: 2, levels: 1, pulse_mods: 3, flare_blocks: 1, room_effect: 'Wave', running_sets: 2 }), { armed: [], history: [], song: { uri: null, position_ms: null, cues: null, expected_scene_change_s: null, expected_scene_change_is_floor: false }, last_crossed: {}, refusal: null }, { run: null });
  ok(r.holdsCount === 2 + 1 + 3 + 1 + 1 + 2, `holdsCount sums every holding field (got ${r.holdsCount})`);
}

console.log(failures === 0 ? '\nPASS' : `\nFAIL (${failures})`);
process.exit(failures === 0 ? 0 : 1);
