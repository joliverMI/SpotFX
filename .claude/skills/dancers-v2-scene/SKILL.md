---
name: dancers-v2-scene
description: >
  The "Dancers V2" SPECTRA scene — Matrix `dancer`, Strips `orbits1d`
  (not a Dancer-specific strip effect), Singles `power`. Load before
  editing this scene's flare bands/kinds, GIF pose/style selection, or
  flame-burst thresholds. Load the dancer-effect skill first (and
  led-gif-assets for asset authoring specifically).
---

# Dancers V2 (scene)

Load `dancer-effect` first (and `led-gif-assets` for GIF pose/style
authoring specifically — that skill covers the tooling side, this one
covers the scene's own bands/kinds).

`scripts/seed_dancers_scene.py` is the LEGACY seed script
this scene was originally authored with — a historical record, NOT a dry
run and NOT current ground truth. It POSTs straight to the retired
spot-effects `/api/events` world on `:8000` the moment it runs (the data
SPECTRA's scenes were later migrated FROM by
`scripts/seed_spectra_from_v2.py`); it never touches SPECTRA's own
`storage/spectra/scenes.json`. Do not run it to "check" anything. For what
this scene actually is today, read `GET /spectra/api/scenes` on the live
process — a scene's stored data (and a legacy seeder's) is not proof he
authored it (AGENTS.md).

`scripts/seed_dancer_event.py` has NOTHING to do with this scene: it seeds
the old keybeat2d GIF "Dancer" event, a different legacy scene
(`seed_dancers_scene.py`'s own docstring: "NOT the old keybeat2d GIF
'Dancer' scene — that one stays").

## Its Strips entry is `orbits1d`, same as Squiggles V2 and Pacman V2

This scene has no Dancer-specific strip effect — check the orbits-effect
skill before assuming a Strips-side report is about the Dancer effect at
all.

## Colour-set preference

Set to `"dark"` by `scripts/set_scene_colorset_preference.py` alongside
Black Hole V2/UI and Fireworks V2 — see the additive-match rule in
AGENTS.md's "per-scene colour-set PREFERENCE" section before assuming a
preference change could ever leave this scene with zero eligible sets.

## The saturating-threshold flame defect is FIXED for this scene's beat-
   burst path, not for all four flame sources

`burst_threshold` (`dancer.py:1149`) is fixed; the flourish payoff burst
and the six `_impact_flames` stunt moments are ungated and no threshold
value silences them. See the dancer-effect skill's full note before
promising a flame-silencing fix will be complete.

## Sonic reach

Scene settings and flare kinds only via the scene console.

## Executable proofs

Shares the dancer-effect skill's proof corpus
(`scripts/check_dancer_flames_off.py`, `tests/test_dancer_flames_off.py`,
and the param-shape smoke test `scripts/smoke_dancer_params.py`). Named
gap: no check proves this scene's own band attachments end to end.
