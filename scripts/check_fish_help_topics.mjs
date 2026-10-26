// Executable spec for the fish help topics (spectra/web/src/help/
// helpContent.ts): every `help_topic` a fish param names in
// config/effect_params.json — the HelpLink the Initial Set tab draws beside
// that param — must be a real entry inside HELP_SECTIONS, not merely a
// substring somewhere in the file (a commented-out or differently formatted
// id would still satisfy a raw-text grep). Added with PR 1 of the fish-swim
// plan for "fish-wake-colour"; PR 2 widened it to every fish topic, so a
// new one is held the day it is registered.
//
// Reuses scripts/check_absorb_page.mjs's own loadData() shape: helpContent.ts
// is a pure-data TS module with no runtime imports, so a plain transform
// (no bundling) is enough to evaluate it for real.
//
// Run: node scripts/check_fish_help_topics.mjs
import { mkdtempSync, writeFileSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
const web = join(repo, 'spectra/web');
const require = createRequire(join(web, 'package.json'));
const esbuild = require('esbuild');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ok ${msg}`);
  else { console.log(`  FAIL ${msg}`); failures += 1; }
};

function loadData(file, name) {
  const code = esbuild.transformSync(
    readFileSync(file, 'utf8'), { loader: 'ts', format: 'cjs' },
  ).code;
  const tmp = mkdtempSync(join(tmpdir(), `fish-help-${name}-`));
  const outFile = join(tmp, 'out.cjs');
  writeFileSync(outFile, code);
  return require(outFile);
}

const { HELP_SECTIONS } = loadData(
  join(web, 'src/help/helpContent.ts'), 'help',
);
const knownIds = new Set();
for (const section of HELP_SECTIONS) {
  knownIds.add(section.id);
  for (const e of section.entries ?? []) knownIds.add(e.id);
  for (const sub of section.subsections ?? []) {
    knownIds.add(sub.id);
    for (const e of sub.entries ?? []) knownIds.add(e.id);
  }
}
const registry = JSON.parse(
  readFileSync(join(repo, 'config/effect_params.json'), 'utf8'),
);
const topics = new Set(
  Object.values(registry.effects.fish.params)
    .map((meta) => meta.help_topic)
    .filter(Boolean),
);
for (const topic of ['fish-wake-colour', 'fish-tail-drive']) {
  ok(topics.has(topic), `a fish param links "${topic}"`);
}
for (const topic of [...topics].sort()) {
  ok(knownIds.has(topic), `"${topic}" is a real section/entry in HELP_SECTIONS`);
}

if (failures) {
  console.log(`\n${failures} FAILURE(S)`);
  process.exit(1);
}
console.log('\nALL OK');
