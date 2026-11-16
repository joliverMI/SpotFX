---
name: fish-scene
description: >
  The "Fish" SPECTRA scene — Matrix `fish`, Strips `fireworks1d` (live data —
  diverged from the `orbits1d` the seed script still copies in; see the note
  below), Singles `power` (`pulse` once scripts/migrate_singles_to_pulse.py
  runs). Load before editing this scene's flare bands/kinds, especially the
  "Fish Swim Burst" flare kind. Load the fish-effect skill first for the
  underlying Matrix effect's kinematics, and the fireworks-effect skill for
  the strip's own charge/lull/drop.
---

# Fish (scene)

Load `fish-effect` first — this scene's motion invariants (the speed
dial, dispersal, the boundary brake, the trail-gain rule) all live there.

`scripts/seed_fish_scene.py` is this scene's own seed script (dry-run by
default, `--apply` backs up and writes SPECTRA's own stores) — it is a
WHOLESALE COPY of Orbits V2's bands/kinds/weightings/curves/labels (his
own instruction). `scripts/add_fish_swim_burst_flare.py` declares the
"Fish Swim Burst" flare kind (it spikes the effect param `swim_burst`) and
pools it into a pick-one "Shape" lane alongside this scene's existing
momentary shape flares (e.g. "Reverse Momentarily (500ms)"), refusing if a
"Shape" lane already exists on that band.

## The Strips entry is `fireworks1d`, not the seed script's own `orbits1d`

The seed script's own docstring states a DELIBERATE, STATED NON-COPY for
Strips: it copies every other device entry from Orbits V2 but leaves
Fish's Strips entry at `orbits1d` ("there is no `fish1d`... the strips
therefore run exactly what Orbits V2 runs on them"). The LIVE scene has
since diverged from that — a later hand edit moved this scene's Strips
entry onto `fireworks1d` (the strip-phase plan's own read of
`storage/spectra/scenes.json`, 2026-10-11). **Load `fireworks-effect`, not
`orbits-effect`, for this scene's Strips behaviour** (charge/lull/drop via
the shared strip phase layer, the rocket ember through the lull, the drop
tail). A re-run of `scripts/seed_fish_scene.py` upserts every device entry
from Orbits V2's CURRENT data (its own docstring: "a re-run upserts Fish,
and only Fish") — including Strips — so re-running it would silently put
`orbits1d` back and undo this divergence. Check which effect the live
scene actually runs on Strips (`GET /spectra/api/scenes`) before touching
either the seed script or this scene's Strips params.

## This scene's AUTHORED DATA (bands/kinds/weights, Matrix only) tracks Orbits V2 — its MOTION never does

A band/kind-authoring change made on Orbits V2 (a weighting rebalance, a
new flare kind, a colour-set change) is a candidate for porting to this
scene's own data too — check the orbits-v2-scene skill. The reverse is
never true for motion: Fish's kinematics are a from-scratch rebuild (real
turn radius, camera window, dispersal, thrust dial) and share nothing
with Orbits' code — never port a motion fix from Orbits onto Fish.

## "Fish Swim Burst" ships at `trigger_offset_ms = 0`, not the -100ms he
   first asked for — his own correction, not a bug

He asked for the burst to start 100ms early, then corrected himself: "no,
dont pull the band forward, just dont add the 100ms pre-fire". When he said
it, a negative offset on this ONE kind would have dragged every sibling
flare on the same band early. That is no longer true: PER-FLARE TRIGGER
MOMENT has shipped, so on a trigger-relocated fire a -100ms burst would
start early while every sibling at 0 still fires on the mark (bridge-
classified flares still fire the band atomically). It stays at 0 because
that is his ruling — see the fish-effect skill's note before changing it.

## "Big Fish" sits in the Shape lane TWICE — half the flares, by data

`scripts/add_fish_big_fish_flare.py` declares two identical `big_fish`
kinds, "Big Fish" and "Big Fish 2" (offset 0), and pools both into every
flare band's existing "Shape" lane with "Fish Swim Burst" and "Reverse
Momentarily (500ms)". His frequency words: "make it happen half the time",
clarified as "just generally weight it so it's about as frequent as the
other flares combined, don't build code to hit 50%". The engine's only
weighting is the even pick-one lane, and a lane's members are kind NAMES,
so the weight is the second copy: each flare picks one of four, a big fish
on half of them (as often as the other two combined), and the burst and the
reverse each drop from one in two to one in four. **The two copies differ
only in name — an edit to one (an offset, switching it off) belongs on
both**, or the frequency silently halves. The script refuses a band with no
Shape lane (alone it would fire every flare), a non-Fish scene, and a "Big
Fish"/"Big Fish 2" of another type. House Fish has no flare response, so
the script says there is nothing to do there. Its look is the effect's own
`big_fish_*` settings — see the fish-effect skill.

## The wall needs no scene data

