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
lows_impulse × spin²**. `ROTATION_SPEED_SCALE` (**0.4** since 2026-11-18;
0.8 before, from the 2026-10-06 order "reduce the maximum speed of rotation
of Star by 20 percent", and halved again by "slow the star rotation by 50%
at all speeds, including the burst speeds, not just the static speed",
data/star-curve-study/report.md) is a single multiplier applied to every
rotation-speed source in this module — spin's reactive ceiling was 6 rev/s
(spin_cfg at its own max 1.0, full audio impulse), then 4.8, now **2.4
rev/s**. THAT IS WHY A BURST NEEDS NO SEPARATE KNOB: a bass hit is this
same law at a high impulse, so one scale slows the static speed and the
bursts together. The per-frame cap is halved in step (below), because the
cap — not the scale — is what the loudest fires sit on. `spin` is a GAIN on the live captured
lows power (snapcast.monitor melbank), NOT the bridge's "intensity"
(stored librosa analysis — the two diverge freely). During bass-light
passages the lows impulse idles ~0.01, so a healthy `spin=0.55`
turns ~2.6°/s (post-scale; it was 5.2 before 2026-11-18) and reads as
parked while rendering fine.
Before diagnosing "effect X ignores its speed param" on ANY effect, check
whether the param is tagged `"aspect": "reactivity"` in
`config/effect_params.json` and measure the LIVE impulse before blaming
the value or the writer — this is a general trap, not radial-specific, but
radial is where it was found (`docs/spectra-star-motion-audio-idle.md`,
`scripts/check_star_spin_motion.py`).

## `base_rotation` is a SEPARATE, differently-scaled control — don't conflate

`base_rotation` (0..**0.8**, default 0.0 — the ceiling is
`2.0 * ROTATION_SPEED_SCALE`: 2.0 originally, 1.6 after the 2026-10-06
order, 0.8 since 2026-11-18) is a quiet FLOOR in plain revolutions/second — LINEAR,
absolute, never squared, never audio-multiplied. It combines with the
audio-driven `spin` term as `effective rev/s = max(base_rotation, reactive
rev/s)` — a FLOOR, not a sum, so it never adds anything at a peak. It
advances on the RENDER clock (`draw()`), not `audio_data_updated` — a base
term there would stall in exactly the quiet case it exists for. Default
0.0 keeps every pre-existing scene byte-identical until he sets one.
`fx/VENDOR.md` deviation #22. A stored scene authored above the current
ceiling is clamped on load (`spectra/models/scene.py`'s
`RADIAL_BASE_ROTATION_MAX` / `_clamp_radial_base_rotation`, which mirrors
the literal — as does `config/effect_params.json`'s declared `max`; all
three move together), not silently dropped by the effect's own schema
validation.

## The charge phase adds its own spin-up — a third rotation source

During a charge, `_phase_step` adds `CHARGE_SPIN_REV_S * p² * dt`
(**0.36** rev/s at full charge — `0.9 * ROTATION_SPEED_SCALE`, so it
followed the 2026-11-18 halving on its own; `p` = charge progress) to `spin_total` — an ease-in that maxes at the charge ramp's
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
docs/agents/spectra-engine-core.md's "STAR reverse-flare-use-flip" entry).

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

## THE STAR IMPROVE PLAN (2026-11-12, data/star-improve-plan/plan.md) — spin from the first frame, the 70% cap, the star wave, Edge Morph

His ask, verbatim: "I want it to be able to spin from the beginning. It
should also cap the max speed it can spin to 70% of what it is now, but it
shouldn't slow down at lower speeds. Also, the amount of star should
dynamically change with the music ... constantly be flowing and bouncing
between the top and bottom values for that setting. Flares should change
the number of edges, but do it visually smoothly like we have"; after the
star grid: "let's do -.2 to +.4 as the standard range they sway between. I
want it to go through 0". Five things not visible cold:

- **The entry no-spin was a FIRE-TIME DEFECT, not the effect's.** STAR's
  `spin` binding carries `random_sign: true`; `binding_resolver` flipped
  the sign and THEN clamped to the registry's `min 0`, so ~52% of fires
  landed `spin = 0.0` and nothing turned until a flare's "Flare patch" kind
  wrote spin back. `_maybe_flip_sign` now never flips a param whose `lo >=
  0` (`spectra/services/binding_resolver.py`). The direction is Flip's job.
