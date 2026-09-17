---
name: fish-scene
description: >
  The "Fish" SPECTRA scene — Matrix `fish`, Strips `orbits1d` (unchanged
  from the Orbits V2 data it was copied from), Singles `power`. Load
  before editing this scene's flare bands/kinds, especially the
  swim_burst flare kind. Load the fish-effect skill first for the
  underlying Matrix effect's kinematics.
---

# Fish (scene)

Load `fish-effect` first — this scene's motion invariants (the speed
dial, dispersal, the boundary brake, the trail-gain rule) all live there.

`scripts/seed_fish_scene.py` is this scene's own seed script — it is a
WHOLESALE COPY of Orbits V2's bands/kinds/weightings/curves/labels (his
own instruction). `scripts/add_fish_swim_burst_flare.py` declares AND
pools the `swim_burst` flare kind into a pick-one "Shape" lane alongside
this scene's existing momentary shape flares (e.g. Reverse), refusing if a
"Shape" lane already exists on that band.

## This scene's AUTHORED DATA tracks Orbits V2 — its MOTION never does

A band/kind-authoring change made on Orbits V2 (a weighting rebalance, a
new flare kind, a colour-set change) is a candidate for porting to this
scene's own data too — check the orbits-v2-scene skill. The reverse is
never true for motion: Fish's kinematics are a from-scratch rebuild (real
turn radius, camera window, dispersal, thrust dial) and share nothing
with Orbits' code — never port a motion fix from Orbits onto Fish.

## `swim_burst` ships at `trigger_offset_ms = 0`, not the -100ms he first
   asked for — his own correction, not a bug

He asked for the burst to start 100ms early, then corrected himself: "no,
dont pull the band forward, just dont add the 100ms pre-fire" — because a
band's relocation is the MIN over every attached kind's offset, so a
negative offset on this ONE kind would drag every sibling flare on the
same band early too. See the fish-effect skill's note for the deferred
fix path (per-kind independent lead) before adding a negative offset here.

## Sonic reach

`set_flare_kind` on `swim_burst` accepts `trigger_offset_ms`/`hold_ms`/
`params`/`gain` with omit-means-keep semantics — this is the one
Sonic-editable control on this scene beyond the usual scene-console
scope. Every other flare kind/scene setting follows the ordinary rule.

## Executable proofs

Shares the fish-effect skill's proof corpus in full
(`scripts/check_fish*.py`, `tests/test_fish*.py`) — no separate
scene-only check exists, since the scene's own authoring is a direct copy
of Orbits V2 and the motion is exhaustively covered at the effect level.
