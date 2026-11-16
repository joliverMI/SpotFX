---
name: word-shapes
description: >
  The Word Shapes shape library — `fx/effects/word_shapes.py` (the one
  registry of every shape an effect can draw: heart, star, diamond, and the
  three derived views radius-per-angle / along-the-outline / signed
  distance), its told-key helper `fx/effects/word_shape_keys.py`, and the
  hex check `scripts/check_word_shapes.py`.
  TRIGGER — load BEFORE adding or changing a shape, before making any
  effect draw one (Black Hole's shaped horizon, STAR's shaped radius,
  Orbits' tethers, Fish's procession, Sauron's shaped iris and pupil,
  Fireworks' shaped burst), before touching the six `word_shape_*` told
  keys or the form/hold/release envelope, and before changing any number
  that a wave-1 "outline coverage" clarity bar is measured against.
  SKIP for the sung-word side of Word Shapes (which words reach which
  shape, the roll, the planner) — that is the sung-labels skill; and for
  the hex panel's own geometry, which is the crystal-hex-grid skill this
  one depends on.
---

# Word Shapes: the shape library

**Read this before changing a shape, drawing one, or trusting an "outline
coverage" number.** Built 2026-11-15 for row W0.1 of the Word Shapes plan
(approved by the Admiral 2026-11-15; defaults P1A/P2A/P3A), his words for
the row: *"Some starting shapes would be a heart, star, and diamond. The
effects would form an outline that represents those. ... Make it easy to
add more shapes and associations down the road."* and *"Remember to use the
crystal hex skill/info so that things look representational."*

Nothing renders differently yet: W0.1 is the library plus the told-key
helper plus the check. No effect is wired to it until wave 1.

## What the library is

`fx/effects/word_shapes.py` is the single source of every shape. A shape is
**one entry** — an id, a name, a closed outline, its starting sung words,
and whether it must stand upright — and everything else is derived from
that outline:

| view | call | who reads it |
|---|---|---|
| radius per angle | `shape.polar(theta)`, `shape.polar_mean` | Black Hole's shaped horizon, STAR's shaped radius |
| a point along the outline, by arc length | `shape.at(s)`, `shape.tangent(s)` | Orbits' tethers, Fish's procession, Fireworks' spark targets |
| signed distance (negative inside) | `shape.sdf(x, y)` exact, `shape.sdf_fast(x, y)` per frame | Sauron's shaped iris and pupil, Fireworks' fill test |

The module's own docstring is the binding statement for the unit box, the
y-DOWN convention, the winding, and the measured accuracy and cost. The
short version an effect needs:

- the outline lives in a **unit box**: centred on (0, 0), height exactly
  2.0, width whatever the shape needs; **y points DOWN**, as on the panel;
- an effect scales a view by `SIZE`, **the shape's half-height in the
  effect's own NORMALIZED coordinates, where 1.0 is the panel's own
  half-height** — the same `sx`/`sy` space every Twod effect already works
  in (`(col - cx) / ((cols - 1) / 2)`, `(row - cy) / ((rows - 1) / 2)`):
  `SIZE * polar(theta)`, `SIZE * at(s)`, `sdf(x / SIZE, y / SIZE) * SIZE`;
- the plan's default is `word_shape_size` **= 0.62**, a FRACTION, never a
  number of cells: on his crystal that one unit of shape height is 0.62 x
  18 = 11.2 rows, while one unit of shape WIDTH is 0.62 x 35.5 = 22.0
  columns;
- `polar` only exists for a shape that is **star-shaped about its centre**
  (`shape.star_shaped`, measured on first read); it raises for one that is
  not, which still has the other two views;
- **`sdf` is exact but costs ~10 ms over the whole panel — never call it
  per frame.** `sdf_fast` is the same field from a lazily built lookup
  grid: ~0.13 ms for the panel's 2,664 cells at any drawn size, within
  `FAST_TOLERANCE` (0.01 units) of the exact value inside its grid, always
  float32. Sauron's shaped iris and pupil are the case it exists for.
  `prime()` builds the lazy parts on the caller's own thread so the first
  frame does not pay for them.
- **Past the grid's box `sdf_fast` is a far-field ESTIMATE**,
  `hypot(x, y) - circumradius` floored at 0: never negative, never larger
  than the truth (a strict lower bound), within `FAR_FIELD_TOLERANCE`
  (35%) of it relatively, and stepping down from the bilinear value at the
  boundary by about the same. Use it for "how far out am I", never for a
  sub-cell decision or an inside test. **The box is fixed in SHAPE
  coordinates, so how much of the panel falls outside it is the drawn
  size's business**: none of the crystal at SIZE 0.62, ~73% of it at
  SIZE 0.27 (Sauron's pupil). The exact `sdf` as a fallback there put a
  small shape's per-frame cost straight back to ~8 ms — the PR 519
  re-review's one finding, and why the estimate exists. The check script
  uses only the exact `sdf`.

### Two things that are easy to get wrong

**The panel is anisotropic and the shape inherits that.** A crystal column
is half a real-cell pitch and a row is sqrt(3)/2 of one, so a shape drawn
with one `SIZE` in normalized space comes out about 14% wider than tall in
the room — exactly as every other effect's circle does, because the
effect's `sx`/`sy` carry it. Measuring in raw grid cells with one size for
both axes instead draws the shape squashed to 0.577 of its width; that was
a real defect in this check script (PR 519 review), and
`tests/test_word_shapes.py::test_a_drawn_shape_is_not_squashed_on_the_panel`
is what keeps it fixed.

**Nothing expensive happens at import.** `build()` does only the cheap
work; the star-shaped verdict, the polar table and the `sdf_fast` grid are
each built on first use and kept on the entry's `_lazy` cache. Importing
the module is ~3 ms — it was 0.5 s before the same review, which every
LedFX start and every SPECTRA import of the word seeds would have paid for
shapes it never draws. Keep any new derived view lazy the same way.

## Adding a shape (the whole job)

1. One `build(...)` entry in `_SHAPES`, in whatever units and winding suit
   it — `build()` normalises the box and the winding — with its starting
   sung words.
2. `.venv/bin/python scripts/check_word_shapes.py`. It must PASS: the
   thinnest point of the outline needs at least 2 real cells within one
   cell pitch, or the outline breaks into dashes on the hex lattice.
   `--ascii` draws it on the real mask — look at it; `--rows` prints the
   per-row counts.
3. Update `PINNED` in `tests/test_word_shapes.py` with the new shape's
   numbers (deliberately — see the next section).
4. Update this skill. The Sung labels side needs NOTHING: since W0.2 the
   `shape` target kind reads `Shape.words` straight off this registry
   (`sung_labels.shape_library()`, imported lazily), so a new entry here
   gets its own Sung labels card, its Claude SHAPE label and its Sonic
   reach for free — there is deliberately no second word table to keep in
   step (`.claude/skills/sung-labels/SKILL.md`). Only re-run the targeted
   tests that pin the word lists.

A shape that is **not** star-shaped is allowed: it reports
`star_shaped False`, `polar()` refuses it, and `at`/`sdf` still work. What
is NOT allowed is an entry that claims star-shaped when it is not — the
check script re-measures that independently (an sdf step-walk, against the
library's analytic ray cast) and fails.

## The outline cell counts are denominators, not decoration

`scripts/check_word_shapes.py` prints, per shape, at the default size on
his REAL `crystal-mapper` mask:

| shape | outline cells | inside cells | thinnest point |
|---|---|---|---|
| heart | 168 | 332 | 3 |
| star | 176 | 196 | 3 |
| diamond | 119 | 191 | 3 |

**Every wave-1 "outline coverage" clarity bar in the plan is a fraction of
that outline count** ("at the hold, at least 65% of the shape's outline
cells are lit by captives"), so the counts are pinned by
`tests/test_word_shapes.py::test_the_check_scripts_numbers_for_the_three_shapes_are_pinned`.
A changed outline therefore has to be a deliberate change to that test
too — which is the point: a bar whose denominator drifts silently is not a
bar. Definitions:

- the shape is PLACED in the effects' normalized space, and every
  DISTANCE is measured in **physical pitch units**: a column is 0.5 of a
  real-cell pitch, a row is sqrt(3)/2 of one, and one cell pitch (1.0) is
  the distance between two neighbouring real cells in any of the six
  lattice directions (`crystal-hex-grid` skill);
- **outline cells** = real cells within one cell pitch of the outline;
- **inside cells** = real cells strictly inside it;
- **thinnest point** = the fewest real cells within one cell pitch of any
  point ALONG the outline (720 samples by arc length). Measured along the
  outline, not per row, on purpose: a tip row holds one cell because it IS
  the tip, which says nothing about whether the stroke survives. `--rows`
  prints the per-row counts too.

## The told keys (section 2.3 of the plan)

`fx/effects/word_shape_keys.py` is the one interface between SpotFX and an
effect drawing a shape — the shape of `fx/effects/pre_drop.py` and
`fx/effects/lull_handoff.py`, and it keeps their **three rules**:

1. **The keys ride only the dedicated write** — never
   `config/effect_params.json`, never an editor surface or a band patch. An
   adopter splices `**schema_fields()` into CONFIG_SCHEMA and `*KEYS` into
   ADVANCED_KEYS (and PASSIVE_CONFIG_KEYS for a strip phase member).
2. **Every member gets every key on every write**, even `NOT_TOLD` —
   `Effect._apply_config` partial-merges, so one word's shape would
   otherwise still be standing at the next.
3. **Not told is the effect's own behaviour** — an older SpotFX, a hand
   test, a LedFX UI scrub, or a word that lost the roll renders byte for
   byte what the effect renders today.

The six keys are `word_shape` (id, "" = none), `word_shape_seq` (an effect
watches the SEQ, not the id, so two words of the same shape both edge),
`word_shape_form_s` / `_hold_s` / `_release_s`, and `word_shape_level` (the
word's Energy, 0..1, for size and counts; 0 = not told). `told(config)`
returns a `WordShapeTold` or None — and it returns **None for a shape id
this build does not know**, because a `vol.In` would make a newer SpotFX's
write drop entirely (`pre_drop.py`'s own reason).

`envelope(t, form, hold, release)` is the ONE motion law: 0 → 1 over the
form on a smoothstep, 1 through the hold, 1 → 0 over the release on a
smoothstep, 0 after. Zero speed at both ends of both ramps is the plan's
"no jump anywhere" — the claim he checks in the room. The engine fires the
band EARLY by the form time (a LEAD: positive = earlier,
`docs/SPECTRA_TIMING_CONVENTIONS.md`) so the shape completes ON the word;
the effect runs the whole thing on its own clock and resets itself after.

## Related

- `.claude/skills/crystal-hex-grid/SKILL.md` — the panel this is all
  measured against; load it before trusting any coverage number.
- `.claude/skills/sung-labels/SKILL.md` — the sung-word side (which words
  reach a shape, the roll, the planner).
- `fx/effects/pre_drop.py`, `fx/effects/lull_handoff.py` — the told-key
  siblings whose rules this one keeps.
- `docs/SPECTRA_TIMING_CONVENTIONS.md` — the LEAD/OFFSET sign conventions
  the form time rides.
- The plan: https://claude.ai/artifact/FdeYJz4kXLt2QamYR8wSDB (section 2.1
  is this row; 2.3 and 2.4 are the keys and the timing).