- **`_govern_rotation` (draw, after `_base_rotation_step`)** measures this
  frame's TOTAL advance (audio spin + base floor + charge spin-up, each
  writer adding its own signed revolutions into `_frame_adv` as it moves
  `spin_total`; `_govern_rotation` drains that accumulator exactly once
  per governed frame — never reduced mod 1, so it reads correctly even
  past half a revolution), scales it by the ease-in and clamps it. The
  clamp shipped as `ROTATION_CAP_REV_S` = 0.7 x 6.0 x ROTATION_SPEED_SCALE
  = 3.36 rev/s; the spin smooth plan (next section) re-expressed it per
  rendered frame — `ROTATION_CAP_DEG_FRAME`, 18 deg per frame then and
  **9 deg per frame** (0.75 rev/s at 30 fps) since 2026-11-18.
  Identity below the cap. `spin_ease_in_s` defaults to **0** on the effect
  (every other Radial scene byte-identical); STAR's Matrix entry carries
  1.0 (`STAR_SPIN_EASE_IN_S`, written by `scripts/star_improve_scene_data.
  py`). No quiet floor on STAR by his word ("it can slow to a stop during
  quiet music"): `base_rotation` stays 0 and his.
- **`_star_wave_step` (draw)**: with `star_wave` on, `self.star` is
  overridden per frame from `_star_wave_u` between `star_wave_lo` and `_hi`
  (STAR: **-0.2 .. +0.4**, through flat = 0 every cycle), period
  `star_wave_period_slow_s` (effect default 7, **STAR 28 since 2026-11-18**)
  at `energy` 0 -> `_fast_s` (3, **kept** — his "slow the star setting drift
  by 75%, but keep the burst speeds": the energy-paced period IS the drift's
  burst speed) at 1; the
  phase integrates (a pace change never jumps the value) and, on the
  scene's FIRST activation, starts AT the fired `star` value (clamped into
  the bounds), heading up — a later re-fire while STAR is already showing
  carries on from its current point in the sway instead, so nothing steps.
  The stored `star` is never rewritten. **Flat is star = 0**, not 0.5 (he assumed
  0.5 until the -0.7..+0.7 x 3-6 edges grid): `radius x (1 + star
  cos(edges phi))`; 0.5 is a 3.0x star. Crossing 0 is continuous.
