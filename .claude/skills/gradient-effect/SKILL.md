---
name: gradient-effect
description: >
  fx/effects/gradient.py (TemporalGradientEffect, registry id `gradient`) +
  fx/effects/modulate.py — the colour set's colour, BREATHING on its own
  clock. Bound since phase 4 of house lighting into the "House Star" and
  "House Fish" scenes on the `single-color-effect` virtual (the porch rail
  and the dining table). Load before touching breathing speed, the
  modulate/sine/breath options, the background on this effect, or a
  "the singles stopped breathing" report.
---

# Gradient (breathing)

A stock LedFX `Non-Reactive` effect: `TemporalGradientEffect(TemporalEffect,
GradientEffect, ModulateEffect)`. TemporalEffect runs `effect_loop` on its
OWN thread at `10 x speed` Hz (non-daemon — an `fx.headless` script must
`os._exit()`); the render thread only reads `self.pixels`.

## The breath, in numbers

- `modulate: true` + `modulation_effect: "sine"` multiplies the colour by
  `0.3*sin(counter)+0.4`, i.e. **10%-70%** of the colour. The counter
  advances `0.1 x modulation_speed / pi` per loop, so ONE BREATH LASTS
  **19.74 / (modulation_speed x speed) seconds** — the house scenes run
  `speed: 2.0`, so `modulation_speed` 0.8 = 12 s, 0.5 = 20 s.
- `"breath"` blanks pixels from an index upward: on a ONE-PIXEL fixture it
  is on/off, not a fade. Use `"sine"` on the singles.
- A one-pixel fixture shows the gradient's FIRST colour (`get_gradient`).
- `modulation_speed` is the registry's `"motion": true` param — the house
  mode's motion hook writes it (0..1 across 0.01..1).

## The breath keeps its phase through a glide (VENDOR #49) — don't undo it

`Effect._apply_config` runs every base's `config_updated` on every write
AND on every frame of a numeric/colour tween. `ModulateEffect.config_updated`
used to reset the counter there, so the breath FROZE at one level for as
long as any glide ran (a mode's 90 s clock change, a colour landing, the
motion hook). It now resets only when `modulation_effect` changes (sine and
breath count in different units). Proof, with the old reset restored as a
red control: `tests/test_gradient_breathing.py`.

## No background, on purpose

`config/effect_params.json` marks `gradient` `no_background_color`: in
overwrite mode the background fills the dark half of the breath
(`bg * (1 - alpha)`), so Calm's Singles background (#ffd37d at 0.64) would
flatten a 10-70% breath to roughly 68-89%. Every colour-set write path
honours the flag (scene compiler, conductor, flare jump).

## Which class is "the effect"

gradient.py also defines the `GradientEffect` mixin (no NAME), which sorts
first; `fx.device_model._effect_class` prefers the class that names itself,
so schema defaults and Sonic's param help come from TemporalGradientEffect.

## Sonic reach

Through the house mode's motion hook (Sonic's `set_house_fixture motion`),
or a direct scene edit. No flare kind targets it.

## Executable proofs

- `tests/test_gradient_breathing.py` — the breath through a glide; red on
  the old reset; byte-identical with no glide.
- `tests/test_house_phase4.py` — registry entry, class resolution, and a
  scene compile writing the set colour and no background.
