---
name: fireworks-v2-scene
description: >
  The "Fireworks V2" SPECTRA scene — Matrix `fireworks`, Strips
  `fireworks1d`, Singles `power`. Load before editing this scene's flare
  bands/kinds, drop-tail behaviour, or the `firework_burst` flare kind.
  Load the fireworks-effect skill first for the underlying effects.
---

# Fireworks V2 (scene)

Load `fireworks-effect` first for the effect module itself.

`scripts/seed_fireworks_scene.py` is this scene's own seed script (dry-run
default). `scripts/add_fireworks_burst_flare.py` declares AND
band-attaches the `firework_burst` flare kind on Fireworks V2 specifically
— run only AFTER the code deploys (it depends on
`fx.device_model.FIREWORK_BURST_EFFECTS` gating being live).

## His real scene runs `spawn_rate: 0` on BOTH effects — check this before
   assuming a launch-rate knob does anything

Beat bursts are the ONLY ordinary launch source on his live scene. See
the fireworks-effect skill's note in full before promising any
`spawn_rate`/`CHARGE_SPAWN_X`-shaped fix will be visible.

## Colour-set preference

`scripts/set_scene_colorset_preference.py` set this scene to `"dark"`
colour-set preference alongside Black Hole V2/UI and Dancers V2 — see the
per-effect skill and AGENTS.md's "per-scene colour-set PREFERENCE" section
for the additive-match rule (a declared preference matches its own mode
plus every UNMARKED set, never leaves a scene with zero eligible sets).

## Sonic reach

Scene settings and flare kinds only via the scene console.

## Executable proofs

Shares the fireworks-effect skill's proof corpus
(`scripts/check_fireworks_drop_tail.py`, `tests/test_fireworks_drop_tail.py`,
`tests/test_firework_burst.py`) — no scene-specific check exists beyond
the migration script itself. Named gap: a scene-level check proving THIS
scene's actual band attachments (not just the effect's generic drop-tail
behaviour) doesn't exist yet.
