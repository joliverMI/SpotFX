import logging

import numpy as np
import voluptuous as vol
from PIL import Image

import fx.effects.particle_handoff as particle_handoff
import fx.effects.phase_grammar as phase_grammar
import fx.effects.pre_drop as pre_drop
import fx.effects.word_shape_keys as word_shape_keys
import fx.effects.word_shapes as word_shapes
from fx.color import validate_gradient
from fx.effects.audio import AudioReactiveEffect
from fx.effects.gradient import GradientEffect
from fx.effects.twod import Twod

_LOGGER = logging.getLogger(__name__)

CAP = 1024          # particle capacity; overflow spawns are dropped
SUBSTEPS = 3        # path sub-samples per frame (gap-free smear)
DT_MAX = 0.1
FADE_IN_S = 0.05
KERNEL_R = 6        # max blob radius the offset table supports
CENTER_BIAS = 1.6   # burst-origin radius exponent (>1 = center-weighted)
SPAWN_FIELD = 0.8   # burst origins live within this normalized radius
SAFE_CAPTURED = 24  # max horizon blobs a blackhole handoff explodes

# charge/lull/drop choreography (SpotFX drives `phase` + ramps
# `phase_progress`; see _phase_step)
CHARGE_SPAWN_X = 5.0   # extra spawn-rate multiplier at full charge (1 + X*p)
CHARGE_SHRINK = 0.6    # burst particle-count reduction at full charge
CHARGE_SLOW = 0.55     # burst speed reduction at full charge
CHARGE_SHORT = 0.4     # burst life reduction at full charge
LULL_ROCKETS = 6       # slow rockets crossing the dark panel
LULL_ROCKET_WIGGLE_FRAC = 1.0 / 6.0  # per-rocket start-angle wiggle, as a
# fraction of the even 2*pi/k step (+/-10 deg at six rockets): the ring
# still reads as a ring, and no two rockets can ever swap order (needs
# < 1/2 of the step) — his ask, 2026-08-21: "radially equidistant around
# the center ... a little bit of wiggle so that they're not all perfectly
# radial but generally close"
LULL_FLIGHT_S = 4.0    # rocket flight fallback when no lull ramp arrives
LULL_ROCKET_FADE = 0.75  # brightness lost over the rocket flight
DROP_SETTLE_S = 0.9    # payoff settle time before phase auto-reset
PAYOFF_SPEED = 1.6     # giant-firework speed multiplier
PAYOFF_LIFE = 1.35     # giant-firework life multiplier
# drop tail: extra ordinary launches per second right after the payoff,
# easing linearly to 0 over DROP_TAIL_S (the charge's own linear ramp,
# mirrored on the way out). Its own clock, not the drop phase's — the
# phase self-resets at DROP_SETTLE_S and the tail must outlive it. A
# launch RATE, not a spawn_rate multiplier: his real scene runs
# spawn_rate=0 (beat bursts only), so a multiplier would be a no-op
# there. Tail launches pass ignore_cap like the payoff, so a cap the
# ordinary show may already be saturating never bounds the shower; and
# no uncapped particle (payoff, flare burst, tail, rocket) ever OCCUPIES
# max_blobs (p_nocap/f_nocap), so the ordinary show — his beat bursts —
# keeps launching underneath the whole time instead of going silent for
# ~PAYOFF_LIFE x burst_life the way it did before that flag existed.
DROP_TAIL_RATE = 8.0   # launches/s right after the payoff
DROP_TAIL_S = 2.5      # seconds for the tail to ease back to the ordinary show

# THE PRE-DROP (fx/effects/pre_drop.py is the binding statement; predrop
# plan step 6, report 3.5; fx/VENDOR.md #87). A lull TOLD its drop has a
# pre-drop launches no rockets at its start: the panel stays dark (the
# ordinary show already stops in a lull, so only what was flying before it
# fades out), goes truly black for the breath-hold right before the
# pre-drop (SpotFX ends the breath exactly on it; whatever is still fading
# is gone, and a flare landing in the breath is swallowed), then the SAME
# rocket ring fires ON the pre-drop and flies the pre-drop-to-drop gap
# (fast for a spike, the whole entry for a vocal intro), bursting on the
# drop (_rocket_payoff, unchanged). One look serves both kinds. An untold
# lull is today's, byte for byte: every pre-drop branch returns before it
# touches anything.
PRE_DROP_LOOK = "rockets"
# a rocket fired on the pre-drop loses brightness at this rate over its
# flight — 0.25 over the plan's 0.8 s prototype, so a spike's short flight
# stays bright — and never more than the whole-lull rockets' own
# LULL_ROCKET_FADE, so a long flight (his 2 s spike maximum, a vocal intro)
# dims like today's and the lull's light stays at or below today's
PRE_DROP_ROCKET_FADE_PER_S = 0.3125


def pre_drop_rocket_fade(gap_s: float) -> float:
    """What a pre-drop rocket loses over a flight of `gap_s` seconds."""
    return min(LULL_ROCKET_FADE, PRE_DROP_ROCKET_FADE_PER_S * max(0.0, gap_s))

# THE KEEPERS MELD (2026-10-08, drop-scene-variety plan phase 3 — spectra/
# services/drop_switch.py is the binding statement; fx/VENDOR.md #64). His
# words: "fish and orbits could have 3 'particles' remain instead of just 1
# and then they could explode into fireworks on the drop". A fish/orbits
# lull TOLD it is leading into Fireworks (fx/effects/lull_handoff.py's
# `lull_next`) leaves `lull_keep` KEEPERS and flags them in its particle
# snapshot (`"keepers"`). When the drop-led switch cuts to Fireworks on the
# drop mark, _adopt_handoff turns each flagged keeper into a stationary
# ROCKET exactly where it stands, and the drop arm that lands on the same
# frame (_rocket_payoff, the lull rockets' own payoff) explodes every one of
# them into a giant firework in its own colour — the keepers ARE the
# payoff's origins. A snapshot with no flagged keepers adopts exactly as
# before (every particle bursts as its own ordinary firework).
KEEPER_ROCKETS_MAX = 2 * LULL_ROCKETS  # never more payoff origins than this
KEEPER_HOLD_S = 0.6    # held keepers with no drop arm by now burst on their
                       # own (an ordinary switch in a lull, or a lost arm) —
                       # never left hanging as dots

