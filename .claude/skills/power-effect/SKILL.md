---
name: power-effect
description: >
  fx/effects/power.py (`Classic` category, Strips/Singles) — the classic
  LedFX bass-percussive "power" effect, bound onto the Singles device —
  and only Singles — across EVERY one of his 10 live scenes. Load
  before touching `sparks_color` (an accent param) or before assuming a
  scene's stored sparks colour reflects what he actually tuned.
---

# Power

A near-stock LedFX `Classic` effect (`mirror`, `blur`, `sparks_color`,
`bass_decay_rate`, ...) — the Singles entry of all 10 live scenes, and no
scene's Strips entry today (STAR's Strips `power` step was removed by the
"always do melt" ruling), so a change here has the widest blast radius of
any effect on this list. Check `EFFECT_SCENE_MAP.json`'s scene entries before
assuming a fix is scoped to one scene.

**Being retired from the Singles (2026-10-07):** `scripts/
migrate_singles_to_pulse.py` (pulse-effect skill, "Phase 4") switches every
Power Singles entry to Pulse at deploy; its `--revert` puts Power and each
scene's old params back. Check the live store before assuming a scene still
runs Power here.

## `sparks_color` is an ACCENT param — force-written black unless the
   scene entry authored it

`config/effect_params.json` marks `sparks_color: {"accent": true}`. Per
AGENTS.md's accent-param rule, `scene_compiler._entry_config` writes this
param black on every compile UNLESS the scene's own entry authored a real
value — ported from spot-effects' `accent_param_for` rule. This was the
un-ported gap that showed white sparks on STAR/Singles/power for a while
(fixed 2026-08-15). Any future accent-capable effect just needs
`"accent": true` on its param in the registry — no compiler change
required — but a scene's CURRENT stored `sparks_color` is not proof he
tuned it; check whether the entry actually authors it before treating the
value as intentional (same caution as AGENTS.md's "a scene's stored data
is not proof he authored it" rule).

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

Power names no activity attributes (its motion is the audio). Its own
white sparks (`sparks_color`, when a scene authors white) are kept in the
set's colours by the white guard during a charge or drop only — outside
the phases it blends exactly as before. Joining the layer also means the
Singles entries still on Power (until `migrate_singles_to_pulse.py` runs)
go dark in a lull, like the Pulse singles do.

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

No dedicated `check_power_*.py`/`test_power_*.py` exists for Power itself;
this effect is close to stock LedFX behaviour. Its documented invariant
(the accent param) is proven by `scripts/check_spectra.py`'s "STAR power/
Singles accent" section, not by any pytest test. History: AGENTS.md's "SPECTRA app" section,
"accent" param paragraph.
