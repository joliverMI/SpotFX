// Executable spec for spectra/web/src/components/{iconRegistry,Icon}.tsx —
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
// to the type, etc.) — it scans every real .tsx/.ts source file under
// spectra/web/src for a literal `<Icon name="...">` usage and fails loudly
// if any such name is not a key of ICONS. This repo has no JS test runner
// (see AGENTS.md's "Tests" section) — following the established
// check_*.mjs precedent, this transpiles the REAL registry module with
// esbuild rather than re-declaring a copy of it.
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

// ── load the real registry ──
const registrySrc = readFileSync(
  join(repo, 'spectra/web/src/components/iconRegistry.ts'), 'utf8');
const { code } = esbuild.transformSync(registrySrc, { loader: 'ts', format: 'esm' });
const modPath = join(mkdtempSync(join(tmpdir(), 'icon-registry-')), 'iconRegistry.mjs');
writeFileSync(modPath, code);
const { ICONS } = await import(pathToFileURL(modPath).href);

console.log('§1 the registry itself');
ok(Object.keys(ICONS).length >= 3, `registry carries at least the 3 icons this task added (has ${Object.keys(ICONS).length})`);
for (const required of ['power', 'bulb', 'home']) {
  ok(typeof ICONS[required] === 'string' && ICONS[required].length > 0, `"${required}" is registered with a non-empty SVG path`);
}

console.log('§2 every real <Icon name="..."> usage names a registered icon');
const srcRoot = join(repo, 'spectra/web/src');
/** Walk every .ts/.tsx file, collecting `<Icon ... name="X" ...>` or
 * `name={'X'}` literal usages (both quote styles seen in this codebase). */
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
for (const file of files) {
  const text = readFileSync(file, 'utf8');
  let m;
  while ((m = nameRe.exec(text)) !== null) {
    const name = m[1] ?? m[2];
    usagesFound += 1;
    if (!(name in ICONS)) unknown.push(`${name} (${file.slice(repo.length + 1)})`);
  }
}
ok(usagesFound > 0, `found ${usagesFound} real <Icon name="..."> call site(s) across the app`);
ok(unknown.length === 0, unknown.length === 0
  ? 'every <Icon name="..."> usage names a registered icon'
  : `unregistered icon name(s) used: ${unknown.join(', ')}`);

console.log('§3 no raw POWER SYMBOL (U+23FB) character survives outside the registry/this check');
const powerSymbol = '⏻';
const stray = [];
for (const file of files) {
  const text = readFileSync(file, 'utf8');
  if (text.includes(powerSymbol)) stray.push(file.slice(repo.length + 1));
}
ok(stray.length === 0, stray.length === 0
  ? 'no component renders the raw U+23FB character directly any more'
  : `raw U+23FB POWER SYMBOL still present in: ${stray.join(', ')}`);

console.log(failures === 0 ? '\nPASS' : `\nFAIL (${failures})`);
process.exit(failures === 0 ? 0 : 1);