# WORD SHAPES — THE SHAPED PAYOFF BURST (Word Shapes plan row W1.2,
# approved by the Admiral 2026-11-15; his words for the row: "have a flare
# style firework (so the ones that are bigger) explode into the given shape
# and hang longer than the others. It should form a slightly more solid
# outline than the filling, but it also needs to still appear random."
# Q9 A: one big centred shaped burst per word, ~70% of the sparks on the
# outline, hanging about twice as long, bigger at higher Energy).
#
# ONE burst from the centre per told word (the SEQ edge of
# fx/effects/word_shape_keys.py's six keys, exactly like burst_rockets),
# `word_shape_sparks_quiet`..`_loud` sparks by the word's Energy, and EVERY
# spark's launch velocity SOLVED from this effect's own drag so it is
# standing on its own target the frame the form ends — which is the word
# (`_word_shape_burst`). They then HANG there (velocity damped to nothing,
# a small per-spark twinkle) and fade out spark by spark over the release
# on their own `p_life`, about twice an ordinary burst's. Uncapped
# (p_nocap) like the Firework Burst flare, so the scene's own rockets, beat
# bursts and drop tail never have their density cap taken from them. Not
# told, nothing here runs and the effect renders what it renders today,
# frame for frame.
#
# W4.3 — A DARK CANVAS, AND HALF AGAIN AS MANY SPARKS (wave 4, his room
# verdict 2026-11-17). **W5.6 SUPERSEDES THREE OF ITS NUMBERS** — the
# hush's span (the whole form + hold -> a 0.25 s quiet before the launch),
# the flight (0.8 -> 2.0 s) and the spark counts (90/150 -> back to 60/100)
# — and turns the withholding into a DIM; read the W5.6 section below
# beside every paragraph of this one. Verbatim: "Fireworks is too
# cluttered to visually identiy the shape. Let's have it plan to make sure
# no fireworks fire right before, or concurrently, so that it is on a
# mostly dark canvass.
# Also, increase the amount of blobs by 50% so it is more clearly visible,
# and have it hold 50% longer." The longer hold is the ROOM's, told as
# `word_shape_hold_s` — row W4.2 — and nothing here stretches it.)
#
# THE HUSH is what "no fireworks right before, or concurrently" is: from
# the SEQ edge to the END OF THE HOLD this effect makes NO ordinary launch
# of any kind — no `spawn_rate` burst, no `_beat_pending` beat burst, no
# drop-tail shower, and a `burst_rockets` flare poke is DROPPED (never
# deferred, the pre-drop breath's own rule). Launching resumes with the
# RELEASE, so W1.2's own vision still ends "the ordinary fireworks carry on
# around them" as the shape fades. What is already in the air at the edge
# is NOT killed — blinking a panel full of sparks out in one frame is
# exactly the jump the plan bars — its remaining life is capped at
# WORD_SHAPE_HUSH_FADE_S so it fades out, and the trail's own half-life
# (0.155 s at his `trail_decay` 0.27) clears the smear behind it. Nothing
# is DEFERRED either: the accumulators are cleared every hushed frame, so
# the release does not open onto a pile of withheld launches.
#
# THE FLIGHT therefore does NOT leave at the edge any more. The band fires
# `fx.device_model.WORD_SHAPE_FORM_MIN_S["fireworks"]` (2.0 s) early — the
# Fish's own precedent, and the lead IS the form in practice — but the
# burst leaves the centre only WORD_SHAPE_FLIGHT_S before the word, so the
# burst itself looks exactly as it did (0.8 s is inside the 0.5-0.9 s
# Energy-paced form W1.2 measured) and the 1.2 s in front of it is the
# panel going dark. The shape's own clock runs from the EDGE (`_ws_form` is
# the whole told form), so `_ws_hang` still flips on the word; only the
# SPAWN waits.
#
# A PHASE ARRIVING ENDS THE HUSH. P3 A means a shape is never TOLD while a
# charge, lull or drop is armed, but one that lands on a standing shape
# owns the panel: the drop payoff and its tail fire as they do today and
# the shaped sparks, additive, keep flying or hanging over them.
#
# W5.6 — DIM, NOT DARK; SLOWER; SOFTER; BACK TO 60/100 (wave 5, his SECOND
# room verdict 2026-11-18, verbatim: "I think we overtuned the fireworks
# last time. The background doesn't need to be clear of other fireworks,
# just they need to be dimmer, so fading out already. I think we can give
# it 80% less pre-fire darkness time. It also holds too long and fades too
# abruptly. And it's too well-defined. Let's turn back the increase in blob
# count, and at the end, the blobs should lightly break apart and fade out.
# Also, the burst is too fast. Slow the burst by 60% so we can see the
# blobs moving out to the outline, and then decelerating to almost a stop,
# but not quite a stop. The blobs should always be slightly drifting.")
# Every number he gave is ONE CONSTANT here, so the next retune is a number
# change — the seven of them are, in his own order:
#
#   1. WORD_SHAPE_HUSH_S (0.25 s, was the form's own 1.2 s of lead) — the
#      80% less pre-fire darkness. The hush is now a QUIET IMMEDIATELY
#      BEFORE THE LAUNCH, not the whole stretch to the hold's end.
#   2. WORD_SHAPE_BACKGROUND_DIM (0.40) + WORD_SHAPE_DIM_RAMP_S — "dimmer,
#      so fading out already" instead of withheld. W4.3's HUSH withheld
#      every ordinary launch from the edge to the hold's end; now only the
#      0.25 s hush withholds, and from the edge to the hold's end the
#      ordinary show is DRAWN AT 0.40 of its brightness, ramped in over
#      WORD_SHAPE_DIM_RAMP_S and back out over the release so nothing
#      steps. The sparks alive at the edge keep W4.3's staggered life cap,
#      which is what "fading out already" is.
#   3. the spark counts back to W1.2's 60/100 (`word_shape_sparks_quiet` /
#      `_loud`, the schema and config/effect_params.json) — "turn back the
#      increase in blob count", and half of his "too well-defined".
#   4. the HOLD back to the room's own 0.8-2.0 s: `fireworks` LEAVES
#      `fx.device_model.WORD_SHAPE_HOLD_X` (STAR and the Black Hole keep
#      their 1.5 — he liked those). Nothing in this module ever stretched
#      the hold, so there is nothing to undo here.
#   5. WORD_SHAPE_FLIGHT_S (2.0 s, was 0.8) + WORD_SHAPE_FLIGHT_HL_S
#      (0.65 s) — "slow the burst by 60%" read as a SPEED (0.8 / 0.4 =
#      2.0 s), with the shaped sparks' own drag relaxed so the
#      deceleration spans the whole flight instead of finishing in its
#      first fifth. See both constants.
#   6. WORD_SHAPE_DRIFT_KEEP (0.04), WORD_SHAPE_DRIFT (0.03 cell pitches/s)
#      and WORD_SHAPE_DRIFT_HL_S — "almost a stop, but not quite ... always
#      slightly drifting". The hang no longer damps to zero: a spark keeps
#      4% of the speed it arrived with and then rides a slow mean-reverting
#      random walk that never reaches zero.
#   7. WORD_SHAPE_BREAK_DRIFT (0.30 cell pitches/s), WORD_SHAPE_FADE_POWER
#      (1.0, was 1.3) and WORD_SHAPE_FADE_FRAC (0.6..1.0, was 0.45..1.0) —
#      "the blobs should lightly break apart and fade out", not abruptly:
#      over the release the drift grows tenfold, outward-and-random, while
#      the fade is linear and no spark is gone before 60% of the release.
#
# The told-key contract is untouched (no seventh key), and everything else
# of W4.3 stands: the flight is the time LEFT to the word, `_ws_hang` flips
# ON the word, a phase arrival or a clearing write ends the quiet AND the
# dim, and the burst is still additive — now "dimmed, never killed;
# launches withheld only in the 0.25 s hush".
WORD_SHAPE_FADE_POWER = 1.0      # a shaped spark's own fade curve: LINEAR
# since W5.6 ("fades too abruptly" — 1.3 held the brightness up and then
# dropped it, which is exactly the abrupt end he saw)
WORD_SHAPE_OUTLINE_BRIGHT = 1.0  # an outline spark, full bright
# THE COLOURS COME OFF THE SET'S GRADIENT BY POSITION — the angle the spark
# lands at, read across this much of the gradient from a per-burst random
# offset. NOT the whole gradient: at his blob_size the sparks on the
# outline overlap about three deep, and two overlapping sparks from
# OPPOSITE ends of a rainbow gradient sum to white (measured 2026-11-16 —
# the whole-gradient version put 1.9% of the lit cells over the white
# threshold against the effect's own 1.4% busy peak). A slice keeps
# neighbours in the same hue, so an overlap reads as that hue, brighter;
# the random offset is why two words are not the same colour, which is the
# effect's own convention (each ordinary firework picks one gradient colour
# at random). 0.15 is the widest slice that puts NO white cell on the panel
# at Energy 1.0 for any of the three shapes (0.20 leaves the diamond at
# 2.4%, 0.25 all three near 3%) — measured by
# scripts/check_fireworks_word_shape.py.
WORD_SHAPE_GRAD_SPAN = 0.15
WORD_SHAPE_FILL_BRIGHT = 0.50    # an inside spark against an outline one:
# his "a slightly more solid outline than the filling", and what keeps the
# measured fill ratio under the plan's bar (the clarity bar in the skill)
WORD_SHAPE_TWINKLE = 0.15        # glitter depth while the shape hangs
WORD_SHAPE_TWINKLE_HZ = 6.5
# the twinkle's phase per spark: its OWN POSITION through these two
# multipliers, so two sparks a cell apart glitter out of step and no second
# per-particle array is needed for it
WORD_SHAPE_TWINKLE_PX = 53.0
WORD_SHAPE_TWINKLE_PY = 97.0
# W5.6 — THE HANG DAMPS TOWARD A DRIFT, NOT TO ZERO ("decelerating to
# almost a stop, but not quite a stop. The blobs should always be slightly
# drifting"). W4.3's `WORD_SHAPE_HANG_HL_S` (a 0.05 s velocity half-life)
# was a dead stop in three frames; it is GONE, and these three take its
# place:
WORD_SHAPE_DRIFT_KEEP = 0.04     # on the arrival frame a shaped spark keeps
# this much of the speed it arrived with — his "almost a stop, but not
# quite". It is a fraction of the spark's OWN arrival speed rather than an
# absolute, so a target far out of the centre keeps drifting a little
# faster than one near it, which is what the flight itself already looks
# like.
WORD_SHAPE_DRIFT = 0.03          # ... and then it rides a random walk this
# fast, in REAL CELL PITCHES A SECOND (rms per axis, scaled by
# `_ws_pitch`): the outline never freezes, and over a 0.8-2.0 s hold that
# is at most a tenth of a cell of travel — a breath at the cell-pitch
# scale, not a visible wander. The lever if he wants more motion is this
# number; the one that would move the shape OFF its outline is
# WORD_SHAPE_DRIFT_HL_S below.
WORD_SHAPE_DRIFT_HL_S = 0.5      # the walk's own mean-reversion half-life.
# IT IS WHAT MAKES THE WALK A DRIFT RATHER THAN A WANDER: plain additive
# jitter is a diffusing random walk, whose speed grows as sqrt(t) and whose
# displacement grows faster still, so a 3 s hold would blur the outline.
# Mean-reverted at this half-life the velocity has a stationary spread of
# exactly WORD_SHAPE_DRIFT and the position only breathes.
WORD_SHAPE_BREAK_DRIFT = 0.30    # ... and over the RELEASE the sparks
# drift OUTWARD at up to this, in cell pitches a second, with the walk's own
# spread growing to half of it on top: his "at the end, the blobs should
# lightly break apart and fade out" — mostly outward, partly random. Ten
# times the hold's drift, ramped linearly over the release so the hold's end
# is not a step, which makes the measured outward travel about half of
# `BREAK_DRIFT x release` (0.5 of a cell over a 3.4 s release — "lightly").
# `scripts/check_fireworks_word_shape.py` prints the travel beside the
# speed, so what this number buys is a number he can see.
WORD_SHAPE_FADE_FRAC = (0.6, 1.0)  # each spark's fade window, as a
# fraction of the told release: the shape goes out spark by spark, never in
# one step, and the last of them is gone by the release's end. W5.6 raised
# the floor 0.45 -> 0.6 ("fades too abruptly"): no spark is gone before 60%
# of the release, where W4.3's earliest went at 45% of it
WORD_SHAPE_MIN_FADE_S = 0.12     # a told release of 0 still fades out
WORD_SHAPE_MIN_FORM_S = 0.1      # the flight is never shorter than this
# (a form shorter than the effect's own minimum is impossible by contract —
# the engine floors it — so this is the graceful clamp, never a divisor)
WORD_SHAPE_JITTER_PITCH = 0.5    # radial jitter on an outline target, in
# real-cell pitches (+/- this much), so the outline is a stroke rather than
# a drawn line: "it also needs to still appear random"
WORD_SHAPE_FILL_DEPTH = (0.15, 0.85)  # an inside target's depth along its
# own ray, drawn uniformly BY AREA over that range (sqrt) rather than
# uniformly in depth: depth-uniform piles the filling into the middle,
# where every ray converges — which both reads as a blob and sums a pile of
# different gradient colours into white (measured, 2026-11-16)
WORD_SHAPE_LAUNCH_PITCH = 2.0    # the burst's origins are scattered within
# this many real-cell pitches of the centre, uniformly by area: a firework
# leaves from one place, but 100 sparks stacked on ONE cell saturate it to
# white before they separate.
#
# W5.6 RAISED IT 1.0 -> 2.0, and that is the same measured correction
# WORD_SHAPE_FADE_IN_FRAC above is: at 0.4x the departure speed the sparks
# are bunched near their origins two and a half times longer, and the trail
# (a channel-wise MAX over time) holds a slow spark's track in a cell far
# longer than a fast one's. With the fade-in fixed and this still at 1.0,
# ONE cell of the star's 73 lit ones went white 0.27 s after the launch at
# Energy 1.0 (1.37%, against W4.3's "no white cell at all at any Energy").
# At 2.0 all three shapes light none at any Energy again, and the measured
# coverage and fill ratio do not move at all (96.4% / 0.29 heart, 97.2% /
# 0.47 star, 100% / 0.47 diamond at Energy 1.0, identical at 1.0, 1.5 and
# 2.0) — the scatter is inside the burst's first few frames and nothing
# about where the sparks LAND reads it.
WORD_SHAPE_FADE_IN_FRAC = 0.225  # a shaped spark's own fade-in, AS A
# SHARE OF THE FLIGHT (the ordinary FADE_IN_S starts at 0.3 of full, which
# is what white at the origin is made of). By the time they are full bright
# they have flown over 40% of the way out, so the burst GROWS out of the
# centre instead of flashing in it.
#
# W5.6 MADE IT A SHARE RATHER THAN THE 0.18 s IT WAS, and that is a
# MEASURED correction rather than tidiness: a fade-in fixed in seconds is
# only "they are full bright once they are out of the centre" at ONE flight
# length. Over the 2 s flight, 0.18 s put them 20% of the way out instead
# of 44%, and 100 sparks still stacked near their origins saturated TWO
# CELLS to white 0.1 s after the launch — 4.9-6.1% of the lit cells at
# Energy 1.0, against W4.3's "no white cell at all at any Energy". 0.225 is
# exactly W4.3's own 0.18 / 0.8, so the burst's own look at the origin is
# what it was measured to be, and a later flight change carries it.
# THE FLIGHT: how long before the word the shaped burst leaves the centre.
# The told form is the LEAD (2.25 s for this effect since W5.6 — the hush
# plus the flight), and the 0.25 s in front of the flight is the quiet.
#
# W5.6 — 2.0 s, "SLOW THE BURST BY 60%" READ AS A SPEED. His sentence is
# about what he SEES ("so we can see the blobs moving out to the outline,
# and then decelerating"), and what he sees is a speed: 60% slower is x0.4,
# so W4.3's 0.8 s flight becomes 2.0 s. The other reading — "60% LONGER",
# 1.3 s — is stated in `.claude/skills/fireworks-effect/SKILL.md` beside
# this number so the retune is one constant either way; 2.0 s was taken
# because a burst that covers the same distance in 2.5x the time is 60%
# slower in the only sense a viewer has.
#
# A told form SHORTER than this is impossible from the engine (it floors
# the form at the effect's own minimum, which is hush + flight); the clamp
# in `_word_shape_arm` makes flight = form there rather than launching
# before the edge.
WORD_SHAPE_FLIGHT_S = 2.0
# W5.6 — THE SHAPED SPARKS' OWN VELOCITY HALF-LIFE DURING THE FLIGHT, which
# is the other half of "so we can see the blobs moving out to the outline,
# and then decelerating to almost a stop". This effect's own drag gives a
# half-life of `0.6 - 0.5 * drag` = 0.255 s at his `drag` 0.69: over a 2 s
# flight that kernel saturates in about 0.4 s, so a longer flight ALONE
# would have landed every spark in the first fifth of it and left them
# sitting on the outline for the other four fifths — the opposite of what
# he asked to see. At a third of the flight the deceleration spans the
# whole of it: a spark still carries 12% of its launch speed when it
# arrives (which is what WORD_SHAPE_DRIFT_KEEP then takes 4% of).
#
# THE SOLVE USES THIS HALF-LIFE, not the effect's drag, so the arrival is
# still ON the word to within a cell: `_word_shape_burst`'s geometric sum
# and the integration in `draw` read the same constant, and the ordinary
# show's physics is untouched (only the FLAGGED sparks are integrated this
# way, and only while they are still flying).
WORD_SHAPE_FLIGHT_HL_S = 0.65
# ... and the fade-in that keeps the origin from saturating is a share of
# that flight (see WORD_SHAPE_FADE_IN_FRAC for the two cells of white that
# proved it has to be)
WORD_SHAPE_FADE_IN_S = WORD_SHAPE_FADE_IN_FRAC * WORD_SHAPE_FLIGHT_S
# W4.3 — THE HUSH's one mercy: the remaining life an ordinary particle
# still in the air at the edge is capped to. It fades out over this instead
# of blinking out (the plan's "nothing jumps" bar is a frame-to-frame one,
# and killing a panel's worth of sparks in one frame is the thing it bars),
# and it is short enough that the 1.2 s of hush in front of the flight
# leaves a nearly dark canvas: at his `trail_decay` 0.27 the trail's own
# half-life is 0.155 s, so the smear behind the last of them is gone too.
WORD_SHAPE_HUSH_FADE_S = 0.7
# ... and each particle takes its OWN share of that window, drawn
# uniformly over this range, exactly as a shaped spark takes its own share
# of the release (WORD_SHAPE_FADE_FRAC). One constant for all of them makes
# every particle of a similar age reach zero on the SAME frame, which is a
# cliff in the lit count even though each one's brightness curve is smooth:
# measured 9.1% of his real cells winking out in one frame against the
# effect's own untold worst of 3.7%. Staggered, they go out a few at a time
# and the whole panel is still empty by WORD_SHAPE_HUSH_FADE_S.
WORD_SHAPE_HUSH_FADE_FRAC = (0.5, 1.0)
# W5.6 — THE QUIET, 80% SHORTER ("I think we can give it 80% less pre-fire
# darkness time"). W4.3's quiet was the whole stretch in front of the
# flight — the form's 2.0 s floor less the 0.8 s flight, so 1.2 s — and
# nothing ordinary launched from the SEQ edge all the way to the hold's
# end. Now the withholding is THIS LONG and no longer: 0.25 s (1.2 x 0.2),
# ending the frame the shaped burst leaves the centre. It is anchored to
# the LAUNCH rather than to the edge, so it is still "pre-fire" darkness
# for any told form (a form longer than hush + flight — impossible from the
# engine, which floors it at exactly that — would simply put the quiet
# later). `fx.device_model.WORD_SHAPE_FORM_MIN_S["fireworks"]` is this plus
# WORD_SHAPE_FLIGHT_S.
WORD_SHAPE_HUSH_S = 0.25
# W5.6 — AND FROM THE EDGE TO THE HOLD'S END THE ORDINARY SHOW IS DIMMED
# RATHER THAN WITHHELD: "The background doesn't need to be clear of other
# fireworks, just they need to be dimmer, so fading out already." Every
# ORDINARY (non-shaped) particle is drawn at this much of its own
# brightness — launches keep coming at the lower light, and the ones in the
# air at the edge are ALSO on W4.3's staggered life cap, which is the
# "fading out already" half of his sentence. 0.40 is what puts the ordinary
# light on the panel at the word under 45% of the same-seed untold frame's
# while leaving a show there at all (`scripts/check_fireworks_word_shape.py`
# prints both, and the bar is a DIM bar now, never a 0% one).
#
# IT IS A BRIGHTNESS, NOT A KILL: nothing is retimed, nothing is dropped,
# and the moment a phase or a clearing write takes over the dim ends — so a
# lull's rockets and a drop's payoff are never dimmed.
WORD_SHAPE_BACKGROUND_DIM = 0.40
# ... ramped in over this long from the SEQ edge, and back out over the
# whole RELEASE ("while the ordinary fireworks come back up"), so neither
# end of the dim is a step on the panel. The ramp in is the hush's own
# length deliberately: the dim is full by the frame the burst leaves.
WORD_SHAPE_DIM_RAMP_S = 0.25
# the shape's clock accumulates dt a frame, so a told time is reached to
# within a float's dust rather than exactly; this is the slack the hang and
# the form fraction flip on, so they land ON the word's own frame
WORD_SHAPE_CLOCK_EPS = 1e-6

