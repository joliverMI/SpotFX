---
name: squiggles-effect
description: >
  fx/effects/squiggles.py (Matrix, crystal-mapper) — the segmented worm/
  chain effect behind Squiggles V2. Load before touching drop-burst
  timing, background handling (his own reversal on this specific effect —
  §85 then §87), or the `reverse` toggle's release path.
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

§85 added `no_background_color` to squiggles after measuring a bright
authored background flooding ~100% of a real headless render. §87
reversed it on his own ruling: "keep the backgrounds, i want to control
them with overrides" — made possible once colour-GROUP overrides were
proven to actually reach the wire (three choke points were silently
discarding them before that fix, AGENTS.md §86). If a Squiggles colour-set
accept list looks narrow, check that flag's CURRENT state and the group-
override machinery before assuming either is broken — squiggles' widened
accept list (`accept_all_sets=True`, §85) is untouched by the background
reversal and independent of it.

## A momentary/permanent kind targeting `reverse` needs a real bool

`reverse` is a toggle-type param — `ParamTarget.value` is a plain float
field, so an authored `true`/`false` silently coerces to `1.0`/`0.0`
unless `scene_response._compute_param_moves` coerces it back to a real
`bool` (fixed for blackhole/orbits/squiggles together, PR
fm/momentary-reverse-flare-on-black-hole-orbits-squiggles — see
`config/effect_params.json`'s `KIND_TOGGLE` handling). The release side
needed the SAME fix: a toggle baseline had to start being tracked in
`param_baseline`/`_carried_value` (both used to explicitly exclude bools
as "NUMERIC baselines only"), or a momentary release could never resolve
where to return to.

## The charge/lull/drop orphan-crash pattern applies here too

Same shape as blackhole's watchdog crash: any `return` inside
`_phase_step` must happen AFTER a sentinel it just set is resolved to a
real value, not before. `squiggles.py` is named in AGENTS.md's list of
modules sharing this state-machine shape (alongside `eye.py`).

## Sonic reach

No direct param edit — reachable only through an already-attached
`FlareKind` on Squiggles V2.

## Executable proofs

`scripts/check_squiggles_drop_timing.py`,
`scripts/widen_squiggles_colorset_accept.py`,
`tests/test_squiggles_drop_timing.py`,
`tests/test_squiggles_colorset_widen.py`. History: AGENTS.md §85, §86,
§87, and the "A saturating signal meeting >=" section (check `min_volume`/
`burst_threshold`-shaped gates on this effect against that pattern before
adding one).
