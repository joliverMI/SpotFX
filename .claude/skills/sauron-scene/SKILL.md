---
name: sauron-scene
description: >
  The "Sauron" SPECTRA scene — a copy of Eye V2 with Matrix `sauron`
  (Strips `blackhole1d`, Singles unchanged). NOT YET CREATED: its seed
  script scripts/seed_sauron_scene.py is written and gated on his live
  tuning session. Load before running or editing that script, or before
  editing the scene's bands/kinds once it exists.
---

# Sauron (scene)

Load `sauron-effect` first.

## Not seeded — the tuning gate stands

`scripts/seed_sauron_scene.py` (dry-run default, `--apply` backs up both
stores, uuid5 ids so a re-run upserts) is WRITTEN, NOT RUN. The order is
docs/ADDING_EFFECTS.md's: he tunes Sauron live on the crystal (set by hand,
no scene), his values go into the script's `MATRIX_TUNED` (and the
registry defaults), THEN the script runs. Do not run it before his word.

## What the copy is

Everything from the stored Eye V2 the moment it runs, verbatim — flare
kinds (including its Pulse kinds and their -92/-355 ms offsets: a copied
scene is not proof he authored it), bands, lanes, bindings, journey, dwell,
availability, accept list, the sequencer selector entry re-keyed. The only
differences: id/name, device ids, Matrix `eye -> sauron`, the static Matrix
params in `DROPPED_MATRIX_PARAMS` left out (iris_size/gaze_radius — the
plan's own defaults; pupil_size — a different meaning on Sauron; spin/
spin_audio — Sauron has none), `MATRIX_TUNED` layered on, and one new
"Sauron Surge" kind APPENDED and attached to NO band (he attaches it on the
lane rack). Eye V2 is disabled today, so the copy is born disabled; the dry
run says so. Raw-dict copy, byte-identity check on every other scene before
and after the write (seed_fish_scene.py's discipline).

## Executable proofs

`tests/test_seed_sauron_scene.py` (the copy's differences, dry run writes nothing,
`--apply` on a temp store leaves every other scene byte-identical, re-run
upserts, a source already carrying the kind is refused). A dry run against
a COPY of his live store was read before shipping (Matrix keeps
drift_speed/snap_threshold/snap_hold/flames bindings and flame_audio 2,
speed_audio, impulse_decay, x/y offsets).

## Words band — one `Word Shape` kind, full range (Word Shapes W2.5)

`scripts/add_word_shapes.py` is the one thing that turns Word Shapes on in
his room — and because this scene is NOT SEEDED YET (the tuning gate above),
the script reports it as absent and skips it rather than inventing it: run
it again, or with `--scene Sauron`, once the seed has landed. On this scene
it writes exactly two keys:

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

**UNDO, and why a re-run is not one.** Plan §7: the kind's power button
switches it off on this scene, detaching it from the band does the same,
and `--revert` removes both from all six. Each of the first two leaves data
the script did not write, so a re-run REFUSES rather than undoing his undo
— an existing `Word Shape` kind is left exactly as authored (a switched-off
one is never re-enabled) and a Words section that differs aborts with the
difference printed. Raw-dict patch, never `scene_store.save()`; dry-run by
default; `--apply` backs the store up to
`storage/spectra/backups/scenes-word-shapes-<stamp>.json` first and
re-reads the written file to verify nothing else moved.

**WHO RUNS IT, AND WHEN:** DJ, at W3, only after the W1 code is deployed
and `spectra.service` restarted (an older process cannot load a `word`
response class). The tuning gate (`docs/ADDING_EFFECTS.md`) puts his eye
before a shape is live in a song, and his first look is the Words preview,
which needs the kind declared. Proof: `tests/test_add_word_shapes.py`
(fixture store only — never live storage). The shape library, the told keys
and the engine contract are the `word-shapes` skill.
