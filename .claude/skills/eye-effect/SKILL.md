---
name: eye-effect
description: >
  fx/effects/eye.py (Matrix, crystal-mapper) — the gaze/blink effect
  behind Eye V2. Load before touching snap_threshold/blink timing, before
  editing the charge/lull/drop state machine here, or before assuming a
  scene transition into/out of Eye doesn't touch particle_handoff.
---

# Eye

Matrix effect renders to `crystal-mapper` — load `crystal-hex-grid` first.

## `snap_threshold` has the SAME saturating-`>=` defect as Dancer's
   `burst_threshold` — reported, NOT fixed

`fx/effects/eye.py:574`: `imp >= self.snap_threshold` gates the "big hit,
dart to a random ring position" snap, and `imp` is one of this pipeline's
clipped-to-1.0 audio signals that converges to exactly 1.0 in float within
~150ms of a loud passage. With `snap_threshold` at its Range max (1.0,
meaning "never snap"), it fires anyway. Left unfixed on purpose (captain's
call, not an oversight) — see the dancer-effect skill and AGENTS.md's "A
saturating signal meeting >=" section for the general shape and the one
instance that IS fixed (`dancer.py:1149`), which is the model to follow if
this one is ever picked up.

## It participates in the SAME particle_handoff transition choreography
   as blackhole/blackhole1d