- **`star_wave_curve` (2026-11-18, data/star-curve-study/report.md)** picks
  the phase -> value map: `cosine` (the DEFAULT, and bit-for-bit the closed
  form that shipped before — so every other Radial scene is untouched),
  `linear`, `smooth`, `plateau` (**STAR's own entry**) and `steps`. It never
  was the "linear bounce" he described: the cosine already eases at both
  LIMITS (37% of a cycle within 0.05 of one) and runs FASTEST through flat
  (11%) — the missing dwell was the one at flat. `plateau` holds four times
  a cycle — at lo, at flat, at hi, at flat again — measuring **45% flat /
  31% ends**, with `star_wave_dwell_flat` (0.161) and `_dwell_end` (0.089)
  as the hold shares of one cycle, his "50% held, split 1.8 : 1 toward
  flat". **A glide's time is proportional to the value span it covers**, so
  every glide shares one peak rate (`pi / glide_share`) and the short leg
  never lurches; holding half the cycle still leaves the glide at HALF the
  old peak rate because the cycle is 4x longer.
  **THE HOLD IS AT THE VALUE 0, NOT THE MIDPOINT OF THE BOUNDS** — with
  -0.2..+0.4 flat is at ONE THIRD (`x0` in `_star_wave_u`), and a curve
  built on the midpoint would hold at +0.1, a half-pointed shape. Bounds
  that never cross 0 lose their flat holds to the limits
  (`_star_wave_segments`), so the param is safe on any bounds.
  **The seeding**: `_star_wave_phase_for` keeps the `arccos` closed form for
  `cosine` (exact, not approximate) and inverts every other curve from a
  256-point table of its RISING span, `searchsorted(side="left")` so a
  landed value sitting on a hold starts at that hold's BEGINNING — the
  binding's own `star = 0.0` therefore enters flat and waits out the whole
  dwell. Round trip measured at < 5e-4 star units
  (`tests/test_star_curve.py`, `data/star-curve-study/seed_inverse_check.py`).
  `_star_wave_rise_end` COMPUTES that span rather than assuming half a cycle;
  it comes to exactly 0.5 for any paired dwell, but computing it is what
  keeps an unequal pair correct.
- **`energy`** (0..1, default 0.5) is PUSHED by the pulse feed
  (`spectra/services/pulse_feed.py`; `fx.device_model.ENERGY_FED_EFFECTS`
  = the one-colour effects + radial, `ENERGY_ONLY_EFFECTS` = radial takes
  `energy` alone, never `beat_ms`). Not a value to author.
- **Edge Morph** is scene data + one engine addition: a `ParamTarget` mode
  `random_other` (`spectra/models/scene.py`; resolved per virtual in
  `scene_response._compute_param_moves` via `_roll_other` — a uniform
  integer in [lo, hi] that is never the carried value, landed verbatim, a
  PERMANENT kind carries it). STAR's kind targets `edges` 3..6 on the two
  upper flare bands; the existing `shape_morph_s` (0.6 s) glides it; it
  holds until the next flare/update (his Q5). The 0.7-1 patch kinds no
  longer write `star: 0`.

Proofs: `tests/test_star_improve.py` (the fire-time fix, the ease, the
cap under a full charge, the wave's bounds/continuity/zero crossing/start,
Edge Morph through the real ResponseEngine, Melt's floor, the TV ring and
both data scripts). Rig scripts: `scripts/render_star_improve_crystal.py`
(the explainer's crystal tiles; the live law driven per frame),
`scripts/render_star_improve_strips.py`, `scripts/render_star_improve_grid.py`
(the star x edges grid he decided from), `scripts/render_star_improve_tablet.py`.

## THE SPIN SMOOTH PLAN (2026-11-12, data/star-spin-smooth/plan.md) — the per-frame clamp and the energy-paced release

His ask, verbatim, after the star improve plan went live: "i like it, but
it is too jerky in it's spin especially on big bass hits. the burst speed
is too fast and fades too fast. I think sometimes it moves so fast it's
hard to tell it moved. We need to cap the burst speed. Do actual analysis
on how it moves, it shouldn't be jerky, but it should be dynamic"; after
the analysis page (side-by-side clips + velocity plots on his own bass
songs): "the burst fade should be snappier at higher energies and lazier
at low energies. do 18 degrees per frame for now". Four things not visible
cold (`data/star-spin-smooth/report.md` has the evidence):

- **The crystal renders at 30 fps, not 60.** The `crystal` WLED device's
  `refresh_rate` is 30 and a virtual renders at its slowest device
  (`fx/virtuals.py`); the audio callback still runs at 60 Hz, so one
  rendered frame carries TWO callbacks' turn. That made the 3.36 rev/s cap
  40 deg per frame — past the **180/edges** deg (30 deg at 6 edges) at
  which an N-point star's turn reads BACKWARDS (temporal aliasing). His
  "hard to tell it moved" was aliasing, not speed. Any per-frame reasoning
  about STAR must use dt = 1/30; the rig (`tests/star_harness.py`) steps
  at 1/60, so a per-frame cap is 2x the rev/s there.
- **`ROTATION_CAP_DEG_FRAME` (per RENDERED frame, whatever dt — a
  stalled frame is clamped to the same angle)** replaces `ROTATION_CAP_
  REV_S`. 18 deg per frame = 1.5 rev/s at 30 fps when the spin smooth plan
  shipped; **9 deg = 0.75 rev/s since 2026-11-18**, both under the aliasing
  limit of every edge count STAR rolls (3..6 -> 60..30 deg). One constant:
  retune it there. A loud fire's STEADY speed rides this clamp — the trade
  he chose over 22 deg, and the reason the 2026-11-18 halving had to touch
  the cap as well as the scale (the scale alone would have left exactly
  those clamped frames at the old angle).
- **The jerk was the impulse SHAPE, not the cap.** `lows_power(filtered)`
  decays 0.2 per 60 Hz frame (ExpFilter, `fx/effects/audio.py`) and the
  drive is spin² x impulse, so a hit was a ~6-frame burst (rise ~100 ms,
  gone in ~200 ms); at spin 0.70 nothing touched the cap and rms jerk was
  still ~290 rev/s³. **The release** (`_govern_rotation`, between the ease
  and the clamp) is a one-pole low-pass ON THE PER-FRAME ADVANCE —
  `lp += (adv - lp)(1 - exp(-dt/tau))` — unity DC gain, so the total turn
  and the mean speed of a steady passage are preserved to the frame and
  only the burst is spread. Not a peak follower on the speed (that needed
  a gain and lowered the floor — candidates B/C on the page). `tau` =
  `spin_release_low_s` at told `energy` 0 -> `spin_release_high_s` at 1,
  linear (`_spin_release_s`); only the coefficient moves, the state
  integrates, so an energy change never steps the motion. Effect default
  **0 / 0 = bypass**, today's motion to the frame for every other Radial
  scene; STAR's Matrix entry carries **0.45 / 0.2** (`STAR_SPIN_RELEASE_
  LOW_S` / `_HIGH_S`, written by `scripts/star_spin_smooth_scene_data.py`,
  DJ applies at deploy). The release state `_spin_lp` seeds on the first
  governed frame and is dropped when both params are 0.
- **The analysed law IS the shipped law.** The scout rig's `GovState`
  (`data/star-spin-smooth/scripts/motion.py`) and the real effect agreed
  to 1e-11 deg over the page's passages; `tests/test_star_spin_smooth.py`
  replays the same arithmetic against the effect to 1e-12. Measured at
  the page's 0.3 s fixed release: rms jerk -85..90%, peak acceleration
  27-49 -> 4.6-8.4 rev/s², mean speed within 3% at spin 0.70, a single hit
  surges +70% with a 300 ms half-life. The final energy-paced numbers are
  in `data/star-spin-smooth/plan.md` ("Final law, measured").

Proofs: `tests/test_star_curve.py` (the halving, the curve's dwell shares, `cosine` bit-identity, the seeding) and `tests/test_star_spin_smooth.py` (the per-frame clamp at any dt,
release 0 = ease+clamp alone, the law to 1e-12, burst spread with the turn
kept, energy linear / snappier-lazier / never a step, the data script, the
registry). Help topic `star-spin-smooth`.

## WORD SHAPES — the third divisor, and the spin eased to rest (row W1.6, 2026-11-15)

His words for the row: *"STAR: change the radial shape so it matches the
shape if possible. This one might be excluded or need some thought"*, and
his Q7 A: *"include — the outline morphs into the shape, the spin eases to
a stop so the shape stands upright, resumes on release."* Load
`.claude/skills/word-shapes` first — it is the binding statement of the
library, the six told keys and the engine contract above them. Star is in
`fx.device_model.WORD_SHAPE_EFFECTS`; one registered param,
`word_shape_size` (0.62); no `WORD_SHAPE_FORM_MIN_S` entry (STAR takes the
approved Energy-paced 0.5-0.9 s form). The WORD SHAPES block comment above
`DEFAULT_WORD_SHAPE_SIZE` in `fx/effects/radial.py` is the binding
statement.

**ITS HOLD IS STRETCHED ×1.5 (row W4.2, his room verdict 2026-11-17).**
`radial` is in `fx.device_model.WORD_SHAPE_HOLD_X`, so the
`word_shape_hold_s` this effect is TOLD is already 1.2–3.0 s rather than
0.8–2.0 s — "star and black hole look pretty good, but could last a
little longer". Nothing in this module changed: it runs whatever hold it is
told (`.claude/skills/word-shapes`, THE HOLD STRETCH).

Eight things not visible cold:

- **IT IS A DIVISOR, IN THE BLEND THE EFFECT ALREADY HAD.** Star's picture
  is the source strip sampled at a shaped radius `u = r / (max_radius x
  div(angle))`, the `u = 1` contour IS the visible outline, and the effect
  already blends two divisors on an `edges` change (`shape_morph_s`,
  harmonically, because `r / div` is what blends linearly). The shape is a
  THIRD divisor in that same blend: `div_shape(psi) = SIZE x polar(theta_n)
  / (max_radius x k(psi))`. It is a function of the **screen** angle, not
  Star's rotating frame, so the polygon keeps turning under it and **the
  shape stands upright** whatever Star was doing when the word arrived.
  Placed on STAR'S OWN centre (`cx`, `cy`) with the canonical normalized
  denominators (`ax = (r_width - 1) / 2`, `ay = (r_height - 1) / 2`) — the
  check script measures the same placement, so the two can never disagree.
  Two code paths carry the one law and are proven equal to each other and
  to the library: the per-cell field (`_word_shape_shaped`, cached per
  shape and size — a holding shape costs one divide a frame) and the
  angle-space divisor (`_word_shape_div`, which `_shape_div(phi, theta)`
  feeds so a lull piece and a transition program ride the shape too).
  **"Upright" here means NOT SPINNING, not which way up.** The library's
  own default orientation became a 180-degree half turn on 2026-11-18
  (row W5.7, `word_shapes.PANEL_ROTATION_DEG`; his verdict was that the
  shapes read upside-down on the crystal), and nothing in this module
  changed: the divisor is still read at the SCREEN angle, so the shape
  still comes to rest rather than turning with the polygon — it simply
  rests the other way up in the FRAME, which is upright on his panel.
- **THE DIVISOR ALONE IS NOT THE SHAPE — THE EDGE IS HALF THE WORK.** `u`
  keeps rising past 1 and the strip REPEATS (`twist_index % 1.0`), so a
  divisor on its own leaves the whole panel lit and the shape is an
  iso-contour rather than a shape; the plan's "95% of the lit cells lie
  inside the shape" is unreachable that way. So a soft CUT sweeps inward to
  exactly `u = 1`, feathered over `WORD_SHAPE_EDGE_U` (0.09 u, about one
  cell pitch at the default size). **It is paced by CELLS and falls
  GEOMETRICALLY** — `u_cut` is the `share ** m` quantile of this frame's
  own `u` field. Both halves were measured, not guessed: a cut swept
  linearly in `u` held still for half the form and then took two thirds of
  the panel out in six frames, and an even share of the CELLS still spent
  15% of the lit cells in one frame at the envelope's steepest, because
  what reads as a jump is the RELATIVE change in what is lit. The
  cells-not-radius half is the RingFormer's own lesson re-learnt (see "Into
  Star" below). Nothing INSIDE the outline is ever touched.
- **THE ROTATION GOVERNOR EASES THE TURN TO ZERO.** `_govern_rotation`
  scales the whole governed advance by `1 - m` — the audio spin, the base
  floor and anything else that moved the pattern this frame, together — so
  the turn fades out over the form, is EXACTLY zero through the hold and
  comes back from the music over the release. Applied AFTER the release
  low-pass on purpose: the filter's state keeps integrating the music's own
  advance while the shape stands, so the resume is the song's current speed
  rather than a lag, and `m = 1` is a true zero rather than a decaying
  tail. **A PHASE TAKES THE GOVERNOR BACK**: a shape is never TOLD during a
  charge, lull or drop (P3 A, the engine's gate), but one can ARRIVE
  mid-shape, and then the phase's own choreography owns the motion
  unscaled. **A stopped spin on STAR is not always the shape's doing** — a
  scene fire's `random_sign` roll on `spin` used to resolve to 0 about half
  the time (fixed in `binding_resolver`, "THE STAR IMPROVE PLAN" above):
  assert against the governor, never against the roll.
- **THE STAR WAVE IS HELD, BY FREEZING ITS PHASE.** `_star_wave_step` stops
  advancing `_wave_phase` while a shape stands and still recomputes
  `self.star` from it, so a config write landing mid-shape (which re-reads
  the stored `star`) cannot step the picture either; it carries on from the
  same point on the release.
- **AN EDGE MORPH ARRIVING MID-SHAPE IS DEFERRED TO THE RELEASE.**
  `config_updated` holds the new `edges` in `_shape_edges_defer` and leaves
  `self.edges` alone; `_shape_apply_deferred_edges` starts the ordinary
  `shape_morph_s` glide as the release begins (also on a clearing write, on
  reset and on `deactivate`), so the release morphs back into the NEW edge
  count. Applying it at the hold would be a step nobody sees followed by a
  second morph on the way out.
- **THE SEQ IS STRICTLY INCREASING, NOT `+1`** (Word Shapes row W4.1,
  2026-11-17). `_shape_seq` edge-detects the told SEQ as it always has, but
  the counter is now one clock-seeded source for the whole SpotFX process
  (`fx/effects/word_shape_keys.next_seq`) rather than a per-engine 1, 2, 3 —
  which is what made every preview lap after the first write the same 1 and
  draw nothing. So two words back to back give seqs that are strictly
  greater, never consecutive: assert `seq2 > seq1`, never `seq1 + 1`, and
  never assume a first write is 1 (a persisted 1 on a fresh instance is
  exactly the creation baseline that must NOT fire).
- **WHAT WRONG LOOKS LIKE.** A shape that spins is the governor not being
  reached (a phase armed, or `_shape_m` stuck at 0 because the SEQ never
  edged). A heart with bands sliding across it rather than out through it
  is the band scroll stopped — that is the strip's, and Melt is never
  touched by this row. A lull landing mid-shape cuts the SHAPE's rim inward
  (lull B's cut rides the same blended field) and its pieces fall along the
  shape too; a drop on a half-formed shape blooms from whatever outline is
  standing, then the release finishes under it. Nothing in this row ever
  writes a told key back.
- **THE CLARITY BAR AND WHY ONE NUMBER IS READ DIFFERENTLY.** Measured by
  `scripts/check_star_word_shape.py` on his real `crystal-mapper` mask, all
  three shapes at Energy 0.2 and 0.8, at the word and at mid-hold: lit
  cells **inside the shape 97.1-100%** (bar 95%), the outline within
  **0.000 cells** of `SIZE x polar(theta)` on 360 angles (bar half a cell)
  with the rendered field within 1.3e-06 of the same law, **no white**, and
  **+0.22 ms** p50 per frame with a shape holding (bar 1 ms). Two numbers
  are honest deviations, both printed by the script rather than moved:
  * **"90% of the shape's area cells are lit" is read against the cells
    the STRIP lights** (97.3-100%). Star has no light of its own: a dark
    band of Melt is a dark band of the heart exactly as it is a dark ring
    across the panel today, and Melt's own lit share swings between about a
    third and three quarters. The absolute figure (32-45%) tracks the
    strip's own share to within a point or two and is reported, not
    asserted.
  * **the 8%-per-frame "nothing jumps" bar is not reachable on STAR** and
    the script says so with the arithmetic: the rest state lights the WHOLE
    panel and a shape is a fifth to a third of it, so the form must take
    the lit count from ~745 real cells to ~172 inside its own length, and
    at the crystal's 30 fps a 0.5 s form is 15 frames (0.92 ** 15 = 0.29).
    Measured with the strip FROZEN (so the only moving thing is the shape):
    **6.9-14.4% at 60 fps, 9.4-25.4% at 30 fps**, against the effect's own
    UNTOLD worst of 18.2% / 26.6% — Melt's breathing alone moves the lit
    count that much with no shape anywhere. What does hold, and is
    asserted: the hold does not move at all (0.0%, and the pattern's
    advance is exactly 0), and no frame of a form or a release is worse
    than the effect's own untold worst. The lever if he ever wants the
    ramp gentler is a `WORD_SHAPE_FORM_MIN_S` entry for `radial` — a
    change to the timing he approved, so his call, not this row's.

Proofs: `tests/test_star_word_shape.py` (untold byte-identity against the
PINNED module hosted beside today's in the same room on the same strip,
with the `random_sign` spin roll both ways and at its historical zero; the
form completing on the word at 0.5 s and 0.9 s; the clarity bar; the
governor's curve frame by frame and a charge taking it back; the wave held;
the deferred Edge Morph; the band scroll still advancing; two words back to
back, a second inside the release, a clearing write, a stale SEQ, an
unknown id; the wiring). Evidence:
`.venv/bin/python scripts/check_star_word_shape.py [--ascii]`.

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
`test_radial_background_recovers_after_a_warp_ends`). History: docs/agents/fx-effects.md's
"Radial (STAR) rotation is audio-lows-driven" section, `fx/VENDOR.md`
#22, #62.
