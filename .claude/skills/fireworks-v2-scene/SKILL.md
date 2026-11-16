---
name: fireworks-v2-scene
description: >
  The "Fireworks V2" SPECTRA scene — Matrix `fireworks`, Strips `fireworks1d`,
  Singles `power` (`pulse` once scripts/migrate_singles_to_pulse.py runs).
  Load before editing this scene's flare bands/kinds, drop-tail behaviour, or
  the `firework_burst` flare kind. Load the fireworks-effect skill first for
  the underlying effects.
---

# Fireworks V2 (scene)

Load `fireworks-effect` first for the effect module itself.

`scripts/seed_fireworks_scene.py` is the LEGACY seed script
this scene was originally authored with — a historical record, NOT a dry
run and NOT current ground truth. It POSTs straight to the retired
spot-effects `/api/events` world on `:8000` the moment it runs (the data
SPECTRA's scenes were later migrated FROM by
`scripts/seed_spectra_from_v2.py`); it never touches SPECTRA's own
`storage/spectra/scenes.json`. Do not run it to "check" anything. For what
this scene actually is today, read `GET /spectra/api/scenes` on the live
process — a scene's stored data (and a legacy seeder's) is not proof he
authored it (AGENTS.md's safety rule; full history in docs/agents/scenes-and-flares.md).
`scripts/add_fireworks_burst_flare.py` (a genuine SPECTRA-store migration,
dry-run by default) declares AND
band-attaches the `firework_burst` flare kind on Fireworks V2 specifically
— run only AFTER the code deploys (it depends on
`fx.device_model.FIREWORK_BURST_EFFECTS` gating being live).

## Check `spawn_rate` live before assuming a launch-rate knob does anything

At `spawn_rate: 0` beat bursts are the ONLY ordinary launch source and
`CHARGE_SPAWN_X` is inert. The legacy seeder authored 0, but the live store
has held other values (0.5 on both entries, read 2026-09-16) — **verify
against `GET /spectra/api/scenes`, this drifts.** See the fireworks-effect
skill's note in full before promising any `spawn_rate`/`CHARGE_SPAWN_X`-
shaped fix will be visible.

## Colour-set preference

`scripts/set_scene_colorset_preference.py` set this scene to `"dark"`
colour-set preference alongside Black Hole V2/UI and Dancers V2 — see the
per-effect skill and docs/agents/sonic-and-colour.md's "per-scene colour-set PREFERENCE" section
for the additive-match rule (a declared preference matches its own mode
plus every UNMARKED set, never leaves a scene with zero eligible sets).

## Drops can switch INTO or OUT OF this scene (2026-10-08)

This scene is drop-switch-ready (its Matrix effect is in
`fx.device_model.DROP_FIREWORKS_EFFECTS`): once a scene has grown stale, a drop sequence
may hard-cut into this one ON the drop, with this scene's own drop firing
on the mark and adopting the outgoing pieces — or cut out of it the same
way. Nothing in this scene's data opts in or out; `spectra/services/
drop_switch.py` (and the drop-detection skill) is where the rule lives,
including the hand-off table row for this effect. Its pairs are the
phase-3 FIREWORKS MELDS: a stale Fish/Orbits drop cuts INTO this scene
with three keepers that each burst where they stand; leaving it, this
scene plays its OWN drop first, then cuts to the Black Hole a second later
(swallowed) or to Fish/Orbits/Squiggles/STAR on the next big analysed
flare (or its deadline), the flare landing on the new scene. Help topic
`fireworks-melds`.

## Sonic reach

Scene settings and flare kinds only via the scene console.

## Executable proofs

Shares the fireworks-effect skill's proof corpus
(`scripts/check_fireworks_drop_tail.py`, `tests/test_fireworks_drop_tail.py`,
`tests/test_firework_burst.py`) — no scene-specific check exists beyond
this scene's own migration, `scripts/add_fireworks_burst_flare.py`. Named gap: a scene-level check proving THIS
scene's actual band attachments (not just the effect's generic drop-tail
behaviour) doesn't exist yet.

## Words band — one `Word Shape` kind, full range (Word Shapes W2.5)

`scripts/add_word_shapes.py` is the one thing that turns Word Shapes on in
his room. On this scene it writes exactly two keys (plus, on a
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
