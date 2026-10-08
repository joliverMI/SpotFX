// Executable spec for RoomControlsBar.tsx's Scenes/Colour top-bar button
// faces — the Admiral's ask, 2026-10-07 (verbatim in AGENTS.md): "the
// scenes button the top bar that currently shows transitions + analyzed:
// change that to show the name of the current scene. Similarly, on the
// color button, show the current color set (or the last chosen one if it
// is drifting). Show a lock icon if it's being forced, and nothing
// otherwise."
//
// This renders the REAL RoomControlsBar.tsx (via esbuild, bundled with its
// real children — TopBarGroupButton, Icon, DriftGradientBar, ReleaseButton
// — exactly the check_icon_registry.mjs precedent: real source, never a
// reimplemented copy), with only the data layer (`../queries`) replaced by
// a controllable in-memory fixture (there is no live backend here, so the
// data layer is the one legitimate seam to stand in for). Every button's
// dropdown PANEL is closed by default (TopBarGroupButton's own
// `useState(false)`), so none of its contents — ColorGradientPicker,
// SearchSelect, AmbientGroupsPicker, HelpLink's own panel entries — ever
// execute; only the always-visible button faces and the two
// unconditionally-rendered siblings (DriftGradientBar, ReleaseButton) do,
// which is why their own queries need fixtures too.
//
// RoomControlsBar deliberately holds its editable draft in `useState(null)`
// and only adopts server `data` into it via a `useEffect` (see that
// effect's own comment: adopting synchronously would re-snap a value mid
// debounced-apply) — so a plain one-shot `react-dom/server` render can
// never show it (effects never run server-side; the component bails out
// on `if (!local) return null`). This harness instead performs a REAL
// mount via `react-dom/client`'s `createRoot` + `act()` under jsdom —
// render, let the adoption effect commit, then read the live DOM — the
// same thing a browser actually does, not a static one-shot snapshot.
//
// Four cases, each asserted against the real rendered HTML:
//   1. An active scene + a drifting colour set (neither forced) — the
//      Scenes button must show the scene's NAME (not a scene-change-mode
//      label) and the Colour button must show the colour set's name
//      (from journey.active_set_id, same field whether forced or not —
//      this is what answers "or the last chosen one if it is drifting"),
//      and NEITHER button may show a lock icon.
//   2. Force Scene on — the Scenes button must show the lock icon.
//   3. Force Colour on — the Colour button must show the lock icon.
//   4. No active scene / no active colour set — neither button's value
//      span renders (nothing to show), matching "nothing otherwise".
//
// Run: node scripts/check_topbar_scene_colour_names.mjs
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
const require = createRequire(join(repo, 'spectra/web/package.json'));
const esbuild = require('esbuild');

let jsdomMod;
try {
  jsdomMod = require('jsdom');
} catch {
  console.log('jsdom not installed in spectra/web/node_modules (dev-only, '
    + 'not a declared dependency) — skipping this check. Install with '
    + '`cd spectra/web && npm install --no-save jsdom` to run it.');
  process.exit(0);
}
const { JSDOM } = jsdomMod;

// A real mount needs a real DOM — jsdom, global before react-dom/client is
// loaded (it feature-detects `document`/`window` at call time, so these
// just need to exist before `renderBar` is first invoked below).
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
// Node 24 ships its own read-only global `navigator` — jsdom's must
// replace it, not plain-assign into it.
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.Node = dom.window.Node;
globalThis.localStorage = dom.window.localStorage;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

// ── a fake `../queries` module, data-only — every export any component in
// the always-rendered tree (RoomControlsBar, DriftGradientBar, ReleaseButton)
// actually calls, reading from one mutable fixture a driver function can
// replace between renders. ──
const fakeQueriesSrc = `
let FIXTURE = null;
export function __setFixture(f) { FIXTURE = f; }
export function useRoomControls() { return { data: FIXTURE.room }; }
export function useSaveRoomControls() { return { mutate: () => {}, isPending: false }; }
export function useScenes() { return { data: FIXTURE.scenes }; }
export function useEngineStatus() { return { data: FIXTURE.engineStatus }; }
export function useAmbientStatusPush() {}
export function useRoomControlsForcePush() {}
export function useAmbientHueGroups() { return { data: { groups: [] } }; }
export function useSpotColorSets() { return { data: FIXTURE.colorCards }; }
export function useOwnership() { return { data: { owner: 'spectra' } }; }
export function useReleaseRoom() { return { mutate: () => {}, isPending: false }; }
export function useGradient2dProfiles() { return { data: {} }; }
export function useSaveGradient2dProfiles() { return { mutate: () => {}, mutateAsync: async () => {}, isPending: false }; }
`;
const tmpDir = mkdtempSync(join(tmpdir(), 'topbar-harness-'));
const fakeQueriesPath = join(tmpDir, 'fakeQueries.mjs');
writeFileSync(fakeQueriesPath, fakeQueriesSrc);

