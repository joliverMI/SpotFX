---
name: orbits-effect
description: >
  fx/effects/orbits.py (Matrix, crystal-mapper) and fx/effects/orbits1d.py
  (Strips) — orbiting-particle effect behind Orbits V2, and the strip
  effect three OTHER scenes' Strips entries reuse (Squiggles V2,
  Dancers V2, Pacman V2). NOT Fish — Fish's own Strips entry is
  `fireworks1d` (live data, see the fish-scene skill), even though its
  Matrix entry is a wholesale copy of this scene's params/bands and moves
  completely differently; see the fish-effect skill for that split.
---

# Orbits / Orbits1d

Matrix effect renders to `crystal-mapper` — load `crystal-hex-grid` first
for anything about coverage/spawn radius on this device.

**Orbits1d is load-bearing for scenes that aren't "Orbits" at all** —
Squiggles V2, Dancers V2 and Pacman V2 all use `orbits1d` for their Strips
entry (their own Matrix effect is something else). A change here can move
four scenes at once (Orbits V2 plus those three); check the live scenes
(`GET /spectra/api/scenes`) before assuming a fix is Orbits-only. **Fish is
NOT one of them** — despite being a wholesale copy of this scene's own
Matrix params/bands, its Strips entry is `fireworks1d` (see the fish-scene
skill's own note on the divergence from its seed script).

## Params worth knowing before tuning

- `orbit_radius` (0.02..0.8): a real geometric radius, degeneracy-guarded —
  `drift_conductor._registry_range()` intersects any drift declaration's
  lo/hi against this param's OWN legal range at Mechanism construction, so
  an authored profile built for a different param (e.g. a [0,1]-ish
  default) can't silently wander below the effect's own floor and get
  rejected by the config schema while the conductor's model keeps moving.
- `reverse` (toggle, "Reverse Spin", default False): read LIVE on every
  frame in `draw()` (`direction = -1.0 if self.reverse else 1.0`), so it
  flips the rotation of EVERY particle AND the tether ring continuously,
  including ones already in flight (`orbits1d`: the oscillation and the
  ring). This is the OPPOSITE of blackhole's spawn-side `reverse` — never
  port a blackhole reverse fix here, or an orbits one there.
- `spin` ("Ring Spin", 0..1, registry aspect `reactivity`): the tether
  RING's rotation speed as a fraction of `base_speed`, boosted by the audio
  impulse (`ring_phase += spin * base_speed * direction * (1 + 0.5 *
  speed_jump * impulse) * dt`). Not a swirl amount — that is Fish's
  meaning for its own `spin` — and not radial's squared audio gain either.
- `speed_jump`/`speed_jog`/`brightness_audio`/`size_audio`: audio gains —
  idle near their floor during quiet passages; see the audio-idle trap
  documented on the radial-effect skill.
- `implode_fade`/`implode_reach`/`bounce_chance`/`overlap_blend`
  (orbits1d only): strip-specific shape/collision params with no Matrix
  analogue — don't assume parity between the two modules' schemas.

## Drop-ejecta persistence is a Little's-Law order statistic

His ask was "3 seconds" for how long ballistic drop ejecta lingers after a
drop. The burst COUNT (`DROP_EJECTA_X=2`, i.e. 3x the configured
population) is explicitly NOT to be touched — it already matches his
stated number. `particle_count` feeds the ejecta count
(`DROP_EJECTA_X * particle_count`), and "time until the last one is gone"
is an order statistic over that count — a higher `particle_count`
mechanically produces a longer worst-case straggler even with an
UNCHANGED per-particle speed distribution. Measure over several RNG seeds
and average; a single run is noisy (`scripts/
check_orbits_drop_burst_and_persistence.py`).

## The lull can be TOLD to keep N blobs (2026-10-08, the fireworks melds)

Orbits joined `fx.device_model.LULL_HANDOFF_EFFECTS` (`fx/effects/
lull_handoff.py`; `fx/VENDOR.md` #64) for the drop-led switch's keepers
meld: a lull leading into Fireworks is told `lull_keep = 3`. Told N > 1,
the lull keeps N blobs (the shortfall flies in from off-panel), the
geometry falls only to `LULL_KEEP_RING` of itself and each blob's own
orbit shrinks to `LULL_KEEP_ORBIT` (`_orbit_scale`), so the N sit on an
evenly spaced ring — distinct origins for Fireworks to explode. Told
`lull_next` another effect, `_handoff_snapshot` flags them (`"keepers"`).
**Told 1 (the default) or untold, the lull is byte-identical to before** —
proven frame for frame against the pinned pre-change module; told 0, it
keeps its one blob anyway (it has no dark lull to fall back to). Orbits'
own drop ejecta burst (`_spawn_drop_ejecta`, `DROP_EJECTA_X *
particle_count`) still does not scale with `drop_intensity` — only the
Shockwave does (below): Orbits is now IN `DROP_INTENSITY_EFFECTS`, widened
2026-10-11 to every `DROP_SHOCK_EFFECTS` member so the Shockwave's own
debris/front-life can scale, but `orbits.py` itself never reads
`drop_intensity`.

## The drop Shockwave and the breath-hold (2026-10-11, transitions-drop plan phase 1)

This effect is a member of `fx.device_model.DROP_SHOCK_EFFECTS`. Its drop
gets the shared Shockwave painted by `Twod.render` AFTER its own `draw()`
(`fx/effects/phase_grammar.py` is the binding statement): a rim bloom, ONE
wavefront born on the tether ring at its resting radius (`horizon_scale` x `radius_scale`), debris (curving back onto the ring) and a wall splash, all in the
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
inside the lull's dark rule). **On Orbits it is NOT true black** (2026-10-12,
the Admiral: "I want orbits and fish to specifically not go dark completely
on the crystal or the strips" / "orbits should keep at least one dim blob"):
`BREATH_FLOOR = BREATH_FLOOR_DIM` (0.25) makes the base render dim the frame
to that share instead, so the lull's one blob stays, dim, through the
breath (`phase_grammar.breath_gain(..., floor=)`). Do not set it back to 0.
Help topics `drop-shockwave`, `lull-dark-cap` (the breath-hold is folded into it); proof
`scripts/check_drop_shockwave.py` (`breath_ok`) / `tests/test_phase_grammar.py`.

WHETHER A DROP PAINTS IT AT ALL (2026-10-12, his "toggled per scene, as
well as globally, as well as a global setting for minimum energy"): the drop
arm also tells this effect `drop_shock_on` — the room's `drop_shock_enabled`,
the showing scene's own `drop_shock_enabled`, and the top bar's Energy
(`bridge.intensity(look_ahead=True)`, ENERGY since 2026-10-28 — `spectra/services/energy.py`; the 0.7 is re-set by `scripts/energy_parity.py`) against the room's `drop_shock_min_energy` (0.7),
decided by `phase_grammar.shock_allowed`. False = no painter at all: the
frame is this effect's own drop byte for byte (no reveal hold-back either).
Untold reads True. It is an overlay, so nothing in this effect's own drop
changes; `drop_shock` (the per-effect strength) is a separate knob. Help
`drop-shockwave-switches`; proof `tests/test_drop_shock_switches.py`.

## The STRIP (`orbits1d`) draws its phases through the strip phase layer

Since 2026-10-11 (strip phase plan phase 3; `fx/effects/strip_phase.py` is
the binding statement, `fx/VENDOR.md` #74) the strip's charge/lull/drop
LOOK — hue-kept colour gain, set-colour fill, the drop's set-colour
shockwave, the lull's fade to black at the room's dark point, the white
guard — comes from the shared layer, and so does its phase PLUMBING (edge
detection, the orphan watchdog, the drop's self-reset after
`DROP_SETTLE_S`): the module keeps only `_strip_phase_enter` and its
per-frame `_phase_step`. The phase is `self._sp_phase`. What it owns:

- **Swell and HOLD** (his call 2): the charge swells to `CHARGE_PEAK_N`
  (16, `particle_count`'s own max) over `CHARGE_PEAK_AT` of progress and
  holds there to the drop. It used to shed back to ONE blob by the
  charge's end — do not bring the shed back.
- The lull's one blob collapses to the middle on the layer's OWN lull
  timing (`_strip_phase_lull()`), landing as the strip reaches its dark
  point — and STAYS, dim (2026-10-12, "orbits should keep at least one dim
  blob"): the strip's own `lull_ember` default is `LULL_EMBER` (0.2,
  `STRIP_PHASE_DEFAULTS`, spliced into the schema and the registry like the
  Fireworks strip's 0.12), so the layer fades it to 20%, never black. This
  is every scene that uses `orbits1d` (Orbits, Squiggles, Dancers, Pacman
  V2). Proof `tests/test_particle_strip_phase.py`,
  `scripts/check_particle_strip_phase.py`.
- The strip's drop SHOCKWAVE obeys the crystal Shockwave's switches (the
  room, the scene, the 0.7 top-bar Energy floor — told `drop_shock_on`);
  skipped, only the wave and flood go (`tests/test_drop_feedback_1012.py`).
- The drop re-adds all 16 (each erupting through its implosion), the
  fly-out on its own clock (`_fly`), and sheds back to the scene's own
  `particle_count` on the "none" edge.
- A flare punch in the dark springs the collapsed blob back out (size and
  position follow `_strip_phase_punch()`) with an implosion burst in the
  blob's OWN colour — the lull has no white guard.
- On a phase the implosion pair comes from the SET (the set rotated by a
  third, `_phase_fragment_colours`), never the hue wheel's ±120°, which
  reaches hues the set does not have. Off-phase it is the ±120° pair, and
  every off-phase frame is byte-identical to before.
- ACTIVITY (`STRIP_PHASE_ACTIVITY`): `base_speed` and `spin`, 0.5 each —
  never the count, which is the swell's.

The 2-D Matrix `orbits.py` is untouched by all of this.

## THE PRE-DROP — the blob dims, then comes back jittering and growing (2026-10-27)

His words (the predrop plan, 2026-10-26): "on orbits, when it comes back
in, make it jitter like it's full of energy and is about to burst, instead
of staying still. Have it grow in size as it does slightly." Orbits is in
`fx.device_model.PRE_DROP_EFFECTS` since predrop step 7, one look for both
kinds ("jitter", `pre_drop_looks` in config/effect_params.json).
`fx/effects/pre_drop.py` is the binding statement for the told keys;
the module's PRE_DROP block (`fx/effects/orbits.py`) for the look. Four
invariants not visible cold:

- **ONE CURVE, NEVER DIMMED TWICE.** The base render (`Twod.render`)
  already multiplies the lull by the breath, floored at `BREATH_FLOOR`
  (25%). `_pre_drop_gain` is the factor ON TOP of that, so the product is
  the plan's single curve: full at the lull's start, smoothstepping to the
  25% floor by the breath's start (the pre-drop, if no breath is told),
  held there through the breath, full on the pre-drop. Changing the
  floor or the breath means re-reading both, not one.
- **THE JITTER MOVES THE RENDER CENTRE, NOT THE PARTICLES** — a fresh
  `self._rng` offset every 1/30 s (0.4 -> 1.8 px, `frac ** 1.3`) added to
  `cx`/`cy` where `pxs`/`pys` are built, so the model, the tether and the
  drop's explosion origin never move; kept blobs (`lull_keep`) share the
  offset, so a meld's three blobs jitter together. The trail is cut to 30%
  each jittering frame, or the smear reads as a fuzzy blob.
- **IT GROWS INSTEAD OF SHRINKING**: on the pre-drop the lull's shrink is
  skipped and the size runs 2.0x -> 2.6x over the gap (still capped at
  `KERNEL_R`); the blob stays at the centre (`_pos_scale` is the lull's).
  The growth and the jitter's trail cut share ONE read of the clock a frame
  (`grow = self._pre_drop_grow()`, reused for the jitter's gate since step
  8), so they can never disagree about whether the pre-drop is on.
- **A LONGER GAP ADDS LIGHT** — back at full and growing for the whole gap:
  -9% against today's lull at the plan's 0.8 s spike, +1% at 2 s, +14% at a
  3.3 s vocal intro (named; `tests/test_pre_drop_looks.py` bounds it at
  +20%). Untold, every new branch returns before touching state or the rng,
  so the lull is today's frame for frame (proven against the module at the
  step-7 base).

## THE PRE-DROP — the strip twinkles (2026-10-27)

Predrop plan step 9 (`fx/VENDOR.md` #90; the drop-detection skill for the
engine). Every strip phase member is a `fx.device_model.PRE_DROP_EFFECTS`
member, and this one plays the shared layer's look, `twinkle` (its
`pre_drop_looks` block in `config/effect_params.json`, for both kinds) —
drawn once in `fx/effects/strip_phase.py`'s THE PRE-DROP, nothing in this
module. Told a pre-drop, the lull is measured to it (its dark point falls
before the pre-drop) and runs exactly as this strip's own lull does; from
the pre-drop to the drop a few pixels light in the set's colours at the
effect's OWN brightness (his "make the twinkles max brightness match the
effect brightness (don't dim, just use twinkle to "dim")") and fade over
about a tenth of a second, born a little faster toward the drop. They are
painted after the lull's fade, brighter-wins (never two hues mixed whiter).
Untold is today's frame for frame against this strip AND the layer before
step 9. Its light over the lull stays below today's at every measured gap.
Proofs: `tests/test_pre_drop_looks.py` (the step-9 section; rig
`tests/pre_drop_look_harness.py`'s `strip_run`/`load_pinned_strip`),
storyboards `strip_orbits1d_*` in `docs/evidence/predrop-storyboards/`.

This is the Orbits STRIP (`orbits1d`); the crystal Orbits' look is the
jitter-and-grow return above. The strip's one dim blob (its 20%
`lull_ember`) stays through the gap; a twinkle over it shows only where
the twinkle is the brighter.

## Thematic transitions (2026-10-11, transitions-drop plan phase 3)

The Black Hole's ERUPTION implodes onto Orbits' LIVE blobs (his comment:
"implode into the orbits like the shoaling"): `_formation_points()` gives
every tracked blob's pixel position each frame, and each ejecta lands ON
one with its velocity. Orbits also FEEDS an Infall into the Black Hole:
`_handoff_snapshot` now carries `vx`/`vy` (px/s, from `p_vx`/`p_vy` — SoA
arrays set every frame from the drawn displacement, render byte-identical)
and `gesture: "orbit"`. An incoming Orbits starts FRESH under a program
(the program owns the outgoing particles). `fx/effects/transition_program.py`'s docstring is the binding statement; `tests/test_transition_programs.py` measures it on the real pipeline.

## WORD SHAPES — few trace it, many become it (2026-11-16, row W1.3; row W4.4's speed section, 2026-11-17, is at the end of it)

Load `.claude/skills/word-shapes` first: it owns the shape library, the six
told keys, the form/hold/release envelope and the outline-cell denominators
every number below is a fraction of. This section is only what ORBITS does
with them. `fx.device_model.WORD_SHAPE_EFFECTS` now names `orbits` — the
2-D Matrix effect ONLY; **`orbits1d` knows no shapes** (a strip has no
outline to draw one on) and nothing about the strip changed.

His words for the row: *"Orbits: if there are few and they are large, they
can change shape from circles to the shape. If there are a lot, they can
move in a path together that forms the shape."* and *"For particles that
flow to move in that shape, like fish and orbits, they need to smoothly
accelerate and not have sudden velocity shifts."* His Q10 A set the
threshold as a setting; his **P1 A** decided the few-blob case: the
tethers gather to the centre so the blobs trace ONE shape together —
*"one heart reads; three overlapping ones read as a tangle on 976 cells"*.

**TWO MODES, LATCHED AT THE EDGE** (`_word_shape_latch`). The live tracked
blob count at the moment the shape starts decides it: `<= word_shape_few`
(3) is FEW, more is MANY, and the verdict is **held for the whole shape**.
That is not tidiness — his scene drives `particle_count` 1-8 by Energy, so
without the latch a rising Energy would flip three blobs tracing one heart
into eight beads on it halfway through the word. Proof:
`tests/test_orbits_word_shape.py::test_the_latch_holds_when_energy_changes_the_count_mid_shape`.

- **FEW** blends each blob's position by `m` between its ordinary point
  (its tether plus its orbit circle at its own phase) and the outline, AND
  scales the tether ring itself by `(1 - m)` so the tethers gather to the
  centre. The blob walks the outline **by arc length at its own orbit
  rate** — the same fraction of its cycle is the same fraction of the
  outline — which is where the continuity comes from.
- **MANY** blends the tether for slot `k` between the ring point at its
  slot angle and the outline at `ring_phase + k/n`, so the string of beads
  circulates along the outline at the RING's own speed, evenly spaced by
  the slots; each bead's orbit radius shrinks to `word_shape_wobble` of
  itself so it still wobbles a little. `tether_scatter` blends out with
  `m` (the even spacing is the whole point of this mode).

**THREE THINGS THAT ARE EASY TO GET WRONG HERE, each one measured:**

1. **SIZE IS DIVIDED BY `radius_scale`** (`_word_shape_scale`).
   `word_shape_size` is the plan's convention — a fraction of THE PANEL's
   half-height — but Orbits' normalized space is not the panel's: `sx`/`sy`
   carry `radius_scale` (1.8 on his scene) to stretch the circular physics
   into a panel-filling ellipse. Drawn without dividing it out, a heart
   comes out at 1.12 of the panel and spills off three sides: measured, 6
   of the 45 real cells the blobs visited were anywhere near the outline
   and the clarity bar read 15%. Any new reader of a shape view in this
   module owes the same division.
2. **FEW ANCHORS EACH BLOB'S WALK TO ITS OWN EVEN SLOT** (`p_ws0`, an SoA
   array holding the blob's orbit phase in revolutions at the edge). The
   blob's own phase drives the RATE; its slot decides WHERE on the outline
   it starts. Three blobs spawn with random phases, so without the anchor
   they trace whichever third of the heart they happened to spawn in —
   measured 58% of the outline lit at mid-hold on the unluckiest of five
   seeds, against 85-99% with it. A blob born mid-shape has no anchor
   (NaN) and walks from its raw phase.
3. **THE TRAIL'S PER-FRAME DECAY IS WHAT IS BLENDED, NOT ITS HALF-LIFE**
   (`WORD_SHAPE_TRAIL_S`, 0.9 s). The trails are what draw the outline's
   edge, so they linger under a shape; the fraction a trail loses per
   frame is hyperbolic in the half-life, so ramping the half-life leaves
   the decay flat for most of the release and then collapses it from 1.2%
   to 11% of the smear per frame over the last few frames — a whole faded
   outline crossing the lit threshold at once, 23-28% of the lit cells in
   ONE frame. Blended as a decay it is linear in `m`, and `m` is a
   smoothstep with zero slope at both ends. At `m` 1 and `m` 0 the two
   formulations are identical, so the hold is the same picture either way.

**PRECEDENCE** — it is a blend on the REST geometry, applied where the
tether, the ring radius and the orbit radius are built, BEFORE the phase
math composes onto the same expressions and before the entering/leaving
branches. So the drop's ejecta (ballistic, their position is overwritten),
the drop Shockwave (painted by `Twod.render` after `draw()`), the
pre-drop's jitter (it moves the render CENTRE, not the model) and the
lull's fall all keep their precedence with no change. P3 A means a shape is
never TOLD during a charge, lull or drop; **one ARRIVING mid-shape wins and
the shape releases from exactly the fraction it is at** — what wrong looks
like is the shape vanishing on that frame, or the drop's explosion coming
out of a half-formed heart. Every edge in `_word_shape_step` starts from
the fraction already standing (`_inv_smoothstep`): a second word in the
release picks the shape back up, a clearing write lets it go, a stale
persisted SEQ on a fresh instance never fires at all.

**A TRANSITION OWNS THE FRAME.** `draw()`'s early returns — the outgoing
collapse into Radial, the held eruption, the held pacman adoption — return
before `_word_shape_step` runs, so a shape told across one of those pauses
its own clock and resumes where it left off rather than running out
invisibly. A transition program's matched birth (`_program_birth`) leaves
`p_ws0` NaN on the born blobs, so a shape told right after one walks from
each blob's raw phase instead of its slot: evenly spread is the next
shape's business, not this one's.

**THE CLARITY BAR, AND WHERE IT IS ASSERTED.** `scripts/check_orbits_word_shape.py`
measures on his real `crystal-mapper` mask at SIZE 0.62, against
`scripts/check_word_shapes.py`'s own pinned outline counts (heart 168, star
176, diamond 119). The bar is at THE HOLD: >= 60% of the outline lit with
FEW, >= 75% with MANY. The word's own number is reported beside it and is
deliberately NOT the bar — at the word the shape has only just completed,
so the trail behind each blob is still the forming sweep, and no blob-based
effect can light 60% of an outline the instant it arrives on it.

Measured 2026-11-16 (seed 7, his live Matrix entry, phrase 1.2 s), at the
hold / at the word, Energy 0.2 and 0.8 — the plan's simulation numbers in
brackets:

| | heart (168) | star (176) | diamond (119) |
|---|---|---|---|
| FEW, Energy 0.2 | **92%** / 29% (sim 98%) | **93%** / 36% (99%) | **93%** / 31% (100%) |
| FEW, Energy 0.8 | **79%** / 32% (95%) | **74%** / 31% (98%) | **78%** / 42% (96%) |
| MANY, Energy 0.2 | **77%** / 68% (83%) | **87%** / 77% (92%) | **83%** / 79% (95%) |
| MANY, Energy 0.8 | **87%** / 57% (76%) | **86%** / 69% (90%) | **88%** / 66% (89%) |

Every bar is met and the whole outline is lit by the hold's END (100% with
FEW). The loud-Energy FEW numbers sit below the simulation's because the
form is shorter there (0.5 s against 0.79 s), so less of the outline has
been walked by the hold's MIDDLE; across five seeds FEW at Energy 0.8 runs
74-100%. Cost: +0.00 to +0.33 ms p50 per frame with a shape holding (bar
1 ms). White: 0 cells of 976, except 1 on many-diamond at Energy 0.8, where
eight beads of different colours crowd one small outline.

### ROW W4.4 (2026-11-17) — FAST ENOUGH FOR THE TRAIL TO CLOSE THE OUTLINE

His verdict on the W1.3 build, after the W3 room deploy: *"I can tell the
fish and orbits are trying to do something, but it's not clear enough. They
need to increase speed so they can pass the outline fast enough that their
trail stays and it clearly forms the shape. Start with orbits and when we
get that dialed in, we will do fish."* Plus his standing rule for the row:
*"they need to smoothly accelerate and not have sudden velocity shifts."*

**THE W1.3 BAR WAS VACUOUS, AND THAT IS THE ROW'S FIRST FINDING.** It
counted a cell LIT at 20/255 — eight percent of full. Re-measured with the
same rig, the W1.3 numbers (74-93% of the outline at the hold) sat beside a
share of the SAME band over half of full (128/255) of **1-25%**. A faint,
broken line passes a bar like that. The Fish review's lesson (a vacuous lit
bar becomes a CONTRAST bar — `scripts/check_fish_word_shape.py`'s
`band_contrast`) was never carried back here; this row carries it, and the
W1.3 number keeps printing beside the new one for the record.

**ONE NEW REGISTERED PARAM, `word_shape_speed_x`** (1.0-6.0, default
**4.0**; `WORD_SHAPE_SPEED_X`), applied as `1 + (x - 1) * m` by
`_word_shape_speed_x()` — which is the binding statement — to **ONE rate
per latched mode**: FEW's `omega` (its walk along the outline IS its orbit
rate, by arc length) and MANY's `ring_phase` rate (its circulation IS the
ring's). Never both: the blend is multiplying the other one towards zero
anyway. Ramped by the envelope, so the acceleration is CONTINUOUS and the
speed is back to today's by the release's end — his standing rule, and
`(1.0, 1.0)` on every untold frame, so untold is still byte-identical.

**`WORD_SHAPE_TRAIL_S` ROSE 0.9 -> 1.8, and only that far.** It is the
row's SECOND lever, and the sweep (16 configurations of `--speed-x` x
`--trail-s` over 24 (mode, count, shape, Energy) rows) separates the two
cleanly — this is the number to know before touching either:

| | speed 2 | speed 3 | speed 4 | speed 6 |
|---|---|---|---|---|
| trail 0.9 | 27 / 64 | 43 / 78 | 53 / 87 | 59 / 88 |
| trail 1.8 | 28 / 74 | 43 / 83 | **60 / 91** | 67 / 93 |
| trail 3.0 | 28 / 77 | 43 / 84 | 61 / 93 | 69 / 95 |
| trail 5.0 | 28 / 78 | 43 / 85 | 61 / 93 | 73 / 96 |

(worst / median share of the outline band over 64/255 at mid-hold.)

- **the WORST row is the SPEED's and almost not the trail's at all** — 43%
  at speed 3 and 60-61% at speed 4 at EVERY trail from 0.9 to 5.0. He was
  right that speed is the lever;
- **the trail moves the MEDIAN and the hold's END**, and saturates by 3.0;
- 0.9 left the worst row at 53%, under the bar; **1.8 clears it**, so the
  trail stopped there. 3.0 and 5.0 were measured and buy the worst row
  nothing.
- **his estimate of 3.0 was not enough**: it leaves the ONE-blob rows (his
  quiet-Energy `particle_count` binding) and the FOUR-bead rows at 43-48%
  of the band, under the bar, at any trail. 6.0 buys the worst row 8 more
  points and costs band/rest contrast (median ratio 4.69 -> 4.28), because
  a faster blob smears light further off the line. **4.0.**
- **the ADAPTIVE rule the row's spec offered as an alternative was measured
  and REFUSED**, with a number: "the rate is whatever makes
  `(outline / n) / v <= k x half_life`". At the spec's own implied `k` ~ 1
  it gives 3.4x for one blob, 1.1x for three, 2.3x for four beads, 1.1x for
  eight — and the measurement says 1.1x is barely better than today's. At
  the `k` ~ 0.15 that a brightness bar actually needs, EVERY count clamps
  to the 6.0 ceiling and the rule degenerates to "max speed". Its premise
  is that the binding constraint is the revisit GAP; it is not, it is the
  DEPOSIT (below). A fixed multiplier is what shipped.

**THE ROW'S BAR, AND ITS ONE OPEN EXCEEDANCE.** The row's spec asked for
**90% of the outline band over 128/255** at every hold frame. That is above
what this effect can DEPOSIT, and the arithmetic is exact rather than
arguable: the band is every real cell within ONE CELL PITCH of the outline,
a pitch is two addressable columns, and `_splat` weights a cell
`1 - dist / (blob_size + 0.5)` — so at his `blob_size` fallback 2.5 a cell a
full pitch off the swept path takes `1 - 2/3 = 0.33` of the blob's
brightness, and his `brightness_audio` 0.5 already holds that brightness at
0.775 of full: **65 OF 255**. The trail composes by `np.maximum`, so nothing
can exceed what was deposited; measured with an UNDECAYING trail at speed 6
the band's over-128 share **ceilings at 43-99%** by row, and 23 of the 24
rows reach no speed in 1..6 that meets the spec. **No speed and no trail
reaches it** — the one row that does is few-3 diamond at Energy 0.8, at
speed 5 (90% -> 91%). So the bar ASSERTED is the share over **64/255** — the same
threshold the Fish row's bar uses, for the same reason — at mid-hold AND at
the hold's end, plus the band/rest luminance ratio, plus that share against
the SAME SEED's frame untold. The over-128 share is printed on every row
with its ceiling (`--needed`). The levers that could close it are
`blob_size` and `brightness_audio` — HIS authored params, his eye, not a
build row's to move. **Reported, not hidden** (the honest-bar rule from
wave 1, and the same shape as the Fish row's white tail).

Measured at the shipped defaults (seed 7, his live Matrix entry, phrase
1.2 s), share of the band over 64/255 at mid-hold / at the hold's end, with
the over-128 share at mid-hold in brackets; bars 55% and ratio 1.4:

| | heart | star | diamond |
|---|---|---|---|
| FEW 1, Energy 0.2 | 95 / 92% (23) | 91 / 89% (26) | 97 / 97% (43) |
| FEW 1, Energy 0.8 | 62 / 97% (41) | 61 / 90% (35) | 64 / 99% (49) |
| FEW 3, Energy 0.2 | 99 / 100% (42) | 98 / 97% (43) | 100 / 100% (62) |
| FEW 3, Energy 0.8 | 100 / 100% (80) | 99 / 97% (73) | 100 / 100% (90) |
| MANY 4, Energy 0.2 | 75 / 73% (21) | 74 / 82% (26) | 68 / 76% (23) |
| MANY 4, Energy 0.8 | 68 / 88% (21) | 72 / 91% (31) | 60 / 84% (19) |
| MANY 8, Energy 0.2 | 90 / 93% (39) | 90 / 97% (47) | 92 / 96% (52) |
| MANY 8, Energy 0.8 | 99 / 99% (77) | 95 / 98% (76) | 97 / 100% (84) |

Untold, on the same seeds and the same frames, the band reads **0-10%**.
Ratios 1.53-11.97 told against 0.00-2.22 untold. The W1.3 lit-cell number
is now **100%** almost everywhere (it was 74-93%). Across 5 seeds the two
lowest rows hold: many-4 diamond at Energy 0.8 reads 60-93% and many-4
heart 68-88% at mid-hold, ratio down to 1.53 — about 5 points and 0.13 of
headroom on the pinned seed, which is the unlucky one. White 0 of 976 cells
(1 on many-diamond at Energy 0.8, as W1.3); cost **+0.03 to +0.18 ms** p50;
the lit-cell jump 6.5-27.2% against this effect's own 16.7-33.3% untold.

**`fill` — THE STATISTIC THAT ANSWERS HIM DIRECTLY.** Seconds from the word
until the whole line stands and stays. 0.00-0.05 s with three blobs or
eight beads, 0.30-0.58 s with ONE blob (it has to get all the way round).
The hold's FIRST frames can never be whole at any speed, and the reason is
structural rather than a tuning miss: during the form the position is a
BLEND, so trail laid early in the form was laid on the blob's CIRCLE, not
on the outline — only the last part of the form lands on the line. Speed is
exactly what shortens this, and it does (`fill` 0.68-0.70 s at speed 3,
0.55-0.58 s at speed 4 on the one-blob rows).

**THE CONTINUITY BAR MOVED AT THE HOLD'S EDGES, and this is the trap for
W4.6 (Fish).** Before this row a blob walked the outline at its own
`base_speed` — SLOWER than its ordinary orbit — so its hold-edge per-frame
speed change sat under the untold control's. At 4x it does not, at quiet
Energy: measured 129-200 px/s against an untold quiet-Energy ordinary of 98.
**It is not the blend.** The panel is ANISOTROPIC (a column is half a cell
pitch, a row sqrt(3)/2), so the same arc-length walk's px speed swings by
nearly 2x round the outline and changes abruptly at every corner — a
STANDING shape, envelope flat at 1.0, produces one-frame changes up to
100 px/s ANYWHERE in the hold, which W1.3 already refused to bar
(`mid-hold`). Comparing a 4x-speed outline walk against a 1x-speed circle
is not a like-for-like test of "sudden shifts". So at the hold's edges what
is asserted is the DECOMPOSITION, with no magic number: the envelope's
largest one-frame move over the whole shape against the steepest its own
smoothstep can be; **`row_speed_bound` = the blend's own bound PLUS the
multiplier's** (`|dx| / x_max` of the fastest speed the hold reaches) —
37-106 px/s, under the ordinary at every row; and the raw change within
what a standing shape already does mid-hold plus that bound. At the form's
START and the release's END, where the row's ramp really is what is moving,
the plain speed-and-heading bar against the ordinary maximum STANDS and is
met with room to spare (2.8-11.7 px/s of 98-488). **Any effect that speeds
a walk along one of these outlines owes the same decomposition.**

Proofs: `scripts/check_orbits_word_shape.py` (`--only contrast`,
`--speed-x`/`--trail-s` for the sweep, `--needed` for the ceiling,
`--ascii` for the luminance-graded renders) and
`tests/test_orbits_word_shape.py`'s ROW W4.4 sections.

## Sonic reach

Same rule as every effect here: no direct param edit. Sonic reaches these
params only through an existing `FlareKind` on whichever scene binds this
effect — except that a registered param's current value on one scene
entry is reachable through `set_scene_entry_param`, which includes the
strip's strip-phase tunables (`charge_fill` … `flare_punch_glow`,
registered on `orbits1d`) and the crystal's four Word Shape settings
(`word_shape_size`, `word_shape_few`, `word_shape_wobble`,
`word_shape_speed_x`). The six
`word_shape_*` TOLD keys are deliberately NOT registered — they ride only
the Words band's own write, so no kind, drift mechanism or Sonic op can
reach them.

