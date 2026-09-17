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

## Params

`iris_size`/`pupil_size`/`gaze_radius`/`gaze_depth`/`spin` shape the
gaze geometry; `flames`/`flame_audio` drive its own independent flame
source (NOT `dancer_flames.py` — eye has no import of that module, this
is a separate implementation); `snap_hold` is the dwell after a snap.
`background_brightness` defaults to 0.0 here (dark canvas by default,
same as Dancer) — there is no `no_background_color` registry flag on this
effect, so an authored background DOES reach the wire, unlike radial/
pacman.

## Sonic reach

No direct param edit — reachable only through an already-attached
`FlareKind` on Eye V2.

## Executable proofs

No dedicated `check_eye_*.py`/`test_eye_*.py` exists yet — a named gap,
not an oversight (see AGENTS.md's rule for adding one when this effect's
behaviour is next touched with enough weight to warrant it). The nearest
proof of the shared machinery this effect uses is
`tests/test_blackhole_orphan_drop_none_crash.py` (the watchdog pattern)
and `tests/test_lead_time_alignment.py` (the transition-anchor system
`particle_handoff` feeds).