`eye.py` imports `fx.effects.particle_handoff` and reads
`particle_handoff.transition_progress(virtual)` /
`particle_handoff.BLOOM_START` / `PACMAN_MORPH_START` (both 0.45, the same
fork constants `spectra/services/transition_phases.py` mirrors for scene-
transition anchor timing — AGENTS.md's "SPECTRA transition-timing
alignment" section). A blink/erupt hold on this effect is gated on how far
a scene transition INTO or OUT OF Eye V2 has progressed — touching either
side of a transition into/out of this scene without checking
`particle_handoff`'s own state machine here risks a stuck blink/erupt
hold (`_erupt_hold`/`_blink_in`, each carrying its own `t0` +
`*_HOLD_MAX_S` bail-out).

## The charge/lull/drop orphan-crash pattern applies here — and this
   module is cited as the GOOD example

AGENTS.md names `eye.py`'s watchdog path as the one that got the
`_phase_step`-sentinel-before-`return` rule right FROM THE START (it sets
a concrete `t: 0.0` directly rather than a `None` sentinel later code must
resolve) — the pattern to copy in any NEW charge/lull/drop state machine,
rather than blackhole's/squiggles' shape which needed a real fix.

## Sauron is a COPY of this effect — a fix here does not reach it

`fx/effects/sauron.py` (2026-10-10, the Eye of Sauron) copied this
module's gaze model, foreshortening, hand-off choreography and
charge/lull/drop state machine verbatim rather than sharing them, so Eye
stays byte-for-byte untouched. A behavioural fix made here should be
weighed for Sauron too (sauron-effect skill) — and the reverse: Sauron
already FIXED the saturating `snap_threshold` `>=` above; Eye has not.

## The lull is UPSIDE DOWN (2026-10-11) — a 180-degree turn, not a flip

His words on the transitions/drop plan, after its revision 3 had read "flip
it vertically" as a quarter turn (lids closing from the sides): "no, i
meant upside down. it's a simple 180 degree rotation." So the lull's lids
are today's lids turned 180 degrees ABOUT THE EYE: the lid geometry is
evaluated at (-dx, -dy) and the panel's bottom edge becomes the turned
frame's top, so the lids meet just ABOVE the eye's centre and curve the
other way; their timing (`_lid_travel`, the pause on the iris), colour and
`_step_lid` are untouched. `_lids_rotated` is set when a lull starts
(`lull_lids_upside_down`, registered, default True) and kept through the
drop until the lids are open again, so the drop opens them the same way
round; a blink-in/out with no lull is the ordinary way round. Off is the
predecessor bit for bit. Sauron does the same (sauron-effect skill).
`lids_rotated` rides the `_handoff_snapshot`'s `native` block alongside
`phase`/`phase_progress`, so a same-type recreation mid-lull (a flare
fallback POST rebuilding the instance) picks up the predecessor's
rotation instead of silently resetting to the un-rotated default —
caught and fixed after the orientation itself shipped, not obvious from
reading `_adopt_handoff` cold. Proof: `tests/test_eye_lull_lids_upside_down.py`
(the closed lull equals today's rot180 on a rectangle, the closing band
mirrored, the drop opening turned, off = the pinned predecessor's frames,
and a same-type hand-off mid-lull carrying the rotation through).

## Params

`iris_size`/`pupil_size`/`gaze_radius`/`gaze_depth`/`spin` shape the
gaze geometry; `flames`/`flame_audio` drive its own independent flame
source (NOT `dancer_flames.py` — eye has no import of that module, this
is a separate implementation); `snap_hold` is the dwell after a snap.
`background_brightness` defaults to 0.0 here (dark canvas by default,
same as Dancer) — there is no `no_background_color` registry flag on this
effect, so an authored background DOES reach the wire, unlike radial/
pacman. The eyelid-covered region (`Eye2d.draw()`'s `out[covered] = ...`)
paints literal BLACK, not `_bg_color` — painting the background colour
there would double it against `get_pixels()`'s own overwrite blend
(`fx/VENDOR.md` #61).

## The drop Shockwave and the breath-hold (2026-10-11, transitions-drop plan phase 1)

This effect is a member of `fx.device_model.DROP_SHOCK_EFFECTS`. Its drop
gets the shared Shockwave painted by `Twod.render` AFTER its own `draw()`
(`fx/effects/phase_grammar.py` is the binding statement): a rim bloom, ONE
wavefront born on the iris rim as drawn this frame (`_last_iris`), debris (burning out as flame licks) and a wall splash, all in the
colour set's own colours, max-composed, never white (his ruling), with this
effect's own frame held dark ahead of the front (`drop_reveal`). The effect
calls `self._shock_begin()` exactly where its own drop payoff fires — never
on a silent watchdog release — and `shock_rim()` names its eye.
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

**The Shockwave paints the drop frames, so a test of the lids' own drop
geometry must hold it off** (`drop_shock: 0`), the way
`tests/test_eye_lull_lids_upside_down.py`'s helper does by default — with it
on, its rim bloom lights the rows the lid tests read, and a pinned pre-
Shockwave Eye is no longer bit-identical on the drop. The two coexist: that
file's `test_the_upside_down_lull_and_the_shockwave_coexist` runs Eye and
Sauron with it on and proves the lids open in the identical sequence, turned
the same way round, while the Shockwave changes the drop's light. Eye and
Sauron draw their construction-time state from an UNSEEDED generator, so
two runs compared frame for frame need a seeded construction.

## Sonic reach

No direct param edit — reachable only through an already-attached
`FlareKind` on Eye V2.

## Executable proofs

No dedicated `check_eye_*.py`/`test_eye_*.py` covering this effect's own
behaviour (snap/blink/gaze) exists yet — a named gap, not an oversight
(see AGENTS.md's rule for adding one when this effect's behaviour is next
touched with enough weight to warrant it). The one exception is the
eyelid's single-application background, proven in
`tests/test_matrix_overwrite_background_double_apply.py`
(`test_eye_eyelid_covered_region_applies_background_once_not_twice`). The
nearest proof of the other shared machinery this effect uses is
`tests/test_blackhole_orphan_drop_none_crash.py` (the watchdog pattern)
and `tests/test_lead_time_alignment.py` (the transition-anchor system
`particle_handoff` feeds).

## Flame Lick / Ignition (2026-10-11, transitions-drop plan phase 4)

Same hooks as Sauron (see the sauron-effect skill): `program_rim`,
`_lens_gain` (multiplies the PUPIL radius here), and the handed brightness
(`snap["body_gain"]` -> `_infall["g0"]` / `_fade_up`; 0.25 when none). Eye ->
the particle effects is FLAME LICK, the particle effects -> Eye is IGNITION.
`fx/effects/transition_cloud.py`'s docstring is the binding statement for phase 4's programs; `tests/test_transition_programs_phase4.py` measures them on the real pipeline.