## Executable proofs

`scripts/check_orbits_word_shape.py` + `tests/test_orbits_word_shape.py`
(the Word Shape section above: both modes, the latch, the clarity bar on the
real mask, the continuity numbers, the cost, and untold byte-identity
against the pinned pre-change module),
`scripts/check_orbits_drop_burst_and_persistence.py`,
`scripts/smoke_orbits_params.py`, `tests/test_orbits_drop_persistence.py`,
`tests/test_fireworks_melds.py` (keep-N ring, the keepers flag, untold
byte-identity), `tests/test_lull_handoff.py`, `tests/test_pre_drop_looks.py`
(the pre-drop look, and the untold lull against the step-7 base) with its
storyboards `scripts/render_predrop_storyboards.py`. The strip on the strip phase
layer: `scripts/check_particle_strip_phase.py` (before/after on his own
Orbits V2 strip entry, the pinned pre-change module as red control) +
`tests/test_particle_strip_phase.py`, `scripts/check_strip_phase.py`.
History: docs/agents/fx-effects.md's "Fish (`fx/effects/fish.py`) — Orbits' twin,
different kinematics" section (how Fish reuses Orbits' patterns but not its
motion) and the drop-timing-reference withdrawal note
(`data/drops-still-fire-early-star-does-not-explode/`).

