/** Component-level proof for the Mode chip's hold-to-toggle gesture
 * (spectra/web/src/components/ModeChip.tsx, his ask 2026-10-06: "pressing
 * and holding the house mode button on the top bars should turn it on and
 * off"). spectra/web/src/components/modeChipHold.ts is the pure module the
 * component's tap/hold/toggle decisions are built on. This repo carries no
 * DOM/component-rendering test harness (AGENTS.md's own "Tests" section),
 * so this follows the established precedent for this exact page family
 * (scripts/check_house_summary.mjs, scripts/check_testbed_edge_knobs.mjs):
 * transpile the REAL module with esbuild and drive it directly, no DOM.
 *
 * Run: node scripts/check_mode_chip_hold.mjs
 */
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'spectra/web/src/components/modeChipHold.ts');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const out = mkdtempSync(path.join(tmpdir(), 'mode-chip-hold-'));
const js = path.join(out, 'modeChipHold.mjs');
execFileSync('npx', ['esbuild', TS, '--format=esm', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const m = await import(js);

console.log('§1 a short tap navigates; a completed hold does not (pointer path)');
{
  ok(m.shouldNavigateOnClick(false) === true, 'no hold fired — the click that follows a tap navigates');
  ok(m.shouldNavigateOnClick(true) === false, 'a hold fired — the trailing click is swallowed');
}

console.log('§2 keyboard: Enter/Space release navigates only when the hold did NOT complete');
{
  ok(m.shouldNavigateOnKeyUp('Enter', false) === true, 'short Enter press navigates');
  ok(m.shouldNavigateOnKeyUp(' ', false) === true, 'short Space press navigates');
  ok(m.shouldNavigateOnKeyUp('Enter', true) === false, 'a completed Enter hold does not also navigate');
  ok(m.shouldNavigateOnKeyUp(' ', true) === false, 'a completed Space hold does not also navigate');
  ok(m.shouldNavigateOnKeyUp('Tab', false) === false, 'an unrelated key never navigates');
}

console.log('§3 the tooltip carries the hold instruction alongside the existing chip title');
{
  const t = m.holdTooltip('Evening, set by Home Assistant. Resting.');
  ok(t.startsWith('Evening, set by Home Assistant. Resting.'), 'the base title survives verbatim');
  ok(t.includes('hold to turn house lighting on/off'), `names the gesture: "${t}"`);
}

console.log('§4 on/off toast wording and the PUT response reader');
{
  ok(m.toggleResultMessage(true) === 'House lighting turned on', 'turned on');
  ok(m.toggleResultMessage(false) === 'House lighting turned off', 'turned off');
  ok(m.toggleErrorMessage('refused').includes('refused'), 'a refusal names its own reason, never a silent/faked state');
  ok(m.resolveEnabledFromResponse({ settings: { enabled: false }, lighting: { enabled: true } }) === true,
    'the PUT response\'s own `lighting.enabled` (the confirmed state) wins when present');
  ok(m.resolveEnabledFromResponse({ settings: { enabled: true } }) === true,
    'no `lighting` key (nothing actually changed) falls back to `settings.enabled`, never a guess');
  ok(m.resolveEnabledFromResponse({ settings: { enabled: false }, lighting: null }) === false,
    'an explicit null `lighting` also falls back to `settings.enabled`');
}

console.log(failures === 0 ? '\nAll checks passed.' : `\n${failures} check(s) FAILED.`);
process.exit(failures === 0 ? 0 : 1);
