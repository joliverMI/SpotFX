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

## A flare in the lull's dark punches through (2026-10-11, strip phase plan phase 5)

His approval: Squiggles takes the same flare punch as the strips. The dark
here is the thinning down to no chains and a cleared panel, so a punch
(`_punch_step`, the module's "a flare in the lull's dark punches through"
block) answers with `PUNCH_CHAINS` (4) fresh chains from the silhouette and
reopens spawning for its length; those chains are TAGGED (`c["punch"]`):
never counted by the thinning (`_lull_chain_count`) or fizzled
(`_fizzle` picks among the lull's own chains only — with none tagged it
draws exactly the same random numbers as before), shown at the punch's
level, and dropped once it has released (or kept as ordinary chains if a
drop lands under them). In the dark the whole frame is scaled by the level
(their sparks too); while darkening the colour slide gives way by the
level. The thinning keeps running underneath, so the release lands where
the lull has got to.

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

## Thematic transitions (2026-10-11, transitions-drop plan phase 3)

Squiggles feeds an Infall into the Black Hole (`_handoff_snapshot` carries
each head's `vx`/`vy` — its last lattice move at `base_speed`, via
`_head_velocity` — and `gesture: "spark"`) and receives the Black Hole's
Eruption: `_formation_points()` is the chain heads, read live, so the
ejecta implode onto heads that are walking. A fresh Squiggles with no
chains yet (silent audio) has no heads: the ejecta then simply fade.
`fx/effects/transition_program.py`'s docstring is the binding statement; `tests/test_transition_programs.py` measures it on the real pipeline.

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

## Unravel (2026-10-11, transitions-drop plan phase 4)

Squiggles -> Orbits / Fish: each chain's path cells (read off `self.chains`
at the switch) become dots released tail-first over 0.45 s, each leaving
along the chain's own path at `base_speed`, imploding onto the incoming form.
Orbits -> Squiggles is also UNRAVEL in reverse: the cloud converges onto
the live chain heads (`_formation_points()`); a Squiggles with NO chain yet
(it walks none until a beat) is SEEDED through its own `_adopt_handoff`
with a few chains at the brightest pieces (TargetFormer._seed). **Fish ->
Squiggles is SHOAL BREAK, not Unravel** — each fish shatters into
`DOTS_PER_FISH` scattered dots (`ShoalBreakProgram._release`) that then
implode onto Squiggles' own chain heads via the same `_formation_points()`/
`_adopt_handoff` seeding; it shares the FORM step with Unravel but not the
release.
`fx/effects/transition_cloud.py`'s docstring is the binding statement for phase 4's programs; `tests/test_transition_programs_phase4.py` measures them on the real pipeline.

## A CHAIN PUBLISHES THE WAY IT IS ACTUALLY GOING (2026-10-17)

The Admiral, on the shoal-burst plan: "The bursts don't seem to carry the
directional velocity of the squiggles. Some look like they go the opposite
direction." He was right, and the cause is the lattice, not the release.

- The six ring directions sit at -135/-90/-45/45/90/135 degrees — **there is
  no horizontal move** — so consecutive gaps are 45/45/90, and every move
  INSIDE one segment is the same slot. So the LAST lattice move points up to
  45 degrees off the way the chain is going, and the first move of a fresh
  segment (`_walk_one` turns one slot at a segment boundary, and a +-1 turn
  across one of the two 90-degree gaps really is 90 degrees) can be 90 out.
  `_head_velocity` published exactly that one move.
- **`_head_motion(c)`** is the fix: the walk direction averaged over
  `_walk_span()` = one whole SEGMENT PAIR (`2 x step_size` lattice moves) at
  the chain's walking speed, plus the turn rate from how that heading changed
  over the span before it — published as the snapshot's
  `walk_vx`/`walk_vy`/`walk_om`, **BESIDE the unchanged `vx`/`vy`, not
  instead of them**. `_head_velocity` is still the
  single lattice move, because that pair is a contract four transition
  programs release from and three effects (blackhole, fireworks, fish) adopt
  on an ordinary crossfade, and none of them was in the shoal-burst plan's
  scope (the Admiral: "for scope, dont do B"). Only
  `transition_program._program_objects` — the host frame's own object set —
  reads the walk keys, which is what keeps every tier-B pair out of
  Squiggles byte-identical.
- **`_step_smooth_head` / `_smooth_head`** — a second, SMOOTH head for
  anything that RIDES a chain rather than draws it (the host frame). The real
  head stands still for two or three frames and then jumps a whole cell:
  invisible when drawn as a path, judder in a direction the parent never went
  when a cloud rides it. The smooth point dead-reckons along `theta` at the
  walking speed (right from the first frame, before the head has moved at
  all) and is pulled onto the real head over `HEAD_CORRECT_S`, snapping past
  `HEAD_SNAP_PX` (a turn-around reverses the path). `_head_pos` is unchanged
  and is still what `_formation_points` and the collision checks use.
- **`_program_birth` / `_program_hosts`** — a program birth starts one chain
  per released object with its head AT that object and walking the way it was
  GOING. `_adopt_handoff` is UNTOUCHED and still aims an adopted chain at the
  centre of the panel +-30 degrees, which is itself "the opposite direction"
  for anything heading outward — that is the crossfade path, deliberately
  byte-identical. A chain head walks at a fixed speed, so there is no turn
  rate to inherit and no count to restore (`max_chains` is a density cap).

Proofs: `tests/test_shoal_burst.py` (the published heading against the
chain's own travel, with the single-move formula as the control),
`tests/shoal_burst_harness.py`.
