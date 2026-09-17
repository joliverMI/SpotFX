---
name: power-effect
description: >
  fx/effects/power.py (`Classic` category, Strips/Singles) — the classic
  LedFX bass-percussive "power" effect, bound onto the Singles device (and
  several scenes' Strips) across EVERY one of his 10 live scenes. Load
  before touching `sparks_color` (an accent param) or before assuming a
  scene's stored sparks colour reflects what he actually tuned.
---

# Power

A near-stock LedFX `Classic` effect (`mirror`, `blur`, `sparks_color`,
`bass_decay_rate`, ...) — shared across virtually every scene here via the
Singles device, so a change here has the widest blast radius of any
effect on this list. Check `EFFECT_SCENE_MAP.json`'s scene entries before
assuming a fix is scoped to one scene.

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

## Sonic reach

No direct param edit — reachable only through an already-attached
`FlareKind` on whichever scene binds this effect (its `sparks_color`
target, if any, is what a "colour jump"-shaped flare on Singles would
move).

## Executable proofs

No dedicated `check_power_*.py`/`test_power_*.py` exists — a named gap;
this effect is close to stock LedFX behaviour and its documented invariant
(the accent param) is proven generically by
`tests/test_dark_light.py`/the scene-fire test suite rather than a
power-specific script. History: AGENTS.md's "SPECTRA app" section,
"accent" param paragraph.
