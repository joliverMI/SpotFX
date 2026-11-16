---
name: orbits-v2-scene
description: >
  The "Orbits V2" SPECTRA scene — Matrix `orbits`, Strips `orbits1d`, Singles
  `power` (`pulse` once scripts/migrate_singles_to_pulse.py runs). Load before
  editing this scene's flare bands/kinds, colour behaviour, or drop-ejecta
  tuning. Load the orbits-effect skill first for the underlying effect's own
  params/invariants. This is also the scene the Fish scene was COPIED FROM
  wholesale — a fix authored here may need the equivalent applied to Fish's
  data too (never its code, which is unrelated).
---

# Orbits V2 (scene)

Load `orbits-effect` first for the effect module itself.

`scripts/seed_orbits_scene.py` is the LEGACY seed script
this scene was originally authored with — a historical record, NOT a dry
run and NOT current ground truth. It POSTs straight to the retired
spot-effects `/api/events` world on `:8000` the moment it runs (the data
SPECTRA's scenes were later migrated FROM by
`scripts/seed_spectra_from_v2.py`); it never touches SPECTRA's own
`storage/spectra/scenes.json`. Do not run it to "check" anything. For what
this scene actually is today, read `GET /spectra/api/scenes` on the live
process — a scene's stored data (and a legacy seeder's) is not proof he
authored it (AGENTS.md's safety rule; full history in docs/agents/scenes-and-flares.md).

It has already diverged from the live scene, which is exactly why it is not
ground truth: it sets its legacy Strips to `melt`, while the live SPECTRA
Orbits V2 runs `orbits1d` on Strips.

`scripts/seed_orbits_colorsets.py` is also not a dry run: it POSTs the
"Orbits" colour group and its "Orbit - <Color>" sets to the running
spot-effects `/api/color-sets` — the colour-set store SPECTRA reads — so
running it rewrites those cards in his live library.

## The Fish scene is a wholesale copy of this scene's data

`docs/SPECTRA_SPEC.md` §94 / `scripts/seed_fish_scene.py`: Fish's flare
kinds, bands, initial params, weightings and curves are a literal copy of
Orbits V2's own. **A band/kind-level authoring fix made here (e.g. a
weighting rebalance, a new flare kind) is a candidate for the equivalent
edit on Fish's own scene data** — check the `fish-scene` skill before
assuming a change here is Orbits-only. The reverse direction: Fish's
MOTION is completely different (see the fish-effect skill) — never port a
motion/kinematics fix from here onto Fish, only scene-authoring
(bands/kinds/weights) changes are shared.

## Drop-ejecta persistence tuning lives at the effect level

The "3 seconds" ejecta-lifetime tuning is a property of `particle_count`
on this scene's Matrix entry (see orbits-effect skill) — his real scene's
value and `radius_scale=1.8`/`horizon_scale=0.19` are the reference
config `scripts/check_orbits_drop_burst_and_persistence.py` measures
against; check that script's own docstring before assuming a different
`particle_count` value is safe to ship without re-measuring.

## Drops can switch INTO or OUT OF this scene (2026-10-08)

This scene is drop-switch-ready (its Matrix effect is in
`fx.device_model.CENTRE_BURST_EFFECTS`): once a scene has grown stale, a drop sequence
may hard-cut into this one ON the drop, with this scene's own drop firing
on the mark and adopting the outgoing pieces — or cut out of it the same
way. Nothing in this scene's data opts in or out; `spectra/services/
drop_switch.py` (and the drop-detection skill) is where the rule lives,
including the hand-off table row for this effect.

## Sonic reach

Scene settings and flare kinds only via the scene console — never the
device entries.

## Executable proofs

Shares the orbits-effect skill's proof corpus
(`scripts/check_orbits_drop_burst_and_persistence.py`,
`scripts/smoke_orbits_params.py`, `tests/test_orbits_drop_persistence.py`).
Named gap: no check proves this scene's own band attachments end to end.

## Words band — one `Word Shape` kind, full range (Word Shapes W2.5)

`scripts/add_word_shapes.py` is the one thing that turns Word Shapes on in
his room. On this scene it writes exactly two keys:

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
