---
name: radial-effect
description: >
  fx/effects/radial.py (Matrix, crystal-mapper) — the polygon/star effect
  behind the STAR scene. Load before touching rotation/spin behaviour, or
  before diagnosing any "the effect isn't reacting to X" report on this
  module — its ordinary motion is a squared audio gain (`spin`), so a
  healthy `spin` can read as frozen during quiet passages and that is not
  a bug; `base_rotation` (a linear floor) and a charge-phase spin-up are
  the only other rotation sources.
---

# Radial (STAR)

Matrix effect renders to `crystal-mapper` — load `crystal-hex-grid` first.
`radial` carries `no_background_color: true` in the registry (sparse
canvas that starts as `np.zeros`; an authored background would wash the
panel) — never add a black-background "fix" here the way blackhole needs
one; this effect is deliberately exempt.

## `spin` is audio-squared, not a motor speed

`spin_total += lows_impulse * spin_cfg² / 10 * ROTATION_SPEED_SCALE` per
60 Hz audio callback — i.e. **rev/s = 6 × ROTATION_SPEED_SCALE ×
lows_impulse × spin²**. `ROTATION_SPEED_SCALE` (0.8, Admiral order
2026-10-06, "reduce the maximum speed of rotation of Star by 20 percent")
is a single multiplier applied to every rotation-speed source in this
module — spin's reactive ceiling was 6 rev/s (spin_cfg at its own max 1.0,
full audio impulse), now 4.8 rev/s. `spin` is a GAIN on the live captured
lows power (snapcast.monitor melbank), NOT the bridge's "intensity"
(stored librosa analysis — the two diverge freely). During bass-light
passages the lows impulse idles ~0.01, so a healthy `spin=0.55`
turns ~5.2°/s (post-scale) and reads as parked while rendering fine.
Before diagnosing "effect X ignores its speed param" on ANY effect, check
whether the param is tagged `"aspect": "reactivity"` in
`config/effect_params.json` and measure the LIVE impulse before blaming
the value or the writer — this is a general trap, not radial-specific, but
radial is where it was found (`docs/spectra-star-motion-audio-idle.md`,
`scripts/check_star_spin_motion.py`).

## `base_rotation` is a SEPARATE, differently-scaled control — don't conflate

`base_rotation` (0..1.6, default 0.0 — ceiling reduced from 2.0 the same
2026-10-06 order) is a quiet FLOOR in plain revolutions/second — LINEAR,
absolute, never squared, never audio-multiplied. It combines with the
audio-driven `spin` term as `effective rev/s = max(base_rotation, reactive
rev/s)` — a FLOOR, not a sum, so it never adds anything at a peak. It
advances on the RENDER clock (`draw()`), not `audio_data_updated` — a base
term there would stall in exactly the quiet case it exists for. Default
0.0 keeps every pre-existing scene byte-identical until he sets one.
`fx/VENDOR.md` deviation #22. A stored scene authored above the new 1.6
ceiling is clamped on load (`spectra/models/scene.py`'s
`_clamp_radial_base_rotation`), not silently dropped by the effect's own
schema validation.

## The charge phase adds its own spin-up — a third rotation source

During a charge, `_phase_step` adds `CHARGE_SPIN_REV_S * p² * dt`
(0.72 rev/s at full charge — `0.9 * ROTATION_SPEED_SCALE`, `p` = charge
progress) to `spin_total` — an ease-in that maxes at the charge ramp's
END. Its direction is `spin`'s sign if it has one, else `twist`'s, else
clockwise. So a star that visibly spins up before a drop, even in a quiet
passage, is this choreography, not `spin` or `base_rotation` misbehaving.

## The lull-implode/drop-bloom warp's own background blend — `bg_color_use`, not a value fix

During a warp frame (`draw()`'s crossfade/implode-bloom branch), the
pasted image already blends `self._bg_color` scaled by its own per-pixel
`bg_alpha` — a value `get_pixels()`'s single-scalar background blend
can't see, so it was adding a second, unscaled copy on top (worse than a
flat double at partial `bg_alpha`: additive `bg*(1 + bg_alpha)`). Fixed by
having `draw()` set `self.bg_color_use = False` for the one frame the warp
branch runs, so `get_pixels()` skips its own blend entirely that frame —
the warp's already-complete pixel stands as rendered. `draw()` now also
calls `self._refresh_bg_render_state()` unconditionally at the top of
every frame — without it, an instance that ever ran one warp frame stayed
background-less FOREVER afterward, since that base-class refresh is a
no-op once the background colour has settled (`fx/VENDOR.md` #62). This
is unrelated to `no_background_color` above — that gates colour-set
WRITES; this is the effect's own per-frame render-state flag.

## `spin_sign` — a real sign-flip control, ported for STAR's Reverse kinds

`spin_sign` (toggle) maps to the REAL param `spin` via
`meta["maps_to"]`, flipping only its SIGN with magnitude preserved from
`spin`'s own current carried value (never a fixed target). A write to it
MUST go through `executor.jump()`, never `.glide()` — a sign flip can
never be allowed to continue smoothly through zero regardless of `spin`'s
own `smooth: true` tag; that's the whole point of the control (see
`scene_response._compute_param_moves`'s `sign_control` branch,
`config/effect_params.json`'s own notes on `spin`/`spin_sign`,
AGENTS.md's "STAR reverse-flare-use-flip" entry).

## Sonic reach

No direct param edit (same rule as every effect skill here). `spin`/
`base_rotation` both have registry `help_topic: radial-base-rotation`
(shown as a HelpLink on the Initial Set tab) — documentation reach, not
Sonic write access.

## Executable proofs

`scripts/check_star_spin_motion.py`, `scripts/check_radial_base_rotation.py`,
`tests/test_radial_base_rotation.py`. The warp background fix is proven in
`tests/test_matrix_overwrite_background_double_apply.py`
(`test_radial_warp_background_applies_once_not_twice`,
`test_radial_background_recovers_after_a_warp_ends`). History: AGENTS.md's
"Radial (STAR) rotation is audio-lows-driven" section, `fx/VENDOR.md`
#22, #62.