const entrySrc = `
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import RoomControlsBar from ${JSON.stringify(join(repo, 'spectra/web/src/components/RoomControlsBar.tsx'))};
import { __setFixture } from ${JSON.stringify(fakeQueriesPath)};

// One container reused across calls, cleared between renders (unmount +
// a fresh root) so a later test's timers/effects can never leak into an
// earlier one's assertions.
const container = document.createElement('div');
document.body.appendChild(container);
let root = null;

export function renderBar(fixture) {
  __setFixture(fixture);
  if (root) act(() => { root.unmount(); });
  root = createRoot(container);
  act(() => {
    root.render(React.createElement(MemoryRouter, null, React.createElement(RoomControlsBar)));
  });
  return container.innerHTML;
}
`;
const entryFile = join(tmpDir, 'entry.mjs');
writeFileSync(entryFile, entrySrc);
const outFile = join(tmpDir, 'out.cjs');

const build = await esbuild.build({
  entryPoints: [entryFile],
  bundle: true,
  format: 'cjs',
  platform: 'node',
  jsx: 'automatic',
  outfile: outFile,
  nodePaths: [join(repo, 'spectra/web/node_modules')],
  // Redirect the real component's `../queries` import (resolved relative
  // to RoomControlsBar.tsx, inside spectra/web/src/components/, and from
  // DriftGradientBar.tsx/ReleaseButton.tsx the same way) to the fixture
  // module above — the one legitimate substitution, since there is no
  // live backend in this harness.
  plugins: [{
    name: 'stub-queries',
    setup(buildApi) {
      const queriesFile = join(repo, 'spectra/web/src/queries.ts');
      buildApi.onResolve({ filter: /\/queries(\.ts)?$/ }, (args) => {
        const resolved = join(dirname(args.importer), args.path);
        if (resolved === queriesFile || `${resolved}.ts` === queriesFile) {
          return { path: fakeQueriesPath };
        }
        return null;
      });
    },
  }],
  logLevel: 'silent',
});
ok(build.errors.length === 0, build.errors.length === 0
  ? 'RoomControlsBar.tsx + real children bundle cleanly with their real imports'
  : `bundle failed: ${build.errors.map((e) => e.text).join('; ')}`);
const { renderBar } = require(outFile);

// ── fixtures ──
const BASE_ROOM = {
  display_mode: 'default',
  display_light_bg_color: '#201830',
  display_light_bg_brightness: 0.3,
  dark_light_shield_categories: [],
  dark_light_shield_virtuals: [],
  brightness_multiplier: 1.0,
  ambient_enabled: false,
  ambient_on_music_pause: false,
  ambient_color: '#ffffff',
  ambient_color_dark: null,
  ambient_hue_group_ids: [],
  global_transition_ms: 0,
  scene_transition_ms_gentle: 300,
  scene_transition_ms_hard: 200,
  scene_change_mode: 'analysed',
  midsong_snap_to_beat: true,
  transitions_per_minute: 8,
  transition_window_beats: 8,
  transition_edge_sensitivity: 0.5,
  scene_changes_per_minute: 0,
  lull_dark_max_s: 3,
  active_gradient_id: null,
  force_scene_enabled: false,
  force_scene_scene_id: null,
  force_color_enabled: false,
  force_color_target_id: null,
};

const SCENE = { id: 'scene-1', name: 'Black Hole V2', labels: [], devices: [], flare_kinds: [], responses: {} };
const COLOR_SET = { id: 'set-1', name: 'Orbit Blues', kind: 'set' };

const engineStatusWith = ({ activeScene, activeSetId }) => ({
  increment: 'S3', dark: true,
  executor: { mode: 'recording', recent_writes: [] },
  conductor: {
    executor_mode: 'recording', leg_s: 0,
    active_scene: activeScene ? { id: SCENE.id, name: SCENE.name } : null,
    deferred_by: null,
    journey: {
      custody: 'room', degrees_per_min: 0, room_degrees_per_min: 0,
      wheel_position_deg: null, active_set_id: activeSetId, rainbow_paused: false,
      destination: null,
    },
    mechanisms: [], last_leg: null,
  },
});

