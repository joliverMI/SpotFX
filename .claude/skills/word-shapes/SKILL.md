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

W0.1 is the library plus the told-key helper plus the check, W0.3 is the
whole engine contract above it, and WAVE 1 wires the effects one at a time
— `fx.device_model.WORD_SHAPE_EFFECTS` names exactly those, so a scene
with a Words band and a Word Shape kind writes to those fixtures and no
others. "Wave 1, effect by effect", below, is the live list, and
`tests/test_word_shape_contract.py`'s `WIRED` tuple is the ledger the
contract asserts against; the Admiral's tuning gate
(`docs/ADDING_EFFECTS.md`) stands in front of each of them, and nothing is
in his room until the row is deployed.

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
watches the SEQ, not the id, so two words of the same shape both edge;
`next_seq()` is the one source — **monotonic per PROCESS, clock-seeded, so a
fresh engine or a restart never repeats the seq a running or persisted
effect already holds**, row W4.1),
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
`no_class` and writes nothing. That, plus `WORD_SHAPE_EFFECTS`, is the pair
of switches between a sung word and a fixture: W0.3 changed nothing in his
room because the second was empty, and wave 1 opens it one effect at a
time.

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

**THE HOLD STRETCH (row W4.2, his room verdict 2026-11-17).** The clamped
hold is then MULTIPLIED by `fx.device_model.word_shape_hold_x(effect_types)`
— `WORD_SHAPE_HOLD_X = {"radial": 1.5, "blackhole": 1.5, "fireworks":
1.5}`, from his own words ("star and black hole look pretty good, but could
last a little longer" / Fireworks "have it hold 50% longer"). So those three
hold **1.2–3.0 s**; Sauron, Orbits and Fish still hold 0.8–2.0 s. Four
things to know, every one of them a place to go wrong:

- **AFTER the clamp, on purpose**, so the MAXIMUM stretches too. Clamping
  after multiplying would cut his half-again back to 2.0 s on exactly the
  long phrases he was watching.
- **the LARGEST stretch among the showing types**, so a panel showing a
  stretched effect beside an unstretched one holds long enough for the one
  that needs it.
- **no effect types at all → 1.0, NOT the global maximum** — the OPPOSITE
  of the form floor's fallback below, and deliberately so: "longest is
  safest" protects a shape's LANDING, and the hold begins once the shape is
  already complete, so it has no landing to protect.
- **decided at PLAN time and never re-made exact.** The fire path keeps the
  planner's hold (`engine.fire_lyric_shape_event` re-floors only the form),
  so a scene change between the plan and the word carries the PLANNED
  scene's stretch — at most one scene's difference, the same trade the
  colour path already makes.

It is a code constant, **not Sonic-tellable**, for the form floor's own
reason; the two hold settings' Sonic text and the `word-shapes` Help topic
both say "STAR, Black Hole and Fireworks hold half again as long as this."
A live knob would be a per-effect registry param read off
`conductor.virtuals[...].param_baseline` (the `pulse_effect_ms` pattern),
not this constant. The preview (`scene_response.preview_word_shape`) and
the Test Bed pass the showing types through the same one function, so both
show the stretched hold unasked. The RELEASE is a multiple of the FORM, so
the stretch never reaches it.

The form is floored at `fx.device_model.word_shape_form_min_s` — a
per-effect minimum (`WORD_SHAPE_FORM_MIN_S`; **two are declared**, the
Fish's 2.0 s since row W1.4 and FIREWORKS' 2.0 s since row W4.3 — STAR,
Sauron, Orbits and the Black Hole take the approved Energy-paced form).
**That accessor is the one thing easiest to get wrong here, and the
W0.3 review caught exactly this:**

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

**A FLOOR IS ALSO A LEAD ON EVERYTHING ELSE IN THAT BAND.** Because the
form is the lead and `on_word_shape` fires the band ATOMICALLY, a colour
kind pooled in a Words band on a floored scene lands that early too — 2.0 s
early on a Fish or a Fireworks scene. Stated here rather than discovered:
it is a property of the band, not of the effect that declared the floor.

**THE LEAD.** The form IS the lead: `fire_at = word − form` (LEAD family,
positive = earlier — `docs/SPECTRA_TIMING_CONVENTIONS.md` has both rows
with file:line cites). One loop in
`trigger_engine._tick_lyric_words` fires a colour word and a shape word
with the same arithmetic; only the hook differs.

**THE PLANNER'S SHAPE BRANCH** (`lyric_events.plan_words`), in order, and
BEFORE the colour branch:

1. sat out (the roll — `chance_for`/`roll_hits`, whose only addition since
   is WORD TEST MODE, 2026-11-17: `RoomControlState.word_test_mode` forces
   every chance to 1.0, so a low-confidence SHAPE word draws on every play
   too, and a word pinned Never still sits out. It reaches the roll ONLY —
   the branch below, the form/hold/release and the Words band's own gates
   are untouched; `.claude/skills/sung-labels/SKILL.md` carries the rest)
   → nothing;
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

**THE SEQ BELONGS TO THE PROCESS, NOT TO AN ENGINE** (row W4.1, 2026-11-17
— the fix for his "the preview of the flare doesn't seem to work").
`word_shape_keys.next_seq()` is the one source: seeded from the wall clock
in milliseconds on first use, +1 per write, re-seeded forward whenever the
clock passes it. Every `ResponseEngine` draws from it — the live one, the
preview's scratch one, the dark timeline's — and keeps only
`_last_word_shape_seq`, a record for its fire record. It has to be unique
against TWO things, and a per-engine 1, 2, 3 was unique against neither:

- **another engine in the same process.** `open_program_hold` seeds a fresh
  scratch engine on EVERY `/fire`, so the old counter wrote 1 on every lap:
  lap 1 edged against the effect's 0 baseline and lap 2 onward wrote 1 to an
  effect already holding 1 — no edge, no shape. All six effects share the
  edge rule, so all six were affected.
- **a persisted config.** The in-process fx host persists each effect's
  config, the six keys included, so a fresh instance's creation baseline (the
  no-fire rule) could be exactly the seq a restarted SpotFX was about to
  write first — one swallowed shape, on a tuning day.