Since 2026-10-06 the fish glance alongside the panel's real lit edge
instead of swimming past it (`wall_lookahead`/`wall_turn_strength`, both
the effect's own defaults — see the fish-effect skill for the mechanism).
This scene's `roam_scale` 0.75 still bounds the fish's MIDDLES; the wall
keeps their bodies on the crystal. Solo bursts are House Fish's, not this
scene's (default off here).

## Drops can switch INTO or OUT OF this scene (2026-10-08)

This scene is drop-switch-ready (its Matrix effect is in
`fx.device_model.CENTRE_BURST_EFFECTS`): once a scene has grown stale, a drop sequence
may hard-cut into this one ON the drop, with this scene's own drop firing
on the mark and adopting the outgoing pieces — or cut out of it the same
way. Nothing in this scene's data opts in or out; `spectra/services/
drop_switch.py` (and the drop-detection skill) is where the rule lives,
including the hand-off table row for this effect; a lull leading into a switch is told the effect coming next through the lull hand-off hook (keep 1 for now — Fireworks' 3 keepers are phase 3).

## Sonic reach

`set_flare_kind` takes `type="big_fish"` (the seeded kinds are "Big Fish"
AND "Big Fish 2" — edit both; they carry no params/gain/hold). Its
brightness/size/crossing times and its wake (`big_fish_ripple`,
`big_fish_ripple_size`) are entry params: `set_scene_entry_param` on scene "Fish", target
"Matrix".

`set_flare_kind` on the "Fish Swim Burst" kind accepts
`trigger_offset_ms`/`hold_ms`/`params`/`gain` with omit-means-keep
semantics. **It looks the kind up BY NAME: pass `name="Fish Swim Burst"`.
`swim_burst` is the effect param the kind targets — passing it as the name
creates a duplicate kind instead of editing this one.** Flare kinds are
already scene-console scope, so this is the ordinary rule applied, not an
exception; every other kind/scene setting follows it the same way.

The Strips entry's strip-phase tunables (`charge_fill` … `flare_punch_glow`,
`fx/effects/strip_phase.py`) are reachable the same way:
`set_scene_entry_param` on scene "Fish", target "Strips" — see the
fireworks-effect skill, since that is the effect actually running there.

## The drop Shockwave is OFF on this scene (2026-10-12)

His words: "Turn it off for fish to test it at first and leave it on
globally for drops over .7 energy." `SceneV2.drop_shock_enabled` is false on
this scene, set by `scripts/set_fish_drop_shock_off.py` (dry run default,
`--apply` at deploy, `--on` puts it back; one raw key, nothing else). The
Fish's own drop (the rush, its scaled burst) plays exactly as before — only
the crystal's Shockwave overlay is withheld, and since 2026-10-12 ("stip
shockwave, yes") the strip's (`fireworks1d`) own drop shockwave too (its
colour/activity burst still plays). The Fish takes no breath-hold before
its drop at all (the fish-effect skill), and the strip keeps its 12%
ember. Sonic flips it back with
`set_scene_setting` on scene "Fish", key `drop_shock_enabled`. The room's
own switch and 0.7 energy floor (`drop_shock_enabled`,
`drop_shock_min_energy`) govern every other scene. Help
`drop-shockwave-switches`.

## The tail drive is ON for this scene only (2026-10-26)

The plan he approved: "tail-driven swimming with beats as strong as today",
with the defaults "the pond rest is for the music Fish scene only". The
effect's own `tail_drive` default is 0 (the fish-effect skill's TAIL DRIVE
section), so House Fish swims exactly as before; `scripts/
set_fish_tail_drive.py` sets `tail_drive = 1.0` on THIS scene's Matrix
entry (`target: Matrix`, `effect_type: fish`) and nothing else — dry run
default, `--apply` at deploy (it backs the store up first), `--revert`
removes the param again. It is a raw single-param patch, refusing to guess
when the scene's name or its one Matrix fish entry is not what it expects
(`tests/test_fish_tail_drive.py`). A Fish scene already showing keeps its
old value until it next fires. Sonic reads and sets it per entry
(`get_scene_entry_params` / `set_scene_entry_param`, scene "Fish", target
"Matrix"), with `glide_drag` and `glide_below` beside it. Help
`fish-tail-drive`.

## The pond rest is ON for this scene only (2026-10-26)

The plan he approved: "a quiet pond rest with occasional darts", with the
defaults "the pond rest is for the music Fish scene only; 'quiet' means
the music's own level". The effect's own `quiet_rest` default is 0 (the
fish-effect skill's POND REST section): House Fish is the house look and
the house is usually quiet, so it would rest almost all the time.
`scripts/set_fish_pond_rest.py` sets `quiet_rest = 1.0` on THIS scene's
Matrix entry and nothing else, through the same entry finder, guards and
raw single-param patch as `set_fish_tail_drive.py` (its shared `run()`);
dry run default, `--apply` at deploy (backed up as
`scenes-pond-rest-<stamp>.json`), `--revert` removes it. The rest works
with the tail drive off too, but it was measured with both on, so run both
scripts (`tests/test_fish_pond_rest.py`). Sonic reaches it and its three
companions (`rest_calm_level`, `rest_full_level`, `dart_every_s`) per
entry. Help `fish-pond-rest`.

## Executable proofs

Shares the fish-effect skill's proof corpus in full
(`scripts/check_fish*.py`, `tests/test_fish*.py`) — no separate
scene-only check exists, since the scene's own authoring is a direct copy
of Orbits V2 and the motion is exhaustively covered at the effect level.

## Words band — one `Word Shape` kind, full range (Word Shapes W2.5)

`scripts/add_word_shapes.py` is the one thing that turns Word Shapes on in
his room — and Fish is the scene the plan gives a per-effect FORM FLOOR
(`fx.device_model.WORD_SHAPE_FORM_MIN_S`, 2.0 s, set by Fish's own wave-1
row), so once that lands a word here forms over that floor however fast the
Energy would otherwise pace it. On this scene it writes exactly two keys (plus, on a
legacy-format scene, the one load-preserving flag below):

- `flare_kinds` gains ONE entry, `{"name": "Word Shape", "type":
  "word_shape", ...}` — offset 0, no minimum intensity, enabled. The type
  carries no jump/params/gain/hold_ms of its own: the five timings are ROOM
  settings (`word_shape_form_slow_s` / `_form_fast_s` / `_hold_min_s` /
  `_hold_max_s` / `_release_ratio`, Sonic-tellable), Energy-paced per word,
  and the shape itself is the sung label's.
- `responses["word"]` is CREATED as ONE full-range band `[0.0, 1.0)`
  attaching that kind at ×1.0 in its own implicit lane (`kind_lanes`
  empty), every other field at the model's default.

**THE BAND IS THE SWITCH** (his Q6 A: shapes are on "for every song once a
scene's Words band has a Word Shape kind attached"). A scene with no Words
section is `no_class` and writes nothing. FULL RANGE because
`scene_response.words_band_draws` is asked at PLAN time whether the showing
scene's Words section covers THIS Energy with an enabled `word_shape` kind
— a band stopping short of 1.0 would silently hand the loudest words back
to the colour path. **No colour kind is pooled beside it**: his Q5 A allows
one and a Words band is an ordinary `ResponseSpec`, but he did not ask for
one and it is his to add from the Scenes page.

**ONE MORE WRITE ON A LEGACY SCENE, and it is load-preserving.** His
stored scenes are in the LEGACY format — no `flare_kinds` key at all, kinds
auto-named on load (`models/scene.py _migrate_flare_kinds`) — and THE
ABSENCE OF THAT KEY IS THE LEGACY FLAG: without it, a response class
carrying no explicit `reroll_dice` loads with the historical default TRUE
and gains a "Dice Re-roll" kind on every band; with it, that class loads
FALSE and the kind silently DETACHES. Declaring the Word Shape kind
introduces the key, so before doing it the script writes the explicit
legacy default (`reroll_dice: true`) into every spec that has none — the
loaded scene is then exactly what it was. Its `verify_diff` compares the
LOADED models (`SceneV2(**raw).model_dump()`, our kind and section
stripped) as well as the raw dicts, so this class of mistake cannot be
invisible to it again. `--revert` drops the now-empty `flare_kinds` key too
(restoring the legacy reading) but leaves that one explicit flag, which is
load-neutral: **the backup is the byte-exact restore.** Found by running
the script end to end on a real-shaped store — W2.5 review, 2026-11-16.

**UNDO, and why a re-run is not one.** Plan §7: the kind's power button
switches it off on this scene, detaching it from the band does the same,
and `--revert` removes both from all six. Each of the first two leaves data
the script did not write, so a re-run REFUSES rather than undoing his undo
— an existing `Word Shape` kind is left exactly as authored (a switched-off
one is never re-enabled) and a Words section that differs aborts with the
difference printed. Raw-dict patch, never `scene_store.save()`; dry-run by
default; `--apply` backs the store up to
`storage/spectra/backups/scenes-word-shapes-<stamp>.json` first and
re-reads the written file to verify nothing else moved. A run with nothing
to do writes nothing and takes NO backup, and a stamp already taken (the
stamp is seconds-resolution) takes the next free name — so the backup of
the original store can never be clobbered by a backup of a patched one.

**WHO RUNS IT, AND WHEN:** DJ, at W3, only after the W1 code is deployed
and `spectra.service` restarted (an older process cannot load a `word`
response class). The tuning gate (`docs/ADDING_EFFECTS.md`) puts his eye
before a shape is live in a song, and his first look is the Words preview,
which needs the kind declared. Proof: `tests/test_add_word_shapes.py`
(fixture store only — never live storage). The shape library, the told keys
and the engine contract are the `word-shapes` skill.
