// Executable spec for the lane-pool scene mutations in
// spectra/web/src/scenes/tabs/flareKindOps.ts (owner ask 2026-08-21,
// docs/SPECTRA_SPEC.md §88): bandPools derivation, moveKindToLane's
// join/insert modes, and the rename/delete/detach cascades that keep
// FlareBand.kind_lanes consistent with band.kinds so a save never trips
// SceneV2's own validation.
//
// This repo has no JS test runner (web builds are `tsc --noEmit && vite
// build`), so — following scripts/check_flare_preview_frontend_loop.mjs's
// precedent — this drives the REAL module, not a copy: esbuild (already in
// spectra/web/node_modules as vite's own dependency) transpiles
// flareKindOps.ts verbatim (its only import is `import type`, erased by
// transpilation), then plain Node exercises the exported functions. Zero
// network, zero browser, zero live storage.
import { mkdtempSync, writeFileSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
const require = createRequire(join(repo, 'spectra/web/package.json'));
const esbuild = require('esbuild');

const src = readFileSync(
  join(repo, 'spectra/web/src/scenes/tabs/flareKindOps.ts'), 'utf8');
const { code } = esbuild.transformSync(src, { loader: 'ts', format: 'esm' });
const modPath = join(mkdtempSync(join(tmpdir(), 'flare-lane-ops-')), 'ops.mjs');
writeFileSync(modPath, code);
const ops = await import(pathToFileURL(modPath).href);

let failures = 0;
const check = (cond, label) => {
  if (cond) console.log(`ok: ${label}`);
  else { console.error(`FAIL: ${label}`); failures += 1; }
};

const band = (kinds, kind_lanes = {}) => ({
  intensity_min: 0, intensity_max: 1, curve: 'linear', gain: 1,
  param_patch: {}, kinds, kind_lanes,
});
const kind = (name) => ({
  name, type: 'permanent', jump: null, params: { x: { mode: 'absolute', value: 1 } },
  gain: 1, hold_ms: null, trigger_offset_ms: 0,
});
const scene = (bands, kinds) => ({
  id: 's1', name: 'S', labels: [], devices: [],
  flare_kinds: kinds, responses: { flare: { bands, reroll_dice: false, color_set_jump: false } },
  update_kind: null,
});
const flareBands = (s) => s.responses.flare.bands;

// ── bandPools: derivation and ordering ─────────────────────────────────────
{
  const p = ops.bandPools(band(
    { A: 1, B: 1, C: 1, D: 1 }, { A: 'colour', C: 'colour' }));
  check(JSON.stringify(p) === JSON.stringify([
    { lane: 'colour', members: ['A', 'C'] },
    { lane: null, members: ['B'] },
    { lane: null, members: ['D'] },
  ]), 'bandPools groups by lane, pool position = first member, members in kinds order');
  const empty = ops.bandPools(band({ A: 1, B: 1 }));
  check(empty.length === 2 && empty.every((x) => x.lane === null),
    'no kind_lanes → every kind is its own solo pool (the pre-lanes rack)');
}

// ── prunedLanes: canonical storage ─────────────────────────────────────────
{
  const lanes = ops.prunedLanes({ A: 1, B: 1, C: 1 },
    { A: 'colour', B: 'colour', C: 'shape', Z: 'colour' });
  check(JSON.stringify(lanes) === JSON.stringify({ A: 'colour', B: 'colour' }),
    'prunedLanes drops unattached entries and one-member pools (C alone in "shape")');
}

// ── moveKindToLane: JOIN mints a lane on a solo anchor, places contiguous ──
{
  const s = scene([band({ Jump: 1, Rotate: 1, Shape: 1 })],
    [kind('Jump'), kind('Rotate'), kind('Shape')]);
  const out = ops.moveKindToLane(s, 'Rotate',
    { cls: 'flare', bandIdx: 0, mode: 'join', anchor: 'Jump' },
    { cls: 'flare', bandIdx: 0 });
  const b = flareBands(out)[0];
  check(JSON.stringify(Object.keys(b.kinds)) === JSON.stringify(['Jump', 'Rotate', 'Shape'])
    && b.kind_lanes.Jump === b.kind_lanes.Rotate
    && typeof b.kind_lanes.Jump === 'string' && b.kind_lanes.Jump.length > 0
    && !('Shape' in b.kind_lanes),
    'join onto a solo mints ONE fresh lane for both, right after the anchor, solos untouched');

  // join a third member into the now-existing pool
  const out2 = ops.moveKindToLane(out, 'Shape',
    { cls: 'flare', bandIdx: 0, mode: 'join', anchor: 'Jump' },
    { cls: 'flare', bandIdx: 0 });
  const b2 = flareBands(out2)[0];
  check(new Set([b2.kind_lanes.Jump, b2.kind_lanes.Rotate, b2.kind_lanes.Shape]).size === 1
    && ops.bandPools(b2).length === 1,
    'joining an existing pool reuses its lane name — one 3-member pool');

  // self-drop join is a no-op
  const self = ops.moveKindToLane(out, 'Rotate',
    { cls: 'flare', bandIdx: 0, mode: 'join', anchor: 'Rotate' },
    { cls: 'flare', bandIdx: 0 });
  check(self === out, 'join onto itself is a no-op (tap-not-drag safety)');
}

// ── moveKindToLane: INSERT leaves the pool, prunes the leftover singleton ──
{
  const s = scene(
    [band({ Jump: 1, Rotate: 1, Shape: 1 }, { Jump: 'colour', Rotate: 'colour' })],
    [kind('Jump'), kind('Rotate'), kind('Shape')]);
  const out = ops.moveKindToLane(s, 'Rotate',
    { cls: 'flare', bandIdx: 0, mode: 'insert', anchor: null },
    { cls: 'flare', bandIdx: 0 });
  const b = flareBands(out)[0];
  check(JSON.stringify(Object.keys(b.kinds)) === JSON.stringify(['Jump', 'Shape', 'Rotate'])
    && JSON.stringify(b.kind_lanes) === JSON.stringify({}),
    'insert-at-end pulls Rotate out of the pool AND prunes Jump\'s now-singleton entry');

  const before = ops.moveKindToLane(s, 'Shape',
    { cls: 'flare', bandIdx: 0, mode: 'insert', anchor: 'Jump' },
    { cls: 'flare', bandIdx: 0 });
  const bb = flareBands(before)[0];
  check(JSON.stringify(Object.keys(bb.kinds)) === JSON.stringify(['Shape', 'Jump', 'Rotate'])
    && bb.kind_lanes.Jump === 'colour' && bb.kind_lanes.Rotate === 'colour',
    'insert before a pool lands ahead of it in kinds order, pool intact');
}

// ── moveKindToLane: cross-band move prunes the source band's leftover ──────
{
  const s = scene(
    [band({ Jump: 1, Rotate: 1 }, { Jump: 'colour', Rotate: 'colour' }),
     band({ Other: 1 })],
    [kind('Jump'), kind('Rotate'), kind('Other')]);
  const out = ops.moveKindToLane(s, 'Rotate',
    { cls: 'flare', bandIdx: 1, mode: 'join', anchor: 'Other' },
    { cls: 'flare', bandIdx: 0 });
  const [b0, b1] = flareBands(out);
  check(JSON.stringify(b0.kind_lanes) === JSON.stringify({})
    && JSON.stringify(Object.keys(b0.kinds)) === JSON.stringify(['Jump'])
    && b1.kind_lanes.Other === b1.kind_lanes.Rotate && b1.kind_lanes.Other,
    'cross-band join detaches + prunes at the source, pools at the target, scale carried');
  check(flareBands(out)[1].kinds.Rotate === 1, 'moved kind keeps its scale');
}

// ── rename cascades into kind_lanes ────────────────────────────────────────
{
  const s = scene(
    [band({ Jump: 1, Rotate: 1 }, { Jump: 'colour', Rotate: 'colour' })],
    [kind('Jump'), kind('Rotate')]);
  const out = ops.renameFlareKind(s, 'Rotate', 'Spin');
  const b = flareBands(out)[0];
  check(JSON.stringify(Object.keys(b.kinds)) === JSON.stringify(['Jump', 'Spin'])
    && b.kind_lanes.Spin === 'colour' && !('Rotate' in b.kind_lanes),
    'rename swaps the kind_lanes key in place (order preserved, pool intact)');
}

// ── delete cascades and prunes ─────────────────────────────────────────────
{
  const s = scene(
    [band({ Jump: 1, Rotate: 1 }, { Jump: 'colour', Rotate: 'colour' })],
    [kind('Jump'), kind('Rotate')]);
  const out = ops.deleteFlareKind(s, 'Rotate');
  const b = flareBands(out)[0];
  check(JSON.stringify(Object.keys(b.kinds)) === JSON.stringify(['Jump'])
    && JSON.stringify(b.kind_lanes) === JSON.stringify({}),
    'delete removes the band reference AND prunes the survivor\'s singleton entry');
}

if (failures) {
  console.error(`\n${failures} check(s) FAILED`);
  process.exit(1);
}
console.log('\nAll flare-lane ops checks passed (real module via esbuild, no browser, no network).');
