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
