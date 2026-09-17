---
name: pacman-v2-scene
description: >
  The "Pacman V2" SPECTRA scene — Matrix `pacman`, Strips `orbits1d`
  (not a Pacman-specific strip effect), Singles `power`. Load before
  editing this scene's flare bands/kinds. Load the pacman-effect skill
  first for the underlying Matrix effect (ghost AI, the `reverse` =
  "frighten ghosts" meaning), and orbits-effect for its Strips entry.
---

# Pacman V2 (scene)

Load `pacman-effect` (Matrix) and `orbits-effect` (Strips — this scene's
Strips entry is `orbits1d`, shared with Squiggles V2/Dancers V2, not a
distinct Pacman strip effect) first.

`scripts/seed_pacman_scene.py` is the LEGACY seed script
this scene was originally authored with — a historical record, NOT a dry
run and NOT current ground truth. It POSTs straight to the retired
spot-effects `/api/events` world on `:8000` the moment it runs (the data
SPECTRA's scenes were later migrated FROM by
`scripts/seed_spectra_from_v2.py`); it never touches SPECTRA's own
`storage/spectra/scenes.json`. Do not run it to "check" anything. For what
this scene actually is today, read `GET /spectra/api/scenes` on the live
process — a scene's stored data (and a legacy seeder's) is not proof he
authored it (AGENTS.md).

## `reverse` on this scene's flare bands frightens the ghosts, it does not
   reverse motion

If a flare kind on this scene targets `reverse`, it is authored to trigger
the fright state (blue ghosts, fleeing) — do not read a "Reverse
Direction"-style kind name here the way it would read on Black Hole,
Orbits or Squiggles (each of which means something different again). See the pacman-effect skill's note in full before
editing or diagnosing any reverse-shaped flare on this scene.

## Sonic reach

Scene settings and flare kinds only via the scene console.

## Executable proofs

No dedicated scene-level check/test exists yet — a named gap. If a band/
kind-level behavioural fix lands on this scene, add a check and register
it under `scenes.pacman-v2-scene.files` in `EFFECT_SCENE_MAP.json`.
