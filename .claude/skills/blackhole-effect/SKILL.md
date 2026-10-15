---
name: blackhole-effect
description: >
  fx/effects/blackhole.py (Matrix, crystal-mapper) and fx/effects/
  blackhole1d.py (Strips) — the particle-infall/explosion effect behind
  the Black Hole V2 and Black Hole V2 UI scenes. Load before touching
  either module, before tuning reverse/charge/lull/drop behaviour on this
  effect, or before reasoning about a "black hole isn't exploding on time"
  or "stuck reversed" style report on either Black Hole scene.
---

# Blackhole / Blackhole1d

Matrix effect renders to `crystal-mapper` — **load the `crystal-hex-grid`
skill first** for anything about spawn radius, coverage, or "is this
visible" on this device; blackhole's own spawn-radius/hex-fill fixes are
downstream of that geometry, not independent tuning.

## Params that mean something other than their name suggests

- `reverse` (toggle, "Reverse Flow", default True on both Matrix and
  Strips): True means blobs flow OUTWARD, False means infall. It is a
  SPAWN-SIDE flag that also picks the sign of every live blob's motion —
  nothing turns a particle already in flight around by itself, which is why
  flipping it used to snap the whole outbound population in one frame. The
  edge is detected in `config_updated` (`_reverse_edge = "fallback" if
  prev_reverse else "eject"`): a **True→False** edge now ARMS a real
  turnaround (`_arm_reverse_fallback`, `REVERSE_FALLBACK_TURN_S`) that
  merges onto the speed curve with no visible step; a False→True edge is
  the outward "eject", still instant by his own ask. **Do not "fix" a
  horizon captive by releasing it** — that was tried (PR #179) and
  reverted the same day (#181): release evicts blobs the flare never moved
  and makes them immortal. The real fix pins a captive to the ring only
  while it's AT the ring (`REVERSE_FALLBACK_RING_TOL`).
- `swirl` ("Swirl", -6..6, default 3.0, registry aspect `shape`,
  `flip_sign`): a SHAPE param, not an audio gain — the sign sets the swirl
  direction and 0 is straight infall.
- `spawn_rate` (0..60, blobs/s), `beat_burst` (0..12, blobs per detected
  beat), `spawn_audio` (0..2), `speed_audio` (0..5): the reactivity family.
  `spawn_rate` is a base rate the live impulse multiplies up
  (`spawn_rate * (1 + spawn_audio * impulse * 3)`), and `speed_audio`
  scales speed by `(1 + speed_audio * impulse * 2)` — the impulse idles
  near 0 during quiet passages, so a "healthy" gain can read as doing
  nothing. See the radial-effect skill's audio-idle note for the general
  shape of this trap.
- `horizon_scale` ("Horizon Size", 0..0.8, default 0.25; 0 disables the
  horizon): the event-horizon radius baseline blobs orbit at instead of
  falling in. Separately, the lull's fill stops at the crystal's own
  real-cell boundary — the CONSTANT `HEX_FILL_RADIUS ≈ 1.128`
  normalized-r, not a param — NOT at the addressable rectangle's corner
  (`r_max ≈ 1.49`); growth past the hex covers dead cells only. Measure
  "is the panel dark?" over real cells (device profile mask), never the
  dummy rectangle.
- `horizon_color`: an ACCENT param (`config/effect_params.json`
  `blackhole.params.horizon_color.accent = true`) — forced black by
  `scene_compiler._entry_config` on every compile unless the scene entry
  itself authored a value. Don't assume a scene's stored value here is
  what he tuned; check `accent_param_for` if a scene shows white/wrong
  sparks.
- `background_color`/`background_brightness`: `blackhole` has NO
  `no_background_color` flag (unlike `radial`/`pacman`), and an authored
  black `bg_color` on a colour set is LOAD-BEARING here in Hybrid mode —
  it's what resets the background to black on every fire. Never strip it
  as "redundant" (`docs/SPECTRA_SPEC.md` §72, also referenced in
  AGENTS.md's own prose, has the full colour-bleed proof). The event-horizon
  disc (`Blackhole2d.draw()`'s `out[inside] = ...`) paints literal BLACK,
  not `_bg_color` — painting the background colour there would double it
  against `get_pixels()`'s own overwrite blend (`fx/VENDOR.md` #61).

## Particle-flag vocabulary (don't conflate these two)

- `p_nocap` = "spawned past `max_blobs`" (drop payoff, blob rush, charge's
  forced formation) — read this for density-cap arithmetic.
- `p_is_burst` = "a drop-payoff particle specifically" — read THIS for
  anything measuring the explosion (`PHASE_BURST_SPEED_MULT` keys off it).
  A blob population is Little's Law (`rate × dwell time`), not the
  integral of the spawn rate — measure counts on rendered frames, never
  derive them from the rate curve. A drop's TOTAL visible peak is the
  payoff burst (`_burst_count()` — `PHASE_BURST_N`, or more on a loud TOLD
  drop, see "The drop Shockwave and the breath-hold" below) plus whatever
  the charge/lull just fed the horizon (`p_cap < 0`, captured), not the
  payoff alone — anchor any target ratio on `p_is_burst`, never on the
  total (`fx/VENDOR.md` #38).

## The three-anchor rule for THIS effect specifically

A drop/explosion anchors its START to the trigger mark (never its ramp's
end) — `_response_switch_lead_ms` short-circuits `lead=0` for
`event_class=="drop"` unconditionally. The burst payoff in this module
fires unconditionally on the phase's first rendered frame (the old
`phase_progress ≈ 0.995` gate is gone) to make that lead land visibly.
`DROP_FALLBACK_S` is dead code — nothing waits on `phase_progress`
reaching anything anymore.

## An orphan watchdog crash class lives here

`_phase_step`'s "drop" branch resolves `burst_t` out of a `None` sentinel
— any early `return` inside `_phase_step` (e.g. the charge/lull orphan
watchdog path) MUST happen only after that sentinel is resolved, or
`draw()`'s next call divides `None` and kills the render thread silently
(fixed once, `tests/test_blackhole_orphan_drop_none_crash.py` — the
general pattern to check before touching `squiggles.py`/`eye.py` too).

## The lull's dark point is the SHARED rule, not a constant here

Since 2026-10-07 (the Admiral: "set a max time for that portion to 3
seconds ... 17 seconds of expansion and 3 seconds of dark") this effect's
lull goes dark at the dark point of `fx/effects/lull_dark.py` — dark for
half the lull, never longer than the room's `lull_dark_max_s` (3 s by
default, Sonic-editable via `set_setting`). SpotFX pushes `lull_ramp_s` /
`lull_dark_s` on the lull arm (`scene_response._drive_phase`, only to
`fx.device_model.LULL_DARK_EFFECTS`), and the effect measures the lull on
its OWN seconds-in-phase, never `phase_progress` — a long lull's dark
point sits inside the progress hang, where only a clock can find it. (A
lull after a completed charge used to start its progress at 1.0 and be
released by the orphan watchdog 12 s in; that is fixed for every phase
effect in the shared tween engine, `fx/VENDOR.md` #58, and the watchdog
reads plain progress again.) A write WITHOUT the two keys falls
back to the old `LULL_FILL_PROGRESS` (0.5) — the horizon's fill, the
halo cut-off, the forced-formation stop and the ambient-spawn pause all
read `_lull_timing()`, byte-identical to before. Read lull_dark.py's
docstring before changing anything about when this lull goes dark.

## A flare in the lull's dark punches through (2026-10-11, strip phase plan phase 5)

His approval: the crystal's Black Hole takes the same flare punch as the
strips, "so a flare in a dark room lights everything together". The lull's
dark here is the HORIZON swallowing the panel, so while a punch is open
(`_punch_step`, `PUNCH_RUSH_N`'s comment is the binding statement): the
horizon's fill is pulled back toward its baseline by the punch's level, the
ambient spawn reopens, the lull's explicit halo ring GIVES WAY by the level
(outside a phase there is no halo — lighting it was tried and measured at
~5x the normal panel), and the punch answers with an even rush of
`PUNCH_RUSH_N` (12) blobs from the hex edge so a flare in an EMPTY dark
still shows blobs falling in. Two traps, both measured: the ~200 captives
the lull already swallowed must STAY on the lull's ring while the horizon
is held back (the infall block holds their radius) — unpinned, they fall
across the panel as a ring brighter than anything the effect draws normally
— and they must still be there afterwards, because the drop releases them
as part of its own burst. Measured: the punch shows ~the normal panel's
light, and the dark is back ~1.3 s after the flare.

SpotFX pokes `flare_punch` (+ `flare_punch_hold_s`) from
`scene_response._punch_lull` only while a lull is armed, only on a virtual
the flare batch actually WROTE to, and only for
`fx.device_model.FLARE_PUNCH_EFFECTS` (every strip phase member plus the
crystal's Black Hole and Squiggles and the Pulse singles) — so a flare kind
that writes nothing here (a Big Fish, a Sauron surge) never punches it, a
Light Show "flares off" virtual is never poked, and a house-withheld lull
reaches nobody. The envelope and its runtime are ONE definition,
`fx/effects/lull_dark.py`'s `punch_envelope` / `FlarePunch` (the strips use
the same object): up in 40 ms, held max(`flare_punch_min_hold_s` 0.5, the
flare's own hold), released over `flare_punch_release_s` (0.8 s); "Flare
punch" (`flare_punch_strength`) 0 restores the dark winning, for one scene
entry. All three settings are registered (help topic `flare-punch`), so
Sonic reaches them with `set_scene_entry_param`. The lull's timing never
moves; with no punch open the lull renders BYTE FOR BYTE what it did before
(`tests/test_flare_punch_crystal.py` loads the pre-change module out of git
at a pinned ref). Measure with `scripts/check_flare_punch_crystal.py`.

## The drop Shockwave and the breath-hold (2026-10-11, transitions-drop plan phase 1)

This effect is a member of `fx.device_model.DROP_SHOCK_EFFECTS`. Its drop
gets the shared Shockwave painted by `Twod.render` AFTER its own `draw()`
(`fx/effects/phase_grammar.py` is the binding statement): a rim bloom, ONE
wavefront born on the event horizon's baseline ring (`horizon_scale`), debris (curving back into the infall — 1.6x the shared count, the plan's Black Hole debris boost) and a wall splash, all in the
colour set's own colours, max-composed, never white (his ruling), with this
effect's own frame held dark ahead of the front (`drop_reveal`). The effect
calls `self._shock_begin()` exactly where its own drop payoff fires — never
on a silent watchdog release — and `shock_rim()` names its eye.
The payoff burst itself grows on a loud TOLD drop (`_burst_count`: never below
`PHASE_BURST_N`; untold it is `PHASE_BURST_N` exactly, so the charge
calibration's denominator is unchanged).
Eleven registered settings (`drop_shock` 0 = off, `drop_bloom_ms`,
`drop_color_lean`, `drop_ring_speed`, `drop_ring_width`, `drop_wake`,
`drop_debris_n`, `drop_debris_speed`, `drop_afterglow_beats`,
`drop_reveal`, `drop_shock_scale_min`) are first guesses pending his eye;
Sonic reaches them with `set_scene_entry_param`. The drop arm tells this
effect `drop_intensity`, which scales the debris count and the front's life.
The lull arm also tells it the BREATH-HOLD (`lull_breath_at_s`,
`lull_breath_s`, from the room's `lull_breath_hold_s`, 0.4 s default, always
inside the lull's dark rule): the base render takes the frame to true black
for that window. Help topics `drop-shockwave`, `lull-dark-cap` (the breath-hold is folded into it); proof
`scripts/check_drop_shockwave.py` / `tests/test_phase_grammar.py`.

WHETHER A DROP PAINTS IT AT ALL (2026-10-12, his "toggled per scene, as
well as globally, as well as a global setting for minimum energy"): the drop
arm also tells this effect `drop_shock_on` — the room's `drop_shock_enabled`,
the showing scene's own `drop_shock_enabled`, and the top bar's Energy
(`bridge.intensity()`) against the room's `drop_shock_min_energy` (0.7),
decided by `phase_grammar.shock_allowed`. False = no painter at all: the
frame is this effect's own drop byte for byte (no reveal hold-back either).
Untold reads True. It is an overlay, so nothing in this effect's own drop
changes; `drop_shock` (the per-effect strength) is a separate knob. Help
`drop-shockwave-switches`; proof `tests/test_drop_shock_switches.py`.

## Thematic transitions in and out (2026-10-11, transitions-drop plan phase 3)

A scene change between the Black Hole and Orbits / Fish / Squiggles (and
Fireworks INTO it) no longer rides the 0.5 s crossfade: it runs a
TRANSITION PROGRAM (INFALL in, ERUPTION out). Three things here exist for it:
- **`_handoff_snapshot` carries `vx`/`vy` (px/s) + `gesture: "unwind"`**,
  read off `_program_field_velocity(px, py)` — the ONE definition of "what a
  blob at this position does next" (fall `v(r)` + swirl, or the horizon
  ring's own `omega_h` at and inside `rh`). The infall program blends its
  cloud into exactly this, so keep it in step with `draw()`'s motion.
- **THE ADOPTION FIX: a cross-type adopt whose snapshot carries `vx`/`vy`
  CONTINUES that velocity** (`p_ivx`/`p_ivy`, normalized units/s, NaN =
  none; `_blend_inherited`, blended into the field over `handoff_ease`)
  instead of `p_vr = 0` + the global wind-up from zero. A snapshot without a
  velocity (pacman, dancer, radial, eye...) keeps the old wind-up. Measured:
  speed at the hand-off 30 px/s -> 30 px/s, the control 30 -> 0.7.
- **`snap["append"]`** adopts AFTER the population already spawned (the
  program's hand-off — the Black Hole has been running under it); every
  other adoption replaces, as before.
`fx/effects/transition_program.py`'s docstring is the binding statement; `tests/test_transition_programs.py` measures it on the real pipeline.

## The STRIP (`blackhole1d`) draws its phases through the strip phase layer

Since 2026-10-11 (strip phase plan phase 2; `fx/effects/strip_phase.py` is
the binding statement, `fx/VENDOR.md` #72 the deviation, #74 the plumbing fold) the strip's
charge/lull/drop LOOK comes from the shared strip layer, not this module:
a hue-kept colour gain, a set-colour fill, the drop's set-colour shockwave,
the lull's fade to black at the room's dark point, and a white guard on
charge and drop. His calls: the charge is a TINTED PALETTE GLOW — the old
white halo flood (`_phase_post`, which ran every strip pixel to near-white)
is retired and must not come back; the lull is black at the dark point
with NO grey phosphor dot; the drop begins BRIGHT on its mark (the old
fade up from black hid the burst). What the module still owns, its
character: the charge's forced formation to `CHARGE_SPAWN_RATE_MAX`
(24/s) past the cap and the faster fall; the formation tapering through
the lull's approach and stopping (ambient spawn too) at the layer's OWN
dark point — read `_strip_phase_lull()`, never a progress fraction; the
drop burst sized by `drop_intensity` (12 → 36, ~32 at 0.85); a 6-blob
ring burst when a flare punches through the dark (`_strip_phase_on_punch`,
none when "Flare punch" is 0). PLUMBING (since plan phase 3): the module
keeps NONE of its own — no edge detection, no watchdog, no self-reset.
The layer calls `_strip_phase_enter(phase, prev, released)` on each edge
(the charge saves `reverse`, the drop arms its burst for the first
rendered frame, "none" puts `reverse` back; a watchdog release is the old
silent sweep back) and resets the key after `STRIP_PHASE_DROP_S`
(`DROP_RESET_S`). The phase is `self._sp_phase` — there is no `_phase`.
`config_updated` must not call `super()` (AGENTS.md's strip phase
section). At strength 0 the strip renders the same bytes as before the
fold, watchdog included (`scripts/check_particle_strip_phase.py`). The
2-D Matrix module is untouched by all of this.

## Sonic reach

Sonic reaches any registered param's CURRENT value on one scene's one
device entry through `get_scene_entry_params`/`set_scene_entry_param`
(since 2026-10-06), validated against `config/effect_params.json` — that
includes the strip's strip-phase tunables (`charge_fill`,
`charge_brightness`, `charge_activity`, `lull_activity`, `lull_ember`,
`drop_shockwave`, `drop_brightness`, …, `flare_punch_strength`), which are
registered on `blackhole1d`. Flare kinds go through `set_flare_kind`.

## Executable proofs

`tests/test_lull_dark.py` (the dark-point rule and this effect's lull on
the real pipeline). The strip on the strip phase layer:
`scripts/check_blackhole_strip_phase.py` (before/after on his own Black
Hole V2 strip entry, the pinned pre-change module as red control) +
`tests/test_blackhole_strip_phase.py`; the strip's drop onset on rendered
frames: `scripts/check_drop_visible_onset.py`; the plumbing fold:
`scripts/check_particle_strip_phase.py` + `tests/test_particle_strip_phase.py`.
`scripts/check_blackhole_charge_lull.py`, `check_blackhole_charge_target.py`,
`check_blackhole_explosion_and_gap.py`, `check_blackhole_explosion_speed.py`,
`check_blackhole_hex_spawn.py`, `check_blackhole_reverse_fallback.py` +
matching `tests/test_blackhole_*.py`. The disc's single-application
background is proven in `tests/test_matrix_overwrite_background_double_apply.py`
(`test_blackhole_disc_*`). Full history: `AGENTS.md`'s "Black
Hole" section and `fx/VENDOR.md` deviations #12, #14, #18, #19, #20, #38, #61, #70, #73.

## Lensing / Fountain / Flame Lick / Ignition (2026-10-11, phase 4)

No new Black Hole code: phase 3's `_program_field_velocity` and the APPEND
adoption with an inherited velocity are what LENSING (Fireworks -> Black Hole,
replacing that Infall row) and a FLAME LICK into the Black Hole hand over to.
Black Hole -> Fireworks is FOUNTAIN (the ring unwinds outward and sprays);
Black Hole -> Sauron / Eye is IGNITION (the ring unwinds into a vortex onto the
iris rim — no flash).
`fx/effects/transition_cloud.py`'s docstring is the binding statement for phase 4's programs; `tests/test_transition_programs_phase4.py` measures them on the real pipeline.