// Extract the HTML slice for the button whose label text is `label`
// (e.g. "Scenes", "Colour") — from its own `.top-bar-group-btn-label`
// span up to the button's own closing tag, so an assertion about the
// Scenes button can never accidentally match the Colour button's markup
// (both share the className `scenes-group-btn`, distinguished only by
// their own content/label).
function sliceButton(html, label) {
  const marker = `>${label}</span>`;
  const i = html.indexOf(marker);
  if (i === -1) throw new Error(`label "${label}" not found in rendered output`);
  const end = html.indexOf('</button>', i);
  if (end === -1) throw new Error(`no closing </button> found after "${label}"`);
  return html.slice(i, end);
}

const hasLock = (slice) => slice.includes('top-bar-group-btn-lock') && slice.includes('<svg');
const hasValueText = (slice, text) =>
  new RegExp(`class="top-bar-group-btn-value"[^>]*>${text}<`).test(slice);
const hasValueSpanAtAll = (slice) => slice.includes('top-bar-group-btn-value');
const hasOldPurpleDot = (slice) => slice.includes('top-bar-group-btn-dot-purple');

console.log('§1 an active scene + a drifting colour set, neither forced');
{
  const html = renderBar({
    room: { ...BASE_ROOM },
    scenes: [SCENE],
    colorCards: [COLOR_SET],
    engineStatus: engineStatusWith({ activeScene: true, activeSetId: COLOR_SET.id }),
  });
  const scenesSlice = sliceButton(html, 'Scenes');
  const colourSlice = sliceButton(html, 'Colour');
  ok(hasValueText(scenesSlice, 'Black Hole V2'),
    'Scenes button shows the active scene\'s NAME, not the scene-change-mode label');
  ok(!scenesSlice.includes('analysed') && !scenesSlice.includes('Transitions'),
    'Scenes button no longer shows the old "Transitions + analysed" mode label on its face');
  ok(!hasLock(scenesSlice), 'Scenes button shows no lock icon when Force Scene is off');
  ok(!hasOldPurpleDot(scenesSlice), 'Scenes button shows no purple dot when Force Scene is off');
  ok(hasValueText(colourSlice, 'Orbit Blues'),
    'Colour button shows the room\'s active (or last-drifted-to) colour set name, unforced');
  ok(!hasLock(colourSlice), 'Colour button shows no lock icon when Force Colour is off');
  ok(!hasOldPurpleDot(colourSlice), 'Colour button shows no purple dot when Force Colour is off');
}

console.log('§2 Force Scene on');
{
  const html = renderBar({
    room: { ...BASE_ROOM, force_scene_enabled: true, force_scene_scene_id: SCENE.id },
    scenes: [SCENE],
    colorCards: [COLOR_SET],
    engineStatus: engineStatusWith({ activeScene: true, activeSetId: COLOR_SET.id }),
  });
  const scenesSlice = sliceButton(html, 'Scenes');
  ok(hasValueText(scenesSlice, 'Black Hole V2'), 'Scenes button still shows the scene name while forced');
  ok(hasLock(scenesSlice), 'Scenes button shows the lock icon when Force Scene is on');
  ok(!hasOldPurpleDot(scenesSlice), 'the old purple dot is gone even while forced (replaced by the lock)');
}

console.log('§3 Force Colour on');
{
  const html = renderBar({
    room: { ...BASE_ROOM, force_color_enabled: true, force_color_target_id: COLOR_SET.id },
    scenes: [SCENE],
    colorCards: [COLOR_SET],
    engineStatus: engineStatusWith({ activeScene: true, activeSetId: COLOR_SET.id }),
  });
  const colourSlice = sliceButton(html, 'Colour');
  ok(hasValueText(colourSlice, 'Orbit Blues'), 'Colour button still shows the colour set name while forced');
  ok(hasLock(colourSlice), 'Colour button shows the lock icon when Force Colour is on');
  ok(!hasOldPurpleDot(colourSlice), 'the old purple dot is gone even while forced (replaced by the lock)');
}

console.log('§4 nothing active — "nothing otherwise"');
{
  const html = renderBar({
    room: { ...BASE_ROOM },
    scenes: [SCENE],
    colorCards: [COLOR_SET],
    engineStatus: engineStatusWith({ activeScene: false, activeSetId: null }),
  });
  const scenesSlice = sliceButton(html, 'Scenes');
  const colourSlice = sliceButton(html, 'Colour');
  ok(!hasValueSpanAtAll(scenesSlice), 'Scenes button renders no value span when no scene is active');
  ok(!hasLock(scenesSlice), 'Scenes button shows no lock icon when unforced and nothing is active');
  ok(!hasValueSpanAtAll(colourSlice), 'Colour button renders no value span when no colour set is active');
  ok(!hasLock(colourSlice), 'Colour button shows no lock icon when unforced and nothing is active');
}

console.log(failures === 0 ? '\nPASS' : `\nFAIL (${failures})`);
process.exit(failures === 0 ? 0 : 1);
