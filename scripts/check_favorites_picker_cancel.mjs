// Executable spec for FavoritesPicker.tsx's "Cancel" button, after it
// moved from a popover (settings/RoomCard.tsx, UI declutter plan §9) to a
// permanently-mounted inline control on the Settings page.
//
// In its original popover usage, pressing Cancel called `onClose`, which
// unmounted the component — discarding whatever checkboxes were toggled
// since the picker opened, as a side effect of the unmount. Once mounted
// permanently inline, `onClose` is a no-op (nothing to close), so without
// a fix Cancel did literally nothing visible: the checkboxes kept
// whatever state the user had toggled, with no way to back out short of
// reloading the page.
//
// This mounts the REAL FavoritesPicker.tsx (esbuild + jsdom +
// react-dom/client, the check_touch_press_hold.mjs §8a/§8b precedent)
// against a fake fetch backing its real query hooks (useRegistry,
// useDevicePreviewFavorites, useSaveDevicePreviewFavorites) and proves,
// behaviourally:
//   ONE   — toggling a checkbox that was off turns it on.
//   TWO   — pressing Cancel reverts that toggle back to the committed
//           favourites (not merely "doesn't crash") — the actual
//           regression this script exists to catch.
//   THREE — Cancel still calls the passed `onClose` (so a future caller
//           that DOES use this in a real popover/dialog keeps working).
//   FOUR  — after cancelling, toggling again and pressing Save posts the
//           NEW toggle, proving Cancel didn't leave the picker's own
//           state wedged.
//
// Run: node scripts/check_favorites_picker_cancel.mjs
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
const webDir = join(repo, 'spectra/web');
const require = createRequire(join(webDir, 'package.json'));
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
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
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

const NodeResponse = globalThis.Response;
const committed = ['crystal-mapper', 'tv-mapper'];
let favorites = { favorite_virtual_ids: committed, effective_virtual_ids: committed, is_default: false };
const putBodies = [];
const fakeFetch = async (url, init = {}) => {
  const method = (init.method || 'GET').toUpperCase();
  const path = String(url).replace(/^https?:\/\/[^/]+/, '').split('?')[0];
  const json = (body, status = 200) => new NodeResponse(JSON.stringify(body),
    { status, headers: { 'Content-Type': 'application/json' } });
  if (path === '/spectra/api/registry' && method === 'GET') {
    return json({
      categories: {
        Matrix: { id: 'Matrix', parent_id: null, virtuals: ['crystal-mapper', 'tv-mapper'], effects: [] },
        Strips: { id: 'Strips', parent_id: null, virtuals: ['sconce-left'], effects: [] },
      },
      effects: {},
    });
  }
  if (path === '/spectra/api/device-preview/favorites' && method === 'GET') return json(favorites);
  if (path === '/spectra/api/device-preview/favorites' && method === 'PUT') {
    const body = JSON.parse(init.body);
    putBodies.push(body.favorite_virtual_ids);
    favorites = { favorite_virtual_ids: body.favorite_virtual_ids,
      effective_virtual_ids: body.favorite_virtual_ids.length ? body.favorite_virtual_ids : committed,
      is_default: body.favorite_virtual_ids.length === 0 };
    return json(favorites);
  }
  throw new Error(`unexpected fetch ${method} ${path}`);
};
globalThis.fetch = fakeFetch;
dom.window.fetch = fakeFetch;

const tmpDir = mkdtempSync(join(tmpdir(), 'favorites-picker-cancel-'));
const entrySrc = `
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ToastProvider } from ${JSON.stringify(join(webDir, 'src/components/Toast.tsx'))};
import FavoritesPicker from ${JSON.stringify(join(webDir, 'src/components/FavoritesPicker.tsx'))};

const container = document.createElement('div');
document.body.appendChild(container);
const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
let root = null;
let closeCalls = 0;

export async function mount() {
  root = createRoot(container);
  await act(async () => {
    root.render(React.createElement(QueryClientProvider, { client: qc },
      React.createElement(ToastProvider, null,
        React.createElement(FavoritesPicker, { onClose: () => { closeCalls += 1; } }))));
  });
  for (let i = 0; i < 20 && !container.querySelector('.device-preview-picker-row'); i++) {
    await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
  }
  return container;
}
export async function flush() {
  await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
}
export async function step(fn) {
  await act(async () => { fn(); await new Promise((r) => setTimeout(r, 5)); });
}
export function getCloseCalls() { return closeCalls; }
`;
const entryFile = join(tmpDir, 'entry.mjs');
writeFileSync(entryFile, entrySrc);
const outFile = join(tmpDir, 'out.cjs');
const build = await esbuild.build({
  entryPoints: [entryFile], bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
  outfile: outFile, nodePaths: [join(webDir, 'node_modules')], logLevel: 'silent',
  loader: { '.css': 'empty' },
});
ok(build.errors.length === 0, 'FavoritesPicker.tsx bundles cleanly with its real imports');
const { mount, step, getCloseCalls } = require(outFile);
const container = await mount();

const rowFor = (id) => [...container.querySelectorAll('.device-preview-picker-row')]
  .find((label) => label.textContent.includes(id));
const checkboxFor = (id) => rowFor(id)?.querySelector('input[type="checkbox"]');
const buttonByText = (text) => [...container.querySelectorAll('.device-preview-picker-actions button')]
  .find((b) => b.textContent.trim() === text);
const click = (el) => step(() => el.dispatchEvent(
  new dom.window.MouseEvent('click', { bubbles: true, cancelable: true })));

console.log('ONE — the committed favourites load, and an unchecked virtual starts unchecked');
ok(checkboxFor('crystal-mapper')?.checked === true, 'crystal-mapper (committed) starts checked');
ok(checkboxFor('sconce-left')?.checked === false, 'sconce-left (not committed) starts unchecked');

console.log('TWO — toggling sconce-left checks it');
await click(checkboxFor('sconce-left'));
ok(checkboxFor('sconce-left')?.checked === true, 'sconce-left is now checked (unsaved toggle)');

console.log('THREE — pressing Cancel reverts the unsaved toggle back to the committed favourites');
await click(buttonByText('Cancel'));
ok(checkboxFor('sconce-left')?.checked === false,
  'sconce-left is unchecked again after Cancel — the toggle was discarded, not left dangling');
ok(checkboxFor('crystal-mapper')?.checked === true,
  'crystal-mapper (still committed) stays checked after Cancel');
ok(getCloseCalls() === 1, 'Cancel still calls the passed onClose once (a future dialog/popover caller keeps working)');

console.log('FOUR — the picker still works after a cancel: a fresh toggle + Save posts the new choice');
await click(checkboxFor('sconce-left'));
await click(buttonByText('Save'));
ok(putBodies.length === 1, 'exactly one PUT was made');
// The post-cancel baseline is the FULL committed list (crystal-mapper + tv-mapper,
// restored by Cancel), plus this fresh toggle — not a stale pre-cancel draft.
ok(JSON.stringify(putBodies[0].slice().sort())
    === JSON.stringify(['crystal-mapper', 'tv-mapper', 'sconce-left'].sort()),
  `the save carries the post-cancel toggle on top of the restored committed list `
  + `(posted: ${JSON.stringify(putBodies[0])})`);

console.log(failures ? `\n${failures} FAILED` : '\nall passed');
process.exit(failures ? 1 : 0);
