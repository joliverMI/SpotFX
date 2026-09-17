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

`spin_total += lows_impulse * spin_cfg² / 10` per 60 Hz audio callback —
i.e. **rev/s = 6 × lows_impulse × spin²**. `spin` is a GAIN on the live
captured lows power (snapcast.monitor melbank), NOT the bridge's
"intensity" (stored librosa analysis — the two diverge freely). During
bass-light passages the lows impulse idles ~0.01, so a healthy `spin=0.55`
turns ~6°/s and reads as parked while rendering fine. Before diagnosing
"effect X ignores its speed param" on ANY effect, check whether the param
is tagged `"aspect": "reactivity"` in `config/effect_params.json` and
measure the LIVE impulse before blaming the value or the writer — this is
a general trap, not radial-specific, but radial is where it was found
(`docs/spectra-star-motion-audio-idle.md`,
`scripts/check_star_spin_motion.py`).

## `base_rotation` is a SEPARATE, differently-scaled control — don't conflate

`base_rotation` (0..2, default 0.0) is a quiet FLOOR in plain
revolutions/second — LINEAR, absolute, never squared, never
audio-multiplied. It combines with the audio-driven `spin` term as
`effective rev/s = max(base_rotation, reactive rev/s)` — a FLOOR, not a
sum, so it never adds anything at a peak. It advances on the RENDER clock
(`draw()`), not `audio_data_updated` — a base term there would stall in
exactly the quiet case it exists for. Default 0.0 keeps every pre-existing
scene byte-identical until he sets one. `fx/VENDOR.md` deviation #22.

## The charge phase adds its own spin-up — a third rotation source

During a charge, `_phase_step` adds `CHARGE_SPIN_REV_S * p² * dt` (0.9 rev/s
at full charge, `p` = charge progress) to `spin_total` — an ease-in that
maxes at the charge ramp's END. Its direction is `spin`'s sign if it has
one, else `twist`'s, else clockwise. So a star that visibly spins up before
a drop, even in a quiet passage, is this choreography, not `spin` or
`base_rotation` misbehaving.

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
`tests/test_radial_base_rotation.py`. History: AGENTS.md's "Radial (STAR)
rotation is audio-lows-driven" section, `fx/VENDOR.md` #22.