Still a plain int (SEQ's schema is `int, min 0`) and still landed by a JUMP,
never a tween. `tests/test_flare_preview_hold.py`'s section 10 proves the
whole of it on the real headless host.

**THE PREVIEW.** `kind_lead_ms` returns the form for this type, so the
existing ruler already draws the three marks: start = word − form,
trigger = word, end = word + hold + release. `fire_kind` synthesises a
`PreviewWordShape` (deliberately NOT a fabricated `WordHit` — a preview
must never flow into the show log looking like a real word), default shape
heart, and `POST /api/flare-preview/open` takes an optional `shape`.

Since **W2.1** (merged) that picker exists: the Scenes page's **Words**
tab mounts the ordinary response editor on the `word` class, and a
`word_shape` kind's ▶ Preview carries a heart/star/diamond choice read
from the shape library itself (`GET /api/sung-labels`' `shapes` rows —
never three hard-coded ids). Three things that row settled and a later
change must keep:

- **`POST /api/flare-preview/fire` takes `shape` too**, through
  `flare_preview_hold.open_hold(..., shape=)` →
  `FlareKindProgram(scene, kind, shape)` → `fire_kind(shape=)`. Open alone
  would have moved the RULER while the room kept drawing heart — the
  preview lying about what it fires.
- **the overlay reads its spans off the ENVELOPE, not the writes**
  (`word_shape` on the timeline, via
  `spectra/web/src/scenes/tabs/wordShapePreview.ts`), because a shape
  produces NO writes while `WORD_SHAPE_EFFECTS` is empty; it labels them
  "forms" / "holds" / "releases" and the trigger mark "the word".
- **that mark does not drag** — the Words section ignores a per-kind
  offset, so authoring one here would be a number the engine ignores.

**WHAT ROW W4.1 ADDED TO THE PREVIEW** (2026-11-17, after his first room
test: "the preview of the flare doesn't seem to work"). Four facts, and
anything that touches this path has to keep all four:

1. **A shape on EVERY lap.** The loop calls `/fire` once per lap, each one
   through a fresh scratch engine — the process-wide seq above is what makes
   each one an edge. Nothing about the hold changed: still the snapshot once
   per session, the deadline, the 3-minute ceiling, the sweep, the
   `apply_scene` per fire.
2. **The close hands the room back with NO shape told.**
   `flare_preview_hold._revert_writes` replaces the six keys in the snapshot
   (only where the snapshot HAS them — an effect that knows no shapes would
   reject them and lose the whole validated write) with
   `word_shape_keys.NOT_TOLD`, and `recover_stale_hold` lands the same way.
   A standing preview shape then RELEASES from its fraction (the clearing
   write every effect already honours; Fireworks' sparks finish on their own
   clock), and the last sung word's shape never re-forms as a parting gift.
3. **The hold is always the room's SHORTEST.** `preview_word_shape` passes
   `phrase_ms=0.0`, so the clamp returns `word_shape_hold_min_s` (0.8 s). The
   ruler used to be truthful but silent about it; `PreviewWordShape` now
   carries `hold_max_s` too, the timeline's `word_shape` block passes it on,
   and the sentence under the ruler says both numbers. Read off the server
   like every other time on that ruler — the frontend computes none.
4. **The room is NOT moved on `/open`** (the overlay opens dark by design),
   so on a scene that is not the one showing, lap 1's shape forms while the
   scene itself is still fading in over its stored crossfade; laps 2+ are
   clean. Stated in the overlay's own sentence and in the help topic rather
   than left for him to wonder about.

The kind itself is declared with **no knobs** (`flareKindOps.
newWordShapeKind`) and adding the Words section seeds one attached across
the whole Energy range; `types.ts` keeps TWO class lists —
`RESPONSE_CLASSES` (the four a trigger may name) and
`SCENE_RESPONSE_CLASSES` (the five a scene may declare). The save's
`warnings` surface as inline notes on the kind each one names.

## Sonic reach (row W2.4, built 2026-11-15)

Everything in this feature is Sonic-tellable, and the `sonic-ops` skill's
checklist is the binding process for changing any of it. What exists:

| what he can say | the operation | domain |
|---|---|---|
| read or edit a shape's sung words | `list_sung_label_targets` / `get_sung_labels` / `edit_sung_label`, `kind="shape"` | lyrics |
| match a word or phrase to a shape | `add_lyric_match`, `target_kind="shape"` | lyrics |
| what each word of a song would do | `preview_lyric_events` (verdict `shape`, plus `shape_skipped` = `drop_wins` / `nothing_can_draw`) | lyrics |
| the five room timings | `set_setting` / `get_settings` on the five `word_shape_*` keys (Help topic `word-shapes`) | settings |
| declare a `word_shape` kind on a scene | `set_flare_kind`, `type="word_shape"` | scene |
| **switch it on / off for a scene** | **`attach_flare_kind` / `detach_flare_kind`** | scene |
| any per-effect `word_shape_*` param | `get_param_info` / `set_scene_entry_param`, for free once a wave-1 row REGISTERS it in `config/effect_params.json` | scene |

**DECLARED AND ATTACHED ARE DIFFERENT FACTS, and this is the one that
bites.** `set_flare_kind` only declares a kind; THE BAND IS THE SWITCH
(his Q6 A), so a `word_shape` kind on a scene with no Words band draws
nothing at all. `attach_flare_kind(scene, kind, response_class,
intensity_min, intensity_max, lane=None)` is what gives the scene that
band — creating the band, and the whole Words section, when none exists —
and `detach_flare_kind(scene, kind, response_class)` is plan §7's own undo
path ("detaching it from the Words band does the same"): it drops the kind
from every band of that class, drops a band left empty, drops the section
once it has no bands, and leaves the kind DECLARED. Three things worth
knowing before using them:

- a window that only PARTLY overlaps an existing band is REFUSED, naming
  that band's real window — `ResponseSpec._no_overlap` would refuse the
  save anyway, and silently retargeting his authored band is not Sonic's
  call. Read `get_flare_kind`'s `attachments` first (its `attached_to` on
  `list_flare_kinds` is the compact form);
