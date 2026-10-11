---
name: squiggles-effect
description: >
  fx/effects/squiggles.py (Matrix, crystal-mapper) — the segmented worm/
  chain effect behind Squiggles V2. Load before touching drop-burst
  timing, the thinning-out lull, background handling (his own reversal on
  this specific effect — docs/SPECTRA_SPEC.md §85 then §87), or the
  `reverse` toggle's release path.
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

## The lull THINS OUT (2026-10-11) — the CRT switch-off is gone

His pick on the transitions/drop plan: "I like A. Use that one" (option A,
"Thinning out"; the old-TV squash to a line and the held WHITE dot were a
one-time gag in no colour set's colours). The lull, all in squiggles.py's
"the lull: thinning out" block:

- THE ENTRY IS EASED: for `lull_entry_s` (1.0 s) the normal flow carries
  on while spawning eases out (`1 - smoothstep`), nothing fizzles and the
  colour has not moved, so the lull's first frame changes no more than an
  ordinary frame (the plan's own complaint about its first sketch was
  "jarringly abrupt").
- No chain is born after the entry. The rest FIZZLE ONE AT A TIME (a random
  one, into a small boom of `FIZZLE_SPARKS` in its own colour) on a
  SCHEDULE: `ceil(n0 * (1 - u) ** lull_fizzle_rate)`, `n0` the population
  when the thinning starts, `u` 0 -> 1 across a window on the approach
  (`_thin_window`: from the entry's end, capped at 0.35 of the approach, to
  `FIZZLE_LIFE_S` before the dark point, capped at 0.2). The schedule is
  what keeps a long lull populated: walls stay solid in a lull, and a
  walled room with no spawning collides itself out in ~8 s, so a head-on
  meeting during the thinning booms only by chance
  (`lull_arc_rate * (1 - u)`), never more than one boom ahead of the
  schedule and never onto the last chain (`_arc_allowed`); otherwise the
  two pass through each other. Outside the thinning every head-on meeting
  booms as always (`self._arc is None`, no rng drawn).
- The colour slides to the set's DARKEST stop (`_dark_stop`, by luminance
  on the current gradient) by `lull_color_slide * entry * smoothstep(
  approach)`.
- THE DARK RULE IS THE LAW: from the dark point the chains and sparks are
  cleared and the frame is black.

The dark point itself is still the SHARED rule (next section). An untold
lull (no `lull_ramp_s`) falls back to `LULL_LEGACY_DARK_AT` (0.55, the old
CRT_SPLIT) of the progress ramp, or `LULL_FALLBACK_S` of wall clock while
progress sits at 0, and thins over `LULL_UNTOLD_THIN_FROM/TO` of the
approach. All four `lull_*` settings are registered (Sonic reaches them).
Outside the lull the effect is the predecessor bit for bit
(`tests/test_squiggles_lull_thinning.py` loads it out of git).

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
reads plain progress again.) Read lull_dark.py's docstring before
changing anything about when this lull goes dark.

## The drop after a lull lands on REAL cells — a chain never changes
   parity

Every ring move (`fx/effects/lattice.py` RING) keeps a cell's
(col + row) parity, so a chain walks ONE sublattice for its whole life and
`step_size` cannot change that (the plan's "odd stride" suspicion was
wrong). The plan found the drop's fan lighting 0 real cells after a lull:
its rig had no shape map, the lattice fell back to an all-live rectangle,
and the fan born at the panel centre (35.5, 18) snapped to (36, 18) — the
DEAD parity on his crystal — so every burst chain walked the dead cells
(without a lull, edge-spawned chains of both parities hid it). His live
crystal-mapper carries a shape map, so the room takes the real-shape path;
the fallback now reads the real cells off the virtual's own gap segments
(`lattice._segment_mask`, the render path's own gap rule, `fx/VENDOR.md`
#69), which is what offline rigs and any virtual whose shape map is
missing get. Proof + red control (the fallback removed reproduces 0 real
lit): `tests/test_squiggles_lull_thinning.py`.

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
the real pipeline), `tests/test_squiggles_lull_thinning.py` (the thinning
lull, the drop after it on real cells, bit-for-bit outside the lull),
`tests/test_fireworks_melds.py` (the cut-frame adopt).
`scripts/check_squiggles_drop_timing.py`,
`tests/test_squiggles_drop_timing.py`,
`tests/test_squiggles_colorset_widen.py`. The accept-list migration,
`scripts/widen_squiggles_colorset_accept.py`, is scene data and belongs to
the squiggles-v2-scene skill. History: `docs/SPECTRA_SPEC.md` §85, §86, §87
(also referenced in AGENTS.md's own prose), and AGENTS.md's "A saturating
signal meeting >=" section (check `min_volume`/
`burst_threshold`-shaped gates on this effect against that pattern before
adding one).
