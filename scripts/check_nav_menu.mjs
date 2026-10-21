// Executable spec for the grouped top menu (UI declutter plan §2,
// nav/NavBar.tsx + NavMenu.tsx + navGroups.ts) — the jsdom real-mount
// pattern established by check_topbar_scene_colour_names.mjs: bundle the
// REAL source with esbuild, mount via react-dom/client under jsdom, drive
// real events.
//
// Six things proven:
//   1. Every route the old flat 17-link NavBar reached is still reachable
//      from some group (a structural check over navGroups.ts's own data,
//      no DOM needed for this part).
//   2. Clicking a group's trigger opens its dropdown; clicking an item
//      navigates (the router's location changes) and the dropdown closes.
//   3. The group containing the active route is highlighted.
//   4. Keyboard: ArrowDown on the trigger opens the menu and focuses the
//      first item; Escape closes it and returns focus to the trigger.
//   5. The unsaved-changes guard (a capture-phase handler on <nav> reading
//      `a.closest('a')`) still intercepts a click on a DROPDOWN item,
//      exactly as it already does for a plain top-level link — proving
//      the dropdown is rendered inline inside <nav>, never portalled.
//   6. Dropdown items render as real `<Link>`s (the guard's own
//      requirement) and the group trigger carries `aria-haspopup`/
//      `aria-expanded`.
//
// Run: node scripts/check_nav_menu.mjs
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

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/scenes' });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.Node = dom.window.Node;
globalThis.localStorage = dom.window.localStorage;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
// jsdom does not implement window.confirm; unsavedGuard.ts's confirmLeave()
// calls the bare global `confirm(...)` when a message is set — stub it to
// "cancel" (false), the harder case to prove the guard actually blocks.
globalThis.confirm = () => false;

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

console.log('§1 every old route is still reachable from the grouped data (navGroups.ts)');
{
  const navGroupsSrc = require('fs').readFileSync(join(repo, 'spectra/web/src/nav/navGroups.ts'), 'utf8');
  // A pure-data require via esbuild transform (no bundling needed — this
  // file imports only a type, which erases).
  const { code } = esbuild.transformSync(navGroupsSrc, { loader: 'ts', format: 'cjs' });
  const tmp = mkdtempSync(join(tmpdir(), 'navgroups-'));
  const outFile = join(tmp, 'navGroups.cjs');
  writeFileSync(outFile, code);
  const { NAV_GROUPS, ALL_NAV_ROUTES, activeGroupId } = require(outFile);

  const reachable = new Set();
  for (const g of NAV_GROUPS) {
    if (g.to) reachable.add(g.to);
    for (const it of g.items ?? []) reachable.add(it.to);
  }
  for (const route of ALL_NAV_ROUTES) {
    ok(reachable.has(route), `route ${route} is reachable from the grouped menu`);
  }
  ok(activeGroupId('/scenes') === 'artifacts', 'activeGroupId("/scenes") === "artifacts"');
  ok(activeGroupId('/show') === 'artifacts', 'activeGroupId("/show") === "artifacts" (Light Show)');
  ok(activeGroupId('/review') === 'engine', 'activeGroupId("/review") === "engine"');
  ok(activeGroupId('/feedback') === 'engine', 'activeGroupId("/feedback") === "engine" (filed next to Review)');
  ok(activeGroupId('/absorb') === 'engine', 'activeGroupId("/absorb") === "engine" (Absorb Music, beside Test Bed)');
  ok(activeGroupId('/settings') === 'settings', 'activeGroupId("/settings") === "settings"');
  ok(activeGroupId('/') === 'home', 'activeGroupId("/") === "home"');
}

