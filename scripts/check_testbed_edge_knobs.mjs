/** Component-level proof for the music-analysis test bed's two new sliders
 * (Window/Sensitivity, data/transition-alignment-plan/report.md section 4,
 * ship task 2) — spectra/web/src/testbed/edgeKnobs.ts is the pure module
 * both TestbedMetricsPanel.tsx's sliders and TestbedPage.tsx's fetch wiring
 * are built on (clamping, defaults, and which A/B engine selection makes
 * the knobs relevant at all). This repo carries no DOM/component-rendering
 * test harness (no jsdom, no testing-library — see AGENTS.md's own "Tests"
 * section), so this follows the established precedent for this exact page
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

console.log('§5 knobsRelevant — the sliders show only while an `edges` lane is selected');
{
  ok(fe.knobsRelevant(['edges']) === true, "engine A alone set to 'edges' is relevant");
  ok(fe.knobsRelevant(['librosa', 'edges']) === true, "engine B set to 'edges' is relevant too");
  ok(fe.knobsRelevant(['librosa', 'beat_this']) === false, 'neither slot on edges is not relevant');
  ok(fe.knobsRelevant(['generator']) === false,
    "generator alone is NOT relevant yet — window_beats/sensitivity/direction are "
    + 'edges-only until a future task wires the R3 placement rule (report section 5 items 3-4)');
  ok(fe.knobsRelevant([null, undefined]) === false, 'an empty A/B selection is not relevant');
}

console.log(failures === 0 ? '\nAll checks passed.' : `\n${failures} check(s) FAILED.`);
process.exit(failures === 0 ? 0 : 1);
