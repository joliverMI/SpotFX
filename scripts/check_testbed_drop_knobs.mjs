/** No-DOM proof for the test bed's Drops lane controls —
 * spectra/web/src/testbed/dropKnobs.ts, the pure module DropKnobsPanel.tsx
 * and TestbedPage.tsx build the two drop-threshold sliders, the one-beat
 * tolerance default and "Use as room default" on. Same shape as
 * scripts/check_testbed_edge_knobs.mjs (this repo has no DOM test harness):
 * transpile the REAL module with esbuild and drive it.
 *
 * Run: node scripts/check_testbed_drop_knobs.mjs
 */
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'spectra/web/src/testbed/dropKnobs.ts');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const out = mkdtempSync(path.join(tmpdir(), 'testbed-drop-knobs-'));
const js = path.join(out, 'dropKnobs.mjs');
execFileSync('npx', ['esbuild', TS, '--format=esm', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const k = await import(js);

console.log('§1 defaults and bounds match RoomControlState.drop_confident_score / drop_suggested_score / drop_floor');
ok(k.DEFAULT_CONFIDENT_SCORE === 1.0, 'confident defaults to 1.0 (the plan\'s operating point)');
ok(k.DEFAULT_SUGGESTED_SCORE === 0.7, 'suggested defaults to 0.7');
ok(k.MIN_DROP_SCORE === 0.3 && k.MAX_DROP_SCORE === 2.0, 'tier bounds are 0.3-2.0');
ok(k.DEFAULT_DROP_FLOOR === 0.7, 'floor defaults to 0.7 (his own fallback — 0.95 kept none of his real drops)');
ok(k.MIN_DROP_FLOOR === 0.0 && k.MAX_DROP_FLOOR === 1.0, 'floor bounds are 0.0-1.0, a different scale');

console.log('§2 clampDropScore/clampDropFloor keep a slider inside its own bounds');
ok(k.clampDropScore(1.234, 1) === 1.23, 'rounds to hundredths');
ok(k.clampDropScore(0, 1) === 0.3 && k.clampDropScore(9, 1) === 2.0, 'clamps both ends');
ok(k.clampDropScore(NaN, 0.7) === 0.7, 'NaN falls back, never NaN');
ok(k.clampDropFloor(1.5, 0.95) === 1.0 && k.clampDropFloor(-1, 0.95) === 0.0, 'floor clamps to 0.0-1.0');
ok(k.clampDropFloor(NaN, 0.95) === 0.95, 'floor NaN falls back, never NaN');

console.log('§3 the sliders show only for a drops lane');
ok(k.dropKnobsRelevant([{ engine: 'drops', kind: 'lull' }, null]), 'a drops lane in slot A shows them');
ok(k.dropKnobsRelevant([{ engine: 'librosa', kind: 'beat' }, { engine: 'drops', kind: 'drop' }]),
  'a drops lane in slot B shows them');
ok(!k.dropKnobsRelevant([{ engine: 'edges', kind: 'bass_up' }, null]), 'no drops lane, no sliders');
ok(k.isDropKind('drop_confident') && k.isDropKind('charge') && !k.isDropKind('beat'),
  'drop kinds are recognised, others are not');

console.log('§4 a Drops lane is scored at one beat');
ok(k.oneBeatToleranceMs(120, 100, 3000) === 500, '120 bpm -> 500 ms');
ok(k.oneBeatToleranceMs(143.55, 100, 3000) === 418, 'Dopamine\'s tempo -> 418 ms');
ok(k.oneBeatToleranceMs(null, 100, 3000) === 500, 'no tempo -> 500 ms');
ok(k.oneBeatToleranceMs(10, 100, 3000) === 3000, 'clamped to the slider\'s ceiling');

console.log('§5 "Use as room default" writes and names only what moved');
const room = { confident: 1.0, suggested: 0.7, floor: 0.95 };
ok(!k.dropDefaultsDiffer({ confident: 1.0, suggested: 0.7, floor: 0.95 }, room), 'synced sliders do not differ');
ok(!k.dropDefaultsDiffer({ confident: 1.5, suggested: 0.7, floor: 0.95 }, null), 'room still loading reads as no difference');
const moved = { confident: 1.1, suggested: 0.7, floor: 0.95 };
ok(k.dropDefaultsDiffer(moved, room), 'a moved slider differs');
ok(JSON.stringify(k.dropRoomControlsPatch(moved, room)) === JSON.stringify({ drop_confident_score: 1.1 }),
  'the patch carries only the moved threshold');
const msg = k.dropUseAsRoomDefaultConfirmMessage(moved, room);
ok(msg.includes('confident from 1.10') && !msg.includes('suggested from') && !msg.includes('energy floor from'),
  'the confirmation names only the moved threshold');
ok(msg.includes('next time it plays') && msg.includes('Nothing fires'),
  'the confirmation says when it takes effect and that nothing fires');
ok(Object.keys(k.dropRoomControlsPatch(room, room)).length === 0, 'nothing moved -> empty patch');

console.log('§6 the energy floor moves independently of the two tier thresholds');
const movedFloor = { confident: 1.0, suggested: 0.7, floor: 0.5 };
ok(k.dropDefaultsDiffer(movedFloor, room), 'a moved floor differs');
ok(JSON.stringify(k.dropRoomControlsPatch(movedFloor, room)) === JSON.stringify({ drop_floor: 0.5 }),
  'the patch carries only the moved floor');
const floorMsg = k.dropUseAsRoomDefaultConfirmMessage(movedFloor, room);
ok(floorMsg.includes('energy floor from 0.50') && !floorMsg.includes('confident from') && !floorMsg.includes('suggested from'),
  'the confirmation names only the moved floor');
const movedBoth = { confident: 1.1, suggested: 0.7, floor: 0.5 };
ok(JSON.stringify(k.dropRoomControlsPatch(movedBoth, room))
  === JSON.stringify({ drop_confident_score: 1.1, drop_floor: 0.5 }),
  'two moved knobs both land in the patch');

if (failures) {
  console.log(`\n${failures} check(s) FAILED`);
  process.exit(1);
}
console.log('\nOK');
