---
name: sauron-scene
description: >
  The "Sauron" SPECTRA scene — a copy of Eye V2 with Matrix `sauron`
  (Strips `blackhole1d`, Singles unchanged). Created `disabled: true` on
  2026-10-10 for his live tuning session, reached by Force Scene, out of
  automatic rotation; its Words band was written at the W3 Word Shapes
  deploy. Load before running or editing scripts/seed_sauron_scene.py, or
  before editing the scene's bands/kinds.
---

# Sauron (scene)

Load `sauron-effect` first.

## Created, disabled, for his tuning session

`scripts/seed_sauron_scene.py` (dry-run default, `--apply` backs up both
stores, uuid5 ids so a re-run upserts) was run — dry run then `--apply` —
on 2026-10-10, against the live checkout, backing up
`storage/spectra/backups/{scenes,sequencer}-pre-sauron-20261011T012820Z.json`
(`data/sauron-tuning-setup/report.md`). The scene exists: id
`4874012c-709b-511d-aad4-d3455532a1cd`, `disabled: true` (born that way
because live Eye V2 was disabled at the time the script ran), out of
`scene_sequencer`'s automatic candidate pool, reached for his tuning only
through an explicit Force Scene pin on `force_scene_scene_id` (set to this
id, `overrode_disabled: true` in the fire result — expected and correct).
Whether the scene is enabled in rotation TODAY is not recorded in this
repo — check the live API (`GET /spectra/api/scenes`, read-only) before
claiming either way; do not assume the disabled flag from this file or
from this scene's age.

His verdict on Sauron's shaped eye (Word Shapes row W1.5), 2026-11-22,
verbatim: "sauron looks good." The W3-list departure for his eye — the
shaped iris reading 1.5–1.65× taller than wide, the eye's own aspect — is
accepted; see the `sauron-effect` skill's word-shape note.

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
his room. It ran, `--apply`, at the W3 Word Shapes deploy, 2026-11-17
(`data/ws-w3-deploy/report.md`): Sauron's scene already existed by then
(seeded 2026-10-10, above), so the script found it and wrote its Words
band like the other five scenes — this write is unconditional on the
scene's own `disabled` flag, which it never touches. On this scene it
wrote exactly two keys:

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
