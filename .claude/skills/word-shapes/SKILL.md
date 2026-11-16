---
name: word-shapes
description: >
  The Word Shapes shape library — `fx/effects/word_shapes.py` (the one
  registry of every shape an effect can draw: heart, star, diamond, and the
  three derived views radius-per-angle / along-the-outline / signed
  distance), its told-key helper `fx/effects/word_shape_keys.py`, and the
  hex check `scripts/check_word_shapes.py` — AND the engine contract that
  drives them (row W0.3): the "word" response class, the `word_shape` flare
  kind, the five room timings, the planner's shape branch and the one told
  write.
  TRIGGER — load BEFORE adding or changing a shape, before making any
  effect draw one (Black Hole's shaped horizon, STAR's shaped radius,
  Orbits' tethers, Fish's procession, Sauron's shaped iris and pupil,
  Fireworks' shaped burst), before touching the six `word_shape_*` told
  keys or the form/hold/release envelope, before touching the Words
  response section or anything that decides WHEN a shape fires, and before
  changing any number that a wave-1 "outline coverage" clarity bar is
  measured against.
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

Nothing renders differently yet, and that is still true after W0.3: W0.1 is
the library plus the told-key helper plus the check, W0.3 is the whole
engine contract above it, and NO EFFECT IS WIRED until wave 1 —
`fx.device_model.WORD_SHAPE_EFFECTS` is empty, so even a scene with a Words
band and a Word Shape kind writes to no fixture.

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

## The engine contract (row W0.3, merged 2026-11-15)

Everything between a sung word and the told write. Read this before
touching the Words section, the `word_shape` kind, or any timing.

**THE FIFTH RESPONSE CLASS.** `models/scene.py`'s `RESPONSE_CLASSES` is now
five: `flare, charge, lull, drop, word`. `responses["word"]` is an
ORDINARY `ResponseSpec` — bands over Energy, lanes, kinds — so a colour
kind pooled beside the shape fires exactly as it would anywhere (his Q5 A),
and a momentary kind beside it still spikes and releases. Two deliberate
asymmetries, each proven by test rather than left to convention:

- **no trigger may name it.** `FireResponseAction` refuses
  `event_class="word"` (`TRIGGER_RESPONSE_CLASSES` is the legal four), and
  `spectra/api/engine.py`'s manual event injector leaves it out too — a
  bare class+intensity injection has no shape and no envelope to carry. A
  sung word is the only way in.
- **the phase machinery never sees it.** `scene_response.PHASE_RAMP_MS` has
  no `word` key, so a Words band arms no charge/lull/drop choreography and
  takes no drop-colour claim. The flare PUNCH stays ALLOWED (set
  explicitly, not left to the default) because the reason `on_event`
  suppresses it for a phase — a phase's own band must not hold its own
  start lit — does not apply to a word; in practice it is unreachable,
  since P3 A skips a shape outright while a phase is armed.

**THE KIND.** `FlareKind.type` gains `word_shape`: the `firework_burst`
shape — no jump, params, gain or hold of its own; it may carry
`min_intensity`, `enabled`, `trigger_offset_ms` like any kind. Attached to
a flare/charge/lull/drop band it is ACCEPTED (a drag into the Flares rack
must not be a validation error) and a NO-OP at fire time, and
`scene_store.scene_warnings` says so on every save.

**THE BAND IS THE SWITCH** (his Q6 A). A scene with no Words band is
`no_class` and writes nothing. That, plus the empty `WORD_SHAPE_EFFECTS`,
is why this row changed nothing in his room.

**WHERE EACH NUMBER COMES FROM.** The five timings are ROOM settings
(Sonic-tellable, Help topic `word-shapes`), resolved by ONE pure function,
`room_controls.word_shape_timing(energy, phrase_ms, settings,
effect_types)`:

| number | default | rule |
|---|---|---|
| `word_shape_form_slow_s` | 0.9 | the form at Energy 0 |
| `word_shape_form_fast_s` | 0.5 | the form at `lyric_events.FAST_AT_ENERGY` (0.75) and above, linear between |
| `word_shape_hold_min_s` / `_hold_max_s` | 0.8 / 2.0 | the hold is the sung phrase's own length, clamped |
| `word_shape_release_ratio` | 1.5 | the release is this × the form |

The form is floored at `fx.device_model.word_shape_form_min_s` — a
per-effect minimum (`WORD_SHAPE_FORM_MIN_S`, empty until Fish's wave-1 row
gives it 2.0 s). **That accessor is the one thing easiest to get wrong
here, and the W0.3 review caught exactly this:**

- **THE LEAD IS THE FORM IN PRACTICE.** The effect is told the time LEFT to
  the word, and the band fired a lead early, so those are the same number.
  A floor applied to the lead therefore does not merely fire early — it
  makes the shape FORM over that floor.
- **so BOTH halves ask the SHOWING scene's own live effects.** Plan time:
  `engine.lyric_shape_timing`, over `conductor.virtuals`. Fire time:
  `engine.fire_lyric_shape_event`, again over the live effects. Asking
  globally at plan time would have given a Black Hole scene Fish's 2.0 s
  instead of the approved Energy-paced 0.5-0.9 s the moment Fish's row
  landed.
- **the GLOBAL maximum is the no-room fallback only** —
  `TriggerEngine._room_shape_timing`, for an engine `services/engine.py`
  has not wired (a spec, a Test Bed with no conductor). It is the only safe
  answer when the room is unknown.
- a late tick therefore shortens the form rather than landing the shape
  late — the same shape the word-colour ramp already has.

**THE LEAD.** The form IS the lead: `fire_at = word − form` (LEAD family,
positive = earlier — `docs/SPECTRA_TIMING_CONVENTIONS.md` has both rows
with file:line cites). One loop in
`trigger_engine._tick_lyric_words` fires a colour word and a shape word
with the same arithmetic; only the hook differs.

**THE PLANNER'S SHAPE BRANCH** (`lyric_events.plan_words`), in order, and
BEFORE the colour branch:

1. sat out (the roll — unchanged, `chance_for`/`roll_hits` untouched) →
   nothing;
2. phrase taken → nothing;
3. **a DROP inside the imprint window skips the SHAPE** (his Q5 A: the
   drop is the bigger moment) — and the word FALLS THROUGH to the colour
   branch, where it imprints on that drop exactly as it does today. Blind
   to `can_carry`: that flag is about carrying a COLOUR, and the colour
   branch applies it itself. A flare or a scene change does not stop a
   shape, and a shape never imprints on anything;
4. **nothing can draw it** (`can_draw(energy)`, below) → the word is
   planned as the ordinary colour word it is;
5. too soon (the SHARED minimum gap — a shape counts against the next word
   and takes its line, exactly like a fired colour word) → nothing;
6. otherwise `VERDICT_SHAPE`, with `transition_ms = form_s × 1000`.

In 3 and 4 the only trace of the shape is `WordAction.shape_skipped`
(`drop_wins` / `nothing_can_draw`), which `describe` and `action_payload`
carry so the Test Bed can say *"it would have drawn a heart, but ..."*
rather than looking like a plain colour word. A word with NO colour set has
nothing to fall through to, so it keeps its shape either way: a drop near it
ends it, and an undrawable one is still planned as a shape, which the fire
path logs as `no_class`.

**A word reaching BOTH a shape and colour sets is a SHAPE** — the Words
band's own colour kinds are how a shape word recolours the room.

**HIS EXISTING WORD COLOURS ARE BYTE-FOR-BYTE AS TODAY**, and two rules
(both from the W0.3 reviews, 2026-11-16) are what guarantee it. All 57 of
his songs with sung words have word colours switched on, so a feature that
waits for a Words band must never SUBTRACT a colour change while it waits:

1. **`can_draw(energy)`, asked at PLAN time.** `scene_response.
   words_band_draws` over the showing scene (bound by
   `engine.lyric_can_draw`): does its Words section have a band covering
   this Energy with an enabled `word_shape` kind that fires at it? If not,
   the word is planned as the colour word it is — **own `fire_at`, own
   transition, own imprint**. This has to be a plan-time question because
   IT DECIDES THE TIMING: a shape fires its form (0.5-0.9 s) early, a
   colour its own `transition_ms_for` (0.15-3 s). Deciding at the fire
   could only hand the colour whatever the shape's lead left — a quiet
   colour that should glide in over 2-3 s would arrive in under a second,
   and a lead that has passed cannot be given back.
2. **a drop near the word skips only the SHAPE** (rule 3 above), so the
   word still tints the drop.

**THE FIRE-TIME FALLBACK IS THE NET** for the one race the plan cannot see:
the showing scene changed inside the replan window (`LYRIC_REPLAN_S`, 1 s),
so the word was planned as a shape and arrives somewhere that cannot draw
it. Then `on_word_shape` reports `lyric_events.SHAPE_NOTHING_DREW`
(`no_class` / `no_band` / `no_active_scene`) and the word takes the colour
path through the same hook (`lyric_events.colour_fallback`), logged
`lyric:shape` with `result: fell_back_to_colour` — with the shape's own lead
behind it, the best available once the moment has passed. Two things the
net deliberately is NOT:

- **not for a HOLD.** A preview, Absorb, a house mode or P3 A's
  charge/lull/drop holds a colour word today too, so falling back there
  would walk straight through a gate.
- **not for `applied` with `virtuals: 0`.** A Words band that RAN is the
  designed path — its own colour kinds included — and before wave 1 that
  is *every* Words band. He attached that band and chose its behaviour.

**P3 A, THE FIRE-TIME SKIP.** `engine.fire_lyric_shape_event` takes the
gates in this order: the response gate at the ANALYSED tier (a preview,
Absorb, a house mode that ignores music, a closed tier) → a house mode that
owns the room → **a charge, lull or drop happening on the showing scene,
skipped with `held_for: "phase"`** (`ResponseEngine.phase_armed()`: the
`_phase_armed` flag for a charge/lull, and a drop's own ramp window, since
a drop arms no phase of its own). Every outcome is logged as `lyric:shape`
on the show log and pushed to every open page.

**THE WORDS SECTION IGNORES PER-KIND OFFSETS** (same review).
`on_word_shape` fires its band ATOMICALLY (`anchor_relocated` False), so a
kind's own `FlareKind.trigger_offset_ms` does not move the real fire: a word
has one moment, and the one lead that matters is the form that lands the
shape on it. Stated three ways rather than left to be discovered — the save
warns (`scene_store.scene_warnings`), the preview draws the mark at offset 0
for this type, and `docs/SPECTRA_TIMING_CONVENTIONS.md` carries the row.

**THE WRITE.** `_word_shape` reads the action off the `WORD_SHAPE_ACTIVE`
ContextVar (the `lyric_events.ACTIVE` pattern — the kind pipeline is shared
by five classes and must not grow a per-class argument) and makes ONE
instant jump of all six keys, through `word_shape_keys.keys_for`, on every
`WORD_SHAPE_EFFECTS` virtual in `_flare_states()` (so a Light Show
"flares off" target gets none). Nothing carried, nothing released. No
action (the kind on a flare band, or a preview with nothing synthesised) →
no write, named `no_word`.

**THE PREVIEW.** `kind_lead_ms` returns the form for this type, so the
existing ruler already draws the three marks: start = word − form,
trigger = word, end = word + hold + release. `fire_kind` synthesises a
`PreviewWordShape` (deliberately NOT a fabricated `WordHit` — a preview
must never flow into the show log looking like a real word), default shape
heart, and `POST /api/flare-preview/open` takes an optional `shape` the
W2.1 picker will pass.

## Related

- `.claude/skills/crystal-hex-grid/SKILL.md` — the panel this is all
  measured against; load it before trusting any coverage number.
- `.claude/skills/sung-labels/SKILL.md` — the sung-word side (which words
  reach a shape, the roll, the planner).
- `fx/effects/pre_drop.py`, `fx/effects/lull_handoff.py` — the told-key
  siblings whose rules this one keeps.
- `docs/SPECTRA_TIMING_CONVENTIONS.md` — the LEAD/OFFSET sign conventions
  the form time rides.
- `docs/agents/scenes-and-flares.md` — the Words section beside the other
  four, from the scene-authoring side.
- `tests/test_word_shape_contract.py` — the engine contract's own proofs;
  `tests/test_word_shapes.py` the library's.
- The plan: https://claude.ai/artifact/FdeYJz4kXLt2QamYR8wSDB (section 2.1
  is the library; 2.3 and 2.4 are the keys and the timing; 2.3-2.5 are the
  engine contract).
