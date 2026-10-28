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
  strip's (Melt on STAR), so the strip's own CHARGE and DROP (gain, fill,
  drop shockwave) still ride into the crystal through the mapping — but
  NOT its lull (2026-10-14, his Q5 changed: "The strip used by the radial
  effect shouldn't do the lull, let the crystal mapping handle the lull").
  Star stamps its source strip every frame (`strip_phase.
  mark_radial_source`, cleared in `deactivate`); the strip phase layer
  skips a lull that starts while it is stamped (strip_phase's THE STRIP
  STAR READS): no fade, no lull content, only an ease back from the
  charge. So Star takes the panel dark ON the dark point BY ITSELF in both
  modes — "bands" by its cut, "implode" by `_implode_fade`. The set's colours are cached once a
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

## THE PRE-DROP — the outline grows out of the centre (2026-10-27)

His approval (the predrop plan, 2026-10-26): "the star predrop should grow
from the center as it spins, so it doesn't just pop in." Star is in
`fx.device_model.PRE_DROP_EFFECTS` since predrop step 8, one look for both
kinds ("outline", `pre_drop_looks` in config/effect_params.json); the
PRE_DROP block above `_LUM` in `fx/effects/radial.py` for the look. Four
invariants not visible cold:

- **THE DARK IS THE ARM'S.** Star is a LULL_DARK and BREATH_HOLD member, so
  SpotFX measures its dark point and breath to the pre-drop: lull B's cut
  empties the star early and the panel is black before the pre-drop with no
  code of the look's own.
- **THE OUTLINE IS RADIAL'S OWN SHAPE.** `_pre_drop_outline` draws a band
  PRE_DROP_OUTLINE_W thin at a shaped radius (`_shaped_radius`, at the
  outline's own angle: Star's rotation plus its spin-up, PRE_DROP_SPIN_FROM
  -> _TO rev/s) growing from 0 to PRE_DROP_OUTLINE_R x the panel height,
  eased out (`1 - (1 - frac)^2`) — a dot on the pre-drop, full size on the
  drop. Dim (30% -> 40%), coloured round the set by angle from the cached
  palette (so the colour change fading across the pre-drop shows in it),
  composed brighter-wins over the black panel in `_star_phase_frame`. The
  drop is Star's own D3.
- **THE DROP'S PIECES WEAR THE SET AS IT IS AT THE DROP** (the plan's 2.2:
  "Star re-samples its palette as the colour fades"; widened 2026-10-28,
  the Admiral: "yes, the star should change color"). A falling piece keeps
  its palette POSITION (`g`, NaN when no palette was seen); after a
  pre-drop that played (`_pd_seen`), OR when SpotFX tells the drop a
  colour change landed with no pre-drop to fade across
  (`fx/effects/drop_colour_resample.py`'s `drop_color_landed` key — the
  SAME `ResponseEngine.on_event` drop-colour claim that tells a band to
  skip its own colour-jump kind), `_drop_snap` recolours the pieces from
  the live palette every frame (`_palette_full`, nearest_set_grad's own
  arithmetic, so an unchanged OR held set gives the same colours back —
  Melt's gradient can roll, but a held change never claims, so the told
  key stays False and nothing resamples). On a drop with no pre-drop the
  pieces now fly out in the NEW set too, under the instant colour change
  (about half a second), landing on the drop's first rendered frame — the
  told key reaches Star right before this drop's own phase arm.
- **LIGHT AND IDENTITY.** The lull's light drops (-14% at a 0.8 s spike,
  -48% at 2 s, -45% at a 3.3 s vocal intro). Untold, `_pre_drop_step`
  clears the clock first, so the lull is today's frame for frame (proven
  against the module at the step-8 base through `pre_drop_look_harness.
  star_run`, which hosts the strip Star samples).

## Out of Star: the bands release (transition programs)