- both replies carry `scene_store.scene_warnings()` verbatim, which is
  how the two legal-but-inert cases reach him rather than only the log: a
  `word_shape` attached to a Flares/Charge/Lull/Drop band, and a kind
  whose `trigger_offset_ms` the Words section ignores;
- both are backed up and verified before the write like every other
  scene edit, so `undo_last_scene_change` reverses either one — which is
  also why an attach that would change NOTHING (same kind, same band,
  same lane) is REFUSED rather than performed: a repeated no-op would
  evict real pre-edit snapshots from the ten-entry ring with copies of
  the same state.

The same row gave the two READS the matching half, since declared and
attached could not be told apart before it: `list_flare_kinds` carries
`attached_to` (the classes, compact) and `get_flare_kind` carries
`attachments` (class, window, scale, lane per band) plus the scene's own
`warnings`. The audit of the whole table above is
`tests/test_scene_console.py::test_the_word_shapes_sonic_reach_is_complete`,
which names where each claim's behaviour is proven.

## Wave 1, effect by effect

Each row below is one effect WIRED to the told keys:
`fx.device_model.WORD_SHAPE_EFFECTS` is the membership, and
`tests/test_word_shape_contract.py`'s own `WIRED` tuple must equal it. The
effect's own `SKILL.md` is the binding statement for how it draws the
shape; this is the one-paragraph index, plus the clarity numbers it
actually measured.

### Black Hole / `blackhole` (row W1.1, 2026-11-16) — the shaped horizon

