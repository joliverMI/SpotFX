---
name: fish-scene
description: >
  The "Fish" SPECTRA scene — Matrix `fish`, Strips `orbits1d` (unchanged from
  the Orbits V2 data it was copied from), Singles `power` (`pulse` once
  scripts/migrate_singles_to_pulse.py runs). Load before editing this scene's
  flare bands/kinds, especially the "Fish Swim Burst" flare kind. Load the
  fish-effect skill first for the underlying Matrix effect's kinematics.
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

## "Big Fish" sits in the Shape lane — one flare in three, not one in two

`scripts/add_fish_big_fish_flare.py` declares the `big_fish` kind "Big
Fish" (offset 0) and pools it into every flare band's existing "Shape"
lane with "Fish Swim Burst" and "Reverse Momentarily (500ms)". His
frequency words: "make it happen half the time", clarified as "just
generally weight it so it's about as frequent as the other flares
combined, don't build code to hit 50%". The engine's only weighting is the
even pick-one lane, so it lands at ONE IN THREE (and the burst and the
reverse each drop from one in two to one in three); exact one in two would
need a per-member lane weight, which does not exist. The script refuses a
band with no Shape lane (alone it would fire every flare), a non-Fish
scene, and a "Big Fish" of another type. House Fish has no flare response,
so the script says there is nothing to do there. Its look is the effect's
own `big_fish_*` settings — see the fish-effect skill.

## The wall needs no scene data

Since 2026-10-06 the fish glance alongside the panel's real lit edge
instead of swimming past it (`wall_lookahead`/`wall_turn_strength`, both
the effect's own defaults — see the fish-effect skill for the mechanism).
This scene's `roam_scale` 0.75 still bounds the fish's MIDDLES; the wall
keeps their bodies on the crystal. Solo bursts are House Fish's, not this
scene's (default off here).

## Drops can switch INTO or OUT OF this scene (2026-10-08)

This scene is drop-switch-ready (its Matrix effect is in
`fx.device_model.CENTRE_BURST_EFFECTS`): once a scene has grown stale, a drop sequence
may hard-cut into this one ON the drop, with this scene's own drop firing
on the mark and adopting the outgoing pieces — or cut out of it the same
way. Nothing in this scene's data opts in or out; `spectra/services/
drop_switch.py` (and the drop-detection skill) is where the rule lives,
including the hand-off table row for this effect; a lull leading into a switch is told the effect coming next through the lull hand-off hook (keep 1 for now — Fireworks' 3 keepers are phase 3).

## Sonic reach

`set_flare_kind` takes `type="big_fish"` (name it "Big Fish" to edit the
seeded one; it carries no params/gain/hold). Its brightness/size/crossing
times are entry params: `set_scene_entry_param` on scene "Fish", target
"Matrix".

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
