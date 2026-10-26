/** Executable spec for the Review page's naming of THE DROP COLOUR CHANGE
 * (predrop plan step 2 — "the Review page names it"): describeEvent() in
 * spectra/web/src/review/describeEvent.ts, transpiled with esbuild and
 * driven directly with the show-log entries the server writes
 * (trigger_engine.drop_colour_brief on the drop's own entry, the
 * "color_sets" count engine.fire_drop_colour_event records) — the
 * check_light_show_now_next.mjs pattern: real source, no DOM.
 *
 * Asserted:
 *   1. A drop sequence's drop names the new set, how far round the wheel,
 *      and why (the rung) — and says nothing extra when the band applies.
 *   2. A hold is named in his words (Force Colour, a house mode, the 2D
 *      gradient, a preview); an unlisted hold word is shown verbatim.
 *   3. His own drop trigger carries the same note; a drop with no
 *      drop_colour detail reads exactly as before.
 *   4. The pre-drop fade's own entry, and the drop that rode it.
 *   5. The colour-set count line names the drop colour change.
 *
 * Run: node scripts/check_drop_colour_review.mjs
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'spectra/web/src/review/describeEvent.ts');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const out = mkdtempSync(path.join(tmpdir(), 'dropcolourreview-'));
const js = path.join(out, 'describeEvent.mjs');
execFileSync('npx', ['esbuild', TS, '--format=esm', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const { describeEvent } = await import(js);

const seqDrop = (dropColour) => ({
  bucket: 'triggers', key: 'drop_sequence:drop', wall_ms: 0, position_ms: 20000,
  detail: { drop_sequence: 'drop:20000', member: 'drop', his: false, intensity: 0.8,
            ...(dropColour ? { drop_colour: dropColour } : {}) },
});

console.log('§1 a drop names its new colours');
{
  const s = describeEvent(seqDrop({ result: 'jumped', to_set_id: 'c1', to_set_name: 'Mid - Fire',
                                     distance_deg: 166.4, rung: 'band', moment: 'drop' }));
  ok(s === 'Drop sequence: drop (detected) @ ⚡0.80 · new colours: Mid - Fire (166° away)', s);
  const w = describeEvent(seqDrop({ result: 'jumped', to_set_name: 'Orbit - Green',
                                     distance_deg: 120, rung: 'widest_available' }));
  ok(w.endsWith('new colours: Orbit - Green (120° away), the farthest set allowed (none 150-210° away)'), w);
  const r = describeEvent(seqDrop({ result: 'jumped', to_set_name: 'Hype 1', rung: 'to_rainbow' }));
  ok(r.endsWith('new colours: Hype 1, a rainbow'), r);
}

console.log('§2 a hold is named');
{
  const f = describeEvent(seqDrop({ result: 'held', held_for: 'force_color' }));
  ok(f.endsWith(' · colours held (Force Colour holds the colours)'), f);
  const h = describeEvent(seqDrop({ result: 'held', held_for: 'house_mode' }));
  ok(h.endsWith('(a house mode keeps its own look)'), h);
  const g = describeEvent(seqDrop({ result: 'held', held_for: 'gradient_drift' }));
  ok(g.endsWith('(the 2D gradient made its own drop change)'), g);
  const p = describeEvent(seqDrop({ result: 'held', held_for: 'preview' }));
  ok(p.endsWith('(a Preview held the room)'), p);
  const u = describeEvent(seqDrop({ result: 'held', held_for: 'something_new' }));
  ok(u.endsWith('(something_new)'), `an unlisted hold is verbatim: ${u}`);
  const k = describeEvent(seqDrop({ result: 'kept_current' }));
  ok(k.endsWith(' · colours kept (no other set allowed)'), k);
  const off = describeEvent(seqDrop({ result: 'off' }));
  ok(off === 'Drop sequence: drop (detected) @ ⚡0.80', `the setting off adds nothing: ${off}`);
}

console.log('§3 his own drop trigger, and a drop with no colour detail');
{
  const his = describeEvent({
    bucket: 'triggers', key: 'authored:fire_response', wall_ms: 0, position_ms: 3000,
    detail: { trigger_id: 'his-drop', action_kind: 'fire_response', source: 'authored',
              drop_colour: { result: 'jumped', to_set_name: 'Black Hole - Cyan',
                             distance_deg: 176.5, rung: 'band' } },
  });
  ok(his === 'Trigger fired: fire_response (authored) · new colours: Black Hole - Cyan (177° away)', his);
  const plain = describeEvent(seqDrop(null));
  ok(plain === 'Drop sequence: drop (detected) @ ⚡0.80', `unchanged without detail: ${plain}`);
}

console.log('§4 the fade across a pre-drop');
{
  const pre = describeEvent({
    bucket: 'triggers', key: 'drop_sequence:pre_drop_colour', wall_ms: 0, position_ms: 19200,
    detail: { drop_sequence: 'drop:20000', member: 'pre_drop',
              drop_colour: { result: 'jumped', to_set_name: 'Mid - Fire', distance_deg: 166,
                             rung: 'band', moment: 'pre_drop' } },
  });
  ok(pre === 'Drop sequence: colour change at the pre-drop · new colours: Mid - Fire (166° away), fading to the drop', pre);
  const rode = describeEvent(seqDrop({ result: 'faded_at_pre_drop',
    pre_drop: { result: 'jumped', to_set_name: 'Mid - Fire', distance_deg: 166, rung: 'band',
                moment: 'pre_drop' } }));
  ok(rode.endsWith('new colours: Mid - Fire (166° away), fading to the drop (at its pre-drop)'), rode);
}

console.log('§5 the colour-set count');
{
  const c = describeEvent({ bucket: 'color_sets', key: 'c1', wall_ms: 0, position_ms: 20000,
    detail: { set_name: 'Mid - Fire', via: 'drop_colour', distance_deg: 166.4, moment: 'drop' } });
  ok(c === 'Colour set: Mid - Fire (drop colour change, 166° away)', c);
  const a = describeEvent({ bucket: 'color_sets', key: 'c1', wall_ms: 0, position_ms: 1,
    detail: { set_name: 'Mid - Fire', via: 'analysed_cue' } });
  ok(a === 'Colour set: Mid - Fire (analysed moment)', `the analysed moment is unchanged: ${a}`);
}

if (failures) {
  console.log(`\nFAIL: ${failures} check(s)`);
  process.exit(1);
}
console.log('\nPASS');
