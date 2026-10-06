/**
 * Executable spec for the Light Show's High/Low Trigger markers on the
 * Timeline (spectra/web/src/timeline/lightShowMarkers.ts) — his ask,
 * verbatim: "I also want to see a marker showing where the light show
 * triggers are, even if they aren't active."
 *
 * Transpiles (and bundles, since this module has a real runtime
 * dependency on ../lightshow/showSummary.ts) the REAL module with
 * esbuild and drives it, zero network, zero DOM.
 *
 * Proves:
 *   ONE   — a cue with nothing armed on it is still drawn (muted) — "even
 *           if they aren't active" means the position never disappears.
 *   TWO   — an arm with no song_uri (carries to every song) marks any
 *           song's cue armed; one scoped to a different song does not.
 *   THREE — a scene_change-triggered arm never produces a position
 *           marker (no fixed song position) but IS picked up by
 *           sceneChangeArms for the legend.
 *   FOUR  — a song with no High/Low (e.g. too short) draws nothing.
 *
 * Run: node scripts/check_timeline_light_show_markers.mjs
 */
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const WEB = path.join(REPO, 'spectra/web');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const tmp = mkdtempSync(path.join(tmpdir(), 'light-show-markers-'));
const js = path.join(tmp, 'lightShowMarkers.mjs');
execFileSync('npx', ['esbuild', path.join(WEB, 'src/timeline/lightShowMarkers.ts'), '--bundle',
  '--format=esm', '--platform=neutral', '--log-level=warning', `--outfile=${js}`],
  { cwd: WEB, stdio: ['ignore', 'ignore', 'inherit'] });
const { armAppliesToCue, lightShowCueMarkers, sceneChangeArms, LIGHT_SHOW_COLOR } = await import(js);

const arm = (over) => ({
  id: 'a1', set_id: 's1', action: null, label: 'Reveal Crystal', on: 'high', repeat: false,
  song_uri: null, source: 'manual', finish_on_mark: true, created_ms: 0, expires_ms: null,
  status: 'armed', fire_count: 0, ended_ms: null, end_reason: '', last_outcome: null, ...over,
});
const cues = (over) => ({
  uri: 'u', reason: null, duration_ms: 180_000,
  high: { level: 'high', timestamp_ms: 60_000, source: 'auto', shift: 0.4, auto_ms: 60_000,
          auto_shift: 0.4, drop_mark_ms: null, alternates: [], runner_up_close: false, moved_ms: null },
  low: { level: 'low', timestamp_ms: 90_000, source: 'moved', shift: -0.3, auto_ms: 85_000,
         auto_shift: -0.3, drop_mark_ms: null, alternates: [], runner_up_close: false, moved_ms: 90_000 },
  ...over,
});

console.log('ONE — a cue with nothing armed on it is still drawn, muted');
{
  const m = lightShowCueMarkers(cues(), { armed: [], history: [], song: {}, last_crossed: {}, refusal: null }, 'u');
  ok(m.length === 2, `both High and Low drawn even with nothing armed (${m.length})`);
  ok(m.every((x) => x.armed === false), 'neither is armed');
  ok(m[0].level === 'high' && m[0].ms === 60_000, 'High at its cue position');
  ok(m[1].level === 'low' && m[1].ms === 90_000, 'Low at its cue position');
  ok(m[0].title.includes('nothing armed on it'), `title names the state: ${m[0].title}`);
}

console.log('TWO — song scoping: no song_uri carries everywhere, a scoped one does not');
{
  const armsGlobal = { armed: [arm()], history: [], song: {}, last_crossed: {}, refusal: null };
  ok(lightShowCueMarkers(cues(), armsGlobal, 'u').find((m) => m.level === 'high').armed,
    'an arm with no song_uri marks THIS song high armed');
  ok(lightShowCueMarkers(cues(), armsGlobal, 'different-song').find((m) => m.level === 'high').armed,
    'and ANY OTHER song too — it carries');
  const armsScoped = { ...armsGlobal, armed: [arm({ song_uri: 'u' })] };
  ok(lightShowCueMarkers(cues(), armsScoped, 'u').find((m) => m.level === 'high').armed,
    'an arm scoped to this song marks it armed');
  ok(!lightShowCueMarkers(cues(), armsScoped, 'other').find((m) => m.level === 'high').armed,
    'but not a DIFFERENT song');
  ok(!armAppliesToCue(arm({ on: 'low' }), 'high', 'u'), 'a low-triggered arm never matches a high query');
}

console.log('THREE — scene_change arms have no position marker, but are named for the legend');
{
  const arms = { armed: [arm({ on: 'scene_change', label: 'Dim Wave' })], history: [], song: {}, last_crossed: {}, refusal: null };
  const m = lightShowCueMarkers(cues(), arms, 'u');
  ok(m.every((x) => !x.armed), 'a scene_change arm never marks the High/Low cue armed');
  const sc = sceneChangeArms(arms, 'u');
  ok(sc.length === 1 && sc[0].label === 'Dim Wave', 'but sceneChangeArms picks it up for the legend');
  ok(sceneChangeArms(arms, 'u').every((a) => a.on === 'scene_change'), 'only scene_change arms');
}

console.log('FOUR — a song with no High/Low draws nothing');
{
  const m = lightShowCueMarkers({ uri: 'u', reason: 'too short', duration_ms: 5000, high: null, low: null },
    { armed: [], history: [], song: {}, last_crossed: {}, refusal: null }, 'u');
  ok(m.length === 0, 'no cues → no markers');
  ok(lightShowCueMarkers(null, null, 'u').length === 0, 'no plan at all → no markers');
}

console.log('FIVE — colours stay off the phase colours (gold charge, sky-blue lull, magenta drop)');
{
  const phaseColours = new Set(['#fbbf24', '#38bdf8', '#ec4899']); // dropSequences.ts PHASE_COLOR
  ok(!phaseColours.has(LIGHT_SHOW_COLOR.high) && !phaseColours.has(LIGHT_SHOW_COLOR.low),
    'High/Low colours are distinct from the drop-sequence phase colours');
}

rmSync(tmp, { recursive: true, force: true });
if (failures) { console.log(`\n${failures} FAILED`); process.exit(1); }
console.log('\nALL CHECKS PASSED');
