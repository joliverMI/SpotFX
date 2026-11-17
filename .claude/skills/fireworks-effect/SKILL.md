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
trails, which is its look. The check script prints the number under "ABOVE
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