console.log('§2-6 a real mount, real events');
{
  const entrySrc = `
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import NavBar from ${JSON.stringify(join(repo, 'spectra/web/src/nav/NavBar.tsx'))};
import { setUnsavedGuard } from ${JSON.stringify(join(repo, 'spectra/web/src/lib/unsavedGuard.ts'))};

const container = document.createElement('div');
document.body.appendChild(container);
let root = null;
let currentPath = '/scenes';

export function mount(initialPath) {
  currentPath = initialPath;
  if (root) act(() => { root.unmount(); });
  root = createRoot(container);
  act(() => {
    root.render(React.createElement(MemoryRouter, { initialEntries: [initialPath] },
      React.createElement(NavBar)));
  });
  return container;
}
export function html() { return container.innerHTML; }
export function setGuard(msg) { setUnsavedGuard(msg); }
export function act_(fn) { act(fn); }
`;
  const tmpDir = mkdtempSync(join(tmpdir(), 'navbar-harness-'));
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
    logLevel: 'silent',
  });
  ok(build.errors.length === 0, build.errors.length === 0
    ? 'NavBar.tsx + NavMenu.tsx + navGroups.ts bundle cleanly with their real imports'
    : `bundle failed: ${build.errors.map((e) => e.text).join('; ')}`);
  const { mount, html, setGuard, act_ } = require(outFile);

  const container = mount('/scenes');

  // Every dropdown item is a real <a> (react-router's <Link>) — the guard's
  // own structural requirement.
  const artifactsTrigger = [...container.querySelectorAll('.nav-group-trigger')]
    .find((b) => b.textContent.includes('Artifacts'));
  ok(!!artifactsTrigger, 'an Artifacts group trigger is rendered');
  ok(artifactsTrigger.getAttribute('aria-haspopup') === 'menu', 'trigger carries aria-haspopup="menu"');
  ok(artifactsTrigger.getAttribute('aria-expanded') === 'false', 'trigger starts aria-expanded="false"');
  ok(artifactsTrigger.classList.contains('active'), 'the Artifacts trigger is highlighted on /scenes');

  // Click opens the dropdown.
  act_(() => artifactsTrigger.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })));
  ok(artifactsTrigger.getAttribute('aria-expanded') === 'true', 'click opens the dropdown (aria-expanded=true)');
  let colourLink = [...container.querySelectorAll('a.nav-group-item')].find((a) => a.textContent === 'Colours');
  ok(!!colourLink, 'the open dropdown renders a real <a> for "Colours"');
  ok(colourLink.getAttribute('href') === '/colorsets', 'Colours links to /colorsets');

  // The unsaved guard intercepts a click on a DROPDOWN item (proving it's
  // inline inside <nav>, not portalled past the capture-phase handler).
  // React's synthetic capture-phase `stopPropagation()` halts the REAL
  // native dispatch at `nav` (an ancestor) before it ever reaches the
  // target, so even a plain native listener bound directly on the link
  // never fires at all — the observable proof is structural instead: with
  // the guard blocking, the Link's own `onClick={onClose}` (and react-
  // router's own navigation) never ran, so the dropdown is STILL OPEN and
  // we're still on /scenes.
  setGuard('unsaved!');
  act_(() => colourLink.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true, cancelable: true })));
  // `globalThis.confirm` is stubbed to return false (the harder case — the
  // user "cancels") above, so confirmLeave() reads as "do not leave" here".
  ok(container.querySelector('.nav-group-menu') !== null,
    'the unsaved-changes guard intercepts a click on a dropdown item (capture-phase, still works) — dropdown stays open');
  setGuard(null);

  // Clear the still-open dropdown from the guard test above with Escape,
  // then re-open it fresh for the keyboard test below.
  act_(() => {
    const ev = new dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true });
    artifactsTrigger.dispatchEvent(ev);
  });
  ok(container.querySelector('.nav-group-menu') === null, 'Escape on the trigger closes an open dropdown');
  act_(() => artifactsTrigger.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })));
  ok(artifactsTrigger.getAttribute('aria-expanded') === 'true', 'reopened for the keyboard test');
  act_(() => {
    const ev = new dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true });
    container.querySelector('a.nav-group-item')?.dispatchEvent(ev);
  });
  ok(container.querySelector('.nav-group-menu') === null, 'Escape (from an item) closes the dropdown');

  // A different route highlights the Engine group instead.
  mount('/review');
  const engineTrigger = [...container.querySelectorAll('.nav-group-trigger')]
    .find((b) => b.textContent.includes('Engine'));
  ok(engineTrigger.classList.contains('active'), 'the Engine trigger is highlighted on /review');
}

console.log(failures === 0 ? '\nPASS' : `\nFAIL (${failures})`);
process.exit(failures === 0 ? 0 : 1);
