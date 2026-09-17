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

`scripts/seed_fireworks_scene.py` is the LEGACY seed script
this scene was originally authored with — a historical record, NOT a dry
run and NOT current ground truth. It POSTs straight to the retired
spot-effects `/api/events` world on `:8000` the moment it runs (the data
SPECTRA's scenes were later migrated FROM by
`scripts/seed_spectra_from_v2.py`); it never touches SPECTRA's own
`storage/spectra/scenes.json`. Do not run it to "check" anything. For what
this scene actually is today, read `GET /spectra/api/scenes` on the live
process — a scene's stored data (and a legacy seeder's) is not proof he
authored it (AGENTS.md).
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
per-effect skill and AGENTS.md's "per-scene colour-set PREFERENCE" section
for the additive-match rule (a declared preference matches its own mode
plus every UNMARKED set, never leaves a scene with zero eligible sets).

## Sonic reach

Scene settings and flare kinds only via the scene console.

## Executable proofs

Shares the fireworks-effect skill's proof corpus
(`scripts/check_fireworks_drop_tail.py`, `tests/test_fireworks_drop_tail.py`,
`tests/test_firework_burst.py`) — no scene-specific check exists beyond
this scene's own migration, `scripts/add_fireworks_burst_flare.py`. Named gap: a scene-level check proving THIS
scene's actual band attachments (not just the effect's generic drop-tail
behaviour) doesn't exist yet.
