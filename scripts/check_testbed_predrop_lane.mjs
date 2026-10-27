/** Executable spec for the test bed's PRE-DROPS LANE glyphs (predrop plan
 * step 3: "a "Pre-drops" lane on the test bed with a glyph per kind") —
 * the real EngineLane from spectra/web/src/testbed/components/
 * TestbedLaneBar.tsx, bundled with esbuild over its real imports (the Icon
 * component, the icon registry) and rendered with react-dom/server: the
 * check_icon_registry.mjs pattern, real source, no copy.
 *
 * Asserted:
 *   1. A mark carrying glyph "spike" draws the spike's own glyph (the
 *      registry's preDrop path, the Drops panel's), "intro" the vocal
 *      intro's (preDropVoice) — each as a glyph button, never a bare tick.
 *   2. A suggested-tier mark is drawn fainter (est-suggested), from its
 *      `tier`, as a suggested drop already is from its label.
 *   3. A mark with no glyph renders exactly as before: a plain tick, no
 *      svg (every other lane's marks).
 *
 * Run: node scripts/check_testbed_predrop_lane.mjs
 */
import { mkdtempSync, writeFileSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
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

const registrySrc = readFileSync(join(repo, 'spectra/web/src/components/iconRegistry.ts'), 'utf8');
const { code: registryCode } = esbuild.transformSync(registrySrc, { loader: 'ts', format: 'esm' });
const regPath = join(mkdtempSync(join(tmpdir(), 'predrop-lane-reg-')), 'iconRegistry.mjs');
writeFileSync(regPath, registryCode);
const { ICONS } = await import(pathToFileURL(regPath).href);

const entry = `
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { EngineLane } from ${JSON.stringify(join(repo, 'spectra/web/src/testbed/components/TestbedLaneBar.tsx'))};
export function render(estimate) {
  return renderToStaticMarkup(React.createElement(EngineLane, {
    label: 'Pre-drops', estimate, durationMs: 200000, metrics: null, toleranceMs: 500,
  }));
}
`;
const tmp = mkdtempSync(join(tmpdir(), 'predrop-lane-'));
writeFileSync(join(tmp, 'entry.mjs'), entry);
const build = esbuild.buildSync({
  entryPoints: [join(tmp, 'entry.mjs')], bundle: true, format: 'cjs', platform: 'node',
  jsx: 'automatic', outfile: join(tmp, 'out.cjs'),
  nodePaths: [join(repo, 'spectra/web/node_modules')], logLevel: 'silent',
});
ok(build.errors.length === 0, 'TestbedLaneBar.tsx bundles with its real imports');
const { render } = require(join(tmp, 'out.cjs'));

const buttons = (html) => html.split('<button').slice(1);
const hasPath = (html, d) => html.includes(`<path d="${d}"`);

console.log('§1 each kind draws its own glyph');
{
  const html = render([
    { time_ms: 69537, label: 'spike 1.15 (confident), 813 ms before the detected drop at 70350 ms',
      score: 1.154, glyph: 'spike', tier: 'confident' },
    { time_ms: 44555, label: 'vocal intro 1.50 (confident), 3295 ms before the detected drop at 47850 ms',
      score: 1.498, glyph: 'intro', tier: 'confident' },
  ]);
  const [spike, intro] = buttons(html);
  ok(spike.includes('est-glyph') && spike.includes('data-glyph="spike"'), 'the spike is a glyph button');
  ok(hasPath(spike, ICONS.preDrop) && !hasPath(spike, ICONS.preDropVoice),
    'the spike draws the spike glyph (the Drops panel\'s preDrop)');
  ok(intro.includes('est-glyph') && hasPath(intro, ICONS.preDropVoice) && !hasPath(intro, ICONS.preDrop),
    'the vocal intro draws its own glyph (preDropVoice)');
  ok(spike.includes('aria-label="') && spike.includes('813 ms before the detected drop'),
    'the mark says how far before which drop it sits');
}

console.log('§2 a suggested one is fainter');
{
  const [b] = buttons(render([{ time_ms: 1000, label: 'spike 1.02 (suggested)', score: 1.02,
                                 glyph: 'spike', tier: 'suggested' }]));
  ok(b.includes('est-suggested'), 'a suggested pre-drop carries est-suggested');
  const [c] = buttons(render([{ time_ms: 1000, label: 'x', score: 1.2, glyph: 'spike', tier: 'confident' }]));
  ok(!c.includes('est-suggested'), 'a confident one does not');
}

console.log('§3 every other lane is unchanged');
{
  const html = render([{ time_ms: 5000, label: 'confident', score: 1.1 },
                       { time_ms: 6000, label: 'suggested', score: 0.8 }]);
  const [a, b] = buttons(html);
  ok(!html.includes('<svg') && !a.includes('est-glyph') && !a.includes('data-glyph'),
    'a mark with no glyph is a plain tick, no svg');
  ok(b.includes('est-suggested'), 'a drops-lane suggestion is still fainter from its label');
}

if (failures) {
  console.log(`\nFAIL: ${failures} check(s)`);
  process.exit(1);
}
console.log('\nPASS');
