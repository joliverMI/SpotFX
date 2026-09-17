---
name: orbits-v2-scene
description: >
  The "Orbits V2" SPECTRA scene — Matrix `orbits`, Strips `orbits1d`,
  Singles `power`. Load before editing this scene's flare bands/kinds,
  colour behaviour, or drop-ejecta tuning. Load the orbits-effect skill
  first for the underlying effect's own params/invariants. This is also
  the scene the Fish scene was COPIED FROM wholesale — a fix authored here
  may need the equivalent applied to Fish's data too (never its code,
  which is unrelated).
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
authored it (AGENTS.md).

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

## Sonic reach

Scene settings and flare kinds only via the scene console — never the
device entries.

## Executable proofs

Shares the orbits-effect skill's proof corpus
(`scripts/check_orbits_drop_burst_and_persistence.py`,
`scripts/smoke_orbits_params.py`, `tests/test_orbits_drop_persistence.py`).
Named gap: no check proves this scene's own band attachments end to end.