A program out of Star captures `_program_snapshot(settings)` — NOT
`_handoff_snapshot`, which stays an empty-pieces snapshot so the ordinary
crossfade adoptions (every particle effect's `src == "radial"` branch) are
unchanged. ~`bands_pieces` lit cells, brightness-weighted, each with its
set colour (`rgb`) and `v = omega x r` from the live rotation rate
(`_track_rotation`). A dark star offers no pieces, so no program. Registry:
`transition_program.STAR_OUT`; the two new flights (UNWIND, CLUSTER) are in
`transition_cloud.py`.

## Into Star: the RingFormer grow-in (2026-10-14, "Do rec on transitions")

`transition_cloud.py`'s "INTO STAR" section is the binding statement;
`transition_program.STAR_IN` the registry (Fountain, Shoal Break, Spark
Rings, Flame Lick, Unravel, WIND). Four things not visible cold:

- **FORM is Star's, chosen by the incoming effect** (`CloudProgram.
  _make_former` -> `RingFormer` whenever the incoming effect has
  `_program_bands`), from `STAR_FORM_AT` (0.35) of the program on every
  pair. Star supplies the geometry: `_program_bands` (the strip's bright
  peaks, read once at FORM — the strip is mid-crossfade before that),
  `_program_polar` / `_piece_xy` (screen <-> Star's ROTATING frame),
  `_program_band_u` (twist-aware), and `_last_u` (this frame's shaped
  radius field, stored by `draw()`).
- **The front is paced by CELLS, not radius**: Star's cells crowd into a
  narrow band of shaped radius, so a front at a steady radial speed lit the
  whole middle in ~0.1 s (measured); the RingFormer passes an even share of
  the cells (their rank in the u field sorted at FORM) each frame. Its
  length is Star's own `ring_reveal_front_s` (0.65 s, registered, Sonic
  `set_scene_entry_param`, help `star-into-transitions`).
- **The old crossfade choreography is retired for program pairs**:
  `_adopt_handoff` stands down while `_transition_program` is set, and the
  particle side's gather only ever ran on a crossfade sibling, which a
  program switch never makes. A plain crossfade (programs off, a house
  glide) still blooms as before.
- **WIND integrates turn_about's law in exact polar terms**: turn_about
  re-reads each piece's radial speed off its last chord, which adds an
  outward drift (rho om^2 dt / 2 a frame) that outruns an inward push.
  UNWIND (approved, outward) is left exactly as shipped.

**Measuring a reveal on this rig**: Melt BREATHES (Star's lit cells swing
~850-2200 over a few seconds on its own) and the rig turns Star (~18/cell a
frame of change by itself) — measure the star's own LAYER (Star's picture x
the program's gain, `former._gain`) against the raw picture of the same
frame, never absolute lit counts across time
(`tests/test_star_into_programs.py`).

## Sonic reach

No direct param edit (same rule as every effect skill here) — except the
per-entry VALUES Sonic reaches through `set_scene_entry_param`: every
registered param, including `lull_mode`, `lull_core_u`, `lull_piece_tau`,
`drop_snap_gain`, `drop_snap_decay_s`, `shape_morph_s`,
`ring_reveal_front_s` (help topics `star-lull-drop`, `star-shape-morph`,
`star-into-transitions`). The three out-of-Star transition
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
of Star on the real `set_effect(program=)` hook),
`tests/test_star_into_programs.py` (every row INTO Star: no pop-in,
staggered landings, WIND),
`tests/test_star_strip_lull.py` (the strip Star reads skips its lull,
keeps charge/drop; other strips unchanged), `scripts/
check_star_phases.py` (the same rig, printed: lull B's lit/falling/kept
cells every 0.1 s, D3's lit/white cells after the drop, and every program
out of Star's largest frame-to-frame change and white-cell count). The warp background fix is proven in
`tests/test_matrix_overwrite_background_double_apply.py`
(`test_radial_warp_background_applies_once_not_twice`,
`test_radial_background_recovers_after_a_warp_ends`). History: AGENTS.md's
"Radial (STAR) rotation is audio-lows-driven" section, `fx/VENDOR.md`
#22, #62.
