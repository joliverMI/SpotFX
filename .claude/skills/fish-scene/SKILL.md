---
name: fish-scene
description: >
  The "Fish" SPECTRA scene — Matrix `fish`, Strips `orbits1d` (unchanged
  from the Orbits V2 data it was copied from), Singles `power`. Load
  before editing this scene's flare bands/kinds, especially the
  "Fish Swim Burst" flare kind. Load the fish-effect skill first for the
  underlying Matrix effect's kinematics.
---

# Fish (scene)

Load `fish-effect` first — this scene's motion invariants (the speed
dial, dispersal, the boundary brake, the trail-gain rule) all live there.

`scripts/seed_fish_scene.py` is this scene's own seed script (dry-run by
default, `--apply` backs up and writes SPECTRA's own stores) — it is a
WHOLESALE COPY of Orbits V2's bands/kinds/weightings/curves/labels (his
own instruction). `scripts/add_fish_swim_burst_flare.py` declares the
"Fish Swim Burst" flare kind (it spikes the effect param `swim_burst`) and
pools it into a pick-one "Shape" lane alongside this scene's existing
momentary shape flares (e.g. "Reverse Momentarily (500ms)"), refusing if a
"Shape" lane already exists on that band.

## This scene's AUTHORED DATA tracks Orbits V2 — its MOTION never does

A band/kind-authoring change made on Orbits V2 (a weighting rebalance, a
new flare kind, a colour-set change) is a candidate for porting to this
scene's own data too — check the orbits-v2-scene skill. The reverse is
never true for motion: Fish's kinematics are a from-scratch rebuild (real
turn radius, camera window, dispersal, thrust dial) and share nothing
with Orbits' code — never port a motion fix from Orbits onto Fish.

## "Fish Swim Burst" ships at `trigger_offset_ms = 0`, not the -100ms he
   first asked for — his own correction, not a bug

He asked for the burst to start 100ms early, then corrected himself: "no,
dont pull the band forward, just dont add the 100ms pre-fire". When he said
it, a negative offset on this ONE kind would have dragged every sibling
flare on the same band early. That is no longer true: PER-FLARE TRIGGER
MOMENT has shipped, so on a trigger-relocated fire a -100ms burst would
start early while every sibling at 0 still fires on the mark (bridge-
classified flares still fire the band atomically). It stays at 0 because
that is his ruling — see the fish-effect skill's note before changing it.

## Sonic reach

`set_flare_kind` on the "Fish Swim Burst" kind accepts
`trigger_offset_ms`/`hold_ms`/`params`/`gain` with omit-means-keep
semantics. **It looks the kind up BY NAME: pass `name="Fish Swim Burst"`.
`swim_burst` is the effect param the kind targets — passing it as the name
creates a duplicate kind instead of editing this one.** Flare kinds are
already scene-console scope, so this is the ordinary rule applied, not an
exception; every other kind/scene setting follows it the same way.

## Executable proofs

Shares the fish-effect skill's proof corpus in full
(`scripts/check_fish*.py`, `tests/test_fish*.py`) — no separate
scene-only check exists, since the scene's own authoring is a direct copy
of Orbits V2 and the motion is exhaustively covered at the effect level.
