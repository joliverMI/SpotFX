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

## A `"sauron"` hand-off snapshot is treated exactly like `"eye"`

Sauron (fx/effects/sauron.py, 2026-10-10) is a copy of Eye with Eye's
hand-off choreography verbatim, so wherever this effect special-cases an
incoming `"eye"` snapshot it names `"sauron"` alongside it (the src gate in `_adopt_handoff` — radial blooms out of either eye). Keep
the two together: a new `"eye"` special case here needs `"sauron"` too
(sauron-effect skill).

## Star's own lull and drop (the star plan, 2026-10-13 — "Use lull b, drop d 3")

`radial.py`'s "STAR'S OWN LULL AND DROP" block comment is the binding
statement; the plan is `/home/javi/fleet-spotfx/data/star-plan/report.md`.
Five things not visible cold:

- **Star draws nothing of its own** — its colours are the `radial-dummy`
  strip's (Melt on STAR), so the strip's own charge/lull/drop (gain, fade,
  drop shockwave) still rides into the crystal through the mapping (his
  answer to the plan's Q5: keep it). The set's colours are cached once a
  frame off the strip effect's gradient (`_refresh_palette`), which is what
  `get_gradient_color_vectorized1d` and `_set_colours` read — a piece
  always wears the SET colour nearest its cell, composed brighter-wins
  (`splat_brighter`), never a channel max (two hues maxed pale to white).
- **LULL B (`lull_mode` "bands", the default)** is a rim CUT in Star's own
  shaped radius, shrinking the lit AREA evenly in time; every lit cell the
  cut passes may become a piece that falls in Star's ROTATING frame (so it
  keeps the ring's turning). Star is in `LULL_DARK_EFFECTS` and reads the
  dark point itself: black ON it (`LULL_END_FADE`), the fall sped up near
  it so every piece is in. Untold (no SpotFX keys) the dark point is
  progress 1.0. "implode" is the original warp, still selectable.
- **DROP D3** throws the swallowed pieces (`_held`) back out on the drop's
  edge (`_begin_snap`) and wears a hue-kept colour gain (`hue_gain`). It is
  NOT the shared Shockwave (`DROP_SHOCK` stays False) but Star is in
  `DROP_SHOCK_TOLD_EFFECTS`: told `drop_shock_on` False (room switch, scene
  switch, energy floor) the drop is the plain bloom. Nothing kept, an
  "implode" lull, or the orphan watchdog's quiet release: plain bloom too.
  The snap outlives the drop phase's own self-reset; a new charge/lull
  discards it.
- **The breath-hold** is applied in Star's own draw (`BREATH_HOLD_EFFECTS`,
  like Pulse) — the base Twod painter only runs for Shockwave members.
- **The shape morph** (`shape_morph_s`, 0.6 s): only a CHANGE of `edges` on
  a live instance starts one (`config_updated`); the shaped radius blends
  linearly old->new, a piece's divisor harmonically (`_shape_div`).

## Out of Star: the bands release (transition programs)

A program out of Star captures `_program_snapshot(settings)` — NOT
`_handoff_snapshot`, which stays an empty-pieces snapshot so the ordinary
crossfade adoptions (every particle effect's `src == "radial"` branch) are
unchanged. ~`bands_pieces` lit cells, brightness-weighted, each with its
set colour (`rgb`) and `v = omega x r` from the live rotation rate
(`_track_rotation`). A dark star offers no pieces, so no program. Registry:
`transition_program.STAR_OUT`; the two new flights (UNWIND, CLUSTER) are in
`transition_cloud.py`. Into Star is not registered yet (his "still need
work") — the next task.

## Sonic reach

No direct param edit (same rule as every effect skill here) — except the
per-entry VALUES Sonic reaches through `set_scene_entry_param`: every
registered param, including `lull_mode`, `lull_core_u`, `lull_piece_tau`,
`drop_snap_gain`, `drop_snap_decay_s`, `shape_morph_s` (help topics
`star-lull-drop`, `star-shape-morph`). The three out-of-Star transition
knobs are ROOM settings (`transition_bands_pieces`, `_bands_hold_ms`,
`transition_unwind`), reached by `set_setting`. `spin`/
`base_rotation` both have registry `help_topic: radial-base-rotation`
(shown as a HelpLink on the Initial Set tab) — documentation reach, not
Sonic write access.

## Executable proofs

`scripts/check_star_spin_motion.py`, `scripts/check_radial_base_rotation.py`,
`tests/test_radial_base_rotation.py`. The star plan: `tests/star_harness.py`
(a real Melt strip under a real Radial — Star renders black without it),
`tests/test_star_phases.py` (lull B black on the dark point, D3 no-white,
the switches, the morph), `tests/test_star_programs.py` (every program out
of Star on the real `set_effect(program=)` hook). The warp background fix is proven in
`tests/test_matrix_overwrite_background_double_apply.py`
(`test_radial_warp_background_applies_once_not_twice`,
`test_radial_background_recovers_after_a_warp_ends`). History: AGENTS.md's
"Radial (STAR) rotation is audio-lows-driven" section, `fx/VENDOR.md`
#22, #62.
