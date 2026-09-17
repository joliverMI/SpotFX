---
name: eye-v2-scene
description: >
  The "Eye V2" SPECTRA scene — Matrix `eye`, Strips `blackhole1d`
  (shares the Black Hole strip effect, not a distinct one), Singles
  `power`. Load before editing this scene's flare bands/kinds or blink/
  snap thresholds. Load the eye-effect skill first for the underlying
  Matrix effect, and blackhole-effect for what its Strips entry runs.
---

# Eye V2 (scene)

Load `eye-effect` (Matrix) and `blackhole-effect` (Strips — this scene's
Strips entry is `blackhole1d`, shared with the Black Hole scenes' strip
render, not a distinct Eye strip effect) first.

`scripts/seed_eye_scene.py` is the LEGACY seed script
this scene was originally authored with — a historical record, NOT a dry
run and NOT current ground truth. It POSTs straight to the retired
spot-effects `/api/events` world on `:8000` the moment it runs (the data
SPECTRA's scenes were later migrated FROM by
`scripts/seed_spectra_from_v2.py`); it never touches SPECTRA's own
`storage/spectra/scenes.json`. Do not run it to "check" anything. For what
this scene actually is today, read `GET /spectra/api/scenes` on the live
process — a scene's stored data (and a legacy seeder's) is not proof he
authored it (AGENTS.md).

## `snap_threshold`'s saturating-`>=` defect is UNFIXED here — a reported,
   not-yet-actioned gap

See the eye-effect skill's note in full. A "the eye snaps even at
`snap_threshold=1.0`" report on this scene is the known, unfixed defect,
not a new one — don't re-diagnose it from scratch.

## Sonic reach

Scene settings and flare kinds only via the scene console.

## Executable proofs

No dedicated scene-level check/test exists yet — a named gap. The nearest
proofs are the eye-effect skill's shared-machinery references
(`tests/test_lead_time_alignment.py`,
`tests/test_blackhole_orphan_drop_none_crash.py`). If a band/kind-level
behavioural fix lands on this scene, add a check here and register it
under `scenes.eye-v2-scene.files` in `EFFECT_SCENE_MAP.json`.
