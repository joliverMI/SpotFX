// Executable spec for spectra/web/src/components/{iconRegistry,Icon,PowerButton}.tsx —
// the "icon appears as an X" fix (2026-10-06, his report on "Force colour"
// and "Snap generated cues to beat", both PowerButton.tsx, which rendered a
// bare U+23FB POWER SYMBOL character with no font-glyph guarantee; see
// iconRegistry.ts's own docstring for the full root-cause writeup).
//
// `Icon`'s `name` prop is a closed TypeScript union, so `tsc --noEmit`
// (already part of `npm run build`) is the PRIMARY build-time check: an
// unregistered name is a compile error. This script is the second,
// independent net, for anything that bypasses the type system (a dynamic
// `name={x as any}`, a future icon added to the registry but never wired
// to the type, etc.).
//
// §1-§2 don't just check that a discovered `<Icon name="...">` call site's
// string is a key of ICONS — they actually RENDER the real Icon/PowerButton
// components (via `react-dom/server`, on the real, esbuild-bundled source,
// never a reimplemented copy) and assert the real markup: either a genuine
// `<svg><path d="...">` matching the registry's own value, or (for an
// intentionally-bogus name in the negative control) the dashed-box fallback
// — never the pre-fix bug shape, a raw U+23FB character reaching the DOM.
// This repo has no JS test runner (see AGENTS.md's "Tests" section) —
// following the established check_*.mjs precedent of transpiling/bundling
// real modules with esbuild rather than re-declaring copies of them.
//
// Run: node scripts/check_icon_registry.mjs
import { mkdtempSync, writeFileSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, extname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
const require = createRequire(join(repo, 'spectra/web/package.json'));
const esbuild = require('esbuild');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

// ── load the real registry (data, not behavior) ──
const registrySrc = readFileSync(
  join(repo, 'spectra/web/src/components/iconRegistry.ts'), 'utf8');
const { code: registryCode } = esbuild.transformSync(registrySrc, { loader: 'ts', format: 'esm' });
const registryModPath = join(mkdtempSync(join(tmpdir(), 'icon-registry-')), 'iconRegistry.mjs');
writeFileSync(registryModPath, registryCode);
const { ICONS } = await import(pathToFileURL(registryModPath).href);

console.log('§1 the registry itself');
ok(Object.keys(ICONS).length >= 3, `registry carries at least the 3 icons this task added (has ${Object.keys(ICONS).length})`);
for (const required of ['power', 'bulb', 'home']) {
  ok(typeof ICONS[required] === 'string' && ICONS[required].length > 0, `"${required}" is registered with a non-empty SVG path`);
}

// ── build a renderer over the REAL Icon + PowerButton components ──
// Bundled (not just transformed) so Icon's/PowerButton's own relative
// imports (iconRegistry.ts, fixedSizeToggleStyle.ts) resolve from their
// real files, and `react`/`react-dom/server` resolve via `nodePaths`
// pointed at spectra/web's own node_modules (the entry file lives in the
// OS tmp dir, outside spectra/web, so plain node resolution wouldn't find
// them otherwise).
const entrySrc = `
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import Icon from ${JSON.stringify(join(repo, 'spectra/web/src/components/Icon.tsx'))};
import PowerButton from ${JSON.stringify(join(repo, 'spectra/web/src/components/PowerButton.tsx'))};
export function renderIcon(name) {
  return renderToStaticMarkup(React.createElement(Icon, { name }));
}
export function renderPowerButton(on) {
  return renderToStaticMarkup(React.createElement(PowerButton, { on, onChange: () => {} }));
}
`;
const renderTmp = mkdtempSync(join(tmpdir(), 'icon-render-'));
const entryFile = join(renderTmp, 'entry.mjs');
writeFileSync(entryFile, entrySrc);
const outFile = join(renderTmp, 'out.cjs');
// CJS output, not ESM: react-dom/server's own CJS build reaches Node's
// `stream` builtin via `require()`, which esbuild can bundle for a CJS
// target but not cleanly for an ESM one (no ambient `require`) — loading
// the bundle with `require()` (via the same createRequire as esbuild
// itself, above) avoids needing a `createRequire` shim inside the bundle.
const build = esbuild.buildSync({
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
  ? 'Icon.tsx + PowerButton.tsx bundle cleanly with their real imports'
  : `bundle failed: ${build.errors.map((e) => e.text).join('; ')}`);
const { renderIcon, renderPowerButton } = require(outFile);

const POWER_SYMBOL = '⏻';
const containsPath = (markup, d) => markup.includes(`<path d="${d}"`);

console.log('§2 the real Icon component actually renders each registered icon');
for (const [name, d] of Object.entries(ICONS)) {
  const markup = renderIcon(name);
  ok(markup.includes('<svg') && containsPath(markup, d) && !markup.includes('unknown icon'),
    `rendering <Icon name="${name}"/> produces its real SVG path (not the fallback)`);
  ok(!markup.includes(POWER_SYMBOL), `rendered "${name}" icon carries no raw U+23FB character`);
}
console.log('  (negative control: an unregistered name renders the dashed-box fallback, not a crash or a bare glyph)');
{
  const markup = renderIcon('definitelyNotRegistered');
  ok(markup.includes('unknown icon') && !markup.includes('<path'),
    'an unregistered name falls back to the dashed box, never a raw glyph');
}

console.log('§3 every real <Icon name="..."> call site in the app renders a real icon');
const srcRoot = join(repo, 'spectra/web/src');
/** Walk every .ts/.tsx file, collecting `<Icon ... name="X" ...>` or
 * `name={'X'}` literal usages (both quote styles seen in this codebase).
 * This enumerates WHERE to render, same as finding files by pattern — the
 * actual pass/fail assertion below comes from executing Icon itself, not
 * from this scan. */
function walk(dir, out) {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    const st = statSync(p);
    if (st.isDirectory()) { walk(p, out); continue; }
    if (!['.ts', '.tsx'].includes(extname(p))) continue;
    if (p.endsWith('iconRegistry.ts') || p.endsWith('/Icon.tsx')) continue;
    out.push(p);
  }
}
const files = [];
walk(srcRoot, files);

const nameRe = /<Icon\b[^>]*?\bname=(?:"([a-zA-Z0-9_-]+)"|'([a-zA-Z0-9_-]+)')/g;
let usagesFound = 0;
const unknown = [];
const discovered = new Set();
for (const file of files) {
  const text = readFileSync(file, 'utf8');
  let m;
  while ((m = nameRe.exec(text)) !== null) {
    const name = m[1] ?? m[2];
    usagesFound += 1;
    discovered.add(name);
    if (!(name in ICONS)) unknown.push(`${name} (${file.slice(repo.length + 1)})`);
  }
}
ok(usagesFound > 0, `found ${usagesFound} real <Icon name="..."> call site(s) across the app`);
ok(unknown.length === 0, unknown.length === 0
  ? 'every <Icon name="..."> usage names a registered icon'
  : `unregistered icon name(s) used: ${unknown.join(', ')}`);
// For every DISTINCT name any real call site actually passes, render it
// for real and confirm it lands as a genuine icon rather than the fallback
// — proving the call site's own string reaches a working SVG, not just
// that the string happens to match a dict key.
for (const name of discovered) {
  if (!(name in ICONS)) continue; // already failed above; nothing more to render
  const markup = renderIcon(name);
  ok(markup.includes('<svg') && !markup.includes('unknown icon'),
    `a real call site's name="${name}" renders a genuine icon when executed`);
}

console.log('§4 PowerButton (the originally-reported broken component) renders no stray glyph, on or off');
for (const on of [true, false]) {
  const markup = renderPowerButton(on);
  ok(!markup.includes(POWER_SYMBOL), `PowerButton(on=${on})'s rendered output carries no raw U+23FB character`);
  ok(markup.includes('<svg') && containsPath(markup, ICONS.power),
    `PowerButton(on=${on}) renders the real power icon via <Icon>, not a bare glyph`);
}

console.log('§5 (secondary, defense-in-depth) no raw POWER SYMBOL (U+23FB) character survives in source outside the registry/this check');
const stray = [];
for (const file of files) {
  const text = readFileSync(file, 'utf8');
  if (text.includes(POWER_SYMBOL)) stray.push(file.slice(repo.length + 1));
}
ok(stray.length === 0, stray.length === 0
  ? 'no component source still spells out the raw U+23FB character'
  : `raw U+23FB POWER SYMBOL still present in: ${stray.join(', ')}`);

console.log(failures === 0 ? '\nPASS' : `\nFAIL (${failures})`);
process.exit(failures === 0 ? 0 : 1);