# Every per-particle SoA array, in one place so compaction and the particle
# handoff native snapshot can never drift out of sync with each other.
_SOA_NAMES = (
    "p_x", "p_y", "p_vx", "p_vy", "p_age", "p_life",
    "p_grad", "p_bright", "p_shown", "p_rev", "p_rocket", "p_nocap",
    "p_wfade",
)


class Fireworks2d(Twod, GradientEffect):
    """Fireworks: bursts of particles erupt from random points (weighted
    toward the center), fly apart, decelerate, and fade with comet trails.
    Every particle of one firework shares a color; each firework picks its
    own at random from the gradient. Volume drives brightness, burst size
    and launch speed; spawn pacing mirrors Blackhole (spawn_rate +
    beat_burst + spawn_audio, capped by max_blobs).
    """

    NAME = "Fireworks"
    CATEGORY = "Matrix"
    # colors update in place — recreation would kill the particles.
    # phase/phase_progress are SpotFX-driven choreography; advanced (not
    # hidden) so the arc can be hand-scrubbed in the LedFX UI for tuning.
    # burst_rockets is the same kind of key (SpotFX's firework_burst flare
    # drives it; self-resets after firing).
    HIDDEN_KEYS = Twod.HIDDEN_KEYS + ["gradient_roll", "color_blend"]
    ADVANCED_KEYS = Twod.ADVANCED_KEYS + [
        "impulse_decay",
        "drag",
        "phase",
        "phase_progress",
        "burst_rockets",
        *pre_drop.KEYS,
        *phase_grammar.BREATH_KEYS,
        # WORD SHAPES: the six told keys ride ONLY SpotFX's own write
        # (word_shape_keys' rule 1) — never an editor surface, never the
        # param registry. The four tunables above them ARE registered.
        *word_shape_keys.KEYS,
    ]

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "gradient",
                description="Firework colors; each burst picks one at random",
                default="linear-gradient(90deg, #ff0000 0.00%,#ff7800 14.00%,#ffc800 28.00%,#00ff00 42.00%,#00c78c 56.00%,#0000ff 70.00%,#800080 84.00%,#ff00b2 98.00%)",
            ): validate_gradient,
            vol.Optional(
                "x_offset",
                description="X offset for center point",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "y_offset",
                description="Y offset for center point",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "radius_scale",
                description="Field scale as a fraction of the panel edge",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=2.0)),
            vol.Optional(
                "blob_size",
                description="Particle radius in pixels",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=6.0)),
            vol.Optional(
                "spawn_rate",
                description="Base fireworks launched per second; 0 = beat bursts only",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=60.0)),
            vol.Optional(
                "beat_burst",
                description="Extra fireworks launched on each beat",
                default=1,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=12)),
            vol.Optional(
                "spawn_audio",
                description="How much the selected band boosts the launch rate",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(
                "reverse",
                description="Implode: particles converge onto the burst point instead of exploding away",
                default=False,
            ): bool,
            vol.Optional(
                "burst_size",
                description="Particles per firework (music adds more)",
                default=12,
            ): vol.All(vol.Coerce(int), vol.Range(min=3, max=30)),
            vol.Optional(
                "burst_audio",
                description="How much the music volume grows each firework's particle count",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(
                "burst_speed",
                description="Base explosion speed, in radii per second",
                default=1.2,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=3.0)),
            vol.Optional(
                "burst_life",
                description="Seconds a particle lives after the explosion",
                default=1.2,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.3, max=3.0)),
            vol.Optional(
                "drag",
                description="How hard particles decelerate after the burst",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "speed_audio",
                description="How much the music boosts the explosion speed",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=5.0)),
            vol.Optional(
                "brightness_audio",
                description="How much the music pumps firework brightness",
                default=0.8,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(
                "max_blobs",
                description="Density cap: launching pauses at this many live particles",
                default=120,
            ): vol.All(vol.Coerce(int), vol.Range(min=20, max=1024)),
            vol.Optional(
                "trail_decay",
                description="Comet-trail length: 0 = crisp dots, 1 = long smear",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "frequency_range",
                description="Audio band driving spawn/speed/brightness reactivity",
                default="Lows (beat+bass)",
            ): vol.In(list(AudioReactiveEffect.POWER_FUNCS_MAPPING.keys())),
            vol.Optional(
                "impulse_decay",
                description="Decay filter applied to the audio impulse",
                default=0.06,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=0.3)),
            vol.Optional(
                "color_blend",
                description="Restart effect on color change, for transitions",
                default=False,
            ): bool,
            vol.Optional(
                "phase",
                description="Charge/lull/drop choreography phase (driven by SpotFX)",
                default="none",
            ): vol.In(["none", "charge", "lull", "drop"]),
            vol.Optional(
                "phase_progress",
                description="Progress through the current phase (ramped by SpotFX)",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "burst_rockets",
                description="Payoff bursts to explode right now (driven by SpotFX flares; self-resets)",
                default=0,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=12)),
            vol.Optional(
                "word_shape_size",
                description="Word shape: its half-height as a fraction of the panel's",
                default=0.62,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=1.0)),
            vol.Optional(
                "word_shape_outline_share",
                description="Word shape: the share of the burst's sparks that land on the outline",
                default=0.70,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=0.9)),
            # W5.6: BACK TO W1.2's 60/100. W4.3 raised them to 90/150 on
            # his "increase the amount of blobs by 50%"; his second room
            # verdict (2026-11-18) is "Let's turn back the increase in blob
            # count" — half of the answer to "it's too well-defined", the
            # other half being the looser break-apart end. These defaults
            # ARE his live values (no scene carries a word_shape_* param)
            # and they are duplicated in config/effect_params.json, which
            # one test pins against these.
            vol.Optional(
                "word_shape_sparks_quiet",
                description="Word shape: sparks in the burst at Energy 0",
                default=60,
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=400)),
            vol.Optional(
                "word_shape_sparks_loud",
                description="Word shape: sparks in the burst at Energy 1",
                default=100,
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=400)),
            # THE PRE-DROP: the four told keys and the breath-hold before it
            # (Fireworks is no breath-hold effect, so it is told a breath
            # only on a lull that plays a pre-drop) — fx/effects/pre_drop.py
            **pre_drop.schema_fields(),
            **phase_grammar.breath_schema_fields(),
            # WORD SHAPES: the six keys SpotFX's Word Shape kind writes
            **word_shape_keys.schema_fields(),
        }
    )

    def __init__(self, ledfx, config):
        super().__init__(ledfx, config)
        # Particle SoA + accumulators live here (NOT do_once) so they survive
        # config patches.
        self.p_x = np.zeros(CAP, dtype=np.float32)
        self.p_y = np.zeros(CAP, dtype=np.float32)
        self.p_vx = np.zeros(CAP, dtype=np.float32)
        self.p_vy = np.zeros(CAP, dtype=np.float32)
        self.p_age = np.zeros(CAP, dtype=np.float32)
        self.p_life = np.full(CAP, 1.0, dtype=np.float32)
        self.p_grad = np.zeros(CAP, dtype=np.float32)
        self.p_bright = np.zeros(CAP, dtype=np.float32)
        # last drawn brightness (fade applied) — exported in the handoff
        self.p_shown = np.zeros(CAP, dtype=np.float32)
        # 1 = reverse-spawned (imploding, runs its brightness curve backward)
        self.p_rev = np.zeros(CAP, dtype=np.float32)
        # 1 = lull rocket (position guided each frame; see _phase_rockets)
        self.p_rocket = np.zeros(CAP, dtype=np.float32)
        # 1.0 = spawned past the density cap (payoff, flare burst, drop
        # tail, lull rockets): never occupies max_blobs, so the ordinary
        # show keeps launching underneath — see _capacity
        self.p_nocap = np.zeros(CAP, dtype=np.float32)
        # WORD SHAPES: > 0 = a shaped spark, and the LENGTH of its own fade
        # window in seconds (the last stretch of its p_life). One array
        # carries both the flag and the fade, and because it is per spark a
        # second word's burst can never retime the first's fade-out.
        self.p_wfade = np.zeros(CAP, dtype=np.float32)
        self._soa = tuple(getattr(self, name) for name in _SOA_NAMES)
        self.n = 0
        self.spawn_acc = 0.0
        self.impulse = 0.0
        self._beat_pending = False
        self._rng = np.random.default_rng()
        self.trail = None
        # adopt a predecessor's on-screen particles on the first draw
        self._handoff_pending = True
        # held eruption while a radial predecessor collapses
        self._erupt_hold = None
        # THE KEEPERS MELD: seconds the adopted keeper rockets have waited
        # for the drop arm (None = no keepers held)
        self._keeper_hold_t = None
        # held pacman adoption while its maze fades out (phase 1)
        self._pacman_hold = None
        # outgoing-to-radial collapse state; None = normal physics
        self._collapse = None

        # Static dot-kernel offset table out to KERNEL_R
        span = np.arange(-KERNEL_R, KERNEL_R + 1)
        kdx, kdy = np.meshgrid(span, span)
        kdist = np.sqrt(kdx**2 + kdy**2).ravel()
        keep = kdist <= KERNEL_R
        self.k_dx = kdx.ravel()[keep].astype(np.int32)
        self.k_dy = kdy.ravel()[keep].astype(np.int32)
        self.k_dist = kdist[keep].astype(np.float32)

    def config_updated(self, config):
        super().config_updated(config)
        self.x_offset = self._config["x_offset"]
        self.y_offset = self._config["y_offset"]
        self.radius_scale = self._config["radius_scale"]
        self.blob_size = self._config["blob_size"]
        self.spawn_rate = self._config["spawn_rate"]
        self.beat_burst = int(self._config["beat_burst"])
        self.spawn_audio = self._config["spawn_audio"]
        self.reverse = self._config["reverse"]
        self.burst_size = int(self._config["burst_size"])
        self.burst_audio = self._config["burst_audio"]
        self.burst_speed = self._config["burst_speed"]
        self.burst_life = self._config["burst_life"]
        self.drag = self._config["drag"]
        self.speed_audio = self._config["speed_audio"]
        self.brightness_audio = self._config["brightness_audio"]
        self.max_blobs = int(self._config["max_blobs"])
        self.trail_decay = self._config["trail_decay"]
        self.word_shape_size = self._config["word_shape_size"]
        self.ws_outline_share = self._config["word_shape_outline_share"]
        self.ws_sparks_quiet = int(self._config["word_shape_sparks_quiet"])
        self.ws_sparks_loud = int(self._config["word_shape_sparks_loud"])

        self.power_func = self.POWER_FUNCS_MAPPING[
            self._config["frequency_range"]
        ]
        self.impulse_filter = self.create_filter(
            alpha_decay=self._config["impulse_decay"], alpha_rise=0.99
        )

        # charge/lull/drop: edge-detect the phase key. State is created here
        # (not __init__) because config_updated runs first, during
        # super().__init__; the pending flag is consumed in draw.
        new_phase = self._config.get("phase", "none")
        self.phase_progress = float(self._config.get("phase_progress", 0.0))
        if not hasattr(self, "_phase"):
            # creation baseline: a stale persisted phase key must never
            # edge-fire choreography on a fresh instance
            self._phase = "none"
            self._phase_t = 0.0
            self._phase_pending = None
            self._rocket_path = None
            self._phase_done_t = None
            self._pd_clk = None       # THE PRE-DROP's clock, read in draw
            # per-frame spawn-shaping multipliers (charge sets these)
            self._pspawn = 1.0
            self._pcount = 1.0
            self._pspeed = 1.0
            self._plife = 1.0
            # drop tail (its own clock; see _drop_tail_step)
            self._tail_t = None
            self._tail_rate = 0.0
            self._tail_acc = 0.0
        else:
            # non-creation pass: a changed phase key arms the edge
            self._phase_pending = new_phase if new_phase != self._phase else None

        # WORD SHAPES: edge-detect the SEQ, never the shape id — two words
        # of the same shape back to back must both fire (word_shape_keys).
        # The same creation-baseline rule as burst_rockets below: a fresh
        # instance built from a persisted config carrying a stale SEQ must
        # NOT fire. Nothing is written back; the effect runs the whole form,
        # hold and release on its own clock and resets itself after.
        ws_told = word_shape_keys.told(self._config)
        ws_seq = int(self._config.get(word_shape_keys.SEQ_KEY, 0) or 0)
        if not hasattr(self, "_ws_seq"):
            self._ws_seq = ws_seq
            self._ws_pending = None   # a told shape waiting for its frame
            self._ws_t = None         # the shape's own clock (None = idle)
            self._ws_form = 0.0       # the TOLD form: edge -> the word
            self._ws_total = 0.0      # form + hold + release, from the edge
            self._ws_frac = 0.0       # how far formed, 0..1
            self._ws_hang = False     # arrived: the sparks are damped
            self._ws_live = False     # any shaped spark still flying
            # armed at the edge, launched WORD_SHAPE_FLIGHT_S before the
            # word; the 0.25 s in front of the launch is THE QUIET (W5.6)
            self._ws_armed = None     # the told shape awaiting its launch
            self._ws_launch_at = 0.0  # when on this clock the burst leaves
            self._ws_hush = False     # no ordinary launch of any kind
            self._ws_hush_from = 0.0  # ... from here on this clock, until
            self._ws_hush_until = 0.0  # here (W5.6: the launch itself)
            # W5.6: the shape owns the ordinary show's BACKGROUND — the
            # quiet, and the DIM that outlasts it. A phase arriving or a
            # clearing write ends it for good (`_word_shape_clock`).
            self._ws_bg = False
            self._ws_dim = 0.0        # 0 = full brightness, 1 = fully dimmed
            self._ws_hold_end = 0.0   # form + hold, on this clock
            self._ws_release = 0.0    # the told release: the dim's own
            #                           return, and the break-apart's ramp
            self._ws_hung = False     # the arrival frame has been taken
        else:
            if ws_told is not None and ws_seq != self._ws_seq:
                self._ws_pending = ws_told
            elif ws_told is None and self._ws_bg:
                # A CLEARING WRITE ENDS THE QUIET AND THE DIM (W4.3's rule,
                # W5.6's two quantities). `told() is None` (the preview's
                # revert, an older SpotFX) says no shape is standing, and
                # holding the ordinary show down for a shape that will never
                # arrive is worse than doing nothing. The CLOCK is left
                # alone, so any spark already in the air keeps fading on its
                # own exactly as W1.2 has it — there is nothing to blend —
                # and a burst still in the barrel is dropped.
                self._ws_bg = False
                self._ws_hush = False
                self._ws_dim = 0.0
                self._ws_armed = None
            self._ws_seq = ws_seq

        # flare-driven payoff burst: edge-detect burst_rockets exactly like
        # the phase key (SpotFX writes a count, draw consumes it and
        # self-resets the key to 0 so an identical later write edges again)
        new_burst = int(self._config.get("burst_rockets", 0))
        if not hasattr(self, "_burst_seen"):
            # creation baseline: a stale persisted count must never explode
            # on a fresh instance
            self._burst_seen = new_burst
            self._burst_pending = 0
        elif new_burst != self._burst_seen:
            self._burst_seen = new_burst
            if new_burst > 0:
                self._burst_pending += new_burst

    def audio_data_updated(self, data):
        impulse = self.impulse_filter.update(
            getattr(data, self.power_func)()
        )
        self.impulse = float(impulse) if np.isfinite(impulse) else 0.0
        if data.bpm_beat_now():
            self._beat_pending = True

    def do_once(self):
        super().do_once()
        self.cx = (self.r_width - 1) * self.x_offset
        self.cy = (self.r_height - 1) * self.y_offset
        # Physics is circular in normalized space; this projection stretches
        # it into a panel-filling ellipse (same convention as Blackhole).
        self.sx = self.radius_scale * (self.r_width - 1) / 2.0
        self.sy = self.radius_scale * (self.r_height - 1) / 2.0
        # normalized radius of the farthest panel corner (+ margin): the
        # cull bound for flyaway particles
        corners = []
        for px in (0.0, self.r_width - 1.0):
            for py in (0.0, self.r_height - 1.0):
                gx = (px - self.cx) / max(self.sx, 1e-6)
                gy = (py - self.cy) / max(self.sy, 1e-6)
                corners.append(np.hypot(gx, gy))
        self.r_max = float(max(corners)) + 0.15
        # WORD SHAPES: one real-cell pitch in this field's own normalized
        # units, averaged over the two axes — a crystal column is half a
        # pitch and a row sqrt(3)/2 of one (.claude/skills/crystal-hex-grid),
        # so a jitter measured in cells needs both. The scale an outline
        # target's radial jitter is drawn in.
        self._ws_pitch = 0.5 * (
            2.0 / max(self.sx, 1e-6)
            + (2.0 / np.sqrt(3.0)) / max(self.sy, 1e-6)
        )
        if self.trail is None or self.trail.shape[:2] != (
            self.r_height,
            self.r_width,
        ):
            self.trail = np.zeros(
                (self.r_height, self.r_width, 3), dtype=np.float32
            )

    def _compact(self, alive, *extra):
        count = int(np.count_nonzero(alive))
        for arr in self._soa:
            arr[:count] = arr[: self.n][alive]
        self.n = count
        return tuple(arr[alive] for arr in extra)

    # ── spawning ────────────────────────────────────────────────────────

    def _capacity(self):
        """Room left under the density cap for ORDINARY launches. Particles
        spawned past the cap (p_nocap: the drop payoff, a flare burst, the
        drop tail, lull rockets) don't occupy it — they layer on top of
        the ordinary show rather than pausing it for as long as they live
        (a payoff used to hold the cap full for PAYOFF_LIFE x burst_life,
        silencing every ordinary launch until it faded)."""
        n = self.n
        occupied = n - int(np.count_nonzero(self.p_nocap[:n]))
        return int(min(self.max_blobs, CAP) - occupied)

    def _burst_brightness(self):
        """Launch brightness from the music volume."""
        return float(
            np.clip(0.45 + self.brightness_audio * self.impulse, 0.2, 1.0)
        )

    def _burst_count(self):
        """Particles for one firework: burst_size grown by the volume —
        quiet passages shrink bursts, loud ones grow them, burst_audio 0
        pins them at exactly burst_size."""
        scale = np.clip(
            1.0 + self.burst_audio * (min(self.impulse, 1.0) - 0.4),
            0.4,
            2.0,
        )
        return int(round(self.burst_size * scale * self._pcount)) or 1

    def _spawn_burst(
        self, k, ox=None, oy=None, grad=None,
        speed_mult=1.0, bright=None, life_mult=1.0, ignore_cap=False,
    ):
        """One firework: k particles from one origin, one shared color,
        uniformly spread directions with speed jitter. ignore_cap bypasses
        max_blobs (the drop payoff must always land)."""
        room = (CAP - self.n) if ignore_cap else self._capacity()
        k = int(min(k, room))
        if k <= 0:
            return
        rng = self._rng
        if ox is None:
            # random origin, weighted toward the center
            rr = (rng.random() ** CENTER_BIAS) * SPAWN_FIELD
            ang = rng.uniform(0.0, 2 * np.pi)
            ox = rr * np.cos(ang)
            oy = rr * np.sin(ang)
        if grad is None:
            grad = rng.random()
        if bright is None:
            bright = self._burst_brightness()
        s = slice(self.n, self.n + k)
        dirs = rng.uniform(0.0, 2 * np.pi, k)
        speed = (
            self.burst_speed
            * speed_mult
            * self._pspeed
            * (1.0 + self.speed_audio * min(self.impulse, 1.0))
            * rng.uniform(0.55, 1.15, k)
        )
        lives = (
            self.burst_life * life_mult * self._plife
            * rng.uniform(0.7, 1.15, k)
        )
        if self.reverse:
            # implosion: each particle starts out at exactly the distance
            # its drag-decelerated flight covers over its life, and flies
            # INWARD — converging onto the burst point as it fades out
            hl = max(0.6 - 0.5 * self.drag, 0.05)
            dist = speed * (hl / np.log(2)) * (
                1.0 - np.power(2.0, -lives / hl)
            )
            self.p_x[s] = ox + dist * np.cos(dirs)
            self.p_y[s] = oy + dist * np.sin(dirs)
            self.p_vx[s] = -speed * np.cos(dirs)
            self.p_vy[s] = -speed * np.sin(dirs)
        else:
            self.p_x[s] = ox
            self.p_y[s] = oy
            self.p_vx[s] = speed * np.cos(dirs)
            self.p_vy[s] = speed * np.sin(dirs)
        self.p_age[s] = 0.0
        self.p_life[s] = lives
        self.p_grad[s] = grad
        self.p_bright[s] = bright
        self.p_shown[s] = 0.0
        self.p_rev[s] = 1.0 if self.reverse else 0.0
        self.p_rocket[s] = 0.0
        self.p_nocap[s] = 1.0 if ignore_cap else 0.0
        self.p_wfade[s] = 0.0
        self.n += k

    def _import_flyers(self, xs, ys, grads, brights, ncx, ncy, speed_mult=1.0):
        """Adopt predecessor particles at their positions, flying radially
        outward from (ncx, ncy) — used for the blackhole handoff."""
        k = int(min(len(xs), self._capacity()))
        if k <= 0:
            return
        rng = self._rng
        s = slice(self.n, self.n + k)
        dx = xs[:k] - ncx
        dy = ys[:k] - ncy
        dist = np.hypot(dx, dy)
        # random directions where a particle sits exactly on the origin
        rnd = rng.uniform(0.0, 2 * np.pi, k)
        ux = np.where(dist > 1e-4, dx / np.maximum(dist, 1e-6), np.cos(rnd))
        uy = np.where(dist > 1e-4, dy / np.maximum(dist, 1e-6), np.sin(rnd))
        speed = (
            self.burst_speed
            * speed_mult
            * (1.0 + self.speed_audio * min(self.impulse, 1.0))
            * rng.uniform(0.7, 1.2, k)
        )
        self.p_x[s] = xs[:k]
        self.p_y[s] = ys[:k]
        self.p_vx[s] = ux * speed
        self.p_vy[s] = uy * speed
        self.p_age[s] = 0.0
        self.p_life[s] = self.burst_life * rng.uniform(0.8, 1.2, k)
        self.p_grad[s] = grads[:k]
        self.p_bright[s] = np.clip(brights[:k], 0.3, 1.0)
        self.p_shown[s] = 0.0
        self.p_rev[s] = 0.0  # handoff flyers always run forward
        self.p_rocket[s] = 0.0
        self.p_nocap[s] = 0.0
        self.p_wfade[s] = 0.0
        self.n += k

    # ── handoff ─────────────────────────────────────────────────────────

    def _handoff_snapshot(self):
        """Live particle state in the neutral handoff format (see
        particle_handoff module). None before the first render."""
        if getattr(self, "r_width", None) is None or self.trail is None:
            return None
        n = self.n
        px = self.cx + self.p_x[:n] * self.sx
        py = self.cy + self.p_y[:n] * self.sy
        return {
            "src": "fireworks",
            "t": particle_handoff.now(),
            "dims": (self.r_width, self.r_height),
            "px": px.astype(np.float32),
            "py": py.astype(np.float32),
            # each spark's velocity (px/s) and how the form lets go — the
            # transition program's RELEASE reads these (particle_handoff)
            "vx": (self.p_vx[:n] * self.sx).astype(np.float32),
            "vy": (self.p_vy[:n] * self.sy).astype(np.float32),
            "gesture": "spray",
            "grad": self.p_grad[:n].copy(),
            "bright": self.p_shown[:n].copy(),
            "gradient": self._config.get("gradient"),
            "spin_sign": 0.0,   # fireworks has no rotation to continue
            "blob_size": float(self.blob_size),
            "flow": "in" if self.reverse else "out",
            "center_px": (float(self.cx), float(self.cy)),
            "trail": self.trail,
            "native": {
                "n": n,
                "spawn_acc": self.spawn_acc,
                "arrays": {
                    name: getattr(self, name)[:n].copy()
                    for name in _SOA_NAMES
                },
            },
        }

    def deactivate(self):
        virtual = self._virtual
        try:
            if virtual is not None:
                particle_handoff.store(virtual.id, self._handoff_snapshot())
        except Exception:
            pass
        super().deactivate()

    def _adopt_handoff(self, snap=None, allow_hold=True):
        """First-draw adoption: blackhole → horizon + strays explode;
        orbits → every particle bursts; radial → held grand burst from the
        center; fireworks → native restore. A pre-fetched `snap` (the
        pacman-hold release path) skips the fetch."""
        virtual = self._virtual
        live = snap is not None
        if snap is None:
            sibling = (
                getattr(virtual, "_transition_effect", None) if virtual else None
            )
            if sibling is not None and sibling is not self and hasattr(
                sibling, "_handoff_snapshot"
            ):
                try:
                    snap = sibling._handoff_snapshot()
                except Exception:
                    snap = None
            live = snap is not None
            if snap is None and virtual is not None:
                snap = particle_handoff.take(getattr(virtual, "id", "") or "")
        if not snap or tuple(snap["dims"]) != (self.r_width, self.r_height):
            return
        if snap["src"] in ("pacman", "dancer") and live and allow_hold:
            # pacman fades its maze (dancer: somersaults out) over phase 1 — hold the
            # adoption until the entities morph at PACMAN_MORPH_START
            frac = particle_handoff.transition_progress(virtual)
            if frac is not None and frac < particle_handoff.PACMAN_MORPH_START:
                self._pacman_hold = {
                    "snap": snap,
                    "t0": particle_handoff.now(),
                }
                return
        if (
            snap.get("trail") is not None
            and self.trail is not None
            and snap["trail"].shape == self.trail.shape
        ):
            np.maximum(self.trail, snap["trail"], out=self.trail)
        if snap.get("append") and snap.get("vx") is not None:
            # a transition program's FOUNTAIN / FLAME LICK hands its sparks
            # over still flying (fx/effects/transition_cloud.py, VENDOR #75)
            self._import_sparks(snap)
            return
        if snap["src"] == "fireworks":
            native = snap["native"]
            k = min(native["n"], CAP)
            for name, arr in native["arrays"].items():
                if hasattr(self, name):
                    getattr(self, name)[:k] = arr[:k]
            self.n = k
            self.spawn_acc = float(native.get("spawn_acc", 0.0))
            return
        # cross-type: carry the predecessor's gradient so colors stay
        # continuous — SpotFX repaints on its next color action.
        g = snap.get("gradient")
        if g and g != self._config.get("gradient"):
            self._apply_config({"gradient": g}, validate=False, fire_event=False)
        c_px = snap.get("center_px") or (self.cx, self.cy)
        ncx = (float(c_px[0]) - self.cx) / max(self.sx, 1e-6)
        ncy = (float(c_px[1]) - self.cy) / max(self.sy, 1e-6)
        if snap["src"] == "radial":
            # implode first (radial owns phase 1), then one grand firework
            if live and particle_handoff.transition_progress(virtual) is not None:
                self._erupt_hold = {
                    "ncx": ncx,
                    "ncy": ncy,
                    "t0": particle_handoff.now(),
                }
            else:
                self._grand_burst(ncx, ncy)
            return
        xs = (snap["px"] - self.cx) / max(self.sx, 1e-6)
        ys = (snap["py"] - self.cy) / max(self.sy, 1e-6)
        if snap["src"] == "blackhole":
            # the event horizon explodes with a safe number of particles;
            # the rest fly away too (brightest first, capacity-capped)
            cap_mask = snap.get("captured")
            bright = snap["bright"]
            if cap_mask is not None and len(cap_mask) == len(bright):
                captured = np.flatnonzero(cap_mask)
                rest = np.flatnonzero(~cap_mask)
            else:
                captured = np.empty(0, dtype=np.int64)
                rest = np.arange(len(bright))
            captured = captured[np.argsort(bright[captured])[::-1]]
            captured = captured[:SAFE_CAPTURED]
            rest = rest[np.argsort(bright[rest])[::-1]]
            for idx, mult in ((captured, 1.3), (rest, 1.0)):
                if idx.size:
                    self._import_flyers(
                        xs[idx], ys[idx], snap["grad"][idx],
                        bright[idx], ncx, ncy, speed_mult=mult,
                    )
            return
        # THE KEEPERS MELD (module constants): a lull told it leads into
        # Fireworks flagged the pieces it kept — each becomes a held rocket
        # where it stands, for the drop's payoff to explode
        keepers = snap.get("keepers")
        if keepers is not None and len(keepers) == len(xs) and np.any(keepers):
            keepers = np.asarray(keepers, dtype=bool)
            kidx = np.flatnonzero(keepers)
            self._import_keepers(
                xs[kidx], ys[kidx], snap["grad"][kidx], snap["bright"][kidx]
            )
            rest = np.flatnonzero(~keepers)
        else:
            rest = np.arange(len(xs))
        # orbits: every particle explodes as its own firework, keeping
        # its color for the whole burst
        m = rest.size
        if m <= 0:
            return
        per = int(np.clip(self.max_blobs // max(m, 1), 4, self.burst_size))
        order = rest[np.argsort(snap["bright"][rest])[::-1]]
        for i in order:
            if self._capacity() <= 0:
                break
            self._spawn_burst(
                per,
                ox=float(xs[i]),
                oy=float(ys[i]),
                grad=float(snap["grad"][i]),
                bright=float(np.clip(snap["bright"][i], 0.4, 1.0)),
            )

    def _import_sparks(self, snap):
        """A transition program's sparks join as ordinary fireworks sparks
        AT their positions WITH their velocities (px/s -> this field's
        normalized units), already past their fade-in, each brightness set
        so its first shown frame equals what the program last drew — one
        motion and one picture across the hand-off. Appended to whatever
        this effect launched while the program ran; capacity-capped."""
        k = int(min(len(snap["px"]), CAP - self.n))
        if k <= 0:
            return
        s = slice(self.n, self.n + k)
        sx, sy = max(self.sx, 1e-6), max(self.sy, 1e-6)
        self.p_x[s] = (np.asarray(snap["px"][:k], np.float32) - self.cx) / sx
        self.p_y[s] = (np.asarray(snap["py"][:k], np.float32) - self.cy) / sy
        self.p_vx[s] = np.asarray(snap["vx"][:k], np.float32) / sx
        self.p_vy[s] = np.asarray(snap["vy"][:k], np.float32) / sy
        life = snap.get("life")
        if life is None or len(life) < k:
            life = self.burst_life * self._rng.uniform(0.8, 1.2, k)
        life = np.maximum(np.asarray(life[:k], np.float32), 2.0 * FADE_IN_S)
        age = np.full(k, FADE_IN_S, dtype=np.float32)
        # the forward envelope's value at that age (the draw's own formula)
        env = (1.0 - age / life) ** 1.4
        shown = np.clip(np.asarray(snap["bright"][:k], np.float32), 0.0, 1.0)
        self.p_age[s] = age
        self.p_life[s] = life
        self.p_grad[s] = np.asarray(snap["grad"][:k], np.float32)
        self.p_bright[s] = np.clip(shown / np.maximum(env, 1e-3), 0.0, 1.0)
        self.p_shown[s] = shown
        self.p_rev[s] = 0.0
        self.p_rocket[s] = 0.0
        self.p_nocap[s] = 1.0   # the hand-off must land whole
        self.p_wfade[s] = 0.0
        self.n += k

    def _program_field_velocity(self, px, py, vx, vy, dt):
        """What a spark here moving at (vx, vy) px/s does over dt: this
        field's own drag (the draw's half-life). A transition program's
        last stretch flies its sparks by it, so the hand-off continues one
        motion (fx/effects/transition_cloud.py)."""
        hl = max(0.6 - 0.5 * self.drag, 0.05)
        decel = np.float32(0.5 ** (dt / hl))
        return vx * decel, vy * decel

    def _import_keepers(self, xs, ys, grads, brights):
        """THE KEEPERS MELD: hold each adopted keeper as a stationary rocket
        at its own position and colour (p_rocket with no flight path — the
        lull's guided-rocket machinery never moves it), so the drop arm's
        _rocket_payoff explodes it where it stands. Uncapped like every
        rocket (p_nocap); at most KEEPER_ROCKETS_MAX."""
        k = int(min(len(xs), KEEPER_ROCKETS_MAX, CAP - self.n))
        if k <= 0:
            return
        s = slice(self.n, self.n + k)
        self.p_x[s] = xs[:k]
        self.p_y[s] = ys[:k]
        self.p_vx[s] = 0.0
        self.p_vy[s] = 0.0
        self.p_age[s] = 0.0
        self.p_life[s] = 1e6  # held: the payoff (or the hold's end) ends it
        self.p_grad[s] = grads[:k]
        self.p_bright[s] = np.clip(brights[:k], 0.6, 1.0)
        self.p_shown[s] = 0.0
        self.p_rev[s] = 0.0
        self.p_rocket[s] = 1.0
        self.p_nocap[s] = 1.0
        self.p_wfade[s] = 0.0
        self.n += k
        self._rocket_path = None
        self._keeper_hold_t = 0.0

    def _release_keepers(self):
        """The keepers' hold ran out with no drop arm (or a lull is about
        to launch its own rockets): each held keeper bursts as an ordinary
        firework where it stands — the adopt path's generic shape."""
        self._keeper_hold_t = None
        n = self.n
        idx = np.flatnonzero(self.p_rocket[:n] > 0.0)
        if idx.size == 0:
            return
        origins = [(float(self.p_x[i]), float(self.p_y[i]),
                    float(self.p_grad[i]), float(self.p_bright[i]))
                   for i in idx]
        self.p_life[idx] = 0.0
        self.p_rocket[idx] = 0.0
        per = int(np.clip(self.max_blobs // max(len(origins), 1), 4,
                          self.burst_size))
        for ox, oy, grad, bright in origins:
            self._spawn_burst(per, ox=ox, oy=oy, grad=grad, bright=bright)

    def _grand_burst(self, ncx, ncy):
        """The big firework a collapsed radial turns into."""
        self._spawn_burst(
            min(self.burst_size * 2, self._capacity()),
            ox=ncx,
            oy=ncy,
            speed_mult=1.4,
            bright=1.0,
        )

    # ── charge/lull/drop choreography ───────────────────────────────────
    # SpotFX writes `phase` (instant) and ramps `phase_progress` 0→1 over
    # the event's ramp. charge: launch rate climbs while the fireworks
    # shrink; lull: launching stops and LULL_ROCKETS slow rockets cross the
    # dark panel from the edges toward offset points past the center,
    # dimming as they travel (trails come free from the trail buffer);
    # drop: each rocket explodes into a giant firework in its own color,
    # then `phase` self-resets to "none" while the drop tail (its own
    # clock, _drop_tail_step) keeps a shower of ordinary fireworks
    # launching through the payoff's afterglow, easing back to the
    # ordinary show.

    def _rocket_start_angles(self, k):
        """THE ONE angular plan for a volley of k travelling rockets: evenly
        spaced around the rim, the whole ring randomly rotated per launch
        (never the same drop twice), each rocket nudged by at most
        LULL_ROCKET_WIGGLE_FRAC of the step. Anything else that ever spawns
        drop rockets must take its angles from here, never draw its own —
        two independent draws clump (the pre-2026-08-21 defect)."""
        rng = self._rng
        step = 2 * np.pi / k
        base = rng.uniform(0.0, 2 * np.pi)
        wiggle = step * LULL_ROCKET_WIGGLE_FRAC
        return base + np.arange(k) * step + rng.uniform(-wiggle, wiggle, k)

    def _launch_rockets(self):
        k = int(min(LULL_ROCKETS, CAP - self.n))
        if k <= 0:
            return
        rng = self._rng
        ang = self._rocket_start_angles(k)
        start_r = float(getattr(self, "r_max", 1.3)) - 0.05
        end_r = rng.uniform(0.36, 0.76, k)  # ~2x his prior 0.18-0.38 past center
        end_ang = ang + np.pi + rng.uniform(-0.5, 0.5, k)
        sx_ = (start_r * np.cos(ang)).astype(np.float32)
        sy_ = (start_r * np.sin(ang)).astype(np.float32)
        ex_ = (end_r * np.cos(end_ang)).astype(np.float32)
        ey_ = (end_r * np.sin(end_ang)).astype(np.float32)
        s = slice(self.n, self.n + k)
        self.p_x[s] = sx_
        self.p_y[s] = sy_
        self.p_vx[s] = 0.0
        self.p_vy[s] = 0.0
        self.p_age[s] = 0.0
        self.p_life[s] = 1e6  # guided: never age out
        self.p_grad[s] = rng.random(k, dtype=np.float32)
        self.p_bright[s] = 1.0
        self.p_shown[s] = 0.0
        self.p_rev[s] = 0.0
        self.p_rocket[s] = 1.0
        self.p_nocap[s] = 1.0
        self.p_wfade[s] = 0.0
        self.n += k
        self._rocket_path = {"sx": sx_, "sy": sy_, "ex": ex_, "ey": ey_}

    def _phase_rockets(self):
        """Guide the lull rockets along their start→end paths. Flight is
        progress-driven with a wall-clock fallback; brightness dims with
        distance travelled."""
        path = self._rocket_path
        if path is None:
            return
        n = self.n
        idx = np.flatnonzero(self.p_rocket[:n] > 0.0)
        m = min(idx.size, len(path["sx"]))
        if m <= 0:
            return
        idx = idx[:m]
        clk = self._pd_clk
        if clk is not None and clk.segment == "pre_drop":
            # THE PRE-DROP's rockets fly the pre-drop-to-drop gap on the
            # effect's own clock, staying bright
            f = clk.frac
            fade = pre_drop_rocket_fade(pre_drop.gap_s(self._config))
        else:
            # progress-driven once it moves (hand-scrubbable in the LedFX
            # UI); the wall-clock fallback only runs while progress sits at
            # 0 so a lost ramp still flies the rockets in
            p = float(np.clip(self.phase_progress, 0.0, 1.0))
            f = p if p > 0.0 else min(self._phase_t / LULL_FLIGHT_S, 1.0)
            fade = LULL_ROCKET_FADE
        ease = 1.0 - (1.0 - f) ** 2  # launch fast, drift into the target
        self.p_x[idx] = path["sx"][:m] + (path["ex"][:m] - path["sx"][:m]) * ease
        self.p_y[idx] = path["sy"][:m] + (path["ey"][:m] - path["sy"][:m]) * ease
        self.p_bright[idx] = 1.0 - fade * f

    def _rocket_payoff(self):
        """Drop: every rocket explodes into a giant firework in its own
        color, at wherever it is right now. Without rockets (drop with no
        lull) the payoff is a spread of giant bursts near the center."""
        n = self.n
        idx = np.flatnonzero(self.p_rocket[:n] > 0.0)
        if idx.size:
            origins = [
                (
                    float(self.p_x[i]),
                    float(self.p_y[i]),
                    float(self.p_grad[i]),
                )
                for i in idx
            ]
            self.p_life[idx] = 0.0  # rockets die into their explosions
        else:
            rng = self._rng
            origins = [
                (
                    float(rng.uniform(-0.3, 0.3)),
                    float(rng.uniform(-0.3, 0.3)),
                    float(rng.random()),
                )
                for _ in range(LULL_ROCKETS)
            ]
        for ox, oy, grad in origins:
            self._payoff_burst_at(ox, oy, grad)
        self._rocket_path = None

    def _payoff_burst_at(self, ox, oy, grad):
        """One giant firework in its own color at one origin — the drop
        payoff's own spawn shape, shared verbatim by the flare-driven
        burst (_flare_burst) so the two can never drift."""
        count = max(int(round(self.burst_size * 2.5)), 24)
        self._spawn_burst(
            count,
            ox=ox,
            oy=oy,
            grad=grad,
            speed_mult=PAYOFF_SPEED,
            bright=1.0,
            life_mult=PAYOFF_LIFE,
            ignore_cap=True,
        )

    def _flare_burst(self, count):
        """`count` payoff bursts explode NOW — the flare-driven burst
        (burst_rockets, written by SpotFX's firework_burst flare kind).
        Each is _rocket_payoff's own giant firework at its own no-rocket
        origin spread near the center — purely additive on top of whatever
        is already flying (ignore_cap, and no live particle, rocket, or
        phase state is touched)."""
        rng = self._rng
        for _ in range(count):
            self._payoff_burst_at(
                float(rng.uniform(-0.3, 0.3)),
                float(rng.uniform(-0.3, 0.3)),
                float(rng.random()),
            )

    # ── word shapes ─────────────────────────────────────────────────────
    # THE SHAPED PAYOFF BURST (the module constants are the binding
    # statement; .claude/skills/word-shapes/SKILL.md is the contract above
    # it). One burst per told word, from the centre, arriving ON the word.

    def _word_shape_clock(self, dt):
        """Advance the shape's own clock, ARM a told shape, and run THE
        HUSH. Runs at the top of `draw`, BEFORE the spawn block, which is
        what lets the hush take the edge frame's own launches with it.

        The clock runs from the SEQ EDGE: `_ws_form` is the whole TOLD form,
        so `_ws_frac` still reads 1.0 and `_ws_hang` still flips ON THE WORD
        however long before it the burst actually left (W4.3). It sets how
        far formed the shape is, whether it has ARRIVED (from that frame on
        its sparks are damped where they stand — the hang), and resets
        itself once the whole form, hold and release is over, by which point
        every one of its sparks has outlived its own `p_life`. The LAUNCH is
        not here but in `draw`, where the frame's own dt is what the launch
        velocities are solved against."""
        if self._ws_bg and self._phase != "none":
            # A PHASE OWNS THE PANEL. P3 A means a shape is never told while
            # a charge, lull or drop is armed; one ARRIVING on a standing
            # shape ends the quiet AND the dim, so the drop payoff and its
            # tail fire at full brightness as they do today and the shaped
            # sparks keep flying over them. (`_phase_step` runs first, so an
            # arrival is already visible.) A lull's own rockets are
            # therefore never dimmed either.
            self._ws_bg = False
        if self._ws_t is not None:
            self._ws_t += dt
            # the clock accumulates dt a frame, so the word's own instant is
            # reached to within a float's dust rather than exactly: EPS is
            # what keeps the hang flipping ON the word's frame instead of
            # the one after it
            arrived = self._ws_t >= self._ws_form - WORD_SHAPE_CLOCK_EPS
            self._ws_frac = (1.0 if self._ws_form <= 0.0 or arrived
                             else min(1.0, self._ws_t / self._ws_form))
            self._ws_hang = arrived
            if self._ws_t >= self._ws_total:
                self._ws_t = None
                self._ws_frac = 0.0
                self._ws_hang = False
                self._ws_hung = False
                self._ws_armed = None
                self._ws_bg = False
        if self._ws_pending is not None:
            told = self._ws_pending
            self._ws_pending = None
            self._word_shape_arm(told)
        # W5.6 — THE QUIET AND THE DIM, both derived from the one clock.
        # The quiet (`_ws_hush`) is WORD_SHAPE_HUSH_S long and ends the
        # frame the burst leaves; the dim rides the whole envelope: in over
        # WORD_SHAPE_DIM_RAMP_S from the edge, full through the form and the
        # hold, out over the release as the ordinary fireworks come back up.
        self._ws_hush = False
        self._ws_dim = 0.0
        if self._ws_bg and self._ws_t is not None:
            t = self._ws_t
            self._ws_hush = bool(
                t >= self._ws_hush_from - WORD_SHAPE_CLOCK_EPS
                and t < self._ws_hush_until - WORD_SHAPE_CLOCK_EPS)
            if t <= self._ws_hold_end:
                self._ws_dim = float(min(
                    1.0, t / max(WORD_SHAPE_DIM_RAMP_S, 1e-6)))
            else:
                self._ws_dim = float(max(0.0, 1.0 - (t - self._ws_hold_end)
                                         / max(self._ws_release, 1e-6)))
        if self._ws_hush:
            # a `burst_rockets` poke landing in the quiet is DROPPED, not
            # deferred — the pre-drop breath's own swallow. `draw` still
            # self-resets the key, so an identical later write edges again.
            self._burst_pending = 0

    def _word_shape_arm(self, told):
        """THE SEQ EDGE: the shape's clock starts and the shape takes over
        the ordinary show's BACKGROUND, but nothing is launched yet — the
        burst leaves the centre WORD_SHAPE_FLIGHT_S before the word
        (`draw`'s launch block).

        W5.6 SPLIT THAT TAKEOVER IN TWO, because his second verdict is "the
        background doesn't need to be clear of other fireworks, just they
        need to be dimmer, so fading out already":

          * THE QUIET — the only withholding left — is the
            WORD_SHAPE_HUSH_S (0.25 s) immediately BEFORE the launch, so the
            burst leaves into a lull of its own rather than onto a fresh
            beat's rockets;
          * THE DIM runs from here to the END OF THE HOLD and back out over
            the release: the ordinary show keeps launching, every ordinary
            spark drawn at WORD_SHAPE_BACKGROUND_DIM of its own brightness
            (the brightness block in `draw`).

        What is already in the air is NOT killed and never was: each
        particle's remaining life is capped at its OWN share of
        WORD_SHAPE_HUSH_FADE_S (over WORD_SHAPE_HUSH_FADE_FRAC — see that
        constant for why one number for all of them is a cliff), so they
        fade out a few at a time rather than blinking out together, which is
        exactly his "so fading out already". Lull rockets are left alone —
        they are a phase's own choreography, not the ordinary show, and
        capping their life would cut a lull's rockets off mid-flight."""
        form = max(float(told.form_s), WORD_SHAPE_MIN_FORM_S)
        hold = max(float(told.hold_s), 0.0)
        release = max(float(told.release_s), WORD_SHAPE_MIN_FADE_S)
        self._ws_armed = told
        self._ws_t = 0.0
        self._ws_form = form
        self._ws_total = form + hold + release
        self._ws_frac = 0.0
        self._ws_hang = False
        # the flight sits INSIDE the form, so the burst looks as it did; a
        # told form shorter than it (impossible from the engine, which
        # floors the form) simply launches at the edge
        self._ws_launch_at = form - min(WORD_SHAPE_FLIGHT_S, form)
        # W5.6: the quiet is the 0.25 s in front of the LAUNCH, clamped to
        # the clock's own start — a form of exactly hush + flight (the
        # engine's floor for this effect) runs it from the edge to the
        # launch, and a shorter one simply has less of it
        self._ws_hush_until = self._ws_launch_at
        self._ws_hush_from = max(0.0, self._ws_launch_at - WORD_SHAPE_HUSH_S)
        self._ws_bg = True
        self._ws_hush = bool(self._ws_hush_from <= WORD_SHAPE_CLOCK_EPS
                             < self._ws_hush_until)
        self._ws_dim = 0.0
        self._ws_hold_end = form + hold
        self._ws_release = release
        self._ws_hung = False
        self._burst_pending = 0
        self.spawn_acc = 0.0
        self._beat_pending = False
        self._tail_acc = 0.0
        n = self.n
        if n:
            idx = np.flatnonzero((self.p_wfade[:n] <= 0.0)
                                 & (self.p_rocket[:n] <= 0.0))
            if idx.size:
                lo, hi = WORD_SHAPE_HUSH_FADE_FRAC
                self.p_life[idx] = np.minimum(
                    self.p_life[idx],
                    self.p_age[idx] + WORD_SHAPE_HUSH_FADE_S
                    * self._rng.uniform(lo, hi, idx.size))

    def _word_shape_burst(self, told, dt, flight):
        """ONE shaped firework: `k` sparks from the centre, `outline_share`
        of them aimed at the shape's own outline (uniformly by ARC LENGTH
        plus up to half a cell of radial jitter) and the rest at a random
        depth inside it — nothing on a lattice, because his ask ends "it
        also needs to still appear random".

        `flight` is the time LEFT to the word (W4.3), not the whole told
        form: the burst leaves the centre WORD_SHAPE_FLIGHT_S before the
        word and the stretch in front of it is THE HUSH emptying the panel.
        The sparks therefore live `flight + hold + their own fade`, which
        ends exactly where W1.2's own `form + hold + fade` did.

        EVERY SPARK'S LAUNCH VELOCITY IS SOLVED FROM THE DRAG IT WILL
        ACTUALLY BE INTEGRATED WITH — since W5.6 the shaped sparks' own
        WORD_SHAPE_FLIGHT_HL_S (0.65 s) rather than this effect's
        `0.6 - 0.5*drag` (0.255 s at his drag), because a 2 s flight under
        the effect's own kernel would land every spark in its first fifth
        and leave it sitting. `draw` integrates `x += v*dt` and then
        `v *= 0.5**(dt/hl)` once per frame, so the distance one unit of
        launch speed covers over `m` frames is a geometric sum — computed
        once per burst for the frame rate this effect is actually
        integrating at — and dividing the target by it lands the spark on
        the target the frame the FLIGHT ends, which is the word. That is
        what makes "the shape arrives ON the word" a measured claim
        (tests/test_fireworks_word_shape.py
        asserts every spark inside one cell of its target) rather than a
        hope.

        The sparks are uncapped (`p_nocap`, the Firework Burst flare's own
        rule) and additive: no live particle, rocket or phase state is
        touched here. What the hush does to the ordinary show happens at the
        EDGE, in `_word_shape_arm`, not in this burst."""
        shape = word_shapes.get(told.shape)
        rng = self._rng
        level = float(np.clip(told.level, 0.0, 1.0))
        quiet, loud = float(self.ws_sparks_quiet), float(self.ws_sparks_loud)
        k = int(round(quiet + (loud - quiet) * level))
        k = int(min(max(k, 0), CAP - self.n))
        if k <= 0:
            return
        share = float(np.clip(self.ws_outline_share, 0.0, 1.0))
        n_out = int(min(max(int(round(k * share)), 0), k))
        n_in = k - n_out
        size = float(self.word_shape_size)

        # the targets, in this field's own normalized space (SIZE is the
        # shape's half-height as a FRACTION of the panel's — word_shapes)
        tx = np.zeros(k, dtype=np.float64)
        ty = np.zeros(k, dtype=np.float64)
        if n_out:
            ox, oy = shape.at(rng.random(n_out))
            safe = np.maximum(np.hypot(ox, oy), 1e-9)
            jit = rng.uniform(-1.0, 1.0, n_out) * (
                WORD_SHAPE_JITTER_PITCH * self._ws_pitch)
            tx[:n_out] = size * ox + jit * (ox / safe)
            ty[:n_out] = size * oy + jit * (oy / safe)
        if n_in:
            # a random point on the outline pulled in to a random depth:
            # every shipped shape is star-shaped about its centre, so that
            # point is inside it, and no sdf grid is built on a render frame
            ix, iy = shape.at(rng.random(n_in))
            lo, hi = WORD_SHAPE_FILL_DEPTH
            depth = np.sqrt(rng.uniform(lo * lo, hi * hi, n_in))
            tx[n_out:] = size * ix * depth
            ty[n_out:] = size * iy * depth

        step = float(min(max(dt, 1e-3), DT_MAX))
        flight = max(float(flight), WORD_SHAPE_MIN_FORM_S)
        frames = max(2, int(round(flight / step)))
        # W5.6: the SHAPED half-life, not the effect's own drag — the whole
        # point of the slower burst is that the deceleration spans the
        # flight, and `draw` integrates these sparks with the same constant
        hl = max(WORD_SHAPE_FLIGHT_HL_S, 0.05)
        decel = 0.5 ** (step / hl)
        span = step * (1.0 - decel ** frames) / max(1.0 - decel, 1e-9)
        flight_eff = frames * step
        release = max(float(told.release_s), WORD_SHAPE_MIN_FADE_S)
        fade = release * rng.uniform(WORD_SHAPE_FADE_FRAC[0],
                                     WORD_SHAPE_FADE_FRAC[1], k)

        # the origins: one place, with a cell or so of scatter (see the
        # constant) so the first frames are a small bright knot rather than
        # one saturated cell
        o_ang = rng.uniform(0.0, 2.0 * np.pi, k)
        o_r = (np.sqrt(rng.random(k)) * WORD_SHAPE_LAUNCH_PITCH
               * self._ws_pitch)
        ox0 = o_r * np.cos(o_ang)
        oy0 = o_r * np.sin(o_ang)

        s = slice(self.n, self.n + k)
        self.p_x[s] = ox0
        self.p_y[s] = oy0
        self.p_vx[s] = (tx - ox0) / span
        self.p_vy[s] = (ty - oy0) / span
        self.p_age[s] = 0.0
        self.p_life[s] = flight_eff + max(float(told.hold_s), 0.0) + fade
        # colour out of the set's own gradient BY POSITION: the angle the
        # spark lands at, read across a SLICE of the gradient from a
        # per-burst random offset (WORD_SHAPE_GRAD_SPAN says why a slice)
        self.p_grad[s] = (
            rng.random()
            + WORD_SHAPE_GRAD_SPAN * (np.arctan2(ty, tx) / (2.0 * np.pi))
        ) % 1.0
        bright = np.empty(k, dtype=np.float64)
        bright[:n_out] = WORD_SHAPE_OUTLINE_BRIGHT
        bright[n_out:] = WORD_SHAPE_FILL_BRIGHT
        self.p_bright[s] = bright
        self.p_shown[s] = 0.0
        self.p_rev[s] = 0.0
        self.p_rocket[s] = 0.0
        self.p_nocap[s] = 1.0
        self.p_wfade[s] = fade
        self.n += k
        # the clock, the form, the total and THE HUSH were all set at the
        # EDGE by `_word_shape_arm` — this burst only joins it
        self._ws_live = True

    def _word_shape_drift(self, n, dt):
        """W5.6 — THE HANG, WHICH IS NOW A DRIFT: "decelerating to almost a
        stop, but not quite a stop. The blobs should always be slightly
        drifting", and then "at the end, the blobs should lightly break
        apart and fade out".

        W4.3's hang damped the arrived sparks to a dead stop in three frames
        (a 0.05 s velocity half-life). This replaces it with two things, and
        touches only the FLAGGED sparks — the ordinary show's physics is
        exactly what it was:

          * THE ARRIVAL FRAME keeps WORD_SHAPE_DRIFT_KEEP (4%) of the speed
            the spark arrived with. A fraction of its OWN speed, so a target
            far from the centre drifts a little faster than a near one,
            which is what the flight itself already looks like;
          * EVERY FRAME AFTER IT the velocity rides a MEAN-REVERTING random
            walk (`v -> (v - mean)*ou + mean + sigma*z`), whose stationary
            spread is exactly the drift constant and whose mean is zero
            through the hold and an OUTWARD push over the release. Plain
            additive jitter would be a diffusing walk — speed growing as
            sqrt(t), the outline blurring over a 3 s hold — which is why
            WORD_SHAPE_DRIFT_HL_S exists.

        So a shaped spark's speed is never exactly zero while it is lit
        (asserted frame by frame in tests/test_fireworks_word_shape.py), and
        over the release the drift grows tenfold: a common OUTWARD push of
        WORD_SHAPE_BREAK_DRIFT, with the walk's own spread growing to half
        of it on top.

        It draws from the effect's own `self._rng`, like everything else
        random here. That is only ever reached with a shape standing, so an
        UNTOLD effect's random stream — and therefore its every frame — is
        untouched.

        A SECOND WORD arriving mid-hold re-arms `_ws_hung`, so the first
        word's sparks take the 4% scale a second time: they are already
        drifting at the floor, and the walk pulls them back to it within a
        second. Nothing else of theirs is retimed (`p_wfade` is per spark)."""
        held = np.flatnonzero(self.p_wfade[:n] > 0.0)
        k = held.size
        if not k:
            return
        pitch = float(self._ws_pitch)
        if not self._ws_hung:
            self._ws_hung = True
            self.p_vx[held] *= np.float32(WORD_SHAPE_DRIFT_KEEP)
            self.p_vy[held] *= np.float32(WORD_SHAPE_DRIFT_KEEP)
        # how far into the RELEASE: 0 through the hold, 1 at its end
        rel = 0.0
        if (self._ws_t is not None and self._ws_release > 0.0
                and self._ws_t > self._ws_hold_end):
            rel = float(min(1.0, (self._ws_t - self._ws_hold_end)
                            / self._ws_release))
        half_break = 0.5 * WORD_SHAPE_BREAK_DRIFT
        spread = (WORD_SHAPE_DRIFT
                  + (half_break - WORD_SHAPE_DRIFT) * rel) * pitch
        out_speed = WORD_SHAPE_BREAK_DRIFT * rel * pitch
        ou = 0.5 ** (dt / max(WORD_SHAPE_DRIFT_HL_S, 1e-3))
        sigma = spread * np.sqrt(max(1.0 - ou * ou, 1e-6))
        if rel > 0.0:
            # the break-apart's common push: straight out from the centre,
            # so the outline loosens outward rather than shuffling in place
            r = np.maximum(np.hypot(self.p_x[held], self.p_y[held]), 1e-9)
            mx = out_speed * self.p_x[held] / r
            my = out_speed * self.p_y[held] / r
        else:
            mx = my = np.float32(0.0)
        noise = self._rng.standard_normal((2, k)) * sigma
        self.p_vx[held] = (self.p_vx[held] - mx) * ou + mx + noise[0]
        self.p_vy[held] = (self.p_vy[held] - my) * ou + my + noise[1]

    def word_shape_state(self):
        """What the shape is doing this frame — read by the rig, the tests
        and scripts/check_fireworks_word_shape.py, never by the render."""
        n = self.n
        return {
            "form_fraction": float(self._ws_frac),
            "t": None if self._ws_t is None else float(self._ws_t),
            "hanging": bool(self._ws_hang),
            # W4.3: whether the burst has left yet; W5.6: the quiet is
            # 0.25 s and `dim` is what the ordinary show is drawn at
            "hushed": bool(self._ws_hush),
            "dim": float(self._ws_dim),
            "background": (1.0 - (1.0 - WORD_SHAPE_BACKGROUND_DIM)
                           * float(self._ws_dim)),
            "armed": self._ws_armed is not None,
            "launch_at": float(self._ws_launch_at),
            # W5.6: the slowest shaped spark's speed, in cell pitches a
            # second — the "never quite a stop" measure (0.0 with none lit)
            "slowest_pitch_s": self._word_shape_slowest_speed(n),
            "sparks": int(np.count_nonzero(self.p_wfade[:n] > 0.0)),
            "outline_sparks": int(np.count_nonzero(
                (self.p_wfade[:n] > 0.0)
                & (self.p_bright[:n] >= WORD_SHAPE_OUTLINE_BRIGHT - 1e-6))),
        }

    def _word_shape_slowest_speed(self, n):
        """The SLOWEST lit shaped spark's speed, in real cell pitches a
        second — W5.6's "almost a stop, but not quite" read at its worst
        spark rather than on an average that a few fast ones would carry.
        0.0 with none of them lit."""
        held = np.flatnonzero(self.p_wfade[:n] > 0.0)
        if not held.size:
            return 0.0
        speed = np.hypot(self.p_vx[held], self.p_vy[held])
        return float(speed.min() / max(self._ws_pitch, 1e-9))

    def _phase_step(self, dt):
        """Advance the charge/lull/drop state machine. Runs every draw;
        sets the per-frame spawn-shaping multipliers."""
        pend = self._phase_pending
        if pend is not None:
            self._phase_pending = None
            if pend != self._phase:
                prev = self._phase
                self._phase = pend
                self._phase_t = 0.0
                self._phase_done_t = None
                if pend == "lull":
                    if self._keeper_hold_t is not None:
                        self._release_keepers()
                    # a lull told a pre-drop stays dark: its rockets fire
                    # on the pre-drop instead (_pre_drop_step)
                    if not pre_drop.told(self._config):
                        self._launch_rockets()
                elif pend == "drop":
                    # held keepers (THE KEEPERS MELD) are rockets: the
                    # payoff explodes each where it stands
                    self._keeper_hold_t = None
                    self._rocket_payoff()
                    self._tail_t = 0.0
                elif pend == "none" and prev == "lull":
                    # cancelled mid-lull: let the rockets age out
                    n = self.n
                    idx = np.flatnonzero(self.p_rocket[:n] > 0.0)
                    if idx.size:
                        self.p_life[idx] = 0.0
                    self._rocket_path = None
        self._pspawn = 1.0
        self._pcount = 1.0
        self._pspeed = 1.0
        self._plife = 1.0
        self._tail_rate = self._drop_tail_step(dt)
        if self._keeper_hold_t is not None:
            self._keeper_hold_t += dt
            if self._keeper_hold_t >= KEEPER_HOLD_S:
                self._release_keepers()
        if self._phase == "none":
            return
        self._phase_t += dt
        # orphan watchdog: a charge/lull whose payoff never arrives
        # releases itself — the rockets fade out, launching resumes
        due, self._phase_done_t = particle_handoff.phase_release_due(
            self._phase, self.phase_progress, self._phase_t,
            self._phase_done_t,
        )
        if due:
            _LOGGER.info(
                "fireworks: %s watchdog release after %.1fs",
                self._phase, self._phase_t,
            )
            n = self.n
            idx = np.flatnonzero(self.p_rocket[:n] > 0.0)
            if idx.size:
                # let the rockets burn out over half a second
                self.p_life[idx] = self.p_age[idx] + 0.5
            self._rocket_path = None
            self._phase = "none"
            self._apply_config(
                {"phase": "none", "phase_progress": 0.0},
                validate=False,
                fire_event=False,
            )
            return
        if self._phase == "charge":
            p = float(np.clip(self.phase_progress, 0.0, 1.0))
            self._pspawn = 1.0 + CHARGE_SPAWN_X * p
            self._pcount = 1.0 - CHARGE_SHRINK * p
            self._pspeed = 1.0 - CHARGE_SLOW * p
            self._plife = 1.0 - CHARGE_SHORT * p
        elif self._phase == "drop":
            if self._phase_t >= DROP_SETTLE_S:
                self._phase = "none"
                # sanctioned in-render config path (under the effect lock);
                # self-reset so an identical later drop write edges again
                self._apply_config(
                    {"phase": "none", "phase_progress": 0.0},
                    validate=False,
                    fire_event=False,
                )

    def _drop_tail_step(self, dt):
        """Advance the drop tail's own clock; return its launch rate
        (fireworks/s, 0.0 when no tail is running). Independent of the
        phase flag: the drop phase self-resets at DROP_SETTLE_S while the
        tail keeps easing out to DROP_TAIL_S."""
        t = self._tail_t
        if t is None:
            return 0.0
        t += dt
        if t >= DROP_TAIL_S:
            self._tail_t = None
            return 0.0
        self._tail_t = t
        return DROP_TAIL_RATE * (1.0 - t / DROP_TAIL_S)

    def _pre_drop_step(self):
        """THE PRE-DROP's look (the module constants): runs only on a lull
        TOLD a pre-drop — every other frame returns 1.0 before touching
        anything, so a lull without one is today's, byte for byte. Returns
        the gain on the trail this frame: the breath-hold's ease into its
        black, 0.0 through the breath, 1.0 otherwise."""
        if self._phase != "lull" or not pre_drop.told(self._config):
            self._pd_clk = None
            return 1.0
        clk = pre_drop.phase_clock(self._config, self._phase,
                                   self.phase_progress, self._phase_t,
                                   prev=self._pd_clk)
        self._pd_clk = clk
        if clk.segment == "breath":
            if clk.edge:
                # true black: whatever is still fading from before the lull
                # is gone before the rockets fire
                self.n = 0
                self.trail[...] = 0.0
                self._rocket_path = None
            self._burst_pending = 0     # a flare in the breath is swallowed
            return 0.0
        if clk.segment == "pre_drop" and clk.edge:
            self._launch_rockets()
            return 1.0
        return phase_grammar.breath_gain(self._config, self._phase_t)

    # ── draw ────────────────────────────────────────────────────────────

    def draw(self):
        if self.test:
            self.draw_test(self.m_draw)
            return

        if self._handoff_pending:
            self._handoff_pending = False
            self._adopt_handoff()

        dt = min(self.passed, DT_MAX)
        if not np.isfinite(dt) or dt <= 0:
            dt = 1.0 / 60.0
        if not np.isfinite(self.spawn_acc):
            self.spawn_acc = 0.0

        self._phase_step(dt)
        self._word_shape_clock(dt)
        pd_gain = self._pre_drop_step()

        virtual = self._virtual

        # held grand burst: a collapsing radial predecessor owns phase 1
        holding = False
        if self._erupt_hold is not None:
            hold = self._erupt_hold
            frac = particle_handoff.transition_progress(virtual)
            if getattr(virtual, "_transition_effect", None) is self:
                self._erupt_hold = None  # switched away mid-hold: no burst
            elif (
                frac is None
                or frac >= particle_handoff.BLOOM_START
                or particle_handoff.now() - hold["t0"]
                > particle_handoff.ERUPT_HOLD_MAX_S
            ):
                self._erupt_hold = None
                self._grand_burst(hold["ncx"], hold["ncy"])
            else:
                holding = True

        # held pacman adoption: its maze fades over phase 1 — adopt at the
        # morph point, re-reading the live sibling so the entities haven't
        # frozen at their first-frame positions
        if self._pacman_hold is not None:
            hold = self._pacman_hold
            frac = particle_handoff.transition_progress(virtual)
            if getattr(virtual, "_transition_effect", None) is self:
                self._pacman_hold = None  # switched away mid-hold
            elif (
                frac is None
                or frac >= particle_handoff.PACMAN_MORPH_START
                or particle_handoff.now() - hold["t0"]
                > particle_handoff.ERUPT_HOLD_MAX_S
            ):
                self._pacman_hold = None
                sib = getattr(virtual, "_transition_effect", None)
                snap = None
                if sib is not None and sib is not self and hasattr(
                    sib, "_handoff_snapshot"
                ):
                    try:
                        snap = sib._handoff_snapshot()
                    except Exception:
                        snap = None
                self._adopt_handoff(
                    snap=snap or hold["snap"], allow_hold=False
                )
            else:
                holding = True

        # collapse latch: we are the outgoing sibling and radial is incoming
        if self._collapse is None:
            inc = particle_handoff.incoming_sibling(virtual, self)
            if inc is not None and getattr(inc, "NAME", None) == "Radial":
                n0 = self.n
                t_px = self.r_width * float(inc._config.get("x_offset", 0.5))
                t_py = self.r_height * float(inc._config.get("y_offset", 0.5))
                tx = (t_px - self.cx) / max(self.sx, 1e-6)
                ty = (t_py - self.cy) / max(self.sy, 1e-6)
                self._collapse = {
                    "rho0": np.hypot(
                        self.p_x[:n0] - tx, self.p_y[:n0] - ty
                    ).astype(np.float32),
                    "phi0": np.arctan2(
                        self.p_y[:n0] - ty, self.p_x[:n0] - tx
                    ).astype(np.float32),
                    "bright0": self.p_shown[:n0].copy(),
                    "tx": tx,
                    "ty": ty,
                    "frac0": particle_handoff.transition_progress(virtual)
                    or 0.0,
                    "t0": particle_handoff.now(),
                    "spin": 1.0,
                }
        elif getattr(virtual, "_transition_effect", None) is not self:
            self._collapse = None
        col = self._collapse

        n = self.n
        # ── update ──────────────────────────────────────────────────────
        if col is not None and n:
            # analytic gather into the radial's center (no aging, no spawn)
            frac = particle_handoff.transition_progress(virtual)
            if frac is not None:
                s_ = float(np.clip(
                    (frac - col["frac0"])
                    / max(particle_handoff.GATHER_FRAC - col["frac0"], 1e-3),
                    0.0, 1.0,
                ))
                p2 = float(np.clip(
                    (frac - particle_handoff.GATHER_FRAC)
                    / (1.0 - particle_handoff.GATHER_FRAC),
                    0.0, 1.0,
                ))
            else:
                t = particle_handoff.now() - col["t0"]
                s_ = min(t / particle_handoff.COLLAPSE_FALLBACK_S, 1.0)
                p2 = min(max(
                    (t - particle_handoff.COLLAPSE_FALLBACK_S) / 0.5, 0.0
                ), 1.0)
            e = s_ * s_ * (3.0 - 2.0 * s_)
            k = min(len(col["rho0"]), n)
            rho = col["rho0"][:k] * (1.0 - s_) ** 2 + 0.05 * e
            phi = col["phi0"][:k] + col["spin"] * 2.0 * np.pi * (
                particle_handoff.SWIRL_TURNS * e + 0.35 * p2
            )
            x0 = self.p_x[:n].copy()
            y0 = self.p_y[:n].copy()
            self.p_x[:k] = (col["tx"] + rho * np.cos(phi)).astype(np.float32)
            self.p_y[:k] = (col["ty"] + rho * np.sin(phi)).astype(np.float32)
            self.p_shown[:k] = np.minimum(
                col["bright0"][:k] * (1.0 + 0.6 * e), 1.0
            ) * (1.0 - p2)
            shown = self.p_shown[:n]
        else:
            x0 = self.p_x[:n].copy() if n else np.empty(0, np.float32)
            y0 = self.p_y[:n].copy() if n else np.empty(0, np.float32)
            if n:
                self.p_x[:n] += self.p_vx[:n] * dt
                self.p_y[:n] += self.p_vy[:n] * dt
                # drag: velocity half-life shrinks as drag rises
                hl = 0.6 - 0.5 * self.drag
                decel = np.float32(0.5 ** (dt / max(hl, 0.05)))
                if self._ws_live:
                    # WORD SHAPES (W5.6): a shaped spark STILL FLYING is
                    # integrated with WORD_SHAPE_FLIGHT_HL_S instead — the
                    # relaxed drag the solve was done against, so the
                    # deceleration spans the whole 2 s flight — and one
                    # that has ARRIVED is left to the drift below. The
                    # ordinary show's own physics is exactly what it was.
                    held = self.p_wfade[:n] > 0.0
                    ws_decel = np.float32(
                        1.0 if self._ws_hang
                        else 0.5 ** (dt / WORD_SHAPE_FLIGHT_HL_S))
                    mult = np.where(held, ws_decel, decel)
                    self.p_vx[:n] *= mult
                    self.p_vy[:n] *= mult
                else:
                    self.p_vx[:n] *= decel
                    self.p_vy[:n] *= decel
                if self._ws_hang and self._ws_live:
                    self._word_shape_drift(n, dt)
                self.p_age[:n] += dt
                alive = (self.p_age[:n] < self.p_life[:n]) & (
                    np.hypot(self.p_x[:n], self.p_y[:n]) < self.r_max
                )
                x0, y0 = self._compact(alive, x0, y0)
                n = self.n

            # ── spawn ───────────────────────────────────────────────────
            # THE QUIET comes first: for WORD_SHAPE_HUSH_S (0.25 s since
            # W5.6, and ONLY that) in front of the launch nothing ordinary
            # launches at all — not the spawn rate, not a beat burst, not
            # the drop tail's shower — so the shaped burst leaves into a
            # lull of its own. Everything else of W4.3's hush is now the
            # DIM instead (the brightness block below): "the background
            # doesn't need to be clear of other fireworks, just they need
            # to be dimmer". Nothing is DEFERRED: the accumulators are
            # cleared each quiet frame, so the launch does not open onto a
            # pile of withheld launches. A phase arriving ends it
            # (`_word_shape_clock`).
            if self._ws_hush:
                self.spawn_acc = 0.0
                self._beat_pending = False
                self._tail_acc = 0.0
            # paused during a lull: the dark panel belongs to the rockets
            elif not holding and self._phase != "lull":
                rate = self.spawn_rate * self._pspawn * (
                    1.0 + self.spawn_audio * self.impulse * 3.0
                )
                self.spawn_acc += rate * dt
                bursts = int(self.spawn_acc)
                self.spawn_acc -= bursts
                if self._beat_pending:
                    bursts += self.beat_burst
                    self._beat_pending = False
                # drop tail: the post-payoff shower, ordinary fireworks
                # at an easing rate, landed regardless of the density cap
                # (which the ordinary show itself may be saturating)
                if self._tail_rate > 0.0:
                    self._tail_acc += self._tail_rate * dt
                    tail = int(self._tail_acc)
                    self._tail_acc -= tail
                    launches = [(bursts, False), (tail, True)]
                else:
                    self._tail_acc = 0.0
                    launches = [(bursts, False)]
                for count, uncapped in launches:
                    for _ in range(count):
                        prev = self.n
                        self._spawn_burst(
                            self._burst_count(), ignore_cap=uncapped
                        )
                        if self.n > prev:
                            fresh = slice(prev, self.n)
                            x0 = np.concatenate([x0, self.p_x[fresh]])
                            y0 = np.concatenate([y0, self.p_y[fresh]])
                n = self.n

            # flare-driven payoff burst — deliberately NOT gated on hold/
            # lull (a flare during a lull still lands, exactly as the drop
            # payoff itself does); self-reset re-arms the edge. A stale
            # persisted count on a fresh instance (nonzero _burst_seen with
            # nothing pending — the creation baseline armed no spawn) is
            # reset the same way, so the key reads 0 whenever idle and an
            # identical later write still edges.
            if self._burst_pending or self._burst_seen:
                pending = self._burst_pending
                self._burst_pending = 0
                if pending:
                    prev = self.n
                    self._flare_burst(pending)
                    if self.n > prev:
                        fresh = slice(prev, self.n)
                        x0 = np.concatenate([x0, self.p_x[fresh]])
                        y0 = np.concatenate([y0, self.p_y[fresh]])
                    n = self.n
                self._apply_config(
                    {"burst_rockets": 0}, validate=False, fire_event=False
                )

            # WORD SHAPES: the shaped burst LAUNCHES here, once the
            # shape's own clock (armed at the SEQ edge by
            # `_word_shape_clock`) reaches the flight's own start —
            # WORD_SHAPE_FLIGHT_S before the word, the quiet having held
            # the last 0.25 s in front of it (W4.3, W5.6). Ungated like the
            # flare burst above — a sung word's shape must land whatever the
            # show is doing — and additive, so nothing live is touched.
            # WORD_SHAPE_CLOCK_EPS for the same reason the quiet's own
            # end and the hang take it: the clock ACCUMULATES dt, so a
            # launch time that is a whole number of frames away is reached
            # to within a float's dust rather than exactly. Without the
            # slack a told form whose launch lands on a frame boundary
            # (2.8 s − 2.0 s = 24 frames at 30 fps) gets ONE frame with
            # neither the quiet nor the burst — the quiet ends on that
            # frame and the launch waits for the next.
            if (self._ws_armed is not None and self._ws_t is not None
                    and self._ws_t >= self._ws_launch_at
                    - WORD_SHAPE_CLOCK_EPS):
                told = self._ws_armed
                self._ws_armed = None
                prev = self.n
                # the flight is the time LEFT to the word, so a frame of
                # quantization at the launch cannot drift the arrival off it
                self._word_shape_burst(told, dt,
                                       self._ws_form - self._ws_t)
                if self.n > prev:
                    fresh = slice(prev, self.n)
                    x0 = np.concatenate([x0, self.p_x[fresh]])
                    y0 = np.concatenate([y0, self.p_y[fresh]])
                n = self.n

            if self._phase == "lull":
                # guided rocket motion (positions set directly; the x0/y0
                # copies above give them their motion smear + trail)
                self._phase_rockets()

            if n:
                frac_t = np.clip(
                    self.p_age[:n] / self.p_life[:n], 0.0, 1.0
                )
                fwd = (
                    (1.0 - frac_t) ** 1.4
                ) * np.minimum(self.p_age[:n] / FADE_IN_S + 0.3, 1.0)
                # reverse envelope — the mirror of the explosion: born with
                # a visible bias at the far point, brightening all the way
                # in, then a fast terminal wink-out so the converged blob
                # doesn't linger on trail decay. Trail Length shapes the
                # START here: long trails = a fainter, more gradual lead-in.
                start_bias = 0.2 + 0.3 * (1.0 - self.trail_decay)
                gamma = 0.8 + 1.2 * self.trail_decay
                rev_env = (
                    start_bias + (1.0 - start_bias) * frac_t**gamma
                ) * np.clip((1.0 - frac_t) / 0.12, 0.0, 1.0) ** 0.7
                fade = np.where(self.p_rev[:n] > 0.0, rev_env, fwd)
                if self._ws_live:
                    # WORD SHAPES: a shaped spark is full bright from its own
                    # fade-in until its own fade window opens, then goes out
                    # on its own clock — spark by spark over the release,
                    # never all at once — twinkling in place throughout (the
                    # phase comes off its own position, so neighbours are out
                    # of step). Read off p_wfade per spark, so an earlier
                    # word's sparks keep fading on their own clock while a
                    # second word's burst forms over them.
                    wf = self.p_wfade[:n]
                    held = wf > 0.0
                    self._ws_live = bool(held.any())
                    if self._ws_live:
                        left = self.p_life[:n] - self.p_age[:n]
                        twinkle = 1.0 - WORD_SHAPE_TWINKLE * 0.5 * (
                            1.0 + np.sin(2.0 * np.pi * (
                                WORD_SHAPE_TWINKLE_HZ * self.p_age[:n]
                                + WORD_SHAPE_TWINKLE_PX * self.p_x[:n]
                                + WORD_SHAPE_TWINKLE_PY * self.p_y[:n])))
                        ws_env = (
                            np.clip(left / np.maximum(wf, 1e-6), 0.0, 1.0)
                            ** WORD_SHAPE_FADE_POWER
                            * np.clip(self.p_age[:n] / WORD_SHAPE_FADE_IN_S,
                                      0.0, 1.0)
                            * twinkle
                        )
                        fade = np.where(held, ws_env, fade)
                if self._ws_dim > 0.0:
                    # W5.6 — DIM, NOT DARK: every ORDINARY spark is drawn at
                    # WORD_SHAPE_BACKGROUND_DIM of its own brightness while
                    # the shape owns the background, ramped by the envelope
                    # (`_word_shape_clock`) so neither end of it steps. His
                    # "the background doesn't need to be clear of other
                    # fireworks, just they need to be dimmer". A BRIGHTNESS
                    # and nothing else: no particle is retimed, killed or
                    # moved by it, and a phase arriving ends it, so a lull's
                    # rockets and a drop's payoff are never dimmed.
                    dim = np.float32(
                        1.0 - (1.0 - WORD_SHAPE_BACKGROUND_DIM)
                        * self._ws_dim)
                    plain = self.p_wfade[:n] <= 0.0
                    fade = np.where(plain, fade * dim, fade)
                self.p_shown[:n] = self.p_bright[:n] * fade
            shown = self.p_shown[:n]

        # ── render ──────────────────────────────────────────────────────
        half_life = 0.02 + self.trail_decay * 0.5
        self.trail *= np.float32(0.5 ** (dt / half_life))

        if n:
            rgb = self.get_gradient_color_vectorized1d(
                self.p_grad[:n]
            ).astype(np.float32)
            rgb *= shown[:, None]

            fractions = (
                np.arange(1, SUBSTEPS + 1, dtype=np.float32) / SUBSTEPS
            )
            xi_n = x0[:, None] + (self.p_x[:n] - x0)[:, None] * fractions
            yi_n = y0[:, None] + (self.p_y[:n] - y0)[:, None] * fractions
            x = self.cx + xi_n * self.sx
            y = self.cy + yi_n * self.sy

            keep = self.k_dist <= self.blob_size
            k_dx = self.k_dx[keep]
            k_dy = self.k_dy[keep]
            k_weight = (
                1.0 - self.k_dist[keep] / (self.blob_size + 0.5)
            ).astype(np.float32)

            xi = np.round(x).astype(np.int32).ravel()
            yi = np.round(y).astype(np.int32).ravel()
            point_count = xi.size
            kernel_count = k_dx.size

            px = (xi[:, None] + k_dx[None, :]).ravel()
            py = (yi[:, None] + k_dy[None, :]).ravel()
            valid = (
                (px >= 0)
                & (px < self.r_width)
                & (py >= 0)
                & (py < self.r_height)
            )
            idx = (py * self.r_width + px)[valid]
            kw_flat = np.broadcast_to(
                k_weight[None, :], (point_count, kernel_count)
            ).ravel()[valid]
            rgb_sub = rgb / SUBSTEPS
            frame = np.empty_like(self.trail)
            cells = self.r_width * self.r_height
            for channel in range(3):
                per_point = np.repeat(rgb_sub[:, channel], SUBSTEPS)
                vals = (
                    np.broadcast_to(
                        per_point[:, None], (point_count, kernel_count)
                    ).ravel()[valid]
                    * kw_flat
                )
                frame[..., channel] = np.bincount(
                    idx, weights=vals, minlength=cells
                ).reshape(self.r_height, self.r_width)
            np.maximum(self.trail, np.minimum(frame, 255.0), out=self.trail)

        trail = (self.trail if pd_gain >= 1.0
                 else self.trail * np.float32(pd_gain))
        out = np.asarray(self.matrix, dtype=np.float32) + trail
        self.matrix = Image.fromarray(
            np.clip(out, 0, 255).astype(np.uint8), "RGB"
        )