## Phase 4 transitions (2026-10-11): Shoaling, Shoal Break, Unravel, Flame Lick

- **`p_om`** (SoA, exported as the snapshot's `om`): each blob's heading RATE,
  rad/s in pixel space, smoothed over `OM_TAU_S` from consecutive velocities.
  Render-inert. The SHOALING (Orbits -> Fish) peel reads it: every fish starts
  on its blob turning at the blob's own rate (fish.PEEL_S).
- Orbits RECEIVES Shoal Break (fish dots), Unravel (a chain's dots), Flame
  Lick (the eye's shards) onto its live `_formation_points()`, the same
  Hermite FORM as the Eruption; Orbits -> Squiggles is UNRAVEL (the blobs
  thread onto the chain heads).
`fx/effects/transition_cloud.py`'s docstring is the binding statement for phase 4's programs; `tests/test_transition_programs_phase4.py` measures them on the real pipeline.

## THE HOST FRAME: born matched, with a velocity graft (2026-10-17)

The shoal-burst plan (`/home/javi/fleet-spotfx/data/shoal-burst-plan/
report.md`; `fx/effects/transition_cloud.py`'s `HostFormer` is the binding
statement) made Orbits a form a transition program can be BORN INTO, so the
cloud leaving the old effect rides the new blobs instead of flying to them.
Three things on this effect:

- **`_program_birth(snap)` / `_program_hosts(pids)`** — one blob per
  released object, AT its position, carrying the id the program's cloud
  follows it by (`p_pid`). It is NOT part of `_adopt_handoff`, deliberately:
  the crossfade adoption path is byte-identical and the birth is an opt-in
  capability. `_program_hosts` answers NaN for a retired pid, and those
  pieces fall back to a constant-turn continuation.
- **THE VELOCITY GRAFT** (`p_resx`/`p_resy`/`p_resage`, applied in `draw()`
  after the entering/leaving blend has settled `x, y`). Orbits is
  POSITION-driven — a tether on a spinning ring, a blob orbiting the tether
  — so there is no velocity state to set. Instead
  `drawn(t) = model(t) + v_res . t . e^(-t/tau)` with
  `v_res = v_inherited - v_model(0)`: the graft's own velocity at birth is
  exactly `v_res`, so the blob leaves on the velocity it inherited; the
  displacement peaks at `v_res.tau/e` and returns to zero, so the model is
  never permanently displaced and NOTHING IS SOLVED BACKWARDS (no inverse
  kinematics for slot/phase/radius). `v_model(0)` is MEASURED on the first
  frame after birth, never guessed. `tau` is `transition_graft_ms`.
- **RING ORDER IS CHOSEN, not left to chance**: `_manage_population` hands
  slots out in array order, so the birth orders the born blobs by their own
  angle and rotates that to the ring, which is what keeps each glide into
  orbit short instead of sending a blob across the panel for a slot it never
  had to have. `_count_hold` holds the matched count (3 fish -> 3 orbits)
  until `transition_count_hold_ms` after the program ends, then the
  authored `particle_count` wins and `_manage_population` flies the
  difference in or out exactly as it does for any live change.

Proofs: `tests/test_shoal_burst.py` (every number, with a `git archive` of
the merge-base as the before), `tests/shoal_burst_harness.py` (the rig).
