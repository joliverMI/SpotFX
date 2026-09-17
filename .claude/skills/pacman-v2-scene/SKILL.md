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

`scripts/seed_pacman_scene.py` is this scene's own seed script.

## `reverse` on this scene's flare bands frightens the ghosts, it does not
   reverse motion

If a flare kind on this scene targets `reverse`, it is authored to trigger
the fright state (blue ghosts, fleeing) — do not read a "Reverse
Direction"-style kind name here the way it would read on Black Hole/
Orbits/Squiggles. See the pacman-effect skill's note in full before
editing or diagnosing any reverse-shaped flare on this scene.

## Sonic reach

Scene settings and flare kinds only via the scene console.

## Executable proofs

No dedicated scene-level check/test exists yet — a named gap. If a band/
kind-level behavioural fix lands on this scene, add a check and register
it under `scenes.pacman-v2-scene.files` in `EFFECT_SCENE_MAP.json`.
