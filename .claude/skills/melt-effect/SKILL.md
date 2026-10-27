---
name: melt-effect
description: >
  fx/effects/melt.py (Strips, `Atmospheric` category) — a plain HSV melt
  effect, currently the STAR scene's Strips entry. Load before touching
  STAR's strip behaviour or before re-running the "always melt" migration
  — a superseded seeder for this same virtual still exists and must NOT
  be re-run.
---

# Melt

A simple, mostly stock LedFX `Atmospheric` effect (`speed`, `reactivity` —
two params, no Matrix/crystal-mapper geometry involved; this is a Strips
effect). The invariant worth knowing lives OUTSIDE the effect module
itself, in how STAR's strips got wired to it:

## Two seeders exist for STAR's Strips — only ONE is current, and running
   the wrong one silently reverts his ruling

`scripts/seed_star_strips.py --apply` originally set up STAR's Strips with
an intensity-stepped `effect_steps` binding: base `melt` below ⚡0.7 (the
fallback, always melt) and a `power` STEP at/above ⚡0.7 (`bass_decay_rate
0.6` — the `star-fold-entry-growth` decision). **That seeder is now SUPERSEDED and must NOT be re-run**: his
2026-08-25 ruling "always do melt" removed STAR's Strips power step via
`scripts/star_strips_always_melt.py`, and re-running the OLD seeder would
silently put the power step back. Melt was never replaced — only the
power overlay on top of it was removed. The underlying intensity-stepped-effect
mechanism itself is unchanged and still used elsewhere — only STAR's own
Strips entry was pinned to melt unconditionally. Before touching STAR's
Strips config, check which of the two scripts is the one to run.

## Charge, lull and drop come from the shared STRIP PHASE LAYER (2026-10-11)

`fx/effects/strip_phase.py` (its module docstring is the binding statement)
is mixed in FIRST in this effect's bases and `fx.device_model.
STRIP_PHASE_EFFECTS` lists it, so SpotFX now tells it every charge, lull
and drop (plus the lull's dark point, the drop's size and the room's
`strip_phase_strength`). The layer works in the OUTPUT STAGE — a hue-kept
colour gain, a set-colour fill under the strip, the drop's set-colour
shockwave, the lull's fade to black at the room's shared dark point, the
flare punch, and a white guard on charge and drop — so the effect's own
render is untouched; off-phase (and at strength 0) its frames are byte for
byte what they were. Its phases are HELD BACK under a house mode
(`scene_response.HOUSE_HELD_PHASE_EFFECTS`).

Melt's one touch: its clock step is multiplied by `self._sp_activity`
(the layer's ACTIVITY — up to `charge_activity` x faster on a build,
`drop_activity` x on a drop, `lull_activity` x as a lull relaxes; left
untouched at 1). STAR, House Star and House Fish run Melt on the strips —
the house scenes never see a phase while a house mode rests.

**On the strip Star reads (`radial-dummy`), Melt skips its LULL** while a
Radial is drawing from it (2026-10-14, his "the strip used by the radial
effect shouldn't do the lull"): the layer tells it "none" for the lull and
only eases what the charge left back to neutral — no fade, no lull
activity — so Star's own lull owns the crystal's dark. Charge and drop are
unchanged. strip_phase's THE STRIP STAR READS; `tests/
test_star_strip_lull.py`.

## THE PRE-DROP — the strip twinkles (2026-10-27)

Predrop plan step 9 (`fx/VENDOR.md` #90; the drop-detection skill for the
engine). Every strip phase member is a `fx.device_model.PRE_DROP_EFFECTS`
member, and this one plays the shared layer's look, `twinkle` (its
`pre_drop_looks` block in `config/effect_params.json`, for both kinds) —
drawn once in `fx/effects/strip_phase.py`'s THE PRE-DROP, nothing in this
module. Told a pre-drop, the lull is measured to it (its dark point falls
before the pre-drop) and runs exactly as this strip's own lull does; from
the pre-drop to the drop a few pixels light in the set's colours at the
effect's OWN brightness (his "make the twinkles max brightness match the
effect brightness (don't dim, just use twinkle to "dim")") and fade over
about a tenth of a second, born a little faster toward the drop. They are
painted after the lull's fade, brighter-wins (never two hues mixed whiter).
Untold is today's frame for frame against this strip AND the layer before
step 9. Its light over the lull stays below today's at every measured gap.
Proofs: `tests/test_pre_drop_looks.py` (the step-9 section; rig
`tests/pre_drop_look_harness.py`'s `strip_run`/`load_pinned_strip`),
storyboards `strip_melt_*` in `docs/evidence/predrop-storyboards/`.

The strip Star reads skips its lull, so it never twinkles: Star draws
its own pre-drop outline. Melt's own blur, applied after the layer as to
everything it draws, softens a one-pixel twinkle's peak.

## Sonic reach

The layer's tunables (Charge colour fill/brightness/activity, Lull
activity/ember, Drop shockwave/brightness/activity and their settles, White
guard, Flare punch strength/hold/release/glow) are registered in
`config/effect_params.json`, so Sonic reaches them per scene entry through
`set_scene_entry_param`, and the room master through `set_setting
strip_phase_strength`. Help topic `strip-phases`.

## Executable proofs

The strip phase layer: `tests/test_strip_phase.py` (byte-identity, strength 0,
the cycle, no white, the shared dark point, the punch, the house hold) and
`scripts/check_strip_phase.py` (the measured cycle and the stage cost).

No dedicated `check_melt_*.py`/`test_melt_*.py` exists for Melt itself. The
"always do melt" migration and its test (`scripts/star_strips_always_melt.py`,
`tests/test_star_strips_always_melt.py`) prove STAR's scene data and belong
to the star-scene skill. History: AGENTS.md's "SPECTRA app" section, "always
do melt" ruling (search "star_strips_always_melt" in AGENTS.md for the full
quote and the superseded-seeder warning).
