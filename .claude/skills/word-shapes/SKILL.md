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

### Fireworks / `fireworks` (row W1.2, 2026-11-16) — the shaped payoff burst

`.claude/skills/fireworks-effect/SKILL.md`'s "WORD SHAPES" section;
`fx/effects/fireworks.py`'s WORD SHAPES block comment; evidence
`scripts/check_fireworks_word_shape.py` (`--ascii` draws it on the real
mask), proofs `tests/test_fireworks_word_shape.py`. Four registered params
(`word_shape_size` 0.62, `word_shape_outline_share` 0.70,
`word_shape_sparks_quiet` 60, `word_shape_sparks_loud` 100); no
`WORD_SHAPE_FORM_MIN_S` entry. **`fireworks1d` is deliberately NOT a
member** — there is nowhere to draw a shape on one line.

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
so the Admiral's call rather than a build row's.

### Orbits V2 / `orbits` (row W1.3, 2026-11-16) — few trace it, many become it

`.claude/skills/orbits-effect/SKILL.md`'s "WORD SHAPES" section;
`fx/effects/orbits.py`'s WORD SHAPES block comment; evidence
`scripts/check_orbits_word_shape.py`, proofs
`tests/test_orbits_word_shape.py`. Three registered params —
`word_shape_size` (0.62), `word_shape_few` (3) and `word_shape_wobble`
(0.15); no `WORD_SHAPE_FORM_MIN_S` entry. The 2-D Matrix effect only:
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

Measured at the hold on the real mask at SIZE 0.62: outline lit **74-93%**
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

THREE DEFECTS THIS ROW FOUND BY MEASURING, each one a trap for the next
effect: **SIZE must be divided by the effect's own space** (Orbits' `sx`/
`sy` carry `radius_scale`, so a heart at 0.62 came out at 1.12 of the panel
and spilled off three sides — coverage read 15%); **a walk along the
outline has to be anchored** or random spawn phases put every blob in one
third of it (58% against 85-99% on the unluckiest seed); and **a lingering
trail must blend its per-frame DECAY, not its half-life** (the decay is
hyperbolic in the half-life, so ramping the half-life collapsed it from
1.2% to 11% per frame over the last few release frames and dumped 23-28%
of the lit cells in one frame).

### Black Hole — the shaped horizon (W1.1, 2026-11-16)

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
