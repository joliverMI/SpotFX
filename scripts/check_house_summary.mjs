/** House lighting's words (spectra/web/src/house/houseSummary.ts) — the
 * Mode chip and the House page's Now panel both read them, so one table of
 * inputs drives both. No DOM harness exists in this repo (AGENTS.md
 * "Tests"), so this follows the established precedent: transpile the REAL
 * module with esbuild and drive it directly.
 *
 * Run: node scripts/check_house_summary.mjs
 */
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'spectra/web/src/house/houseSummary.ts');
let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};
const out = mkdtempSync(path.join(tmpdir(), 'house-summary-'));
const js = path.join(out, 'houseSummary.mjs');
execFileSync('npx', ['esbuild', TS, '--format=esm', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const hs = await import(js);

const base = {
  mode: { id: 'm1', name: 'Evening' }, source: 'ha', since_ms: 1, manual: false,
  ha_value: 'Evening', ha_value_ms: 1, ha_mapped_mode: 'Evening', active: true,
  phase: 'resting', reason: 'mode change', problems: [], recent: [],
};

console.log('§1 the chip says which mode, who set it, and whether it is on the room');
{
  const c = hs.chipLine(base);
  ok(c.text === 'Mode: Evening · HA' && c.tone === 'on', `resting from HA: "${c.text}"`);
  const m = hs.chipLine({ ...base, source: 'spectra', manual: true });
  ok(m.text === 'Mode: Evening · manual', `a person's pick says manual: "${m.text}"`);
  const music = hs.chipLine({ ...base, phase: 'music' });
  ok(music.tone === 'music' && music.text.endsWith('♪'), `music: "${music.text}"`);
  const off = hs.chipLine({ ...base, phase: 'inactive', active: false, reason: 'the room is released' });
  ok(off.tone === 'idle' && off.text.includes('not applied'), `inactive: "${off.text}"`);
  ok(off.title.includes('the room is released'), 'the title carries the reason');
  const none = hs.chipLine({ ...base, mode: null, ha_value: 'Party', ha_mapped_mode: null });
  ok(none.text === 'Mode: none' && none.title.includes('no mode answers to it'),
    'no mode: says so, and names an unmapped HA word');
  ok(hs.chipLine(undefined).text === 'Mode: …', 'no status yet: never a guess');
}

console.log('§2 the phase sentence never claims more than the status says');
{
  ok(hs.phaseLine({ ...base, mode: null }).startsWith('No house mode'), 'no mode');
  ok(hs.phaseLine(base).startsWith('Resting'), 'resting');
  const back = hs.phaseLine({ ...base, phase: 'music', music: { playing: false, policy: 'show', hue: 'hold', returns_in_s: 41.2 } });
  ok(back.startsWith('Music stopped') && back.includes('in 42 s'), `music stopped counts down: "${back}"`);
  ok(hs.phaseLine({ ...base, phase: 'music', music: { playing: true, policy: 'show', hue: 'hold', returns_in_s: null } })
    .startsWith('Music is playing'), 'music playing says so');
  ok(hs.phaseLine({ ...base, phase: 'standby', reason: 'a preview is holding the room' })
    .includes('a preview is holding the room'), 'standby names what holds the room');
  ok(hs.phaseLine({ ...base, phase: 'inactive', reason: 'the room is released' })
    .includes('applies when SPECTRA holds the room'), 'inactive says when it will apply');
  ok(hs.manualLine(base) === null, 'an HA-set mode has no manual line');
  ok(hs.manualLine({ ...base, manual: true }).startsWith('Picked by hand'), 'a manual one does');
}

console.log('§3 a new mode starts with the backend\'s own defaults');
{
  const b = hs.blankMode('X');
  ok(b.transitions.clock_glide_s === 90 && b.transitions.button_glide_s === 5
    && b.transitions.music_debounce_s === 60 && b.transitions.music_return_glide_s === 20,
    'glides 90 / 5 / 60 / 20 (spectra/models/house_mode.py HouseTransitions)');
  ok(b.flow.scene_every_min === 45 && b.flow.journey_deg_per_min === 15 && b.flow.intensity === 0.25,
    'flow 45 min / 15°/min / 0.25');
  ok(b.music === 'show' && b.music_hue === 'hold', 'music: full show, Hue held');
}

console.log('§4 the colour-temperature swatch is warm at 2000 K and neutral at 6500 K');
{
  const warm = hs.kelvinToHex(2000);
  const cool = hs.kelvinToHex(6500);
  ok(warm.startsWith('#ff') && parseInt(warm.slice(5, 7), 16) < 60, `2000 K → ${warm}`);
  ok(parseInt(cool.slice(5, 7), 16) > 230, `6500 K → ${cool}`);
}

console.log('§5 the Home Assistant card says what the seam is doing, and only that');
{
  ok(hs.seamLines(base).length === 0, 'nothing reported: no lines');
  const strip = { devices: ['tv-backlight'], owner: 'hyperion', why: 'TV Music is off — Hyperion drives the strip', streaming: [] };
  const lent = hs.seamLines({ ...base, seam_active: true, tv_music: false, tv_strip: strip });
  ok(lent.some((x) => x.startsWith('TV strip: hyperion — TV Music is off')), `lent: ${lent[0]}`);
  const ours = hs.seamLines({ ...base, seam_active: true, tv_music: true,
    tv_strip: { ...strip, owner: 'spectra', why: null, streaming: ['tv-backlight'] } });
  ok(ours[0] === 'TV strip: Spectra drives it (TV Music on).', `ours: ${ours[0]}`);
  const recorded = hs.seamLines({ ...base, seam_active: false, seam_reason: 'no house mode is set' });
  ok(recorded[0] === 'Recorded, not acted on — no house mode is set.', 'inert: says so first');
  const media = hs.seamLines({ ...base, clock_mode: { id: 'c', name: 'Evening' },
    media: { source: 'roku', state: 'playing', since_ms: 1, active: true, mode: null, words: ['TV (roku)', 'TV'] } });
  ok(media[0].includes('no mode answers to "TV (roku)" or "TV"') && media[0].includes('Evening stays'),
    `media with no TV mode names it: ${media[0]}`);
  const fx = (o) => ({ device: 'crystal', name: 'Crystal', target: null, why: null, in_flight: false,
    override: null, applied: null, ...o });
  ok(hs.fixtureLine(fx({ target: 'on', applied: { target: 'on', outcome: 'landed', detail: '', at_ms: 1 } })) === null,
    'a fixture held on as asked is the quiet normal case');
  ok(hs.fixtureLine(fx({ target: 'off' })) === 'Crystal: switched off — no stream', 'off');
  ok(hs.fixtureLine(fx({ target: 'on', applied: { target: 'on', outcome: 'failed', detail: 'no answer', at_ms: 1 } }))
    === 'Crystal: on — failed: no answer', 'a failed write is named');
  ok(hs.fixtureLine(fx({ override: { power: 'off', lent_to: null, source: 'ha', since_ms: 1 } }))
    === 'Crystal: switched off (recorded, not acted on)', 'recorded but inert');
  const voice = hs.seamLines({ ...base, voice: { state: 'listening', since_ms: 1, fixtures: ['crystal'],
    skipped: [{ fixture: 'sconce-kitchen-left', reason: 'busy — the Light Show holds it' }] } });
  ok(voice[0].startsWith('Voice: listening on crystal (skipped sconce-kitchen-left: busy'), `voice: ${voice[0]}`);
}

if (failures) {
  console.log(`\n${failures} failure(s)`);
  process.exit(1);
}
console.log('\nall house summary checks passed');
