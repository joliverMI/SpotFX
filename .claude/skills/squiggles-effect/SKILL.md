---
name: squiggles-effect
description: >
  fx/effects/squiggles.py (Matrix, crystal-mapper) — the segmented worm/
  chain effect behind Squiggles V2. Load before touching drop-burst
  timing, background handling (his own reversal on this specific effect —
  docs/SPECTRA_SPEC.md §85 then §87), or the `reverse` toggle's release
  path.
---

# Squiggles

Matrix effect renders to `crystal-mapper` — load `crystal-hex-grid` first.

## Drop burst is START-anchored (his settled 3-anchor rule), NOT the
   original end-anchored fix

History matters here so a future "fix" doesn't flip-flop it back: his
FIRST report was "squiggles needs to explode right on the trigger," fixed
by mirroring Black Hole's THEN-good end-anchored gate
(`phase_progress ≈ 1.0`). Black Hole was later tried and WITHDRAWN as a
timing reference; he settled a three-anchor rule instead — momentary
flares anchor their switch's END, scene transitions anchor their MIDDLE,
drops/explosions anchor their START. Squiggles' burst now fires
unconditionally on the phase's first rendered frame (the old
`phase_progress` gate removed), proven with BOTH a ramped and a
STALLED `phase_progress` (a lost ramp can't delay it — there's nothing
left to wait for). Reversing this specific mechanism a second time
without a fresh ask from him would be the flip-flop this history exists
to prevent.

## `no_background_color` was set, then explicitly REMOVED — his call, not
   a defect fix

`docs/SPECTRA_SPEC.md` §85 (also referenced in AGENTS.md's own prose)
added `no_background_color` to squiggles after measuring a bright authored
background flooding ~100% of a real headless render. §87 reversed it on his
own ruling: "keep the backgrounds, i want to control
them with overrides" — made possible once colour-GROUP overrides were
proven to actually reach the wire (three choke points were silently
discarding them before that fix, `docs/SPECTRA_SPEC.md` §86). If a Squiggles colour-set
accept list looks narrow, check that flag's CURRENT state and the group-
override machinery before assuming either is broken — squiggles' widened
accept list (`accept_all_sets=True`, §85) is untouched by the background
reversal and independent of it.

## A momentary/permanent kind targeting `reverse` needs a real bool

`reverse` is a toggle-type param ("Flip travel: every chain turns around
and retraces its path") — `ParamTarget.value` is a plain float field, so an
authored `true`/`false` silently coerces to `1.0`/`0.0` unless
`scene_response._compute_param_moves` coerces it back to a real `bool`
(fixed for blackhole/orbits/squiggles together, PR
fm/momentary-reverse-flare-on-black-hole-orbits-squiggles). That handling
lives in `spectra/services/scene_response.py` (its
`binding_resolver.KIND_TOGGLE` branches); `config/effect_params.json` only
declares the param's `"type": "toggle"`. The release side
needed the SAME fix: a toggle baseline had to start being tracked in
`param_baseline`/`_carried_value` (both used to explicitly exclude bools
as "NUMERIC baselines only"), or a momentary release could never resolve
where to return to.

## The charge/lull/drop orphan-crash pattern applies here too

Same shape as blackhole's watchdog crash: any `return` inside
`_phase_step` must happen AFTER a sentinel it just set is resolved to a
real value, not before. `squiggles.py` is named in AGENTS.md's list of
modules sharing this state-machine shape (alongside `eye.py`).

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
back to `CRT_SPLIT` (0.55) and pauses spawning for the whole lull. Told,
the CRT squash completes at the dark point, the line pinches to its dot
by the end of SpotFX's ramp (`after`), and ordinary chains KEEP SPAWNING
until the dark point (`_lull_still_lit`, Black Hole's model) — without
that, a long lull's walled-in chains collide themselves out within ~8 s
and the squash has nothing left to squash, byte-identical to before.
Read lull_dark.py's docstring before changing anything about when this
lull goes dark.

## A piece adopted on a HARD CUT skips its fade-in (2026-10-08)

The drop-led switch cuts (`fx/VENDOR.md` #63) — and the fireworks melds
cut Fireworks into Squiggles on the next big hit — leave no outgoing
frames to hide a fade-in behind. `_adopt_handoff`'s generic path starts a
chain adopted from the REGISTRY snapshot (the cut path, `live` False) at
`age = FADE_IN_S`, so the panel does not go dark for ~80 ms while it fades
up (measured: 189 lit cells -> 0 for five frames before; -> 42 on the cut
frame after). A crossfade adoption (`live` True) is unchanged; so is the
radial burst. `fx/VENDOR.md` #64.

## Sonic reach

No direct param edit — reachable only through an already-attached
`FlareKind` on Squiggles V2.

## Executable proofs

`tests/test_lull_dark.py` (the dark-point rule and this effect's lull on
the real pipeline), `tests/test_fireworks_melds.py` (the cut-frame adopt).
`scripts/check_squiggles_drop_timing.py`,
`tests/test_squiggles_drop_timing.py`,
`tests/test_squiggles_colorset_widen.py`. The accept-list migration,
`scripts/widen_squiggles_colorset_accept.py`, is scene data and belongs to
the squiggles-v2-scene skill. History: `docs/SPECTRA_SPEC.md` §85, §86, §87
(also referenced in AGENTS.md's own prose), and AGENTS.md's "A saturating
signal meeting >=" section (check `min_volume`/
`burst_threshold`-shaped gates on this effect against that pattern before
adding one).
