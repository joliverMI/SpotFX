/** Component-level proof for the music-analysis test bed's sliders
 * (Window/Sensitivity/Direction, data/transition-alignment-plan/report.md
 * section 4 ship task 2; the "transitions per minute" density RATE knob
 * (2026-09-25, replacing the old flat "strongest N" per-song count) and
 * "Use as room default" button, section 5 ship task 4) — spectra/web/src/testbed/
 * edgeKnobs.ts is the pure module both TestbedMetricsPanel.tsx's sliders/
 * button and TestbedPage.tsx's fetch wiring are built on (clamping,
 * defaults, which A/B engine selection makes each knob relevant, the
 * confirm text and exact PUT payload the "Use as room default" button
 * sends). This repo carries no DOM/component-rendering test harness (no
 * jsdom, no testing-library — see AGENTS.md's own "Tests" section), so
 * this follows the established precedent for this exact page
 * (scripts/check_testbed_song_search.mjs, scripts/check_testbed_metrics.mjs):
 * transpile the REAL module with esbuild and drive it directly, no DOM.
 *
 * Run: node scripts/check_testbed_edge_knobs.mjs
 */
import { existsSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'spectra/web/src/testbed/edgeKnobs.ts');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const out = mkdtempSync(path.join(tmpdir(), 'testbed-edge-knobs-'));
const js = path.join(out, 'edgeKnobs.mjs');
execFileSync('npx', ['esbuild', TS, '--format=esm', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const fe = await import(js);

console.log('§1 default knobs match the backend defaults (spectra/services/rhythmic_edges.py)');
{
  ok(fe.DEFAULT_WINDOW_BEATS === 8, 'DEFAULT_WINDOW_BEATS is 8');
  ok(fe.DEFAULT_SENSITIVITY === 0.5, 'DEFAULT_SENSITIVITY is 0.5');
  ok(fe.DEFAULT_DIRECTION === 'both', 'DEFAULT_DIRECTION is "both"');
  ok(fe.MIN_WINDOW_BEATS === 1 && fe.MAX_WINDOW_BEATS === 16, 'window_beats bounds are 1-16');
  ok(fe.MIN_SENSITIVITY === 0.2 && fe.MAX_SENSITIVITY === 1.5, 'sensitivity bounds are 0.2-1.5');
  ok(JSON.stringify(fe.DIRECTIONS) === JSON.stringify(['both', 'up', 'down']),
    'DIRECTIONS is the three-way toggle\'s own option list, in order');
}

console.log('§2 clampWindowBeats — the slider can never drag a value outside its bounds');
{
  ok(fe.clampWindowBeats(8) === 8, 'a value already in range is unchanged');
  ok(fe.clampWindowBeats(0) === fe.MIN_WINDOW_BEATS, 'below the floor clamps to the floor');
  ok(fe.clampWindowBeats(-5) === fe.MIN_WINDOW_BEATS, 'a negative value clamps to the floor');
  ok(fe.clampWindowBeats(999) === fe.MAX_WINDOW_BEATS, 'above the ceiling clamps to the ceiling');
  ok(fe.clampWindowBeats(8.6) === 9, 'a fractional value rounds to the nearest whole beat');
  ok(fe.clampWindowBeats(NaN) === fe.DEFAULT_WINDOW_BEATS, 'NaN falls back to the default, never NaN itself');
}

console.log('§3 clampSensitivity');
{
  ok(fe.clampSensitivity(0.5) === 0.5, 'a value already in range is unchanged');
  ok(fe.clampSensitivity(0.0) === fe.MIN_SENSITIVITY, 'zero clamps to the floor');
  ok(fe.clampSensitivity(-1.0) === fe.MIN_SENSITIVITY, 'a negative value clamps to the floor');
  ok(fe.clampSensitivity(99.0) === fe.MAX_SENSITIVITY, 'a huge value clamps to the ceiling');
  ok(fe.clampSensitivity(NaN) === fe.DEFAULT_SENSITIVITY, 'NaN falls back to the default');
}

console.log('§4 clampDirection — the toggle can never resolve to a value outside its three options');
{
  ok(fe.clampDirection('both') === 'both', 'a valid value passes through unchanged');
  ok(fe.clampDirection('up') === 'up', "'up' passes through unchanged");
  ok(fe.clampDirection('down') === 'down', "'down' passes through unchanged");
  ok(fe.clampDirection('sideways') === fe.DEFAULT_DIRECTION,
    'an unrecognized value falls back to the default, never a raw pass-through');
  ok(fe.clampDirection('') === fe.DEFAULT_DIRECTION, 'an empty value falls back to the default');
}

console.log('§5 knobsRelevant — the sliders show while an `edges` lane, or the '
  + '`generator` engine\'s own `preview` kind, is selected (2026-09-23: the R3 '
  + 'placement rule reads the same three knobs)');
{
  ok(fe.knobsRelevant([{ engine: 'edges', kind: 'bass_up' }]) === true,
    "engine A alone set to 'edges' is relevant");
  ok(fe.knobsRelevant([{ engine: 'librosa', kind: 'beat' },
    { engine: 'edges', kind: 'gap_stop' }]) === true, "engine B set to 'edges' is relevant too");
  ok(fe.knobsRelevant([{ engine: 'librosa', kind: 'beat' },
    { engine: 'beat_this', kind: 'downbeat' }]) === false, 'neither slot on edges/generator:preview is not relevant');
  ok(fe.knobsRelevant([{ engine: 'generator', kind: 'preview' }]) === true,
    "generator's own 'preview' kind IS relevant — it now reflects the R3 placement rule");
  ok(fe.knobsRelevant([{ engine: 'generator', kind: 'stored' }]) === false,
    "generator's 'stored' kind is NOT relevant — it is exactly what is currently "
    + 'written, never recomputed with these knobs');
  ok(fe.knobsRelevant([null, undefined]) === false, 'an empty A/B selection is not relevant');
}

console.log('§6 the "transitions per minute" density RATE knob (default/bounds match '
  + "RoomControlState.transitions_per_minute's own Field(ge=1, le=30, default=8))");
{
  ok(fe.DEFAULT_TRANSITIONS_PER_MINUTE === 8, 'DEFAULT_TRANSITIONS_PER_MINUTE is 8');
  ok(fe.MIN_TRANSITIONS_PER_MINUTE === 1 && fe.MAX_TRANSITIONS_PER_MINUTE === 30,
    'transitions_per_minute bounds are 1-30');
  ok(fe.clampTransitionsPerMinute(8) === 8, 'a value already in range is unchanged');
  ok(fe.clampTransitionsPerMinute(0) === fe.MIN_TRANSITIONS_PER_MINUTE, 'below the floor clamps to the floor');
  ok(fe.clampTransitionsPerMinute(999) === fe.MAX_TRANSITIONS_PER_MINUTE, 'above the ceiling clamps to the ceiling');
  ok(fe.clampTransitionsPerMinute(NaN) === fe.DEFAULT_TRANSITIONS_PER_MINUTE, 'NaN falls back to the default');
}

console.log('§7 transitionsPerMinuteRelevant — narrower than knobsRelevant: only the '
  + "generator's own preview kind ranks/trims candidates, `edges` never does");
{
  ok(fe.transitionsPerMinuteRelevant([{ engine: 'generator', kind: 'preview' }]) === true,
    "generator's 'preview' kind is relevant");
  ok(fe.transitionsPerMinuteRelevant([{ engine: 'generator', kind: 'stored' }]) === false,
    "generator's 'stored' kind is NOT relevant — it is exactly what is currently written");
  ok(fe.transitionsPerMinuteRelevant([{ engine: 'edges', kind: 'bass_up' }]) === false,
    "an `edges` lane is NOT relevant — density has no meaning for edge detection");
  ok(fe.transitionsPerMinuteRelevant([{ engine: 'librosa', kind: 'beat' },
    { engine: 'generator', kind: 'preview' }]) === true, 'engine B alone on generator:preview is relevant too');
  ok(fe.transitionsPerMinuteRelevant([null, undefined]) === false, 'an empty A/B selection is not relevant');
}

console.log('§8 transitionDefaultsDiffer — the "differs from room default" highlight '
  + '(section 5 task 4 item (c))');
{
  const current = { windowBeats: 8, sensitivity: 0.5, transitionsPerMinute: 8 };
  ok(fe.transitionDefaultsDiffer(current, { windowBeats: 8, sensitivity: 0.5, transitionsPerMinute: 8 }) === false,
    'identical to the room default is not a difference');
  ok(fe.transitionDefaultsDiffer(current, { windowBeats: 2, sensitivity: 0.5, transitionsPerMinute: 8 }) === true,
    'a different windowBeats is a difference');
  ok(fe.transitionDefaultsDiffer(current, { windowBeats: 8, sensitivity: 0.8, transitionsPerMinute: 8 }) === true,
    'a different sensitivity is a difference');
  ok(fe.transitionDefaultsDiffer(current, { windowBeats: 8, sensitivity: 0.5, transitionsPerMinute: 6 }) === true,
    'a different transitionsPerMinute is a difference');
  ok(fe.transitionDefaultsDiffer(current, null) === false,
    'a not-yet-loaded room default (null) reads as no difference, never a false highlight');
  ok(fe.transitionDefaultsDiffer(current, undefined) === false,
    'undefined room default reads as no difference too');
}

console.log('§9 "Use as room default" — the confirm message and the exact PUT payload, '
  + 'both against a NON-DEFAULT room (section 5 task 4 item (a) + the partial-write fix); '
  + 'nothing is written until the caller actually PUTs this)');
{
  // A room already tuned away from the module defaults — the shape that
  // exposed the original bug: a page opening at the hardcoded 8/0.5/8
  // defaults would have read every one of these three as "differs" the
  // instant it loaded, with nothing dragged.
  const room = { windowBeats: 6, sensitivity: 0.7, transitionsPerMinute: 20 };

  const allThreeDiffer = { windowBeats: 4, sensitivity: 0.35, transitionsPerMinute: 14 };
  const msg = fe.useAsRoomDefaultConfirmMessage(allThreeDiffer, room);
  ok(typeof msg === 'string' && msg.length > 0, 'the confirm message is a real sentence');
  ok(msg.includes('4 beat'), 'the confirm message names the window value when it differs');
  ok(msg.includes('0.35'), 'the confirm message names the sensitivity value when it differs');
  ok(msg.includes('14'), 'the confirm message names the rate value when it differs');

  const singular = fe.useAsRoomDefaultConfirmMessage(
    { windowBeats: 1, sensitivity: room.sensitivity, transitionsPerMinute: room.transitionsPerMinute }, room,
  );
  ok(singular.includes('1 beat') && !singular.includes('1 beats'),
    'a single beat is grammatically singular');

  const patchAllThree = fe.roomControlsPatchForUseAsDefault(allThreeDiffer, room);
  ok(JSON.stringify(patchAllThree) === JSON.stringify({
    transition_window_beats: 4, transition_edge_sensitivity: 0.35, transitions_per_minute: 14,
  }), 'the PUT patch carries all three room-control fields when all three differ');
  ok(!('direction' in patchAllThree),
    'direction is deliberately excluded — it has no room-level setting');

  // The exact scenario the finding named: opens with non-default room
  // values, changes ONLY Window, confirms — the PUT must carry ONLY
  // transition_window_beats, and the confirm text must not claim the
  // other two are changing too.
  const onlyWindowDiffers = {
    windowBeats: 9, sensitivity: room.sensitivity, transitionsPerMinute: room.transitionsPerMinute,
  };
  const windowOnlyMsg = fe.useAsRoomDefaultConfirmMessage(onlyWindowDiffers, room);
  ok(windowOnlyMsg.includes('9 beat'), 'the confirm message names the changed Window value');
  ok(!windowOnlyMsg.includes(room.sensitivity.toFixed(2)),
    'the confirm message does not claim sensitivity is changing when it is untouched');
  ok(!/\btransitions per minute\b/i.test(windowOnlyMsg)
    && !windowOnlyMsg.includes(String(room.transitionsPerMinute)),
    'the confirm message does not claim the rate is changing when it is untouched');

  const patchWindowOnly = fe.roomControlsPatchForUseAsDefault(onlyWindowDiffers, room);
  ok(JSON.stringify(patchWindowOnly) === JSON.stringify({ transition_window_beats: 9 }),
    'the PUT patch carries ONLY transition_window_beats when only Window was changed');

  // Nothing changed at all — the button is disabled in this state, but the
  // pure functions themselves must still say so honestly rather than
  // silently writing/confirming a no-op.
  const noneDiffer = { ...room };
  const noneMsg = fe.useAsRoomDefaultConfirmMessage(noneDiffer, room);
  ok(noneMsg.toLowerCase().includes('nothing to change'),
    'an unchanged set of knobs reports nothing to change, rather than confirming a no-op write');
  const patchNone = fe.roomControlsPatchForUseAsDefault(noneDiffer, room);
  ok(Object.keys(patchNone).length === 0,
    'the PUT patch is empty when every knob already matches the room');
}

console.log(failures === 0 ? '\nAll checks passed.' : `\n${failures} check(s) FAILED.`);
process.exit(failures === 0 ? 0 : 1);