`fx/effects/blackhole.py` (`blackhole`, the Matrix crystal effect only —
`blackhole1d` is a STRIP and gets nothing). **One change in the effect: the
event-horizon radius became a radius per angle**,
`(1 - m) * horizon_scale + m * word_shape_size * shape.polar(theta)`, with
the breathing and the charge/lull/drop math applied to that unchanged, so
every existing phase composes with no code of its own. The captives ride
the swelling ring out onto the outline and circle it at the ring's own
LINEAR speed (`omega x ref / r(theta)`, with `ref` the blended mean radius
— that is what keeps them from thinning over a heart's lobes), the black
disc follows the outline 1.5 cell pitches in, and the whole thing beats
with the bass.

Two things this row learned that the next ones should read before
repeating them:

- **A SIZE MULTIPLIER IS NOT A BEAT ON A SHAPE.** This effect's breathing
  is a multiplier on its radius, and a shaped radius is ~3x the ring's, so
  the same multiplier is 3x the absolute swell: at his own `horizon_audio`
  0.3 on loud lows the heart stood 12% WIDE of its told size and the
  clarity bar — whose denominator is the outline band at SIZE 0.62 —
  measured almost nothing, while the captives were tracing the shape
  beautifully one band out. The fix is an ADDITIVE swell capped at HALF A
  CELL, which makes the plan's own "the radius equals `SIZE x polar(theta)`
  within half a cell at the hold" true under any audio rather than only in
  silence. **Any effect whose shape rides a per-frame audio gain has this
  problem**; measure the drawn outline against the pinned band before
  trusting a coverage number.
- **MEASURE THE DRAWN BAND BESIDE THE PINNED ONE.** Coverage against the
  pinned 168/176/119 answers "is the shape where it was told to be";
  coverage against the band the effect is actually drawing answers "is the
  outline continuous". A low number on the first with a high number on the
  second means the shape MOVED, not that it broke up — which is exactly the
  diagnosis above, and it took a second denominator to see it.
  `tests/test_blackhole_word_shape.py::drawn_band` is the helper.

Measured (`scripts/check_blackhole_word_shape.py`, his own Black Hole V2
crystal entry, three seeds of busy music, at the word / mid-hold / the
hold's end): heart 76.8-85.2%, star 58.5-79.0%, diamond 89.1-92.8% of the
pinned outline cells, inside black 100% everywhere, cost +0.1 ms p50.
**The one miss is the star at Energy 0.2 at the END of a 1.2 s hold
(~58%), and it is the captive POPULATION, not the shape** — his
quiet-Energy binding spawns 0.8 blobs/s for a 176-cell outline, and
`spawn_rate` 2.0 or `beat_burst` 3 (his own params) read 72.7% / 75.6% in
the same room. `.claude/skills/blackhole-effect/SKILL.md`'s own "WORD
SHAPES" section is the full record.

### Fireworks / `fireworks` (row W1.2, 2026-11-16) — the shaped payoff burst

`.claude/skills/fireworks-effect/SKILL.md`'s "WORD SHAPES" section;
`fx/effects/fireworks.py`'s WORD SHAPES block comment; evidence
`scripts/check_fireworks_word_shape.py` (`--ascii` draws it on the real
mask, and since W4.3 also graded by luminance), proofs
`tests/test_fireworks_word_shape.py`. Four registered params
(`word_shape_size` 0.62, `word_shape_outline_share` 0.70,
`word_shape_sparks_quiet` **90**, `word_shape_sparks_loud` **150** — W1.2
shipped 60/100; W4.3 raised them); **`WORD_SHAPE_FORM_MIN_S["fireworks"] =
2.0` since W4.3**. **`fireworks1d` is deliberately NOT a member** — there
is nowhere to draw a shape on one line.

ONE big burst from the centre per told word, 60 sparks at Energy 0 to 100 at
Energy 1, 70% of them aimed along the outline BY ARC LENGTH with half a cell
of jitter and the rest inside at a random depth, nothing on a lattice.
**Every spark's launch velocity is solved from the effect's own drag** (the
draw's own geometric sum, computed per burst for the frame rate it
integrates at) so it is standing on its target the frame the form ends —
measured arrival error 0.000 cell pitches. A separate damper then holds them
where they arrived (the hang), each twinkling off its own position, and they
fade spark by spark over the release on their own `p_life`: about 1.93x an
ordinary burst's life at the effect's DEFAULT `burst_life`, which is where
the plan's "about twice" comes from, and 1.22x against his own entry's tuned
1.9 s — the shape's duration is the told envelope's, a room setting, not the
effect's to stretch. Uncapped and additive, so the scene's rockets, beat
bursts and drop tail carry on underneath; a second word bursts over the
first, which keeps fading, so there is nothing to blend on release.

Clarity bar, the shape alone on the real mask at SIZE 0.62, on the word
(>= 70% of the outline cells lit, fill ratio <= 0.70):

| shape | Energy 0.2 | Energy 0.8 | the plan's sim |
|---|---|---|---|
| heart | 87.5% / 0.39 | 95.2% / 0.60 | 72% / 0.46, 87% / 0.47 |
| star | 92.0% / 0.50 | 98.3% / 0.64 | 76% / 0.65, 86% / 0.65 |
| diamond | 95.8% / 0.43 | 100.0% / 0.63 | 81% / 0.50, 90% / 0.53 |

Two numbers the measurements forced, worth knowing before another row copies
the approach: the colours come off a 0.15 SLICE of the gradient read by the
spark's angle, not the whole gradient, because sparks from opposite ends of
a rainbow desaturate each other where they overlap at his blob size; and the
burst's origins are scattered over a cell with their own fade-in from 0,
because 100 sparks stacked on one cell saturate it.

**The one section-6 bar this row does not reach, and the finding every other
row's "no white" bar should have in hand:** alone the shape lights no
white-ish cell at all, but over a LIVE show 1.74-2.01% of the lit cells read
washed out at the worst frame against the room's own 0.62% — about ten cells
of 976 while the shape hangs. The per-frame composite is NOT the lever
(summing, a per-channel max and a per-cell winner-takes-all all give the
heart the same 1.74%; the two-pass version was measured and not kept), and
neither is the trail length (shortening it RAISES the share). The cause is
`self.trail` being a channel-wise MAX over time, so a cell holding the
shape's hue and a passing burst's hue from a neighbouring frame has every
channel high whatever this frame did. **Any effect here that leaves
something STANDING STILL over a show that keeps drawing through it will meet
the same wall** — the lever is the effect's trailing, which is its look, and
so the Admiral's call rather than a build row's. **His ruling, 2026-11-17:
option A, ship as built, his to judge by eye** — no trail rework, this
stays as measured in the W3 room deploy.

#### W4.3 (2026-11-17) — the dark canvas, 50% more sparks, a 2.0 s form

His room verdict, verbatim: *"Fireworks is too cluttered to visually
identiy the shape. Let's have it plan to make sure no fireworks fire right
before, or concurrently, so that it is on a mostly dark canvass. Also,
increase the amount of blobs by 50% so it is more clearly visible, and have
it hold 50% longer."* (The hold is the ROOM's — W4.2 tells a longer
`word_shape_hold_s` — and this row only asserts the hang follows it.)
`.claude/skills/fireworks-effect/SKILL.md`'s own W4.3 section is the full
record; what belongs HERE, because it is about this contract rather than
that effect:

- **The second declared minimum form.**
  `WORD_SHAPE_FORM_MIN_S["fireworks"] = 2.0`, applied at plan time with the
  showing scene's effects and again at fire time — the Fish's own
  mechanism, for a different reason: the floor is HOW EARLY THE WRITE
  ARRIVES, and that is all a hush needs. **There is deliberately no seventh
  told key**: a "quiet" key would reopen the W0.3 told-key contract for one
  effect, and the form already means exactly "how long before the word the
  effect is told".
- **So a colour kind pooled in a Fireworks Words band lands 2.0 s early
  too**, exactly as it already does on Fish. The band fires atomically;
  that is a property of the band, not of the effect.
- **The release follows the form**, so flooring the form at 2.0 s makes the
  room's release 3.0 s (1.5 ×) — the shape stands much longer than W1.2
  measured, and neither the row nor the effect chose that. The lever is the
  room's `word_shape_release_ratio`.
- **A clarity bar that is a bare ">= LIT" share is not a bar once the room
  draws through the shape** — and this row is the proof of it: W1.2's
  coverage read 99-100% over a live show while his own eye called the panel
  too cluttered to read the shape on. W4.3 adds the Fish `band_contrast`
  pattern (the band's own luminance against the rest of the panel,
  6.0-11.5× measured against a bar of 3.0) and a luminance-graded ASCII at
  the word and at mid-hold. **Any wave-1 bar still read as a bare lit share
  should expect the same.**
- **A "nothing jumps" bar expressed as a RATIO of the lit count cannot
  survive an effect that deliberately empties its own panel.** W4.3 reads
  it on the panel's own MEAN LIGHT instead, against the effect's own untold
  worst over the same span, and prints W1.2's form of the number beside it
  rather than dropping it.

### Orbits V2 / `orbits` (row W1.3, 2026-11-16; row W4.4, 2026-11-17) — few trace it, many become it, FAST

`.claude/skills/orbits-effect/SKILL.md`'s "WORD SHAPES" section;
`fx/effects/orbits.py`'s WORD SHAPES block comment; evidence
`scripts/check_orbits_word_shape.py`, proofs
`tests/test_orbits_word_shape.py`. **Four** registered params —
`word_shape_size` (0.62), `word_shape_few` (3), `word_shape_wobble`
(0.15) and, since row W4.4, `word_shape_speed_x` (**4.0**); no
`WORD_SHAPE_FORM_MIN_S` entry. The 2-D Matrix effect only:
**`orbits1d` knows no shapes**, and a strip has no outline to draw one on.

TWO MODES, LATCHED AT THE EDGE from the live blob count (`<=
word_shape_few` is FEW) and held for the whole shape — his scene drives
`particle_count` 1-8 by Energy, so without the latch a rising Energy would
flip three blobs tracing one heart into eight beads on it mid-word. His
P1 A: with FEW the TETHER RING scales by `(1 - m)` so the tethers gather to
the centre and the blobs trace ONE shape, each walking the outline BY ARC
LENGTH at its own orbit rate from its own EVEN SLOT; with MANY each slot's
tether blends to the outline at `ring_phase + k/n`, so the beads circulate
at the ring's own speed, orbits shrunk to `word_shape_wobble`. Both are
POSITION blends on the envelope's smoothstep — Orbits is position-driven,
so continuity is a property of the blend (the velocity graft's own reason).

Measured at the hold on the real mask at SIZE 0.62 — W1.3's own numbers,
at its own vacuous 20/255 threshold and before row W4.4's speed, kept here
for the record (`.claude/skills/orbits-effect/SKILL.md`'s ROW W4.4 section
carries the contrast table that replaced them): outline lit **74-93%**
with FEW (bar 60%) and **77-88%** with MANY (bar 75%), 100% by the hold's
END; every blob's centre (FEW) or tether (MANY) within **0.02 cell
pitches** of the outline; **+0.00 to +0.33 ms** p50 (bar 1 ms); white 0 of
976 cells except 1 on many-diamond at Energy 0.8. Three things read
honestly rather than moved, all printed by the check script:

- **the bar is asserted AT THE HOLD, not at the word** — at the word the
  shape has only just completed, so the trail behind each blob is still the
  forming sweep: measured 29-79%. No blob-based effect can light 60% of an
  outline the instant it arrives on it.
- **the 8%-per-frame jump bar is not a property this effect has even
  untold**: at his `trail_decay` 0.15 the comet smear loses 11% of its
  brightness every frame, so cells near the lit threshold wink out in
  blocks — 13-20% frame to frame on the untold control. The bar asserted is
  acceptance 3's own wording for this effect, "the effect's own ordinary
  maximum".
- **the heading change at the hold's EDGES is not the blend's**, so it is
  not what is barred there: the envelope's largest one-frame move over the
  whole shape is asserted against the steepest its own smoothstep can be
  (1.5 / its duration), and the most the blend could be moving a blob at an
  edge against the ordinary maximum. A hard turn in those frames is the
  OUTLINE (a heart's cleft turns 3.11 rad) or Orbits' own jog kick, which
  reverses a blob at loud Energy told or not — the untold control reaches
  3.10 of the 3.14 rad a heading change can be.

**ROW W4.4 (2026-11-17) — HIS VERDICT, AND THE THREE THINGS EVERY LATER ROW
SHOULD READ BEFORE REPEATING THEM.** His words after the W3 room deploy:
*"I can tell the fish and orbits are trying to do something, but it's not
clear enough. They need to increase speed so they can pass the outline fast
enough that their trail stays and it clearly forms the shape."* The row gave
this effect one new registered param, `word_shape_speed_x` (4.0), applied as
`1 + (x - 1) * m` to FEW's `omega` and MANY's `ring_phase` rate — ramped by
the envelope, so the acceleration is continuous and the speed is back to
today's by the release's end — and raised `WORD_SHAPE_TRAIL_S` 0.9 -> 1.8.
Three findings that are about THIS CONTRACT rather than that effect:

1. **A "LIT" BAR AT 20/255 IS VACUOUS FOR A TRAIL, AND W1.3 SHIPPED ONE.**
   Re-measured, its 74-93% sat beside a share of the SAME band over half of
   full of 1-25% — which is the faint, broken line he saw. The Fish review
   had already learned this (`band_contrast`) and nothing carried it back.
   **W4.3 reached the same conclusion independently on Fireworks in the
   same wave** (its own bullet above: a bare ">= LIT" share read 99-100%
   while his eye called the panel unreadable) — two rows, two effects, one
   lesson, which is the strongest reason to treat it as a rule of this
   contract rather than a per-effect quirk. **Every "outline coverage"
   number in this skill is a fraction of the pinned band; grade it by
   LUMINANCE or it says nothing.**
2. **128/255 IS THE WRONG THRESHOLD FOR A ONE-PITCH BAND ON A BLOB EFFECT,
   and the arithmetic says so exactly.** The band is every real cell within
   ONE CELL PITCH of the outline, a pitch is two addressable columns, and
   Orbits' `_splat` weights a cell `1 - dist / (blob_size + 0.5)` — so at
   his `blob_size` 2.5 the band's OUTER cells cap at 0.33 x 0.775 x 255 =
   65 of 255 whatever the speed or the trail (an undecaying trail at speed 6
   ceilings at 46-83%). The bar asserted is the share over 64/255, as the
   Fish row's is; the 128 share is printed with its ceiling as an OPEN
   EXCEEDANCE. **Any later row owes the same sum before promising a
   brightness bar: the band's width against the effect's own kernel.**
3. **SPEED AND TRAIL ARE NOT INTERCHANGEABLE LEVERS, measured.** Over 16
   configurations x 24 (mode, count, shape, Energy) rows: the WORST row's
   band share is the SPEED's and almost not the trail's at all (43% at
   speed 3 and 60-61% at speed 4 at every trail from 0.9 to 5.0), while the
   trail moves the MEDIAN and the hold's END and saturates by 3.0. And the
   ADAPTIVE rule ("make the revisit gap a fraction of the half-life") was
   refused with numbers: its premise is that the gap binds, and the DEPOSIT
   does. His own estimate of 3.0 was not enough for the one-blob and
   four-bead rows; 6.0 costs band contrast.

Row W4.4 also moved this effect's HOLD-EDGE continuity bar, and **that is
the trap waiting for W4.6 (Fish)**: a 4x arc-length walk on an ANISOTROPIC
panel (a column is half a pitch, a row sqrt(3)/2) has a px speed that swings
nearly 2x round the outline and changes abruptly at every corner — a
STANDING shape makes one-frame speed changes up to 100 px/s, against an
untold quiet-Energy control's 98. Comparing a 4x outline walk with a 1x
circle is not a like-for-like test of "no sudden velocity shifts". What is
asserted at the hold's edges is the DECOMPOSITION (the blend's own bound
plus the multiplier's, `row_speed_bound`), with the plain bar kept where the
ramp really is moving — the form's start and the release's end.

THREE DEFECTS THE W1.3 ROW FOUND BY MEASURING, each one a trap for the next
effect: **SIZE must be divided by the effect's own space** (Orbits' `sx`/
`sy` carry `radius_scale`, so a heart at 0.62 came out at 1.12 of the panel
and spilled off three sides — coverage read 15%); **a walk along the
outline has to be anchored** or random spawn phases put every blob in one
third of it (58% against 85-99% on the unluckiest seed); and **a lingering
trail must blend its per-frame DECAY, not its half-life** (the decay is
hyperbolic in the half-life, so ramping the half-life collapsed it from
1.2% to 11% per frame over the last few release frames and dumped 23-28%
of the lit cells in one frame).

### Fish / `fish` (row W1.4, 2026-11-15) — a procession along the outline

His revision of the row, verbatim: *"Fish: similar to orbits ... they need
to smoothly accelerate and not have sudden velocity shifts"*, then *"the
fish didn't seem to be sufficiently making the outline. We may need to boost
the trail brightness and lower decay briefly to get it to show better. They
also may need to more tightly flow."* P2 A, approved: with FEW fish the
water keeps a trace of the loop while the fish swim it.

The fish turn onto the loop nose to tail, each dashing a little to get
there, circle it for the phrase and peel away. `.claude/skills/fish-effect`
(its WORD SHAPES section) is the binding statement; what matters HERE,
because it is about this contract rather than that effect:

- **Fish was the FIRST effect with a MINIMUM FORM, and since W4.3 it is
  one of two** (Fireworks declares 2.0 s as well, for a different reason —
  emptying its panel rather than swimming onto a line; STAR, Sauron, Orbits
  and the Black Hole all take the approved Energy-paced one). Its 2.0 s is
  why W0.3's "both floors ask the SHOWING scene's own effects" rule exists
  at all: a procession has to SWIM onto the outline, and the lead IS the
  form in practice, so asking globally would stretch every other scene's
  shape to 2.0 s. `fx.device_model.WORD_SHAPE_FORM_MIN_S["fish"] = 2.0` —
  in `device_model`, never a registered param, because the planner needs
  it before it has asked any effect anything.
- **The library views it reads** are `at(s)` and nothing else — no `polar`,
  no `sdf`, no `sdf_fast`. So it deliberately does NOT call `prime()`,
  which would build the ~200 ms `sdf_fast` grid it never looks at. An
  effect that only walks the outline should do the same.
- **SIZE is not the effect's own `sx`/`sy` here.** `word_shape_size` is a
  fraction of the PANEL's half-height in the -1..1 space this skill
  describes, but Fish's `sx`/`sy` carry `radius_scale` on top of that, so
  it converts (`_word_shape_size_n`, `word_shape_size / radius_scale`).
  Any effect whose normalized space is not the panel's own owes the same
  conversion — the drawn shape must still come out the panel's aspect.
- **The angle a shape's `at(s)` reports is the angle an effect's own
  normalized space reports**, as long as its two axis scales are equal (as
  Fish's are, both `radius_scale`), because a positive diagonal scaling
  preserves the cyclic order of rays. That is what lets the Fish map a
  fish's bearing to a place on the outline with `np.interp` and no panel
  geometry at all, and it is monotonic only because every shipped shape is
  star-shaped about its centre — which the library MEASURES.
- **The clarity bar's denominators are this skill's own counts.** Fish's
  check script imports `scripts/check_word_shapes.py`'s mask decode and its
  `measure()` outline mask rather than re-deriving either, so a changed
  outline moves both the pinned counts and the Fish's bar together.
- **What its bar cost, and the warning for any effect that FOLLOWS an
  outline rather than sampling it.** The shapes' corners are far sharper
  than a fish's own turn radius: at SIZE 0.62 the outline turns 249 degrees
  (the heart's cleft), 154 (a star's notch) and 114 (the diamond's tip)
  inside ONE turn radius of arc, and the depth a radius-R arc must leave at
  a corner of exterior angle theta is `R (1 / cos(theta / 2) - 1)` — a
  reversal past 180 degrees being bounded by the circle's own diameter
  instead. Fish answers it by tightening the turn ARC under a shape
  (`WS_TURN_X`, the pre-drop's own mechanism) and by reading both distance
  bars off the fish that law allows on the line. Budget for this before
  promising a distance bar.
- **"100% lit" on this effect is vacuous — ITS WAKE SATURATES AN
  "above-zero" SHARE** on the same frame untold, which is what the clarity
  bar was first read against (the squadron leader caught this, PR 532
  review). The bar is now the share of the band ABOVE A LIGHT THRESHOLD
  (64 and 128 of 255) plus the band-to-rest luminance ratio, each read
  beside the SAME SEED's frame UNTOLD — `band_contrast`. Measured (20
  seeds, his real mask, medians): on the word 0.4-1.4 cell pitches, at
  mid-hold 0.2-1.8 (worst bound on the word, median at mid-hold — the
  plan's own two statistics); band>64 told/untold 91-100%/4-25% against
  bars of 60% (few)/70% (many), ratio at least 2.5x and at least 1.4x the
  untold ratio on the same seed; many-star is MARGINAL (median 1.8-2.4
  depending on seed count, bound by a star notch's own 2.0-3.4-pitch
  geometry at this SIZE); untold byte-identical over both real-audio arcs.
- **THE WHITE TAIL IS AN OPEN EXCEEDANCE, not a pass — his 2026-11-17
  ruling, option A, ship as built, his to judge by eye.** The half-life
  ships as a (FEW 0.6 s, MANY 1.0 s) pair, chosen on the `band_contrast`
  metric (the plan's suggested 1.2-1.5 s bought 10-17 points of real light
  for 2.6-3.2 points MORE white with only 1.5 points of headroom). Across
  8 seeds the shaped worst is 23.9-33.8% against this effect's own worst
  busy frame today (26.0% few, 24.5% many) — five of six (mode, shape)
  rows exceed the plan's own bar in the tail, many-diamond over on the
  median too — because overlapping fish bodies sum two gradient hues the
  same way his 2026-10-26 wake report did (option A fixed the wake only).
  The root fix (narrowing the gradient span a procession draws from, one
  colour per drawn shape) changes his authored colour behaviour and so is
  his call, not a build row's; this is his explicit 2026-11-17 ruling to
  ship it as measured. Any effect that concentrates its own light onto the
  outline should expect the same trade.

### Sauron / `sauron` (row W1.5, 2026-11-15) — the shaped iris and pupil

His Q8 **C**: both at once. Sauron already draws itself from two signed
distance fields, so the shape is a blend of each with the shape's own —
the iris boundary with `shape_sdf(iris_r x word_shape_size)` and the slit
lens with `shape_sdf(that x word_shape_pupil)` — in the eye's own gazed,
foreshortened coordinates. The ring, the flames' root, the heat, the
radial colour bands and the white-hot rim all read those two fields, so
one blend bends the whole picture and every phase composes unchanged.

Three facts a later row should not re-derive:

- **`word_shape_size` is a MULTIPLIER of the iris radius here**, not the
  plan's fraction of the panel: the shape is the eye's own edge bent, so
  it lives in the eye's own frame (both axes divided by `s_min`, so it
  inherits the eye's 1.7:1 aspect, deliberately). With his `iris_size`
  0.62 the two coincide, which is why the bars are measured at SIZE 0.62.
- **`sdf_fast`'s far field needs clamping at these sizes.** Past its grid
  box the estimate steps down by 0.055 eye units — a whole rendered pixel,
  measured — and at a pupil's size that boundary is inside the panel.
  `sauron._shape_field` evaluates at the point where the ray leaves the
  box and adds the radial step back: exact inside, continuous across, one
  `sdf_fast` call, +0.2 to +0.7 ms for both fields together on a quiet
  host (and see that skill on measuring it on a busy one).
- **A small dark shape needs a bite.** A cell lands fully dark only once
  it is 0.4 x the anti-alias inside the edge; a pupil about five real
  cells across measured 50-73% fully dark because of it. Sauron draws the
  pupil shape that much fatter (`PUPIL_BITE_PX`) and reaches 100%.

Bars (plan §3.5): 85% of the shaped iris's area cells outside the pupil
lit, 80% of its outline cells ringed, 70% of the pupil's cells black —
**measured 100% / 100% / 100%** for all three shapes at Energy 0.2 and
0.8, at the word and mid-hold, gaze centred and at its four extremes
(`scripts/check_sauron_word_shape.py`). `.claude/skills/sauron-effect`
holds the rest, including what a drop arriving on a standing shape looks
like.

### STAR / `radial` (row W1.6, 2026-11-15) — the third divisor, spin to rest

`.claude/skills/radial-effect/SKILL.md`'s "WORD SHAPES" section;
`fx/effects/radial.py`'s WORD SHAPES block comment; evidence
`scripts/check_star_word_shape.py`, proofs `tests/test_star_word_shape.py`.
One registered param, `word_shape_size` (0.62); no
`WORD_SHAPE_FORM_MIN_S` entry (the approved Energy-paced 0.5-0.9 s form).

Star samples a strip at a SHAPED RADIUS, so the shape is a third angle
DIVISOR in the harmonic blend an `edges` change already used — read at the
SCREEN angle, so the polygon turns under it and the shape stands upright —
plus a soft CUT at `u = 1` without which the strip simply repeats outward
and the panel stays lit. The rotation governor scales the whole per-frame
advance by `1 - m`, so the turn is exactly zero through the hold and
resumes from the music on the release; the star wave is held by freezing
its phase; an Edge Morph arriving mid-shape is deferred to the release.

Measured: lit cells inside the shape **97.1-100%** (bar 95%), the outline
within **0.000 cells** of `SIZE x polar(theta)` on 360 angles (bar half a
cell), no white, **+0.22 ms** p50 (bar 1 ms). Two bars read honestly rather
than moved, both printed by the check script:

- **"90% of the area cells lit" is read against the cells the STRIP
  lights** (97.3-100%). Star has no light of its own — Melt's own lit share
  swings between about a third and three quarters, and a dark band of the
  strip is a dark band of the heart. The absolute figure (32-45%) tracks
  the strip's share and is reported.
- **the 8%-per-frame jump bar is arithmetically out of reach here**: STAR's
  rest state lights the whole panel and a shape is a fifth to a third of
  it, so a 0.5 s form has to cut the lit count 4.3x in 15 rendered frames
  at 30 fps. Measured with the strip frozen: 6.9-14.4% (60 fps) /
  9.4-25.4% (30 fps), against the effect's own UNTOLD worst of 18.2% /
  26.6%. The hold itself does not move at all.

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
  `tests/test_word_shapes.py` the library's;
  `tests/test_scenes_words_tab.py` + `scripts/check_scenes_words_tab.mjs`
  the Words tab's, the picker's and the two class lists';
  `scripts/render_words_tab.py` (+ `spectra/web/harness/wordstab.html`)
  drives the real tab and preview in a browser and measures that the
  "forms" span ends ON the word — shots in `docs/evidence/words-tab/`.
- The plan: https://claude.ai/artifact/FdeYJz4kXLt2QamYR8wSDB (section 2.1
  is the library; 2.3 and 2.4 are the keys and the timing; 2.3-2.5 are the
  engine contract).
