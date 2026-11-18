---
name: fireworks-effect
description: >
  fx/effects/fireworks.py (Matrix, crystal-mapper) and fx/effects/
  fireworks1d.py (Strips) — the rocket/burst effect behind Fireworks V2,
  and ALSO the Fish scene's Strips entry (live data — see the fish-scene
  skill). Load before touching launch/burst/drop-tail timing, before
  tuning spawn_rate (at 0, beat bursts are the ONLY launch source and every
  spawn_rate multiplier is inert — verify the live value, it drifts), or
  before adding a firework_burst-style flare kind to another scene.
---

# Fireworks / Fireworks1d

Matrix effect renders to `crystal-mapper` — load `crystal-hex-grid` first.

**`fireworks1d` is also the Fish scene's Strips entry** (live data, not
the `orbits1d` that `scripts/seed_fish_scene.py` itself still copies in —
see the fish-scene skill's own note on the divergence). A change to the
strip's phase behaviour, launch rate or lull ember can move two scenes at
once (Fireworks V2 and Fish); check the live scenes
(`GET /spectra/api/scenes`) before assuming a fix is Fireworks-V2-only.

## At `spawn_rate: 0`, beat bursts are the ONLY launch source — check the
   live value before promising a spawn-rate fix

The mechanism: with `spawn_rate` at 0, beat bursts (`beat_burst`) are the
ONLY ordinary launch source, and any `_pspawn`-style spawn_rate multiplier
(including the charge's `CHARGE_SPAWN_X`, `1 + X*p`) multiplies zero and is
INERT. Anything that must visibly add launches then has to be a launch RATE
or touch beat bursts directly — which is exactly why the drop tail is a
rate (`fx/VENDOR.md` #17, "Fireworks drop tail").

Which regime his scene is in is NOT a fixed fact: `seed_fireworks_scene.py`
and the drop-tail notes authored `spawn_rate: 0`, but a read of the live
store on 2026-09-16 showed 0.5 on both entries. **Verify against
`GET /spectra/api/scenes` — this drifts.**

## Density cap: `p_nocap`/`f_nocap` bypass, and why the "big burst then
   nothing" cliff existed

Particles spawned past `max_blobs` (payoff, `firework_burst` flare, drop
tail, beat-burst rockets past the cap) are flagged `p_nocap`/`f_nocap` and
DON'T occupy the cap slot. Before that flag, a payoff held the cap full
for `PAYOFF_LIFE × burst_life` (~2.6s on his crystal) and silenced every
beat burst — the "big burst then nothing" defect. Measure post-drop
density with `scripts/check_fireworks_drop_tail.py` before reasoning about
spawn pacing anywhere near a drop.

## Drop tail: an elevated launch rate that eases back, not a flat return

Right after the payoff an EXTRA launch rate is ADDED on top of the ordinary
show: `DROP_TAIL_RATE * (1 - t/DROP_TAIL_S)` launches/s — linear, additive,
`DROP_TAIL_RATE = 8.0`, `DROP_TAIL_S = 2.5` (`_drop_tail_step`; the same
`DROP_TAIL_S` in `fireworks.py` and `fireworks1d.py`, but the strip's RATE
is 12 since strip phase plan phase 3 — a heavier shower on the strip). It eases to exactly
baseline by `DROP_TAIL_S`, never overshooting below it, and runs on its own
clock (the drop phase itself self-resets earlier, at `DROP_SETTLE_S`). This
covers a drop with NO preceding lull too (no rockets still grows a tail).
An ordinary flare burst (`burst_rockets`) does NOT start a tail — the tail
belongs to the drop specifically; a flare stays the additive volley it
was authored as.

## The STRIP (`fireworks1d`) draws its phases through the strip phase layer

Since 2026-10-11 (strip phase plan phase 3; `fx/effects/strip_phase.py` is
the binding statement, `fx/VENDOR.md` #74) the strip's charge/lull/drop
LOOK comes from the shared layer, and so does its phase PLUMBING (edge
detection, the orphan watchdog, the self-reset after `DROP_SETTLE_S`) —
the module keeps `_strip_phase_enter` (a lull launches its rockets, a drop
explodes them and starts the tail, leaving a lull any other way burns them
out) and a per-frame `_phase_step`. The phase is `self._sp_phase`. Retuned:

- the charge no longer slows or shortens its fireworks (`CHARGE_SLOW`,
  `CHARGE_SHORT` 0);
- his scene's `max_blobs` 6 clipped the charge's launch multiplier to 3
  fireworks in flight, so the charge ADDS an uncapped launch rate rising
  0 -> `CHARGE_LAUNCH_RATE_MAX` (8/s) (the tail's own `ignore_cap` shape);
- the strip's drop tail is 12/s (the crystal's stays 8);
- the lull is not black (his call 3): this effect's own `lull_ember`
  default is `LULL_EMBER` (0.12, its schema via `strip_phase.
  tunable_fields`, its registry entry via
  `registry_params(STRIP_PHASE_DEFAULTS)`), so the rockets cross the dark
  as 12% embers. Their own dimming (`LULL_ROCKET_FADE`) is retired — the
  layer's fade is the one dimmer. (Since 2026-10-12 the Orbits strip has
  its own non-black lull too, its one dim blob at 20% — see the
  orbits-effect skill; the two are independent `STRIP_PHASE_DEFAULTS`.)
- ACTIVITY (`STRIP_PHASE_ACTIVITY`): spawn_rate, beat_burst, burst_speed
  (0.3) — never max_blobs, his density cap.

A Firework Burst flare in the lull's dark is its own punch; nothing else
answers it here. Off-phase frames are byte-identical to before. The 2-D
Matrix `fireworks.py` is untouched.

## `firework_burst` flare kind: it jumps a phase key, it does not schedule

`firework_burst` explodes an intensity-scaled rocket count (3 at intensity
0 → 6 at 1) IMMEDIATELY, by jumping the effect's own `burst_rockets` key
(edge-detected, self-resetting — a phase-key pattern, `fx/VENDOR.md` #15,
deliberately absent from the param registry, gated by
`fx.device_model.FIREWORK_BURST_EFFECTS`). It is deliberately NOT
`beat_burst` — that param only launches on the NEXT beat, so it can never
land on a trigger mark. It has NO release queue (nothing to schedule at
the four drain points) — particles simply age out inside the effect.

## THE KEEPERS MELD — a flagged keeper becomes a payoff rocket (2026-10-08)

The drop-led switch's fireworks melds (`spectra/services/drop_switch.py`,
drop-scene-variety plan phase 3, `fx/VENDOR.md` #64). A Fish/Orbits lull
TOLD it leads into Fireworks (`lull_handoff`'s `lull_next`) flags its
`lull_keep` (3) keepers in its snapshot (`"keepers"`); `_adopt_handoff`
turns each flagged one into a HELD, stationary rocket (`_import_keepers`:
`p_rocket` with no `_rocket_path`, `p_nocap`, at most
`KEEPER_ROCKETS_MAX`) and the drop arm that follows the cut makes
`_rocket_payoff` — the lull rockets' own payoff — explode every one where
it stands, in its own colour, instead of six random near-centre bursts.
Three things not visible cold:

- **No flag, no change**: an unflagged snapshot adopts byte-identically
  to before (proven against the pinned pre-change module). The flag only
  exists when the outgoing lull was told a DIFFERENT effect is coming.
- **Held keepers never hang**: no drop arm within `KEEPER_HOLD_S` (0.6 s)
  and each bursts as an ordinary firework where it stands
  (`_release_keepers`); a lull arriving meanwhile releases them first, so
  `_phase_rockets` (which guides the first N rockets) can never grab them.
- **Order**: `_adopt_handoff` runs before `_phase_step` in `draw()`, so a
  drop arm that lands before the first frame still finds the keepers.

Leaving Fireworks is spectra-side only (a cut 1 s after its own drop into
the Black Hole; on the next big analysed flare into the others) — the
incoming effects' generic adopts take the burst cloud; nothing here
changed for it.

## THE PRE-DROP — rockets fire ON it and burst on the drop (2026-10-27)

Predrop plan step 6 (`fx/VENDOR.md` #87; the drop-detection skill for the
engine). Fireworks is a `fx.device_model.PRE_DROP_EFFECTS` member with ONE
look, `rockets` (`PRE_DROP_LOOK`), for both kinds. Told a pre-drop on its
lull arm, the lull launches NO rockets at its start (it stays dark while
what flew before fades); the breath-hold right before the pre-drop is
TRUE black (`_pre_drop_step` clears particles and trail on its first frame
and swallows a flare landing in it); the ordinary rocket ring fires ON the
pre-drop and flies the gap on the effect's own clock, so it bursts on the
drop (`_rocket_payoff`, unchanged). Three things not visible cold:

- **Untold is today's, frame for frame** — every branch returns before it
  touches state, proven against the pinned pre-look module.
- **The brightness fade is a RATE** (`pre_drop_rocket_fade`: 0.3125/s,
  capped at `LULL_ROCKET_FADE`): a spike's short flight stays bright, and
  a long one (his 2 s spike maximum, a vocal intro) dims like today's, so
  the whole lull's light stays at or below today's on every measured
  lull/gap pair (storyboards below).
- **It takes the breath keys** although it is no `BREATH_HOLD_EFFECTS`
  member: SpotFX tells it a breath only on a lull that plays a pre-drop
  (zeros otherwise).

Proofs: `tests/test_pre_drop_looks.py` (rig `tests/pre_drop_look_harness.py`,
the engine's own lull arm on his crystal's real mask),
`scripts/render_predrop_storyboards.py` -> `docs/evidence/predrop-storyboards/`.

### On the strip (`fireworks1d`, predrop plan step 9, `fx/VENDOR.md` #90)

The crystal's idea on the strip: the Fireworks strip's look is `rockets`
too (its own `pre_drop_looks` block; the shared layer's twinkle is not its
look). Told a pre-drop, `_strip_phase_enter("lull")` launches NO rockets,
the strip goes dark under the layer's fade, `_pre_drop_step` makes the
breath TRUE black (clears particles and trail on its first frame, swallows
a flare burst landing in it), and on the pre-drop the same two rockets
fire from the strip's ends (`_launch_rockets`), guided over the gap by the
layer's clock (`_strip_phase_pre_drop()`), bursting on the drop
(`_rocket_payoff`, unchanged). Two things not visible cold:

- **The layer lifts the lull's 12% ember for the gap**
  (`_strip_phase_pre_drop_lift`), so the rockets fly bright as the
  crystal's do; untold, the lull's two rockets still cross the dark at the
  ember, as before.
- **They dim by the crystal's own rule** (`pre_drop_rocket_fade`, 0.3125/s
  capped at 0.75 — the strip's own lull dimming was retired, so in the lit
  gap this is the one dimmer), keeping the whole lull's light below today's.

## Thematic transitions (2026-10-11, transitions-drop plan phase 3)

Fireworks' `_handoff_snapshot` carries `vx`/`vy` = `p_vx`/`p_vy` in px/s +
`gesture: "spray"`. Since phase 4 its sparks LENS into the Black Hole
(LENSING, not Infall) and the Black Hole FOUNTAINS into it (see below). A DROP-led Fireworks -> Black
Hole switch is still the SWALLOWED meld, untouched. `fx/effects/transition_program.py`'s docstring is the binding statement; `tests/test_transition_programs.py` measures it on the real pipeline.

## Sonic reach

No direct param edit on the 2-D Matrix effect — same rule as every effect
here; reachable only through an already-attached `FlareKind` on Fireworks
V2. The strip (`fireworks1d`) is the one exception: a registered param's
current value on one scene entry is reachable through
`set_scene_entry_param` (since 2026-10-06), which includes the strip's
strip-phase tunables (`charge_fill` … `flare_punch_glow`, registered on
`fireworks1d`) — including its own non-zero `lull_ember` default. The
melds' two room tunables (`drop_switch_swallow_delay_s`,
`drop_switch_hit_threshold`) are settings-registry keys.

## Executable proofs

`scripts/check_fireworks_drop_tail.py`, `scripts/check_firework_burst.py`,
`tests/test_fireworks_drop_tail.py`, `tests/test_fireworks_rocket_angles.py`,
`tests/test_firework_burst.py`, `scripts/check_particle_strip_phase.py`
+ `tests/test_particle_strip_phase.py` (the strip on the strip phase
layer, his own Fireworks V2 strip entry, the pinned pre-change module as
red control), `tests/test_fireworks_melds.py` (the
keepers meld on the real pipeline, the pinned-module byte-identity, the
swallow and implode adopts), `tests/test_pre_drop_looks.py` (the pre-drop
look), `scripts/render_fireworks_melds.py` (offline
GIFs, committed under `docs/evidence/fireworks-melds/`). The scene
migration that attaches the kind, `scripts/add_fireworks_burst_flare.py`
(dry-run default), belongs to the fireworks-v2-scene skill. History:
`docs/SPECTRA_SPEC.md` §89 (also
referenced in docs/agents/fx-effects.md's own prose), `fx/VENDOR.md` #15, #17.

## Lensing / Fountain / Flame Lick into Fireworks (2026-10-11, phase 4)

- **`_import_sparks`** (reached from `_adopt_handoff` when a snapshot carries
  `append` + `vx`): a transition program's sparks join as ORDINARY sparks at
  their positions WITH their velocities, already past their fade-in, each
  `p_bright` set so its first shown frame equals what the program drew (the
  draw's own forward envelope inverted), uncapped (`p_nocap`). Every other
  adoption is exactly as before.
- **`_program_field_velocity(px, py, vx, vy, dt)`**: this field's own drag
  (the draw's half-life). FOUNTAIN (Black Hole -> Fireworks) and a FLAME LICK
  into Fireworks fly their last stretch by it, so the hand-off continues one
  motion.
`fx/effects/transition_cloud.py`'s docstring is the binding statement for phase 4's programs; `tests/test_transition_programs_phase4.py` measures them on the real pipeline.

## WORD SHAPES — the shaped payoff burst (2026-11-16, Word Shapes plan row
   W1.2). Matrix only; the strip gets nothing

His words for the row: *"Fireworks: have a flare style firework (so the ones
that are bigger) explode into the given shape and hang longer than the
others. It should form a slightly more solid outline than the filling, but
it also needs to still appear random."* Q9 A: one big centred shaped burst
per word, ~70% of the sparks on the outline, hanging about twice as long,
bigger at higher Energy.

**Read `.claude/skills/word-shapes/SKILL.md` first** — the shape library,
the six told keys, the envelope and the engine contract above all of this.
`fireworks` is in `fx.device_model.WORD_SHAPE_EFFECTS`; **`fireworks1d` is
NOT and must not be** (there is nowhere to draw a shape on one line), and
the strip's schema does not carry the keys.

**ITS HOLD IS THE ROOM'S OWN AGAIN — 0.8–2.0 s (row W5.6, his SECOND room
verdict 2026-11-18: "It also holds too long").** Row W4.2 had put
`fireworks` in `fx.device_model.WORD_SHAPE_HOLD_X` at ×1.5 (1.2–3.0 s);
W5.6 **took it back out**, leaving `radial` (STAR) and `blackhole` there —
the two he said "look pretty good, but could last a little longer". Nothing
in this module ever stretched the hold: it runs whatever it is told
(`.claude/skills/word-shapes`, THE HOLD STRETCH), so removing the entry is
the whole change and there is still exactly ONE stretch in the system.

**AND THE QUIET NO LONGER SPANS THE HOLD AT ALL** (W5.6). W4.3's hush ran
from the SEQ edge to the END OF THE HOLD, so the stretched hold lengthened
the dark canvas with it — 3.2–5.0 s of withheld launches. Now the only
withholding is `WORD_SHAPE_HUSH_S` (0.25 s) in front of the launch, and the
hold's length does not change it by a frame.
`tests/test_word_shape_contract.py`'s
`test_the_stretch_no_longer_composes_with_fireworks_own_form_floor` pins
both halves, including that the form floor stays
`WORD_SHAPE_HUSH_S + WORD_SHAPE_FLIGHT_S`.

**ONE BURST PER TOLD WORD, from the centre.** The SEQ edge (never the id —
two hearts back to back both fire) arms `_ws_pending` in `config_updated`,
with the same **creation-baseline rule as `burst_rockets`**: a fresh
instance built from a config that already carries a shape and a SEQ does
NOT fire. `draw` consumes it in `_word_shape_burst`, ungated exactly like
the flare burst (a sung word's shape lands whatever the show is doing) and
`ignore_cap`/`p_nocap`, so the scene's own rockets, beat bursts and drop
tail never go quiet underneath and `_capacity()` is unchanged across the
edge (the additive proof). **The effect writes no key back** — it runs the
whole form, hold and release on its own clock (`_word_shape_clock`) and
resets itself.

**THE ONE THING THAT IS NOT OBVIOUS: EVERY SPARK'S LAUNCH VELOCITY IS
SOLVED FROM THIS EFFECT'S OWN DRAG.** `draw` integrates `x += v*dt` and then
`v *= 0.5**(dt/hl)`, `hl = 0.6 - 0.5*drag`, so the distance one unit of
launch speed covers over `m` frames is the geometric sum
`dt*(1-decel**m)/(1-decel)`; dividing the target by it lands the spark on
the target the frame the form ends — the word. Measured arrival error on his
crystal: **0.000 cell pitches**, every spark, both forms, all three shapes.
Three consequences worth knowing before touching any of it:

- **the solve is for the frame rate the effect is integrating at** (the
  frame's own dt, at the spawn). A render rate that changes mid-form moves
  the arrival a little; a render rate that is simply different (30 vs 60
  fps) does not, because the solve is re-done per burst.
- **the hang is a separate damper.** At the end of the form a spark still
  carries `decel**m` of its launch speed (9% at his `drag` 0.69), which
  would drift it on out through its own outline. From the frame it arrives,
  `_ws_hang` damps the FLAGGED sparks only, half-life
  `WORD_SHAPE_HANG_HL_S` (0.05 s) — the ordinary show's physics is
  untouched. Residual drift after that is about 0.1 of a cell.
- **a told form of 0** (impossible by contract: the engine floors it)
  clamps to `WORD_SHAPE_MIN_FORM_S` and `max(2, ...)` frames rather than
  dividing by zero or teleporting.

**THE TARGETS, AND WHY NOTHING IS ON A LATTICE** ("it also needs to still
appear random"): `word_shape_outline_share` (0.70) of the sparks take a
uniformly random point along the outline BY ARC LENGTH (`shape.at(s)`) plus
up to half a cell of radial jitter; the rest take another random outline
point pulled in to a random depth, drawn **uniformly by area** over
`WORD_SHAPE_FILL_DEPTH` (0.15..0.85) — depth-uniform piles the filling into
the middle where every ray converges, which reads as a blob and sums
different gradient colours into white. **`at(s)` is the only library view
this row uses**, so no shape it draws ever builds an `sdf_fast` grid
(`prime()` is ~200 ms and must never happen on a render frame) — asserted
by test.

**THE HANG AND THE FADE.** `p_wfade` (a new SoA array) is both the flag and
the LENGTH of that spark's own fade window, so a second word's burst can
never retime the first's fade-out. A spark is full bright from its own
fade-in until its window opens, then goes out on its own clock over
`WORD_SHAPE_FADE_FRAC` (0.45..1.0) of the told release — **spark by spark,
never in one step** — twinkling throughout (`WORD_SHAPE_TWINKLE` 0.15 at
6.5 Hz, the phase taken off the spark's own POSITION so neighbours are out
of step and no second array is needed).

**"HANG LONGER THAN THE OTHERS", MEASURED, AND WHY IT IS NOT LITERALLY
TWICE IN HIS ROOM.** A shaped spark's whole life is the told form + hold +
its own share of the release; an ordinary burst's is `burst_life` x
`uniform(0.7, 1.15)`, so its mean is 0.925 x `burst_life`. At the effect's
DEFAULT `burst_life` (1.2 s) that is **1.93x** — which is where the plan's
"about twice as long" comes from. **His own Matrix entry carries 1.9 s**: he
tuned ordinary bursts to be long-lived, so against the show he actually runs
it is **1.22x** (a shaped spark living 2.14 s on average at Energy 0.8
against an ordinary burst's 1.76 s; the whole shape stands 2.35 s loud,
3.1 s quiet). Both are
pinned by `test_the_shaped_sparks_hang_longer_than_the_others` rather than
rounded to the plan's phrase, because the shape's duration is the TOLD
envelope's — a room setting — and not this effect's to stretch. If he wants
a longer hang, the lever is the room's `word_shape_hold_max_s` /
`word_shape_release_ratio`, not anything here.

**THREE CHOICES THE MEASUREMENTS FORCED** (all in the module constants, all
re-measurable with `scripts/check_fireworks_word_shape.py`):

- **the colours are a SLICE of the gradient** (`WORD_SHAPE_GRAD_SPAN` 0.15),
  read by the spark's own angle from a per-burst random offset — not the
  whole gradient. At his `blob_size` 2.0 the outline sparks overlap about
  three deep, and two overlapping sparks from opposite ends of a rainbow
  gradient sum to WHITE: the whole-gradient version put 1.9-3.3% of the lit
  cells over the white threshold. A slice keeps neighbours in one hue, so an
  overlap reads as that hue, brighter. 0.15 is the widest slice that leaves
  NO white cell at Energy 1.0 for any of the three shapes.
- **no bright knot at the origin**: the origins are scattered within one
  cell pitch (uniformly by area) and the sparks have their own fade-in
  (`WORD_SHAPE_FADE_IN_S` 0.18, from 0 — not the ordinary `FADE_IN_S`'s 0.3
  floor), so the burst GROWS out of the centre instead of saturating one
  cell to white.
- **the inside sparks are dimmer** (`WORD_SHAPE_FILL_BRIGHT` 0.50 against
  the outline's 1.0) so the filling reads as filling. This is the number the
  fill-ratio bar below is most sensitive to.

**THE CLARITY BAR IS MEASURED ON THE SHAPE ALONE.** No ordinary show
underneath — which is a real state of his scene, not a convenience: his
Matrix entry runs `spawn_rate: 0`, so a quiet passage launches nothing at
all. A beat burst that happens to land inside the outline is the room, not
the shape failing to be one, and the busy-room numbers are reported
separately against an UNTOLD TWIN (the same show, the same frames, no
shape). Measured on his real 976-cell mask at SIZE 0.62, at the word
(bar: >= 70% of the outline cells lit, fill ratio <= 0.70):

| shape | Energy 0.2 | Energy 0.8 | the plan's sim |
|---|---|---|---|
| heart (168 outline / 248 fill cells) | 87.5% / 0.39 | 95.2% / 0.60 | 72% / 0.46, 87% / 0.47 |
| star (176 / 116) | 92.0% / 0.50 | 98.3% / 0.64 | 76% / 0.65, 86% / 0.65 |
| diamond (119 / 136) | 95.8% / 0.43 | 100.0% / 0.63 | 81% / 0.50, 90% / 0.53 |

At mid-hold coverage falls a few points and the fill ratio drops to
0.22-0.40 (the flight's own trails have decayed): the shape reads MORE like
an outline as it hangs, not less. 68 sparks at Energy 0.2, 92 at 0.8, 60 at
the floor and 100 at 1.0. Cost: the shape holding adds about 0.1 ms p50 a
frame on the 976 cells (bar 1.0), measured against the same show without
it. **The denominators are
`scripts/check_word_shapes.py`'s own cell sets, not re-derived here** — a
bar whose denominator drifts silently is not a bar.

**THE ONE NUMBER THIS ROW DID NOT CLEAR, and it is in the proofs rather
than smoothed over.** The plan's fifth bar is "no whiter than the effect's
own busy frames today". **Alone, the shape lights NO white cell** — not one,
at any Energy, for any of the three shapes. But over a LIVE show the room's
own beat bursts cross the standing sparks, and where they do the two
colours ADD: the worst frame carries ~10 more washed-out cells than the
same show without a shape (1.7-2.0% of the lit cells, against the room
alone's ~0.6% and the effect's own Firework Burst flare's ~0.5% over the
same frames; 1.49% over 600 frames of his ordinary busy show). It is the
same mechanism the effect already shows wherever two of its own fireworks
overlap, and **nothing an effect-level knob reaches changes it** — all of
this is measured, not assumed:

- **not brightness**: 1.63-2.01% at shaped-spark brightness 1.0, 0.8 and
  0.65 alike;
- **NOT THE PER-FRAME COMPOSITE, which is the one that looks like the
  answer.** Rendering the shaped sparks into a frame of their own and
  meeting the room's with a per-channel `np.maximum`, or with a per-cell
  winner-takes-all, or summing as today, all give the heart the **same
  1.74%** and differ by at most 0.23 points on the diamond. The two-pass
  version was built, measured and **not kept** (it cost +0.2-0.4 ms p50 for
  that). A per-channel max of two hues that between them cover all three
  channels desaturates exactly as a sum does — and the two contributions
  usually arrive on DIFFERENT frames anyway, which no per-frame arithmetic
  can reach;
- **the cause is `self.trail`**, a channel-wise MAX over time: a cell
  holding the shape's hue and a passing burst's hue from a neighbouring
  frame has all three channels high however this frame was composited.
  Shortening the trail is not a lever in the other direction either —
  `trail_decay` 0.27 -> 0.0 RAISES the share to 2.95-3.63%, because the
  room's own lit cells leave the denominator faster than the washed-out
  ones leave the numerator.

**So the remaining levers are his, not a build row's**: accept it (the
comet trail doing to a standing shape what it already does wherever two of
this effect's own fireworks share a cell), or change how this effect
trails, which is its look. **His ruling, 2026-11-17: option A, ship as
built, his to judge by eye** — no trail rework, this stays as measured in
the W3 room deploy. The check script prints the number under "ABOVE
THE PLAN'S LETTER — reported, not moved" and
`test_the_live_show_white_is_recorded_above_the_plans_letter` pins it, so it
cannot drift unnoticed in either direction.

**WHAT WRONG LOOKS LIKE, and the precedence.** P3 A means a shape is never
TOLD while a charge, lull or drop is armed, so the shaped burst and the
phase choreography do not normally meet. If one arrives anyway: a **lull**
pauses ordinary launching but not the shaped sparks (they are on their own
clocks, like any particle); a **drop** payoff and the drop tail burst over
them; and a **pre-drop breath** clears every particle including them
(`_pre_drop_step`'s true black — the shape vanishes, which is the breath
doing exactly its job). A second word mid-hold or mid-release simply bursts
over the first, which keeps fading: there is nothing to blend, which is this
effect's answer to the plan's "no snap". A clearing write
(`told() is None`) mid-shape takes nothing away for the same reason.

## W4.3 — A DARK CANVAS, HALF AGAIN AS MANY SPARKS, AND A 2.0 s FORM
   (2026-11-17, his room verdict)

> **SUPERSEDED IN PART BY W5.6 BELOW** (his second room verdict,
> 2026-11-18): the hush's span (edge → the hold's end becomes a 0.25 s
> quiet before the LAUNCH, with the rest DIMMED rather than withheld), the
> flight (0.8 → 2.0 s), the form floor (2.0 → 2.25 s) and the spark counts
> (90/150 → back to 60/100). Every number in this section below is W4.3's
> as shipped, kept as the record of why it was chosen; read the W5.6
> section beside every paragraph of it.

His words, verbatim: *"Fireworks is too cluttered to visually identiy the
shape. Let's have it plan to make sure no fireworks fire right before, or
concurrently, so that it is on a mostly dark canvass. Also, increase the
amount of blobs by 50% so it is more clearly visible, and have it hold 50%
longer."* The longer hold is the ROOM's (row W4.2 tells a longer
`word_shape_hold_s`); nothing in this effect stretches it, and this row
asserts the hang follows what it is told.

**`fireworks` NOW DECLARES A MINIMUM FORM** —
`fx.device_model.WORD_SHAPE_FORM_MIN_S["fireworks"] = 2.0`, the Fish's own
precedent and the second entry in that dict. Read the word-shapes skill's
own note on that accessor first: the form IS the lead in practice, so the
floor does not merely fire the band early, it makes the whole envelope
2.0 s long. **A consequence worth stating rather than discovering: the band
fires 2.0 s EARLY, so a COLOUR kind pooled in a Fireworks scene's Words
band lands 2.0 s early too** — exactly as it already does on Fish. There is
deliberately **no seventh told key** for a "quiet": that would reopen the
W0.3 told-key contract for one effect, and "how early the write arrives" is
all a hush needs.

**THE HUSH** (`_word_shape_arm`, `_word_shape_clock`, the spawn block's
first branch). From the SEQ edge to the **END OF THE HOLD** this effect
makes no ordinary launch of any kind:

- `spawn_rate` bursts, `_beat_pending` beat bursts and the **drop tail's
  shower** are all withheld, and the accumulators (`spawn_acc`,
  `_beat_pending`, `_tail_acc`) are CLEARED every hushed frame — nothing is
  deferred, so the release does not open onto a pile of withheld launches;
- a **`burst_rockets` flare poke is DROPPED, not deferred** (`_burst_pending
  = 0`, the pre-drop breath's own swallow). The key is still self-reset, so
  an identical later write edges again;
- what is **already in the air is not killed**: each ordinary particle's
  remaining life is capped at its own share of `WORD_SHAPE_HUSH_FADE_S`
  (0.7 s) over `WORD_SHAPE_HUSH_FADE_FRAC` (0.5..1.0). **The stagger is not
  decoration** — one constant for all of them made every particle of a
  similar age reach zero on the SAME frame, measured as 9.1% of his real
  cells winking out in one frame against the effect's own untold worst of
  3.7%. Lull rockets (`p_rocket`) are left alone: they are a phase's
  choreography, not the ordinary show;
- launching **resumes with the release**, which is W1.2's own vision ("the
  ordinary fireworks carry on around them").

**THE FLIGHT NO LONGER LEAVES AT THE EDGE.** `_word_shape_arm` starts the
clock and opens the hush; `draw`'s launch block fires the burst when the
clock reaches `form − WORD_SHAPE_FLIGHT_S` (0.8 s), and the flight handed to
`_word_shape_burst` is the time LEFT to the word on the effect's own clock,
so a frame of quantization at the launch cannot drift the arrival off the
word (measured arrival error still **0.000 cell pitches**). Three things
that follow:

- **`_ws_form` is the whole TOLD form, from the edge** — so `_ws_frac` still
  reads 1.0 and `_ws_hang` still flips ON the word. `WORD_SHAPE_CLOCK_EPS`
  is why it flips on that frame rather than the one after it: the clock
  accumulates `dt` and reaches a told time to within a float's dust;
- **a told form shorter than the flight** (impossible from the engine, which
  floors it) makes flight = form, so the burst launches at the edge rather
  than before it;
- **a shaped spark's `p_life` is flight + hold + its own fade**, not form +
  hold + fade — it is not born until the flight starts — and it still ends
  exactly where W1.2's did.

**A CLEARING WRITE ALSO ENDS THE HUSH** (`config_updated`, the
`told() is None` branch). It says no shape is standing, and holding the
panel dark for a shape that will never arrive is worse than doing nothing,
so launching resumes at once and a burst still in the barrel is dropped.
The CLOCK is left alone, so a spark already in the air keeps fading on its
own exactly as W1.2 has it — there is nothing to blend.

**A PHASE ARRIVING ENDS THE HUSH.** P3 A means a shape is never told while a
charge, lull or drop is armed, but one landing on a standing shape owns the
panel: the drop payoff and its tail fire as today and the shaped sparks,
additive, keep flying or hanging over them. The check is one line in
`_word_shape_clock` (`self._phase != "none"`), so an already-armed phase
ends it on the next frame too.

**`word_shape_sparks_quiet` 90, `_loud` 150** — W1.2's 60/100 plus half
again, in the module's `CONFIG_SCHEMA` **and** in
`config/effect_params.json`, with one test pinning that they agree. They
are uncapped (`p_nocap`), so `CAP` (1024) is the only bound: a show
saturating his `max_blobs` of 100 plus a loud burst's 150 is 250, and even
the registry's own 400 ceiling fits — asserted, so the clamp in
`_word_shape_burst` is provably unreachable in his room.

### What W4.3 measured, and the one bar it had to re-read

`scripts/check_fireworks_word_shape.py` prints all of it (`--ascii` now also
draws the frame GRADED BY LUMINANCE at the word and at mid-hold).

- **THE DARK CANVAS**, his headline: over 20 seeds at Energy 1.0 with a
  120 bpm beat and his scene at its busiest (`beat_burst` 6 × `burst_size`
  14 a beat, each spark living 1.9 s into a `max_blobs` of 100), the
  ordinary light left on the panel ON THE WORD is **0.00% of his 976 real
  cells** at 20/255, against **43.6% median / 60.6% worst** on the same
  seeds untold. Zero `_spawn_burst` calls between the edge and the hold's
  end in every seed. Measured by telling the shape exactly as the engine
  does and stubbing the burst itself out — the only way to read the canvas
  without guessing which cells were whose.
- **CLARITY**, the shape alone on his real mask: coverage **96.4-100%** of
  the pinned outline cells on the word (bar 70%), fill ratio **0.41-0.57**
  (bar 0.70); up from W1.2's 87.5-100% with 100 sparks.
- **CONTRAST**, the row's new bar, because legibility on that canvas is the
  whole point: the outline band's mean luminance is **6.0-11.5× the rest of
  the panel's** at the word and at mid-hold (bar 3.0), with 86.9-99.2% of
  the band above 64/255 and 65.5-96.6% above 128/255.
- **WHITE**: the shape alone still lights **no white cell at all** at any
  Energy, 150 sparks included. Over a LIVE show the told worst is now
  **0.97-2.17%** of the lit cells against the room alone's **1.46%** over
  the same frames — so most (shape, Energy) rows sit at or BELOW the room's
  own number, where W1.2 read 1.74-2.01% against 0.62%. **What moved was
  the window and the hush, not the sparks**: the 2.0 s form makes the
  measured span two and a half times longer (catching more of the room's own
  beats, which is why the untold comparator rose) and the hush takes those
  beats away for the whole form and hold. His 2026-11-17 ruling stands —
  option A, ship as built. If it ever does rise with the spark count,
  `WORD_SHAPE_GRAD_SPAN` and `WORD_SHAPE_LAUNCH_PITCH` are the levers and
  the trade is his: a narrower slice is less of his colour set on the shape.
- **THE "NOTHING JUMPS" BAR HAD TO BE RE-READ, and that is arithmetic
  rather than convenience.** W1.2's form is the frame-to-frame change in LIT
  CELLS as a share of the lit count. The hush drives that denominator to
  ZERO on purpose, so the first spark of the burst is an unbounded relative
  change and the measured number (2300-3300%) is about the lit threshold,
  not about anything a viewer would call a jump. It is still printed. The
  bar is asserted on the panel's own **MEAN LIGHT** over each of the
  shape's four stretches (the hush emptying, the flight, the hold, the
  release), against **the effect's own ordinary maximum** — the same seed's
  untold worst over the same SPAN. Measured: **0.0022-0.0737 told against
  an own-worst of 0.0611-0.0737**, every stretch under it. The comparator is
  the span's worst and not each stretch's own, deliberately: the hush MOVES
  when this effect's busiest frames happen (the release's return lands on an
  emptied panel instead of a full one), so a per-stretch comparison would
  put a shifted show beside an unshifted one. Both numbers are printed.
- **W1.2's additive proof is RETIRED and rewritten.** "The ordinary
  particles are untouched across the edge" is exactly what his verdict
  overturns. The rule now:
  `test_the_shaped_burst_is_additive_except_the_hush` — ordinary sparks are
  SHORTENED (never killed, never re-timed longer, keeping their age, colour
  and motion) and ordinary LAUNCHES are withheld from the edge to the
  hold's end; everything else is as additive as it was, and `_capacity()`
  is still unchanged across the edge.
- **COST**: +0.07 to +0.11 ms p50 a frame with the shape holding (bar 1.0).

**One side effect of the floor worth knowing before tuning it.** The room's
release is 1.5 × the FORM, so flooring the form at 2.0 s makes the release
3.0 s: a shaped spark now lives the flight (0.8 s) + the hold + its own
share of 3.0 s, which is **2.0-3.0× an ordinary burst's** life against
W1.2's 1.22×. Neither this effect nor this row chose that — it is the
room's `word_shape_release_ratio` times the planner's floor, and the lever
is the room's, not the effect's.

## W5.6 — DIM NOT DARK, SLOWER, SOFTER, BACK TO 60/100
   (2026-11-18, his SECOND room verdict)

His words, verbatim: *"I think we overtuned the fireworks last time. The
background doesn't need to be clear of other fireworks, just they need to be
dimmer, so fading out already. I think we can give it 80% less pre-fire
darkness time. It also holds too long and fades too abruptly. And it's too
well-defined. Let's turn back the increase in blob count, and at the end,
the blobs should lightly break apart and fade out. Also, the burst is too
fast. Slow the burst by 60% so we can see the blobs moving out to the
outline, and then decelerating to almost a stop, but not quite a stop. The
blobs should always be slightly drifting."*

**THIS ROW REVISES W4.3 ABOVE RATHER THAN ADDING TO IT.** Read every
paragraph of that section beside this one: the hush's span, the flight's
length and the spark counts are all superseded here. **EVERY NUMBER HE GAVE
IS ONE MODULE CONSTANT, with his own sentence beside it in
`fx/effects/fireworks.py`**, so the next retune is a number change and not
a build:

| his words | the constant | was | is |
|---|---|---|---|
| "80% less pre-fire darkness time" | `WORD_SHAPE_HUSH_S` | the form's own 1.2 s of lead | **0.25 s** |
| "just they need to be dimmer" | `WORD_SHAPE_BACKGROUND_DIM`, `WORD_SHAPE_DIM_RAMP_S` | — (launches withheld) | **0.40**, ramped over **0.25 s** |
| "turn back the increase in blob count" | `word_shape_sparks_quiet` / `_loud` | 90 / 150 | **60 / 100** |
| "it also holds too long" | `fx.device_model.WORD_SHAPE_HOLD_X["fireworks"]` | 1.5 | **gone** (the room's 0.8–2.0 s) |
| "slow the burst by 60%" | `WORD_SHAPE_FLIGHT_S`, `WORD_SHAPE_FLIGHT_HL_S` | 0.8 s, the effect's own drag | **2.0 s**, **0.65 s** |
| "almost a stop, but not quite ... always slightly drifting" | `WORD_SHAPE_DRIFT_KEEP`, `WORD_SHAPE_DRIFT`, `WORD_SHAPE_DRIFT_HL_S` | `WORD_SHAPE_HANG_HL_S` 0.05 s (a dead stop) | **0.04**, **0.03 pitches/s**, **0.5 s** |
| "lightly break apart and fade out" / "fades too abruptly" | `WORD_SHAPE_BREAK_DRIFT`, `WORD_SHAPE_FADE_POWER`, `WORD_SHAPE_FADE_FRAC` | — , 1.3, (0.45, 1.0) | **0.30 pitches/s**, **1.0**, **(0.6, 1.0)** |

Two more constants moved, and they are **measured corrections rather than
his asks** — both of them consequences of the slower departure, both
documented at the constant:
`WORD_SHAPE_FADE_IN_FRAC` (new: the fade-in is now **0.225 of the flight**,
which is W4.3's own 0.18 / 0.8, instead of a fixed 0.18 s) and
`WORD_SHAPE_LAUNCH_PITCH` (**1.0 → 2.0**). See "the two corrections" below.

**"SLOW THE BURST BY 60%" IS READ AS A SPEED, and the other reading is
stated here so the retune is one constant either way.** ×0.4 of W4.3's 0.8 s
flight is **2.0 s**; "60% LONGER" would be 1.3 s. 2.0 s was taken because
his sentence says what he wants to SEE — "so we can see the blobs moving out
to the outline, and then decelerating" — and a burst that covers the same
distance in two and a half times the time is 60% slower in the only sense a
viewer has. If he wants 1.3 s, that is `WORD_SHAPE_FLIGHT_S` and
`WORD_SHAPE_FORM_MIN_S["fireworks"]` (which must stay hush + flight).

**THE SECOND HALF OF THE SLOW BURST IS A SECOND CONSTANT, and without it the
longer flight would have made the problem worse.** The effect's own drag
gives a velocity half-life of `0.6 − 0.5 × drag` = **0.255 s** at his `drag`
0.69. Over a 2 s flight that kernel saturates in about 0.4 s: the solve
would still land every spark on the word, but it would get there in the
FIRST FIFTH of the flight and sit on the outline for the other four — the
opposite of "moving out to the outline, and then decelerating".
`WORD_SHAPE_FLIGHT_HL_S` (0.65 s, about a third of the flight) is the shaped
sparks' own, used BY THE SOLVE AND BY THE INTEGRATION ALIKE (a mismatch
between the two would throw every arrival off its target, which is why the
arrival test is the proof that they agree). Measured mean speed over the
flight, in real cell pitches a second:

| shape | 25% | 50% | 75% | the flight's last frame | on the word (after the 4% keep) |
|---|---|---|---|---|---|
| heart | 5.94 | 3.49 | 2.05 | 1.24 | 0.048 |
| star | 5.27 | 3.09 | 1.81 | 1.10 | 0.043 |
| diamond | 4.58 | 2.69 | 1.58 | 0.96 | 0.038 |

— falling at every quarter, and at the halfway mark the sparks are about
three quarters of the way out (a 0.255 s kernel would have had them at 98%).

**"ALMOST A STOP, NEVER QUITE" IS A MEAN-REVERTING WALK, AND THE
MEAN-REVERSION IS THE PART THAT MATTERS.** `_word_shape_drift` (new) does
two things to the flagged sparks on and after the arrival frame: it takes
`WORD_SHAPE_DRIFT_KEEP` (4%) of the speed each one arrived with — a fraction
of its OWN speed, so a far target drifts a little faster than a near one —
and then every frame it runs `v → (v − mean)·ou + mean + σ·z`, with `ou`
from `WORD_SHAPE_DRIFT_HL_S` and σ set so the stationary spread is exactly
`WORD_SHAPE_DRIFT`. **Plain additive jitter would have been wrong**: that is
a diffusing walk whose speed grows as √t and whose displacement grows faster
still, so a 3 s hold would have blurred the outline off its own line.
Measured over the hold, the SLOWEST spark of every frame: **0.000–0.002
cell pitches/s, never exactly zero on any frame**, mean 0.035–0.040 — and
the shape at mid-hold still covers 70.8–97.5% of the outline cells (the
clarity table below), so the breath does not cost the outline.

**WHAT 0.03 CELL PITCHES A SECOND ACTUALLY BUYS, stated rather than
implied**: about a tenth of a cell of travel over a 0.8–2.0 s hold. It is a
breath at the cell-pitch scale, which is what "slightly drifting" asks for,
and it is NOT visible motion. If he wants more, `WORD_SHAPE_DRIFT` is the
one number; `WORD_SHAPE_DRIFT_HL_S` is the one that would let the shape
wander off its outline, so raise that one last.

**THE BREAK-APART IS SMALL, AND THE MEASURE IS SURVIVORSHIP-FREE.** Over the
release the drift grows to `WORD_SHAPE_BREAK_DRIFT` (0.30 pitches/s) of
common OUTWARD push, with the walk's own spread growing to half of that on
top, ramped linearly from the hold's end so there is no step. Ramped, the
outward travel is about half of `BREAK_DRIFT × release` — half a cell over a
3.4 s release, which is "lightly". **Measured on the COMPLETE POPULATION**:
`WORD_SHAPE_FADE_FRAC` (0.6, 1.0) guarantees no spark is gone before 60% of
the release, so the frame just inside that holds exactly the sparks the
hold's end held, and the mean radius there is a TRAVEL rather than a
survivorship effect — 8.288 → 8.381 pitches (heart 0.8), 7.300 → 7.389
(star), 6.711 → 6.815 (diamond), with the mean speed 0.040 → 0.131. **At the
release's END the radius reads anywhere from 6.6 to 11.1 pitches and that
number is noise, not a measurement**: a handful of sparks are left by then
and which ones is random, which is why the bar is read where the population
is whole and the last-lit radius is printed with the caveat beside it.

**THE FADE IS GENTLER TWO WAYS** ("fades too abruptly"):
`WORD_SHAPE_FADE_POWER` 1.3 → **1.0** (linear; 1.3 is a curve that holds the
brightness up and then drops it, which is the abrupt end he saw) and
`WORD_SHAPE_FADE_FRAC` (0.45, 1.0) → **(0.6, 1.0)** (the first spark goes at
60% of the release, the last exactly at its end). Measured: the outline
band's own light falls over the release with a steepest one-frame drop of
**2.6×** the even rate (bar 6×), and the first spark goes at **60%** of the
release.

### What W5.6 measured, and the bar it had to re-read

`scripts/check_fireworks_word_shape.py` prints all of it.

- **THE DIM BAR REPLACES W4.3's DARK CANVAS**, because that bar is exactly
  what his verdict overturns. W4.3 measured 0.00% of his 976 real cells
  carrying ordinary light on the word; the measure now is the ORDINARY LIGHT
  on the panel at the word against **the same seed's untold frame**, bounded
  on BOTH sides. Over 20 seeds at Energy 1.0, 120 bpm, his scene at its
  busiest: **39.7% of the untold light POOLED** (against
  `WORD_SHAPE_BACKGROUND_DIM` 0.40 — the dim is exactly what it says),
  per seed median 40.7%, least 25.1%. The panel is still a show: **57.8% of
  his real cells lit at 20/255** against the same seeds untold's 80.3%.
  **ZERO** ordinary launches inside the 0.25 s quiet, every seed.
  Light is the panel's MEAN LUMINANCE over his real cells, not a cell count:
  a share of cells above a threshold cannot see a cell that merely went
  dimmer, which is the whole of what this row does to the background.
- **THE ONE NUMBER ABOVE THE ROW'S LETTER, reported rather than moved.** The
  row's bar is "≤ 45% of the same-seed untold frame's". **The WORST single
  seed reads 53.8%.** The bar is asserted on the POOLED ratio and the worst
  seed is printed under the check script's "ABOVE THE PLAN'S LETTER" block
  and in the test's own output. Why the pooled number is the one that
  measures the claim: one frame of one seed compares two shows whose last
  beat landed differently — the 0.25 s quiet withholds a beat's launches on
  some seeds and not others — so a single seed's ratio is a noisy estimate
  of a 0.40 dim rather than a measurement of it (per-seed range 25.1–53.8%,
  pooled 39.7%). **If he wants the worst frame under 45% the lever is
  `WORD_SHAPE_BACKGROUND_DIM` at about 0.33**, and the trade is that the
  background goes dimmer than he asked for on the median frame.
- **CLARITY**, the shape alone on his real mask at SIZE 0.62 (bar: ≥70%
  coverage, ≤0.70 fill): **80.4–98.3% on the word** and **70.8–97.5% at
  mid-hold** (fill 0.28–0.48), with 68 sparks at Energy 0.2 and 92 at 0.8.
  Lower than W4.3's 96.4–100% — 60/100 sparks instead of 90/150 is exactly
  his "it's too well-defined", and the bar is still clear everywhere.
- **CONTRAST** (bar 3.0): the outline band's mean luminance is **9.07–13.19×
  the rest of the panel's** on the word and 9.93–13.61× at mid-hold, with
  49.4–83.2% of the band above 128/255. W4.3 read 6.0–11.5× with half again
  as many sparks — the contrast went UP because the W5.7 flip moved the band
  onto a different set of real cells and the fill is dimmer relative to it.
- **ARRIVAL: still 0.000 cell pitches**, every spark, all three shapes, at
  Energy 0.2, 0.8 and the floor, and at a told form longer than the floor —
  the proof that the solve and the integration read the same half-life.
- **WHITE**: the shape alone lights **no white cell at all** at any Energy,
  all three shapes — after the two corrections below. Over a live show the
  told worst is **1.40–1.45% at Energy 0.8 and 0.52% at Energy 1.0** against
  the room alone's **1.46%** over the same frames, so every row sits at or
  below the room's own number (W4.3 read 0.97–2.17%). His 2026-11-17 ruling
  stands and no longer has anything to cover.
- **"NOTHING JUMPS"**, the four stretches against the effect's own untold
  worst over the same span: **0.0169–0.0451 told against an own-worst of
  0.0736**, every stretch under it. The first stretch is now "the dim comes
  in" rather than "the hush empties".
- **COST**: +0.10 ms p50 a frame with the shape holding (0.48 → 0.57 ms,
  bar 1.0). The drift adds one `standard_normal` draw over 60–100 sparks a
  frame and only while a shape is hanging.
- **THE ADDITIVE PROOF IS REWRITTEN AGAIN.** W1.2's rule was "untouched
  across the edge"; W4.3's was "shortened, never killed; launches withheld
  from the edge to the hold's end". W5.6's is **"dimmed, never killed;
  launches withheld only in the 0.25 s quiet"** —
  `test_the_shaped_burst_is_additive_except_the_quiet_and_the_dim`. The dim
  is a brightness and ONLY a brightness: `test_the_dim_is_a_brightness_and_
  only_a_brightness` renders the same seed told and untold and asserts every
  ordinary particle's position, velocity, age and colour matches frame for
  frame, with the light being this effect's own forward envelope times the
  dim factor. **And ON THE EDGE FRAME ITSELF the dim is 0.0** — the ramp is
  why — so the frame the shape is told renders exactly as it would untold.

### The two corrections the slower burst forced

Neither is one of his numbers; both are measured consequences of a departure
at 0.4× the speed, and both are documented at the constant.

- **`WORD_SHAPE_FADE_IN_FRAC` (new, 0.225 of the flight) replaces a fixed
  `WORD_SHAPE_FADE_IN_S` of 0.18 s.** W4.3's own reasoning for the fade-in
  is "by the time they are full bright they have flown over half of the way
  out, so the burst GROWS out of the centre instead of flashing in it" —
  which is only true at ONE flight length. At 0.18 s into a 2 s flight the
  sparks are 20% of the way out instead of 44%, and 100 of them still
  stacked near their origins **saturated two cells to white 0.1 s after the
  launch** (4.88–6.12% of the lit cells at Energy 1.0, against W4.3's "no
  white cell at all at any Energy"). 0.225 is exactly 0.18 / 0.8, so the
  geometry is what W4.3 measured, and a later flight change carries it.
- **`WORD_SHAPE_LAUNCH_PITCH` 1.0 → 2.0.** With the fade-in fixed, ONE cell
  of the star's 73 lit ones still went white 0.27 s after the launch at
  Energy 1.0 (1.37%). The trail is a channel-wise MAX over TIME, so a slow
  spark's track lingers in a cell far longer than a fast one's, and the
  scatter that was enough at 17 pitches/s is not at 7. At 2.0 all three
  shapes light no white cell at any Energy again, and **the coverage and
  fill ratio do not move at all** between 1.0, 1.5 and 2.0 (96.4%/0.29
  heart, 97.2%/0.47 star, 100%/0.47 diamond at Energy 1.0) — the scatter
  lives in the burst's first few frames and nothing about where the sparks
  LAND reads it.

### One length consequence of this row, stated rather than discovered

The form floor went 2.0 → **2.25 s** (`WORD_SHAPE_HUSH_S` + 
`WORD_SHAPE_FLIGHT_S`), and the room's release is **1.5 × the FORM**, so the
release went 3.0 → **3.375 s**. With the hold back to the room's 0.8–2.0 s a
shaped spark now lives the flight (2.0 s) + the hold + its own share of
3.375 s — **3.0–4.5× an ordinary burst's** life, measured, against W4.3's
2.0–3.0×. Neither this effect nor this row chose that: it is
`word_shape_release_ratio` times the planner's floor, and **the lever for
the whole length is the room's, not the effect's**. He asked for the HOLD to
be shorter and it is; if the whole thing is still too long, that setting is
where it lives.

**Proofs:** `tests/test_fireworks_word_shape.py` (the pinned-module
byte-identity over 320 busy and 320 quiet frames, the real `ResponseEngine`
through to the real effect, arrival, the split, the counts, the hang, the
clarity bar, no white, the additive proof, the SEQ edges, the creation
baseline), `scripts/check_fireworks_word_shape.py` (the evidence, with
`--ascii`). Help topic `fireworks-word-shape`; the four tunables are
registered in `config/effect_params.json`, so Sonic reaches them through
`set_scene_entry_param` for free. **The shape is live only after `ledfx` is
restarted (W3), and no scene is seeded with one ahead of his own tuning
session** (`docs/ADDING_EFFECTS.md`).
