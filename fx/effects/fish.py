import colorsys
import logging
import math

import numpy as np
import voluptuous as vol
from PIL import Image

import fx.effects.particle_handoff as particle_handoff
import fx.effects.pre_drop as pre_drop
from fx.effects import lull_handoff, phase_grammar, word_shape_keys, word_shapes
from fx.color import validate_gradient
from fx.effects.audio import AudioReactiveEffect
from fx.effects.gradient import GradientEffect
from fx.effects.twod import Twod

_LOGGER = logging.getLogger(__name__)

# ── buffer capacity ─────────────────────────────────────────────────────────
# Ordinary swimming is ALWAYS bounded by the `particle_count` parameter. The
# density cap is bypassed at exactly two scripted moments — the charge's
# school (`school_count`) and the DROP's rush (`rush_count`, which was the
# lull's until his 2026-08-28 addendum moved it) — via the
# `p_nocap` tag, the same shape blackhole's blob rush / fireworks' payoff
# already use. CAP is sized so those two moments plus a full drop explosion
# can never starve the ordinary render (see MAX_* below and
# tests/test_fish.py::test_buffer_headroom).
MAX_PARTICLE_COUNT = 16   # `particle_count` schema max
MAX_SCHOOL = 24           # `school_count` schema max (default 18, +50% from
                          # his original 12, 2026-09-16, watching it live)
MAX_RUSH = 24             # `rush_count` schema max ("up to 20" default)
DROP_EJECTA_X = 2         # ejecta per kept fish (3x total spawn), from orbits
CAP = (
    MAX_PARTICLE_COUNT
    + MAX_SCHOOL
    + MAX_RUSH
    + DROP_EJECTA_X * MAX_PARTICLE_COUNT
)  # = 96

SUBSTEPS = 2        # path sub-samples per frame (gap-free smear)
DT_MAX = 0.1
KERNEL_R = 8        # max body-segment radius the offset table supports
SPLAT_KERNEL_R = 16  # the shared splat offset table's own span, in px:
                    # every soft dot (a body segment, a wake deposit) is
                    # stamped from it and filtered by its own radius

HANDOFF_ENTER_S = 0.65
# THE PEEL (transitions-drop plan phase 4, SHOALING — fx/effects/
# transition_cloud.py; VENDOR #75). A fish adopted from a predecessor that
# said how fast its piece was TURNING (`snap["om"]`, rad/s: an orbit blob
# curving round its orbit) peels off that curve: its heading rate starts
# at the inherited rate and eases into the fish's own steering over
# PEEL_S, so the heading's rate of change is continuous through the
# transformation, not only the heading itself. Its body is backfilled
# along that same curve.
PEEL_S = 0.4
SLOT_EASE_S = 0.6    # home-anchor re-spacing ease time constant

# ── dispersal: a fish NEVER fades out ───────────────────────────────────────
# HIS WORDS (2026-09-16): "the fish shouldn't fade out, they should disperse
# off the screen." Every way a fish used to leave by dimming — the ordinary
# population trim (the old 1.2 s LEAVE_FADE_S horizon), the lull's paced
# exodus, a phase abandoned, the drop's surplus rush fish, and an outgoing
# scene crossfade into an effect with no blobs of its own to merge into — is
# now ONE mode, DISPERSING (mode 4): the fish keeps its
# full brightness, steers out of the window along the turn-radius-bounded
# arc every other steer obeys, and is retired only once its whole body is
# off the panel. There is no brightness term on a dispersing fish at all,
# which is what makes "never fades" structural rather than tuned.
#
# A DEADLINE, NOT A SPEED: each dispersing fish carries the effect-clock time
# it must be off the panel by (`p_dl`), and its swim speed is DERIVED every
# frame from the distance still to cover and the time still left — so a long
# lull disperses at a relaxed pace and a 0.5 s crossfade scatters them hard,
# with no second number to keep in step with either. The only speed that is
# a constant is the floor (a dispersing fish is never slower than it cruised)
# and the ceiling (see DISPERSE_MAX_PANELS_S).
DEPART_S = 1.2           # an ordinary departure's deadline: the SAME time
                         # budget the old fade had, spent swimming out
DISPERSE_MIN_X = 1.3     # never slower than this multiple of cruise
DISPERSE_PATH_X = 1.25   # the path out is an arc, not the straight line the
                         # distance is measured along; this is its allowance
DISPERSE_MAX_PANELS_S = 5.0  # ceiling: panel long-axes per second. Past this
                         # the smear reads as a streak rather than a fish, and
                         # only a deadline far shorter than any real lull or
                         # crossfade can ask for it (measured in
                         # scripts/check_fish_disperse.py)
DISPERSE_TAU = 0.05      # speed ease while dispersing — far quicker than
                         # SPEED_TAU, or the derived speed arrives too late.
                         # Tightened from 0.07 by fm/spotfx-fish-body-
                         # trails-head-tail-thrust (his ruling): at his
                         # tightest tested lull gap (0.9s) 0.07 left a
                         # straggler on the panel in 3 of 60 seed/gap
                         # combinations on that branch (0 of 60 on master,
                         # 0 of 60 at 0.05). A MITIGATION, NOT A STRUCTURAL
                         # FIX: it widens a sampled margin and removes every
                         # failure we can currently reproduce. At a 0.9s gap
                         # the ramp is ~0.81s, the third lands at ~0.27s and
                         # the exit aim (LULL_GONE_AT * LULL_EXIT_BY) at
                         # ~0.248s — ~22ms (~1.3 frames) of slack, shorter
                         # than this ease, before `_lull_step`'s hard
                         # backstop runs its unconditional instant
                         # `_compact`, which removes any fish still on the
                         # panel at full brightness in one frame. Other
                         # pre-lull states (other songs, populations, a lull
                         # with no charge before it, real render dt jitter)
                         # can still land a fish there. KNOWN, ACCEPTED, and
                         # follow-up-worthy: make the backstop disperse
                         # rather than pop, or state the exit margin in
                         # absolute time rather than a fraction.
DISPERSE_MIN_LEFT_S = 0.05  # the "time left" a deadline is never read below,
                         # so a missed deadline asks for the ceiling, never
                         # for infinity
DISPERSE_TURN_S = 0.35   # a leaking lull fish turns from its swirl to
                         # outward across this long (a spiral, not a snap)
DISPERSE_OFF_MARGIN = 2.0  # px past the panel edge, beyond a body length,
                         # at which a dispersing fish counts as gone

# ── the outgoing crossfade ──────────────────────────────────────────────────
# A scene change away from Fish crossfades (his crystal-mapper is "Add",
# 0.5 s), and "Add" multiplies the OUTGOING frame by (1 - weight): the fish
# used to simply dim away underneath the incoming effect. HIS SPLIT: "merge
# into blobs from the other effects that have them ... when there isnt a
# blob, have them disperse to black, rather than fade". So which way a fish
# leaves depends on the INCOMING effect:
#   * an ADOPTER (TRANSITION_ADOPTERS) reads our live snapshot on its first
#     draw and spawns its own particles at the fish positions — the fish ARE
#     its blobs now, and the outgoing shoal is left exactly as it always was
#     (scattering it too would show the shoal twice: once adopted, once
#     swimming away);
#   * radial keeps its own gather-into-the-bloom collapse, untouched;
#   * anything else has no blob to merge into, so every fish disperses with
#     a deadline inside the crossfade, and for an additive blend the bodies
#     are drawn brighter by the inverse of that weight (floored). The body
#     layer is what carries that gain — the smear it leaves in the trail
#     decays from the gained value — and the wake is NOT compensated, so
#     once the fish are gone the panel goes to black, which is the ask. A
#     gained body clips HUE-PRESERVING (`_clip_body_layer`): a pixel past
#     255 is scaled down as a whole, so an orange fish stays orange on its
#     way out instead of washing toward yellow-white the way clipping each
#     channel on its own would.
TRANSITION_EXIT_BY = 0.6     # of the crossfade: every fish off by here
TRANSITION_GAIN_FLOOR = 0.3  # the blend weight compensation never exceeds
                             # 1 / this, so a body cannot blow out to white
# A NAMED LIMIT, measured and accepted: the virtual clips the OUTGOING frame
# at 255 before weighting it by (1 - weight), so no gain inside the effect
# can lift a core that is already saturated — the compensation only helps
# the parts of a fish below full. Rendered pixels through his Add 0.5 s
# crossfade into black, four seeds: median on-panel body peak 0.90-0.96 of
# its pre-switch value at weight 0.03, 0.80-0.89 at 0.23, ~0.6-0.75 on the
# last fish still centred on the panel (weight 0.32-0.42), every centre off
# by ~0.36-0.45 and every body by 0.48-0.55 (scripts/check_fish_disperse.py
# section 2 prints it frame by frame). Lifting that needs a change to the
# virtual's blend, not to this effect.
#
# Keyed by the incoming effect's MODULE basename. Measured on fx.headless:
# each of these reads the live fish sibling's _handoff_snapshot() (or the
# registry snapshot) in its own _adopt_handoff and spawns its own particles
# at the fish positions — "fish" is the same-type native restore. Pacman is
# the one of his named five with NO adopt path at all, so it still gets the
# dispersal until it grows one (carded separately); concentric, equalizer2d,
# blender, noise, keybeat2d, gifplayer, singleColor and everything else
# likewise have no blob to merge into.
TRANSITION_ADOPTERS = frozenset(
    {"blackhole", "orbits", "fireworks", "squiggles", "eye", "dancer", "fish",
     "sauron"}
)

# ── the swim burst flare ────────────────────────────────────────────────────
# HIS WORDS: "a flare ... that makes the fish swim fast for a burst, and have
# a dramatic change in the frequency of their fin strokes ... lasts 300ms
# total, and make sure Sonic can adjust those numbers easily." (He also asked
# for it to start 100 ms before the trigger, then corrected that himself —
# "no, dont pull the band forward, just dont add the 100ms pre-fire" — so it
# fires ON the trigger; an early start belongs to per-flare trigger-moment
# work, not to this band.)
#
# The effect side is only a LEVEL, `swim_burst` (a toggle): while it is on,
# every fish swims SWIM_BURST_SPEED_X faster and strokes FLAP_BURST_X faster.
# The TIMING lives entirely in the flare kind that drives it — a momentary
# kind (`hold_ms` = the 300 ms length, `trigger_offset_ms` = where it starts
# relative to the trigger, OFFSET family, authored 0 = on the mark;
# docs/SPECTRA_TIMING_CONVENTIONS.md) — so both numbers are ordinary
# FlareKind fields Sonic already edits, and the effect has no duration of
# its own to disagree with them. A toggle's momentary write and release are
# both instant jumps, which is what makes the kind's hold the burst's real
# length. The envelope below only rounds the edges.
SWIM_BURST_SPEED_X = 2.2   # extra swim speed, as a multiple of cruise
FLAP_BURST_X = 2.5         # extra fin-stroke frequency (x3.5 at full)
BURST_ATTACK_S = 0.03      # envelope rise ...
BURST_RELEASE_S = 0.05     # ... and fall, so the burst is ~its hold long
BURST_SPEED_TAU = 0.04     # speed ease while the burst envelope is live, so
                           # the dash lands inside 300 ms and ENDS with it
SPIKE_COOL_S = 0.12  # min gap between beat turn-kicks

# ── the solo burst (his 2026-10-06 ask, for the House Fish scene) ───────────
# HIS WORDS: "In house fish scene, give individual ones an occasional burst
# of speed." Not the swim burst above — that is a flare that sends the WHOLE
# shoal at once, on a trigger. This is one fish at a time, at random, on its
# own clock: now and then a fish picked at random accelerates hard, holds
# that speed for `solo_burst_time`, then eases back to its ordinary pace.
# `solo_burst_rate` is how many a minute across the whole shoal (a Poisson
# clock, so they are irregular the way a real tank is), and it SHIPS AT 0 —
# the effect's own default is "never"; only the House Fish scene's own
# params turn it on, so the music Fish scene is untouched.
#
# Only an ordinary swimmer that is not already bursting and has the wall at
# most faintly in its look-ahead is picked (a fish does not sprint into a
# wall); a burst that is due while nobody qualifies waits for someone who
# does, so the rate holds. Nothing bursts during a charge, lull, drop or an
# outgoing crossfade — those moments are authored. A burst gives up its hold
# and eases back the moment the wall presses hard on it; and since the
# look-ahead grows with speed, a bursting fish already sees the wall sooner.
SOLO_ATTACK_S = 0.15     # the envelope's rise to full
SOLO_FALL_S = 0.35       # half-life of the ease back once the hold is over
SOLO_SPEED_TAU = 0.1     # speed ease while rising, so the dash reads as one
SOLO_FLAP_X = 1.0        # extra fin-stroke frequency at full (x2)
SOLO_WALL_CUT = 0.5      # wall urgency at which a burst gives up its hold
SOLO_WALL_FREE = 0.15    # ... and below which a fish may start one
SOLO_DUE_MAX = 2.0       # bursts owed while nobody qualifies, at most

# ── the lunge ───────────────────────────────────────────────────────────────
# A strong beat used to raise the swim speed for tens of milliseconds — the
# ripple correctly sized itself off that speed, so a big ring rode a tiny
# travel. The lunge holds the boost near full for a real fraction of a second
# so a strong beat covers several body lengths and the ripple's own scaling
# self-heals. It is a MOTION change only: nothing about the wake is touched.
# Magnitude keeps riding `speed_jump` x the existing spike signal (which is
# itself impulse-derived), so the menu gains no knob.
LUNGE_SPIKE_MIN = 0.35   # only a STRONG spike lunges; below this, nothing
                         # happens at all and quiet swimming is untouched
LUNGE_HOLD_S = 0.6       # ... and it holds near full for this long, measured
                         # by distance covered (see
                         # scripts/check_fish_lunge.py), not chosen by feel
LUNGE_FALL_S = 0.35      # half-life of the release after the hold
LUNGE_GAIN = 1.0         # boost as a fraction of cruise, per unit of
                         # speed_jump x spike
ENTRY_MARGIN = 0.32  # how far OUTSIDE the pond new fish appear (normalized).
                     # Unlike Orbits, a fish is not lerped in from its entry
                     # point — it SWIMS in under its own kinematics, so the
                     # entry distance is a real travel time, not a cosmetic
                     # start point. Kept just off-panel.
ENTER_SPEED_X = 1.7  # entering fish swim in faster than they cruise

# ── body ────────────────────────────────────────────────────────────────────
# The spine is a fixed chain of splats from nose (u=0) to tail (u=1); the
# profile is the oval's half-width at each node, normalized to blob_size.
# Asymmetric on purpose — rounded head, thin tail — so the oval reads as a
# fish from above rather than as a symmetric lozenge.
SPINE_U = np.array([0.0, 0.2, 0.4, 0.6, 0.8, 1.0], dtype=np.float32)
SPINE_PROFILE = np.array(
    [0.45, 0.85, 1.0, 0.78, 0.50, 0.34], dtype=np.float32
)
# the travelling wave down the spine: the tail trails the head by this many
# flap cycles, and lateral throw grows toward the tail
SPINE_WAVE = 0.42
SPINE_THROW = SPINE_U ** 1.6

# ── body trail (his 2026-09-16 ruling: "let the body BE the head's recent
# path") ─────────────────────────────────────────────────────────────────
# The HEAD (the front half of the spine, u<=0.5) still points the CURRENT
# heading by straight extrapolation — a real fish's nose does lead where
# it is going, and that much of the old rigid-stick layout was already
# right. Only the trailing half (u>0.5) is walked back along the fish's
# own recorded path instead of projected along that same heading — see
# `p_trail_x`/`p_trail_y` (set up in __init__, pushed in draw(), read in
# `_draw_bodies`). A fish on a straight run has a trail that IS that
# straight line, so the body reduces to exactly its old rigid shape; a
# fish mid-turn gets a body that bends through the arc it actually swam,
# with the head at the front of that curve rather than a stick pivoted to
# the tangent — his own complaint, and no separate "how much to bend"
# number to disagree with the path.
#
# Sampled by ARC LENGTH — a fresh sample every BODY_TRAIL_STEP_PX of real
# travel, never every frame — so the trail always covers roughly the same
# physical distance of path regardless of how fast the fish is moving
# right now (a time-sampled trail would instead spread the same history
# over a longer or shorter path depending on speed, exactly the coupling
# a speed-independent body shape needs to avoid — and speed is no longer
# smooth, see the THRUST block below).
BODY_TRAIL_LEN = 28       # recorded path samples behind the tracked point
BODY_TRAIL_STEP_PX = 4.0  # spacing between samples, in SCREEN px — the
                          # trail covers up to BODY_TRAIL_LEN * this
                          # (112px) of real path. A body asking for more
                          # than that (an extreme blob_size/body_aspect/
                          # size_audio combination) holds at the oldest
                          # recorded point instead of extending further —
                          # a soft truncation, not a crash, for a
                          # combination far past anything ever tuned.

FLAP_BASE = 0.35        # amplitude floor — a drifting fish still breathes
FLAP_SPEED_GAIN = 0.65  # ... plus this much at cruise speed
FLAP_ACCEL_REF = 40.0   # px/s^2 that counts as "full" acceleration
FLAP_MIN = 0.08
FLAP_MAX = 2.0

CRUISE_K = 1.8          # px/s of cruise per unit base_speed per unit of
                        # field radius — swim speed is DECOUPLED from the
                        # turn radius on purpose: tying them (Orbits' own
                        # "revolutions per second" reading of base_speed)
                        # makes a tight turner a slow swimmer, and the two
                        # are separately judged by eye.
SPEED_TAU = 0.28        # speed ease time constant (real acceleration) —
                        # this is what `want` above eases toward when the
                        # tail-stroke cap below is 0. See THE DIAL comment.

# ── tail-stroke thrust (his 2026-09-16 ruling, "the tail beat must
# actually produce the forward movement") ──────────────────────────────
# Speed is no longer one smooth continuous target: every fish keeps a
# MINIMUM DRIFT floor (`min_drift_speed`, a fraction of the ordinary
# continuous target this effect always computed) plus a PULSE synced to
# its own tail-beat phase (`p_flap` — the SAME oscillator the visual flap
# already runs on, so the surge on screen and the stroke that supposedly
# produced it can never drift apart), capped by `stroke_speed_cap` (a
# fraction of that same target). ONE PULSE PER FLAP CYCLE — his "tail
# flipping ... drives the speed": one flip, one push — shaped to rise and
# fall smoothly rather than snap.
#
# THE DIAL, his explicit design requirement: he is taking a bigger change
# than usual on faith and asked for a way back that costs no rebuild.
# Raising `min_drift_speed` to its max (1.0) while lowering
# `stroke_speed_cap` to 0 makes the speed target exactly the old
# continuous one again, with SPEED_TAU exactly restored too (see the
# speed section in draw()) — this is NOT a redundant pair collapsing to
# one knob: a single "pulse amount" slider cannot express "smooth AND
# fast" and "pulsed AND slow" as different points on the same line, and
# he asked for the escape hatch specifically, not just an amount. Do not
# fold these into one parameter or drop the floor as decoration.
#
# This also delivers his separate "more jerky to the music, especially in
# slower sections" WITHOUT a second mechanism: a quiet passage lowers
# `want_full` (less audio-driven jump/lunge), which lowers `speed_norm`,
# which lowers `flap_freq` — so the SAME stroke that pulses the speed
# also slows down, spacing its pushes further apart in slow music and
# blurring them together in fast music, exactly as he described it.
#
# THE SHIPPED DEFAULTS PRESERVE THE OLD MEAN SPEED — found live 2026-09-17
# (his ruling, after a rebase onto the swim-burst boundary-brake fix #279
# surfaced it): the first-shipped defaults (0.6 / 0.45) averaged only
# ~0.77x the old continuous target over a full stroke cycle, a real,
# unasked-for 23% slowdown that #279's own regression test caught (its
# unbraked-burst negative control stopped overshooting at all, because the
# burst's fixed 3.2x multiplier was now applied to an already-smaller
# baseline). His correction, and the governing principle: A PULSE
# REDISTRIBUTES SPEED IN TIME, IT MUST NOT REDUCE THE AVERAGE — within one
# stroke cycle a fish surges and coasts, but across a whole cycle it must
# cover the same ground the old smooth target did. `min_drift_speed` and
# `stroke_speed_cap` are otherwise INDEPENDENT (his own requirement, see
# THE DIAL above) — this constraint binds only the two SHIPPED DEFAULT
# VALUES together, not the sliders themselves; moving either one off its
# default is still free to raise or lower the mean, same as it always was.
#
# The constraint, derived (not tuned by eye), and FIRST-ORDER: `pulse_shape`'s
# own mean over a full 0..2*pi cycle of PHASE is PULSE_SHAPE_CYCLE_MEAN =
# 3/8 = 0.375 (mean of ((1-cos)/2)^PULSE_SHAPE_POWER at POWER=2 — a fixed
# algebraic fact of this shaping curve, not a measurement). `want`'s cycle
# mean is therefore approximately `min_drift_speed + stroke_speed_cap *
# PULSE_SHAPE_CYCLE_MEAN` (see the speed section in draw()), and a
# first-order exponential ease (the `tau` blend just below) has unity DC
# gain, so `p_spd`'s mean tracks `want`'s. APPROXIMATELY, NOT EXACTLY: the
# phase does not advance at a constant rate — `flap_freq` rises with
# `speed_norm`, i.e. with `p_spd` itself — so the stroke runs faster through
# the surge than through the coast, the time-averaged `pulse_shape` falls a
# little below 0.375, and the measured mean lands slightly LOW (0.16% at the
# shipped defaults; tests/test_fish.py::
# test_default_dial_preserves_the_old_mean_speed holds it within 1% on the
# real render pipeline). That bias grows with `stroke_speed_cap`.
# Solving `min_drift_speed + stroke_speed_cap * 0.375 == 1.0` for the
# shipped `stroke_speed_cap = 0.4` gives `min_drift_speed = 0.85` (trough
# 0.85x / peak 1.25x of the old target) — subtle, visible, mean-neutral to
# within that tolerance. Changing either shipped default number requires
# re-solving this equation for the other (and re-measuring against that
# test, since a larger cap widens the first-order error), or the defaults
# will silently reintroduce a mean-speed drift exactly like this one.
PULSE_SHAPE_CYCLE_MEAN = 0.375  # = 3/8 over phase; see the block above
PULSE_SHAPE_POWER = 2.0  # sharpens the hump so a stroke reads as a push,
                         # not a smooth sine wobble
THRUST_TAU = 0.09        # speed-ease time constant once any stroke cap is
                         # in play — fast enough that the coast between
                         # strokes is visible instead of eased away. Blended
                         # with SPEED_TAU by `stroke_speed_cap` itself (see
                         # draw()), so at cap=0 this is never reached at all.
#
# THE ONE DEGENERATE COMBINATION, found by review: `min_drift_speed` and
# `stroke_speed_cap` both go down to 0 in the schema (each independently a
# legitimate value — 0 drift is the "pure surge and coast" endpoint's own
# floor, 0 cap is the "no pulse" endpoint's own ceiling). Set TOGETHER,
# `pulsed_want` is a permanent, exact zero for every ordinary swimmer —
# not a momentary trough between pulses, which is fine and intended, but a
# speed that never recovers. Zero speed means zero turn rate too
# (`omega_max = p_spd / turn_radius_px`), so heading freezes as well, and
# an off-panel ENTERING fish (mode 1, itself pulse-eligible) never reaches
# the pond at all — the population can visibly stall. `MOTION_FLOOR_FRAC`
# is a tiny floor under `pulsed_want` (as a fraction of `want_full`), the
# same shape `cruise_px` already floors `base_speed` at 0.1px/s so speed
# can never be a literal, permanent zero anywhere in this effect. Picked
# small enough to be provably inert everywhere it matters: it sits well
# below the shipped defaults' own trough (0.85x) and below the neutral
# setting's constant 1.0x, and even at the "pure surge and coast" test
# endpoint (0, 1) it only lifts that cycle's true trough from exactly 0 to
# 0.02x — still comfortably under the 0.05x the endpoint test itself
# requires for "the coast approaches a stop." It only ever engages in the
# one combination that would otherwise be permanent, never a real one.
MOTION_FLOOR_FRAC = 0.02

# ── THE TAIL DRIVE (2026-10-26, data/fish-swim-plan part 2) ───────────────
# His ask: "the fish could get more realism if their velocity bursts were
# more directly tied to their swimming motion, so a slow moving fish, or
# barely moving fish, would show it's tail swimming and that motion would
# visually propel the fish ... so we still get the good reactive movement,
# but also a more realistic swim"; the plan he approved: "tail-driven
# swimming with beats as strong as today".
#
# Without it the music sets a SPEED and the tail follows the speed (the
# flap's rate and size are read off how fast the fish is going). With
# `tail_drive` on, the music sets an EFFORT and the TAIL IS THE ENGINE: the
# tail's own stroke — its size A and rate f, the very numbers that draw it —
# makes the thrust, the water's drag takes speed away, and the speed is what
# is left. So the tail visibly moves first and the fish surges because of it.
#
#   effort e = the target speed this effect always computed, / cruise (the
#              music's ask, unchanged: the lunge, the swim burst, the solo
#              burst and the big fish's flee all still act on it)
#   thrust   = K (A f)^2 * 2 cos^2(tail-tip phase)   two pushes per stroke
#              cycle, one per sweep, at mid-sweep
#   drag     = d v^2 + l v    cruise units per second; d + l = `glide_drag`,
#              l = TAIL_DRAG_LINEAR_SHARE of it
#   K        = (d + l) / flap_rate^2, so A = 1 at f = flap_rate holds exactly
#              cruise. A stroke for effort e_s beats at f = flap_rate (0.4 +
#              0.6 e_s), today's own rate law, with A = sqrt((d e_s^2 + l e_s)
#              / (d + l)) flap_rate / f, the size that holds e_s steady.
#
# BURST AND GLIDE. Below `glide_below` (an effort) a fish does not wiggle
# slowly all the time: it strokes a short bout harder than asked
# (TAIL_BOUT_GAIN), then GLIDES with its body near straight (TAIL_AMP_GLIDE)
# until it has slowed out of the band H = TAIL_GLIDE_BAND * (1 - e /
# glide_below) either side of the effort. A stroke always runs at least half
# a cycle, and a beat strokes until its envelope (`p_tkick`) falls below
# TAIL_BEAT_ON. The ordinary target never drops below cruise, so this engages
# only when something asks a fish for less than cruise.
#
# No separate power stroke: one was tried in the plan's prototype (rate x2,
# size x1.45) and overshot to 13.7x cruise; the effort alone already matches
# today's beat strength.
#
# SCOPE is exactly the thrust pulse's: mode < 2, not cap-exempt, no school.
# `tail_drive` blends the speed and the drawn flap between the two laws: 0 is
# the pre-tail-drive motion bit for bit (no tail-drive code runs at all, the
# escape hatch), 1 is the tail drive, and the thrust dial
# (`min_drift_speed`/`stroke_speed_cap`) fades out as it rises. It draws no
# random numbers, so the shared generator is consumed exactly as before.
TAIL_DRAG_LINEAR_SHARE = 0.25   # l / (d + l): the linear drag that lets a
                                # glide come to rest (0.4 of 1.6 per s)
TAIL_GLIDE_BAND = 0.5           # the burst-and-glide band at zero effort
                                # (+- this share of the effort)
TAIL_BOUT_GAIN = 2.0            # a bout strokes at this x the effort (never
                                # past glide_below), so the glide that
                                # follows averages it
TAIL_AMP_MAX = 1.5              # tail size ceiling (1 = its cruise size); a
                                # bigger ask beats faster instead
TAIL_AMP_GLIDE = 0.06           # tail size while gliding: near straight
TAIL_FREQ_GLIDE = 0.25          # ... and its slow ripple, x flap_rate
TAIL_AMP_UP_S = 0.04            # the tail's size eases up into a stroke ...
TAIL_AMP_DOWN_S = 0.14          # ... and settles straight into a glide
TAIL_FREQ_S = 0.06              # the stroke rate's ease
TAIL_BEAT_HL = 0.22             # the beat envelope's half-life, s ...
TAIL_BEAT_MAX = 1.5             # ... its ceiling ...
TAIL_BEAT_ON = 0.05             # ... and above this the fish strokes
# THE QUICK MOMENTS: the swim burst's dash, a solo burst and a flee from the
# big fish each ask a fish to answer FASTER than ordinary swimming does (the
# speed ease's own shorter time constant: BURST_SPEED_TAU, SOLO_SPEED_TAU,
# BIG_FLEE_TAU). The tail drive keeps that: while a moment has shortened the
# ease, thrust and drag are scaled together so the speed answers within that
# same time constant (the water's own, 1 / (2 d v + l), is far slower near
# cruise) and settles at the same speed, and its strokes (several a second)
# push with their cycle mean rather than sweep by sweep, so the dash starts
# on its trigger instead of waiting for the next mid-sweep. A beat does not
# shorten the ease, so a beat is the tail drive's own response.
TAIL_STIFF_MAX = 12.0           # the most a moment may quicken it

# ── THE POND REST (2026-10-26, data/fish-swim-plan part 2) ────────────────
# His ask: "at really low music levels, like when it's almost or completely
# quiet, the fish should almost come to a rest, with very sporadic short
# motions, like real fish in a pond"; the plan he approved: "a quiet pond
# rest with occasional darts", for the music Fish scene only, "'quiet' means
# the music's own level".
#
# THE QUIET DETECTOR (`rest_step`, shared with the library check) reads
# `volume()`: 1 + dB SPL / 100, the ABSOLUTE level. The band powers the fish
# otherwise react to are auto-gained (the melbank divides by a slow max), so
# they read a quiet passage as loud within ~2 s. A slow average (REST_SLOW_S)
# is what the rest ENTERS on and a fast one (REST_FAST_S) can only wake it;
# calm starts at `rest_calm_level` and is full rest at `rest_full_level`
# (smoothstep between); the level eases in over REST_IN_S and out over
# REST_OUT_S. No audio callback for REST_SILENCE_S is silence (the audio
# hub's own pause); an effect that has never heard anything reads as loud. A
# strong hit (the lunge's own spike) cuts the level by its size at once: the
# startle.
#
# AT REST an ordinary swimmer's target falls toward REST_SPEED_X of cruise,
# but the beat's own share (the lunge) is never scaled, so the first hit
# after quiet is a full burst, and nor is a moment's (a flee from the big
# fish, the swim burst, a solo dash): the rest is applied after them, to the
# ordinary share only. With the tail drive on, the fins brake (REST_BRAKE
# extra linear drag at full rest, never on a fish a dart or a moment drives)
# and the low effort bursts and glides. Each resting fish keeps a dart clock (mean `dart_every_s`, never
# sooner than DART_MIN_S after its last): a dart is about DART_S of DART_X
# effort with the brake off, toward a heading DART_TURN radians either way.
# A turn needs path (the turn radius caps the rate), so the turn carries on
# through the glide until the fish faces that heading (DART_FACE) or
# DART_STEER_S has passed; then it glides back to rest.
# The beat TRACKER's predicted ticks are scaled by (1 - rest), so a drumless
# quiet passage stops twitching to the tempo grid; a real onset still
# bursts.
#
# SCOPE: ordinary swimmers, and never during a charge, lull or drop, while a
# school is formed or a rush is running, or during a crossfade on either side
# of this effect (a transition program included): the level is held at 0 and
# every dart ends. `quiet_rest` 0 is the motion before it, bit for bit: none
# of it runs and `volume()` is never read. Between 0 and 1 the rest is that
# share of full. The darts draw from their OWN generator, spawned from the
# effect's: the shared stream is never drawn from.
REST_SLOW_S = 1.2       # the average the rest enters on ...
REST_FAST_S = 0.12      # ... and the one that can only wake it
REST_SILENCE_S = 1.0    # this long with no audio callback is silence
REST_UNHEARD = 0.8      # what an effect that never heard anything reads
REST_IN_S = 2.2         # the rest eases in over this ...
REST_OUT_S = 0.15       # ... and out this fast
REST_SPEED_X = 0.03     # the target at full rest, x cruise
REST_BRAKE = 1.2        # extra linear drag at full rest (tail drive), /s
REST_DART_AT = 0.5      # a fish this rested keeps a dart clock
DART_MIN_S = 3.0        # never sooner than this after its last dart
DART_X = 1.6            # a dart's effort, x cruise ...
DART_S = 0.3            # ... for about this long (x 0.6-1.4) ...
DART_TURN = (0.5, 2.0)  # ... turning this many radians, either way
DART_W = 6.0            # the steer toward a dart's heading ...
DART_FACE = 0.15        # ... which lets go once it faces it (rad) ...
DART_STEER_S = 1.0      # ... or this long into the glide after the push
ACCEL_TAU = 0.18        # acceleration smoothing
TURN_GAIN = 3.0         # 1/s: desired turn rate per radian of heading
                        # error, BEFORE the turn-rate clamp. Frame-rate
                        # independent on purpose — an error/dt form makes
                        # every steering term saturate the clamp, which
                        # reads as one permanent tight circle.
WANDER_SWING = 0.18     # radians a fish meanders either side of its
WANDER_SWING_JIGGLE = 0.5  # ... heading, plus this much at jiggle 1
# The pond edge is judged by TURN FEASIBILITY, not by distance from centre:
# a fish steers away only once the water left ALONG ITS OWN HEADING is short
# enough that its turning circle needs the room. A fish cruising parallel to
# the rim has plenty of water ahead and is left alone, so the pond is
# actually used instead of being orbited in the middle.
TURN_CLEAR = 1.0        # turn diameters of clearance the steer needs
BOUND_SOFT = 1.25       # ... and the multiple of that where it starts
BOUND_W = 8.0           # inward steer weight relative to wander/home
BOUND_BRAKE_AT = 0.7    # the boundary SPEED brake (see below, near the
                        # inward steer; live only while a swim burst is) acts
                        # once w_bound passes this fraction of BOUND_W and is
                        # at full strength when the steer is fully engaged.
                        # It takes back ANY speed above cruise (burst, lunge,
                        # the drop boost, whatever produced it), and only on a
                        # fish heading OUTWARD - one already turning back in
                        # is left alone
BOUND_BRAKE_TAU = 1.0 / 60.0  # s over which that brake takes back its own
                        # fraction of the excess, compounded per unit time so
                        # it holds the same at any frame rate. Measured: a
                        # linear ease slow enough to be dt-scaled (0.05 s)
                        # let the overshoot back in, 7.9px past the panel

# ── the wall: a glancing landing, not a turn away (his 2026-10-06/07 asks) ──
# HIS WORDS, 2026-10-06: "the fish don't interact with the 'wall' naturally.
# Have them 'anticipate' the wall and start turning away. Do this on both
# fish scenes." And the next day, on what that first build did: "The fish
# now get stuck in the middle. I still want them to go right up to the edge
# of the wall, but i want them to start turning so their bodies sides touch
# the walls, more than their heads. That should improve how natural the
# motion looks. It's okay for light to bleed off the fixture, I'm more
# interested in a natural look."
#
# What they did before any of this (still reachable at `wall_lookahead = 0`,
# the BOUND_* block above): the pond-edge steer only woke up inside the last
# ~2 px before the turn became infeasible, aimed at the CENTRE of the pond,
# and only watched the fish's MIDDLE — a long fish (his House Fish is 21 px
# nose to tail on a 37 px panel) swam its head into the wall and pivoted at
# its tightest turn. The first build (PR 361) turned AWAY instead: a fish
# kept a whole look-ahead plus 25% of free water in front of it, which for
# a 21 px fish on a 37 px panel is most of the panel — measured, its middle
# visited about 23% of the lit cells and no part of any fish ever reached the
# wall: the shoal circled in a ball in the middle. That is what he saw.
#
# THE GLANCE. A fish swims on until the wall is close, then curves ALONG it:
# it turns on the one circular arc that ends with its heading PARALLEL to the
# wall and its middle WALL_GRAZE half-widths from it — so what arrives is its
# SIDE, laid along the wall, not its nose. For a fish whose middle is `f` px
# (along its own heading) from that landing line, meeting it at angle
# `theta`, that arc's radius is exactly
#     R = f * cot(theta / 2)
# (the perpendicular gap f*sin(theta) closes as R*(1 - cos(theta))). The fish
# leaves the wall alone while R is wider than the arc it wants (the GLANCE
# RADIUS, below), starts turning the frame R falls to it, and is given the
# curvature that still lands it from wherever it is now — steady along a
# straight wall, tighter if it is late or the wall turns a corner ahead.
# Alongside, it carries on WALL_PEEL further on the same arc and lets go,
# so the side brushes the wall and the fish curves back into the water
# instead of riding the rim. No free-water search and no "turn away": the
# wall is where the fish arrives, not something it keeps clear of.
#
# THE GLANCE RADIUS. The nose is drawn straight out along the heading (see
# BODY TRAIL), so the tighter a fish turns the further its nose sticks out
# past its arc. The arc it wants is the tightest one that keeps its NOSE's
# light no deeper past the wall than its FLANK's ends up — his "sides touch
# the walls, more than their heads", as a rule:
#     R_nose(theta) = max over phi <= theta of
#                     (half_len * sin(phi) - give) / (1 - cos(phi))
# with `give` WALL_NOSE_GIVE half-widths (independent of where the middle
# lands). For his fish shape (body_aspect 3) that is about 1.3 body lengths
# for any steep approach and next to nothing for a shallow one — a shallow
# approach just straightens up at the wall. Never tighter than the fish's
# own turn radius, never tighter than the distance it swims in
# `wall_lookahead` seconds (a fast fish sweeps wider and starts sooner), and
# divided by `wall_turn_strength` (lower is a lazier, wider sweep; higher a
# tighter one, nose first).
#
# CORNERS ARE ROUNDED (`_landing_field`). The landing line is the lit edge
# pulled in WALL_GRAZE half-widths, its corners rounded to the glance radius
# (never past WALL_ROUND_FIT of the room inside it): a long fish cannot fly
# a hexagon's corner, and steered into one its nose leaves the panel. On his
# crystal the 90-degree tips are where that mattered: a 21 px fish has to
# turn within less room than its glance arc, so it now curves round on the
# rounded line while its nose still reaches into the tip. MEASURED, honestly:
# a fish this size on a panel this size cannot round a corner without its
# nose brushing past it by a pixel or two, and he has said that bleed is
# fine — what changed is that it arrives side-on and turns smoothly
# (scripts/check_fish_wall.py, his House Fish: 3% of the time at its
# tightest turn against the old edge's 14%, its flank on the wall 57% of the
# time against PR 361's 0%, the body alongside in three contacts out of
# four).
#
# LIGHT MAY BLEED, by his word: WALL_GRAZE 0.3 lands the middle so the flank
# lies over the last lit cells and past them. A middle that is past the
# landing line anyway, heading out, turns back in on its glance arc
# (firmer the deeper it is) until it heads WALL_BACK into the water.
#
# THE WALL IS THE PANEL'S REAL SHAPE. It is read off the virtual's own
# segment list once (`_real_cell_mask`): a cell whose pixel lands on a gap
# device (`fx.utils.is_gap_device`, the render path's own rule) is dark,
# and the lit silhouette (`_silhouette`) is the outline of the real cells
# with the lattice's holes filled — on his crystal-mapper, the hexagon (see
# .claude/skills/crystal-hex-grid). A virtual with no gap devices has the
# whole rectangle as its silhouette. `_wall_field` turns it into a signed
# distance field in SCREEN px, cached by the mask itself. The pond
# (`roam_scale`) still bounds the fish's MIDDLE — a pond smaller than the
# panel (his music Fish scene's 0.75) is a wall of its own, glanced the same
# way — and the silhouette bounds its FLANK. At `roam_scale > 1` the wall
# grows with the pond.
#
# SCOPE: ordinary swimming. While the charge's school is formed, every fish
# keeps the old pond-edge steer — the school is authored choreography whose
# shared heading and window travel he tuned against that edge, the same
# reason mutual avoidance and the thrust pulse stay out of it. The drop's
# rush, the ejecta and a dispersing fish were never bounded by the pond and
# are not by the wall.
WALL_STEP_PX = 1.0       # spacing of the points the path ahead is checked at
WALL_GRAZE = 0.3         # where the middle lands, in half-widths from the
                         # lit edge: most of the flank lies over the last lit
                         # cells (and past them), so the side visibly touches
                         # the wall. Swept (scripts/check_fish_wall.py): 0.6
                         # touched the wall a third less often and left the
                         # nose deeper than the flank more often
WALL_NOSE_GIVE = 0.55    # how far shy of the flank's landing depth (in
                         # half-widths) the nose point is kept: 1 - the nose
                         # splat's own width, so the nose's LIGHT reaches no
                         # deeper past the wall than the flank's
WALL_PHI = np.deg2rad(np.arange(1.0, 90.5, 1.0)).astype(np.float32)
                         # the approach angles R_nose is maximised over
WALL_ON = np.deg2rad(3.0)     # below this angle to the wall a fish is
                         # already gliding along it and is left alone
WALL_OFF = np.deg2rad(1.0)    # ... and at this a turn in is alongside
WALL_PEEL = np.deg2rad(12.0)  # once alongside, a turn carries on this much
                         # further on the same arc before it lets go: the
                         # flank brushes the wall and the fish curves away
                         # again, rather than riding the rim round and round
WALL_HOLD = 1.6          # a turn under way is kept while the arc it still
                         # needs is no wider than this many times the one it
                         # chose (a corner can move the landing a little)
WALL_BACK = np.deg2rad(15.0)  # a middle already past the landing line turns
                         # back in until it heads this far into the water
WALL_BACK_FIRM = 2.0     # ... on its glance arc, tightened by this much per
                         # half-width past the line it is
WALL_ROUND_FIT = 0.85    # the landing line's corners are rounded to the
                         # fish's own glance arc, but never past this share of
                         # the room inside it
WALL_DODGE = 2.0         # a neighbour's swerve during a glance, as a
                         # multiple of the swerve it gets swimming free.
                         # Measured at his crowded music state (10 fish,
                         # roam 0.75): 1x left the glancing shoal crossing
                         # 12% of the time, 2x 8.5% (the pre-wall fish:
                         # 11.9%; PR 361: 14.1%)
WALL_TIE = np.deg2rad(10.0)   # within this of dead-on, a fish turns the
                         # way with more wall to sweep along
WALL_LATE = 0.5          # urgency past which the ease below stops easing
WALL_RISE_S = 0.06       # the turn and authority the wall applies ease up
WALL_FALL_S = 0.15       # ... and back down over these time constants. The
                         # rise shrinks to nothing as the wall gets close
                         # (the ease never makes a turn late); the fall is
                         # slower (a curve straightens, it does not snap)
WALL_FIELD_PAD = 12      # px of field kept past the panel edge, so a fish
                         # arriving from off-panel still has a gradient
WALL_SMOOTH_PASSES = 2   # [1,2,1] blurs on the field: smooths the lattice's
                         # 1-px staircase into a wall a fish can follow

HOME_W = 0.35
HOME_FREE = 0.5         # no home pull inside this fraction of the pond
WANDER_W = 1.0
AVOID_W = 6.0           # mutual-avoidance steer weight at avoid_strength 1,
                        # relative to wander/home. Below BOUND_W on purpose:
                        # dodging a neighbour must never win against the pond
                        # edge, or a crowd would push a fish out of the water.
AVOID_MAX_TURN = np.pi / 2.5  # the widest a swerve ever ASKS for, before
                        # the turn-rate clamp has its say. A quarter-turn
                        # aside clears a neighbour; asking for more only
                        # spends arc the fish does not have.
AVOID_SEP_BODIES = 1.6  # separation radius as a multiple of BODY LENGTH — the
                        # radius is DERIVED from the fish's own size, never a
                        # second knob: bigger fish need more room by
                        # construction, and a blob_size/body_aspect edit can
                        # never leave the avoidance mis-scaled.
SCHOOL_W = 14.0         # alignment dominates while a school is formed
# HIS ASK (2026-08-28): "in the charge, I don't want the fish to clump so
# much and I want them evenly distributed across the screen" — while still
# arriving together. Two things do it, and neither touches the shared
# heading that IS the unison:
#   * they SPAWN on an even lateral spread instead of a uniform-random one
#     (see _spawn_school: a random spread has clusters and gaps by
#     construction, and equal speeds on a shared heading preserve whatever
#     spread they started with, so a clumpy start stays clumpy);
#   * and a SEPARATION steer keeps them apart once formed. This is not the
#     forward-arc dodge `avoid_strength` runs (still off in a school): every
#     close neighbour pushes, whichever side it is on, so a converging pair
#     opens out whether it is head-on or side by side. Its weight sits well
#     under SCHOOL_W, so the shared heading still dominates and the school
#     still arrives together — the spacing only bends it.
SCHOOL_SPACING_W = 6.5
RUSH_SWIRL_W = 9.0      # the drop's rush swirling around the centre of
                        # view: a TANGENTIAL steering weight, bounded by
                        # the same turn-rate clamp as everything else
SCHOOL_SEP_BODIES = 3.0  # target spacing, in BODY LENGTHS — derived from the
                         # fish's own size for the same reason
                         # AVOID_SEP_BODIES is, never a second knob
# Low-discrepancy spawn offsets: any PREFIX of these sequences is already
# evenly spread, which matters because a school fills progressively (see
# _charge_step) — an in-order even spread would fill one side of the panel
# first and only look even once the last fish arrived.
SCHOOL_PHI_LAT = 0.6180339887   # golden ratio, lateral
SCHOOL_PHI_DEPTH = 0.7548776662  # plastic number, depth

# ── the wake ──────────────────────────────────────────────
# HIS ASK (2026-08-28): "the ripples ... more like the trails in Orbits, but
# ... expand and fade instead of just fading. I don't like the circles that
# form because the circle line is kind of messy."
#
# So there is no ripple any more — no radius, no ring, no outline to read as
# messy. The wake is ORBITS' OWN MECHANISM: a persistent accumulation buffer
# decayed exponentially every frame (`buf *= 0.5 ** (dt / half_life)`, the
# same shape `self.trail` already uses for the bodies), with ONE addition —
# the buffer also DIFFUSES outward every frame, so what was deposited opens
# out as it dims. Deposits are soft FILLED splats laid at the tail every
# frame, never stamped shapes.
#
# The energy still scales off REAL MOTION (swim speed x the tail's own
# throw), never a bare beat value, so the lunge's longer travel lays down a
# longer smear for free.
WAKE_HALF_LIFE_X = 0.42   # wake half-life as a fraction of `ripple_life`,
                          # so the knob keeps meaning "seconds to fade"
WAKE_EXPAND_K = 2.6       # diffusion blend per second per unit of
                          # `ripple_spread` — THE expand half of his ask
WAKE_EXPAND_MAX = 0.85    # ... and the most of one frame it may ever be, so
                          # a long frame can never flatten the buffer in one
                          # step (the diffusion kernel is a 3-tap average;
                          # blending it in fully is still a real blur, but
                          # more than that is not defined)
WAKE_DEPOSIT_HZ = 26.0    # deposits are per-frame and scaled by dt x this,
                          # so the wake is frame-rate independent and its
                          # steady state is set here rather than emerging
                          # from whatever frame rate the host happens to run
RIPPLE_BASE = 0.08      # brightness floor: "the trail is always subtle"
RIPPLE_SPEED_GAIN = 0.55  # ... "but stronger on faster" — measured against
                        # the fish's OWN cruise, so "faster" means this fish
                        # speeding up (audio, a drop boost), not a
                        # differently-tuned scene
RIPPLE_SPEED_FLOOR = 0.5  # cruise sits this far up the speed ramp …
RIPPLE_SPEED_SPAN = 1.5   # … which tops out this far above it
WAKE_FLAP_FLOOR = 0.55  # the deposit pulses with the tail: this much always,
WAKE_FLAP_GAIN = 0.45   # ... plus this much on the throw's own |sin|. The
                        # flap is what used to set the ripple CADENCE; it now
                        # sets the deposit's own texture instead, which keeps
                        # the wake tied to the body's real motion without
                        # anything being stamped.
WAKE_R0_BODY = 0.30     # splat radius from the body's own length …
WAKE_R0_FLAP = 0.60     # … plus this much of the tail's lateral throw
WAKE_R_MAX_BODY = 1.1   # … and a deposit is never wider than this many body
                        # lengths ("match the size of the motion to the
                        # ripple" — the wake is fish-sized, not panel-sized;
                        # the DIFFUSION is what opens it out past this, not
                        # the deposit)

# COLOUR — the rule, stated, and his reversal of half of it.
#
# 2026-08-28, his ask: "a different color from the fish if there is a
# gradient to work with, or if it's a solid/uniform color, at least
# substantially less bright than the fish". On a rainbow that put the
# OPPOSITE colour under every fish, and the bodies and the wake were ADDED
# together — complementary light summed is white. Measured on his crystal
# (data/fish-swim-plan, a busy rainbow arc) that was the main source of the
# wash-out he reported on 2026-10-26: "the fish scene gains a lot of white
# color, especially in rainbow effects when there is a lot going on". His
# answer the same day: "I approve option A for the wake" — the wake wears
# the fish's OWN colour and meets the bodies by LIGHTEN, not by adding.
# Both of the old choices stay one setting away: `wake_hue = opposite` with
# `wake_blend = add` renders exactly as before, frame for frame.
#
# THE DECISION RULE, read off the RESOLVED gradient curve and not the config
# string: sample the built curve end to end; if every channel's spread
# across those samples is within WAKE_SOLID_TOL, the palette is SOLID.
#   * SOLID  → the wake wears the fish's own colour at WAKE_SOLID_DIM of its
#              amplitude, whatever `wake_hue` says (every point along a solid
#              is the same colour). Distinctness is a BRIGHTNESS ratio.
#   * GRADIENT → the wake samples the gradient WAKE_HUE_OFFSETS[wake_hue]
#              further along than the fish that made it: `own` (the default)
#              is the fish's own colour; `neighbour` is an eighth along (a red
#              fish leaves an orange wake); `opposite` is half a turn, the
#              2026-08-28 rule — the furthest apart two points on a wrapped
#              gradient can be.
WAKE_SOLID_TOL = 8.0 / 255.0
WAKE_SOLID_DIM = 0.35
WAKE_HUE_OFFSETS = {"own": 0.0, "neighbour": 0.125, "opposite": 0.5}

# THE BLEND (`wake_blend`) — how the WATER (the wake, and the big fish swimming
# behind the shoal) meets the BODIES in the final mix (`_composite`):
#   * lighten (default) → per channel, whichever is brighter. No channel is
#              ever brighter than the brighter of the two layers (a sum can
#              reach twice that), and a fish over its own-colour wake shows
#              exactly the fish. The water goes in through a hue-preserving
#              clip (an over-bright pixel is scaled down as a whole,
#              `_hue_clip`).
#   * under  → the water shows only where the fish is not: a body hides what
#              is behind it in proportion to how lit the body is.
#   * add    → bodies + water, clipped per channel (everything before
#              2026-10-26).
WAKE_BLENDS = ("lighten", "under", "add")

# ── the camera window ───────────────────────────────────────────────────────
# The panel is a WINDOW onto a larger body of water, not the whole of it.
# Fish and ripples live in WORLD pixels; the camera is an origin that maps
# world -> screen (screen = world - cam). AT REST THE MAPPING IS THE
# IDENTITY, so every expression downstream reduces to exactly what it was
# before this existed — which is what makes `camera_follow = 0` byte-
# identical rather than merely close.
#
# What it replaces: the charge used to hold the school on screen by
# SUBTRACTING the school's own velocity from every swimming fish (the
# "clamp" below). That is a window locked rigidly to the shoal — the shoal
# cannot move within it, and the water streams past at exactly the swim
# speed, one motion, not two. `camera_follow` hands that travel back to the
# fish and gives the window its own, slower, LAGGING speed instead: the
# school crosses the panel AND the water streams past it, at two different
# rates. The lull had no window motion at all before this, so its wake was
# dead still on screen; it moves now too.
#
# The window moves ONLY during the charge and the lull. Everywhere else it
# eases back to rest at the same bounded rate, and the home-ring tether
# keeps ordinary roaming centred exactly as it always did.
CAM_TAU = 0.55          # s: how hard the window pulls toward the school.
                        # A LAG, on purpose — a window that tracked
                        # perfectly would pin the school again and show
                        # nothing, which is the state this replaces.
CAM_VEL_TAU = 0.35      # s: the window's own acceleration ease, so a beat
                        # turn cannot snap the view. The old clamp had
                        # exactly that snap: the water changed direction
                        # the instant `_school_hd` did.
CAM_MAX_SPEED_X = 1.4   # the window can never pan faster than this
                        # multiple of cruise. A rush fish runs at 2.2-3.3x
                        # cruise and a lunge adds more again; neither can
                        # whip the view.
CAM_LEASH = 0.55        # ... and however far it lags, catching up becomes
                        # the whole job once the school's centroid is this
                        # far from the middle of the window — as a fraction
                        # of the panel's SHORT half-axis, so the bound means
                        # the same thing whichever way the school travels.
                        # The correction is a position nudge folded into the
                        # SAME per-frame step cap, so it can never teleport.
CAM_REST_EPS = 1e-3     # px: below this, and not following, the camera IS
                        # zero — the identity mapping is restored exactly,
                        # never left sitting on a residue.
WAKE_SHIFT_EPS = 1e-6   # The wake buffer is SCREEN space but WORLD
                        # anchored: every frame it is rolled by exactly the
                        # displacement the world->screen mapping moved (the
                        # current's own flow, minus the window's own step),
                        # with the sub-pixel remainder carried across frames.
                        # Content rolled off an edge is DROPPED, never
                        # wrapped — that is the cull, and it needs no pad,
                        # because a pixel outside the buffer cannot light
                        # anything. Below this the shift is not worth a roll.

# ── charge / lull / drop choreography ───────────────────────────────────────
# SpotFX writes `phase` (instant) and ramps `phase_progress` 0->1 over the
# event's ramp; see _phase_step.
CHARGE_FILL_AT = 0.45   # school is fully gathered here; beat turns arm after
CHARGE_TURN_MIN = (np.pi / 3.0, 2.2)  # turn magnitude range, radians
# TIMING HONESTY (the convention blackhole.py's LULL_FILL_PROGRESS records):
# SpotFX ramps phase_progress over ~90% of the real gap and then hangs at
# 1.0 (scene_response._phase_ramp_ms), so p=0.5 lands at ~45% of the lull's
# true wall-clock duration, not exactly half. That is the closest an effect
# can get to his "by half way through the lull" without ever being told the
# duration.
# HIS 2026-10-08 LULL — ONE FISH STAYS AND SEARCHES (the Admiral, verbatim:
# "have all the fish leave over time except for one, so one is left at the
# half way mark. then have that last fish move slowly and look like it's
# searching. have it move to one side, pause, then move to the other. then
# on the drop, all the missing fish come back in the rush we currently
# have"). This REVERSES, on his own word, the 2026-08-28 "no lone fish"
# clock described just below; that clock is still the lull when the lull
# is told `lull_keep = 0` (fx/effects/lull_handoff.py — the hand-off hook
# the drop-scene-variety work drives), byte for byte, and only then.
#   lull edge        the school breaks into the swirl exactly as before,
#                    except the `lull_keep` fish nearest the centre of view
#                    (default 1) — the KEEPERS (mode 5) — which ease toward
#                    the centre and slow down instead of swirling.
#   -> half way      everyone else leaks out of the swirl in rank order,
#                    furthest first, across KEEP_LEAK_FROM..KEEP_LEAK_TO of
#                    the way to the half-way mark, aimed off the panel by
#                    KEEP_EXIT_BY of it; a backstop at the mark retires
#                    anything that is not a keeper. The half-way mark is
#                    SECONDS (lull_s / 2) when SpotFX told the lull its
#                    length, else phase_progress 0.5 (~45% of the clock).
#   half way -> drop THE SEARCH: a slow leg (`search_speed` x cruise) toward
#                    one side of the pond (`search_reach`) — first the side
#                    it already faces, no about-face — a PAUSE at a hover
#                    with its head swinging as if looking (`search_pause_s`
#                    at most, shorter on a short lull), then a leg to the
#                    other side, and so on until the drop lands, usually
#                    mid-leg. The lull is never dark: the keeper's wake
#                    keeps rippling. The window does not follow a keeper,
#                    so the search plays out against a settled view.
#   the drop         the keepers rejoin the population (mode 0) and are
#                    boosted with everyone into the existing rush.
# More than one keeper (`lull_keep` N, e.g. 3 for a drop that lands on
# Fireworks) holds a loose, evenly spaced group that searches together;
# told a different `lull_next` effect, the group spaces itself further
# apart so the arriving effect adopts N distinct origins.
KEEP_LEAK_FROM = 0.15     # of the way to the keep mark: first leak ...
KEEP_LEAK_TO = 0.8        # ... last leak ...
KEEP_EXIT_BY = 0.95       # ... every leaver aimed off the panel by here
KEEP_SPACING_BODIES = 1.6       # keeper-to-keeper spacing, body lengths
KEEP_SPACING_NEXT_BODIES = 3.0  # ... when the drop lands on another effect
KEEP_GROUP_MAX = 0.6      # the group row never spans more of the pond's
                          # width than this either side
KEEP_SEEK_W = 14.0        # how hard a keeper steers for its target
KEEP_SEP_W = 20.0          # ... and away from a keeper closer than the
                          # group's own spacing (several keepers only), so
                          # an about-face's arc cannot fold the row up
KEEP_LEVEL_W = 6.0        # a keeper's pull back toward the window's middle
                          # height: its legs run side to side, so it is the
                          # only containment a keeper needs, and it is what
                          # picks which way an about-face arcs (away from
                          # the nearer top/bottom wall). Keepers are kept
                          # off the wall glance: its authority would take a
                          # searching fish over mid-turn and run it along
                          # the wall instead of back across the pond.
KEEP_LEVEL_SPAN = 0.25    # ... at full weight this far off the middle, as
                          # a fraction of the panel's height
KEEP_SPEED_TAU = 0.2      # a keeper's speed ease: it settles into a pause's
                          # hover in a fraction of a second, not a drift
SEARCH_PAUSE_X = 0.12     # hover speed in a pause, x cruise (fins breathe)
SEARCH_PAUSE_MIN_S = 0.5  # a pause is never shorter than this ...
SEARCH_PAUSE_FRAC = 0.18  # ... and otherwise this share of the time left,
                          # capped by `search_pause_s`
SEARCH_LEG_SHARE = 0.25   # the FIRST leg is budgeted this share of the time
SEARCH_LEG_MIN_S = 0.35   # left (never less than this), so even a short
                          # lull fits a leg, a pause and the turn back before
                          # the drop; every later leg runs to the reach (the
                          # drop usually lands mid-leg)
SEARCH_LEG_SLACK = 1.6    # a leg that has not arrived within this many times
SEARCH_LEG_SLACK_S = 0.5  # its own travel time (+ this) pauses anyway: a
                          # turn arc can make the straight-line time a lie
SEARCH_Y_WANDER = 0.15    # each leg's target strays this much of the pond
                          # up or down, so the search is not a ruled line
SEARCH_LOOK_SWING = 0.5   # radians the head swings either way in a pause
SEARCH_LOOK_HZ = 0.9      # ... this many times a second
SEARCH_LOOK_EASE_S = 0.15  # ... eased in and out
PHASE_RAMP_SHARE = 0.9    # SpotFX's ramp covers this much of the gap (scene_
                          # response.PHASE_RAMP_HANG_FRACTION's complement):
                          # how an UNTOLD lull's length is read off its ramp
# THE PRE-DROP (fx/effects/pre_drop.py is the binding statement; predrop
# plan step 8, the plan's 3.5: "the searching fish darts to the centre on
# the pre-drop, then waits there poised, its head quivering, until the
# drop"). Told one, the searching lull is measured to the pre-drop — the
# half-way keep mark is half the way to it and the search's legs end on
# it, the rule the engine already applies to every member's ramp, dark
# point and breath — so the lone searcher is there to go. On the pre-drop
# each keeper turns sharply (its turn circle PRE_DROP_TURN of its own for
# the whole gap) and darts to its place at the centre of view, at the
# speed that arrives in PRE_DROP_DART_S; arrived (or PRE_DROP_DART_MAX_S
# on), it waits there poised: a tight coil round its place, fast at first
# and settling, its head quivering harder toward the drop — the plan's
# approved prototype, number for number (its contact sheet: the fish loops
# at the centre, its wake curling in the new colours). The drop is today's
# rush. Fish takes no breath (BREATH_HOLD below), so the lull is never
# dark. A lull told to keep several fish moves them the same way, each to
# its own place in the row.
PRE_DROP_LOOK = "dart"
PRE_DROP_TURN = 0.25           # the keepers' turn circle x their own, the gap
PRE_DROP_DART_S = 0.28         # the dart's speed is sized to arrive in this ...
PRE_DROP_DART_SPEED = (1.0, 7.0)   # ... held to this range, x cruise
PRE_DROP_ARRIVE_BODIES = 1.2   # arrived within this many body lengths (2 px
PRE_DROP_DART_MAX_S = 0.45     # at least), or this long after the pre-drop
PRE_DROP_COIL_BODIES = 0.9     # the poised coil's radius, body lengths
PRE_DROP_COIL_REV = (2.2, 0.8)     # its turns a second, settling ...
PRE_DROP_COIL_SETTLE_S = 0.5   # ... over this long after arriving
PRE_DROP_COIL_LEAD = 0.6       # radians ahead on the circle a keeper aims
PRE_DROP_QUIVER = (0.15, 0.45)     # the head's quiver, radians, rising to
PRE_DROP_QUIVER_HZ = 8.0       # the drop, this many times a second
#
# HIS LULL CLOCK (2026-08-28) — now only `lull_keep = 0` — in THIRDS of the
# lull's own duration, and the duration is the dynamic ramp gap SpotFX
# drives `phase_progress` over, never a wall-clock constant:
#   0 -> 1/3    every fish disperses and is GONE by the end of it. None
#               survive: no lone fish, no exceptions, and a hard backstop
#               retires anything the paced dispersal has not already sent
#               away.
#   1/3 -> 2/3  ripples only. The wake buffer keeps expanding and fading
#               with no fish anywhere.
#   2/3 -> end  fully dark, until the drop.
# SUPERSEDED, on his own instruction, by the above: the lull used to
# disperse down to ONE fish held at the centre of view by half way through
# (LULL_CENTER_PROGRESS / LULL_CENTER_PULL / CENTER_W / `p_lone`), and its
# RUSH used to arrive at 60% of the lull. The lone hold is gone outright.
# The rush is NOT gone — it MOVED INTO THE DROP (see _drop_step), which is
# where he asked for it: "I want the rush to be part of the drop."
LULL_GONE_AT = 1.0 / 3.0
LULL_DARK_AT = 2.0 / 3.0
# HIS 2026-09-16 LULL, laid INSIDE that same first third (the clock is his
# 2026-08-28 ruling and is not moved — "gone by 1/3" already satisfies "all
# gone by half way"; this changes only HOW they go): "when we reach the lull,
# have them go from their ordered school to a chaotic swirl, and as they
# swirl, have them leak out and off the screen." Fractions of LULL_GONE_AT:
LULL_LEAK_FROM = 0.4     # the school breaks into the swirl at once; the
                         # first fish leaks out here (the swirl needs real
                         # time to form — measured, see
                         # scripts/check_fish_disperse.py) ...
LULL_LEAK_TO = 0.72      # ... the last one here ...
LULL_EXIT_BY = 0.92      # ... and every one is aimed to be off the panel by
                         # here, ahead of the backstop at the third. AIMED,
                         # not guaranteed: at a 0.9 s gap this leaves only
                         # ~22ms before the backstop's instant full-brightness
                         # `_compact`. scripts/check_fish_disperse.py section
                         # 1 holds it strict (== 0) over its sampled seeds
                         # and gaps, which passes only with the DISPERSE_TAU
                         # mitigation — see that constant for the residual
                         # slack, a known, accepted limitation.
LULL_EXIT_MIN_S = 0.3    # ... but no fish leaks later than this many SECONDS
                         # before that exit moment. A lull too short to swirl
                         # in (his real gaps run from 900 ms to 6 s) scatters
                         # straight out rather than waiting to be retired on
                         # the panel by the backstop — subject to the same
                         # ~22ms residual slack at a 0.9 s gap (DISPERSE_TAU).
LULL_SWIRL_W = 10.0      # tangential steer around the centre of view
LULL_SWIRL_RING = 0.45   # ... held near this fraction of the pond radius
LULL_SWIRL_RING_W = 4.0  # ... by a radial correction this strong
LULL_SWIRL_CHAOS = 1.1   # radians of per-fish heading noise — the chaos
LULL_SWIRL_CHAOS_W = 0.35  # ... weighted against the swirl itself: more and
                           # the school never actually wheels round
LULL_SWIRL_SPEED_X = 1.7  # swirl speed, as a multiple of cruise
LULL_DARK_FROM = 0.5     # the wake is ramped to nothing between here and
                         # LULL_DARK_AT, so the last third is genuinely dark
                         # rather than "decayed enough": a half-life alone
                         # can never reach zero, and his ask is DARK
LULL_FALL_S = 3.0        # wall-clock fallback when no lull ramp arrives
DROP_FLY_S = 0.4
DROP_SETTLE_S = 4.2      # drop boost decay / phase auto-reset horizon
DROP_BOOST = 2.5         # extra swim speed at the drop instant
DROP_EJECTA_SPEED = (1.6, 2.9)  # ejecta speed, multiples of cruise

# ── THE BIG FISH (2026-10-08, his ask, verbatim: "add a flare to fish,
# where a really large fish swims directly across the screen, in the
# background of the others, and at 60% brightness (tuneable). ... The speed
# it goes at is dependant on intensity. the color should be the 120 to 180
# degree rotation of the central color of the scene, so it contrasts. at .5
# intensity or higher 180 degrees, scale linearly to .2 insesity = 120
# degrees (either direction)") ─────────────────────────────────────────────
# PHASE 1 was the look; PHASE 2 (the block below, BIG_AVOID_W) is the
# ordinary fish steering out of its way, built once he approved the look.
#
# SpotFX's `big_fish` flare kind (spectra scene_response._big_fish) pokes
# the unregistered, self-resetting `big_fish` key with the fire's own
# intensity (floored at BIG_FISH_POKE_FLOOR so a fire at 0 still edges).
# One poke = one big fish, entering fully off one side of the panel and
# swimming straight across to fully off the other, at a height near the
# middle (BIG_FISH_Y_SPREAD). Which side it starts from is a coin flip per
# fire.
#
#   SPEED: `big_fish_cross_slow_s` is the crossing time at intensity 0 and
#   `big_fish_cross_fast_s` at intensity 1; the SPEED (not the time) is
#   linear in intensity between them (big_fish_cross_s), so a loud fire is
#   proportionally faster rather than the time shrinking linearly.
#   COLOUR: the gradient's centre (position 0.5, never rolled by
#   gradient_spin — the scene's colour, not a fish's) with its hue turned by
#   big_fish_hue_degrees: 120 at intensity 0.2 or less, 180 at 0.5 or more,
#   linear between. The DIRECTION of the turn (+ or -) is a coin flip per
#   fire (his "either direction"); at 180 the two are the same colour.
#   Saturation and value are kept, so an achromatic (white/grey) centre has
#   no hue to turn and the big fish wears that same white/grey.
#   Re-read every frame, so a colour jump mid-crossing keeps it contrasting.
#   THE BODY IS AN ORDINARY FISH, BIGGER (2026-10-08, his word on the first
#   build: "the fish looks all wrong. it should be the same as the other
#   fish in the effect, just bigger, in the background, and dimmer, with a
#   dim but large ripple"). It is drawn through the very same spine layout,
#   flap wave and splats as every ordinary fish (`_spine_wave`,
#   `_splat_spines`, SPINE_PROFILE at the effect's own `body_aspect`), its
#   stroke follows the ordinary flap rules read in body lengths a second
#   (`_big_fish_motion`), it carries the ordinary fish's audio brightness
#   and size swell, and it keeps the same persistent smear (`trail_decay`).
#   A big fish crossing at the body-lengths/s an ordinary one cruises at
#   strokes exactly like it. It still swims STRAIGHT across: a straight run
#   is the one case where an ordinary fish's trailed body IS its
#   all-heading layout, so nothing about its shape differs.
#   BRIGHTNESS: `big_fish_brightness` (0.6 default, his number) scales the
#   finished body, so 60% means 60% of what an ordinary fish of that colour
#   would show. Overlapping splats are clipped to 255 KEEPING THE COLOUR
#   (the scatter's clip), so his 120-180 degree rule survives the body's
#   bright middle.
#   THE WAKE: it lays the ordinary fish's own wake (at the tail, sized off
#   the body and its tail throw, stronger when faster), scaled to its size
#   and in its own colour, into the shared wake buffer — so it ripples
#   through the water like theirs, LARGE because the rule scales with the
#   body, and DIM because the rule is "stronger when faster" in body lengths
#   a second, which a big slow fish barely is (measured: its wake peaks
#   near a fifth of its body, a quarter of the ordinary fish's wakes).
#   `big_fish_ripple` scales its level (1 = that rule; 0 = no wake) and
#   `big_fish_ripple_size` its width (1 = in proportion to its body).
#   BACKGROUND: its own layer, composited UNDER the ordinary fish: wherever
#   the ordinary fish's body layer is lit, the big fish is hidden in
#   proportion (fully at BIG_FISH_OCCLUDE_AT), so a fish swimming across it
#   reads in front. The lull's dark applies to it and its wake like
#   everything else.
#   SIZE: `big_fish_size` is its body length as a fraction of the panel
#   width. It swims in SCREEN space (the camera window never moves it).
# At most BIG_FISH_MAX are on the panel at once; a poke past that is
# counted (big_fish_dropped) and ignored.
BIG_FISH_POKE_FLOOR = 0.001
BIG_FISH_MAX = 3
BIG_FISH_Y_SPREAD = 0.15       # of the panel height either side of middle
BIG_FISH_MARGIN_PX = 2.0       # past the widest splat, at both ends of a run
BIG_FISH_OCCLUDE_AT = 48.0     # ordinary-fish level (0..255) that hides it
BIG_FISH_GONE = 0.5            # its smear under this (0..255) has gone
BIG_FISH_RIPPLE_DEFAULT = 1.0   # its wake level: 1 = the ordinary wake rule
BIG_FISH_NODE_PX = 1.5         # its spine is sampled this often (px) ...
BIG_FISH_NODES_MAX = 64        # ... up to this many nodes
BIG_FISH_HUE_LO = (0.2, 120.0)  # (intensity, degrees) — his two points
BIG_FISH_HUE_HI = (0.5, 180.0)

# ── THE OTHER FISH AVOID IT (2026-10-08, phase 2; his approval of the look:
# "Big fish looks right: build step 2 - the other fish steer around the big
# fish while it crosses") ──────────────────────────────────────────────────
# While a big fish is crossing, every ordinary swimmer (and the lull's
# keepers) ANTICIPATES its path and gets out of its way, the way they already
# handle the wall and each other: a term in the same desired-heading sum,
# bounded by the same turn-rate clamp, so a dodge is always an arc and never
# a snap. `_big_fish_threat` is the whole judgement:
#
#   THE BODY it keeps clear of is the big fish's OWN drawn body — its centre
#   line, and at each point along it the LIT CORE of the splat the renderer
#   lays there (BIG_AVOID_CORE of its reach: the faint fringe past it is
#   glow, not body) plus its tail throw — the tapering profile, not a box —
#   grown by the ordinary fish's own lit core at five points along ITS body
#   and `big_fish_avoid_margin` px. So "body size + a margin" is read off
#   what is drawn, and a bigger ordinary fish keeps further off by
#   construction.
#   ANTICIPATION (`_big_fish_threat`): both bodies are rolled forward
#   BIG_AVOID_LOOK_S, the fish along its current heading and speed AND
#   holding still in the water — the big fish is faster than a cruising fish
#   at every intensity, so "will its body sweep over the spot I am in" is
#   the question that matters, and the heading rollout keeps a fish that has
#   got out from turning straight back in. Urgency is how soon the first
#   contact comes (1 = now), or how close the body already is.
#   THE WAY OUT is a small SEARCH, not a rule: spots around the fish
#   (BIG_AVOID_ANGLES x BIG_AVOID_RADII_PX) inside the lit panel, each scored
#   by how clear of the big fish's moving body it stays from when the fish
#   could be there to the end of the look-ahead AND every step of the way
#   there — less a little for distance, plus a little for the one it already
#   faces (no bias to a side of the panel). The crystal is a hexagon: near
#   its points there is no room above or below the big fish at all, so "turn
#   off its line" alone sends a fish there into the wall; the search makes
#   for where the room is (above, below, or behind it once it has passed).
#   HOW IT MOVES: a heading term like the neighbour swerve, and the same
#   turn-rate clamp — but a startled fish turns up to its turn circle
#   (BIG_TURN_BOOST), comes about the way that swings it AWAY from the big
#   fish's line (never the short way through it), and darts a little
#   (BIG_FLEE_X of its own speed at full urgency, on a short ease). The soft
#   pond (`roam_scale`) gives way for it (`_wall_landing(free=)`, the glance
#   off the lit panel only): his music Fish's pond is too small to hold a
#   fish beside a big fish centred on the panel.
#   THE WALL WINS: while the wall is late turning a fish back from a wall it
#   is heading into, the wall keeps it (the threat's term still rides the
#   neighbour swerve's "toward the water only" filter); otherwise the threat
#   steers, toward a spot already inside the panel. Measured
#   (scripts/check_fish_big_fish_avoid.py): no fish goes further past the
#   lit edge than without the big fish. THE HONEST LIMIT: at the hexagon's
#   two points the big fish fills the whole lit height, so a fish caught
#   there by the wall can brush it as it passes — in the middle columns,
#   where there is room, no fish's middle is ever on it.
#   SCOPE: ordinary swimmers (mode 0/1, the charge's school included — a big
#   fish swimming through a school would overlap all of it) and the lull's
#   keepers. The drop's rush and ejecta (authored chaos) and dispersing fish
#   (on a deadline) are left alone. With no big fish crossing, nothing here
#   runs: every frame is exactly the frame drawn before this existed.
#   `big_fish_avoid` 0 turns it off (the escape hatch: the step-1 crossing
#   bit for bit).
BIG_AVOID_W = 20.0           # steer weight at urgency 1, big_fish_avoid 1:
                             # above the school's 14, so a school bends
                             # round it too
BIG_AVOID_LOOK_S = 2.5       # how far ahead (s) both bodies are rolled
BIG_AVOID_STEPS = 13         # ... in this many samples
BIG_AVOID_NEAR_PX = 3.0      # inside this much clearance urgency rises with
                             # closeness alone
BIG_AVOID_ANGLES = 16        # the spots a fish weighs for its way out:
BIG_AVOID_RADII_PX = (4.0, 8.0, 14.0, 20.0, 26.0)  # ... this many directions, at
                             # these distances
BIG_AVOID_WAY = np.array([0.25, 0.5, 0.75], dtype=np.float32)
                             # ... and the way there is checked at these
                             # shares of it, each when it would be there
BIG_AVOID_GOOD_PX = 2.0      # clearance past which a spot is simply clear
BIG_AVOID_DIST_COST = 0.15   # px of clearance a px further away is worth
BIG_AVOID_FACING = 0.3       # px of clearance facing a spot is worth
BIG_TURN_BOOST = 3.0         # its turn gain x (1 + this) at full urgency —
                             # never past its own turn circle
BIG_FLEE_X = 1.6             # its own speed x this at full urgency ...
BIG_FLEE_TAU = 0.15          # ... eased in over this
BIG_AVOID_CORE = 0.7         # the share of a splat's reach counted as BODY:
                             # a splat's light falls off linearly to its
                             # reach, so this is where it is still about a
                             # quarter lit (measured on the big fish's own
                             # cross-section) — the faint fringe past it is
                             # glow, not body, for both fish
BIG_AVOID_U = np.array([0.0, 0.25, 0.5, 0.75, 1.0], dtype=np.float32)
                             # the ordinary fish's body, sampled nose to tail

# ── WORD SHAPES: a procession along the outline (plan row W1.4) ─────────────
# HIS WORDS for the row: "Fish: similar to orbits ... they need to smoothly
# accelerate and not have sudden velocity shifts", and on the first design:
# "the fish didn't seem to be sufficiently making the outline. We may need to
# boost the trail brightness and lower decay briefly to get it to show
# better. They also may need to more tightly flow." P2 A, approved: with FEW
# fish the water keeps a trace of the loop while the fish swim it.
#
# WHAT HAPPENS. A sung word that reaches a shape fires the showing scene's
# Words response and the `word_shape` kind writes the six told keys
# (fx/effects/word_shape_keys.py) in ONE jump. This effect edge-detects the
# SEQ, runs the whole form/hold/release on its own clock and resets itself
# after; it never writes a key back. Every fish is assigned a place on the
# outline, swims onto it under its ORDINARY turn clamp and speed ease — the
# lull keepers' steer-to-target is the pattern — and then circles the loop
# nose to tail for the hold. The trail brightens and lingers, and with few
# fish the wake carries a trace of the loop behind them, so the whole
# outline shows with only two or three.
#
# STEERED, NEVER PLACED, and nothing here is a new MODE: a shaped fish is
# an ordinary swimmer (mode < 2) with the loop's own steer summed into the
# same desired-heading vector every other term lands in, bounded by the
# same turn-rate clamp. So the two fish laws still hold structurally — no
# fish reverses on the spot, every about-face is an arc — and the whole
# mechanism is a BLEND on the rest geometry: at m = 0 (untold, or after the
# release) not one expression in draw() differs from today's, which is what
# `tests/test_fish_word_shape.py`'s pinned-module proof holds.
#
# THE ENVELOPE IS THE SPEED, NEVER THE AIM (his "smoothly accelerate"): the
# told smoothstep `m` paces how hard the loop pulls and how fast a fish
# runs, but a fish heads for its entry from the FIRST frame of the form.
# `grip` is the loop's own authority — 1 from that first frame, let go over
# the first half of the RELEASE (WS_RELEASE_GRIP), so the fish return to
# wandering with heading and speed intact while the trail is still fading.
#
# THE ENTRY RULE. Each fish's entry is the outline point on its OWN bearing
# from the centre of view, so no two cross on the way in; no two entries are
# within WS_ENTRY_MIN_GAP / n of the loop; and over WS_SPACE_EASE_S the
# entries ease to EVEN spacing, each fish keeping its order round the loop.
# The bearing is read in the fish's own normalized space, which is the
# shape's own space up to one scale per axis (`sx` and `sy` share
# `radius_scale`), so the two angles are the same angle.
#
# THE PAUSES (plan 3.4): the wall's authority, the big fish, a swim burst
# and the pond rest are all held while a shape runs and resume after; one
# already in flight finishes. The wall's hold is faded by m exactly the way
# a big fish's threat already relaxes it, EXCEPT where the wall is late
# turning a fish back from a wall it is heading into — "the pond gives way,
# the wall does not" (the BIG_AVOID block) is kept, so nothing here can push
# a fish off the panel. The lunge, the solo burst and the speed moments need
# no gate of their own: they multiply the ORDINARY target, which the blend
# below fades out.
#
# WHAT WRONG LOOKS LIKE. P3 A means a shape is never TOLD while a charge,
# lull or drop is armed, but a phase can still ARRIVE mid-shape. Then the
# phase wins: a formed school, a rush, ejecta, keepers and dispersing fish
# are not on the loop at all, so the procession simply empties while the
# told clock keeps running — and the trail and wake restore themselves at
# the release's end either way. On the panel that reads as the shape
# dissolving into the charge's school, which is the right answer: his
# authored moment is the bigger one.
WS_LOOP_S_FEW = 5.5         # seconds for one lap of the outline, few fish,
                            # AT x1 — the registered `word_shape_speed_x`
                            # below divides it while a shape stands
WS_LOOP_S_MANY = 7.0        # ... and many (a longer line, a slower flow)
# ROW W5.5's FIRST LEVER, and Orbits' own (W4.4): SPEED. His verdict after
# the W3 room deploy, which W4.4 answered for Orbits and this row answers
# here: *"Oribits is really good at showing shape, we need to get Fish to
# behave similarly."* The arithmetic is the revisit gap against the trail's
# own half-life — the thing that decides whether a procession reads as a
# LINE or as three fish in a row. At x1 three fish on the heart's 168-cell
# outline revisit a point every WS_LOOP_S_FEW / 3 = 1.83 s against a 0.6 s
# trail half-life, so each smear is down to 12% of itself before the next
# fish arrives; at x3 the gap is 0.61 s — ONE half-life, 49% — and the lap
# runs in 1.83 s, which is what `_word_shape_speed_x` buys. See that
# method's docstring for what it multiplies (the line's own march, the
# procession's pace, the dash cap and the phase ease, so the whole law
# scales together and the approach still lands on the word) and
# `scripts/check_fish_word_shape.py --only sweep` for the loop x turn x
# trail table that chose this number.
WS_SPEED_X = 3.0            # the registered param's own default
WS_TARGET_LEAD = 0.008      # the target sits this much of the loop AHEAD of
                            # a fish's own place, so it is always swimming
                            # toward something rather than sitting on it.
                            # ROW W5.5 HALVED IT (0.015 -> 0.008) WITH THE
                            # ARITHMETIC THAT SAYS WHY: a pursuit steer
                            # aimed `L` of arc ahead passes a corner of
                            # exterior angle theta at `(L / 2) sin(theta /
                            # 2)` — so at the old lead the heart's cleft
                            # (151 deg) was cut by 1.7 px = 0.9-1.5 cell
                            # pitches BY THE AIM ALONE, whatever the turn
                            # circle underneath it. That cut, not the
                            # circle, was the corner bar's binding term
                            # (measured: WS_TURN_X 0.25 -> 0.08 moved a
                            # star's worst corner 5.39 -> 5.45 pitches at
                            # x1, i.e. not at all). Halved it is 0.9 px =
                            # 0.4-0.8 pitches, under the bar.
WS_REACH = 0.008            # ... and NEVER further ahead than this, however
                            # far behind its station the fish is. THE ONE
                            # THING THAT KEEPS A FISH ON A CORNER: anchored
                            # to the time-marched station instead, a fish
                            # that had fallen a tenth of the loop behind
                            # aimed at a point right across the heart's
                            # cleft or a star's notch and swam the CHORD —
                            # measured 11 px (5.6 cell pitches) inside the
                            # outline, against a 2-pitch bar. Anchored a
                            # short arc ahead of the fish's OWN place, the
                            # chord is always a few px long and the fish
                            # follows the line round the corner; the lag is
                            # closed by WS_SPACING_GAIN's speed correction
                            # instead, which cannot pull it off the line.
# ROW W6.1 — AND THE AIM IS NEVER SHORTER THAN WHAT A FRAME COVERS.
# THE AIM ABOVE IS AN ARC, AND A FRAME'S TRAVEL IS A LENGTH; at 30 fps the
# second is the bigger one. Measured frame by frame on the diamond — whose
# own tangent never reverses, so every reversal read there is the effect's
# (0.00 per second of geometric floor against 6.0-6.3 measured): the target
# sits 0.2-1.1 px of arc ahead while the fish covers 1.5 px in one rendered
# frame, so at a corner the aim point jumps from one side of it to the other
# WITHIN one frame. The heading error then arrives as 90 degrees in a single
# step, the steer spends it all at once, and the next three frames bring the
# fish back: -9, -13, -7 degrees. That is the nose snapping at a corner —
# his "the fish seem to jitter out of the outline" and the row's own "no
# twitch at a star's point" — and it is the AIM's length, not the gain.
#
# So the aim arc is floored at this many of the fish's OWN frame steps,
# which makes the target's direction move CONTINUOUSLY at any frame rate.
# It is read per fish from its own speed, so a dashing fish aims further
# ahead than a gliding one, exactly as a pursuit should. AT 60 fps IT
# BARELY BINDS (one step is 0.7 px against the 0.96 px the shipped aim
# already is), which is why W5.5 never saw this.
#
# THE COST IS THE CORNER, and it is arithmetic: a steer aimed `L` of arc
# ahead passes a corner of exterior angle theta at `(L / 2) sin(theta / 2)`
# whatever it can turn (WS_TARGET_LEAD's own block). Swept against both
# bars together — section 10's own aim-step table — and this is where they
# cross.
WS_AIM_STEP_X = 1.5
WS_SPACE_EASE_S = 1.0       # the entries ease to even spacing over this
WS_ENTRY_MIN_GAP = 0.5      # no two entries closer than this x (1 / n) of
                            # the loop
WS_SEEK_W = 14.0            # the loop's steer weight — the lull keepers'
                            # own KEEP_SEEK_W, the same job
WS_TURN_GAIN_X = 24.0       # the heading gain is x (1 + m * this) under a
                            # full shape, still clipped to the turn circle
                            # below so it can never turn a fish tighter
                            # than it can go. The plan asked for DOUBLE and
                            # double was not enough: a proportional steer
                            # needs a heading error to command a rate at
                            # all, so at x2 the fish lagged the line's own
                            # turn and swung wide of it — measured worst
                            # distance on the word 4.5 cell pitches at x2
                            # against 2.2 at x3, with the mid-hold and the
                            # smoothness bars unchanged
                            # (scripts/check_fish_word_shape.py sections 3
                            # and 4). Reported, not quietly widened.
                            #
                            # ROW W5.5 TOOK IT 2.0 -> 12.0, and THIS — not
                            # the circle — is what made his corners
                            # corners. The same lag the W1.4 note describes
                            # gets WORSE the faster the line runs, and row
                            # W5.5 runs it three times faster: measured on
                            # the corner bar at x3 with the shaped circle
                            # at 0.10, a star's worst corner is 3.88 cell
                            # pitches at x2, 1.40 at x6, 0.99 at x12 and
                            # 1.27 at x24 (over-steer coming back), and the
                            # per-instant median distance 1.31 -> 0.10. A
                            # proportional steer's lag is a GAIN problem
                            # and the clamp is what makes a high gain safe:
                            # at x12 the heading settles in about two
                            # frames and EVERY frame of it is still bounded
                            # by the tightened circle below, so nothing
                            # here turns a fish faster than its own
                            # geometry allows — the structural guarantee is
                            # the same single `np.clip` it always was.
                            #
                            # ROW W6.1 TOOK IT 12.0 -> 24.0, and what the
                            # number MEANS changed with it: the step is now
                            # the exact first-order form
                            # (`1 - exp(-gain * dt)` of the error, the
                            # block in draw()), so this names a SETTLING
                            # TIME and can never command more than the
                            # error however large it is. Re-swept at HIS
                            # OWN 30 fps against the corner bar and the
                            # nose-wag bar together, 2 seeds x 6 rows, at
                            # the shipped aim floor:
                            #   gain x6 : corner 3.28 p, wag 6.29/s,
                            #             61.9% filled, white 40.2%
                            #   gain x12: corner 1.04 p, wag 6.00/s,
                            #             75.6% filled, white 33.1%
                            #   gain x24: corner 0.79 p, wag 6.14/s,
                            #             77.8% filled, white 33.8%
                            # x6 is pure lag and costs the band as well as
                            # the corner; x24 is the best corner and the
                            # best band, and the WAG IS FLAT ACROSS ALL OF
                            # THEM — which is the row's own finding that
                            # the wag is not the gain's to fix (the
                            # WS_AIM_STEP_X block is).
# ROW W6.1 — AND A ONE-POLE ON THE TURN COMMAND WAS BUILT AND IS NOT
# SHIPPED, which is this row's own version of W1.4's curvature feed-forward
# (that block above) and is recorded for the same reason: it is the textbook
# answer and it MEASURED WORSE. STAR's `_govern_rotation` smooths that
# effect's jerk with a unity-DC-gain one-pole on the per-frame advance, so
# the same filter on the shaped turn command — state `p_om`, the rate the
# previous frame really applied, in RENDERED frames — is the obvious fix
# for a pursuit that overshoots a corner. Swept at 30 fps over 0, 1, 1.5,
# 2.5 and 4 frames it barely touched the WAG (6.00 -> 4.86 at four frames)
# and destroyed everything the row is for: the worst corner 1.04 -> 10.73
# cell pitches, the band filled 75.6% -> 29.2%, white 33.1% -> 43.8%. A
# fish that cannot spend its turn WHEN the corner arrives does not round
# the corner at all. Do not re-add it without re-running section 12's own
# table.
WS_TURN_X = 0.10            # THE TURN ARC TIGHTENS, scaled by m: the circle
                            # a fish turns on is this fraction of its own
                            # under a full shape — HIS OWN NOTE, "They also
                            # may need to more tightly flow". (W1.4 called
                            # it "the only way the clarity bar is reachable
                            # at all"; row W5.5's own paragraph below
                            # measured that reading and corrected it.) Every
                            # shape in the library has corners far sharper
                            # than his `orbit_radius` of 0.14 (a 4.5 px
                            # circle): measured, the outline turns 249
                            # degrees (the heart's cleft), 154 (a star's
                            # notch) and 114 (the diamond's tip) inside one
                            # turn radius of arc, so a fish on its ordinary
                            # circle rounds those 5 cell pitches wide of the
                            # line and the whole shape reads as a blob. At
                            # 0.25 it is 1.1 px and the same corners cost
                            # 0.3-2.4. THE CLAMP IS STILL THE CLAMP — every
                            # steering term is bounded by it exactly as
                            # before, it is simply a tighter circle while a
                            # shape runs, and the mechanism is the lull
                            # keepers' own (PRE_DROP_TURN, `kst["turn"]`
                            # dividing omega_max). At m = 0 it IS the fish's
                            # own circle, to the bit.
                            #
                            # ROW W5.5 (2026-11-18) TOOK IT FROM 0.25 TO
                            # 0.10 — HIS OWN INSTRUCTION FOR THE ROW,
                            # verbatim: "you might need to override some
                            # min turn radii to match the effect,
                            # especially on the star." At 0.10 the circle
                            # is 0.45 px, a quarter to four tenths of a
                            # cell pitch, which is the spec's own "a turn
                            # circle under half a cell pitch", and
                            # `tests/test_fish_word_shape.py` pins exactly
                            # that sentence.
                            #
                            # AND IT IS NOT WHAT BOUND HIS CORNERS, which
                            # is the row's first finding and is MEASURED
                            # rather than argued: at x1, taking this from
                            # 0.25 to 0.08 moved a star's worst corner from
                            # 5.39 cell pitches to 5.45 — no movement at
                            # all (section 10's lap x turn table). What
                            # bound them was the AIM, in the two terms
                            # WS_TURN_GAIN_X and WS_TARGET_LEAD above now
                            # carry. The circle still has to be small
                            # enough not to bind, and at 0.10 it is: the
                            # minimal-arc depth R (1 / cos(theta / 2) - 1)
                            # at the sharpest corner of each shape comes to
                            # 1.52 cell pitches (the heart's cleft, 156
                            # degrees), 0.73 (a star's point, 139) and 0.20
                            # (the diamond's tip, 97) — and THAT IS A
                            # REFERENCE, NOT A BOUND, because a fish can
                            # come in either side of it: wider when its aim
                            # cuts the corner, and CLOSER when it
                            # overshoots into a cusp and comes back, which
                            # is why the heart's cleft measures 0.04
                            # pitches of real path against its 1.52-pitch
                            # arc. The bar itself is therefore the measured
                            # path (section 9 of
                            # `scripts/check_fish_word_shape.py`): every
                            # vertex of every shape within 1.0 cell pitch
                            # on EVERY seed, worst 0.49 on the star.
                            #
                            # THE CLAMP IS STILL THE CLAMP at 0.10 exactly
                            # as at 0.25 — a tighter circle while a shape
                            # runs, his own again by the release's end —
                            # and at 0.10 it is also what makes
                            # WS_TURN_GAIN_X's gain safe.
                            #
                            # ROW W6.1 RE-SWEPT IT AT HIS OWN 30 fps AND
                            # LEFT IT HERE. {0.10, 0.15, 0.25} x the gain,
                            # at the shipped aim floor: 0.15 measured
                            # 0.75 cell pitches of worst corner against
                            # 0.79 at 0.10 — inside the noise of two
                            # seeds — while 0.25 gives it back (1.01) and
                            # the band with it. So the row keeps 0.10 and
                            # keeps the spec sentence
                            # `tests/test_fish_word_shape.py` pins ("a turn
                            # circle under half a cell pitch"), which 0.15
                            # would have broken for nothing.
# ROW W6.1 — AND THE CLAMP HAS TO MEAN AN ARC AT HIS OWN FRAME RATE.
# `omega_max = speed / turn_radius_px`, tightened by WS_TURN_X above, is
# the right angular RATE for that circle; what the drawn frame gets is
# `omega_max * dt` of heading. At the shaped circle (0.45 px) and the x3
# pace that rate is 140-215 rad/s, so one 30 fps frame is 4.7 to 7.2
# RADIANS — more than a full turn. MEASURED, before this constant existed:
# a fish on the loop with the wall's glance saturating the clamp
# (urgency 1.00, omega 190-214 rad/s) corkscrewed a complete circle every
# frame and travelled 20.5 px OFF THE LIT PANEL, against 0.00 px on the
# same seed untold — while at 60 fps the same configuration measured 0.00
# and the defect was invisible. The turn-circle guarantee's own sentence
# ("an about-face is always an arc and never a flip") is simply FALSE once
# `omega_max * dt` passes pi.
#
# So the shaped clamp carries a per-RENDERED-FRAME ceiling as well, which
# is STAR's own precedent one effect over (`ROTATION_CAP_DEG_FRAME`, the
# spin smooth plan: a cap per rendered frame, whatever dt, because a
# stalled frame must not be allowed the angle two frames would have had).
# It is still ONE `np.clip` on omega in draw(); this only bounds the bound.
# IT CANNOT BIND AT m = 0, by arithmetic rather than by a gate: the
# ordinary clamp would need a fish at
# `WS_TURN_MAX_RAD_FRAME / dt * turn_radius_px` = 214 px/s at 30 fps, and
# the dash cap is 2.04x the procession's own pace.
WS_TURN_MAX_RAD_FRAME = np.pi / 2.0
WS_DASH_X = 2.5             # the approach may run this many x cruise
                            # (`dist / time_left`, capped — the swim burst's
                            # own 2.2x + lunge is the precedent for a fish
                            # moving this fast)
WS_DASH_SETTLE_S = 0.4      # ... eased to the procession's pace over the
                            # form's last stretch, so the word itself is
                            # never a velocity step
WS_MIN_LEFT_S = 0.05        # the time left is never read below this
# HOLDING STATION, in two parts, and the split is what keeps the fish ON
# the line. The lag between a fish and its own place on the loop has a
# COMMON-MODE part (the whole line is behind, because the places marched
# while the fish were still swimming in, and a fish's path round a corner
# is longer than the arc it is following) and a DIFFERENTIAL part (this
# fish is out of step with its neighbours). Correcting both with speed
# meant every fish sprinting to catch an absolute phase — his "no sudden
# velocity shifts" — and never catching it, since a fish and its place move
# at the same pace. So:
#   * the LINE'S OWN PHASE follows the fish (WS_PHASE_GAIN): the procession
#     is where the fish are, which is also what the water trace should be
#     drawing;
#   * each fish's SPEED fixes only its spacing against its neighbours
#     (WS_SPACING_GAIN), so the line self-spaces nose to tail.
WS_PHASE_GAIN = 1.5         # loop fractions a second the line's own phase
                            # eases toward the fish's own mean place, per
                            # fraction of common-mode lag
WS_PHASE_MAX = 0.25         # ... reading no more lag than this in one go
WS_SPACING_GAIN = 1.4       # a fish behind its SLOT swims this much faster
                            # per slot of differential lag. 1.4 against 0.8
                            # measured better on 11 of 12 distance columns
                            # (scripts/check_fish_word_shape.py section 4,
                            # 4 seeds x 3 shapes x few/many)
WS_SLOT_LAG_MAX = 2.0       # ... slots the correction reads up to
WS_PACE_MIN = 0.4           # ... and a fish AHEAD of its slot never slows
                            # below this much of the pace
WS_WALL_LOOK_CUT = 0.75     # the wall's look-ahead shrinks by m x this (its
                            # glance starts later) ...
WS_WALL_TURN_X = 1.0 / WS_TURN_X
                            # ... and its arc tightens toward this x — ROW
                            # W5.5 relaxed it THE SAME WAY the fish's own
                            # circle is relaxed (it was a flat 2.0, chosen
                            # when the shaped circle was 0.25), because the
                            # wall is the one authority that can still
                            # re-widen the arc at a corner near the pond's
                            # edge: its glance OVERRIDES the loop's steer
                            # while it runs, so an arc planned on the
                            # fish's own 4.5 px circle rounds a star's
                            # notch 3.9 px wide of the line however tight
                            # the shape's own circle is.
# ... and the wall's FLOOR is relaxed with it. `_glance_radius`'s
# `np.maximum(want, turn_radius_px)` becomes the SHAPED circle while a shape
# stands — `_ws_wall`'s third member, the same `1 - (1 - WS_TURN_X) * m`
# factor the clamp in draw() uses — and is the fish's own again by the
# release's end. STILL FLOORED: "tightened WITHIN the clamp" is unchanged,
# it is simply the same tighter clamp the rest of the steering is already
# under. The LANDING LINE's own corner rounding (`_landing`) and the
# probe's reach (`_wall_steer`'s `widest`) keep the fish's own radius
# either way: the first is how a long BODY rounds a panel corner (geometry,
# not steering authority — and a per-frame rho would thrash
# `_landing_field`'s cache), the second is only ever safer the longer it is.
# HIS "LOWER DECAY BRIEFLY": the body trail's half-life under a full shape,
# as (FEW, MANY) — a PAIR because the trade is only real with many fish.
# With FEW the water trace (P2 A) already carries the line, so a longer
# trail buys nothing and only adds light; with MANY there is no trace and
# the trail IS how the band between the fish stays lit.
#
# BOTH NUMBERS WERE RE-MEASURED ON A METRIC THAT MEANS LIGHT, and the first
# answer here was wrong because the metric was: counting a band cell "lit"
# at ANY value above zero saturates at ~100% on this effect, since the
# fish's own wake already washes the band untold. Read as the share of the
# band above 128/255 (scripts/check_fish_word_shape.py's `band_contrast`),
# the longer trail buys 13-24 points of real light with many fish for 3-5
# points of white — which is the Admiral's own ask, so it is taken — and
# nothing at all with few. The per-mode table is in
# `.claude/skills/fish-effect/SKILL.md`; white stays under this effect's
# own worst busy frame today either way, which is the standing constraint
# (the WAKE COLOUR block, his 2026-10-26 report).
#
# ROW W5.5 READS THIS PAIR AS A SMEAR LENGTH RATHER THAN A DURATION: the
# lap now runs `word_shape_speed_x` times faster, so the same half-life
# would lay a smear that many times longer, and `_trail_half_life` divides
# the BLENDED value by the multiplier (see there for why the blend and not
# the target). The smear therefore keeps exactly the length W1.4 measured.
# That division is also what pays for the clarity — measured at x3, the
# unscaled duration runs the white share to 40.8% against 33.0% scaled, for
# four points of band share nobody needs (the shipped pair already reads
# 86-100% of the band over 64/255 against bars of 60/70%).
#
# AND ROW W5.5 MEASURED THE PAIR'S OWN REASON AWAY, so its two ends are now
# one number. The pair existed because "the trade is only real with many
# fish": with FEW the water trace carried the line, with MANY the trail WAS
# how the band between the fish stayed lit. At x3 that is no longer true —
# MANY clears its 70% band bar by 16 to 30 points at the FEW end too (the
# revisit gap is 7.0 / (6 x 3) = 0.39 s) — while the longer end costs 4 to 5
# points of white on exactly the three rows where white is the open
# exceedance, which is his own standing concern (the WAKE COLOUR block, his
# 2026-10-26 report) and the row's instruction: speed first, the trail only
# as far as the bar needs. Kept as a TUPLE because the mode latch is still
# the thing that would re-open it. The per-lever table is in
# `.claude/skills/fish-effect/SKILL.md`'s ROW W5.5 section.
WS_TRAIL_HALF_LIFE_S = (0.6, 0.6)
# ROW W6.1 — AND NOW IT IS FLOORED AT THE REVISIT GAP, which is THE PORT
# FROM ORBITS and is the whole of his third room verdict's second half.
#
# HIS WORDS, 2026-11-18: *"The shape outline needs to reach at least a
# moment where it is either filled with fish or trail. ... Also, if we did
# a highlight of the shape in orbits, do it on fish."*
#
# THERE IS NO HIGHLIGHT IN ORBITS TO PORT. `fx/effects/orbits.py` carries
# exactly four WORD_SHAPE_* constants (FEW, MANY, TRAIL_S 1.8, SPEED_X 4.0)
# and no shape-time brightness, glow or line lift at all; W4.4's option B
# ("a shape-time brightness lift") was framed and NEVER BUILT — he settled
# option A, as built. What makes Orbits' outline read WHOLE is that its
# trail OUTLIVES THE REVISIT GAP at x4: WORD_SHAPE_TRAIL_S is a DURATION
# add-on, raised 0.9 -> 1.8 s for exactly that. So what is ported here is
# the PERSISTENCE, not a highlight.
#
# AND ROW W5.5 HAD DONE THE OPPOSITE. It read this pair, and
# WS_RIPPLE_LIFE_S, as smear LENGTHS — divided by the lap's own speed-up
# (`_trail_half_life`, `_wake_half_life`) — which at x3 leaves 0.20 s of
# trail against a revisit gap of 0.61 s (FEW heart) or 0.39 s (MANY): each
# smear is at 12% of itself by the time the next fish arrives, so the band
# reads over 64/255 nearly everywhere (93-100%) and is NEVER WHOLE at half
# of full. Measured before this row changed anything, at his own 30 fps:
# the most-filled frame of a hold had 44-88% of the band over 128/255
# against his "filled" and a band/off-band ratio of 7.7-26x.
# That division bought 5-8 points of white (40.8% -> 33.0%); his new word
# outranks it, and white stays REPORTED under his standing option A.
#
# So the half-life a shape asks for is a DURATION floored at the gap: a
# smear still at half of its own brightness when the next fish arrives.
# THE FLOOR IS RAMPED BY `m` LIKE EVERYTHING ELSE HERE — a floor applied
# flat would step the half-life from 0.165 s to 0.61 s on the first frame
# of the form, which is the one thing his standing note rules out, and
# Orbits' own W1.3 finding (a lingering trail's per-frame decay is
# hyperbolic in its half-life) is why that step would be visible.
WS_TRAIL_GAP_X = 1.0        # the floor, in revisit gaps. 1.0 = a smear at
                            # half brightness exactly when the next fish
                            # arrives.
# SWEPT {0, 0.7, 1.0, 1.5} against bar 4 and the white share — section 10's
# own gap table, worst of its six (mode, shape) rows at 30 fps:
#
#   gap           band>64   FILLED   band/off   white
#   0.00 (W5.5's)     61%      36%      12.1x   19.6%
#   0.70              90%      63%      11.4x   25.0%
#   1.00 (shipped)    94%      78%      10.5x   31.0%
#   1.50              98%      86%       8.6x   39.9%
#
# (the corner and the wag columns do not move at all down this axis, which
# is the cleanest evidence in the row that the trail and the steering are
# separate defects)
#
# The row's instruction was "the smallest that makes the outline whole",
# and NONE of them does: 95% of the band over half of full is not reached
# at any gap this effect can afford. So the choice is read off BOTH halves
# of his sentence — "filled with fish or trail" AND "it isn't distinct
# enough" — and 1.0 is the only value that improves both against what he
# saw (44-88% filled and 7.7x at the deploy he judged). 1.5 buys eight
# points of filling by giving the DISTINCTNESS back to 8.2x and spending
# nine more points of white, which is trading one half of his sentence for
# the other. Section 11 prints the 1.5 row beside the shipped one so his
# own eye can overrule this.
WS_TRAIL_GAIN = 1.6         # ... and his "boost the trail brightness",
                            # through the body layer's own hue-preserving
                            # clip so a brighter smear never goes white
WS_RIPPLE_LIFE_S = 3.0      # THE WATER TRACE (P2 A, few fish only):
                            # `ripple_life` under a full shape — a ~1.26 s
                            # wake half-life at x1, so the trace is still
                            # there at the end of the longest hold (2.0 s).
                            # ROW W5.5 reads this as a LENGTH too (the
                            # WS_TRAIL_HALF_LIFE_S block above): divided by
                            # the lap's own speed-up it is ~0.42 s at x3,
                            # which still covers the 0.61 s a point waits
                            # between two of three fish and costs five
                            # points less white than the unscaled 1.26 s.
# ROW W6.1 — THE FLAP GLIDES ON THE LINE, if the flap is what lights the
# water off it. His "the fish seem to jitter out of the outline": the drawn
# lateral throw is a wave down the spine (`_spine_wave`, `SPINE_THROW =
# SPINE_U ** 1.6`), zero at the NOSE and full at the TAIL, and the W1.4
# hand-over blends it toward the tail drive's own stroke — which at the x3
# pace is near FLAP_MAX. So every stroke throws the tail's light a flap
# amplitude off the band while the fish's middle is on it.
#
# Under a full shape the drawn amplitude eases toward the GLIDE size — the
# tail drive's own `TAIL_AMP_GLIDE`, "its body near straight" — by `m`, and
# his own stroke is back by the release's end. The scale is this constant,
# in glide sizes. `None` means LEAVE THE FLAP ALONE.
#
# AND IT IS NONE, measured, which is the answer the row owed either way.
# Section 10's own OFF-BAND table, worst of its six (mode, shape) rows at
# 30 fps: the flap IS part of the off-band light — easing it to one glide
# size lifts the band/off-band ratio 10.5x -> 14.6x, so the attribution was
# right — but it costs FOUR POINTS OF THE BAND HE ASKED FOR (78% -> 74%
# filled) and FOUR of white (31.0% -> 35.4%, W1.4's own recorded
# non-monotonicity: a dimmer single-hue layer stops winning `lighten`'s max
# against the whiter body sum under it). The band is 1 cell pitch wide and
# the tail's throw lands IN it as often as beside it, so narrowing the body
# takes light off the line as well as off the water. His own words are
# "either filled with fish or trail" first, so the row does not spend his
# band to buy the ratio. `check_fish_word_shape.py --only sweep`'s OFF-BAND
# table re-measures this and the trace refusal below side by side, which is
# how a later change overturns either.
WS_FLAP_X = None
# ROW W6.1 — AND THE ORDINARY WAKE OFF THE LINE. The row's bar 4 reads the
# band against the water AROUND it, and half of that water is this effect's
# ordinary wake: every fish lays a deposit at its own TAIL every frame
# (`_deposit_wake`, the `laying` block in draw()), and W1.4 left MANY's
# `ripple_life` "exactly as it is" under a shape. Measured at the whole
# moment with the off-band light attributed per layer (section 11's
# `layer_off_band`): FEW 15.2 body / 14.4 water, MANY 13.8 body / 7.7
# water. So it is BOTH, and this is the water's half — the deposit eased
# toward this multiple of his own by `m`, his value back by the release's
# end, and `ripple_amount` itself never written. The TRACE's own deposit is
# untouched: that one IS the line.
#
# MEASURED, section 10's OFF-BAND table, worst of six (mode, shape) rows at
# 30 fps: easing it OUT costs the band nothing at all (78% filled either
# way), lifts the band/off-band ratio 8.1x -> 10.5x and takes 2.8 points OFF
# the white share (33.8% -> 31.0%). It is the only lever in this row that
# improves every column at once, which is why it goes to zero rather than
# part way.
WS_WAKE_FADE = 0.0
# ROW W6.1 — AND THE TRACE IS NO LONGER FEW-ONLY. W1.4 scoped the water
# trace (P2 A) to `n <= word_shape_few` deliberately: "with many, the bodies
# and trails already light the outline and a longer-lived busy wake is where
# white comes from". Row W6.1's bar 4 measured that premise and it does not
# hold at HALF OF FULL — with six fish the most-filled frame of a hold reads
# 77.8-79.8% of the band over 128/255 against his "filled", the worst rows
# of all six. The trace is the only lever that adds light AT THE LINE rather
# than at a fish (it is deposited at the loop point each fish's own place
# has reached, not at its tail), so it is also the cheapest in off-band
# light and in white — which is exactly why the row reaches for it rather
# than for more trail. It is HIS OWN existing mechanism extended, not a new
# drawing: the same deposit, the same palette rule, the same envelope.
#
# AND IT IS NOT SHIPPED, because the measurement refused it. Section 10's
# OFF-BAND table, worst of six rows at 30 fps with the ordinary wake already
# eased out: extending the trace to MANY at its own amplitude moves the band
# filled NOT AT ALL (78% -> 78%) and costs FIVE points of white (31.0% ->
# 36.0%); at WS_TRACE_AMP 1.4 it buys four points of band (-> 82%) for eight
# of white (-> 39.2%). With six fish the revisit gap is already 0.39 s and the
# floored trail covers it, so there is no dark stretch for a trace to fill —
# W1.4's own scoping reason survives bar 4 after all, which is worth the
# record. `--only sweep`'s OFF-BAND table carries it (and the
# brighter-trace variant); section 11 and section 5 together are the
# absolute figures.
WS_TRACE_MANY = False
WS_TRACE_AMP = 0.9          # the loop trace's deposit, x the ordinary
                            # wake's own strength
WS_TRACE_SIZE_BODY = 0.5    # ... sized this many body lengths across
WS_TRACE_MAX_ARC = 0.08     # never more than this much of the loop in one
                            # frame (a guard: a huge dt cannot paint the
                            # whole outline at once)
WS_OUTLINE_SAMPLES = 720    # the bearing -> place table's resolution
WS_RELEASE_GRIP = 0.5       # the fish let go of the loop this far down the
                            # release ("half-way down", plan 3.4)
WS_PAUSE_AT = 0.02          # m past which the paused features are held


def word_shape_grip(t, form_s, hold_s, release_s, share=WS_RELEASE_GRIP):
    """THE LOOP'S OWN AUTHORITY, which is NOT the told envelope: 1 from the
    first frame of the form (a fish heads for its entry straight away — the
    S-curve paces its speed, never where it is going), 1 through the hold,
    then 1 -> 0 on a smoothstep over the first `share` of the release, and 0
    after. Zero at both ends of that ramp, so letting go of the loop is as
    smooth as taking it.

    A module function so the check script and the tests read the same law
    the effect does."""
    t = float(t)
    form_s = max(0.0, float(form_s or 0.0))
    hold_s = max(0.0, float(hold_s or 0.0))
    release_s = max(0.0, float(release_s or 0.0))
    if t < 0.0:
        return 0.0
    standing = form_s + hold_s
    if t <= standing:
        return 1.0
    span = release_s * max(min(float(share), 1.0), 0.0)
    if span <= 0.0:
        return 0.0
    u = min(max((t - standing) / span, 0.0), 1.0)
    return float(1.0 - u * u * (3.0 - 2.0 * u))


def word_shape_restart_t(fraction, form_s):
    """Where on the FORM's own smoothstep a shape already `fraction` formed
    sits, in seconds — the inverse of `word_shape_keys.envelope`'s rising
    ramp (`3u^2 - 2u^3`, inverted in closed form).

    This is what makes "a second word arriving mid-release restarts the form
    from the current fraction" true without a snap to zero: the new form
    starts at the clock time that already reads the fraction the old shape
    had reached, so the envelope is continuous across the edge."""
    form_s = max(0.0, float(form_s or 0.0))
    f = min(max(float(fraction), 0.0), 1.0)
    if form_s <= 0.0 or f <= 0.0:
        return 0.0
    if f >= 1.0:
        return form_s
    u = 0.5 - math.sin(math.asin(1.0 - 2.0 * f) / 3.0)
    return float(form_s * min(max(u, 0.0), 1.0))


def word_shape_release_t(fraction, form_s, hold_s, release_s):
    """Where on the RELEASE's own smoothstep a shape still `fraction`
    standing sits, in seconds — what a CLEARING write (told() back to None
    mid-shape) jumps the clock to, so the shape lets go from where it is
    instead of vanishing."""
    form_s = max(0.0, float(form_s or 0.0))
    hold_s = max(0.0, float(hold_s or 0.0))
    release_s = max(0.0, float(release_s or 0.0))
    f = min(max(float(fraction), 0.0), 1.0)
    base = form_s + hold_s
    if release_s <= 0.0:
        return base
    if f >= 1.0:
        return base
    if f <= 0.0:
        return base + release_s
    u = 0.5 - math.sin(math.asin(1.0 - 2.0 * (1.0 - f)) / 3.0)
    return float(base + release_s * min(max(u, 0.0), 1.0))


def word_shape_entries(bearings, table_ang, table_s, min_gap):
    """Each fish's entry place on the loop, in loop fractions.

    `bearings` are the fish's own bearings from the centre of view (radians,
    the shape's own angle convention); `table_ang`/`table_s` the monotonic
    bearing -> place map. Returns (entry place per fish, its rank round the
    loop). Every entry is at least `min_gap` of the loop from its
    neighbours, opened by order-preserving relaxation passes — so the fish
    never cross on the way in, which is the whole point of reading the
    bearing rather than handing out places by index."""
    th = np.asarray(bearings, dtype=np.float64)
    lo = float(table_ang[0])
    wrapped = lo + (th - lo) % (2.0 * np.pi)
    s = np.interp(wrapped, table_ang, table_s) % 1.0
    k = s.size
    order = np.argsort(s, kind="stable")
    rank = np.empty(k, dtype=np.float64)
    rank[order] = np.arange(k, dtype=np.float64)
    if k < 2 or min_gap <= 0.0:
        return s, rank
    gap = min(float(min_gap), 1.0 / k)
    # Exactly, not by relaxation. Sorted ascending, "every cyclic gap is at
    # least `gap`" is "`v_i = ring_i - i * gap` is NON-DECREASING, and
    # `v_last - v_first` is at most `1 - k * gap`". So: the nearest
    # non-decreasing sequence to v (pool adjacent violators — exact, one
    # pass), then, if the wrap is still short, compress the whole span into
    # the room there is. Both steps keep v non-decreasing, so the fish keep
    # their order round the loop, which is the entry rule's own point.
    ring = s[order]
    v = ring - np.arange(k, dtype=np.float64) * gap
    stack_v: list[float] = []
    stack_n: list[int] = []
    for value in v:
        total, count = float(value), 1
        while stack_v and stack_v[-1] > total / count + 1e-15:
            total += stack_v[-1] * stack_n[-1]
            count += stack_n[-1]
            stack_v.pop()
            stack_n.pop()
        stack_v.append(total / count)
        stack_n.append(count)
    v = np.repeat(np.asarray(stack_v), np.asarray(stack_n))
    span = float(v[-1] - v[0])
    room = 1.0 - k * gap
    if span > room > 0.0:
        v = v[0] + (v - v[0]) * (room / span)
    elif room <= 0.0:
        v = np.full(k, v[0])
    out = np.empty(k, dtype=np.float64)
    out[order] = (v + np.arange(k, dtype=np.float64) * gap) % 1.0
    return out, rank


def big_fish_hue_degrees(intensity):
    """His colour rule: 120 degrees at intensity 0.2 or below, 180 at 0.5
    or above, linear between."""
    (i0, d0), (i1, d1) = BIG_FISH_HUE_LO, BIG_FISH_HUE_HI
    f = (float(intensity) - i0) / (i1 - i0)
    return d0 + (d1 - d0) * min(max(f, 0.0), 1.0)


def big_fish_cross_s(intensity, slow_s, fast_s):
    """Seconds for the big fish to cross: `slow_s` at intensity 0, `fast_s`
    at 1, with the SPEED linear in intensity between them."""
    i = min(max(float(intensity), 0.0), 1.0)
    v = (1.0 - i) / max(float(slow_s), 1e-3) + i / max(float(fast_s), 1e-3)
    return 1.0 / max(v, 1e-6)


def rotate_hue(rgb, degrees):
    """Turn an RGB colour (0..255) round the colour wheel by `degrees`,
    keeping its saturation and value."""
    r, g, b = (min(max(float(c), 0.0), 255.0) / 255.0 for c in rgb[:3])
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    h = (h + float(degrees) / 360.0) % 1.0
    return np.array(colorsys.hsv_to_rgb(h, s, v), dtype=np.float32) * 255.0


def _channel_peak(layer):
    """Each pixel's brightest channel, (h, w, 1). Two elementwise maxima:
    numpy's `max(axis=-1)` over a 3-wide axis costs ~100x more."""
    return np.maximum(
        np.maximum(layer[..., 0], layer[..., 1]), layer[..., 2]
    )[..., None]


def _hue_clip(layer, cap=255.0):
    """Scale a pixel down AS A WHOLE wherever its brightest channel passes
    `cap`, keeping its hue and saturation (the scatter's own body clip,
    `_clip_body_layer`, is the same rule). A per-channel clip of an
    over-bright colour pushes it toward white."""
    if float(layer.max()) <= cap:
        return layer
    peak = _channel_peak(layer)
    return np.where(
        peak > cap,
        layer * (np.float32(cap) / np.maximum(peak, 1e-6)),
        layer,
    )


def rest_quiet(level, calm, full):
    """How quiet one volume reading is for THE POND REST: 0 at or above
    `calm`, 1 at or below `full`, a smoothstep between."""
    z = min(max((calm - level) / max(calm - full, 1e-6), 0.0), 1.0)
    return z * z * (3.0 - 2.0 * z)


def rest_step(state, volume, dt, calm, full):
    """One frame of THE POND REST's quiet detector: `state` is (slow
    average, fast average, rest level); returns the next one. The effect and
    scripts/check_fish_pond_rest.py's library check run this same step."""
    slow, fast, level = state
    slow += (volume - slow) * min(1.0, dt / REST_SLOW_S)
    fast += (volume - fast) * min(1.0, dt / REST_FAST_S)
    target = min(rest_quiet(slow, calm, full), rest_quiet(fast, calm, full))
    tau = REST_IN_S if target > level else REST_OUT_S
    level += (target - level) * min(1.0, dt / tau)
    return slow, fast, level


# Every per-fish SoA array, in one place so compaction and the particle
# handoff native snapshot can never drift out of sync with each other.
_SOA_NAMES = (
    "p_mode", "p_nocap", "p_disp", "p_slot", "p_slot_frac",
    "p_x", "p_y", "p_x0", "p_y0", "p_hd", "p_spd", "p_acc",
    "p_flap", "p_jog", "p_ro", "p_lun", "p_lun_t", "p_var",
    "p_enter", "p_erate", "p_leave", "p_lfade", "p_dl", "p_lk",
    "p_nf1", "p_nf2", "p_np1", "p_np2", "p_wf", "p_wp", "p_gf", "p_gp",
    "p_grad", "p_grad_from", "p_scatter", "p_bright",
    "p_trail_x", "p_trail_y", "p_trail_acc",
    "p_wsg", "p_wurg", "p_wcmd", "p_wauth", "p_sb", "p_sb_t", "p_wr",
    "p_wph", "p_peel",
    # the host frame (fx/effects/transition_program.py, the shoal-burst
    # plan): the rate its heading is turning (published on the hand-off so
    # a successor continues the turn), and which released object a fish
    # born by a matched birth came from
    "p_om", "p_pid",
    # the tail drive (the TAIL DRIVE block): the tail's size and stroke rate,
    # whether it is stroking, the flap phase that stroke began at, and the
    # beat envelope
    "p_tamp", "p_tf", "p_tst", "p_tph0", "p_tkick",
    # the pond rest (the POND REST block): a dart's clock (> 0 its push,
    # below 0 the turn through its glide), its heading (NaN = none), and
    # when that fish's next dart is due
    "p_dart", "p_dhd", "p_dnext",
    # WORD SHAPES (the block of that name): this fish's entry place on the
    # outline and its rank round the loop (NaN = not on the loop). A PLACE,
    # not an index, for `p_disp`'s own reason: _compact() reshuffles slots
    # whenever a fish retires, so anything keyed on an index silently moves
    # to the wrong fish.
    "p_ws_s", "p_ws_rank",
)


def _wrap_pi(a):
    """Wrap an angle (or array) into (-pi, pi]."""
    return (a + np.pi) % (2 * np.pi) - np.pi


def _real_cell_mask(effect):
    """(r_height, r_width) bool: True where a matrix cell lands on a real
    fixture, False where it lands on a gap device (dark) or past the end of
    the virtual. Read off the virtual's own segments with the render path's
    own gap rule, through the SAME flip/mirror/rotate Twod applies on the
    way out, so a cell here is the cell the effect draws. Anything this
    cannot read (no virtual, copy mapping, a malformed segment) is the
    whole rectangle — never a guess at a smaller shape."""
    h, w = int(effect.r_height), int(effect.r_width)
    full = np.ones((h, w), dtype=bool)
    virtual = getattr(effect, "_virtual", None)
    ledfx = getattr(effect, "_ledfx", None)
    try:
        if virtual is None or ledfx is None:
            return full
        if virtual._config.get("mapping") != "span":
            return full
        from fx.utils import is_gap_device

        devices = ledfx.devices
        runs = []
        any_gap = False
        for seg in virtual.segments:
            dev_id, start, end = seg[0], int(seg[1]), int(seg[2])
            dev = devices.get(dev_id)
            gap = is_gap_device(dev) or (
                dev is None and str(dev_id).startswith("gap-")
            )
            any_gap = any_gap or gap
            runs.append(np.full(max(end - start + 1, 0), not gap))
        if not any_gap or not runs:
            return full
        phys = np.concatenate(runs)
        group = int(getattr(virtual, "group_size", 1) or 1)
        if group > 1:
            k = int(np.ceil(phys.size / group))
            padded = np.zeros(k * group, dtype=bool)
            padded[: phys.size] = phys
            phys = padded.reshape(k, group).any(axis=1)
        idx = np.arange(h * w, dtype=np.int32).reshape(h, w)
        img = Image.fromarray(idx)
        if effect.flip2d:
            img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        if effect.mirror2d:
            img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if effect.rotate_t != 0:
            img = img.transpose(effect.rotate_t)
        order = np.asarray(img, dtype=np.int64).ravel()
        real = np.zeros(h * w, dtype=bool)
        count = min(order.size, phys.size)
        real[order[:count]] = phys[:count]
        mask = real.reshape(h, w)
        return mask if mask.any() else full
    except Exception:
        _LOGGER.debug("fish: wall shape unreadable, using the rectangle",
                      exc_info=True)
        return full


def _silhouette(real):
    """The lit silhouette of a real-cell mask: the row-span fill of the real
    cells intersected with the column-span fill, then each row closed. The
    crystal's real cells sit on a checkerboard lattice inside a hexagon,
    and its tip rows come in pairs with one-cell crenels between them; this
    is that hexagon's own outline, with the lattice's holes and crenels
    filled, because a fish is wider than either."""
    rows = np.zeros_like(real)
    cols = np.zeros_like(real)
    # the lattice alternates columns row by row, so a column's own span is
    # read across it and its neighbours
    wide = real.copy()
    wide[:, 1:] |= real[:, :-1]
    wide[:, :-1] |= real[:, 1:]
    for r in range(real.shape[0]):
        c = np.flatnonzero(real[r])
        if c.size:
            rows[r, c[0]: c[-1] + 1] = True
    for c in range(real.shape[1]):
        r = np.flatnonzero(wide[:, c])
        if r.size:
            cols[r[0]: r[-1] + 1, c] = True
    both = rows & cols
    out = np.zeros_like(real)
    for r in range(real.shape[0]):
        c = np.flatnonzero(both[r])
        if c.size:
            out[r, c[0]: c[-1] + 1] = True
    return out


_WALL_FIELDS = {}


def _wall_field(real):
    """Signed distance (px, positive inside) to the lit silhouette's edge,
    on the cell grid padded by WALL_FIELD_PAD, plus its gradient. Cached by
    the mask itself, so every fish on the same panel shares one. The edge
    sits half a cell beyond the outermost lit cell centres."""
    key = (real.shape, real.tobytes())
    hit = _WALL_FIELDS.get(key)
    if hit is not None:
        return hit
    pad = WALL_FIELD_PAD
    inside = np.zeros(
        (real.shape[0] + 2 * pad, real.shape[1] + 2 * pad), dtype=bool
    )
    inside[pad:-pad, pad:-pad] = _silhouette(real)
    nb = np.zeros_like(inside)          # any 4-neighbour of the other class
    nb_in = np.zeros_like(inside)
    for axis, step in ((0, 1), (0, -1), (1, 1), (1, -1)):
        moved = np.roll(inside, step, axis=axis)
        nb |= moved != inside
        nb_in |= moved
    in_edge = np.argwhere(inside & nb)
    out_edge = np.argwhere(~inside & nb_in)
    cells = np.argwhere(np.ones_like(inside))
    dist = np.full(cells.shape[0], np.inf, dtype=np.float32)
    for edge, want in ((out_edge, True), (in_edge, False)):
        if edge.size == 0:
            continue
        pick = inside.ravel() == want
        pts = cells[pick].astype(np.float32)
        best = np.full(pts.shape[0], np.inf, dtype=np.float32)
        for lo in range(0, edge.shape[0], 256):
            e = edge[lo: lo + 256].astype(np.float32)
            d = np.hypot(
                pts[:, None, 0] - e[None, :, 0], pts[:, None, 1] - e[None, :, 1]
            ).min(axis=1)
            best = np.minimum(best, d)
        dist[pick] = best
    dist = np.where(np.isfinite(dist), dist, float(max(inside.shape)))
    field = np.where(
        inside.ravel(), dist - 0.5, -(dist - 0.5)
    ).reshape(inside.shape).astype(np.float32)
    for _ in range(WALL_SMOOTH_PASSES):
        for axis in (0, 1):
            ext = np.concatenate(
                [np.take(field, [0], axis=axis), field,
                 np.take(field, [-1], axis=axis)], axis=axis,
            )
            a = np.take(ext, range(0, field.shape[axis]), axis=axis)
            b = np.take(ext, range(1, field.shape[axis] + 1), axis=axis)
            c = np.take(ext, range(2, field.shape[axis] + 2), axis=axis)
            field = (a + 2.0 * b + c) * 0.25
    gy, gx = np.gradient(field)
    gx = gx.astype(np.float32)
    gy = gy.astype(np.float32)
    out = (field, gx, gy, pad, np.stack([field, gx, gy]))
    if len(_WALL_FIELDS) > 16:
        _WALL_FIELDS.clear()
    _WALL_FIELDS[key] = out
    return out


def _sample_field(wall, x, y):
    """Bilinear (distance, unit inward normal) at SCREEN points. Past the
    padded grid the distance keeps falling with the distance to it and the
    normal points back at it, so a fish far off-panel is still steered in."""
    stack, pad = wall[4], wall[3]
    gh, gw = stack.shape[1], stack.shape[2]
    u = np.asarray(x, dtype=np.float32) + pad
    v = np.asarray(y, dtype=np.float32) + pad
    uc = np.clip(u, 0.0, gw - 1.001)
    vc = np.clip(v, 0.0, gh - 1.001)
    i0 = uc.astype(np.int32)
    j0 = vc.astype(np.int32)
    fu = uc - i0
    fv = vc - j0
    flat = stack.reshape(3, -1)
    k = j0 * gw + i0
    top = flat[:, k] * (1 - fu) + flat[:, k + 1] * fu
    bot = flat[:, k + gw] * (1 - fu) + flat[:, k + gw + 1] * fu
    d, nx, ny = top * (1 - fv) + bot * fv
    ox, oy = uc - u, vc - v
    off = np.hypot(ox, oy)
    far = off > 1e-6
    if far.any():
        d = np.where(far, d - off, d)
        nx = np.where(far, ox, nx)
        ny = np.where(far, oy, ny)
    norm = np.maximum(np.hypot(nx, ny), 1e-6)
    return d, nx / norm, ny / norm


_LANDING_FIELDS = {}


def _landing_field(wall, inset, round_px):
    """The line a glance lands the middle on, as a field like `_wall_field`'s:
    the lit silhouette pulled in by `inset` px, its corners rounded to
    `round_px` (the morphological opening of the inset shape by a disc) —
    a long fish cannot follow a sharp corner, and a corner it is steered
    into is where its nose would leave the panel. Cached by both numbers."""
    key = (id(wall), round(float(inset) * 4), round(float(round_px) * 4))
    hit = _LANDING_FIELDS.get(key)
    if hit is not None and hit[5] is wall:
        return hit
    field = wall[0]
    pad = wall[3]
    rho = max(float(round_px), 0.0)
    inner = field - inset
    core = inner >= rho
    if rho <= 0.0 or not core.any():
        out_field = inner
    else:
        # distance from every cell to the eroded core: the core's own
        # depth inside it, the nearest core cell's distance outside it
        cells = np.argwhere(~core).astype(np.float32)
        edge = np.argwhere(core & (
            ~np.roll(core, 1, 0) | ~np.roll(core, -1, 0)
            | ~np.roll(core, 1, 1) | ~np.roll(core, -1, 1)
        )).astype(np.float32)
        best = np.full(cells.shape[0], np.inf, dtype=np.float32)
        for lo in range(0, edge.shape[0], 256):
            e = edge[lo: lo + 256]
            d = np.hypot(cells[:, None, 0] - e[None, :, 0],
                         cells[:, None, 1] - e[None, :, 1]).min(axis=1)
            best = np.minimum(best, d)
        dist = np.zeros(core.shape, dtype=np.float32)
        dist[~core] = best
        out_field = np.where(core, inner, rho - dist).astype(np.float32)
    gy, gx = np.gradient(out_field)
    out = (out_field, gx.astype(np.float32), gy.astype(np.float32), pad,
           np.stack([out_field, gx, gy]).astype(np.float32), wall)
    if len(_LANDING_FIELDS) > 16:
        _LANDING_FIELDS.clear()
    _LANDING_FIELDS[key] = out
    return out


class Fish2d(Twod, GradientEffect):
    """Orbits' visual language with a fish's kinematics.

    Each particle is a thin oval swimming under its own heading and speed:
    it POINTS the way it is going, its spine flaps (harder under
    acceleration, subtler when slowing), and it leaves a wake: Orbits' own
    decaying accumulation buffer, which also EXPANDS every frame, so the
    smear opens out as it dims. Nothing is stamped as a shape — see the
    wake block at the top of this module, including the stated rule for
    what colour the wake takes against the fish's own. Turning is rate-limited by a real turn
    RADIUS, so a fish can never reverse on the spot — every about-face is an
    arc. Physics runs in Orbits' normalized space (same x_offset/y_offset/
    radius_scale projection) but headings and body geometry are SCREEN-space,
    so the oval is never sheared by the panel's aspect.

    Positions are WORLD coordinates and the panel is a WINDOW onto them
    (`camera_follow`, added 2026-08-28): the render subtracts a camera
    origin, and at rest — which is every moment outside a charge or a lull
    — that mapping is the identity, so the effect is exactly what it was
    before the window existed. See the camera-window block at the top of
    this module for what it replaces and why.

    The lull is HIS CLOCK (2026-08-28): every fish gone by a third of it,
    ripples only to two thirds, dark after that until the drop — and the
    drop is what brings the room back, with the rush that used to belong to
    the lull. See the LULL_* block and `_drop_step`.

    Mutual avoidance (`avoid_strength`, added 2026-08-28) is STEERING ONLY:
    it contributes one more term to the desired-heading vector sum below and
    is then bounded by the same turn-rate clamp as every other term, so the
    two fish laws hold structurally — no fish ever reverses on the spot, and
    every about-face stays a clear arc. It never writes a position.
    """

    NAME = "Fish"
    # THE DROP SHOCKWAVE (fx/effects/phase_grammar.py): born on the home
    # ring (on screen: the window's centre); its debris curves back to it
    DROP_SHOCK = True
    SHOCK_DEBRIS_FATE = "return"
    # NO BREATH-HOLD (2026-10-12, the Admiral: "I want orbits and fish to
    # specifically not go dark completely"): the lull's searcher swims
    # straight through to the drop — no short black before it. SpotFX does
    # not tell the Fish the breath either (fx.device_model.
    # BREATH_HOLD_EFFECTS); this makes a told one a no-op too.
    BREATH_HOLD = False
    CATEGORY = "Matrix"
    HIDDEN_KEYS = Twod.HIDDEN_KEYS + ["gradient_roll", "color_blend"]
    ADVANCED_KEYS = Twod.ADVANCED_KEYS + [
        "impulse_decay",
        "color_shift",
        "phase",
        "phase_progress",
        *lull_handoff.KEYS,
        lull_handoff.DROP_KEY,
        "big_fish",
        *phase_grammar.BREATH_KEYS,
        phase_grammar.SHOCK_ON_KEY,
        *pre_drop.KEYS,
        *word_shape_keys.KEYS,
    ]

    CONFIG_SCHEMA = vol.Schema(
        {
            # ── inherited from Orbits, same key + same range ─────────────
            vol.Optional(
                "gradient",
                description="Fish colors, sampled evenly across the gradient",
                default="linear-gradient(90deg, #ff0000 0.00%,#ff7800 14.00%,#ffc800 28.00%,#00ff00 42.00%,#00c78c 56.00%,#0000ff 70.00%,#800080 84.00%,#ff00b2 98.00%)",
            ): validate_gradient,
            vol.Optional(
                "particle_count",
                description="Number of fish kept alive on the matrix",
                default=6,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_PARTICLE_COUNT)),
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
                description="Field radius as a fraction of the panel edge",
                default=1.8,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=2.0)),
            vol.Optional(
                "horizon_scale",
                description="Home-anchor ring radius; 0 anchors every fish to the center",
                default=0.4,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=0.8)),
            vol.Optional(
                "tether_scatter",
                description="Home-anchor spacing bias: 0 = perfectly equidistant, 1 = fully random placement",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "enter_time",
                description="Seconds a new or adopted fish takes to fade in as it swims on",
                default=2.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=5.0)),
            vol.Optional(
                "orbit_radius",
                description="Turn radius: the tight circle a fish traces when it turns around",
                default=0.14,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.02, max=0.8)),
            vol.Optional(
                "blob_size",
                description="Fish half-width in pixels (length follows from Body Length)",
                default=1.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=6.0)),
            vol.Optional(
                "spin",
                description="Current swirl: a steady bias making every fish curve one way",
                default=0.15,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "base_speed",
                description="Swim speed: field radii crossed per second",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=2.0)),
            vol.Optional(
                "reverse",
                description="Reverse the current swirl direction",
                default=False,
            ): bool,
            vol.Optional(
                "jiggle",
                description="0 = every fish wanders alike, 1 = fully independent wander and reactivity",
                default=0.2,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "reactivity_scale",
                description="Master scale multiplying every audio reactivity below",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(
                "speed_jump",
                description="Max speed boost the music can add to a fish",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=3.0)),
            vol.Optional(
                "speed_jog",
                description="How hard spikes/beats knock fish off course",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=3.0)),
            vol.Optional(
                "brightness_audio",
                description="How much the music pumps fish brightness",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(
                "size_audio",
                description="How much the music inflates fish size",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(
                "trail_decay",
                description="How long the water holds the wake: 0 = crisp, 1 = long smear",
                # 2026-09-17, his word: trail duration down 25% from his live
                # 0.4 (half-life 0.02+0.4*0.5=0.22s). 0.29 -> half-life 0.165s,
                # exactly 25% shorter; 0.75*0.4=0.3 would only be ~23% at the
                # effect because of the 0.02s floor.
                default=0.29,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "gradient_spin",
                description="Roll fish colors along the gradient over time (rev/s)",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=-1.0, max=1.0)),
            vol.Optional(
                "color_shift",
                description="Rotate the fish->color assignment by this many slots",
                default=0,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=96)),
            vol.Optional(
                "frequency_range",
                description="Audio band driving the reactivity",
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
            # ── fish's own knobs (every one judged by eye — tunable) ──────
            vol.Optional(
                "body_aspect",
                description="Body length as a multiple of its width — higher is a thinner, longer fish",
                default=3.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=1.2, max=6.0)),
            vol.Optional(
                "flap_amount",
                description="How far the spine throws its tail",
                default=0.55,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.5)),
            vol.Optional(
                "flap_rate",
                description="Tail beats per second at cruise",
                default=2.2,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=6.0)),
            vol.Optional(
                "flap_accel",
                description="How much harder the tail waves under acceleration (and softer when slowing)",
                default=1.2,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=3.0)),
            vol.Optional(
                "min_drift_speed",
                description=(
                    "Minimum swim speed kept independent of the tail "
                    "stroke, as a fraction of the ordinary continuous "
                    "swim target — his escape hatch: raise this to 1 "
                    "with Stroke speed cap at 0 to get back the old "
                    "smooth, un-pulsed motion. Paired with Stroke speed "
                    "cap's own default so the shipped pair keeps the old "
                    "MEAN speed (0.85 + 0.4*0.375 = 1.0) rather than just "
                    "pulsing around a slower average"
                ),
                default=0.85,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "stroke_speed_cap",
                description=(
                    "Cap on the extra speed a single tail stroke can add "
                    "on top of the minimum drift speed; 0 = no pulse at "
                    "all. Paired with the default Minimum drift speed so "
                    "the shipped defaults keep the OLD MEAN SPEED"
                ),
                default=0.4,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            # 2026-10-26, the plan he approved: "tail-driven swimming with
            # beats as strong as today" (the TAIL DRIVE block at the top of
            # this module)
            vol.Optional(
                "tail_drive",
                description=(
                    "How much the tail itself drives the fish: 0 = speed "
                    "follows the music and the tail follows the speed (the "
                    "motion before 2026-10-26, exactly), 1 = the tail's "
                    "strokes push the fish and the water's drag slows it"
                ),
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "glide_drag",
                description=(
                    "Tail drive: the water's drag at cruise, per second. "
                    "Higher = a gliding fish slows sooner and the speed "
                    "follows the tail more tightly; cruise is held either "
                    "way"
                ),
                default=1.6,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.4, max=4.0)),
            vol.Optional(
                "glide_below",
                description=(
                    "Tail drive: below this effort (a share of cruise) a "
                    "fish strokes a short burst and then glides with its "
                    "body straight instead of beating steadily; 0 = never "
                    "glide"
                ),
                default=0.75,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.5)),
            # 2026-10-26, the plan he approved: "a quiet pond rest with
            # occasional darts" (the POND REST block at the top of this
            # module)
            vol.Optional(
                "quiet_rest",
                description=(
                    "Pond rest: how far the fish come to rest when the "
                    "music is almost or completely quiet (0 = never, the "
                    "motion before 2026-10-26 exactly; 1 = almost still, "
                    "with an occasional short dart)"
                ),
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "rest_calm_level",
                description=(
                    "Pond rest: the music level (volume, 1 + dB/100) below "
                    "which the fish start to calm"
                ),
                default=0.66,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "rest_full_level",
                description=(
                    "Pond rest: the music level at and below which they are "
                    "fully at rest"
                ),
                default=0.52,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "dart_every_s",
                description=(
                    "Pond rest: the average seconds between one resting "
                    "fish's darts (never sooner than 3 s)"
                ),
                default=9.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=3.5, max=120.0)),
            vol.Optional(
                "ripple_amount",
                description="Wake strength: how much smear a fish lays down",
                default=0.35,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "ripple_spread",
                description="How fast the wake opens outward as it fades",
                default=0.45,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=3.0)),
            vol.Optional(
                "ripple_life",
                description="Seconds the wake takes to fade",
                # 2026-09-17, his word: trail duration down 25% from his live
                # 0.9 -> 0.675.
                default=0.675,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=4.0)),
            vol.Optional(
                "ripple_width",
                description="Wake thickness: the size of each deposit, relative to the fish",
                # 2026-09-17, his word: trail size down 25% from his live
                # 1.3 -> 0.975.
                default=0.975,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=4.0)),
            # 2026-10-26, his word ("I approve option A for the wake"): the
            # wake in the fish's own colour, lightened onto the bodies. See
            # the WAKE COLOUR block at the top of this module.
            vol.Optional(
                "wake_hue",
                description=(
                    "Wake color on a gradient: own = the fish's own color, "
                    "neighbour = an eighth of the way along the gradient, "
                    "opposite = half way round it (the look before "
                    "2026-10-26)"
                ),
                default="own",
            ): vol.In(list(WAKE_HUE_OFFSETS)),
            vol.Optional(
                "wake_blend",
                description=(
                    "How the wake meets the fish: lighten = the brighter of "
                    "the two, under = the wake only where the fish is not, "
                    "add = the two summed (the look before 2026-10-26)"
                ),
                default="lighten",
            ): vol.In(list(WAKE_BLENDS)),
            vol.Optional(
                "avoid_strength",
                description="How hard they avoid each other; 0 = they swim straight through",
                default=0.45,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "roam_scale",
                description="Pond size as a fraction of the panel; fish turn back at its edge",
                default=0.95,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.3, max=1.4)),
            vol.Optional(
                "camera_follow",
                description="How far the view travels with the school during a charge or lull; 0 pins the window to the shoal",
                default=0.8,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "school_count",
                description="Fish that swim in for the charge's school (ignores the population cap)",
                default=18,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_SCHOOL)),
            vol.Optional(
                "school_variation",
                description="How much each fish in the school differs from the shared heading",
                default=0.15,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "turn_min_time",
                description="Minimum seconds between the school's beat-driven direction changes",
                default=0.4,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=2.0)),
            vol.Optional(
                "rush_count",
                description="Fish in the drop's rush (ignores the population cap)",
                default=20,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_RUSH)),
            vol.Optional(
                "rush_time",
                description="Seconds the drop's rush sweeps inward before it starts to swirl",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=3.0)),
            vol.Optional(
                "rush_chaos",
                description="How disorderly the drop's rush is: 0 = a clean ring, 1 = scattered",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "swim_burst",
                description=(
                    "Swim burst (driven by SpotFX's swim-burst flare): while "
                    "on, every fish dashes and strokes its fins much faster. "
                    "The flare's own hold is the burst's length"
                ),
                default=False,
            ): bool,
            vol.Optional(
                "wall_lookahead",
                description=(
                    "How a fish meets the wall: it swims right up to it and "
                    "curves alongside so its side, not its nose, touches. "
                    "That curve is never tighter than the distance it swims "
                    "in this many seconds, so a faster fish starts sooner "
                    "and sweeps wider. 0 = the old late turn at the pond "
                    "edge"
                ),
                default=0.35,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=3.0)),
            vol.Optional(
                "wall_turn_strength",
                description=(
                    "How tight the curve along the wall is: lower is a "
                    "lazier, wider sweep that starts further out; higher is "
                    "a tighter turn made closer to the wall, nose first"
                ),
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=3.0)),
            vol.Optional(
                "solo_burst_rate",
                description=(
                    "How many times a minute one fish, picked at random, "
                    "puts on a sudden burst of speed. 0 = never"
                ),
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=30.0)),
            vol.Optional(
                "solo_burst_speed",
                description=(
                    "A solo burst's top speed, as a multiple of that fish's "
                    "ordinary swimming speed"
                ),
                default=2.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=1.2, max=5.0)),
            vol.Optional(
                "solo_burst_time",
                description=(
                    "Seconds a solo burst holds its top speed before it "
                    "eases back"
                ),
                default=0.8,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=3.0)),
            # ── the lull's searching keeper, and the scaled drop ─────────
            vol.Optional(
                "search_speed",
                description=(
                    "Lull: how fast the fish left behind swims while it "
                    "searches, as a fraction of its ordinary cruise"
                ),
                default=0.45,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=1.0)),
            vol.Optional(
                "search_pause_s",
                description=(
                    "Lull: the longest the searching fish pauses at the end "
                    "of a leg, looking about, before it heads the other way "
                    "(a short lull pauses less)"
                ),
                default=1.2,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=4.0)),
            vol.Optional(
                "search_reach",
                description=(
                    "Lull: how far toward each side the searching fish "
                    "goes, as a fraction of the pond"
                ),
                default=0.7,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=1.0)),
            vol.Optional(
                "drop_scale_min",
                description=(
                    "Drop: how short and gentle the rush gets on the "
                    "quietest song, as a fraction of the full rush (a song "
                    "at the automatic ceiling gets the full rush)"
                ),
                default=lull_handoff.DEFAULT_DROP_SCALE_MIN,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=1.0)),
            # ── the BIG FISH flare (see the BIG FISH block at the top) ───
            vol.Optional(
                "big_fish_brightness",
                description=(
                    "Big fish flare: how bright the big background fish "
                    "is (0.6 = 60%)"
                ),
                default=0.6,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "big_fish_size",
                description=(
                    "Big fish flare: its body length, as a fraction of the "
                    "panel width"
                ),
                default=0.65,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=1.2)),
            vol.Optional(
                "big_fish_cross_slow_s",
                description=(
                    "Big fish flare: seconds to cross the panel at the "
                    "quietest intensity"
                ),
                default=7.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=30.0)),
            vol.Optional(
                "big_fish_cross_fast_s",
                description=(
                    "Big fish flare: seconds to cross the panel at full "
                    "intensity"
                ),
                default=2.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=30.0)),
            vol.Optional(
                "big_fish_ripple",
                description=(
                    "Big fish flare: how bright its wake is (1 = the "
                    "ordinary fish's own wake rule at its size and speed, "
                    "which a big slow fish leaves dim)"
                ),
                default=BIG_FISH_RIPPLE_DEFAULT,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=4.0)),
            vol.Optional(
                "big_fish_ripple_size",
                description=(
                    "Big fish flare: its wake's width, against the ordinary "
                    "wake rule scaled to its body (1 = in proportion)"
                ),
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=2.0)),
            vol.Optional(
                "big_fish_avoid",
                description=(
                    "Big fish flare: how hard the other fish steer out of "
                    "its way (0 = they swim straight through it)"
                ),
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(
                "big_fish_avoid_margin",
                description=(
                    "Big fish flare: the gap (px) the other fish keep "
                    "between their bodies and its body"
                ),
                default=2.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=8.0)),
            vol.Optional(
                "big_fish",
                description=(
                    "Big fish flare poke: the fire's intensity (written by "
                    "SpotFX, self-resets)"
                ),
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            # ── SpotFX-driven choreography ───────────────────────────────
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
            # the lull hand-off hook (fx/effects/lull_handoff.py): ride ONLY
            # the lull/drop arm writes, like the phase keys above
            **lull_handoff.schema_fields(),
            **lull_handoff.drop_schema_fields(),
            # THE PHASE GRAMMAR (fx/effects/phase_grammar.py): the drop's
            # Shockwave settings (registered) and the breath-hold keys
            # (ride ONLY the lull arm write)
            **phase_grammar.shock_schema_fields(),
            **phase_grammar.shock_on_schema_fields(),
            **phase_grammar.breath_schema_fields(),
            # THE PRE-DROP's told keys (ride only the lull arm; zeros on a
            # lull that plays none) — fx/effects/pre_drop.py
            **pre_drop.schema_fields(),
            # WORD SHAPES (the block of that name): the shape's own two
            # REGISTERED settings, plus the six told keys, which ride ONLY
            # the `word_shape` kind's own write — fx/effects/
            # word_shape_keys.py's rule 1.
            vol.Optional(
                "word_shape_size",
                description=(
                    "Word shape: the shape's half-height as a fraction of "
                    "the panel's, so the fish's loop is this big"
                ),
                default=0.62,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=1.0)),
            vol.Optional(
                "word_shape_few",
                description=(
                    "Word shape: this many fish or fewer is 'few' — the "
                    "water keeps a trace of the loop behind them so the "
                    "whole outline shows"
                ),
                default=3,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_PARTICLE_COUNT)),
            vol.Optional(
                "word_shape_speed_x",
                description=(
                    "Word shape: how much faster the fish run the outline "
                    "while a shape stands, so each one's smear is still "
                    "bright when the next arrives"
                ),
                default=WS_SPEED_X,
            ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=6.0)),
            **word_shape_keys.schema_fields(),
        }
    )

    def __init__(self, ledfx, config):
        super().__init__(ledfx, config)
        # SoA + accumulators live here (NOT do_once) so they survive config
        # patches — do_once re-runs on every config change.
        # 0 swim 1 enter 2 ejecta (the drop's explosion only) 3 rush
        # 4 DISPERSING — see the dispersal block at the top of the module
        # 5 KEEPER — the lull's searching fish (the 2026-10-08 LULL block)
        self.p_mode = np.zeros(CAP, dtype=np.int8)
        self.p_nocap = np.zeros(CAP, dtype=np.int8)  # spawned past the cap
        # the lull's dispersal RANK (NaN = not scheduled). A rank, not an
        # index: _compact() reshuffles slots whenever a fish retires, so a
        # queue of indices silently disperses the wrong fish (or nobody).
        self.p_disp = np.full(CAP, np.nan, dtype=np.float32)
        self.p_slot = np.zeros(CAP, dtype=np.int16)
        self.p_slot_frac = np.zeros(CAP, dtype=np.float32)
        self.p_x = np.zeros(CAP, dtype=np.float32)
        self.p_y = np.zeros(CAP, dtype=np.float32)
        self.p_x0 = np.zeros(CAP, dtype=np.float32)  # last drawn position
        self.p_y0 = np.zeros(CAP, dtype=np.float32)
        self.p_hd = np.zeros(CAP, dtype=np.float32)  # SCREEN-space heading
        self.p_spd = np.zeros(CAP, dtype=np.float32)  # px/s
        self.p_acc = np.zeros(CAP, dtype=np.float32)  # smoothed px/s^2
        self.p_flap = np.zeros(CAP, dtype=np.float32)
        self.p_jog = np.zeros(CAP, dtype=np.float32)   # turn kick, rad/s
        self.p_ro = np.zeros(CAP, dtype=np.float32)    # speed kick, fraction
        self.p_lun = np.zeros(CAP, dtype=np.float32)   # lunge boost, fraction
        self.p_lun_t = np.zeros(CAP, dtype=np.float32)  # ... hold left, s
        self.p_var = np.zeros(CAP, dtype=np.float32)   # school variation, -1..1
        self.p_enter = np.zeros(CAP, dtype=np.float32)
        self.p_erate = np.ones(CAP, dtype=np.float32)
        self.p_leave = np.zeros(CAP, dtype=np.float32)
        self.p_lfade = np.full(CAP, DROP_SETTLE_S, dtype=np.float32)
        # dispersal: the effect-clock time a dispersing fish must be off the
        # panel by, and the time it starts heading OUT (a lull fish swirls
        # until then). inf = no deadline / not leaking yet.
        self.p_dl = np.full(CAP, np.inf, dtype=np.float64)
        self.p_lk = np.full(CAP, np.inf, dtype=np.float64)
        self.p_nf1 = np.zeros(CAP, dtype=np.float32)
        self.p_nf2 = np.zeros(CAP, dtype=np.float32)
        self.p_np1 = np.zeros(CAP, dtype=np.float32)
        self.p_np2 = np.zeros(CAP, dtype=np.float32)
        self.p_wf = np.zeros(CAP, dtype=np.float32)
        self.p_wp = np.zeros(CAP, dtype=np.float32)
        self.p_gf = np.zeros(CAP, dtype=np.float32)
        self.p_gp = np.zeros(CAP, dtype=np.float32)
        self.p_grad = np.zeros(CAP, dtype=np.float32)
        self.p_grad_from = np.full(CAP, np.nan, dtype=np.float32)
        self.p_scatter = np.zeros(CAP, dtype=np.float32)
        self.p_bright = np.zeros(CAP, dtype=np.float32)
        # body trail (his ask): a recorded path of the tracked point, WORLD
        # units, newest sample at column 0. NaN in column 0 flags "needs
        # backfill" — see the seeding pass near the top of draw().
        self.p_trail_x = np.full((CAP, BODY_TRAIL_LEN), np.nan, dtype=np.float32)
        self.p_trail_y = np.full((CAP, BODY_TRAIL_LEN), np.nan, dtype=np.float32)
        self.p_trail_acc = np.zeros(CAP, dtype=np.float32)
        # the wall: which way this fish is curving along it (+1/-1), or 0
        # when it is not gliding onto one, and the arc it chose (px) — see
        # the WALL block
        self.p_wsg = np.zeros(CAP, dtype=np.float32)
        self.p_wr = np.zeros(CAP, dtype=np.float32)
        # ... and, once alongside, the heading it was alongside at (NaN
        # while still on its way in)
        self.p_wph = np.full(CAP, np.nan, dtype=np.float32)
        self.p_wurg = np.zeros(CAP, dtype=np.float32)  # ... and how hard
        # ... and the turn and authority it is actually applying, eased
        # (WALL_RISE_S / WALL_FALL_S) so a turn eases out as it eased in
        self.p_wcmd = np.zeros(CAP, dtype=np.float32)
        self.p_wauth = np.zeros(CAP, dtype=np.float32)
        # a solo burst: its envelope (0..1) and the seconds it still holds
        # top speed — see the SOLO BURST block
        self.p_sb = np.zeros(CAP, dtype=np.float32)
        self.p_sb_t = np.zeros(CAP, dtype=np.float32)
        # THE PEEL: the inherited heading rate, rad/s (NaN = none)
        self.p_peel = np.full(CAP, np.nan, dtype=np.float32)
        self._peel_age = None
        # the rate each fish's heading is turning, rad/s — computed every
        # frame and, since the shoal-burst plan, PUBLISHED on the hand-off
        # so a successor (and a program's cloud) continues the turn
        self.p_om = np.zeros(CAP, dtype=np.float32)
        # THE HOST FRAME (the shoal-burst plan §5.2): the id a program's
        # cloud follows a fish born by a matched birth by
        self.p_pid = np.full(CAP, -1, dtype=np.int64)
        # THE TAIL DRIVE: tail size (1 = its cruise size), stroke rate (Hz,
        # 0 = not yet set), stroking (1) or gliding (0), the flap phase the
        # current stroke began at, and the beat envelope
        self.p_tamp = np.ones(CAP, dtype=np.float32)
        self.p_tf = np.zeros(CAP, dtype=np.float32)
        self.p_tst = np.ones(CAP, dtype=np.float32)
        self.p_tph0 = np.zeros(CAP, dtype=np.float32)
        self.p_tkick = np.zeros(CAP, dtype=np.float32)
        # THE POND REST: the quiet detector's state (slow, fast, level), the
        # level in use this frame, the last volume heard and when, the darts
        # (clock, heading, next due), their own generator, and this frame's
        # steering and pushing masks
        self._rest = None
        self._rest_level = 0.0
        self._rest_vol = None
        self._rest_heard = None
        self.p_dart = np.zeros(CAP, dtype=np.float32)
        self.p_dhd = np.full(CAP, np.nan, dtype=np.float32)
        self.p_dnext = np.zeros(CAP, dtype=np.float32)
        # WORD SHAPES (the block of that name): this fish's entry place on
        # the outline and its rank round the loop, NaN while it has none
        self.p_ws_s = np.full(CAP, np.nan, dtype=np.float64)
        self.p_ws_rank = np.full(CAP, np.nan, dtype=np.float64)
        self._dart_rng = None
        self._darting = None
        self._rest_free = None
        self._prog_birth_snap = None
        self._prog_birth_pids = None
        self._prog_birth_token = None
        self._next_pid = 0
        self._count_hold = None
        self._soa = tuple(getattr(self, name) for name in _SOA_NAMES)
        self.n = 0

        # THE WAKE: one persistent accumulation buffer, allocated with the
        # body trail in do_once (it is panel-shaped, and the panel is not
        # known here yet).
        self.wake = None
        self._wake_ox = 0.0     # sub-pixel world-anchoring remainder
        self._wake_oy = 0.0

        self._booted = False
        self._handoff_pending = True
        self._size_from = None
        self._size_age = None
        self._collapse = None
        self._erupt_hold = None
        self._pacman_hold = None
        self.t = 0.0
        self.roll_total = 0.0
        self.impulse = 0.0
        self.slow = 0.0
        self._beat_pending = False
        self._spike_cool = 0.0
        self._rng = np.random.default_rng()
        self.trail = None
        # charge/lull state that must survive a config patch
        self._school_hd = 0.0
        self._school_on = False
        self._rush_swirl = 0.0   # the drop's swirl, 0..1
        self._burst = 0.0        # the swim burst envelope, 0..1
        self._burst_tail = 0.0   # s of fast speed-ease left after a burst
        self._scatter = None     # outgoing-crossfade latch (see draw)
        self._keep = None        # the lull keepers' targets (_keep_targets)
        # THE PRE-DROP: its clock (None on every frame of a lull not told
        # one) and the dart's own state (PRE_DROP_* above)
        self._pd_clk = None
        self._pd_dart = None
        # WORD SHAPES (the block of that name): the shape running now (None
        # on every untold frame), the edge a write left for draw() to take,
        # the bearing -> place table for the shape in hand, the loop's own
        # drawn length, and the wall's (look-ahead, arc) multipliers while
        # one runs
        self._ws = None
        self._ws_pending = None
        self._ws_table = None
        self._ws_loop = None
        self._ws_wall = None
        self._ws_gain_clip = False
        self._wall = None        # the lit silhouette's distance field
        self._wall_key = None    # ... and what it was read from
        self._solo_due = 0.0     # solo bursts owed but not yet placed
        # the big fish (see the BIG FISH block): the ones crossing now,
        # and counters the tests and check script read
        self._big = []
        self._big_trail = None   # the big fish's own smear (trail_decay)
        self.big_fish_spawned = 0
        self.big_fish_dropped = 0
        self.big_fish_last = None
        self.solo_bursts = 0     # solo bursts started, ever (a count)
        self._school_turn_t = 0.0
        # the water's own current, world px/s: whatever fraction of the
        # school's travel the clamp still removes from the fish is expressed
        # here instead, so the wake and the shoal never disagree about which
        # way the water is going.
        self._flow_px = 0.0
        self._flow_py = 0.0
        # the window. World px; screen = world - cam. Zero is the identity.
        self.cam_px = 0.0
        self.cam_py = 0.0
        self.cam_vx = 0.0
        self.cam_vy = 0.0
        self._cam_px_prev = 0.0
        self._cam_py_prev = 0.0

        span = np.arange(-SPLAT_KERNEL_R, SPLAT_KERNEL_R + 1)
        kdx, kdy = np.meshgrid(span, span)
        kdist = np.sqrt(kdx**2 + kdy**2).ravel()
        self.k_dx = kdx.ravel().astype(np.int32)
        self.k_dy = kdy.ravel().astype(np.int32)
        self.k_dist = kdist.astype(np.float32)
        order = np.argsort(self.k_dist)
        self.k_dx = self.k_dx[order]
        self.k_dy = self.k_dy[order]
        self.k_dist = self.k_dist[order]

    # ── config ──────────────────────────────────────────────────────────
    def config_updated(self, config):
        super().config_updated(config)
        self.particle_count = self._config["particle_count"]
        self.x_offset = self._config["x_offset"]
        self.y_offset = self._config["y_offset"]
        self.radius_scale = self._config["radius_scale"]
        self.horizon_scale = self._config["horizon_scale"]
        self.tether_scatter = self._config["tether_scatter"]
        self.enter_time = self._config["enter_time"]
        self.orbit_radius = self._config["orbit_radius"]
        self.blob_size = self._config["blob_size"]
        self.spin = self._config["spin"]
        self.base_speed = self._config["base_speed"]
        self.reverse = self._config["reverse"]
        self.jiggle = self._config["jiggle"]
        self.reactivity_scale = self._config["reactivity_scale"]
        self.speed_jump = self._config["speed_jump"]
        self.speed_jog = self._config["speed_jog"]
        self.brightness_audio = self._config["brightness_audio"]
        self.size_audio = self._config["size_audio"]
        self.trail_decay = self._config["trail_decay"]
        self.gradient_spin = self._config["gradient_spin"]
        self.color_shift = self._config["color_shift"]
        self.body_aspect = self._config["body_aspect"]
        self.flap_amount = self._config["flap_amount"]
        self.flap_rate = self._config["flap_rate"]
        self.flap_accel = self._config["flap_accel"]
        self.min_drift_speed = self._config["min_drift_speed"]
        self.stroke_speed_cap = self._config["stroke_speed_cap"]
        self.tail_drive = self._config["tail_drive"]
        self.glide_drag = self._config["glide_drag"]
        self.glide_below = self._config["glide_below"]
        self.quiet_rest = self._config["quiet_rest"]
        self.rest_calm_level = self._config["rest_calm_level"]
        self.rest_full_level = self._config["rest_full_level"]
        self.dart_every_s = self._config["dart_every_s"]
        if self.quiet_rest <= 0.0:
            # switched off: forget the level and any dart in flight, so
            # nothing reads a stale one (the arrays exist once __init__ has)
            self._rest = None
            self._rest_level = 0.0
            self._darting = self._rest_free = None
            if hasattr(self, "p_dart"):
                self.p_dart[:] = 0.0
                self.p_dhd[:] = np.nan
                self.p_dnext[:] = 0.0
        self.ripple_amount = self._config["ripple_amount"]
        self.ripple_spread = self._config["ripple_spread"]
        self.ripple_life = self._config["ripple_life"]
        self.ripple_width = self._config["ripple_width"]
        self.wake_hue = self._config["wake_hue"]
        self.wake_blend = self._config["wake_blend"]
        self.avoid_strength = self._config["avoid_strength"]
        self.roam_scale = self._config["roam_scale"]
        self.camera_follow = self._config["camera_follow"]
        self.school_count = self._config["school_count"]
        self.school_variation = self._config["school_variation"]
        self.turn_min_time = self._config["turn_min_time"]
        self.rush_count = self._config["rush_count"]
        self.rush_time = self._config["rush_time"]
        self.rush_chaos = self._config["rush_chaos"]
        self.swim_burst = bool(self._config.get("swim_burst", False))
        self.wall_lookahead = self._config["wall_lookahead"]
        self.wall_turn_strength = self._config["wall_turn_strength"]
        self.solo_burst_rate = self._config["solo_burst_rate"]
        self.solo_burst_speed = self._config["solo_burst_speed"]
        self.solo_burst_time = self._config["solo_burst_time"]
        self.search_speed = self._config["search_speed"]
        self.search_pause_s = self._config["search_pause_s"]
        self.search_reach = self._config["search_reach"]
        self.drop_scale_min = self._config["drop_scale_min"]
        self.big_fish_brightness = self._config["big_fish_brightness"]
        self.big_fish_size = self._config["big_fish_size"]
        self.big_fish_cross_slow_s = self._config["big_fish_cross_slow_s"]
        self.big_fish_cross_fast_s = self._config["big_fish_cross_fast_s"]
        self.big_fish_ripple = self._config["big_fish_ripple"]
        self.big_fish_ripple_size = self._config["big_fish_ripple_size"]
        self.big_fish_avoid = self._config["big_fish_avoid"]
        self.big_fish_avoid_margin = self._config["big_fish_avoid_margin"]
        self.word_shape_size = self._config["word_shape_size"]
        self.word_shape_few = self._config["word_shape_few"]
        self.word_shape_speed_x = self._config["word_shape_speed_x"]
        self._word_shape_told()
        # the big fish poke: edge-detected like fireworks' burst_rockets (a
        # write that changes the value arms; draw consumes it and self-
        # resets the key to 0 so an identical later write edges again)
        new_big = float(self._config.get("big_fish", 0.0) or 0.0)
        if not hasattr(self, "_big_seen"):
            # creation baseline: a stale persisted poke never swims
            self._big_seen = new_big
            self._big_pending = []
        elif new_big != self._big_seen:
            self._big_seen = new_big
            if new_big > 0.0:
                self._big_pending.append(new_big)

        self.power_func = self.POWER_FUNCS_MAPPING[
            self._config["frequency_range"]
        ]
        decay = self._config["impulse_decay"]
        self.impulse_filter = self.create_filter(
            alpha_decay=decay, alpha_rise=0.99
        )
        self.slow_filter = self.create_filter(
            alpha_decay=0.08, alpha_rise=0.08
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
            self._drop_state = None
            self._lull_state = None
            self._charge_n0 = 1
            self._speed_scale = 1.0
            self._phase_done_t = None
        else:
            self._phase_pending = (
                new_phase if new_phase != self._phase else None
            )

    def audio_data_updated(self, data):
        power = getattr(data, self.power_func)()
        impulse = self.impulse_filter.update(power)
        self.impulse = float(impulse) if np.isfinite(impulse) else 0.0
        slow = self.slow_filter.update(power)
        self.slow = float(slow) if np.isfinite(slow) else 0.0
        if data.bpm_beat_now():
            self._beat_pending = True
        if self.quiet_rest > 0.0:
            # THE POND REST hears the absolute level, and when it last did
            # (clipped: a fresh analysis filter starts at -90 dB)
            try:
                level = float(data.volume())
            except Exception:
                return
            if np.isfinite(level):
                self._rest_vol = min(max(level, 0.0), 1.0)
                self._rest_heard = self.t

    def do_once(self):
        super().do_once()
        self.cx = (self.r_width - 1) * self.x_offset
        self.cy = (self.r_height - 1) * self.y_offset
        # Positions live in Orbits' normalized space; this projection
        # stretches it into a panel-filling ellipse.
        self.sx = self.radius_scale * (self.r_width - 1) / 2.0
        self.sy = self.radius_scale * (self.r_height - 1) / 2.0
        # ... but body geometry and speed are SCREEN-space, isotropic, so a
        # fish is the same shape and the same speed whichever way it points.
        self.s_min = max(
            self.radius_scale
            * min((self.r_width - 1) / 2.0, (self.r_height - 1) / 2.0),
            1e-3,
        )
        if self.trail is None or self.trail.shape[:2] != (
            self.r_height,
            self.r_width,
        ):
            self.trail = np.zeros(
                (self.r_height, self.r_width, 3), dtype=np.float32
            )
        if self.wake is None or self.wake.shape[:2] != (
            self.r_height,
            self.r_width,
        ):
            self.wake = np.zeros(
                (self.r_height, self.r_width, 3), dtype=np.float32
            )
            self._wake_ox = self._wake_oy = 0.0
        # the wall: re-read only when what it is read from changes, since
        # do_once also runs on every config patch (a glide is one a frame)
        virtual = getattr(self, "_virtual", None)
        segments = getattr(virtual, "segments", None) if virtual else None
        key = (
            id(segments), len(segments or ()), self.r_width, self.r_height,
            getattr(self, "rotate_t", 0), getattr(self, "flip2d", False),
            getattr(self, "mirror2d", False),
            getattr(virtual, "group_size", 1) if virtual else 1,
        )
        if self._wall is None or key != self._wall_key:
            self._wall = _wall_field(_real_cell_mask(self))
            self._wall_key = key

    # ── derived geometry ────────────────────────────────────────────────
    @property
    def turn_radius_px(self):
        return max(self.orbit_radius * self.s_min, 0.5)

    @property
    def cruise_px(self):
        """Cruise speed in px/s: `base_speed` crosses the field's own radius
        about CRUISE_K times a second. See CRUISE_K for why this is NOT
        Orbits' revolutions-per-second reading."""
        return max(self.base_speed * self.s_min * CRUISE_K, 0.1)

    @property
    def roam_bound(self):
        """Pond radius in NORMALIZED units — it bounds the fish's MIDDLE.
        roam_scale=1 is the panel's own inscribed ellipse, which on the
        crystal hex pokes past the slanted edges by a pixel or two (the
        rectangle's corners are pure gap — see
        .claude/skills/crystal-hex-grid/SKILL.md); the BODY is kept inside
        the real lit shape by the wall instead (see the WALL block)."""
        return max(self.roam_scale / max(self.radius_scale, 1e-6), 1e-3)

    @property
    def cam_nx(self):
        """The window's centre in NORMALIZED world units — the space every
        fish position, the pond and the home ring live in. Zero when the
        window is at rest, which is what makes each of those reduce to its
        pre-camera form exactly."""
        return self.cam_px / max(getattr(self, "sx", 1.0), 1e-6)

    @property
    def cam_ny(self):
        return self.cam_py / max(getattr(self, "sy", 1.0), 1e-6)

    def _half_width_px(self, blob_size=None):
        """Rendered half-WIDTH. `blob_size` keeps meaning "how big is this
        creature" rather than "how wide": the width is divided by
        sqrt(body_aspect) so a fish covers about the same area as the Orbits
        blob of the same blob_size would have, just stretched into an oval.
        At body_aspect=1 a fish IS that blob."""
        b = self.blob_size if blob_size is None else blob_size
        return b / np.sqrt(max(self.body_aspect, 1e-3))

    def _body_len_px(self):
        return 2.0 * self._half_width_px() * self.body_aspect

    @property
    def entry_radius(self):
        """Normalized radius new arrivals appear at — just outside the pond
        (and, at every sane radius_scale, just off the panel)."""
        return self.roam_bound + ENTRY_MARGIN

    # ── population ──────────────────────────────────────────────────────
    def _compact(self, alive):
        count = int(np.count_nonzero(alive))
        for arr in self._soa:
            arr[:count] = arr[: self.n][alive]
        self.n = count

    def _spawn(self, count, *, mode=1, nocap=False):
        """Append `count` fish. Caller sets position/heading/speed after —
        this seeds the per-fish randomness every mode shares."""
        count = int(min(count, CAP - self.n))
        if count <= 0:
            return slice(self.n, self.n)
        s = slice(self.n, self.n + count)
        rng = self._rng
        self.p_mode[s] = mode
        self.p_nocap[s] = 1 if nocap else 0
        self.p_disp[s] = np.nan
        self.p_enter[s] = 0.0 if mode == 1 else 1.0
        self.p_erate[s] = 1.0
        self.p_leave[s] = 0.0
        self.p_lfade[s] = DROP_SETTLE_S
        self.p_dl[s] = np.inf
        self.p_lk[s] = np.inf
        self.p_scatter[s] = rng.random(count, dtype=np.float32)
        self.p_bright[s] = 0.0
        self.p_grad_from[s] = np.nan
        # every fish carries a colour from birth; the ordinary population's
        # is overwritten from its slot each frame, a school/rush fish keeps
        # the one it arrived with
        self.p_grad[s] = rng.random(count, dtype=np.float32)
        self.p_flap[s] = rng.uniform(0.0, 2 * np.pi, count)
        self.p_jog[s] = 0.0
        self.p_ro[s] = 0.0
        self.p_lun[s] = 0.0
        self.p_lun_t[s] = 0.0
        self.p_var[s] = rng.uniform(-1.0, 1.0, count)
        self.p_acc[s] = 0.0
        self.p_spd[s] = self.cruise_px
        self.p_hd[s] = rng.uniform(0.0, 2 * np.pi, count)
        self.p_x[s] = 0.0
        self.p_y[s] = 0.0
        self.p_x0[s] = np.nan
        self.p_y0[s] = np.nan
        # body trail: NaN flags "needs backfill" — seeded from the final
        # spawn position/heading each caller sets right after this returns
        self.p_trail_x[s] = np.nan
        self.p_trail_y[s] = np.nan
        self.p_trail_acc[s] = 0.0
        self.p_wsg[s] = 0.0
        self.p_wr[s] = 0.0
        self.p_wph[s] = np.nan
        self.p_peel[s] = np.nan
        self.p_om[s] = 0.0
        self.p_pid[s] = -1
        self.p_tamp[s] = 1.0
        self.p_tf[s] = 0.0
        self.p_tst[s] = 1.0
        self.p_tph0[s] = self.p_flap[s]
        self.p_tkick[s] = 0.0
        self.p_dart[s] = 0.0
        self.p_dhd[s] = np.nan
        self.p_dnext[s] = 0.0
        # WORD SHAPES: a fish born mid-shape has no place on the loop (the
        # places are handed out at the edge, and nothing re-spaces the line
        # for an arrival), so it swims ordinarily until the next word
        self.p_ws_s[s] = np.nan
        self.p_ws_rank[s] = np.nan
        self.p_wurg[s] = 0.0
        self.p_wcmd[s] = 0.0
        self.p_wauth[s] = 0.0
        self.p_sb[s] = 0.0
        self.p_sb_t[s] = 0.0
        for freq, phase in (
            (self.p_nf1, self.p_np1),
            (self.p_nf2, self.p_np2),
            (self.p_wf, self.p_wp),
            (self.p_gf, self.p_gp),
        ):
            freq[s] = rng.uniform(0.25, 1.2, count)
            phase[s] = rng.uniform(0.0, 2 * np.pi, count)
        self.n += count
        return s

    def _spawn_swimmers(self, count, active=False, nocap=False):
        """Ordinary population fill: fish swim in from off-panel heading for
        the pond (or appear already inside it on the first boot / an effect
        restart, so a config change never replays the whole arrival)."""
        s = self._spawn(count, mode=0 if active else 1, nocap=nocap)
        k = s.stop - s.start
        if k <= 0:
            return s
        rng = self._rng
        ang = rng.uniform(0.0, 2 * np.pi, k)
        # the pond is wherever the WINDOW is: fish appear just off the view,
        # not just off a fixed patch of a much larger sea.
        cnx, cny = self.cam_nx, self.cam_ny
        if active:
            rr = rng.uniform(0.0, self.roam_bound * 0.9, k)
            self.p_x[s] = cnx + rr * np.cos(ang)
            self.p_y[s] = cny + rr * np.sin(ang)
            self.p_hd[s] = rng.uniform(0.0, 2 * np.pi, k)
            self.p_enter[s] = 1.0
            if self.wall_lookahead > 0.0 and self._wall is not None:
                self._place_inside_the_wall(s)
        else:
            er = self.entry_radius
            self.p_x[s] = cnx + er * np.cos(ang)
            self.p_y[s] = cny + er * np.sin(ang)
            # head for the pond, with a little splay so arrivals aren't a
            # perfect radial star
            inward = np.arctan2(
                (cny - self.p_y[s]) * self.sy,
                (cnx - self.p_x[s]) * self.sx,
            )
            self.p_hd[s] = inward + rng.uniform(-0.5, 0.5, k)
        return s

    def _place_inside_the_wall(self, s, tries=24):
        """A fish that appears already swimming (first boot, an effect
        restart) is placed with its nose, middle and tail inside the line a
        glance lands on — re-drawn, position and heading, until it fits;
        one that never fits keeps its last draw and the wall steer brings it
        in. Only ever runs while the wall is on, so `wall_lookahead = 0`
        draws exactly what it always did."""
        rng = self._rng
        idx = np.arange(s.start, s.stop)
        half = self._half_width_px() * self.body_aspect
        along = np.array([0.0, half, -half], dtype=np.float32)[:, None]
        for _ in range(tries):
            px = self.cx + self.p_x[idx] * self.sx - self.cam_px
            py = self.cy + self.p_y[idx] * self.sy - self.cam_py
            hd = self.p_hd[idx]
            g, _, _ = self._wall_landing(
                px[None, :] + np.cos(hd)[None, :] * along,
                py[None, :] + np.sin(hd)[None, :] * along,
            )
            bad = idx[(g < 0.0).any(axis=0)]
            if bad.size == 0:
                return
            k = bad.size
            ang = rng.uniform(0.0, 2 * np.pi, k)
            rr = rng.uniform(0.0, self.roam_bound * 0.9, k)
            self.p_x[bad] = self.cam_nx + rr * np.cos(ang)
            self.p_y[bad] = self.cam_ny + rr * np.sin(ang)
            self.p_hd[bad] = rng.uniform(0.0, 2 * np.pi, k)
            idx = bad

    def _manage_population(self):
        """Keep the ORDINARY (non-nocap) swimming population equal to
        `particle_count`, then (re)assign evenly spaced home anchors.
        Fish tagged `p_nocap` are the charge school / drop rush and are
        deliberately outside this accounting — their own choreography
        retires them, so the parameter's limit is never permanently
        ignored."""
        n = self.n
        capped = (self.p_mode[:n] < 2) & (self.p_nocap[:n] == 0)
        tracked = np.flatnonzero(capped)
        want = int(self.particle_count)
        have = tracked.size
        if have < want:
            self._spawn_swimmers(want - have, active=not self._booted)
            n = self.n
            tracked = np.flatnonzero(
                (self.p_mode[:n] < 2) & (self.p_nocap[:n] == 0)
            )
        elif have > want:
            doomed = self._rng.choice(
                tracked, size=have - want, replace=False
            )
            self._depart(doomed)
            n = self.n
            tracked = np.flatnonzero(
                (self.p_mode[:n] < 2) & (self.p_nocap[:n] == 0)
            )
        self._booted = True
        self.p_slot[tracked] = np.arange(tracked.size, dtype=np.int16)
        fresh = tracked[~np.isfinite(self.p_x0[tracked])]
        if fresh.size:
            self.p_slot_frac[fresh] = (
                self.p_slot[fresh].astype(np.float32) / max(tracked.size, 1)
            )

    def _depart(self, idx, within=DEPART_S):
        """Send fish away by DISPERSING them (mode 4): full brightness, off
        the panel by `within` seconds from now, retired only once gone. A
        fish already dispersing keeps whichever deadline is SOONER, so a
        later, lazier departure can never slow one down."""
        if len(idx) == 0:
            return
        idx = np.asarray(idx)
        idx = idx[self.p_mode[idx] != 2]   # the drop's ejecta keep theirs
        if idx.size == 0:
            return
        fresh = idx[self.p_mode[idx] != 4]
        self.p_dl[fresh] = np.inf
        # a fish not yet heading out (new, or a lull fish still swirling)
        # starts now; one already on its way keeps its own turn clock
        unleaked = idx[(self.p_mode[idx] != 4) | ~np.isfinite(self.p_lk[idx])]
        self.p_lk[unleaked] = self.t
        self.p_mode[idx] = 4
        self.p_nocap[idx] = 0
        self.p_disp[idx] = np.nan
        self.p_dl[idx] = np.minimum(self.p_dl[idx], self.t + float(within))

    # ── particle handoff ────────────────────────────────────────────────
    def _handoff_snapshot(self):
        if getattr(self, "r_width", None) is None or self.trail is None:
            return None
        n = self.n
        px = self.cx + self.p_x[:n] * self.sx - self.cam_px
        py = self.cy + self.p_y[:n] * self.sy - self.cam_py
        px = np.where(np.isfinite(px), px, self.cx)
        py = np.where(np.isfinite(py), py, self.cy)
        hd = self.p_hd[:n]
        spd = np.where(np.isfinite(self.p_spd[:n]), self.p_spd[:n], 0.0)
        snap = {
            "src": "fish",
            "t": particle_handoff.now(),
            "dims": (self.r_width, self.r_height),
            "px": px.astype(np.float32),
            "py": py.astype(np.float32),
            # each fish's velocity (px/s, its heading x its speed) and how
            # the form lets go — the transition program's RELEASE reads
            # these (particle_handoff)
            "vx": (np.cos(hd) * spd).astype(np.float32),
            "vy": (np.sin(hd) * spd).astype(np.float32),
            # ... and the rate it was turning at (the shoal-burst plan
            # §5.1) — a cloud with no host continues on this, and a born
            # fish/blob keeps turning at it
            "om": np.where(np.isfinite(self.p_om[:n]),
                           self.p_om[:n], 0.0).astype(np.float32),
            "gesture": "swim",
            "grad": self.p_grad[:n].copy(),
            "bright": self.p_bright[:n].copy(),
            "gradient": self._config.get("gradient"),
            "spin_sign": -1.0 if self.reverse else 1.0,
            "blob_size": float(self.blob_size),
            "trail": self.trail,
            "native": {
                "n": n,
                "t": self.t,
                "roll_total": self.roll_total,
                # the window travels with the fish: the SoA holds WORLD
                # positions, so a successor that reset the camera to zero
                # would inherit a shoal parked wherever the window had got
                # to and never see it again.
                "cam": (self.cam_px, self.cam_py, self.cam_vx, self.cam_vy),
                "arrays": {
                    name: getattr(self, name)[:n].copy()
                    for name in _SOA_NAMES
                },
            },
        }
        # THE KEEPERS MELD (drop-scene-variety phase 3, fx/effects/
        # fireworks.py's KEEPERS block): a lull TOLD it leads into another
        # effect flags its keepers, so the arriving effect can treat them as
        # the drop's own pieces (Fireworks explodes each where it stands).
        # Untold, or told its own effect: no flag — every successor adopts
        # exactly as before.
        nxt = lull_handoff.next_effect(self._config)
        if self._lull_state is not None and nxt and nxt != "fish":
            snap["keepers"] = self.p_mode[:n] == 5
        return snap

    def _formation_points(self):
        """The fish a transition program forms onto: the screen position
        of every ordinary (swimming or entering) fish, in a stable order,
        read live each frame (fx/effects/transition_program.py)."""
        n = self.n
        idx = np.flatnonzero(self.p_mode[:n] < 2)
        x = self.cx + self.p_x[idx] * self.sx - self.cam_px
        y = self.cy + self.p_y[idx] * self.sy - self.cam_py
        ok = np.isfinite(x) & np.isfinite(y)
        return (x[ok], y[ok])

    # ── THE HOST FRAME (the shoal-burst plan §5.2, fx/effects/
    # transition_program.py's own docstring is the binding statement) ─────

    def _program_birth(self, snap):
        """BORN MATCHED: one fish per released object, AT its position, on
        its heading and speed, turning at its inherited rate (the PEEL),
        which is what lets a transition program's cloud ride it instead of
        flying to a stranger.

        Fish needs nothing new to be born this way — heading and speed ARE
        its state and `PEEL_S` already eases an inherited turn rate into
        its own steering; this is `_adopt_handoff`'s own cross-type block
        plus the count rule and a pid. Deliberately NOT part of that method
        (the crossfade adoption path stays byte-identical).

        Returns one pid per released object (-1 where the count clamped and
        it got none)."""
        px = np.asarray(snap["px"], dtype=np.float32)
        n_obj = int(px.size)
        pids = np.full(n_obj, -1, dtype=np.int64)
        if n_obj == 0 or getattr(self, "r_width", None) is None:
            return pids
        py = np.asarray(snap["py"], dtype=np.float32)
        vx = np.asarray(snap.get("vx", np.zeros(n_obj)), dtype=np.float32)
        vy = np.asarray(snap.get("vy", np.zeros(n_obj)), dtype=np.float32)
        om = np.asarray(snap.get("om", np.zeros(n_obj)), dtype=np.float32)
        grad = np.asarray(snap.get("grad", np.zeros(n_obj)), dtype=np.float32)
        bright = np.asarray(snap.get("bright", np.ones(n_obj)), dtype=np.float32)
        authored = int(self._config["particle_count"])
        match = bool(snap.get("match_count", True))
        # the count the SCENE will run at: the released count when the match
        # is on, the authored one when it is off (the plan's §5.4 rule)
        count = int(min(max(n_obj if match else authored, 1), MAX_PARTICLE_COUNT))
        # ... and how many are born ON a released object: never more than
        # there are objects to be born on. With the match off the rest fly
        # in from off-panel the ordinary way, as any live count change does.
        want = int(min(count, n_obj))
        # a DEFERRED birth (the eruption's, at its bloom) replaces whatever
        # is on the panel: every ordinary fish disperses out of it
        if self.n:
            live = np.flatnonzero(
                (self.p_mode[: self.n] < 2) & (self.p_nocap[: self.n] == 0))
            if live.size:
                self._depart(live, within=HANDOFF_ENTER_S)
                self.p_pid[live] = -1
        base = self.n
        sl = self._spawn(want, mode=1)
        got = self.n - base
        if got <= 0:
            return pids
        ex = (px[:got] - self.cx + self.cam_px) / max(self.sx, 1e-6)
        ey = (py[:got] - self.cy + self.cam_py) / max(self.sy, 1e-6)
        self.p_x[sl] = ex
        self.p_y[sl] = ey
        self.p_x0[sl] = ex
        self.p_y0[sl] = ey
        spd = np.hypot(vx[:got], vy[:got])
        moving = np.isfinite(spd) & (spd > 1e-3)
        self.p_hd[sl] = np.where(
            moving, np.arctan2(vy[:got], vx[:got]),
            np.arctan2(ey * self.sy, ex * self.sx) + np.pi / 2.0)
        self.p_spd[sl] = np.where(
            moving,
            np.clip(spd, 0.2 * self.cruise_px, 4.0 * self.cruise_px),
            self.cruise_px)
        # THE PEEL (PEEL_S): the inherited turning rate, easing into its
        # own steering — so the host's first stretch IS the parent's
        # continuation and the cloud riding it continues that motion
        ok = moving & np.isfinite(om[:got])
        self.p_peel[sl] = np.where(ok, om[:got], np.nan)
        if ok.any():
            self._peel_age = 0.0
        self.p_erate[sl] = max(1.0, self.enter_time / HANDOFF_ENTER_S)
        self.p_grad[sl] = grad[:got]
        self.p_grad_from[sl] = grad[:got]
        self.p_bright[sl] = np.clip(bright[:got], 0.3, 1.0)
        ids = self._next_pid + np.arange(got, dtype=np.int64)
        self._next_pid += got
        self.p_pid[sl] = ids
        pids[:got] = ids
        self.particle_count = count
        self._count_hold = (
            self.t + max(float(snap.get("count_hold_s", 0.0) or 0.0), 0.0),
            authored,
        )
        self._booted = True
        return pids

    def _program_hosts(self, pids):
        """Where each pid's fish is NOW, on screen (pixels) — NaN for a pid
        that has since retired (a fish disperses), whose pieces fall back to
        the constant-turn continuation and fade."""
        pids = np.asarray(pids, dtype=np.int64)
        qx = np.full(pids.size, np.nan, dtype=np.float32)
        qy = np.full(pids.size, np.nan, dtype=np.float32)
        n = self.n
        if n == 0 or pids.size == 0:
            return qx, qy
        live = np.flatnonzero((self.p_mode[:n] < 2) & (self.p_pid[:n] >= 0))
        if live.size == 0:
            return qx, qy
        have = self.p_pid[live]
        srt = np.argsort(have)
        have, live = have[srt], live[srt]
        at = np.searchsorted(have, pids)
        at_c = np.clip(at, 0, max(have.size - 1, 0))
        ok = (at < have.size) & (pids >= 0) & (have[at_c] == pids)
        if not ok.any():
            return qx, qy
        idx = live[at_c[ok]]
        x = self.cx + self.p_x[idx] * self.sx - self.cam_px
        y = self.cy + self.p_y[idx] * self.sy - self.cam_py
        good = np.isfinite(x) & np.isfinite(y)
        sel = np.flatnonzero(ok)[good]
        qx[sel] = x[good]
        qy[sel] = y[good]
        return qx, qy

    def deactivate(self):
        virtual = self._virtual
        try:
            if virtual is not None:
                particle_handoff.store(virtual.id, self._handoff_snapshot())
        except Exception:
            pass
        super().deactivate()

    def _adopt_handoff(self, snap=None, allow_hold=True):
        """First-draw adoption of the predecessor's on-screen particles —
        same two delivery paths and the same holds as Orbits."""
        virtual = self._virtual
        live = snap is not None
        if snap is None:
            sibling = (
                getattr(virtual, "_transition_effect", None)
                if virtual else None
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
        if snap["src"] == "fish":
            native = snap["native"]
            k = min(native["n"], CAP)
            for name, arr in native["arrays"].items():
                if hasattr(self, name):
                    getattr(self, name)[:k] = arr[:k]
            self.n = k
            self.t = float(native.get("t", 0.0))
            self.roll_total = float(native.get("roll_total", 0.0))
            cam = native.get("cam") or (0.0, 0.0, 0.0, 0.0)
            (
                self.cam_px, self.cam_py, self.cam_vx, self.cam_vy
            ) = (float(v) for v in cam)
            self._cam_px_prev = self.cam_px
            self._cam_py_prev = self.cam_py
            self._booted = True
            return
        # cross-type: carry the predecessor's gradient and swirl sign so
        # colors and rotation are continuous at the switch instant.
        patch = {}
        g = snap.get("gradient")
        if g and g != self._config.get("gradient"):
            patch["gradient"] = g
        spin_sign = float(snap.get("spin_sign") or 0.0)
        if spin_sign and (spin_sign < 0) != bool(self._config["reverse"]):
            patch["reverse"] = spin_sign < 0
        if patch:
            # sanctioned in-render config path (we're under the effect lock)
            self._apply_config(patch, validate=False, fire_event=False)
        size_from = snap.get("blob_size")
        if size_from and size_from != self.blob_size:
            self._size_from = float(size_from)
            self._size_age = 0.0
        c_px = snap.get("center_px")
        if c_px:
            ncx = (
                float(c_px[0]) - self.cx + self.cam_px
            ) / max(self.sx, 1e-6)
            ncy = (
                float(c_px[1]) - self.cy + self.cam_py
            ) / max(self.sy, 1e-6)
        else:
            ncx = ncy = 0.0
        if snap["src"] == "radial":
            # "suck in then erupt": the collapsing radial owns phase 1 —
            # hold the school's arrival until it has pinched out
            self._booted = True
            if live and particle_handoff.transition_progress(virtual) is not None:
                self._erupt_hold = {
                    "ncx": ncx, "ncy": ncy, "t0": particle_handoff.now(),
                }
            else:
                self._spawn_center_burst(ncx, ncy, self.particle_count)
            return
        # generic particle predecessor: its brightest blobs become fish,
        # already swimming, at the positions they were left at.
        bright = snap["bright"]
        cap_mask = snap.get("captured")
        if cap_mask is not None and len(cap_mask) == len(bright):
            eligible = np.flatnonzero(~cap_mask)
        else:
            eligible = np.arange(len(bright))
        order = eligible[np.argsort(bright[eligible])[::-1]]
        want = min(self.particle_count, order.size)
        self._booted = True
        got = 0
        if want > 0:
            base = self.n
            s = self._spawn(want, mode=1)
            got = self.n - base
            if got > 0:
                idx = order[:got]
                ex = (
                    snap["px"][idx] - self.cx + self.cam_px
                ) / max(self.sx, 1e-6)
                ey = (
                    snap["py"][idx] - self.cy + self.cam_py
                ) / max(self.sy, 1e-6)
                self.p_x[s] = ex
                self.p_y[s] = ey
                self.p_x0[s] = ex
                self.p_y0[s] = ey
                # swim off along the tangent of where they sat — never a
                # radial star, which reads as an explosion, not a shoal
                self.p_hd[s] = np.arctan2(
                    ey * self.sy, ex * self.sx
                ) + np.pi / 2.0
                # THE SHOALING FIX (VENDOR #68): a predecessor that said how
                # each piece was moving keeps that heading and speed — a
                # re-heading to the tangent is a new direction and speed on
                # the first real frame.
                ivx, ivy = snap.get("vx"), snap.get("vy")
                if ivx is not None and ivy is not None:
                    ivx = np.asarray(ivx, dtype=np.float32)[idx]
                    ivy = np.asarray(ivy, dtype=np.float32)[idx]
                    ispd = np.hypot(ivx, ivy)
                    moving = np.isfinite(ispd) & (ispd > 1e-3)
                    self.p_hd[s] = np.where(
                        moving, np.arctan2(ivy, ivx), self.p_hd[s])
                    self.p_spd[s] = np.where(
                        moving,
                        np.clip(ispd, 0.2 * self.cruise_px,
                                4.0 * self.cruise_px),
                        self.p_spd[s])
                    # THE PEEL (PEEL_S): the inherited turning rate too
                    iom = snap.get("om")
                    if iom is not None and len(iom) == len(snap["px"]):
                        iom = np.asarray(iom, dtype=np.float32)[idx]
                        ok = moving & np.isfinite(iom)
                        self.p_peel[s] = np.where(ok, iom, np.nan)
                        if ok.any():
                            self._peel_age = 0.0
                self.p_erate[s] = max(1.0, self.enter_time / HANDOFF_ENTER_S)
                self.p_grad[s] = snap["grad"][idx]
                self.p_grad_from[s] = snap["grad"][idx]
                self.p_bright[s] = np.clip(snap["bright"][idx], 0.3, 1.0)
        deficit = self.particle_count - got
        if deficit > 0:
            s = self._spawn_swimmers(deficit)
            if s.stop > s.start:
                self.p_erate[s] = max(1.0, self.enter_time / HANDOFF_ENTER_S)

    def _spawn_center_burst(self, ncx, ncy, count):
        """Fish erupting outward from a predecessor's center point."""
        base = self.n
        s = self._spawn(count, mode=1)
        k = self.n - base
        if k <= 0:
            return
        ang = self._rng.uniform(0.0, 2 * np.pi, k)
        jr = self._rng.uniform(0.0, 0.08, k)
        self.p_x[s] = ncx + jr * np.cos(ang)
        self.p_y[s] = ncy + jr * np.sin(ang)
        self.p_x0[s] = self.p_x[s]
        self.p_y0[s] = self.p_y[s]
        self.p_hd[s] = ang
        self.p_erate[s] = max(1.0, self.enter_time / HANDOFF_ENTER_S)

    def _spawn_drop_ejecta(self, count):
        """Drop explosion surplus: fish that bolt from the centre and swim
        fully off-panel before the boost window ends. They ride the
        'leaving' machinery (mode 2, constant heading, off-panel retirement)
        and stay bright almost to the exit."""
        base = self.n
        s = self._spawn(count, mode=2)
        k = self.n - base
        if k <= 0:
            return
        rng = self._rng
        ang = rng.uniform(0.0, 2 * np.pi, k)
        jr = rng.uniform(0.0, 0.06, k)
        self.p_x[s] = self.cam_nx + jr * np.cos(ang)
        self.p_y[s] = self.cam_ny + jr * np.sin(ang)
        self.p_x0[s] = self.p_x[s]
        self.p_y0[s] = self.p_y[s]
        self.p_hd[s] = ang
        self.p_spd[s] = self.cruise_px * rng.uniform(*DROP_EJECTA_SPEED, k)
        self.p_lfade[s] = DROP_SETTLE_S
        self.p_grad[s] = rng.random(k, dtype=np.float32)

    # ── charge / lull / drop ────────────────────────────────────────────
    def _mean_heading(self):
        n = self.n
        live = np.flatnonzero(self.p_mode[:n] < 2)
        if live.size == 0:
            return float(self._rng.uniform(0.0, 2 * np.pi))
        return float(np.arctan2(
            np.sin(self.p_hd[live]).mean(), np.cos(self.p_hd[live]).mean()
        ))

    def _spawn_school(self, count, slot0=0):
        """The charge's school: fish swim in from behind the shared heading
        so they arrive already travelling with the shoal. Tagged `p_nocap`
        — the ONE charge-scoped bypass of the population cap.

        Placement is an EVEN spread, not a uniform-random one (his ask, see
        SCHOOL_SPACING_W above): each fish takes the next slot on a
        low-discrepancy sequence across the school's width and depth, so a
        half-filled school is already spread across the panel rather than
        clustered wherever the dice fell. `slot0` continues that sequence
        across the several calls a progressive fill makes.
        """
        base = self.n
        s = self._spawn(count, mode=1, nocap=True)
        k = self.n - base
        if k <= 0:
            return
        rng = self._rng
        hd = self._school_hd
        slot = np.arange(slot0, slot0 + k, dtype=np.float32)
        # an even spread across the width behind the school, jittered by the
        # school's own variation knob so it never reads as a drawn rank
        jitter = rng.uniform(-1.0, 1.0, k) * 0.5 * self.school_variation
        lateral = np.clip(
            2.0 * ((slot * SCHOOL_PHI_LAT) % 1.0) - 1.0 + jitter, -1.0, 1.0
        ) * self.roam_bound
        back = self.entry_radius + (
            (slot * SCHOOL_PHI_DEPTH) % 1.0
        ) * 0.5
        self.p_x[s] = self.cam_nx - np.cos(hd) * back - np.sin(hd) * lateral
        self.p_y[s] = self.cam_ny - np.sin(hd) * back + np.cos(hd) * lateral
        self.p_x0[s] = self.p_x[s]
        self.p_y0[s] = self.p_y[s]
        self.p_hd[s] = hd + self.p_var[s] * self.school_variation
        self.p_erate[s] = max(1.0, self.enter_time / HANDOFF_ENTER_S)

    def _spawn_rush(self, count, speed_x=None):
        """THE DROP'S RUSH (his 2026-08-28 addendum: "I want the rush to be
        part of the drop. All the fish rush in, swirl around and some stay
        behind per the blob count parameter after the drop is done").

        It used to be the lull's, entering at 60% of the lull behind the
        lone fish. His lull clock has no fish left to enter behind, so the
        rush moved WHOLE to the drop instead of being dropped: same
        population, same chaos knob, same `p_nocap` cap exemption, and the
        same `_settle_rush` handing the survivors to the ordinary
        population. What changed is only WHERE they come from — every
        direction, converging on the centre of view — because the drop is
        an explosion at the centre, not a shoal sweeping past one fish.

        Tagged `p_nocap` — the ONE drop-scoped bypass of the population cap.

        `speed_x` scales the entry speed for an INTENSITY-SCALED drop (see
        _drop_step); None is the fixed rush, expression for expression.
        """
        base = self.n
        s = self._spawn(count, mode=3, nocap=True)
        k = self.n - base
        if k <= 0:
            return
        rng = self._rng
        chaos = float(self.rush_chaos)
        # in from every side, evenly around the ring so the surge does not
        # arrive as one clump (the same reason the charge's school spawns on
        # an even spread — see SCHOOL_SPACING_W)
        ang = (
            (np.arange(k, dtype=np.float32) + rng.random(k, dtype=np.float32)
             * chaos) / max(k, 1) * 2 * np.pi
        )
        # just off-panel, never far beyond it: a rush fish that spawns
        # outside the off-panel retirement bound is retired on the very
        # frame it was born and is never seen at all
        out = self.entry_radius + rng.uniform(0.0, 0.15 + 0.35 * chaos, k)
        self.p_x[s] = self.cam_nx + np.cos(ang) * out
        self.p_y[s] = self.cam_ny + np.sin(ang) * out
        self.p_x0[s] = self.p_x[s]
        self.p_y0[s] = self.p_y[s]
        # heading inward, jittered by the chaos knob
        self.p_hd[s] = (
            ang + np.pi + rng.uniform(-1.0, 1.0, k) * chaos * (np.pi / 3.0)
        )
        if speed_x is None:
            self.p_spd[s] = self.cruise_px * (
                2.2 + rng.uniform(-1.0, 1.0, k) * chaos * 1.1
            )
        else:
            self.p_spd[s] = self.cruise_px * float(speed_x) * (
                2.2 + rng.uniform(-1.0, 1.0, k) * chaos * 1.1
            )
        self.p_enter[s] = 1.0

    def _enter_phase(self, phase):
        self._phase = phase
        self._phase_t = 0.0
        self._phase_done_t = None
        if phase == "charge":
            n = self.n
            self._charge_n0 = int(np.count_nonzero(self.p_mode[:n] < 2)) or 1
            self._school_hd = self._mean_heading()
            self._school_on = True
            self._school_turn_t = 0.0
            self._drop_state = None
            self._lull_state = None
        elif phase == "lull":
            self._school_on = False
            self._drop_state = None
            self._start_lull()
        elif phase == "drop":
            self._school_on = False
            self._lull_state = None
            self._drop_state = {"burst_done": False}
        elif phase == "none":
            self._school_on = False
            self._drop_state = None
            self._lull_state = None
            self._speed_scale = 1.0
            self.particle_count = int(self._config["particle_count"])
            self._release_nocap()

    def _start_lull(self):
        """The lull's edge. Told (or defaulting to) `lull_keep` >= 1: the
        2026-10-08 searching lull (_start_lull_keep). Told 0: his
        2026-08-28 clock, byte for byte (_start_lull_gone)."""
        keep = lull_handoff.keep(self._config)
        if keep <= 0:
            self._start_lull_gone()
            return
        self._start_lull_keep(keep)

    def _start_lull_keep(self, keep):
        """Break the school into the swirl, except the `keep` fish nearest
        the centre of view, which become KEEPERS (mode 5). Every other fish
        is ranked to leak out before the half-way mark exactly the way the
        old lull ranked them for the third. A lull with fewer fish than it
        was told to keep calls the shortfall in from off-panel (they swim
        in and fade up like any arrival — never appear from nothing)."""
        n = self.n
        self.p_disp[:n] = np.nan
        nxt = lull_handoff.next_effect(self._config)
        self._lull_state = {
            "dark": 1.0, "keep": keep, "search": None,
            "spacing": (KEEP_SPACING_NEXT_BODIES
                        if nxt and nxt != "fish" else KEEP_SPACING_BODIES),
            "look_phase": float(self._rng.uniform(0.0, 2 * np.pi)),
        }
        live = np.flatnonzero(
            (self.p_mode[:n] < 2) | (self.p_mode[:n] == 3)
        )
        d = np.hypot(
            (self.p_x[live] - self.cam_nx) * self.sx,
            (self.p_y[live] - self.cam_ny) * self.sy,
        )
        near = live[np.argsort(d, kind="stable")]
        keepers = near[:keep]
        leavers = near[keep:]
        if keepers.size:
            self.p_mode[keepers] = 5
            self.p_nocap[keepers] = 0
            self.p_lk[keepers] = np.inf
            self.p_dl[keepers] = np.inf
        if leavers.size:
            self.p_mode[leavers] = 4
            self.p_nocap[leavers] = 0
            self.p_lk[leavers] = np.inf
            self.p_dl[leavers] = np.inf
            # furthest from the centre of view leaves first
            order = leavers[::-1]
            self.p_disp[order] = (
                np.arange(1, order.size + 1, dtype=np.float32) / order.size
            )
        short = keep - int(keepers.size)
        if short > 0:
            s = self._spawn_swimmers(short, active=False)
            self.p_mode[s] = 5

    def _start_lull_gone(self):
        """Break the school into the SWIRL and schedule every fish to leak
        out of it across the lull's first third (`lull_keep = 0` only).

        His 2026-08-28 ruling: no lone fish and no survivor of any kind. His
        2026-09-16 one: they leave by swirling and leaking off the screen,
        never by fading. Every live fish becomes a DISPERSING fish at once
        (mode 4, full brightness) that is not heading out yet (`p_lk` inf);
        the rank written here is what `_lull_step` releases them by, and its
        backstop still guarantees the third.
        """
        n = self.n
        self.p_disp[:n] = np.nan
        self._lull_state = {"dark": 1.0, "keep": 0}
        live = np.flatnonzero(
            (self.p_mode[:n] < 2) | (self.p_mode[:n] == 3)
        )
        if live.size == 0:
            return
        self.p_mode[live] = 4
        self.p_nocap[live] = 0
        self.p_lk[live] = np.inf
        self.p_dl[live] = np.inf
        # furthest from the centre of view leaves first, so the panel
        # empties inward rather than in a random order
        d = np.hypot(
            (self.p_x[live] - self.cam_nx) * self.sx,
            (self.p_y[live] - self.cam_ny) * self.sy,
        )
        order = live[np.argsort(d)][::-1]
        self.p_disp[order] = (
            np.arange(1, order.size + 1, dtype=np.float32) / order.size
        )

    def _phase_step(self, dt):
        """Advance the charge/lull/drop state machine. Runs every draw,
        before population management; sets the per-frame overrides
        (_speed_scale, particle_count, school/rush state)."""
        pend = self._phase_pending
        if pend is not None:
            self._phase_pending = None
            if pend != self._phase:
                self._enter_phase(pend)
        self._speed_scale = 1.0
        if self._phase != "drop":
            self._rush_swirl = 0.0
        if self._phase != "lull":
            # the lull's swirl belongs to the lull: whatever cut it short (the
            # drop arriving early, a watchdog release, a reset) sends anything
            # still circling out on an ordinary departure, never leaves it
            # swirling forever with nothing to release it
            n = self.n
            circling = np.flatnonzero(
                (self.p_mode[:n] == 4) & ~np.isfinite(self.p_lk[:n])
            )
            if circling.size:
                self._depart(circling)
            # ... and its KEEPERS belong to it too: whatever ended the lull
            # (the drop — "all the missing fish come back" with the keeper
            # among them — a watchdog release, a reset), they rejoin the
            # ordinary population on the very next frame
            self._keep = None
            self._pd_clk = None
            self._pd_dart = None
            keepers = np.flatnonzero(self.p_mode[:n] == 5)
            if keepers.size:
                self.p_mode[keepers] = np.where(
                    self.p_enter[keepers] < 1.0, 1, 0)
                self.p_nocap[keepers] = 0
        if self._phase == "none":
            return
        self._phase_t += dt
        # orphan watchdog: a charge/lull whose payoff never arrives releases
        # itself — the school scatters, no burst
        due, self._phase_done_t = particle_handoff.phase_release_due(
            self._phase, self.phase_progress, self._phase_t,
            self._phase_done_t,
        )
        if due:
            _LOGGER.info(
                "fish: %s watchdog release after %.1fs",
                self._phase, self._phase_t,
            )
            self._school_on = False
            self._lull_state = None
            self._phase = "drop"
            self._phase_t = 0.0
            self.phase_progress = 0.0
            self.particle_count = int(self._config["particle_count"])
            # every sentinel this branch sets is a concrete value: nothing
            # downstream can observe a half-built drop state (the render-
            # thread crash class, AGENTS.md)
            self._drop_state = {"burst_done": True, "settled": True}
            self._release_nocap()
            return
        p = float(np.clip(self.phase_progress, 0.0, 1.0))
        if self._phase == "charge":
            self._charge_step(p)
        elif self._phase == "lull":
            self._lull_step(p, dt)
        else:
            self._drop_step()

    def _charge_step(self, p):
        """His words: up to 12 fish come in, all moving in unison, then
        start changing directions on every beat, minimum 400ms apart, still
        in unison — near-identical motion with minor variation. His own
        `school_count` default has since moved to 18 (+50%, 2026-09-16),
        watching it live — the quote above is the original ask, not the
        current number; see `school_count`'s own schema default."""
        self._school_on = True
        want = int(min(self.school_count, MAX_SCHOOL))
        f = min(p / CHARGE_FILL_AT, 1.0) if CHARGE_FILL_AT > 0 else 1.0
        target = int(round(self._charge_n0 + (want - self._charge_n0) * f))
        target = max(target, 1)
        n = self.n
        have = int(np.count_nonzero(self.p_mode[:n] < 2))
        if have < target:
            # the slot base is what has ALREADY arrived, so the even
            # spread continues across a progressive fill instead of
            # restarting (and stacking) on every call
            self._spawn_school(target - have, slot0=have)
        self._school_turn_t += self.passed_dt
        # beat turns arm only once the school has gathered; the flag is
        # consumed either way so a beat during the gather can't latch and
        # fire late
        if self._beat_pending:
            self._beat_pending = False
            if f >= 1.0 and self._school_turn_t >= max(self.turn_min_time, 0.0):
                self._school_turn_t = 0.0
                lo, hi = CHARGE_TURN_MIN
                mag = float(self._rng.uniform(lo, hi))
                sign = 1.0 if self._rng.random() < 0.5 else -1.0
                self._school_hd = float(
                    _wrap_pi(self._school_hd + sign * mag)
                )

    def _lull_step(self, p, dt):
        """Advance the lull: the searching lull (_lull_keep_step) unless it
        was told `lull_keep = 0`, which runs his 2026-08-28 clock."""
        self._pre_drop_step()
        st = self._lull_state
        if st is None:
            self._start_lull()
            st = self._lull_state
        if st.get("keep", 0) > 0:
            self._lull_keep_step(p, dt)
            return
        self._lull_gone_step(p, dt)

    def _lull_clock(self, p):
        """(f, h, h_rate, lull_s) for the searching lull: `f` the progress
        (or its wall-clock fallback while progress sits at 0), `h` how far
        toward the half-way keep mark (lull_handoff.keep_mark), `h_rate` how
        fast `h` moves per second, and the lull's length in seconds — TOLD
        when SpotFX pushed `lull_s`, else read back off the progress ramp
        (which covers PHASE_RAMP_SHARE of the gap), None until it moves."""
        f = p if p > 0.0 else min(self._phase_t / LULL_FALL_S, 1.0)
        cfg = self._config
        if lull_handoff.told(cfg):
            total = lull_handoff.lull_s(cfg)
            if self._pd_clk is not None:
                # THE PRE-DROP: the searching lull ends on it (PRE_DROP_*)
                total = min(total, pre_drop.at_s(cfg))
                h = max(0.0, self._phase_t) / max(total / 2.0, 1e-6)
                return f, h, 2.0 / max(total, 1e-6), total
            h = lull_handoff.keep_mark(cfg, f, self._phase_t)
            return f, h, 2.0 / max(total, 1e-6), total
        h = lull_handoff.keep_mark(cfg, f, self._phase_t)
        rate = (f / self._phase_t if self._phase_t > 1e-3 and f > 0.0
                else 1.0 / LULL_FALL_S)
        total = (1.0 / max(rate, 1e-6)) / PHASE_RAMP_SHARE if f > 0.0 else None
        return f, h, rate / lull_handoff.LEGACY_KEEP_MARK, total

    def _lull_keep_step(self, p, dt):
        """THE SEARCHING LULL (the 2026-10-08 block at the top of the
        module): leak every non-keeper out before the half-way mark, then
        let the keepers search side to side until the drop. Never dark."""
        st = self._lull_state
        f, h, h_rate, total = self._lull_clock(p)
        n = self.n

        # ── edge -> half way: swirl, leak out in rank order ─────────────
        disp = np.flatnonzero(self.p_mode[:n] == 4)
        if disp.size:
            rank = self.p_disp[disp]
            ranked = np.isfinite(rank)
            leak_h = np.minimum(
                KEEP_LEAK_FROM
                + np.where(ranked, rank, 0.0) * (KEEP_LEAK_TO - KEEP_LEAK_FROM),
                KEEP_EXIT_BY - LULL_EXIT_MIN_S * h_rate,
            )
            due = disp[ranked & (h >= leak_h)]
            if due.size:
                self.p_lk[due] = self.t
                self.p_disp[due] = np.nan
            self.p_dl[disp] = self.t + max(KEEP_EXIT_BY - h, 0.0) / max(
                h_rate, 1e-6)
        # the backstop that makes "one left at the half way mark" a
        # guarantee: past the mark, only keepers remain
        if h >= 1.0 and n:
            alive = self.p_mode[:n] == 5
            if not alive.all():
                self._compact(alive)
            if st["search"] is None:
                st["search"] = {"stage": None}

        st["dark"] = 1.0
        self.particle_count = 0
        self._keep_targets(h, total)

    def _keeper_offsets(self, k):
        """Each keeper's place in its group, normalized units relative to
        the group's centre, and the group's half-width in px: a loose ROW
        across the panel's long axis, neighbours `spacing` body lengths
        apart (closer if the row would span more than KEEP_GROUP_MAX of the
        pond either side), every other one a little up or down so it never
        reads as a ruled line. A row, not a ring: the search runs side to
        side, and a ring would park a keeper against the top or bottom wall.
        One keeper: the centre itself."""
        if k <= 1:
            z = np.zeros(max(k, 0))
            return z, z, 0.0
        st = self._lull_state
        pond_px = max(self.roam_bound * self.sx, 1e-3)   # across, not up
        gap = min(st["spacing"] * self._body_len_px(),
                  2.0 * KEEP_GROUP_MAX * pond_px / (k - 1))
        col = np.arange(k) - (k - 1) / 2.0
        x_px = col * gap
        y_px = np.where(np.arange(k) % 2 == 0, 0.3, -0.3) * gap
        st["spacing_px"] = float(gap)
        return x_px / self.sx, y_px / self.sy, float(np.max(np.abs(x_px)))

    def _keep_targets(self, h, total):
        """Where every keeper is heading, how fast, and which way its head
        is looking — written into `self._keep` for draw() to steer by.
        Before the mark: the centre of view, slowing toward search speed.
        After it: the search legs and pauses (the module's LULL block)."""
        st = self._lull_state
        n = self.n
        keepers = np.flatnonzero(self.p_mode[:n] == 5)
        self._keep = None
        if keepers.size == 0:
            return
        k = keepers.size
        ox, oy, half_px = self._keeper_offsets(k)
        # who takes which place in the row: by where they are across the
        # panel, so no two keepers cross to reach their places. Settled at
        # the lull's first frame, and again at the start of every leg.
        cruise = self.cruise_px
        cnx, cny = self.cam_nx, self.cam_ny
        gx = float(np.mean(self.p_x[keepers]))
        gy = float(np.mean(self.p_y[keepers]))
        search = st["search"]
        look = 0.0
        if search is None:
            # approach: ease in to the centre of view, slowing as the mark
            # nears
            w = min(max(h, 0.0), 1.0)
            tx, ty = cnx, cny
            speed = cruise * (1.0 + (self.search_speed - 1.0) * w)
            seek = True
        else:
            left = (None if total is None
                    else max(total - self._phase_t, 0.0))
            v = max(self.search_speed * cruise, 1e-3)
            if search["stage"] is None:
                # the first leg goes the way the keepers already face
                hx = float(np.mean(np.cos(self.p_hd[keepers])))
                search["side"] = 1.0 if hx >= 0.0 else -1.0
                self._start_leg(search, gx, gy, left, v, half_px, first=True)
                st["slot_of"] = None
            elif search["stage"] == "go":
                d_px = float(np.hypot((search["tx"] - gx) * self.sx,
                                      (search["ty"] - gy) * self.sy))
                over = self._phase_t - search["t0"] > search["limit"]
                if d_px <= max(0.5 * self._body_len_px(), 1.5) or over:
                    search["stage"] = "pause"
                    search["t0"] = self._phase_t
                    hi = float(self.search_pause_s)
                    lo = min(SEARCH_PAUSE_MIN_S, hi)
                    search["limit"] = (hi if left is None else float(
                        np.clip(SEARCH_PAUSE_FRAC * left, lo, hi)))
            elif self._phase_t - search["t0"] >= search["limit"]:
                search["side"] = -search["side"]
                self._start_leg(search, gx, gy, left, v, half_px,
                                first=False)
                st["slot_of"] = None
            if search["stage"] == "go":
                tx, ty = search["tx"], search["ty"]
                speed = v
                seek = True
            else:
                tx, ty = gx, gy
                speed = SEARCH_PAUSE_X * cruise
                seek = False
                el = self._phase_t - search["t0"]
                ease = min(el / SEARCH_LOOK_EASE_S,
                           (search["limit"] - el) / SEARCH_LOOK_EASE_S, 1.0)
                look = max(ease, 0.0)
        slot_of = st.get("slot_of")
        if slot_of is None or len(slot_of) != k:
            slot_of = st["slot_of"] = np.argsort(
                np.argsort(self.p_x[keepers], kind="stable"), kind="stable")
        ox, oy = ox[slot_of], oy[slot_of]
        idx = np.arange(k, dtype=np.float64)
        swing = (
            SEARCH_LOOK_SWING * look
            * np.sin(2 * np.pi * SEARCH_LOOK_HZ * self._phase_t
                     + st["look_phase"] + 0.9 * idx)
        )
        self._keep = {
            "idx": keepers,
            "spacing_px": float(st.get("spacing_px", 0.0)),
            "tx": tx + ox, "ty": ty + oy,
            "speed": float(speed), "seek": seek,
            "look": swing.astype(np.float32),
        }
        self._pre_drop_dart(keepers, ox, oy)

    def _pre_drop_step(self):
        """THE PRE-DROP's clock: read only on a lull TOLD a pre-drop —
        every other frame clears it, so a lull without one is today's,
        byte for byte."""
        if self._phase != "lull" or not pre_drop.told(self._config):
            self._pd_clk = None
            self._pd_dart = None
            return
        self._pd_clk = pre_drop.phase_clock(
            self._config, self._phase, self.phase_progress, self._phase_t,
            prev=self._pd_clk)

    def _pre_drop_dart(self, keepers, ox, oy):
        """On the pre-drop, overwrite the keepers' targets with the dart
        and then the poised coil (PRE_DROP_* above): each keeper's place is
        the centre of view plus its own offset in the row (`ox`, `oy`)."""
        clk = self._pd_clk
        if clk is None or clk.segment != "pre_drop" or self._keep is None:
            return
        k = keepers.size
        sx, sy = max(self.sx, 1e-6), max(self.sy, 1e-6)
        px = self.cam_nx + ox
        py = self.cam_ny + oy
        d_px = np.hypot((px - self.p_x[keepers]) * sx,
                        (py - self.p_y[keepers]) * sy)
        cruise = self.cruise_px
        body = self._body_len_px()
        st = self._pd_dart
        if st is None:
            lo, hi = PRE_DROP_DART_SPEED
            st = self._pd_dart = {
                "t0": self._phase_t, "arrived": None, "phi": None,
                "speed": float(np.clip(float(d_px.max()) / PRE_DROP_DART_S,
                                       lo * cruise, hi * cruise)),
            }
        if st["arrived"] is None and (
                float(d_px.max()) <= max(PRE_DROP_ARRIVE_BODIES * body, 2.0)
                or self._phase_t - st["t0"] > PRE_DROP_DART_MAX_S):
            st["arrived"] = self._phase_t
            st["phi"] = np.arctan2((self.p_y[keepers] - py) * sy,
                                   (self.p_x[keepers] - px) * sx)
        if st["arrived"] is None:
            tx, ty, speed = px, py, st["speed"]
            look = np.zeros(k, np.float32)
        else:
            ea = self._phase_t - st["arrived"]
            r0, r1 = PRE_DROP_COIL_REV
            rev = r0 + (r1 - r0) * min(ea / PRE_DROP_COIL_SETTLE_S, 1.0)
            st["phi"] = st["phi"] + 2.0 * np.pi * rev * float(self.passed_dt)
            rad_px = PRE_DROP_COIL_BODIES * body
            ahead = st["phi"] + PRE_DROP_COIL_LEAD
            tx = px + rad_px * np.cos(ahead) / sx
            ty = py + rad_px * np.sin(ahead) / sy
            speed = 2.0 * np.pi * rad_px * rev
            q0, q1 = PRE_DROP_QUIVER
            amp = q0 + (q1 - q0) * clk.frac
            idx = np.arange(k, dtype=np.float64)
            look = (amp * np.sin(2.0 * np.pi * PRE_DROP_QUIVER_HZ * self._phase_t
                                 + 0.9 * idx)).astype(np.float32)
        self._keep.update(tx=np.asarray(tx, np.float64) * np.ones(k),
                          ty=np.asarray(ty, np.float64) * np.ones(k),
                          speed=float(speed), seek=True, look=look,
                          turn=PRE_DROP_TURN)

    def _start_leg(self, search, gx, gy, left, v, half_px, first):
        """A search leg toward `search["side"]`: the reach point on that
        side of the pond (a little up or down). The first leg goes no
        further than its share of the time left lets a slow fish swim; a
        later one turns round first, so its time allowance carries the
        about-face's own arc (half a turn circle at search speed). A group's
        centre reaches its own half-width less far, so its outermost keeper
        reaches the same point a lone fish would."""
        cnx, cny = self.cam_nx, self.cam_ny
        reach = max(self.search_reach * self.roam_bound
                    - half_px / max(self.sx, 1e-6), 0.0)
        rx = cnx + search["side"] * reach
        ry = cny + float(self._rng.uniform(-1.0, 1.0)) * (
            SEARCH_Y_WANDER * self.roam_bound)
        dx_px, dy_px = (rx - gx) * self.sx, (ry - gy) * self.sy
        dist = float(np.hypot(dx_px, dy_px))
        if first and left is not None:
            cap = v * max(SEARCH_LEG_SHARE * left, SEARCH_LEG_MIN_S)
            if dist > cap > 0.0:
                k = cap / dist
                rx, ry = gx + (rx - gx) * k, gy + (ry - gy) * k
                dist = cap
        turn_s = 0.0 if first else np.pi * self.turn_radius_px / v
        search.update({
            "stage": "go", "t0": self._phase_t, "tx": rx, "ty": ry,
            "limit": (dist / v + turn_s) * SEARCH_LEG_SLACK
            + SEARCH_LEG_SLACK_S,
        })

    def _lull_gone_step(self, p, dt):
        """His clock, in thirds of the lull's own duration: everything gone
        by 1/3, ripples only to 2/3, dark after that until the drop
        (`lull_keep = 0` only — the 2026-10-08 block).

        The thirds are of `phase_progress`, which SpotFX ramps over the real
        gap to the lull's own drop, else the next trigger with no drop ahead
        (`scene_response._phase_ramp_ms`, `spectra/services/phase_partner.py`)
        — so they are thirds of the DYNAMIC lull, never of a wall-clock
        constant. The same honesty note the charge carries applies: that
        ramp covers ~90% of the true gap and then hangs at 1.0, so 1/3
        lands a little before a third of the wall clock. That is the
        closest an effect can get without ever being told the duration.
        """
        st = self._lull_state
        # progress-driven once the ramp moves (hand-scrubbable in the LedFX
        # UI); the wall-clock fallback only runs while progress sits at 0
        f = p if p > 0.0 else min(self._phase_t / LULL_FALL_S, 1.0)
        n = self.n

        # ── 0 -> 1/3: swirl, leak out in rank order, off the panel ──────
        # A leak's moment is a fraction of the lull; its DEADLINE is a time,
        # and the lull never says how long it is — so the rate the progress
        # is actually moving at is read back off the clock (a progress ramp
        # is linear from the phase edge; the wall-clock fallback moves at
        # exactly 1 / LULL_FALL_S) and turned into seconds left.
        rate = f / max(self._phase_t, 1e-3) if f > 0.0 else 1.0 / LULL_FALL_S
        exit_at = LULL_GONE_AT * LULL_EXIT_BY
        disp = np.flatnonzero(self.p_mode[:n] == 4)
        if disp.size:
            rank = self.p_disp[disp]
            ranked = np.isfinite(rank)
            leak_f = np.minimum(
                LULL_GONE_AT * (
                    LULL_LEAK_FROM
                    + np.where(ranked, rank, 0.0)
                    * (LULL_LEAK_TO - LULL_LEAK_FROM)
                ),
                exit_at - LULL_EXIT_MIN_S * rate,
            )
            due = disp[ranked & (f >= leak_f)]
            if due.size:
                self.p_lk[due] = self.t
                self.p_disp[due] = np.nan
            self.p_dl[disp] = self.t + max(exit_at - f, 0.0) / max(rate, 1e-6)
        # ... and the backstop that makes "gone by 1/3" a guarantee rather
        # than a schedule: past the third, nothing is left alive at all.
        if f >= LULL_GONE_AT and n:
            self._compact(np.zeros(n, dtype=bool))

        # ── 1/3 -> 2/3 ripples only, then dark ──────────────────────────
        # A half-life alone can never reach zero, and his ask is DARK — so
        # the wake is RAMPED out across [LULL_DARK_FROM, LULL_DARK_AT] and
        # held at nothing for the last third.
        st["dark"] = float(np.clip(
            (LULL_DARK_AT - f) / max(LULL_DARK_AT - LULL_DARK_FROM, 1e-3),
            0.0, 1.0,
        ))

        # nothing is ever re-spawned mid-lull: the paced dispersal above is
        # the only thing that moves the population, and it only removes
        self.particle_count = 0

    def _settle_rush(self):
        """The rush is over: keep exactly as many fish as the blob-count
        parameter asks for and send the rest on their way. This is what puts
        the population back under its own cap — the nocap tag never outlives
        the moment it was granted for.

        HOW THE STAY-BEHIND HANDS OVER TO THE INTENSITY-DRIVEN COUNT (his
        addendum's own open question). `particle_count` is written live by
        SpotFX and is intensity-bound (1-8 in his scene). The stay-behind
        reads it ONCE, here, at the instant the drop settles — so the number
        that survives is whatever the room's intensity was asking for right
        then. From the very next frame the ordinary population manager
        governs again, unchanged: a later rise lets fish swim in through the
        normal entry path, a later fall departs the excess through the
        normal exit path. There is no special case and nothing to fight —
        the rush sets the population once, at the handover, and the
        intensity-driven count owns it from there.
        """
        n = self.n
        rushing = np.flatnonzero(
            (self.p_mode[:n] == 3) & (self.p_nocap[:n] == 1)
        )
        keep_total = int(self._config["particle_count"])
        already = int(np.count_nonzero(
            (self.p_mode[:n] < 2) & (self.p_nocap[:n] == 0)
        ))
        keep = max(min(keep_total - already, rushing.size), 0)
        if keep:
            # the ones still inside the pond are the natural stayers
            d = np.hypot(
                (self.p_x[rushing] - self.cam_nx) * self.sx,
                (self.p_y[rushing] - self.cam_ny) * self.sy,
            )
            stay = rushing[np.argsort(d)][:keep]
            self.p_mode[stay] = 0
            self.p_nocap[stay] = 0
            leave = np.setdiff1d(rushing, stay)
        else:
            leave = rushing
        self._depart(leave)

    def _release_nocap(self):
        """Send every cap-exempt fish away — used when a phase is abandoned
        so ordinary swimming can never inherit a school or a rush."""
        n = self.n
        extra = np.flatnonzero((self.p_nocap[:n] == 1) & (self.p_mode[:n] < 2))
        self._depart(extra)
        self.p_disp[:n] = np.nan

    def shock_rim(self):
        """The Shockwave's eye (fx/effects/phase_grammar.py): the home ring, centred on the
        window (screen = world - window, so on screen its centre is the
        panel's own cx, cy), in
        render pixels."""
        r = max(float(self.horizon_scale), 0.05)
        return (self.cx, self.cy, r * self.sx, r * self.sy)

    def _drop_step(self):
        """The drop he likes, plus his addendum's three beats — RUSH IN,
        SWIRL AROUND, STAY BEHIND. Nothing about the existing payoff (the
        boost, the ejecta explosion, the settle horizon, the self-reset)
        is changed; the rush is laid on top of it.

        THE DROP FOLLOWS THE MUSIC (2026-10-08, his ask: "make the length of
        the drop and how fast the fish swirl depend on the intensity of the
        music so that lower intensity songs don't have such a prolonged
        rush"). SpotFX tells the drop arm the fire's intensity
        (`drop_intensity`, fx/effects/lull_handoff.py); `lull_handoff.
        drop_scale` turns it into one multiple — the automatic ceiling 0.75
        is exactly the fixed drop, a marked track at 1.0 runs 20% longer, a
        quiet song shrinks toward `drop_scale_min` — applied to the settle
        horizon (so the swirl, which decays over it, follows), the boost and
        the rush's entry speed (by half). Not told: the fixed constants,
        expression for expression. The ejecta keep their fixed fade."""
        drop = self._drop_state
        if drop is None:
            drop = self._drop_state = {"burst_done": False, "settled": False}
        drop.setdefault("settled", False)
        if not drop["burst_done"]:
            drop["burst_done"] = True
            drop["scale"] = lull_handoff.drop_scale(
                lull_handoff.drop_intensity(self._config),
                self.drop_scale_min,
            )
            self._release_nocap()
            self.particle_count = int(self._config["particle_count"])
            n = self.n
            tracked = int(np.count_nonzero(
                (self.p_mode[:n] < 2) & (self.p_nocap[:n] == 0)
            ))
            missing = self.particle_count - tracked
            rush = int(min(self.rush_count, MAX_RUSH))
            if rush > 0:
                # BEAT 1 — RUSH IN. The rush is now what repopulates a drop
                # (his "the scene exits a drop already populated instead of
                # repopulating from nothing"), so the centre burst stands
                # down while it runs. With the rush turned off the drop is
                # exactly what it was.
                scale = drop.get("scale")
                if scale is None:
                    self._spawn_rush(rush)
                else:
                    self._spawn_rush(rush, speed_x=0.5 + 0.5 * scale)
            elif missing > 0:
                self._spawn_center_burst(
                    self.cam_nx, self.cam_ny, missing
                )
            # the explosion: 2x more fish that DON'T stay — they bolt
            # straight off the panel during the boost window
            self._spawn_drop_ejecta(DROP_EJECTA_X * self.particle_count)
            self._shock_begin()
        scale = drop.get("scale")
        if scale is None:
            settle_s, boost = DROP_SETTLE_S, DROP_BOOST
        else:
            settle_s, boost = DROP_SETTLE_S * scale, DROP_BOOST * scale
        self._speed_scale = 1.0 + boost * max(
            1.0 - self._phase_t / settle_s, 0.0
        )
        # BEAT 2 — SWIRL AROUND, for the drop's own duration. `_rush_swirl`
        # is read by the steering block; it is a tangential bias on the
        # rush fish only, bounded by the same turn-rate clamp as every other
        # steering term, so it can never flip one on the spot.
        surge = min(self._phase_t / max(self.rush_time, 0.05), 1.0)
        self._rush_swirl = surge * (
            1.0 - min(self._phase_t / settle_s, 1.0)
        )
        if self._phase_t >= settle_s:
            if not drop["settled"]:
                # BEAT 3 — STAY BEHIND, per the blob count. See
                # _settle_rush for how that hands over to the
                # intensity-driven count.
                drop["settled"] = True
                self._rush_swirl = 0.0
                self._settle_rush()
            self._phase = "none"
            self._drop_state = None
            self._speed_scale = 1.0
            # sanctioned in-render config path (under the effect lock);
            # self-reset so an identical later drop write edges again
            # (the told intensity is forgotten with it, so a later drop
            # that is not told runs the fixed drop, never this one's scale)
            self._apply_config(
                {"phase": "none", "phase_progress": 0.0,
                 lull_handoff.DROP_KEY: 0.0},
                validate=False,
                fire_event=False,
            )

    def _pond_rest_step(self, n, dt, eligible, ordinary, target, cruise,
                        spike, jump_eff):
        """THE POND REST (the block of that name at the top of the module):
        update the quiet level, startle it on a strong hit, then ask the
        ordinary swimmers for less and run their darts. `ordinary` and
        `target` are the (speed ease's, tail drive's) targets before and
        after this frame's moments (a flee, a burst, a solo dash). Returns
        the two targets to use: the ordinary share rested, every moment's
        share kept whole and a dart's push raised, for eligible fish only."""
        want, want_tail = target
        vol = self._rest_vol if self._rest_vol is not None else REST_UNHEARD
        if (self._rest_heard is not None
                and self.t - self._rest_heard > REST_SILENCE_S):
            vol = 0.0
        state = self._rest if self._rest is not None else (vol, vol, 0.0)
        slow, fast, level = rest_step(
            state, vol, dt, self.rest_calm_level, self.rest_full_level
        )
        # the startle: a strong hit cuts the rest by its own size at once
        if spike >= LUNGE_SPIKE_MIN and jump_eff > 0.0:
            level *= 1.0 - min(float(spike), 1.0)
        if self._rest_held(n):
            level = 0.0
        self._rest = (slow, fast, level)
        rest = level * float(self.quiet_rest)
        self._rest_level = rest
        self._darting = self._rest_free = None
        if rest <= 0.0:
            # awake, or held: no dart flies, and the clocks start again when
            # the rest comes back
            if np.isfinite(self.p_dhd[:n]).any() or self.p_dnext[:n].any():
                self._end_darts(n)
            return want, want_tail
        thrust, steer = self._dart_step(n, dt, eligible, rest)
        self._darting = steer
        lunge = self.p_lun[:n]
        keep = 1.0 - rest * (1.0 - REST_SPEED_X)
        # the fins never brake a fish a dart pushes or a moment drives
        free = eligible & (want > ordinary[0])
        if thrust is not None:
            free |= thrust
        self._rest_free = free if free.any() else None

        def asked(base, moved):
            # the beat's own share (the lunge) and a moment's are never
            # scaled: only the ordinary swimming comes to rest
            rested = base / (1.0 + lunge) * (keep + lunge) + (moved - base)
            if thrust is not None:
                rested = np.where(thrust, np.maximum(rested, cruise * DART_X),
                                  rested)
            return np.where(eligible, rested, moved)
        want = asked(ordinary[0], want)
        if want_tail is not None:
            want_tail = asked(ordinary[1], want_tail)
        return want, want_tail

    def _rest_held(self, n):
        """THE POND REST is held at 0: a charge, lull or drop, a formed
        school, a rush, a WORD SHAPE, or a crossfade on either side of this
        effect (a transition program running into it included)."""
        return (
            self._phase != "none"
            or self._word_shape_holds()
            or self._school_on
            or bool((self.p_mode[:n] == 3).any())
            or getattr(self, "_transition_program", None) is not None
            or particle_handoff.transition_progress(self._virtual) is not None
        )

    def _end_darts(self, n):
        """No dart in flight, and every dart clock unset."""
        self.p_dart[:n] = 0.0
        self.p_dhd[:n] = np.nan
        self.p_dnext[:n] = 0.0

    def _dart_step(self, n, dt, eligible, rest):
        """The resting fish's dart clocks (THE POND REST's block), on the
        darts' own generator. Returns (thrusting, steering): the fish a dart
        pushes this frame, and the fish still turning toward their dart's
        heading — each None when there are none."""
        if self._dart_rng is None:
            # spawned, never drawn from: the shared stream is untouched and
            # a seeded effect darts the same way every run
            self._dart_rng = self._rng.spawn(1)[0]
        rng = self._dart_rng
        flying = np.isfinite(self.p_dhd[:n])
        if flying.any():
            # the push runs its own few tenths of a second (`p_dart` > 0);
            # the turn carries on through the glide (`p_dart` <= 0) until the
            # fish faces the dart's heading or DART_STEER_S has passed
            self.p_dart[:n] = np.where(flying, self.p_dart[:n] - dt, 0.0)
            off = np.abs(_wrap_pi(
                self.p_hd[:n] - np.nan_to_num(self.p_dhd[:n])))
            done = flying & (self.p_dart[:n] <= 0.0) & (
                (off < DART_FACE) | (self.p_dart[:n] <= -DART_STEER_S))
            if done.any():
                self.p_dart[:n][done] = 0.0
                self.p_dhd[:n][done] = np.nan
        due_at = self.p_dnext[:n]
        extra = max(float(self.dart_every_s) - DART_MIN_S, 0.1)
        resting = eligible & (rest > REST_DART_AT)
        if resting.any():
            unset = resting & (due_at <= 0.0)
            if unset.any():
                due_at[unset] = self.t + DART_MIN_S + rng.exponential(
                    extra, int(unset.sum()))
            due = resting & (self.t >= due_at) & ~np.isfinite(
                self.p_dhd[:n])
            if due.any():
                idx = np.flatnonzero(due)
                self.p_dart[idx] = DART_S * rng.uniform(0.6, 1.4, idx.size)
                lo, hi = DART_TURN
                turn = rng.uniform(lo, hi, idx.size) * rng.choice(
                    [-1.0, 1.0], idx.size)
                self.p_dhd[idx] = (self.p_hd[idx] + turn).astype(np.float32)
                due_at[idx] = self.t + DART_MIN_S + rng.exponential(
                    extra, idx.size)
        else:
            # too awake to dart: the clocks start again when it rests
            due_at[eligible] = 0.0
        thrusting = eligible & (self.p_dart[:n] > 0.0)
        steering = eligible & np.isfinite(self.p_dhd[:n])
        return (thrusting if thrusting.any() else None,
                steering if steering.any() else None)

    def _decay_tail_kick(self, n, dt):
        """The beat envelope decays every frame tail_drive is on, whether or
        not any fish is eligible to stroke from it this frame — a kick
        armed just before a school forms (the charge gates `pulse_eligible`
        off for its whole duration) must not freeze and survive, unaged,
        into the fish that resumes ordinary swimming after the drop."""
        self.p_tkick[:n] *= np.float32(0.5 ** (dt / TAIL_BEAT_HL))

    def _tail_drive_step(self, eligible, want_tail, prev, dt, cruise, spike,
                         jump_eff, weight, tau, tau_ordinary):
        """THE TAIL DRIVE's controller and thrust law (the block of that name
        at the top of the module), for every eligible fish: decide stroke or
        glide, ease the tail toward the stroke that effort asks for, push
        with the tail's CURRENT motion, lose speed to drag. `p_spd` (already
        eased the old way this frame) becomes the blend `weight` of the two.
        `tau`/`tau_ordinary` are this frame's speed ease and the ordinary
        one, so a quick moment stays quick (TAIL_STIFF_MAX's block).
        """
        n = eligible.size
        idx = np.flatnonzero(eligible)
        # the beat envelope: a strong beat arms it where the lunge arms, and
        # a fish strokes while it is up
        if spike >= LUNGE_SPIKE_MIN and jump_eff > 0.0:
            beat = min(jump_eff * float(spike), TAIL_BEAT_MAX)
            self.p_tkick[idx] = np.maximum(self.p_tkick[idx], beat)
        self._decay_tail_kick(n, dt)
        kick = self.p_tkick[idx]

        fc = max(float(self.flap_rate), 0.05)
        drag = float(self.glide_drag)
        lin = drag * TAIL_DRAG_LINEAR_SHARE
        quad = drag - lin
        k_thrust = drag / (fc * fc)
        v = prev[idx] / cruise
        effort = np.maximum(want_tail[idx] / cruise, 0.0)
        below = float(self.glide_below)
        if below > 0.0:
            band = TAIL_GLIDE_BAND * np.clip(1.0 - effort / below, 0.0, 1.0)
        else:
            band = np.zeros_like(effort)

        # stroke or glide: start below the band (or on a beat); stop above it,
        # never before half a stroke and never while a beat is up
        stroking = self.p_tst[idx] > 0.5
        phase = self.p_flap[idx]
        half_done = ((phase - self.p_tph0[idx]) % (2 * np.pi * 64)) >= np.pi
        start = ~stroking & ((v < effort * (1.0 - band)) | (kick > TAIL_BEAT_ON))
        stop = (
            stroking & (band > 0.02) & (v > effort * (1.0 + band))
            & half_done & (kick <= TAIL_BEAT_ON)
        )
        stroking = (stroking | start) & ~stop
        self.p_tph0[idx] = np.where(start, phase, self.p_tph0[idx])
        self.p_tst[idx] = stroking.astype(np.float32)

        # the stroke this effort asks for: continuous above glide_below, a
        # harder bout below it
        e_s = np.where(
            effort >= below, effort,
            np.clip(TAIL_BOUT_GAIN * effort, effort, below),
        )
        f_s = fc * (0.4 + 0.6 * e_s)
        a_s = (
            np.sqrt(np.maximum(quad * e_s * e_s + lin * e_s, 0.0) / drag)
            * fc / np.maximum(f_s, 1e-3)
        )
        capped = a_s > TAIL_AMP_MAX
        f_s = np.where(capped, f_s * a_s / TAIL_AMP_MAX, f_s)
        a_s = np.minimum(a_s, TAIL_AMP_MAX)
        a_cmd = np.where(stroking, a_s, TAIL_AMP_GLIDE)
        f_cmd = np.where(stroking, f_s, fc * TAIL_FREQ_GLIDE)
        amp = self.p_tamp[idx]
        tau_a = np.where(a_cmd > amp, TAIL_AMP_UP_S, TAIL_AMP_DOWN_S)
        amp = amp + (a_cmd - amp) * np.minimum(1.0, dt / tau_a)
        freq = self.p_tf[idx]
        freq = np.where(freq <= 0.0, f_cmd, freq)
        freq = freq + (f_cmd - freq) * min(1.0, dt / TAIL_FREQ_S)
        self.p_tamp[idx] = amp.astype(np.float32)
        self.p_tf[idx] = freq.astype(np.float32)

        # the push, from the tail's CURRENT motion: it peaks mid-sweep, where
        # the tail tip moves fastest
        tip = phase - SPINE_WAVE * 2.0 * np.pi
        quick = tau[idx] < tau_ordinary[idx]
        # ... except in a quick moment, whose strokes come too fast to tell
        # apart: it pushes with their mean, so a dash starts on its trigger
        push = np.where(quick, 1.0, 2.0 * np.cos(tip) ** 2)
        thrust = k_thrust * (amp * freq) ** 2 * push
        stiff = np.where(
            quick,
            np.clip(
                1.0 / (2.0 * quad * np.abs(v) + lin)
                / np.maximum(tau[idx], 1e-3),
                1.0, TAIL_STIFF_MAX,
            ),
            1.0,
        )
        if self._rest_level > 0.0:
            # THE POND REST: the fins brake, except on a fish a dart pushes
            # or a moment drives
            brake = REST_BRAKE * self._rest_level
            free = self._rest_free
            if free is not None and free.size == n:
                lin = lin + np.where(free[idx], 0.0, brake)
            else:
                lin = lin + brake
        v = (v + stiff * thrust * dt) / (
            1.0 + stiff * (quad * np.abs(v) + lin) * dt
        )
        v_tail = np.maximum(v, 0.0) * cruise
        # `weight` is a SCALAR on every frame but one under a WORD SHAPE,
        # where the tail hands over per fish (the WORD SHAPES block), so the
        # scalar branches below are the only ones an untold frame reaches.
        if np.ndim(weight):
            w = np.asarray(weight, dtype=np.float32)[idx]
            self.p_spd[idx] = (
                (1.0 - w) * self.p_spd[idx] + w * v_tail
            ).astype(np.float32)
        elif weight >= 1.0:
            self.p_spd[idx] = v_tail.astype(np.float32)
        else:
            self.p_spd[idx] = (
                (1.0 - weight) * self.p_spd[idx] + weight * v_tail
            ).astype(np.float32)

    def _tail_drive_flap(self, eligible, flap_amp, flap_freq, half_w, weight):
        """The drawn flap for every tail-driven fish: the tail drive's own
        size and stroke rate (the numbers its thrust came from), blended by
        `weight` with the flap read off the speed."""
        base = self.flap_amount * half_w * self.body_aspect
        n = eligible.size
        amp_t = base * self.p_tamp[:n]
        freq_t = np.where(self.p_tf[:n] > 0.0, self.p_tf[:n], flap_freq)
        if np.ndim(weight) or weight < 1.0:
            # an ARRAY weight is a WORD SHAPE's per-fish hand-over; a scalar
            # one is everything else, and 1.0 keeps today's expression
            amp_t = (1.0 - weight) * flap_amp + weight * amp_t
            freq_t = (1.0 - weight) * flap_freq + weight * freq_t
        return (np.where(eligible, amp_t, flap_amp),
                np.where(eligible, freq_t, flap_freq))

    def _solo_burst_step(self, n, dt, mode):
        """THE SOLO BURST (see the block at the top of the module): advance
        every live envelope, then, on the Poisson clock, start one on a
        random fish that qualifies."""
        sb = self.p_sb[:n]
        held = self.p_sb_t[:n] > 0.0
        if held.any() or sb.any():
            self.p_sb_t[:n] = np.maximum(self.p_sb_t[:n] - dt, 0.0)
            rise = np.minimum(sb + dt / SOLO_ATTACK_S, 1.0)
            fall = sb * np.float32(0.5 ** (dt / SOLO_FALL_S))
            sb = np.where(held, rise, np.where(fall < 0.01, 0.0, fall))
            self.p_sb[:n] = sb
        quiet = self._phase == "none" and self._scatter is None
        if self.solo_burst_rate <= 0.0 or not quiet:
            self._solo_due = 0.0
            return
        if self._rng.random() < self.solo_burst_rate / 60.0 * dt:
            self._solo_due = min(self._solo_due + 1.0, SOLO_DUE_MAX)
        if self._solo_due < 1.0:
            return
        ok = np.flatnonzero(
            (mode == 0) & (self.p_nocap[:n] == 0) & (sb <= 0.0)
            & (self.p_sb_t[:n] <= 0.0) & (self.p_wurg[:n] < SOLO_WALL_FREE)
        )
        if ok.size == 0 or self._school_on:
            return
        pick = int(self._rng.choice(ok))
        self.p_sb_t[pick] = float(self.solo_burst_time)
        self._solo_due -= 1.0
        self.solo_bursts += 1

    # ── WORD SHAPES (the block of that name at the top of the module) ───
    def _word_shape_told(self):
        """Read the told keys off a config write and leave draw() an edge.

        THE SEQ, NEVER THE ID (word_shape_keys.py): two words of the same
        shape back to back both edge. CREATION BASELINE, the fireworks
        `burst_rockets` rule: a fresh instance built from a persisted config
        carrying a stale SEQ must NOT fire, so the first read only
        remembers the number it saw. A write that tells NOTHING while a
        shape is running is a CLEARING write — it releases from where the
        shape has got to rather than snapping it away.

        Runs on the writer's own thread (`config_updated`), which is also
        where the geometry lookup belongs: `word_shapes.get` is cheap, but
        it is not the render thread's work. Nothing lazy is PRIMED here on
        purpose — this effect reads only `at()`/`tangent()`, whose tables
        `build()` already made, and `prime()` would build the ~200 ms
        `sdf_fast` grid Fish never looks at.
        """
        told = word_shape_keys.told(self._config)
        seq = int(self._config.get(word_shape_keys.SEQ_KEY, 0) or 0)
        if not hasattr(self, "_ws_seen"):
            self._ws_seen = seq
            self._ws_told = told
            return
        was, self._ws_told = self._ws_told, told
        if told is not None and seq != self._ws_seen:
            self._ws_seen = seq
            shape = word_shapes.get(told.shape)
            self._ws_pending = ("start", told, shape)
            return
        self._ws_seen = seq
        if told is None and was is not None:
            self._ws_pending = ("clear", None, None)

    def _word_shape_table(self, shape):
        """The monotonic bearing -> place map for one shape, built once and
        kept: a fish's own bearing from the centre of view answers with the
        place on the outline that bearing points at.

        Read in the fish's own NORMALIZED space, which is the shape's own
        space up to one scale per axis (`sx` and `sy` both carry
        `radius_scale`), so the two angles are literally the same angle and
        this needs no panel geometry. Monotonic because every shipped shape
        is star-shaped about its centre — the library measures that, it is
        not assumed here."""
        cached = self._ws_table
        if cached is not None and cached[0] is shape:
            return cached[1], cached[2]
        s = np.linspace(0.0, 1.0, WS_OUTLINE_SAMPLES, endpoint=False)
        ux, uy = shape.at(s)
        ang = np.unwrap(np.arctan2(uy, ux))
        if ang[-1] < ang[0]:
            ang, s = ang[::-1].copy(), s[::-1].copy()
        self._ws_table = (shape, ang, s)
        return ang, s

    def _word_shape_size_n(self):
        """The shape's half-height in the fish's OWN normalized units.

        `word_shape_size` is a fraction of the PANEL's half-height in the
        -1..1 space every Twod effect works in; this effect's `sx`/`sy`
        carry `radius_scale` on top of that (do_once), so one panel
        half-height is `1 / radius_scale` of a fish's normalized unit. Both
        axes share the factor, which is what keeps the drawn shape the
        panel's own aspect — about 14% wider than tall on his crystal,
        exactly as every circle here is (the word-shapes skill)."""
        return float(self.word_shape_size) / max(float(self.radius_scale), 1e-6)

    def _word_shape_loop_px(self, shape, size_n):
        """The outline's length in SCREEN px at the size it is drawn — the
        denominator of the procession's pace. A fact about the outline AS
        DRAWN, so it depends on the drawn size and on the panel's own
        `sx`/`sy`; hence the cache key."""
        key = (id(shape), round(float(size_n), 6), float(self.sx),
               float(self.sy))
        cached = self._ws_loop
        if cached is not None and cached[0] == key:
            return cached[1]
        s = np.linspace(0.0, 1.0, WS_OUTLINE_SAMPLES, endpoint=False)
        ux, uy = shape.at(s)
        dx = np.diff(np.append(ux, ux[0])) * size_n * self.sx
        dy = np.diff(np.append(uy, uy[0])) * size_n * self.sy
        loop_px = float(np.hypot(dx, dy).sum())
        self._ws_loop = (key, loop_px)
        return loop_px

    def _word_shape_reset(self):
        """Forget the shape and every place on it. Nothing writes a told key
        back (word_shape_keys.py's contract): the effect simply stops
        reading them."""
        self._ws = None
        self._ws_wall = None
        self.p_ws_s[:] = np.nan
        self.p_ws_rank[:] = np.nan

    def _word_shape_speed_x(self, m):
        """ROW W5.5's FIRST LEVER — the procession's pace multiplier for THIS
        frame, `1 + (x - 1) * m` from the registered `word_shape_speed_x`.

        His words for the row, 2026-11-18: *"Oribits is really good at
        showing shape, we need to get Fish to behave similarly"*, and
        Orbits' own W4.4 verdict underneath it: *"They need to increase
        speed so they can pass the outline fast enough that their trail
        stays and it clearly forms the shape."* The arithmetic is the
        WS_SPEED_X block's: the revisit gap (`loop_s / n`) against the
        trail's own half-life decides whether a procession reads as a line.

        FOUR QUANTITIES TAKE IT, and they have to take it together or the
        law stops being one law:

          * the LINE'S OWN MARCH (`st["march"]`), so the lap really is
            `loop_s / x` seconds long and the places the fish hold station
            against move at the pace they are asked to swim;
          * the PROCESSION'S PACE (`pace`), the px/s that keeps a fish on
            its own place — it is the loop's length over its lap time, and
            the lap time is what this divides;
          * the DASH CAP (`WS_DASH_X * cruise`), which is an ABSOLUTE
            ceiling in px/s: left alone it binds at x3 (the heart's pace
            goes 21 -> 64 px/s against a 44 px/s cap) and the fish would
            fall behind a line it can never catch. Scaled, the cap keeps
            exactly the headroom over the pace it has today — 2.04x either
            way, since pace and cap both scale — so the approach still
            lands on the word;
          * the PHASE EASE (`WS_PHASE_GAIN`), which is in loop fractions a
            second: scaled, the line closes a common-mode lag in the same
            number of LAPS at any speed.

        `WS_SPACING_GAIN` needs nothing — it is a multiplier ON the pace
        already. RAMPED BY THE ENVELOPE, which is his standing rule ("they
        need to smoothly accelerate and not have sudden velocity shifts"):
        the acceleration is continuous, x1 at both ends, and the pace is
        his own again by the release's end."""
        return 1.0 + (float(self.word_shape_speed_x) - 1.0) * float(m)

    def _word_shape_step(self, dt, n, mode, cruise):
        """One frame of THE PROCESSION. None on every frame no shape runs —
        and then not one expression in draw() below differs from today's,
        which is what makes an untold frame byte for byte what it is now.

        Returns the state draw() steers, paces and brightens by:
          m        the told envelope (word_shape_keys.envelope), 0..1
          grip     the loop's own authority (word_shape_grip)
          idx      the fish on the loop this frame
          m_fish   (n,) the envelope per fish, 0 for every fish not on it
          tx, ty   each of `idx`'s target, in normalized world units
          want     each of `idx`'s speed target, px/s
          few      the latched mode (his Q10 A, as revised for Fish)
          trace    the loop arc to lay into the water this frame, or None
          speed_x  row W5.5's pace multiplier this frame (1 untold-adjacent,
                   up to `word_shape_speed_x` at the hold)
        """
        pend, self._ws_pending = self._ws_pending, None
        if pend is not None:
            kind, told, shape = pend
            if kind == "start" and shape is not None:
                was = self._ws
                # A SECOND WORD MID-SHAPE RESTARTS THE FORM FROM WHERE IT
                # IS (acceptance 7), never from zero: the clock starts at
                # the time that already reads the fraction standing.
                frac = 0.0
                if was is not None:
                    frac = float(word_shape_keys.envelope(
                        was["t"], was["told"].form_s, was["told"].hold_s,
                        was["told"].release_s))
                self._ws = {
                    "told": told, "shape": shape,
                    "t": word_shape_restart_t(frac, told.form_s),
                    "few": None, "loop_s": 0.0, "loop_px": 0.0,
                    "assigned": False, "age": 0.0, "march": 0.0,
                    "line_phase": 0.0, "place": None,
                }
            elif kind == "clear" and self._ws is not None:
                st = self._ws
                frac = float(word_shape_keys.envelope(
                    st["t"], st["told"].form_s, st["told"].hold_s,
                    st["told"].release_s))
                st["t"] = word_shape_release_t(
                    frac, st["told"].form_s, st["told"].hold_s,
                    st["told"].release_s)
        st = self._ws
        if st is None:
            self._ws_wall = None
            return None
        told = st["told"]
        st["t"] += dt
        if st["t"] > told.total_s:
            self._word_shape_reset()
            return None
        t = st["t"]
        m = float(word_shape_keys.envelope(
            t, told.form_s, told.hold_s, told.release_s))
        grip = word_shape_grip(
            t, told.form_s, told.hold_s, told.release_s)
        # ROW W5.5's pace multiplier, read once a frame beside the envelope
        # it is ramped by (`_word_shape_speed_x` is the binding statement).
        speed_x = self._word_shape_speed_x(m)

        # WHO IS ON THE LOOP. Ordinary swimmers only: a formed school, the
        # drop's rush, its ejecta, the lull's keepers and a dispersing fish
        # are authored choreography (or already leaving), and a scattering
        # instance is on its way off the panel.
        on = (mode < 2) & (self.p_nocap[:n] == 0)
        if self._school_on or self._scatter is not None:
            on = np.zeros(n, dtype=bool)
        shape = st["shape"]
        size_n = self._word_shape_size_n()
        cnx, cny = self.cam_nx, self.cam_ny

        if not st["assigned"]:
            idx0 = np.flatnonzero(on)
            if idx0.size == 0:
                self._ws_wall = None
                return None
            ang, s_tab = self._word_shape_table(shape)
            bearing = np.arctan2(self.p_y[idx0] - cny, self.p_x[idx0] - cnx)
            entry, rank = word_shape_entries(
                bearing, ang, s_tab, WS_ENTRY_MIN_GAP / idx0.size)
            self.p_ws_s[:n] = np.nan
            self.p_ws_rank[:n] = np.nan
            self.p_ws_s[idx0] = entry
            self.p_ws_rank[idx0] = rank
            few = idx0.size <= int(self.word_shape_few)
            st.update(
                assigned=True, few=few,
                loop_s=WS_LOOP_S_FEW if few else WS_LOOP_S_MANY,
                loop_px=self._word_shape_loop_px(shape, size_n),
                # the common phase the even spacing is measured from: the
                # one that moves the line least, so easing to even spacing
                # never drags a fish the long way round
                phase0=float(np.angle(np.exp(
                    2j * np.pi * (entry - rank / idx0.size)).mean())
                    / (2.0 * np.pi)),
                count=int(idx0.size),
            )

        placed = on & np.isfinite(self.p_ws_s[:n])
        idx = np.flatnonzero(placed)
        m_fish = np.where(placed, np.float32(m), np.float32(0.0))
        # THE WALL IS PAUSED, by m: its glance starts later and, while it
        # still has authority at all, flies the tightest arc THE CLAMP IN
        # FORCE allows rather than a wide sweep. Row W5.5 relaxed both the
        # arc (WS_WALL_TURN_X) and the FLOOR (the third member) the same way
        # the fish's own circle is relaxed — the wall's glance overrides the
        # loop's steer while it runs, so a floor left at the fish's own
        # 4.5 px circle rounds a star's notch wide of the line near the
        # pond's edge however tight the shape's circle is. Still floored:
        # "tightened WITHIN the clamp", on the same tighter clamp.
        self._ws_wall = (
            self.wall_lookahead * (1.0 - WS_WALL_LOOK_CUT * m),
            1.0 + (WS_WALL_TURN_X - 1.0) * m,
            max(1.0 - (1.0 - WS_TURN_X) * m, 1e-3),
        )
        if idx.size == 0:
            return {"m": m, "grip": grip, "idx": idx, "m_fish": m_fish,
                    "tx": None, "ty": None, "want": None,
                    "few": bool(st["few"]), "trace": None,
                    "speed_x": speed_x}

        # ── where each fish is going ────────────────────────────────────
        st["age"] += dt
        # THE MARCH IS PACED BY THE ENVELOPE TOO: the line barely moves on
        # the first frames of the form and is circling at full pace by the
        # word, so a fish swims onto (very nearly) its own entry instead of
        # chasing a place that has already run a third of the loop.
        direction = -1.0 if self.reverse else 1.0
        # ROW W5.5: the lap is `loop_s / x` long while the shape stands —
        # `_word_shape_speed_x` is the binding statement for the four
        # quantities that take the multiplier together.
        st["march"] += m * speed_x * dt / max(st["loop_s"], 1e-3)
        k = max(int(st["count"]), 1)
        entry = self.p_ws_s[idx]
        rank = self.p_ws_rank[idx]
        even = st["phase0"] + rank / k
        # the entries ease to EVEN spacing, each fish keeping its order:
        # the shortest way round, on a smoothstep so the easing never adds
        # a velocity step of its own
        w = min(st["age"] / WS_SPACE_EASE_S, 1.0)
        w = w * w * (3.0 - 2.0 * w)
        delta = (even - entry + 0.5) % 1.0 - 0.5
        place = (
            entry + delta * w
            + direction * (st["march"] + st["line_phase"])
        ) % 1.0
        prev = st["place"]
        st["place"] = (place, idx.size)

        # EACH FISH'S OWN PLACE ON THE LOOP, read from its bearing through
        # the same table its entry came from — exact once it is on the line,
        # and before then it is the outline point on its own bearing, which
        # IS its entry. The target is a short arc ahead of THAT (never
        # further than WS_REACH, see that block), so the chord the fish
        # swims is always a few pixels long and it follows the line round a
        # corner instead of cutting across it; how far it is behind its
        # station is answered by its SPEED below, never by its aim.
        ang, s_tab = self._word_shape_table(shape)
        lo = float(ang[0])
        bearing = np.arctan2(self.p_y[idx] - cny, self.p_x[idx] - cnx)
        s_fish = np.interp(lo + (bearing - lo) % (2.0 * np.pi), ang, s_tab)
        s_fish = s_fish % 1.0
        lag = direction * (((place - s_fish) + 0.5) % 1.0 - 0.5)
        aim = np.clip(lag, -WS_REACH, WS_REACH) + WS_TARGET_LEAD
        # ROW W6.1: ... and never shorter than WS_AIM_STEP_X of this fish's
        # own frame step, converted from px into the loop's own arc by the
        # loop's measured length (that constant's block). The floor goes on
        # the WHOLE aim and not on the lead alone, because a fish AHEAD of
        # its station has `lag` negative: at the shipped numbers
        # `-WS_REACH + WS_TARGET_LEAD` is exactly ZERO, which aims a fish
        # at its own place and makes the direction to it meaningless.
        aim = np.maximum(aim, WS_AIM_STEP_X * self.p_spd[idx] * dt
                         / max(float(st["loop_px"]), 1e-3))
        # ... and never more than a QUARTER of the loop ahead, whatever the
        # frame. The floor above is `speed * dt`, and `dt` is capped at
        # DT_MAX (0.1 s), so one stalled frame at the shaped dash cap would
        # otherwise ask for 0.55 of the loop — past the halfway point,
        # where "ahead" wraps round and the aim points BEHIND the fish.
        # Normal frames are 0.04-0.06, so this never binds in play.
        aim = np.minimum(aim, 0.25)
        target_s = (s_fish + direction * aim) % 1.0
        ux, uy = shape.at(target_s)
        tx = cnx + ux * size_n
        ty = cny + uy * size_n

        # ── how fast ────────────────────────────────────────────────────
        # The procession's own pace is the loop's length over its lap time,
        # corrected by how far the fish is BEHIND its own station (`lag`).
        # That correction is what holds the line together: at the pace
        # alone a lag is never closed, since a fish and its station move at
        # the same speed.
        # On the APPROACH it may run `dist / time_left` up to WS_DASH_X x
        # cruise so it is on the line by the word, eased back to the pace
        # over the form's last stretch so the word itself is never a step.
        pace = st["loop_px"] / max(st["loop_s"], 1e-3) * speed_x
        # the LINE'S phase takes the common-mode lag (read next frame — one
        # frame of lag on a 1.5/s ease is nothing), each fish's speed only
        # its own share against its neighbours
        common = float(np.mean(lag))
        st["line_phase"] -= (
            WS_PHASE_GAIN * speed_x * dt
            * min(max(common, -WS_PHASE_MAX), WS_PHASE_MAX))
        slots = np.clip((lag - common) * k, -1.0, WS_SLOT_LAG_MAX)
        station = pace * np.maximum(
            1.0 + WS_SPACING_GAIN * slots, WS_PACE_MIN)
        dist = np.hypot((tx - self.p_x[idx]) * self.sx,
                        (ty - self.p_y[idx]) * self.sy)
        left = told.form_s - t
        if left > 0.0:
            need = dist / max(left, WS_MIN_LEFT_S)
            u = min(max(left / WS_DASH_SETTLE_S, 0.0), 1.0)
            u = u * u * (3.0 - 2.0 * u)
            want = station + (np.maximum(need, station) - station) * u
        else:
            want = station
        want = np.minimum(want, WS_DASH_X * cruise * speed_x)

        # ── THE WATER TRACE (P2 A), few fish only ───────────────────────
        # One deposit per fish per frame at the loop point its own PLACE has
        # reached — the loop, not the fish, so the line glows even while a
        # fish is still swimming onto it, and never ahead of its own place.
        # A place moves about a pixel a frame at row W5.5's own lap (0.4 at
        # x1), against a splat WS_TRACE_SIZE_BODY of a body across — 4.3 px
        # on his Fish — so a per-frame splat still paints a continuous line
        # exactly the way the fish's own tail deposit does, under exactly
        # that deposit's own per-frame rule; WS_TRACE_MAX_ARC (0.08 of the
        # loop, against the 0.009 a frame of the fastest shipped lap) is
        # the guard against a frame so long (or a restart) that the step
        # would be a dotted line instead.
        trace = None
        if (st["few"] or WS_TRACE_MANY) and m > 0.0:
            step = 0.0
            if prev is not None and prev[1] == idx.size:
                step = float(np.max(np.abs(
                    (place - prev[0] + 0.5) % 1.0 - 0.5)))
            if step <= WS_TRACE_MAX_ARC:
                lx, ly = shape.at(place)
                trace = (
                    self.cx + (cnx + lx * size_n) * self.sx - self.cam_px,
                    self.cy + (cny + ly * size_n) * self.sy - self.cam_py,
                    idx,
                )
        return {"m": m, "grip": grip, "idx": idx, "m_fish": m_fish,
                "tx": tx, "ty": ty, "want": want,
                "few": bool(st["few"]), "trace": trace,
                "speed_x": speed_x}

    def _word_shape_revisit_gap(self, m):
        """ROW W6.1 — HOW LONG A POINT ON THE OUTLINE WAITS between one
        fish and the next, in seconds: the lap time over the number of fish
        on the loop, at this frame's own pace multiplier.

        This is the quantity Orbits' W4.4 finding is about and the one
        `WS_TRAIL_GAP_X` floors the two half-lives at — 0.61 s with his
        three fish on the heart at x3, 0.39 s with six. The COUNT and the
        LAP are both the LATCHED ones (`st["count"]`, `st["loop_s"]`, set
        once when the entries are assigned), so a fish leaving mid-shape
        cannot step the floor: 0 before the entries exist, which is what
        makes the floor inert on those frames."""
        ws = self._ws
        if ws is None:
            return 0.0
        loop_s = float(ws.get("loop_s") or 0.0)
        if loop_s <= 0.0:
            return 0.0
        k = max(int(ws.get("count") or 0), 1)
        return loop_s / (k * max(self._word_shape_speed_x(m), 1e-3))

    def _trail_half_life(self):
        """The body trail's half-life. HIS NOTE on the Word Shapes build:
        "We may need to boost the trail brightness and lower decay briefly
        to get it to show better" — so under a shape the half-life eases
        from the authored `trail_decay`'s own value toward its end of
        WS_TRAIL_HALF_LIFE_S — the (FEW, MANY) pair, chosen by the latched
        mode, OVER ROW W5.5's OWN PACE MULTIPLIER, because the pair is a
        smear LENGTH and the lap is that much faster (that constant's own
        block) — and back, by the told envelope. `trail_decay` itself is
        NEVER written: the scaling is the quantity it drives, so the
        release's end restores his value exactly and no new param exists."""
        half_life = 0.02 + self.trail_decay * 0.5
        ws = self._ws
        if ws is None:
            return half_life
        m = float(word_shape_keys.envelope(
            ws["t"], ws["told"].form_s, ws["told"].hold_s,
            ws["told"].release_s))
        if m <= 0.0:
            return half_life
        few, many = WS_TRAIL_HALF_LIFE_S
        want = few if ws.get("few") else many
        # THE DIVISION GOES ON THE BLEND, NOT THE TARGET. Blending toward
        # `want / x` instead would make the half-life NON-MONOTONIC in `m`
        # (it peaks 0.233 s around m = 0.5 against 0.200 at the hold,
        # because the target falls faster than the blend climbs); blending
        # first and dividing after makes the SMEAR LENGTH — the half-life
        # times the pace — follow W1.4's own ramp exactly, since
        # `(h + m (F - h)) / x * x` is that ramp by construction.
        life = ((half_life + m * (want - half_life))
                / self._word_shape_speed_x(m))
        # ROW W6.1's FLOOR: the smear outlives the revisit gap, which is
        # what makes the outline WHOLE for a moment rather than merely lit
        # (WS_TRAIL_GAP_X's own block — Orbits' persistence, ported). Ramped
        # by `m` so the first frame of the form is still his own value.
        return max(life, m * WS_TRAIL_GAP_X * self._word_shape_revisit_gap(m))

    def _trail_gain(self):
        """The body's deposit brightness into the trail — 1.0 untold, up to
        WS_TRAIL_GAIN under a full shape (his "boost the trail
        brightness"). It goes in through `_clip_body_layer`'s own
        hue-preserving ceiling, so a brighter smear is never a whiter
        one."""
        ws = self._ws
        if ws is None:
            return 1.0
        m = float(word_shape_keys.envelope(
            ws["t"], ws["told"].form_s, ws["told"].hold_s,
            ws["told"].release_s))
        return 1.0 + m * (WS_TRAIL_GAIN - 1.0)

    def _wake_half_life(self):
        """The wake's half-life. Under a shape the water keeps a trace of
        the loop for the whole hold (P2 A), which is `ripple_life` eased
        toward WS_RIPPLE_LIFE_S over row W5.5's own pace multiplier (a
        LENGTH, like the trail's pair — that constant's block) by the told
        envelope, floored at row W6.1's revisit gap, and back down over the
        release — the authored value never written.

        STILL FEW-FISH ONLY: row W6.1 measured W1.4's scoping reason
        against its own bar 4 and it SURVIVED — extending the trace to MANY
        (`WS_TRACE_MANY`, False) moved the band filled 0.0 points and cost
        five of white, because with six fish the revisit gap is already
        0.39 s and the floored body trail covers it. That constant's own
        block carries the table."""
        life = float(self.ripple_life)
        half = None
        ws = self._ws
        if ws is not None and (ws.get("few") or WS_TRACE_MANY):
            m = float(word_shape_keys.envelope(
                ws["t"], ws["told"].form_s, ws["told"].hold_s,
                ws["told"].release_s))
            if m > 0.0:
                # on the BLEND, not the target — `_trail_half_life`'s own
                # reason, the same arithmetic
                life = ((life + m * (WS_RIPPLE_LIFE_S - life))
                        / self._word_shape_speed_x(m))
                # ... AND ROW W6.1's SAME FLOOR, read on the HALF-LIFE this
                # returns rather than on `life` (the two differ by
                # WAKE_HALF_LIFE_X): the trace is what carries the line
                # between the FEW fish, so it has to outlive the gap for
                # the same reason the trail does.
                half = max(
                    life * WAKE_HALF_LIFE_X,
                    m * WS_TRAIL_GAP_X * self._word_shape_revisit_gap(m))
        if half is None:
            half = life * WAKE_HALF_LIFE_X
        return max(half, 0.02)

    def _word_shape_holds(self):
        """Whether the paused features are held this frame (the PAUSES
        paragraph of the WORD SHAPES block): a swim burst, the big fish and
        the pond rest do not START while a shape is running. One already in
        flight finishes."""
        pend = self._ws_pending
        if pend is not None and pend[0] == "start":
            return True
        ws = self._ws
        if ws is None:
            return False
        return float(word_shape_keys.envelope(
            ws["t"], ws["told"].form_s, ws["told"].hold_s,
            ws["told"].release_s)) > WS_PAUSE_AT

    def _pond_distance(self, x, y):
        """Signed distance (SCREEN px, positive inside) from points to the
        pond's own ellipse (`roam_scale`), and its unit inward normal. The
        pond is centred on the window, which in screen space never moves.
        First-order (the algebraic distance over its gradient): exact on the
        ellipse itself, which is the only place a steer reads it closely."""
        a = max(self.roam_bound * self.sx, 1e-3)
        b = max(self.roam_bound * self.sy, 1e-3)
        ex = x - self.cx
        ey = y - self.cy
        r = np.sqrt((ex / a) ** 2 + (ey / b) ** 2)
        gx = ex / (a * a)
        gy = ey / (b * b)
        g = np.maximum(np.hypot(gx, gy), 1e-9)
        d = np.where(r > 1e-4, (1.0 - r) * r / g, min(a, b))
        return d, -gx / g, -gy / g

    def _wall_landing(self, x, y, free=None):
        """Where a glance lands, as a signed distance (SCREEN px, positive
        inside) at points (x, y) with its unit inward normal: the nearer of
        the pond (it bounds the middle) and the lit silhouette pulled in by
        WALL_GRAZE half-widths with its corners rounded (`_landing`; it
        bounds the flank). See the WALL block. Where `free` (broadcast
        against x) is True the pond is left out — a fish getting out of a
        big fish's way may use the whole lit panel (the BIG_AVOID block)."""
        grow = max(float(self.roam_scale), 1.0)
        ox = (self.r_width - 1) / 2.0
        oy = (self.r_height - 1) / 2.0
        d_sil, snx, sny = _sample_field(
            self._landing(), ox + (x - ox) / grow, oy + (y - oy) / grow
        )
        d_sil = d_sil * grow
        d_pond, pnx, pny = self._pond_distance(x, y)
        pond = d_pond < d_sil
        if free is not None:
            pond = pond & ~np.asarray(free, dtype=bool)
        return (
            np.where(pond, d_pond, d_sil),
            np.where(pond, pnx, snx),
            np.where(pond, pny, sny),
        )

    def _landing(self):
        """The landing line's field (see `_landing_field`): the silhouette
        pulled in WALL_GRAZE half-widths, its corners rounded to the arc this
        fish sweeps a wall on — never more than WALL_ROUND_FIT of the room
        the inset shape has, or a small panel would round away to nothing."""
        hw = self._half_width_px()
        inset = WALL_GRAZE * hw / max(float(self.roam_scale), 1.0)
        room = float(self._wall[0].max()) - inset
        rho = min(float(self._glance_radius(
            np.float32(np.pi / 2), np.float32(0.0), own_floor=True)),
            WALL_ROUND_FIT * max(room, 0.0))
        return _landing_field(self._wall, inset, rho)

    def _glance_radius(self, theta, speed, own_floor=False):
        """The arc (px) a fish wants to sweep in alongside the wall on,
        meeting it at angle `theta` (radians, 0 = parallel) at `speed` px/s:
        the tightest that keeps its nose no deeper past the wall than its
        own flank lands (R_nose), never tighter than the TURN CIRCLE IN
        FORCE or the distance it swims in `wall_lookahead` seconds, over
        `wall_turn_strength`. See the WALL block.

        `own_floor=True` reads the fish's OWN turn radius as the floor
        whatever a shape is doing — two callers want that and neither is
        steering: `_landing`'s corner rounding (how a long BODY rounds a
        panel corner, and a per-frame rho would thrash `_landing_field`'s
        cache) and `_wall_steer`'s probe reach (only ever safer wider)."""
        hw = self._half_width_px()
        half = hw * self.body_aspect
        give = hw * WALL_NOSE_GIVE
        r_nose = np.maximum.accumulate(
            (half * np.sin(WALL_PHI) - give) / (1.0 - np.cos(WALL_PHI))
        )
        k = np.clip(
            np.searchsorted(WALL_PHI, theta, side="right") - 1,
            0, WALL_PHI.size - 1,
        )
        # WORD SHAPES (the block of that name): while a shape runs the
        # look-ahead shortens, the arc tightens and — since row W5.5 — the
        # floor relaxes onto the SHAPED circle, all three by the told
        # envelope. `None` is every other frame, where these are
        # `self.wall_lookahead` and two literal 1.0s, so the expression is
        # exactly what it was, and `own_floor` keeps the fish's own radius
        # for the two callers that are not steering.
        look_s, turn_x, floor_x = self.wall_lookahead, 1.0, 1.0
        if self._ws_wall is not None:
            look_s, turn_x, shaped = self._ws_wall
            floor_x = 1.0 if own_floor else shaped
        want = np.maximum(
            r_nose[k], look_s * np.maximum(speed, 0.0)
        ) / (max(float(self.wall_turn_strength), 1e-3) * turn_x)
        return np.maximum(
            want, self.turn_radius_px * floor_x).astype(np.float32)

    def _wall_run(self, px, py, dx, dy, s, free=None):
        """How far each middle at (px, py) can swim straight along (dx, dy)
        before it meets the landing line (px; the probe's own length when it
        never does)."""
        g, _, _ = self._wall_landing(
            px[:, None] + dx[:, None] * s[None, :],
            py[:, None] + dy[:, None] * s[None, :],
            free=free,
        )
        below = g < 0.0
        first = np.where(below.any(axis=1), below.argmax(axis=1), s.size - 1)
        return s[first]

    def _wall_steer(self, n, hd, active, dt=1.0 / 60.0):
        """THE WALL (see the block at the top of the module). For each of
        the first `n` fish, returns:
          urgency    0..1 — 0.5 the frame a glance starts, 1 once it is late
                     (or its middle is already past the landing line)
          turn       signed curvature command, as a fraction of the fish's
                     own tightest turn (+ = counter-clockwise)
          authority  0..1 — how much of the other steering it overrides
          toward     True where it is heading into the wall within reach
        A fish leaves the wall alone until the arc that would land it
        alongside (R = f * cot(theta/2)) has shrunk to the arc it wants
        (`_glance_radius`), flies that arc in, then peels WALL_PEEL away."""
        urgency = np.zeros(n, dtype=np.float32)
        turn = np.zeros(n, dtype=np.float32)
        authority = np.zeros(n, dtype=np.float32)
        toward = np.zeros(n, dtype=bool)
        self.p_wurg[:n] = 0.0
        idx = np.flatnonzero(active)
        if idx.size == 0 or self._wall is None:
            self.p_wsg[:n] = 0.0
            self.p_wr[:n] = 0.0
            self.p_wph[:n] = np.nan
            eased_turn, eased_auth = self._wall_ease(n, turn, authority, dt)
            return self._wall_release(n, active, urgency, eased_turn,
                                      eased_auth, toward)

        r_min = self.turn_radius_px
        hw = self._half_width_px()
        spd = np.maximum(self.p_spd[idx], 0.0)
        px = self.cx + self.p_x[idx] * self.sx - self.cam_px
        py = self.cy + self.p_y[idx] * self.sy - self.cam_py
        h = hd[idx]
        hx = np.cos(h)
        hy = np.sin(h)
        held = np.maximum(self.p_wr[idx], r_min)

        # the path straight ahead, out to the furthest landing that could
        # still matter: the widest arc any of them wants, met head-on (the
        # landing is then f = R tan(theta/2) <= R away), with WALL_HOLD of
        # room for a turn already under way
        widest = max(
            float(self._glance_radius(
                np.full(idx.size, np.pi / 2, np.float32), spd,
                own_floor=True).max()),
            float(held.max()),
        )
        reach = widest * WALL_HOLD + WALL_STEP_PX
        steps = max(int(np.ceil(reach / WALL_STEP_PX)), 2)
        s = np.linspace(0.0, reach, steps + 1).astype(np.float32)
        # a fish getting out of a big fish's way glances off the lit panel
        # only, not the pond (the BIG_AVOID block); None for everyone else
        free = getattr(self, "_pond_free", None)
        free = None if free is None else free[idx][:, None]
        g, nx, ny = self._wall_landing(
            px[:, None] + hx[:, None] * s[None, :],
            py[:, None] + hy[:, None] * s[None, :],
            free=free,
        )
        below = g < 0.0
        hit = below.any(axis=1)
        rows = np.arange(idx.size)
        j = np.where(hit, below.argmax(axis=1), 0)
        jl = np.maximum(j - 1, 0)
        g_lo = g[rows, jl]
        g_hi = g[rows, j]
        # f: how far along its heading the middle meets the landing line
        f = np.where(
            j > 0,
            s[jl] + (s[j] - s[jl]) * g_lo / np.maximum(g_lo - g_hi, 1e-6),
            0.0,
        )
        n_x = nx[rows, j]
        n_y = ny[rows, j]
        theta = np.arcsin(np.clip(-(hx * n_x + hy * n_y), -1.0, 1.0))
        past = hit & (j == 0)

        want = self._glance_radius(theta, spd)
        r_need = np.where(
            theta > 1e-4,
            f * (1.0 + np.cos(theta)) / np.maximum(np.sin(theta), 1e-6),
            np.inf,
        )
        prev = self.p_wsg[idx]
        committed = prev != 0.0
        approaching = hit & ~past & (theta > WALL_ON)

        # the phases: a turn under way flies its arc in to the wall; once
        # its angle to the wall is down to WALL_OFF (or it no longer sees
        # that wall ahead) it is ALONGSIDE and carries on WALL_PEEL further
        # on the same arc before letting go. A new wall ahead while it peels
        # away (the next side of a corner) starts a fresh glance.
        landed_at = self.p_wph[idx]
        alongside = committed & ~np.isnan(landed_at)
        arriving = committed & ~alongside
        inbound = (
            arriving & hit & ~past & (theta > WALL_OFF)
            & (r_need <= WALL_HOLD * held)
        )
        lands = arriving & ~inbound & ~past
        landed_at = np.where(lands, h, landed_at)
        turned = np.where(
            np.isnan(landed_at), 0.0, prev * _wrap_pi(h - landed_at)
        )
        peeling = (alongside | lands) & (turned < WALL_PEEL) & ~past
        start = (
            (~committed | (alongside & ~lands)) & approaching
            & (r_need <= want)
        )
        peeling = peeling & ~start
        # a middle past the landing line, heading out (or not yet WALL_BACK
        # back in): turn back in
        back = past & (theta > -WALL_BACK)
        keep = inbound | peeling
        engaged = start | keep | back

        # which way: toward the water — the turn that swings its heading
        # onto the wall's own line without sweeping through the wall (|h x n|
        # is cos(theta)). Within WALL_TIE of dead-on either way is as short,
        # so it takes the way with more wall to sweep along.
        cross = hx * n_y - hy * n_x
        fresh = np.where(cross >= 0.0, 1.0, -1.0).astype(np.float32)
        tie = engaged & (np.abs(cross) < np.sin(WALL_TIE))
        if tie.any():
            ti = np.flatnonzero(tie)
            tx = -n_y[ti]
            ty = n_x[ti]
            fti = None if free is None else free[ti]
            room_a = self._wall_run(px[ti], py[ti], tx, ty, s, free=fti)
            room_b = self._wall_run(px[ti], py[ti], -tx, -ty, s, free=fti)
            # the + side ends on whichever tangent is counter-clockwise of
            # its heading
            a_is_plus = (hx[ti] * ty - hy[ti] * tx) >= 0.0
            plus_room = np.where(a_is_plus, room_a, room_b)
            minus_room = np.where(a_is_plus, room_b, room_a)
            fresh[ti] = np.where(plus_room >= minus_room, 1.0, -1.0)
        side = np.where(keep, prev, fresh).astype(np.float32)
        radius = np.where(start, want, held)
        # in: the curvature that lands it from where it is now (a late fish,
        # or the next side of a corner, turns tighter); peeling away: the
        # arc it chose; back in from past the line: its glance arc, firmer
        # the deeper past it the middle is
        depth = np.maximum(-g[:, 0], 0.0) / max(hw, 1e-3)
        arc = np.where(peeling, radius, r_need)
        cmd = np.where(
            back,
            np.clip(r_min / want * (1.0 + WALL_BACK_FIRM * depth), 0.0, 1.0),
            np.clip(r_min / np.maximum(arc, 1e-3), 0.0, 1.0),
        )
        urg = np.where(
            back, 1.0,
            np.where(approaching | inbound,
                     np.clip(0.5 * np.where(inbound, held, want)
                             / np.maximum(r_need, 1e-3), 0.0, 1.0),
                     0.0),
        )
        fi = idx
        self.p_wsg[:n] = 0.0
        self.p_wr[:n] = 0.0
        self.p_wph[:n] = np.nan
        self.p_wsg[fi] = np.where(engaged, side, 0.0)
        self.p_wr[fi] = np.where(engaged, radius, 0.0)
        self.p_wph[fi] = np.where(peeling, landed_at, np.nan)
        self.p_wurg[fi] = urg
        urgency[fi] = urg
        turn[fi] = np.where(engaged, cmd * side, 0.0)
        authority[fi] = np.where(engaged, 1.0, 0.0)
        toward[fi] = (hit & (theta > 0.0)) | back
        eased_turn, eased_auth = self._wall_ease(
            n, turn, authority, dt, urgency
        )
        return self._wall_release(n, active, urgency, eased_turn, eased_auth,
                                  toward)

    def _wall_release(self, n, active, urgency, turn, authority, toward):
        """A fish that stops swimming (it disperses, rushes, is ejected)
        lets go of the wall at once rather than easing out of a turn: its
        own steering takes over this frame, not WALL_FALL_S later."""
        gone = ~np.asarray(active[:n], dtype=bool)
        if gone.any():
            self.p_wcmd[:n][gone] = 0.0
            self.p_wauth[:n][gone] = 0.0
            turn = np.where(gone, 0.0, turn)
            authority = np.where(gone, 0.0, authority)
        return urgency, turn, authority, toward

    def _wall_ease(self, n, turn, authority, dt, urgency=None):
        """The turn and authority the wall APPLIES: its plan, eased per fish
        — WALL_FALL_S down; WALL_RISE_S up while the wall is still far,
        shrinking to nothing as it gets close (WALL_LATE), so the ease can
        smooth a turn but never make one late."""
        if urgency is None:
            urgency = np.zeros(n, dtype=np.float32)
        far = np.clip((1.0 - urgency) / (1.0 - WALL_LATE), 0.0, 1.0)
        rise = np.maximum(WALL_RISE_S * far, 1e-4)
        out = []
        for applied, want in ((self.p_wcmd, turn), (self.p_wauth, authority)):
            cur = applied[:n]
            rising = np.abs(want) > np.abs(cur)
            tau = np.where(rising, rise, WALL_FALL_S)
            cur += (want - cur) * np.minimum(dt / tau, 1.0)
            out.append(cur.copy())
        return tuple(out)

    def _disperse_speed(self, n, cruise):
        """The swim speed a leaking fish needs to be off the panel by its
        own deadline: the SCREEN distance from where it is, straight out
        from the centre of view, past the panel edge by a body length (the
        same line `draw` retires it on), over the time it has left — with
        the arc allowance, the cruise floor and the streak ceiling. Every
        fish's own number, every frame, so it re-plans as it goes."""
        px = self.cx + self.p_x[:n] * self.sx - self.cam_px
        py = self.cy + self.p_y[:n] * self.sy - self.cam_py
        ox = px - self.cx
        oy = py - self.cy
        d = np.hypot(ox, oy)
        hd = self.p_hd[:n]
        ux = np.where(d > 1e-3, ox / np.maximum(d, 1e-3), np.cos(hd))
        uy = np.where(d > 1e-3, oy / np.maximum(d, 1e-3), np.sin(hd))
        m = self._body_len_px() + DISPERSE_OFF_MARGIN
        w1 = self.r_width - 1 + m
        h1 = self.r_height - 1 + m
        with np.errstate(divide="ignore", invalid="ignore"):
            tx = np.where(ux > 1e-6, (w1 - px) / ux,
                          np.where(ux < -1e-6, (-m - px) / ux, np.inf))
            ty = np.where(uy > 1e-6, (h1 - py) / uy,
                          np.where(uy < -1e-6, (-m - py) / uy, np.inf))
        d_out = np.maximum(np.minimum(tx, ty), 0.0)
        # ... but the fish travels along its HEADING, not along that line: a
        # fish skimming an edge sideways is not "3 px from gone". Measure the
        # way out along its heading too, and never credit it with less than
        # the outward distance, nor charge it more than that plus the half
        # turn that would line it up.
        hx, hy = np.cos(hd), np.sin(hd)
        with np.errstate(divide="ignore", invalid="ignore"):
            hx_t = np.where(hx > 1e-6, (w1 - px) / hx,
                            np.where(hx < -1e-6, (-m - px) / hx, np.inf))
            hy_t = np.where(hy > 1e-6, (h1 - py) / hy,
                            np.where(hy < -1e-6, (-m - py) / hy, np.inf))
        d_hd = np.maximum(np.minimum(hx_t, hy_t), 0.0)
        dist = np.clip(d_hd, d_out, d_out + np.pi * self.turn_radius_px)
        left = np.maximum(self.p_dl[:n] - self.t, DISPERSE_MIN_LEFT_S)
        need = dist * DISPERSE_PATH_X / left
        ceiling = max(self.r_width, self.r_height) * DISPERSE_MAX_PANELS_S
        return np.clip(
            np.maximum(need, cruise * DISPERSE_MIN_X), 0.0,
            max(ceiling, cruise * DISPERSE_MIN_X),
        ).astype(np.float32)

    # ── the window ──────────────────────────────────────────────────────
    def _step_camera(self, dt, cruise):
        """Move the window toward the school, or ease it back to rest.

        Three bounds hold structurally, not by tuning:

        * it only ever FOLLOWS — the target is the school's own centroid, so
          the window has no motion of its own to invent;
        * its velocity is eased (`CAM_VEL_TAU`) and capped
          (`CAM_MAX_SPEED_X` x cruise), so no beat turn, rush or lunge can
          whip the view;
        * the whole frame's movement, leash correction included, is capped
          to that same speed x dt, so there is one number bounding a
          per-frame step and nothing can teleport.

        `camera_follow = 0` returns before touching anything: the window
        never leaves the origin, and world == screen.
        """
        self._cam_px_prev = self.cam_px
        self._cam_py_prev = self.cam_py
        if self.camera_follow <= 0.0:
            return
        # ONLY the charge and the lull move the window — and a lull only
        # while there is still a school in it. Since the 2026-09-16
        # dispersal the lull turns every fish into a DISPERSING one (mode 4)
        # on its first frame, so there is nothing to follow from the moment
        # the swirl starts and the window EASES HOME instead of holding
        # wherever the charge left it; the swirl, the leak and the ripples
        # all play out against a settling view.
        active = self._phase in ("charge", "lull")
        if active and self._phase == "lull" and not np.any(
            self.p_mode[: self.n] < 2
        ):
            active = False
        n = self.n
        # The school is the fish that have ARRIVED. A charge spawns its
        # shoal a whole entry radius behind the window and they swim in
        # over a second or more; counting them would drag the target out
        # to where they are, not to where the school is.
        live = np.empty(0, dtype=np.int64)
        if active:
            live = np.flatnonzero(self.p_mode[:n] == 0)
            if live.size:
                # ... and, of those, THE ONES IT CAN SEE. A rush stayer
                # converted from mode 3 lands wherever it had got to, a
                # whole entry radius off-window; letting it into the mean
                # would send the window off after it. Following only what
                # is on the panel also makes "the school is never lost"
                # structural: the target is inside the window by
                # construction, so the lag is the only thing that can put
                # the school off-centre, and the lag is capped.
                seen = live[
                    (np.abs(self.p_x[live] * self.sx - self.cam_px)
                     <= (self.r_width - 1) / 2.0)
                    & (np.abs(self.p_y[live] * self.sy - self.cam_py)
                       <= (self.r_height - 1) / 2.0)
                ]
                if seen.size:
                    live = seen
            else:
                live = np.flatnonzero(self.p_mode[:n] < 2)
        if active and live.size:
            tx = float(np.mean(self.p_x[live])) * self.sx
            ty = float(np.mean(self.p_y[live])) * self.sy
        elif active:
            tx, ty = self.cam_px, self.cam_py     # nothing to follow: hold
        else:
            tx = ty = 0.0                          # ease home

        cap = max(CAM_MAX_SPEED_X * cruise, 1e-3)
        want_vx = (tx - self.cam_px) / max(CAM_TAU, 1e-3)
        want_vy = (ty - self.cam_py) / max(CAM_TAU, 1e-3)
        sp = float(np.hypot(want_vx, want_vy))
        if sp > cap:
            want_vx *= cap / sp
            want_vy *= cap / sp
        ease = min(1.0, dt / max(CAM_VEL_TAU, 1e-3))
        self.cam_vx += (want_vx - self.cam_vx) * ease
        self.cam_vy += (want_vy - self.cam_vy) * ease
        sp = float(np.hypot(self.cam_vx, self.cam_vy))
        if sp > cap:
            self.cam_vx *= cap / sp
            self.cam_vy *= cap / sp
        cam_x = self.cam_px + self.cam_vx * dt
        cam_y = self.cam_py + self.cam_vy * dt

        # the leash: the window may lag as far as it likes, but it may never
        # LOSE the school. This only ever reduces the error, and it is capped
        # with everything else immediately below.
        if active and live.size:
            # radial, against the panel's SHORT half-axis, so the bound
            # means the same thing whichever way the school travels
            leash = CAM_LEASH * min(
                (self.r_width - 1) / 2.0, (self.r_height - 1) / 2.0
            )
            ox, oy = tx - cam_x, ty - cam_y
            off = float(np.hypot(ox, oy))
            if off > leash:
                k = (off - leash) / off
                cam_x += ox * k
                cam_y += oy * k

        step_cap = cap * dt
        dxp = cam_x - self.cam_px
        dyp = cam_y - self.cam_py
        step = float(np.hypot(dxp, dyp))
        if step > step_cap:
            k = step_cap / step
            cam_x = self.cam_px + dxp * k
            cam_y = self.cam_py + dyp * k
        self.cam_px = float(cam_x)
        self.cam_py = float(cam_y)
        if (
            not active
            and abs(self.cam_px) < CAM_REST_EPS
            and abs(self.cam_py) < CAM_REST_EPS
        ):
            # back to rest EXACTLY, never on a residue
            self.cam_px = self.cam_py = 0.0
            self.cam_vx = self.cam_vy = 0.0

    # ── render primitives ───────────────────────────────────────────────
    def _splat_many(self, buf, xs, ys, rgb, sizes):
        """Additively stamp soft dots of PER-POINT size and colour.

        One vectorized pass over every point instead of Orbits' per-particle
        loop — a fish is a chain of splats, so the point count is an order
        of magnitude higher and a Python loop would dominate the frame."""
        if xs.size == 0:
            return
        max_size = float(np.max(sizes))
        if not np.isfinite(max_size) or max_size <= 0:
            return
        keep = self.k_dist <= max_size
        k_dx = self.k_dx[keep]
        k_dy = self.k_dy[keep]
        k_dist = self.k_dist[keep]
        if k_dx.size == 0:
            return
        xi = np.round(xs).astype(np.int32)
        yi = np.round(ys).astype(np.int32)
        px = (xi[:, None] + k_dx[None, :]).ravel()
        py = (yi[:, None] + k_dy[None, :]).ravel()
        w = np.clip(
            1.0 - k_dist[None, :] / (sizes[:, None] + 0.5), 0.0, 1.0
        ).ravel()
        valid = (
            (px >= 0) & (px < self.r_width)
            & (py >= 0) & (py < self.r_height)
            & (w > 0.0)
        )
        if not valid.any():
            return
        idx = (py * self.r_width + px)[valid]
        w = w[valid]
        cells = self.r_width * self.r_height
        for channel in range(3):
            cw = np.repeat(rgb[:, channel], k_dx.size)[valid]
            buf[..., channel] += np.bincount(
                idx, weights=w * cw, minlength=cells
            ).reshape(self.r_height, self.r_width)

    # ── the wake ────────────────────────────────────────────────────────
    def _wake_palette(self):
        """Resolve the wake's colour rule for the CURRENT gradient.

        Returns `(is_solid, grad_offset, dim)`. The decision is read off the
        BUILT gradient curve, never the config string, so a "gradient" whose
        stops all resolve to one colour is correctly treated as solid — see
        the WAKE COLOUR block at the top of this module for the rule. A real
        gradient's offset is `wake_hue`'s (own / neighbour / opposite).
        """
        self._assert_gradient()
        curve = self._gradient_curve
        if curve is None or curve.size == 0:
            return True, 0.0, WAKE_SOLID_DIM
        spread = float(
            np.max(np.max(curve, axis=1) - np.min(curve, axis=1))
        ) / 255.0
        if spread <= WAKE_SOLID_TOL:
            return True, 0.0, WAKE_SOLID_DIM
        return False, WAKE_HUE_OFFSETS[self.wake_hue], 1.0

    def _step_wake(self, dt):
        """Decay, EXPAND, and carry the buffer with the water.

        Three things happen, in this order and no other:

        1. WORLD ANCHORING. The buffer is screen space; the water is not.
           Every frame it is rolled by exactly the displacement the
           world->screen mapping moved — the current's own flow, minus the
           window's own step — with the sub-pixel remainder carried. What
           rolls off an edge is dropped, never wrapped.
        2. DECAY, exactly Orbits' trail: an exponential half-life.
        3. EXPANSION, the half of his ask a decaying buffer alone cannot
           give: a 3-tap separable blur blended in at a rate set by
           `ripple_spread`, so every deposit opens outward as it dims. This
           is why nothing needs to draw a growing shape, and why there is no
           outline left to read as a messy circle.
        """
        if self.wake is None:
            return
        shift_x = self._flow_px * dt - (self.cam_px - self._cam_px_prev)
        shift_y = self._flow_py * dt - (self.cam_py - self._cam_py_prev)
        self._wake_ox += shift_x
        self._wake_oy += shift_y
        rx = int(self._wake_ox)
        ry = int(self._wake_oy)
        if rx:
            self._wake_ox -= rx
            self.wake = np.roll(self.wake, rx, axis=1)
            if rx > 0:
                self.wake[:, :rx, :] = 0.0
            else:
                self.wake[:, rx:, :] = 0.0
        if ry:
            self._wake_oy -= ry
            self.wake = np.roll(self.wake, ry, axis=0)
            if ry > 0:
                self.wake[:ry, :, :] = 0.0
            else:
                self.wake[ry:, :, :] = 0.0

        half_life = self._wake_half_life()
        self.wake *= np.float32(0.5 ** (dt / half_life))

        a = float(np.clip(
            WAKE_EXPAND_K * float(self.ripple_spread) * dt,
            0.0, WAKE_EXPAND_MAX,
        ))
        if a > 0.0:
            w = self.wake
            blur = (w + np.roll(w, 1, axis=1) + np.roll(w, -1, axis=1)) / 3.0
            blur = (
                blur + np.roll(blur, 1, axis=0) + np.roll(blur, -1, axis=0)
            ) / 3.0
            # the wrapped rows/columns a roll brings back are not water:
            # zero them so the smear never re-enters from the far edge
            blur[0, :, :] = 0.0
            blur[-1, :, :] = 0.0
            blur[:, 0, :] = 0.0
            blur[:, -1, :] = 0.0
            self.wake *= np.float32(1.0 - a)
            self.wake += (blur * np.float32(a)).astype(np.float32)

    def _deposit_wake(self, xs, ys, amp, sizes, grad):
        """Lay this frame's soft splats into the wake buffer.

        A FILLED dot with a linear falloff (`_splat_many`, the same primitive
        every body segment uses), never a ring — his "the circle line is kind
        of messy" is answered by there being no line at all.
        """
        if self.wake is None or xs.size == 0:
            return
        is_solid, offset, dim = self._wake_palette()
        if not is_solid:
            grad = (grad + offset) % 1.0
        rgb = self.get_gradient_color_vectorized1d(grad).astype(np.float32)
        rgb = rgb * (amp * dim)[:, None]
        self._splat_many(self.wake, xs, ys, rgb, sizes)

    # ── outgoing collapse (radial incoming) ─────────────────────────────
    def _draw_collapse(self, dt):
        """Outgoing gather: every fish spirals into the incoming radial's
        centre, pinching bright. Mirrors Orbits' own collapse so the
        radial's bloom lands identically whichever of the two it replaces."""
        col = self._collapse
        n = self.n
        self._rest_level = 0.0      # nothing swims here, so nothing rests
        self._darting = self._rest_free = None
        frac = particle_handoff.transition_progress(self._virtual)
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
            p2 = min(
                max((t - particle_handoff.COLLAPSE_FALLBACK_S) / 0.5, 0.0),
                1.0,
            )
        e = s_ * s_ * (3.0 - 2.0 * s_)

        half_life = self._trail_half_life()
        self.trail *= np.float32(0.5 ** (dt / half_life))

        if n:
            k = min(len(col["rho0"]), n)
            rho = col["rho0"][:k] * (1.0 - s_) ** 2 + 0.05 * e
            phi = (
                col["phi0"][:k]
                + col["spin"] * 2.0 * np.pi
                * (particle_handoff.SWIRL_TURNS * e + 0.35 * p2)
            )
            x = col["tx"] + rho * np.cos(phi)
            y = col["ty"] + rho * np.sin(phi)
            bright = np.minimum(
                col["bright0"][:k] * (1.0 + 0.6 * e), 1.0
            ) * (1.0 - p2)
            self.p_bright[:k] = bright
            # they keep pointing where they are travelling as they spiral
            hd = phi + col["spin"] * np.pi / 2.0
            self.p_x[:k] = x
            self.p_y[:k] = y
            self.p_hd[:k] = hd
            frame = np.zeros_like(self.trail)
            self._draw_bodies(
                frame,
                np.arange(k),
                x, y, hd, bright,
                np.full(k, self._half_width_px(), dtype=np.float32),
                np.zeros(k, dtype=np.float32),
                col["grad0"][:k],
                use_trail=False,
            )
            np.maximum(self.trail, np.minimum(frame, 255.0), out=self.trail)
            self.p_x0[:k] = x
            self.p_y0[:k] = y

        # the collapse composites no wake, so the big fish lays none
        big = self._big_fish_layer(dt, self.trail, wake=False)
        self._composite(self.trail, None, big)

    def _trail_points(self, idx, px, py, d):
        """Points walked back along each fish's recorded path, in SCREEN
        space. `px`/`py` are the fish's current screen centres (shape k);
        `d` (shape k x m) is the path distance behind the centre of each
        point wanted. The chain is [current point, trail[0], trail[1],
        ...], lying at path distances [0, acc, acc + BODY_TRAIL_STEP_PX,
        acc + 2x, ...] behind the centre — `acc` (`p_trail_acc`) being
        exactly how far the fish has travelled since trail[0] was laid (see
        the push in draw()). A point at distance d is linearly interpolated
        between whichever two chain points bracket it. The ONE definition
        both `_draw_bodies`'s rear spine nodes and `_trail_tail_point`'s
        wake deposit read, so the wake and the drawn tail cannot disagree
        about where the tail is."""
        trail_x = self.cx + self.p_trail_x[idx] * self.sx - self.cam_px
        trail_y = self.cy + self.p_trail_y[idx] * self.sy - self.cam_py
        chain_x = np.concatenate([px[:, None], trail_x], axis=1)
        chain_y = np.concatenate([py[:, None], trail_y], axis=1)
        acc = self.p_trail_acc[idx][:, None]
        first = d <= acc
        idx_f = np.clip(
            (d - acc) / BODY_TRAIL_STEP_PX, 0.0, BODY_TRAIL_LEN - 1 - 1e-4
        )
        floor_j = np.floor(idx_f).astype(np.int32)
        near_j = np.where(first, 0, floor_j + 1)
        frac = np.clip(
            np.where(first, d / np.maximum(acc, 1e-6), idx_f - floor_j),
            0.0, 1.0,
        )
        rows = np.arange(len(idx))[:, None]
        near_x = chain_x[rows, near_j]
        far_x = chain_x[rows, near_j + 1]
        near_y = chain_y[rows, near_j]
        far_y = chain_y[rows, near_j + 1]
        return (
            near_x + (far_x - near_x) * frac,
            near_y + (far_y - near_y) * frac,
        )

    def _trail_tail_point(self, idx, x, y, length):
        """The TRUE tail point (SCREEN space): the `SPINE_U=1.0` node of
        `_draw_bodies`, i.e. `_trail_points` at `d = length/2`. The wake
        deposit (below) lays its smear here, so it sits at the body's own
        curved tail during a turn instead of the old rigid heading
        projection, and in the same world->screen mapping the body is drawn
        in, so it sits under its fish while the window moves. No heading
        needed — that is the whole point of a trail-based point."""
        px = self.cx + x * self.sx - self.cam_px
        py = self.cy + y * self.sy - self.cam_py
        tail_x, tail_y = self._trail_points(
            idx, px, py, (length * 0.5)[:, None]
        )
        return tail_x[:, 0], tail_y[:, 0]

    def _draw_bodies(self, frame, idx, x, y, hd, bright, half_w, flap_amp,
                     grad, use_trail=True):
        """Lay each fish's spine out in SCREEN space and splat it.

        The HEAD (the front half of the spine, u<=0.5) still points the
        CURRENT heading by straight extrapolation, exactly as before the
        body-trail rework — a fish's nose really does lead where it is
        going. The trailing half (u>0.5) is instead walked back along the
        fish's own recorded path (`p_trail_x`/`p_trail_y`; see the
        BODY_TRAIL_* comment near the top of the module), so the body
        bends through a turn it actually swam rather than pivoting as a
        rigid stick to the tangent. `use_trail=False` (the outgoing radial
        collapse, which overwrites position/heading directly every frame
        into a synthetic spiral with no recorded path of its own) keeps
        the old all-heading layout for every node.

        On top of that backbone, the lateral throw is a wave travelling
        from head to tail, which is what reads as a flap."""
        k = len(idx)
        if k == 0:
            return
        px = self.cx + x * self.sx - self.cam_px
        py = self.cy + y * self.sy - self.cam_py
        length = half_w * 2.0 * self.body_aspect
        cos_h = np.cos(hd)
        sin_h = np.sin(hd)

        n_front = int(np.count_nonzero(SPINE_U <= 0.5)) if use_trail else SPINE_U.size
        along_front = (0.5 - SPINE_U[:n_front])[None, :] * length[:, None]
        base_x = np.empty((k, SPINE_U.size), dtype=np.float32)
        base_y = np.empty((k, SPINE_U.size), dtype=np.float32)
        base_x[:, :n_front] = px[:, None] + along_front * cos_h[:, None]
        base_y[:, :n_front] = py[:, None] + along_front * sin_h[:, None]
        if n_front < SPINE_U.size:
            # walk the trailing nodes back along the recorded path instead
            # of along the current heading (see _trail_points)
            rear_u = SPINE_U[n_front:]
            d = (rear_u[None, :] - 0.5) * length[:, None]
            base_x[:, n_front:], base_y[:, n_front:] = self._trail_points(
                idx, px, py, d
            )

        sx_, sy_ = self._spine_wave(
            base_x, base_y, cos_h, sin_h, flap_amp, self.p_flap[idx]
        )
        sizes = np.clip(
            half_w[:, None] * SPINE_PROFILE[None, :], 0.4, float(KERNEL_R)
        )
        rgb = self.get_gradient_color_vectorized1d(grad).astype(np.float32)
        # a substep smear along the frame's own travel keeps fast fish
        # continuous instead of dotted
        # ... measured on SCREEN, so the smear follows the window's own
        # travel too: a fish holding station in the water still streaks when
        # the view pans past it.
        dx = px - np.where(
            np.isfinite(self.p_x0[idx]),
            self.cx + self.p_x0[idx] * self.sx - self._cam_px_prev, px,
        )
        dy = py - np.where(
            np.isfinite(self.p_y0[idx]),
            self.cy + self.p_y0[idx] * self.sy - self._cam_py_prev, py,
        )
        self._splat_spines(frame, sx_, sy_, sizes, rgb, bright, dx, dy)

    def _spine_wave(self, base_x, base_y, cos_h, sin_h, flap_amp, flap,
                    u=SPINE_U, throw=SPINE_THROW):
        """The flap: a lateral throw travelling from head to tail, laid on
        a backbone sampled at spine positions `u` (SPINE_U for an ordinary
        fish). The ONE definition every fish body is drawn with — the
        ordinary fish (`_draw_bodies`) and the big fish
        (`_big_fish_bodies`)."""
        lat = (
            flap_amp[:, None]
            * np.sin(
                flap[:, None] - u[None, :] * SPINE_WAVE
                * 2 * np.pi
            )
            * throw[None, :]
        )
        return base_x - lat * sin_h[:, None], base_y + lat * cos_h[:, None]

    def _splat_spines(self, frame, sx_, sy_, sizes, rgb, bright, dx, dy,
                      node_w=None):
        """Splat laid-out spines (k fish x SPINE_U nodes) into `frame`, with
        the substep smear along each fish's own screen travel `dx`/`dy` that
        keeps a fast fish continuous instead of dotted. Shared by the
        ordinary fish and the big fish, so the two are one body drawn at
        two sizes. `node_w` (k x nodes) weights each node's splat (None:
        every node at full)."""
        nodes = sx_.shape[1]
        pts_x = []
        pts_y = []
        pts_rgb = []
        pts_size = []
        for f in range(SUBSTEPS):
            back = (SUBSTEPS - 1 - f) / SUBSTEPS
            pts_x.append((sx_ - dx[:, None] * back).ravel())
            pts_y.append((sy_ - dy[:, None] * back).ravel())
            pts_size.append(sizes.ravel())
            if node_w is None:
                pts_rgb.append(
                    np.repeat(
                        rgb * (bright[:, None] / SUBSTEPS), nodes, axis=0
                    )
                )
            else:
                pts_rgb.append(
                    (
                        (rgb * (bright[:, None] / SUBSTEPS))[:, None, :]
                        * node_w[:, :, None]
                    ).reshape(-1, 3)
                )
        self._splat_many(
            frame,
            np.concatenate(pts_x),
            np.concatenate(pts_y),
            np.concatenate(pts_rgb),
            np.concatenate(pts_size),
        )

    # ── the big fish (the BIG FISH block at the top of the module) ──────
    def _spawn_big_fish(self, intensity):
        """One big fish for one poke: off one side of the panel (a coin
        flip), nose first, at a height near the middle. `x` is the body's
        CENTRE in screen px, as an ordinary fish's position is."""
        if len(self._big) >= BIG_FISH_MAX:
            self.big_fish_dropped += 1
            return
        w = float(self.r_width)
        h = float(self.r_height)
        length = max(float(self.big_fish_size) * (w - 1.0), 4.0)
        rng = self._rng
        travel = 1.0 if rng.random() < 0.5 else -1.0   # +1 = left to right
        turn = 1.0 if rng.random() < 0.5 else -1.0     # hue direction
        degrees = big_fish_hue_degrees(intensity)
        cross_s = big_fish_cross_s(
            intensity, self.big_fish_cross_slow_s, self.big_fish_cross_fast_s
        )
        # the whole fish (half its length either side of the centre, and
        # the widest splat `_big_fish_bodies` ever lays) is off the panel at
        # both ends; its tail throw is sideways, across the run
        off = 0.5 * length + float(SPLAT_KERNEL_R) + BIG_FISH_MARGIN_PX
        if travel > 0:
            x0, x1 = -off, (w - 1.0) + off
        else:
            x0, x1 = (w - 1.0) + off, -off
        y = (h - 1.0) / 2.0 + float(
            rng.uniform(-BIG_FISH_Y_SPREAD, BIG_FISH_Y_SPREAD)
        ) * h
        fish = {
            "x": x0, "x_prev": x0, "x_end": x1, "y": y, "travel": travel,
            "speed": abs(x1 - x0) / cross_s, "cross_s": cross_s,
            "length": length,
            "degrees": degrees, "turn": turn,
            "intensity": float(intensity),
            "flap": float(rng.uniform(0.0, 2.0 * np.pi)),
        }
        self._big.append(fish)
        self.big_fish_spawned += 1
        self.big_fish_last = dict(fish)

    def _big_fish_colour(self, fish):
        """The gradient's centre, its hue turned by this fish's own angle —
        at FULL level; `big_fish_brightness` is applied when the layer is
        composited. Re-read every frame."""
        centre = self.get_gradient_color_vectorized1d(
            np.array([0.5], dtype=np.float32)
        )[0]
        return rotate_hue(centre, fish["turn"] * fish["degrees"])

    def _big_fish_motion(self, fish, swell=1.0):
        """What an ordinary fish would be doing at this one's size and
        speed: (scale, flap_amp, flap_freq, speed_norm). `scale` is its
        length over an ordinary fish's. Speed is read in BODY LENGTHS a
        second against an ordinary fish at cruise, so a big fish crossing at
        the same body-lengths/s strokes exactly like an ordinary one, just
        bigger — the same flap rules (FLAP_BASE, FLAP_SPEED_GAIN,
        `flap_amount`, `flap_rate`) as `draw()`'s."""
        length = fish["length"]
        ord_len = max(self._body_len_px(), 1e-3)
        scale = length / ord_len
        speed_norm = float(np.clip(
            (fish["speed"] / length) / (self.cruise_px / ord_len), 0.0, 3.0
        ))
        flap_scale = float(np.clip(
            FLAP_BASE + FLAP_SPEED_GAIN * speed_norm, FLAP_MIN, FLAP_MAX
        ))
        half_w = swell * length / (2.0 * max(float(self.body_aspect), 1e-3))
        flap_amp = self.flap_amount * half_w * self.body_aspect * flap_scale
        flap_freq = self.flap_rate * (0.4 + 0.6 * speed_norm)
        return scale, flap_amp, flap_freq, speed_norm

    def _big_fish_bodies(self, frame, fish, scale, swell, flap_amp, rgb,
                         bright):
        """Draw one big fish into `frame` through the ORDINARY fish's own
        spine layout, flap and splats (`_spine_wave`, `_splat_spines`).

        It is an ordinary fish SCALED, geometry and all: each splat's whole
        reach — an ordinary fish's size (`_draw_bodies`' own clip of
        half_w x SPINE_PROFILE) plus the 0.5 px `_splat_many` adds — is
        multiplied by `scale`. And the SAME spine (SPINE_PROFILE, the throw,
        the wave) is sampled at BIG_FISH_NODE_PX spacing instead of six
        nodes: six soft splats blur into one body at an ordinary fish's few
        pixels, but magnified five times they fall apart into six beads.
        Each dense node is weighted by spacing / reach, so the level along
        the spine is an ordinary fish's (about one splat's peak) — the
        continuous body its six splats stand for.

        Its run is straight, so its recorded path is the straight line
        behind it and the all-heading layout IS its trailed body (the same
        identity a straight-swimming ordinary fish reduces to)."""
        length = fish["length"] * swell
        hd = 0.0 if fish["travel"] > 0 else np.pi
        cos_h = np.array([np.cos(hd)], dtype=np.float32)
        sin_h = np.array([np.sin(hd)], dtype=np.float32)
        nodes = int(np.clip(
            np.ceil(length / BIG_FISH_NODE_PX) + 1, SPINE_U.size,
            BIG_FISH_NODES_MAX,
        ))
        u = np.linspace(0.0, 1.0, nodes, dtype=np.float32)
        along = (0.5 - u)[None, :] * np.float32(length)
        base_x = (fish["x"] + along * cos_h[:, None]).astype(np.float32)
        base_y = (fish["y"] + along * sin_h[:, None]).astype(np.float32)
        sx_, sy_ = self._spine_wave(
            base_x, base_y, cos_h, sin_h,
            np.array([flap_amp], dtype=np.float32),
            np.array([fish["flap"]], dtype=np.float32),
            u=u, throw=(u ** 1.6).astype(np.float32),
        )
        profile = np.interp(u, SPINE_U, SPINE_PROFILE).astype(np.float32)
        ordinary = np.clip(
            np.float32(self._half_width_px() * swell) * profile[None, :],
            0.4, float(KERNEL_R),
        )
        reach = np.minimum(
            (ordinary + 0.5) * np.float32(scale), float(SPLAT_KERNEL_R) - 0.5
        ).astype(np.float32)
        spacing = np.float32(length / (nodes - 1))
        self._splat_spines(
            frame, sx_, sy_, reach - 0.5,
            np.asarray(rgb, dtype=np.float32)[None, :],
            np.array([bright], dtype=np.float32),
            np.array([fish["x"] - fish["x_prev"]], dtype=np.float32),
            np.zeros(1, dtype=np.float32),
            node_w=np.minimum(spacing / reach, 1.0),
        )
        return sx_[0], sy_[0]

    def _big_fish_wake(self, fish, length, flap_amp, speed_norm, rgb,
                       bright, dt, sx_, sy_):
        """Lay the big fish's own wake into the shared wake buffer: the
        ordinary deposit rule (at the TAIL, sized off the body's length and
        tail throw, stronger when faster, pulsing with the tail), scaled to
        this fish's size and at the scene's own `ripple_amount` — then
        `big_fish_ripple_size` on the radius and `big_fish_ripple` on the
        level. It wears the big fish's own colour,
        so it reads as that fish's water. Large, and dim."""
        if (self.wake is None or self.big_fish_ripple <= 0.0
                or self.ripple_amount <= 0.0):
            return
        size = (
            min(
                WAKE_R0_BODY * length + WAKE_R0_FLAP * flap_amp,
                WAKE_R_MAX_BODY * length,
            )
            * max(float(self.ripple_width), 0.5)
            * float(self.big_fish_ripple_size)
        )
        size = float(np.clip(size, 0.6, float(SPLAT_KERNEL_R) - 1.0))
        pulse = WAKE_FLAP_FLOOR + WAKE_FLAP_GAIN * abs(np.sin(fish["flap"]))
        amp = (
            float(self.big_fish_ripple) * float(self.ripple_amount)
            * (
                RIPPLE_BASE
                + RIPPLE_SPEED_GAIN
                * float(np.clip(
                    (speed_norm - RIPPLE_SPEED_FLOOR) / RIPPLE_SPEED_SPAN,
                    0.0, 1.0,
                ))
            )
            * pulse * bright * min(dt * WAKE_DEPOSIT_HZ, 1.0)
        )
        if self._phase == "lull" and self._lull_state is not None:
            amp *= float(self._lull_state.get("dark", 1.0))
        if amp <= 0.0:
            return
        self._splat_many(
            self.wake,
            np.array([sx_[-1]], dtype=np.float32),
            np.array([sy_[-1]], dtype=np.float32),
            (np.asarray(rgb, dtype=np.float32) * np.float32(amp))[None, :],
            np.array([size], dtype=np.float32),
        )

    def _big_fish_layer(self, dt, occluder, wake=True):
        """Take any pending pokes, swim every big fish one frame and return
        its layer (H, W, 3) — its body, with the ordinary fish's own
        persistent smear (`trail_decay`), at `big_fish_brightness`, hidden
        behind `occluder` (the ordinary fish's body layer) — or None when
        nothing is crossing and its smear has gone. With `wake`, each big
        fish also lays its own wake into the shared wake buffer, so the
        caller must composite `self.wake` AFTER calling this. Called once
        per frame by whichever path composites it."""
        # WORD SHAPES: a big fish does not SET OFF while a shape is running
        # (the PAUSES paragraph) — its poke stays queued and crosses after.
        # One already in flight finishes, and the other fish still get out
        # of its way at full strength.
        holding = bool(self._big_pending) and self._word_shape_holds()
        if (self._big_pending or self._big_seen) and not holding:
            pending, self._big_pending = self._big_pending, []
            for strength in pending:
                self._spawn_big_fish(max(strength, 0.0))
            # sanctioned in-render config path (under the effect lock)
            self._apply_config(
                {"big_fish": 0.0}, validate=False, fire_event=False
            )
        if not self._big and self._big_trail is None:
            return None
        h, w = int(self.r_height), int(self.r_width)
        if self._big_trail is None:
            self._big_trail = np.zeros((h, w, 3), dtype=np.float32)
        half_life = self._trail_half_life()
        self._big_trail *= np.float32(0.5 ** (dt / half_life))
        frame = np.zeros((h, w, 3), dtype=np.float32)
        # the ordinary fish's own audio brightness and size swell (no
        # per-fish jiggle: there is one of it), so it is as lively as they are
        rscale = self.reactivity_scale
        impulse = min(self.impulse, 1.0)
        br_eff = self.brightness_audio * rscale
        bright = float(np.clip(
            (1.0 - 0.45 * min(br_eff, 1.0)) * (1.0 + 1.2 * br_eff * impulse),
            0.0, 1.0,
        ))
        swell = 1.0 + 0.8 * self.size_audio * rscale * impulse
        keep = []
        for fish in self._big:
            fish["x_prev"] = fish["x"]
            fish["x"] += fish["travel"] * fish["speed"] * dt
            if (fish["x"] - fish["x_end"]) * fish["travel"] > 0.0:
                continue   # the whole fish is off the far side: done
            keep.append(fish)
            scale, flap_amp, flap_freq, speed_norm = self._big_fish_motion(
                fish, swell
            )
            fish["flap"] = (
                fish["flap"] + 2 * np.pi * flap_freq * dt
            ) % (2 * np.pi * 64)
            rgb = self._big_fish_colour(fish)
            sx_, sy_ = self._big_fish_bodies(
                frame, fish, scale, swell, flap_amp, rgb, bright
            )
            if wake:
                self._big_fish_wake(
                    fish, fish["length"] * swell, flap_amp,
                    speed_norm, rgb, bright, dt, sx_, sy_,
                )
        self._big = keep
        # the ceiling keeps its colour (the scatter's clip): his 120-180
        # degree rule must survive a body's overlapping splats
        peak = frame.max(axis=2, keepdims=True)
        frame = np.where(
            peak > 255.0,
            frame * (np.float32(255.0) / np.maximum(peak, np.float32(1.0))),
            frame,
        )
        np.maximum(self._big_trail, frame, out=self._big_trail)
        if self._phase == "lull" and self._lull_state is not None:
            self._big_trail *= np.float32(self._lull_state.get("dark", 1.0))
        if not self._big and float(self._big_trail.max()) < BIG_FISH_GONE:
            self._big_trail = None
            return None
        layer = self._big_trail * np.float32(self.big_fish_brightness)
        if occluder is not None:
            hide = np.clip(
                occluder.max(axis=2) / np.float32(BIG_FISH_OCCLUDE_AT),
                0.0, 1.0,
            )
            layer = layer * (1.0 - hide)[..., None]
        return layer

    def _big_fish_profile(self, fish, swell):
        """The big fish's drawn body as the avoidance reads it: (length px,
        half-thickness at each SPINE_U node). The thickness is the reach of
        the splat `_big_fish_bodies` lays there (its lit core,
        BIG_AVOID_CORE of it) plus its tail throw."""
        scale, flap_amp, _f, _s = self._big_fish_motion(fish, swell)
        ordinary = np.clip(
            np.float32(self._half_width_px() * swell) * SPINE_PROFILE,
            0.4, float(KERNEL_R),
        )
        prof = (
            np.minimum((ordinary + 0.5) * np.float32(scale),
                       float(SPLAT_KERNEL_R) - 0.5) * np.float32(BIG_AVOID_CORE)
            + np.float32(flap_amp) * SPINE_THROW
        )
        return float(fish["length"]) * swell, prof.astype(np.float32)

    def _big_fish_threat(self, n, affected, hd, rscale, impulse):
        """THE OTHER FISH AVOID IT (the block beside BIG_AVOID_W): for each
        of the first `n` fish, (urgency 0..1, escape heading) against every
        big fish crossing. Fish outside `affected` get urgency 0. Pure: it
        reads the fish and the big fish and changes neither. Also returns
        `away`: +1 / -1, the side of the big fish's line (screen y) each
        threatened fish is getting out to (0 where none)."""
        urg = np.zeros(n, dtype=np.float32)
        esc = np.asarray(hd, dtype=np.float32).copy()
        away = np.zeros(n, dtype=np.float32)
        idx = np.flatnonzero(affected)
        if idx.size == 0 or not self._big:
            return urg, esc, away
        swell = 1.0 + 0.8 * self.size_audio * rscale * min(impulse, 1.0)
        # the ordinary fish's body: five points nose to tail, each with the
        # reach of the splat drawn there (size swell and tail throw in)
        hw = float(self._half_width_px()) * swell
        half = hw * float(self.body_aspect)
        u = BIG_AVOID_U
        along = (0.5 - u) * np.float32(2.0 * half)          # + = toward nose
        r_ord = (
            (hw * np.interp(u, SPINE_U, SPINE_PROFILE).astype(np.float32)
             + 0.5) * np.float32(BIG_AVOID_CORE)
            + self.flap_amount * half * u ** 1.6
        ).astype(np.float32)
        margin = float(self.big_fish_avoid_margin)
        px = self.cx + self.p_x[idx] * self.sx - self.cam_px
        py = self.cy + self.p_y[idx] * self.sy - self.cam_py
        h = hd[idx]
        ch, sh = np.cos(h), np.sin(h)
        spd = np.maximum(self.p_spd[idx], 0.0)
        qx = px[:, None] + ch[:, None] * along[None, :]     # (fish, point)
        qy = py[:, None] + sh[:, None] * along[None, :]
        vx = (ch * spd)[:, None, None]
        vy = (sh * spd)[:, None, None]
        t = np.linspace(0.0, BIG_AVOID_LOOK_S, BIG_AVOID_STEPS,
                        dtype=np.float32)[None, None, :]
        best = np.zeros(idx.size, dtype=np.float32)
        best_b = np.zeros(idx.size, dtype=np.int32)
        profiles = []
        for b, fish in enumerate(self._big):
            lb, prof = self._big_fish_profile(fish, swell)
            profiles.append((lb, prof))
            vb = fish["travel"] * fish["speed"]
            worst = np.zeros(idx.size, dtype=np.float32)
            for moving in (True, False):
                if moving:      # on its own heading and speed
                    ox = qx[:, :, None] + vx * t
                    oy = qy[:, :, None] + vy * t
                else:           # holding still where it is
                    ox = np.broadcast_to(qx[:, :, None], (*qx.shape, t.size))
                    oy = np.broadcast_to(qy[:, :, None], ox.shape)
                d = self._big_clearance(
                    ox, oy, fish["x"] + vb * t, fish, lb, prof,
                ) - r_ord[None, :, None] - margin
                hit = (d < 0.0).any(axis=1)                 # (fish, t)
                first = np.where(hit.any(axis=1), hit.argmax(axis=1),
                                 BIG_AVOID_STEPS - 1)
                soon = np.where(
                    hit.any(axis=1),
                    1.0 - first / (BIG_AVOID_STEPS - 1.0), 0.0)
                if moving:
                    near = np.clip(
                        1.0 - d[:, :, 0].min(axis=1) / BIG_AVOID_NEAR_PX,
                        0.0, 1.0)
                    soon = np.maximum(soon, near)
                worst = np.maximum(worst, soon)
            take = worst > best
            best = np.where(take, worst, best).astype(np.float32)
            best_b = np.where(take, b, best_b)
        live = np.flatnonzero(best > 0.0)
        if live.size == 0:
            return urg, esc, away
        # THE WAY OUT: a spot nearby, inside the lit panel, that the big
        # fish's body will stay clear of from when this fish could get there
        # on to the end of the look-ahead (and the way to it with it). The
        # crystal is a hexagon, so near its points there is no room above or
        # below the big fish at all — a fish there has to make for where
        # there is, which is why this searches rather than just turning off
        # the big fish's line.
        ang = np.linspace(0.0, 2.0 * np.pi, BIG_AVOID_ANGLES,
                          endpoint=False).astype(np.float32)
        rad = np.asarray(BIG_AVOID_RADII_PX, dtype=np.float32)
        cdx = (np.cos(ang)[None, :] * rad[:, None]).ravel()
        cdy = (np.sin(ang)[None, :] * rad[:, None]).ravel()
        dist = np.hypot(cdx, cdy)
        r_body = float(r_ord.max()) + margin
        tt = np.linspace(0.0, BIG_AVOID_LOOK_S, BIG_AVOID_STEPS,
                         dtype=np.float32)
        for k in live:
            x, y = float(px[k]), float(py[k])
            cx_ = x + cdx
            cy_ = y + cdy
            t_arr = dist / max(float(spd[k]) * BIG_FLEE_X, 1e-3)
            clear_end = np.full(cdx.size, np.inf, dtype=np.float32)
            clear_way = np.full(cdx.size, np.inf, dtype=np.float32)
            for (lb, prof), fish in zip(profiles, self._big):
                vb = fish["travel"] * fish["speed"]
                # parked at the spot from when it arrives ...
                bxt = fish["x"] + vb * tt[None, :]
                d = self._big_clearance(cx_[:, None], cy_[:, None], bxt,
                                        fish, lb, prof) - r_body
                d = np.where(tt[None, :] >= t_arr[:, None] - 1e-6, d, np.inf)
                clear_end = np.minimum(clear_end, d.min(axis=1))
                # ... and every step of the way there, when it is there
                frac = BIG_AVOID_WAY[None, :]
                bxw = fish["x"] + vb * (t_arr[:, None] * frac)
                d = self._big_clearance(x + cdx[:, None] * frac,
                                        y + cdy[:, None] * frac, bxw,
                                        fish, lb, prof) - r_body
                clear_way = np.minimum(clear_way, d.min(axis=1))
            score = (
                np.minimum(np.minimum(clear_end, clear_way), BIG_AVOID_GOOD_PX)
                - BIG_AVOID_DIST_COST * dist
                # among equally good spots, the one it is already facing:
                # the least turning, never a bias to one side of the panel
                + BIG_AVOID_FACING * (np.cos(h[k]) * cdx + np.sin(h[k]) * cdy)
                / np.maximum(dist, 1e-3)
            )
            room = self._room_many(cx_, cy_)
            score = np.where(room >= 0.0, score, -np.inf)
            if not np.isfinite(score).any():
                continue        # nowhere inside the panel: leave it be
            j = int(np.argmax(score))
            out = float(np.arctan2(cdy[j], cdx[j]))
            near = self._big[int(best_b[k])]
            esc[idx[k]] = out
            urg[idx[k]] = best[k]
            away[idx[k]] = 1.0 if cy_[j] >= near["y"] else -1.0
        return urg, esc, away

    @staticmethod
    def _big_clearance(qx, qy, bx, fish, lb, prof):
        """Distance (px) from points (qx, qy) to a big fish's body (its
        drawn core, `prof` along its length `lb`) with its centre at `bx`
        (all broadcast together); negative inside it."""
        ra = (qx - bx) * fish["travel"]
        ry = qy - fish["y"]
        ul = np.clip(0.5 - ra / max(lb, 1e-3), 0.0, 1.0)
        hb = np.interp(ul, SPINE_U, prof)
        cap = np.where(ra > 0.0, prof[0], prof[-1])
        return np.where(
            np.abs(ra) > 0.5 * lb,
            np.hypot(np.abs(ra) - 0.5 * lb, ry) - cap,
            np.abs(ry) - hb,
        )

    def _room_many(self, x, y):
        """Signed room (SCREEN px, positive inside) for a fish's MIDDLE at
        points (x, y): the lit panel's own landing line (the pond left out —
        a fish getting out of a big fish's way may use the whole panel),
        else the pond when no wall has been read."""
        xs = np.asarray(x, dtype=np.float32)
        ys = np.asarray(y, dtype=np.float32)
        if self._wall is not None:
            d, _, _ = self._wall_landing(xs, ys, free=True)
        else:
            d, _, _ = self._pond_distance(xs, ys)
        return d

    # ── main ────────────────────────────────────────────────────────────
    def draw(self):
        if self.test:
            self.draw_test(self.m_draw)
            return

        # A MATCHED BIRTH REPLACES THE ADOPT (the shoal-burst plan §5.2)
        pend = self._prog_birth_snap
        if pend is not None:
            self._prog_birth_snap = None
            self._handoff_pending = False
            self._prog_birth_token = pend.get("token")
            self._prog_birth_pids = self._program_birth(pend)
        if self._handoff_pending:
            self._handoff_pending = False
            self._adopt_handoff()

        dt = min(self.passed, DT_MAX)
        if not np.isfinite(dt) or dt <= 0:
            dt = 1.0 / 60.0
        self.passed_dt = dt
        self.t += dt
        self._spike_cool = max(0.0, self._spike_cool - dt)
        for name in ("roll_total", "t"):
            if not np.isfinite(getattr(self, name)):
                setattr(self, name, 0.0)

        virtual = self._virtual
        if self._erupt_hold is not None:
            hold = self._erupt_hold
            frac = particle_handoff.transition_progress(virtual)
            if getattr(virtual, "_transition_effect", None) is self:
                self._erupt_hold = None
            elif (
                frac is None
                or frac >= particle_handoff.BLOOM_START
                or particle_handoff.now() - hold["t0"]
                > particle_handoff.ERUPT_HOLD_MAX_S
            ):
                self._erupt_hold = None
                self._spawn_center_burst(
                    hold["ncx"], hold["ncy"], self.particle_count
                )
            else:
                self._fade_only(dt)
                return

        if self._pacman_hold is not None:
            hold = self._pacman_hold
            frac = particle_handoff.transition_progress(virtual)
            if getattr(virtual, "_transition_effect", None) is self:
                self._pacman_hold = None
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
                self._fade_only(dt)
                return

        # collapse latch: we are the outgoing crossfade sibling and radial
        # is incoming — the shoal spirals into its centre
        if self._collapse is None:
            inc = particle_handoff.incoming_sibling(virtual, self)
            if inc is not None and getattr(inc, "NAME", None) == "Radial":
                n0 = self.n
                t_px = self.r_width * float(inc._config.get("x_offset", 0.5))
                t_py = self.r_height * float(inc._config.get("y_offset", 0.5))
                tx = (t_px - self.cx + self.cam_px) / max(self.sx, 1e-6)
                ty = (t_py - self.cy + self.cam_py) / max(self.sy, 1e-6)
                px = np.where(np.isfinite(self.p_x[:n0]), self.p_x[:n0], 0.0)
                py = np.where(np.isfinite(self.p_y[:n0]), self.p_y[:n0], 0.0)
                self._collapse = {
                    "rho0": np.hypot(px - tx, py - ty).astype(np.float32),
                    "phi0": np.arctan2(py - ty, px - tx).astype(np.float32),
                    "bright0": self.p_bright[:n0].copy(),
                    "grad0": self.p_grad[:n0].copy(),
                    "tx": tx,
                    "ty": ty,
                    "frac0": particle_handoff.transition_progress(virtual)
                    or 0.0,
                    "t0": particle_handoff.now(),
                    "spin": -1.0 if self.reverse else 1.0,
                }
        elif getattr(virtual, "_transition_effect", None) is not self:
            self._collapse = None

        if self._collapse is not None:
            self._draw_collapse(dt)
            return

        # scatter latch: we are the outgoing crossfade sibling and the
        # incoming effect has no blobs to merge the fish into (neither radial
        # nor an adopter) — every fish disperses off the panel inside the
        # crossfade instead of dimming away under it (see the
        # outgoing-crossfade block at the top of the module)
        inc = particle_handoff.incoming_sibling(virtual, self)
        if (
            inc is not None
            and inc is not self
            and type(inc).__module__.rsplit(".", 1)[-1]
            not in TRANSITION_ADOPTERS
        ):
            frames = float(getattr(virtual, "transition_frame_total", 0) or 0)
            # the virtual advances its counter straight AFTER rendering us,
            # so the weight this frame is blended at is one frame further on
            frac = min(
                (particle_handoff.transition_progress(virtual) or 0.0)
                + 1.0 / max(frames, 1.0),
                1.0,
            )
            total_s = frames / max(
                float(getattr(virtual, "refresh_rate", 60) or 60), 1.0
            )
            additive = (
                (getattr(virtual, "_config", None) or {}).get("transition_mode")
                == "Add"
            )
            self._scatter = {
                "left_s": max(TRANSITION_EXIT_BY - frac, 0.0) * total_s,
                "gain": (1.0 / max(1.0 - frac, TRANSITION_GAIN_FLOOR)
                         if additive else 1.0),
            }
        elif self._scatter is not None:
            self._scatter = None

        rscale = self.reactivity_scale
        impulse = min(self.impulse, 1.0)
        direction = -1.0 if self.reverse else 1.0
        jiggle = self.jiggle

        spike = np.clip((self.impulse - self.slow) * 3.0, 0.0, 1.0)
        beat_now = self._beat_pending

        # the swim burst envelope — a level the flare holds, rounded at the
        # edges only (the flare kind's own hold is the burst's length).
        # WORD SHAPES: a burst does not START while a shape is running (the
        # PAUSES paragraph); one already in flight keeps its envelope and
        # releases on its own hold, so it finishes rather than being cut.
        if self.swim_burst and not (
            self._burst <= 0.0 and self._word_shape_holds()
        ):
            self._burst = min(self._burst + dt / BURST_ATTACK_S, 1.0)
        else:
            self._burst = max(self._burst - dt / BURST_RELEASE_S, 0.0)
        if self._burst > 0.0:
            self._burst_tail = 0.15
        else:
            self._burst_tail = max(self._burst_tail - dt, 0.0)

        if self._scatter is None:
            self._phase_step(dt)
            # THE COUNT RULE (the shoal-burst plan §5.4): a matched birth's
            # count holds until `transition_count_hold_ms` after the program
            # ends, then the authored count wins and _manage_population
            # flies the difference in or out as it does for a live change.
            if self._count_hold is not None and self.t >= self._count_hold[0]:
                self.particle_count = int(self._count_hold[1])
                self._count_hold = None
            self._manage_population()
        else:
            # an outgoing instance receives no more choreography and spawns
            # no replacements: everything on it is leaving
            self._depart(np.arange(self.n), within=self._scatter["left_s"])
        n = self.n
        if n == 0:
            self._fade_only(dt)
            return

        # ── body trail backfill ─────────────────────────────────────────
        # A fish born this frame has no recorded path yet (flagged NaN in
        # _spawn) — seed one straight back along its own heading at the
        # ordinary sample spacing, so its very first drawn frame already
        # has a real (if momentarily straight) tail instead of a
        # collapsed point. Matches the ongoing push in this same draw()
        # exactly (see BODY_TRAIL_STEP_PX), so nothing needs re-seeding
        # once real travel starts overwriting it.
        need_trail = ~np.isfinite(self.p_trail_x[:n, 0])
        if need_trail.any():
            ni = np.flatnonzero(need_trail)
            steps = (
                np.arange(BODY_TRAIL_LEN, dtype=np.float32)
                * BODY_TRAIL_STEP_PX
            )
            back_x = np.cos(self.p_hd[ni])[:, None] * steps[None, :] / self.sx
            back_y = np.sin(self.p_hd[ni])[:, None] * steps[None, :] / self.sy
            peel = np.isfinite(self.p_peel[ni])
            if peel.any():
                # THE PEEL: a fish peeling off a curve was on that curve —
                # its body lies back along it, not on a straight line
                pi_ = ni[peel]
                rate = self.p_peel[pi_] / np.maximum(self.p_spd[pi_], 1e-3)
                ang = (self.p_hd[pi_][:, None]
                       - rate[:, None] * (steps[None, :] + 0.5 * BODY_TRAIL_STEP_PX))
                seg_x = np.cos(ang) * BODY_TRAIL_STEP_PX / self.sx
                seg_y = np.sin(ang) * BODY_TRAIL_STEP_PX / self.sy
                back_x[peel, 1:] = np.cumsum(seg_x, axis=1)[:, :-1]
                back_y[peel, 1:] = np.cumsum(seg_y, axis=1)[:, :-1]
            self.p_trail_x[ni, :] = self.p_x[ni][:, None] - back_x
            self.p_trail_y[ni, :] = self.p_y[ni][:, None] - back_y
            self.p_trail_acc[ni] = 0.0

        if beat_now and self._phase != "charge":
            hit = 0.4 + 0.5 * impulse
            if self._rest_level > 0.0:
                # THE POND REST: the tracker's predicted ticks do not lunge a
                # resting fish (a real onset still does, through the spike)
                hit *= 1.0 - self._rest_level
            spike = max(spike, hit)
            self._beat_pending = False

        self.roll_total = (self.roll_total + self.gradient_spin * dt) % 1.0

        mode = self.p_mode[:n]
        swimming = mode < 2
        rushing = mode == 3
        dispersing = mode == 4
        # the lull's searching KEEPERS (mode 5): steered toward the targets
        # _keep_targets set, never by the population, the pond or the swirl
        keeping = mode == 5
        kst = self._keep
        if keeping.any():
            kidx = np.flatnonzero(keeping)
            if kst is None or len(kst["idx"]) != kidx.size:
                kst = None
        else:
            kidx = None
            kst = None
        steered = swimming | rushing | dispersing | keeping
        # a dispersing fish is SWIRLING until its leak time, then heading out
        swirling = dispersing & (self.p_lk[:n] > self.t)
        leaking = dispersing & ~swirling
        m = int(np.count_nonzero(swimming))
        # WORD SHAPES (the block of that name): one frame of the procession.
        # None on every untold frame, and then nothing below it is reached —
        # which is what makes an untold frame byte for byte today's.
        ws = self._word_shape_step(dt, n, mode, self.cruise_px)
        # THE OTHER FISH AVOID THE BIG FISH (the block beside BIG_AVOID_W):
        # read once a frame, before speed, so the dart and the swerve agree.
        # With no big fish crossing (or big_fish_avoid 0) nothing here runs.
        big_urg = big_esc = big_away = None
        if self._big and self.big_fish_avoid > 0.0:
            big_urg, big_esc, big_away = self._big_fish_threat(
                n, swimming | keeping, self.p_hd[:n], rscale, impulse
            )
            if not big_urg.any():
                big_urg = big_esc = big_away = None

        # home-anchor re-spacing ease (wrapped shortest way around the ring)
        target = self.p_slot[:n].astype(np.float32) / max(m, 1)
        diff = (target - self.p_slot_frac[:n] + 0.5) % 1.0 - 0.5
        self.p_slot_frac[:n] = (
            self.p_slot_frac[:n] + diff * min(1.0, dt / SLOT_EASE_S)
        ) % 1.0

        # smooth per-fish noise + reactivity gain: identical response at
        # jiggle 0, fully independent at jiggle 1
        n_w = np.sin(self.t * self.p_wf[:n] * 2 * np.pi + self.p_wp[:n])
        n_r = np.sin(self.t * self.p_nf1[:n] * 2 * np.pi + self.p_np1[:n])
        gain = (1.0 - jiggle) + jiggle * (
            0.5 + 0.5 * np.sin(
                self.t * self.p_gf[:n] * 2 * np.pi + self.p_gp[:n]
            )
        )

        # ── the lunge ───────────────────────────────────────────────────
        # A strong spike arms a per-fish envelope that HOLDS the boost near
        # full for LUNGE_HOLD_S before releasing, so a beat is a real dash
        # of several body lengths instead of a blip the ripple outruns.
        # Below LUNGE_SPIKE_MIN nothing is armed and nothing decays, so
        # quiet swimming is bit-for-bit the plain cruise.
        jump_eff = self.speed_jump * rscale
        if spike >= LUNGE_SPIKE_MIN and jump_eff > 0.0:
            mag = LUNGE_GAIN * jump_eff * float(spike)
            self.p_lun[:n] = np.maximum(self.p_lun[:n], mag)
            self.p_lun_t[:n] = LUNGE_HOLD_S
        held = self.p_lun_t[:n] > 0.0
        if held.any():
            self.p_lun_t[:n] = np.maximum(self.p_lun_t[:n] - dt, 0.0)
        self.p_lun[:n] = np.where(
            held, self.p_lun[:n],
            self.p_lun[:n] * np.float32(0.5 ** (dt / LUNGE_FALL_S)),
        )

        # ── speed ───────────────────────────────────────────────────────
        cruise = self.cruise_px
        want_full = (
            cruise
            * (1.0 + jump_eff * impulse * gain)
            * (1.0 + self.p_lun[:n])
            * (1.0 + 0.25 * jiggle * n_r)
            * (1.0 + self.p_ro[:n])
            * self._speed_scale
            * np.where(mode == 1, ENTER_SPEED_X, 1.0)
        )
        # tail-stroke thrust (his ruling — see the THRUST block at the top
        # of the module for the full reasoning): `want_full` above is the
        # plain continuous target this effect always computed; the speed a
        # fish actually chases is a MINIMUM DRIFT floor plus a PULSE synced
        # to its own tail-beat phase, capped as a fraction of that same
        # target. `p_flap` is read here BEFORE its own increment further
        # down in this frame (the flap section) — a one-frame lag, which is
        # fine since the two feed back into each other every frame anyway
        # (faster swimming -> faster flap -> a stronger/more frequent
        # pulse -> ...).
        # SCOPED to the ordinary population only — mode<2 (swimming/
        # entering), not a cap-exempt school/rush fish, AND not while a
        # school is formed. The charge's school and the drop's rush are
        # authored choreography, not ordinary swimmers ("the school moves
        # 'almost identically'", the same reasoning that keeps mutual
        # avoidance off while a school is formed below) — a pulsing speed on
        # top of that would perturb a moment he has already tuned for
        # something this feature was never asked to touch. `p_nocap` alone
        # is not enough: the charge counts the fish already swimming toward
        # its school and steers every one of them, so `_school_on` gates the
        # whole population for as long as the school holds.
        pulse_eligible = (
            (mode < 2) & (self.p_nocap[:n] == 0) & (not self._school_on)
        )
        stroke_phase = self.p_flap[:n] % (2.0 * np.pi)
        pulse_shape = (0.5 - 0.5 * np.cos(stroke_phase)) ** PULSE_SHAPE_POWER
        pulsed_want = np.maximum(
            want_full * self.min_drift_speed
            + want_full * self.stroke_speed_cap * pulse_shape,
            want_full * MOTION_FLOOR_FRAC,
        )
        want = np.where(pulse_eligible, pulsed_want, want_full)
        # WORD SHAPES: THE PROCESSION'S OWN PACE, blended in by the told
        # envelope. It lands HERE — before the moments below — on purpose:
        # the dash to the line replaces the surge-and-coast thrust pulse
        # (his "smoothly accelerate and not have sudden velocity shifts"),
        # while a swim burst, a big-fish flee or a solo dash already in
        # flight still multiplies whatever speed the fish is on, so one
        # mid-shape finishes instead of being cut off.
        if ws is not None and ws["want"] is not None:
            wsm = ws["m_fish"]
            shaped = np.array(want, dtype=np.float32, copy=True)
            shaped[ws["idx"]] = ws["want"]
            want = want * (1.0 - wsm) + shaped * wsm
        # THE TAIL DRIVE (the block of that name at the top of the module):
        # its effort is the target WITHOUT the pulse (the tail makes the
        # pushes now), carried through every multiplier below. At
        # tail_drive 0 none of it exists and nothing below changes.
        tail_w = float(self.tail_drive) if pulse_eligible.any() else 0.0
        want_tail = (
            np.where(pulse_eligible, want_full, want) if tail_w > 0.0
            else None
        )
        if ws is not None and want_tail is not None:
            # ... and under a shape the tail hands over: the procession's
            # pace is a smooth speed, so the tail's own thrust-and-drag
            # pulse is faded out per fish by the envelope (an ARRAY weight —
            # a scalar one is the only thing an untold frame ever sees), and
            # what effort is left asks for the procession's pace.
            wsm = ws["m_fish"]
            tail_w = np.float32(tail_w) * (1.0 - wsm)
            want_tail = want_tail * (1.0 - wsm) + want * wsm
        if want_tail is None and self.tail_drive > 0.0:
            # no fish is eligible this frame (a formed school) — the beat
            # envelope still ages, or a kick armed just before the charge
            # would resume ordinary swimming after the drop still above
            # TAIL_BEAT_ON and force an extra stroke
            self._decay_tail_kick(n, dt)
        if self.quiet_rest > 0.0:
            # THE POND REST rests this ORDINARY target; the moments below (a
            # flee, a burst, a solo dash) keep their own share whole
            ordinary = (want, want_tail)
        # The ease is per fish (the pulse split makes `tau` an array even
        # for ordinary swimming). At stroke_speed_cap=0 (with
        # min_drift_speed at its max of 1) `want` above is `want_full`
        # exactly and every `tau` below is SPEED_TAU exactly — his stated
        # escape hatch back to the pre-pulse motion.
        pulse_engage = min(max(self.stroke_speed_cap, 0.0), 1.0)
        fast_tau = SPEED_TAU * (1.0 - pulse_engage) + THRUST_TAU * pulse_engage
        tau = np.where(pulse_eligible, fast_tau, SPEED_TAU)
        tau_ordinary = tau
        if dispersing.any():
            want = np.where(
                swirling,
                cruise * LULL_SWIRL_SPEED_X * (1.0 + 0.3 * n_r),
                want,
            )
            if leaking.any():
                want = np.where(leaking, self._disperse_speed(n, cruise), want)
            tau = np.where(dispersing, DISPERSE_TAU, tau)
        if kst is not None:
            want = np.where(keeping, np.float32(kst["speed"]), want)
            tau = np.where(keeping, KEEP_SPEED_TAU, tau)
        if big_urg is not None:
            # a startled fish darts out of the big fish's way
            flee = 1.0 + (BIG_FLEE_X - 1.0) * big_urg
            want = want * flee
            if want_tail is not None:
                want_tail = want_tail * flee
            tau = np.where(big_urg > 0.0, np.minimum(tau, BIG_FLEE_TAU), tau)
        if self._burst > 0.0:
            dash = 1.0 + SWIM_BURST_SPEED_X * self._burst
            want = want * dash
            if want_tail is not None:
                want_tail = want_tail * dash
        self._solo_burst_step(n, dt, mode)
        solo = self.p_sb[:n]
        if solo.any():
            sprint = 1.0 + (self.solo_burst_speed - 1.0) * solo
            want = want * sprint
            if want_tail is not None:
                want_tail = want_tail * sprint
            tau = np.where(
                self.p_sb_t[:n] > 0.0, np.minimum(tau, SOLO_SPEED_TAU), tau
            )
        if self._burst_tail > 0.0:
            tau = np.minimum(tau, BURST_SPEED_TAU)
        if self.quiet_rest > 0.0:
            want, want_tail = self._pond_rest_step(
                n, dt, pulse_eligible, ordinary, (want, want_tail), cruise,
                spike, jump_eff,
            )
        # ejecta hold whatever they left with
        prev = self.p_spd[:n].copy()
        if np.ndim(tau):
            ease = np.minimum(1.0, dt / np.maximum(tau, 1e-3))
        else:
            ease = min(1.0, dt / max(tau, 1e-3))
        self.p_spd[:n] = np.where(
            steered, prev + (want - prev) * ease, prev
        )
        if want_tail is not None:
            self._tail_drive_step(
                pulse_eligible, want_tail, prev, dt, cruise, spike, jump_eff,
                tail_w, tau, tau_ordinary,
            )
        inst_acc = (self.p_spd[:n] - prev) / max(dt, 1e-4)
        a_ease = min(1.0, dt / max(ACCEL_TAU, 1e-3))
        self.p_acc[:n] += (inst_acc - self.p_acc[:n]) * a_ease

        # ── steering ────────────────────────────────────────────────────
        desired_x = np.zeros(n, dtype=np.float32)
        desired_y = np.zeros(n, dtype=np.float32)
        hd = self.p_hd[:n]

        # wander: a slow smooth swing either side of the current heading
        wander = hd + n_w * (WANDER_SWING + WANDER_SWING_JIGGLE * jiggle)
        w_wander = np.where(steered, WANDER_W, 0.0)
        if ws is not None:
            # WORD SHAPES, ROW W6.1: the wander hands over to the loop
            # exactly as the swirl and the beat's kicks already do (the
            # `bias * (1 - m)` block in the steering below) — THE LOOP IS
            # THE CURRENT while a shape runs, and a meander is a heading
            # noise by construction. It was the one steering term left
            # ungated: WANDER_W is 1.0 against the loop's WS_SEEK_W of 14,
            # so it moved the DESIRED heading about 0.7 deg every frame,
            # which the shaped gain then chased — the noise that re-excited
            # the overshoot above. His own again by the release's end.
            w_wander = w_wander * (1.0 - ws["m_fish"])
        desired_x += np.cos(wander) * w_wander
        desired_y += np.sin(wander) * w_wander

        # Everything below that names the pond, the home ring or "inward"
        # is a fact about the VISIBLE water, so it is measured from the
        # window's own centre. At rest cam_nx/cam_ny are zero and each of
        # these is exactly the expression it was before the window existed.
        cnx, cny = self.cam_nx, self.cam_ny
        rel_x = self.p_x[:n] - cnx
        rel_y = self.p_y[:n] - cny

        # home anchors: a gentle pull back toward each fish's own patch
        ring_frac = self.p_slot_frac[:n]
        if self.tether_scatter > 0.0:
            scatter_diff = (
                self.p_scatter[:n] - ring_frac + 0.5
            ) % 1.0 - 0.5
            ring_frac = ring_frac + scatter_diff * self.tether_scatter
        ring_ang = ring_frac * 2 * np.pi
        hx = cnx + self.horizon_scale * np.cos(ring_ang)
        hy = cny + self.horizon_scale * np.sin(ring_ang)
        to_home = np.arctan2(
            (hy - self.p_y[:n]) * self.sy, (hx - self.p_x[:n]) * self.sx
        )
        home_d = np.hypot(
            (hx - self.p_x[:n]) * self.sx, (hy - self.p_y[:n]) * self.sy
        )
        pond_px = max(self.roam_bound * self.s_min, 1e-3)
        w_home = np.where(
            swimming,
            HOME_W * np.clip(
                (home_d - pond_px * HOME_FREE) / (pond_px * (1 - HOME_FREE)),
                0.0, 1.0,
            ),
            0.0,
        )
        if ws is not None:
            # WORD SHAPES: the loop is the fish's patch while a shape runs
            w_home = w_home * (1.0 - ws["m_fish"])
        desired_x += np.cos(to_home) * w_home
        desired_y += np.sin(to_home) * w_home

        bound = self.roam_bound
        # the charge's school is authored choreography — it keeps the edge
        # it was tuned against, the same scope avoidance and the thrust
        # pulse already keep out of it (see the WALL block)
        wall_on = self.wall_lookahead > 0.0 and not self._school_on
        if wall_on:
            # THE WALL, anticipated (see the block at the top of the module).
            # It steers through the turn law below, not through this sum;
            # `w_bound`/`bb` are re-expressed from it only so the swim
            # burst's brake keeps reading what it always read: how hard the
            # edge is pressing, and whether the fish is heading into it.
            self._pond_free = None if big_urg is None else big_urg > 0.0
            try:
                w_urg, w_turn, w_auth, w_toward = self._wall_steer(
                    n, hd, swimming, dt
                )
            finally:
                self._pond_free = None
            if big_urg is not None:
                # a fish getting out of a big fish's way is steered by that
                # (the spot it makes for is inside the lit panel) — except
                # while the wall is turning it back from a wall it is heading
                # into, late: that turn is what keeps it on the panel
                relax = big_urg * np.where(
                    w_toward & (w_urg >= WALL_LATE), 0.0, 1.0)
                w_turn = w_turn * (1.0 - relax)
                w_auth = w_auth * (1.0 - relax)
            if ws is not None:
                # WORD SHAPES: THE WALL IS PAUSED, by the told envelope and
                # by exactly the mechanism above — EXCEPT where it is late
                # turning a fish back from a wall it is heading into. "The
                # pond gives way, the wall does not" (the BIG_AVOID block)
                # is what keeps a fish on the panel, and a shape is not
                # allowed to spend it; the loop sits well inside the lit
                # hexagon at any sane `word_shape_size` anyway.
                relax = ws["m_fish"] * np.where(
                    w_toward & (w_urg >= WALL_LATE), 0.0, 1.0)
                w_turn = w_turn * (1.0 - relax)
                w_auth = w_auth * (1.0 - relax)
            w_bound = w_urg * BOUND_W
            bb = np.where(w_toward, 1.0, -1.0)
            # a solo burst gives up its hold (and eases back) once the wall
            # presses hard — a fish does not sprint into a wall
            self.p_sb_t[:n] = np.where(
                w_urg >= SOLO_WALL_CUT, 0.0, self.p_sb_t[:n]
            )
        else:
            # the old pond edge — how much water is left straight ahead, in
            # px (ray/ellipse intersection in normalized space, read back as
            # a distance the fish would actually swim)
            for name in ("p_wsg", "p_wr", "p_wurg", "p_wcmd", "p_wauth"):
                getattr(self, name)[:n] = 0.0
            self.p_wph[:n] = np.nan
            spd = np.maximum(self.p_spd[:n], 1e-3)
            dxn = np.cos(hd) * spd / self.sx
            dyn = np.sin(hd) * spd / self.sy
            aa = dxn * dxn + dyn * dyn
            bb = rel_x * dxn + rel_y * dyn
            cc = rel_x ** 2 + rel_y ** 2 - bound * bound
            disc = np.maximum(bb * bb - aa * cc, 0.0)
            t_hit = np.where(
                cc >= 0.0, 0.0, (-bb + np.sqrt(disc)) / np.maximum(aa, 1e-12)
            )
            ahead_px = np.maximum(t_hit, 0.0) * spd
            need = TURN_CLEAR * 2.0 * self.turn_radius_px
            w_bound = np.clip(
                (need * BOUND_SOFT - ahead_px)
                / max(need * (BOUND_SOFT - 1.0), 1e-3),
                0.0, 1.0,
            ) * BOUND_W
            w_bound = np.where(swimming, w_bound, 0.0)
            if big_urg is not None:
                # the pond gives way to a fish getting out of a big fish's
                # way (its way out was chosen inside the lit panel)
                w_bound = w_bound * (1.0 - big_urg)
            if ws is not None:
                # ... and to the loop, the same way (the WORD SHAPES block)
                w_bound = w_bound * (1.0 - ws["m_fish"])
        # THE SWIM BURST'S BOUNDARY BRAKE - live only while a burst is
        # (self._burst / self._burst_tail), so ordinary swimming never
        # reaches it and is bit-for-bit what it always was. The steer above
        # is unchanged (`need`/`ahead_px`/`w_bound`, the turn radius and
        # TURN_GAIN are exactly what they were). What it fixes: the heading
        # correction converges on a fixed TIME constant (TURN_GAIN's own
        # proportional gain), so a fish moving at several times cruise
        # travels several times as far before its heading has caught up and
        # can clear the panel edge before the steer finishes turning it -
        # measured 2026-09-16, his report on the "Fish Swim Burst" flare:
        # "they always fly off the screen".
        #
        # While a burst is live the brake takes back ANY current speed above
        # cruise (burst, lunge, the drop boost - whatever produced it), but
        # ONLY on a fish whose heading has an outward component. The defect
        # is outward OVERSHOOT: a fish already heading back in is not
        # overshooting, so braking it buys no safety and costs the burst's
        # surge where it does no harm - which is also why an arriving fish
        # swimming in keeps its entry speed. "Outward" is measured against
        # the pond's own ellipse (`bb`, the ray term above), not as "away
        # from the centre": the pond is roughly 2:1, so a fish can point
        # toward the centre and still be crossing its top edge on the way
        # out. A fish below cruise is never sped up. `BOUND_BRAKE_AT` sits
        # well into the steer's own ramp, so a fish only mildly influenced
        # by the edge is left alone, and `BOUND_BRAKE_TAU` makes the
        # take-back a rate rather than a per-frame fraction.
        # `scripts/check_fish_burst_bounds.py` proves both sides: the
        # excursion held, and the burst's own speed away from an edge
        # untouched.
        if self._burst > 0.0 or self._burst_tail > 0.0:
            brake = np.clip(
                (w_bound / BOUND_W - BOUND_BRAKE_AT)
                / max(1.0 - BOUND_BRAKE_AT, 1e-3),
                0.0, 1.0,
            )
            braking = swimming & (brake > 0.0) & (bb > 0.0)
            if braking.any():
                extra_spd = np.maximum(self.p_spd[:n] - cruise, 0.0)
                take = 1.0 - (1.0 - brake) ** (dt / BOUND_BRAKE_TAU)
                self.p_spd[:n] = np.where(
                    braking, self.p_spd[:n] - extra_spd * take,
                    self.p_spd[:n],
                )
        inward = np.arctan2(-rel_y * self.sy, -rel_x * self.sx)
        if not wall_on:
            desired_x += np.cos(inward) * w_bound
            desired_y += np.sin(inward) * w_bound

        # mutual avoidance: a turn-away term, and ONLY a turn-away term.
        # It lands in the same desired-heading sum as every other steer and
        # is bounded by the same turn-rate clamp below, so it can never
        # reverse a fish on the spot, exceed the turn circle, or move one.
        #
        # A real fish swerves around what is IN FRONT of it — it does not
        # brake for something behind. So only neighbours inside the forward
        # arc count, and the answer is a lateral SWERVE (pick the side that
        # clears them), never a "point away from it" vector: pointing away
        # from a fish dead ahead asks for a 180, which the turn clamp then
        # spends a whole arc serving while the crossing happens anyway.
        #
        # SCOPE, deliberate: only ordinary swimming fish (mode < 2) steer
        # here AND only they count as neighbours, and the whole term is off
        # while a school is formed. The charge's school moves "almost
        # identically" and the drop's rush is deliberately chaotic — both are
        # authored choreography, not crowds to fix — so avoidance is never
        # allowed to argue with either.
        avoid_x = avoid_y = None
        if self.avoid_strength > 0.0 and n > 1 and not self._school_on:
            idx = np.flatnonzero(swimming)
            if idx.size > 1:
                ax_px = self.p_x[:n][idx] * self.sx
                ay_px = self.p_y[:n][idx] * self.sy
                dx = ax_px[None, :] - ax_px[:, None]   # me -> neighbour
                dy = ay_px[None, :] - ay_px[:, None]
                d = np.hypot(dx, dy)
                np.fill_diagonal(d, np.inf)
                sep = max(AVOID_SEP_BODIES * self._body_len_px(), 1e-3)
                close = np.clip(1.0 - d / sep, 0.0, 1.0)
                inv = 1.0 / np.maximum(d, 1e-3)
                ux, uy = dx * inv, dy * inv
                hx_ = np.cos(hd[idx])[:, None]
                hy_ = np.sin(hd[idx])[:, None]
                ahead = np.clip(hx_ * ux + hy_ * uy, 0.0, 1.0)
                side = np.sign(hx_ * uy - hy_ * ux)  # +1 = on my left
                w = close * ahead
                bias = -(side * w).sum(axis=1)       # + = swerve left
                strength = np.minimum(np.abs(bias), 1.0)
                swerve = hd[idx] + np.sign(bias) * strength * AVOID_MAX_TURN
                w_avoid = AVOID_W * self.avoid_strength * strength
                if ws is not None:
                    # WORD SHAPES: nose-to-tail spacing on the loop is
                    # AUTHORED (the entry rule, then even spacing), so a
                    # crowd fix would only argue with it — the same reason
                    # avoidance stays out of the charge's school
                    w_avoid = w_avoid * (1.0 - ws["m_fish"][idx])
                add_x = np.zeros(n, dtype=np.float32)
                add_y = np.zeros(n, dtype=np.float32)
                add_x[idx] = np.cos(swerve) * w_avoid
                add_y[idx] = np.sin(swerve) * w_avoid
                desired_x += add_x
                desired_y += add_y
                avoid_x, avoid_y = add_x, add_y
        if big_urg is not None:
            # ... and out of the big fish's way: a heading term like the
            # swerve above, through the same turn clamp — and, while the
            # wall has a fish, the same toward-the-water-only filter
            w_big = BIG_AVOID_W * self.big_fish_avoid * big_urg
            big_x = (np.cos(big_esc) * w_big).astype(np.float32)
            big_y = (np.sin(big_esc) * w_big).astype(np.float32)
            desired_x += big_x
            desired_y += big_y
            if avoid_x is None:
                avoid_x, avoid_y = big_x, big_y
            else:
                avoid_x, avoid_y = avoid_x + big_x, avoid_y + big_y

        # the school: everyone on the shared heading, plus minor variation
        if self._school_on:
            school_hd = self._school_hd + self.p_var[:n] * self.school_variation
            w_school = np.where(swimming, SCHOOL_W, 0.0)
            desired_x += np.cos(school_hd) * w_school
            desired_y += np.sin(school_hd) * w_school
            # ... and they must not CLUMP while they do it. See
            # SCHOOL_SPACING_W: omnidirectional separation, weighted well
            # under the shared heading, so unison survives the spread.
            sidx = np.flatnonzero(swimming)
            if sidx.size > 1:
                sx_px = self.p_x[:n][sidx] * self.sx
                sy_px = self.p_y[:n][sidx] * self.sy
                dx = sx_px[:, None] - sx_px[None, :]   # neighbour -> me
                dy = sy_px[:, None] - sy_px[None, :]
                d = np.hypot(dx, dy)
                np.fill_diagonal(d, np.inf)
                sep = max(SCHOOL_SEP_BODIES * self._body_len_px(), 1e-3)
                close = np.clip(1.0 - d / sep, 0.0, 1.0)
                inv = 1.0 / np.maximum(d, 1e-3)
                push_x = (dx * inv * close).sum(axis=1)
                push_y = (dy * inv * close).sum(axis=1)
                mag = np.hypot(push_x, push_y)
                keep = mag > 1e-6
                add_x = np.zeros(n, dtype=np.float32)
                add_y = np.zeros(n, dtype=np.float32)
                w_sep = SCHOOL_SPACING_W * np.minimum(mag[keep], 1.0)
                add_x[sidx[keep]] = push_x[keep] / mag[keep] * w_sep
                add_y[sidx[keep]] = push_y[keep] / mag[keep] * w_sep
                desired_x += add_x
                desired_y += add_y

        # THE DROP'S SWIRL (his addendum, beat 2): the rush fish swirl
        # around the centre of view for the drop's own duration. A
        # TANGENTIAL bias only — it is summed into the desired heading like
        # every other steering term and is then bounded by the same
        # turn-rate clamp, so it can never flip a fish on the spot.
        if self._rush_swirl > 0.0:
            rushers = (mode == 3) & (self.p_nocap[:n] == 1)
            if rushers.any():
                tangent = inward + np.pi / 2.0
                w_swirl = np.where(rushers, RUSH_SWIRL_W * self._rush_swirl,
                                   0.0)
                desired_x += np.cos(tangent) * w_swirl
                desired_y += np.sin(tangent) * w_swirl

        # DISPERSAL (mode 4). A swirling lull fish circles the centre of
        # view on a loose ring with its own chaotic heading noise; a leaking
        # fish turns from whatever it was doing to straight OUT of the
        # window across DISPERSE_TURN_S. Both are summed like every other
        # steer and bounded by the same turn-rate clamp below — a spiral out,
        # never a flip.
        if dispersing.any():
            outward = inward + np.pi
            if swirling.any():
                ring_px = LULL_SWIRL_RING * pond_px
                r_px = np.hypot(rel_x * self.sx, rel_y * self.sy)
                radial = np.clip((r_px - ring_px) / max(ring_px, 1e-3),
                                 -1.0, 1.0)
                chaos = hd + n_w * LULL_SWIRL_CHAOS
                tangent = inward + direction * np.pi / 2.0
                sw = np.where(swirling, 1.0, 0.0)
                desired_x += sw * (
                    np.cos(tangent) * LULL_SWIRL_W
                    + np.cos(inward) * LULL_SWIRL_RING_W * radial
                    + np.cos(chaos) * LULL_SWIRL_W * LULL_SWIRL_CHAOS_W
                )
                desired_y += sw * (
                    np.sin(tangent) * LULL_SWIRL_W
                    + np.sin(inward) * LULL_SWIRL_RING_W * radial
                    + np.sin(chaos) * LULL_SWIRL_W * LULL_SWIRL_CHAOS_W
                )
            if leaking.any():
                # the swirl-to-outward turn never spends more than a third of
                # the time the fish has left to be gone
                with np.errstate(invalid="ignore"):   # inf - inf, unused
                    span = np.where(
                        leaking, self.p_dl[:n] - self.p_lk[:n],
                        DISPERSE_TURN_S,
                    )
                span = np.where(np.isfinite(span), span, DISPERSE_TURN_S * 3)
                turn_s = np.clip(
                    span / 3.0, DISPERSE_MIN_LEFT_S, DISPERSE_TURN_S,
                )
                age = np.clip((self.t - self.p_lk[:n]) / turn_s, 0.0, 1.0)
                w_out = np.where(leaking, LULL_SWIRL_W * (0.25 + age), 0.0)
                desired_x += np.cos(outward) * w_out
                desired_y += np.sin(outward) * w_out

        # THE LULL'S KEEPERS: each steers for its own place in the search
        # (a leg's target, or the centre of view before the half-way mark);
        # in a pause it only drifts on its wander. Summed like every other
        # steer and bounded by the same turn clamp — the search's about-
        # faces are arcs too.
        if kst is not None and kst["seek"]:
            to_t = np.arctan2(
                (kst["ty"] - self.p_y[kidx]) * self.sy,
                (kst["tx"] - self.p_x[kidx]) * self.sx,
            )
            desired_x[kidx] += np.cos(to_t) * KEEP_SEEK_W
            desired_y[kidx] += np.sin(to_t) * KEEP_SEEK_W
        if kst is not None and kidx.size > 1:
            kx_px = self.p_x[kidx] * self.sx
            ky_px = self.p_y[kidx] * self.sy
            dx = kx_px[:, None] - kx_px[None, :]   # neighbour -> me
            dy = ky_px[:, None] - ky_px[None, :]
            d = np.hypot(dx, dy)
            np.fill_diagonal(d, np.inf)
            sep = max(kst["spacing_px"], 1e-3)
            close = np.clip(1.0 - d / sep, 0.0, 1.0)
            inv = 1.0 / np.maximum(d, 1e-3)
            desired_x[kidx] += (dx * inv * close).sum(axis=1) * KEEP_SEP_W
            desired_y[kidx] += (dy * inv * close).sum(axis=1) * KEEP_SEP_W
        if kst is not None:
            off_px = rel_y[kidx] * self.sy
            desired_y[kidx] -= KEEP_LEVEL_W * np.clip(
                off_px / max(KEEP_LEVEL_SPAN * self.r_height, 1e-3),
                -1.0, 1.0)

        darting = self._darting
        if darting is not None and darting.size == n:
            # THE POND REST: a darting fish turns toward its dart's heading
            aim = np.nan_to_num(self.p_dhd[:n])
            desired_x += np.where(darting, np.cos(aim) * DART_W, 0.0)
            desired_y += np.where(darting, np.sin(aim) * DART_W, 0.0)
        # WORD SHAPES: THE LOOP'S OWN STEER. Summed like every other term
        # and bounded by the same turn clamp below, so swimming onto the
        # line is an arc like every other about-face here. At FULL weight
        # from the first frame of the form — a fish heads for its entry
        # straight away and the envelope paces only its speed — and let go
        # over the first half of the release (`grip`).
        if ws is not None and ws["tx"] is not None:
            wsi = ws["idx"]
            to_loop = np.arctan2(
                (ws["ty"] - self.p_y[wsi]) * self.sy,
                (ws["tx"] - self.p_x[wsi]) * self.sx,
            )
            w_loop = WS_SEEK_W * ws["grip"]
            desired_x[wsi] += np.cos(to_loop) * w_loop
            desired_y[wsi] += np.sin(to_loop) * w_loop
        desired = np.arctan2(desired_y, desired_x)
        d_hd = _wrap_pi(desired - hd)

        # beat/spike turn kicks (never a snap — clipped by the turn rate
        # below like every other steering term)
        jog_eff = self.speed_jog * rscale
        if spike > 0.12 and self._spike_cool <= 0.0 and jog_eff > 0.0:
            self._spike_cool = SPIKE_COOL_S
            common = self._rng.uniform(-1.0, 1.0, 2)
            per = self._rng.uniform(-1.0, 1.0, (2, n))
            k_ang = (1.0 - jiggle) * common[0] + jiggle * per[0]
            k_rad = (1.0 - jiggle) * common[1] + jiggle * per[1]
            self.p_jog[:n] += k_ang * spike * jog_eff * 3.0
            self.p_ro[:n] += np.abs(k_rad) * spike * jog_eff * 0.5
        self.p_jog[:n] *= np.float32(0.5 ** (dt / 0.2))
        self.p_ro[:n] *= np.float32(0.5 ** (dt / 0.3))

        # the current's steady swirl bias (Orbits' ring spin, as a curve)
        swirl = direction * self.spin * 2 * np.pi * self.base_speed

        omega_max = self.p_spd[:n] / self.turn_radius_px
        if ws is not None:
            # WORD SHAPES: the turn arc TIGHTENS, by the told envelope (the
            # WS_TURN_X block). Exactly the pre-drop's own mechanism one
            # mechanism over — the clamp still bounds every steering term,
            # it is just a tighter circle while the shape runs.
            omega_max = omega_max / np.maximum(
                1.0 - (1.0 - WS_TURN_X) * ws["m_fish"], 1e-3)
            # ROW W6.1: ... and no more than WS_TURN_MAX_RAD_FRAME of
            # heading in ONE RENDERED FRAME, so the clamp still means an
            # ARC at his crystal's 30 fps (that constant's own block).
            omega_max = np.minimum(
                omega_max, WS_TURN_MAX_RAD_FRAME / max(dt, 1e-6))
        if kst is not None and "turn" in kst:
            # THE PRE-DROP: the keepers turn on PRE_DROP_TURN of their circle
            omega_max[kidx] = omega_max[kidx] / max(float(kst["turn"]), 1e-3)
        if big_urg is not None:
            # a startled fish that has to come about turns the way that
            # swings it AWAY from the big fish's line, never the shorter way
            # through it ...
            swing = big_away * np.cos(hd)       # + = turning that way is away
            flip = (
                (big_urg > 0.0) & (np.abs(d_hd) > np.pi / 2)
                & (np.abs(swing) > 0.05) & (np.sign(swing) != np.sign(d_hd))
            )
            d_hd = np.where(
                flip, d_hd - np.sign(d_hd) * 2.0 * np.pi, d_hd
            )
            # ... and as fast as its own turn circle allows (still clipped
            # to it below)
            d_hd = d_hd * (1.0 + BIG_TURN_BOOST * big_urg)
        turn_gain = TURN_GAIN
        bias = swirl + self.p_jog[:n]
        if ws is not None:
            # WORD SHAPES: the heading gain is RAISED under a full shape
            # (still clipped to the turn circle below, so no fish ever turns
            # tighter than it can — "tightened WITHIN the clamp"), and the
            # current's steady swirl and the beat's turn kicks hand over to
            # the loop: the loop IS the current while a shape runs, and a
            # kick is exactly the sudden heading shift his note rules out.
            #
            # ROW W6.1 — AND IT IS THE EXACT FIRST-ORDER STEP, NOT THE
            # PROPORTIONAL ONE. `omega = d_hd * gain` then
            # `hd += omega * dt` corrects `gain * dt` of the heading error
            # in one frame, so at the shaped gain of
            # TURN_GAIN * (1 + WS_TURN_GAIN_X) = 39 /s it corrects 0.65 of
            # it at 60 fps — the rate every W5.5 number was measured at —
            # and 1.30 at HIS CRYSTAL'S 30: PAST the target, with the error
            # alternating sign every frame and the clamp no longer binding
            # (at WS_TURN_X 0.10 the clamp in force is ~140 rad/s at the x3
            # pace). Measured at 30 fps before this was written: 18.6 to
            # 27.7 nose WAGS per fish-second against a 0.5 bar, the head's
            # p95 2.75-8.18 cell pitches from the band while its middle sat
            # at 0.06-0.34 — his "the fish seem to jitter out of the
            # outline", drawn by `_draw_bodies`' own straight extrapolation
            # of the CURRENT heading — and, worse, fish up to 14.5 px OFF
            # THE LIT PANEL, because an alternating steer defeats the wall's
            # glance too (section 9's own two depths).
            #
            # So the step a shape takes is the closed form of the same
            # first-order law: `k = 1 - exp(-gain_ws * dt)` of the error per
            # frame, commanded as a rate `d_hd * k / dt`. NEVER more than
            # the error, at any dt — 0.73 at 30 fps, 0.48 at 60 — so there
            # is no alternation to excite and the SETTLING TIME rather than
            # the per-frame step is what `WS_TURN_GAIN_X` now names. It is
            # BLENDED by `m_fish`, so at m = 0 this is `TURN_GAIN * 1.0 +
            # (...) * 0.0`, the ordinary expression to the bit, and the
            # whole block is gated on `ws is not None` exactly as every
            # shape block is (section 1, both frame rates).
            m_f = ws["m_fish"]
            gain_ws = TURN_GAIN * (1.0 + WS_TURN_GAIN_X)
            k_ws = -np.expm1(-gain_ws * dt) / max(dt, 1e-6)
            turn_gain = TURN_GAIN * (1.0 - m_f) + k_ws * m_f
            bias = bias * (1.0 - m_f)
        omega = (
            d_hd * turn_gain
            + np.where(steered & ~keeping, bias, 0.0)
        )
        if wall_on:
            # the wall takes over the steering while it turns a fish, at a
            # CURVATURE (a fraction of its own tightest turn), so the curve
            # is the same shape at any speed — all but a neighbour's swerve:
            # a fish sweeping along the wall still dodges one coming the
            # other way, and the glance re-plans from wherever that leaves it
            omega = omega * (1.0 - w_auth) + w_turn * omega_max
            if avoid_x is not None:
                # ... but only toward the water: a swerve that would turn it
                # back into the wall is dropped, so a crowd can never push a
                # fish off the panel (measured: allowed both ways, his
                # House Fish shoal was shoved up to 34 px off it)
                dodge = _wrap_pi(np.arctan2(
                    np.sin(hd) * WANDER_W + avoid_y,
                    np.cos(hd) * WANDER_W + avoid_x,
                ) - hd)
                away = np.sign(self.p_wsg[:n])
                dodge = np.where(dodge * away > 0.0, dodge, 0.0)
                omega = omega + w_auth * dodge * TURN_GAIN * WALL_DODGE
        # THE turn-circle guarantee: no steering term, kick or phase can
        # turn a fish faster than its own radius allows, so an about-face
        # is always an arc and never a flip.
        omega = np.clip(omega, -omega_max, omega_max)
        omega = np.where(steered, omega, 0.0)
        if self._peel_age is not None:
            # THE PEEL (PEEL_S): an adopted fish still turns at the rate
            # it inherited, easing into its own steering
            self._peel_age += dt
            w = min(self._peel_age / PEEL_S, 1.0)
            if w >= 1.0:
                self._peel_age = None
                self.p_peel[:n] = np.nan
            else:
                w = w * w * (3.0 - 2.0 * w)
                pe = np.isfinite(self.p_peel[:n])
                omega = np.where(
                    pe, (1.0 - w) * np.nan_to_num(self.p_peel[:n]) + w * omega,
                    omega)
        # the rate actually applied — published on the hand-off (the
        # shoal-burst plan §5.1: Fish computed this every frame and threw
        # it away, so a cloud leaving a turning fish flew dead straight)
        self.p_om[:n] = omega.astype(np.float32)
        self.p_hd[:n] = _wrap_pi(hd + omega * dt)
        hd = self.p_hd[:n]

        # ── integrate ───────────────────────────────────────────────────
        vx_px = np.cos(hd) * self.p_spd[:n]
        vy_px = np.sin(hd) * self.p_spd[:n]
        swim_vx = vx_px
        swim_vy = vy_px
        self._flow_px = 0.0
        self._flow_py = 0.0
        # THE CLAMP, and what `camera_follow` does to it. Before the window
        # existed this removed the school's whole travel from every swimming
        # fish and pushed the same amount through the water instead: the
        # shoal was pinned and the wake streamed at exactly the swim speed.
        # `camera_follow` hands that travel back — the fish keep this
        # fraction of it as REAL world travel and the window follows them
        # for it, at its own lagging pace. At 0 the clamp is whole and the
        # window never moves, which is master, expression for expression.
        hold = float(np.clip(1.0 - self.camera_follow, 0.0, 1.0))
        if self._school_on and hold > 0.0:
            sch = (
                np.cos(self._school_hd) * cruise * hold,
                np.sin(self._school_hd) * cruise * hold,
            )
            vx_px = np.where(swimming, vx_px - sch[0], vx_px)
            vy_px = np.where(swimming, vy_px - sch[1], vy_px)
            self._flow_px = -sch[0]
            self._flow_py = -sch[1]
        self.p_x[:n] += vx_px * dt / self.sx
        self.p_y[:n] += vy_px * dt / self.sy

        # ── body trail push ────────────────────────────────────────────
        # A new sample every BODY_TRAIL_STEP_PX of the fish's own swimming
        # travel (its UNCLAMPED velocity), never every frame — see the
        # BODY_TRAIL_* comment near the top of the module for why arc
        # length, not time. The path is recorded in the water the fish
        # swims through: whatever the school clamp removed from a fish's
        # world travel went into the water (`_flow_px`/`_flow_py`, the
        # wake's own carry), so that fish's stored samples ride along with
        # it. Every moving fish records its path, whatever its mode. Each
        # sample is laid at the exact point along this frame's own travel
        # where the threshold was crossed (as many as the frame crossed,
        # oldest first), so `p_trail_acc` is always exactly the path
        # distance back to trail[0].
        if vx_px is not swim_vx:
            self.p_trail_x[:n] += ((vx_px - swim_vx) * dt / self.sx)[:, None]
            self.p_trail_y[:n] += ((vy_px - swim_vy) * dt / self.sy)[:, None]
        travelled = np.hypot(swim_vx, swim_vy) * dt
        self.p_trail_acc[:n] += travelled
        step_x = swim_vx * dt / self.sx
        step_y = swim_vy * dt / self.sy
        for _ in range(BODY_TRAIL_LEN):
            push = self.p_trail_acc[:n] >= BODY_TRAIL_STEP_PX
            if not push.any():
                break
            pidx = np.flatnonzero(push)
            back = np.clip(
                (self.p_trail_acc[pidx] - BODY_TRAIL_STEP_PX)
                / np.maximum(travelled[pidx], 1e-6),
                0.0, 1.0,
            )
            self.p_trail_x[pidx, 1:] = self.p_trail_x[pidx, :-1]
            self.p_trail_y[pidx, 1:] = self.p_trail_y[pidx, :-1]
            self.p_trail_x[pidx, 0] = self.p_x[pidx] - step_x[pidx] * back
            self.p_trail_y[pidx, 0] = self.p_y[pidx] - step_y[pidx] * back
            self.p_trail_acc[pidx] -= BODY_TRAIL_STEP_PX

        entering = mode == 1
        if (entering | dispersing | keeping).any():
            self.p_enter[:n] = np.where(
                entering
                | ((dispersing | keeping) & (self.p_enter[:n] < 1.0)),
                self.p_enter[:n]
                + dt * self.p_erate[:n] / max(self.enter_time, 0.05),
                self.p_enter[:n],
            )
            inside = np.hypot(
                self.p_x[:n] - cnx, self.p_y[:n] - cny
            ) <= bound
            arrived = np.flatnonzero(
                entering & inside & (self.p_enter[:n] >= 1.0)
            )
            if arrived.size:
                self.p_mode[arrived] = 0
        leaving = mode == 2
        if leaving.any():
            self.p_leave[:n] += np.where(leaving, dt, 0.0)

        # the window moves last, once the water it is looking at has moved
        self._step_camera(dt, cruise)
        if kidx is not None:
            # THE LULL'S KEEPERS RIDE THE WINDOW. It eases home from wherever
            # the charge left it (up to 1.4x cruise) while a keeper swims at
            # search speed, so a keeper left in the world would be dragged
            # across — and off — the panel by the view's own motion. They
            # hold their place ON SCREEN instead (their recorded path moves
            # with them, so the body does not stretch); the water and its
            # wake slide past underneath, which is what the window moving
            # looks like.
            dcx = (self.cam_px - self._cam_px_prev) / max(self.sx, 1e-6)
            dcy = (self.cam_py - self._cam_py_prev) / max(self.sy, 1e-6)
            if dcx or dcy:
                self.p_x[kidx] += dcx
                self.p_y[kidx] += dcy
                self.p_trail_x[kidx] += dcx
                self.p_trail_y[kidx] += dcy

        # ── flap ────────────────────────────────────────────────────────
        speed_norm = np.clip(self.p_spd[:n] / max(cruise, 1e-3), 0.0, 3.0)
        acc_norm = np.clip(self.p_acc[:n] / FLAP_ACCEL_REF, -1.5, 1.5)
        flap_scale = np.clip(
            FLAP_BASE
            + FLAP_SPEED_GAIN * speed_norm
            + self.flap_accel * acc_norm,
            FLAP_MIN, FLAP_MAX,
        )
        half_w = np.clip(
            self._half_width_px()
            * (1.0 + 0.8 * self.size_audio * rscale * impulse * gain),
            0.4, float(KERNEL_R),
        )
        if self._size_age is not None:
            self._size_age += dt
            ease_t = max(self.enter_time, 0.05)
            if self._size_age >= ease_t:
                self._size_age = None
                self._size_from = None
            else:
                w = self._size_age / ease_t
                w = w * w * (3.0 - 2.0 * w)
                half_w = (
                    half_w * w
                    + self._half_width_px(self._size_from) * (1.0 - w)
                )
        flap_amp = self.flap_amount * half_w * self.body_aspect * flap_scale
        flap_freq = self.flap_rate * (0.4 + 0.6 * speed_norm) * (
            1.0 + FLAP_BURST_X * self._burst
        ) * (1.0 + SOLO_FLAP_X * self.p_sb[:n])
        if want_tail is not None:
            # what is drawn IS what pushes: the tail drive's own size and
            # rate are the flap for every tail-driven fish
            flap_amp, flap_freq = self._tail_drive_flap(
                pulse_eligible, flap_amp, flap_freq, half_w, tail_w
            )
        if ws is not None and WS_FLAP_X is not None:
            # WORD SHAPES, ROW W6.1: THE FLAP GLIDES ON THE LINE
            # (WS_FLAP_X's own block). Drawing only — the tail drive's
            # THRUST is untouched, so nothing about how a fish moves
            # changes here; and it lands before the wake deposit below, so
            # a gliding fish lays a narrower wake too, which is the same
            # fact about its tail.
            glide = (self.flap_amount * half_w * self.body_aspect
                     * TAIL_AMP_GLIDE * WS_FLAP_X)
            flap_amp = flap_amp + (glide - flap_amp) * ws["m_fish"]
        self.p_flap[:n] = (
            self.p_flap[:n] + 2 * np.pi * flap_freq * dt
        ) % (2 * np.pi * 64)

        # ── colour / brightness ─────────────────────────────────────────
        count = max(self.particle_count, 1)
        grad = (
            ((self.p_slot[:n].astype(np.float32) - self.color_shift) % count)
            / count
            + self.roll_total
        ) % 1.0
        blend_src = self.p_grad_from[:n]
        blend = entering & np.isfinite(blend_src)
        if blend.any():
            prog = np.clip(self.p_enter[:n], 0.0, 1.0)
            gdiff = (blend_src - grad + 0.5) % 1.0 - 0.5
            grad = np.where(blend, (grad + gdiff * (1.0 - prog)) % 1.0, grad)
        keep_grad = ~(swimming) | (self.p_nocap[:n] == 1)
        self.p_grad[:n] = np.where(keep_grad, self.p_grad[:n], grad)

        br_eff = self.brightness_audio * rscale
        bright = np.clip(
            (1.0 - 0.45 * min(br_eff, 1.0))
            * (1.0 + 1.2 * br_eff * impulse * gain),
            0.0, 1.0,
        )
        # a fish caught mid-arrival by a dispersal keeps the fade-in it had
        # reached (and keeps rising): nothing about leaving ever dims it
        fade_in = np.where(
            entering | dispersing | keeping,
            np.clip(self.p_enter[:n] * 3.3, 0.0, 1.0), 1.0,
        )
        fade_out = np.where(
            leaving,
            np.clip(
                1.0 - self.p_leave[:n] / np.maximum(self.p_lfade[:n], 0.05),
                0.0, 1.0,
            ),
            1.0,
        )
        bright = bright * fade_in * fade_out
        self.p_bright[:n] = bright

        # ── wake deposit (every frame, off real motion) ─────────────────
        # Continuous, like Orbits' own body splats — there is no per-beat
        # stamp any more. The flap still shapes it: it modulates the deposit
        # (see WAKE_FLAP_*), so the wake keeps the body's own texture without
        # anything being drawn as a shape.
        laying = np.flatnonzero(bright > 0.02)
        if laying.size and self.ripple_amount > 0.0 and self.wake is not None:
            body_len = half_w[laying] * 2.0 * self.body_aspect
            # the deposit is laid at the TRUE tail (the same recorded-path
            # point _draw_bodies draws, via _trail_tail_point), sized by the
            # motion that made it: the body's own length and the tail's
            # lateral throw. WHERE IT LANDS CHANGED in fm/spotfx-fish-body-
            # trails-head-tail-thrust, and not only through a turn: the
            # wake buffer is SCREEN space, but the old deposit
            # (`cx + p_x*sx - cos(hd)*len/2`) never subtracted the window
            # origin the body is drawn with — so whenever the view had
            # moved (every charge and lull at camera_follow > 0) the whole
            # wake was laid off to one side of its school by the window's
            # own displacement, tens of px. It now sits under the school.
            tail_px, tail_py = self._trail_tail_point(
                laying, self.p_x[:n][laying], self.p_y[:n][laying], body_len,
            )
            sizes = np.minimum(
                WAKE_R0_BODY * body_len + WAKE_R0_FLAP * flap_amp[laying],
                WAKE_R_MAX_BODY * body_len,
            )
            sizes = np.clip(
                sizes * max(float(self.ripple_width), 0.5),
                0.6, float(SPLAT_KERNEL_R) * 0.5,
            ).astype(np.float32)
            pulse = (
                WAKE_FLAP_FLOOR
                + WAKE_FLAP_GAIN * np.abs(np.sin(self.p_flap[:n][laying]))
            )
            amp = (
                self.ripple_amount
                * (
                    RIPPLE_BASE
                    + RIPPLE_SPEED_GAIN
                    * np.clip(
                        (speed_norm[laying] - RIPPLE_SPEED_FLOOR)
                        / RIPPLE_SPEED_SPAN,
                        0.0, 1.0,
                    )
                )
                * pulse
                * bright[laying]
                * min(dt * WAKE_DEPOSIT_HZ, 1.0)
            ).astype(np.float32)
            if ws is not None and WS_WAKE_FADE < 1.0:
                # WORD SHAPES, ROW W6.1: the ORDINARY wake eases out of the
                # water a shaped fish swims through (WS_WAKE_FADE's own
                # block) — per fish, by its own `m_fish`, so a fish that is
                # not on the loop keeps its whole wake.
                amp = (amp * (1.0 - (1.0 - WS_WAKE_FADE)
                              * ws["m_fish"][laying])).astype(np.float32)
            self._deposit_wake(
                tail_px, tail_py, amp, sizes, self.p_grad[:n][laying]
            )
        # WORD SHAPES — THE WATER TRACE (P2 A, few fish only): the same
        # deposit rule, laid at the loop point each fish's own place has
        # reached rather than at its tail, in the fish's own colour (so the
        # trace is the colour set's, through `_deposit_wake`'s own palette
        # rule), faded in and out by the told envelope.
        if (ws is not None and ws["trace"] is not None
                and self.ripple_amount > 0.0 and self.wake is not None):
            trace_x, trace_y, which = ws["trace"]
            body_len = half_w[which] * 2.0 * self.body_aspect
            t_sizes = np.clip(
                WS_TRACE_SIZE_BODY * body_len * max(
                    float(self.ripple_width), 0.5),
                0.6, float(SPLAT_KERNEL_R) * 0.5,
            ).astype(np.float32)
            t_amp = (
                self.ripple_amount * WS_TRACE_AMP * ws["m"]
                * (RIPPLE_BASE + RIPPLE_SPEED_GAIN)
                * np.clip(bright[which], 0.0, 1.0)
                * min(dt * WAKE_DEPOSIT_HZ, 1.0)
            ).astype(np.float32)
            self._deposit_wake(
                np.asarray(trace_x, dtype=np.float64),
                np.asarray(trace_y, dtype=np.float64),
                t_amp, t_sizes, self.p_grad[:n][which],
            )
        self._step_wake(dt)
        self._apply_lull_dark()

        # ── render ──────────────────────────────────────────────────────
        half_life = self._trail_half_life()
        self.trail *= np.float32(0.5 ** (dt / half_life))

        # THE TRAIL IS FED THE FISH'S TRUE (UNGAINED) BRIGHTNESS, NEVER THE
        # SCATTER'S CROSSFADE COMPENSATION (hotfix 2026-09-16, his live
        # report: trails "at least 3 times too long" and "about 50% too
        # big" the same night #274 shipped). The scatter gain
        # (`self._scatter["gain"]`, up to 1/TRANSITION_GAIN_FLOOR = 3.33x)
        # exists so a dispersing fish does not visibly dim as the incoming
        # effect's crossfade weight climbs — but `self.trail` is a
        # PERSISTENT, DECAYING buffer (`*= 0.5**(dt/half_life)` above), so
        # depositing the gained value into it made every departing fish's
        # smear start from up to 3.33x its true peak: an exponential decay
        # from a 3.33x higher start takes ~1.7 extra half-lives to cross the
        # same visible-brightness floor (the reported "3x" persistence), and
        # a brighter smear crosses that same floor, after the wake's own
        # diffusion, over a wider area (the reported "50% too big"). ONE
        # cause produces both numbers, which is why this is fixed at its
        # root rather than by shortening the wake's half-life or lowering
        # TRANSITION_GAIN_FLOOR — either of those would mask it and cost
        # him the anti-dimming the gain exists for, or his trails generally.
        #
        # So the body is drawn TWICE only while scattering: once at its true
        # brightness, which is what lands in `self.trail` and therefore
        # governs every future frame's decay and diffusion exactly as
        # before #274; and, ONLY for THIS frame's composited output below,
        # a second time at the gained brightness, maxed against the (true)
        # trail so the current frame still reads fully anti-dimmed. The
        # boosted value itself is never stored — next frame's decay starts
        # from the true value alone, so it cannot compound.
        frame = np.zeros_like(self.trail)
        visible = np.flatnonzero(bright > 0.0)
        # WORD SHAPES — HIS NOTE, verbatim: "We may need to boost the trail
        # brightness and lower decay briefly to get it to show better." The
        # decay is `_trail_half_life` above; this is the brightness, and it
        # goes in through `_clip_body_layer`'s WHOLE-pixel ceiling (the
        # scatter's own, which keeps the colour) rather than a per-channel
        # clip, so a boosted smear is a brighter smear and never a whiter
        # one — asked for by the `_ws_gain_clip` flag, for the signature
        # reason that method's own docstring gives. At gain 1.0 — every untold frame — `body_bright` IS `bright`,
        # the same object, so nothing about this frame differs.
        ws_gain = self._trail_gain()
        body_bright = bright
        if ws_gain > 1.0:
            body_bright = bright * np.float32(ws_gain)
        # a pausing keeper LOOKS about: its head swings, its path does not
        # (drawing only — the travel heading above is untouched)
        hd_draw = hd
        if kst is not None and np.any(kst["look"]):
            hd_draw = hd.copy()
            hd_draw[kidx] = hd[kidx] + kst["look"]
        if visible.size:
            self._draw_bodies(
                frame, visible,
                self.p_x[:n][visible], self.p_y[:n][visible],
                hd_draw[visible], body_bright[visible], half_w[visible],
                flap_amp[visible], self.p_grad[:n][visible],
            )
        self._ws_gain_clip = ws_gain > 1.0
        try:
            np.maximum(self.trail, self._clip_body_layer(frame),
                       out=self.trail)
        finally:
            self._ws_gain_clip = False

        body_out = self.trail
        if self._scatter is not None and visible.size:
            gained_frame = np.zeros_like(self.trail)
            gained = body_bright * np.float32(self._scatter["gain"])
            self._draw_bodies(
                gained_frame, visible,
                self.p_x[:n][visible], self.p_y[:n][visible],
                hd_draw[visible], gained[visible], half_w[visible],
                flap_amp[visible], self.p_grad[:n][visible],
            )
            body_out = np.maximum(
                self.trail, self._clip_body_layer(gained_frame)
            )

        self.p_x0[:n] = self.p_x[:n]
        self.p_y0[:n] = self.p_y[:n]

        # retire departed fish once fully off-panel (or, ejecta only, faded).
        # A dispersing fish is retired the moment its WHOLE body is past the
        # panel edge — never by brightness, and never before it is gone.
        gone = leaving | rushing | dispersing
        if gone.any():
            px = self.cx + self.p_x[:n] * self.sx - self.cam_px
            py = self.cy + self.p_y[:n] * self.sy - self.cam_py
            off = (
                (np.abs(px - self.cx) > (self.r_width + 12))
                | (np.abs(py - self.cy) > (self.r_height + 12))
            )
            dead = (leaving & ((self.p_leave[:n] >= self.p_lfade[:n]) | off))
            dead = dead | (rushing & off)
            if dispersing.any():
                m = (
                    float(np.max(half_w)) * 2.0 * self.body_aspect
                    + DISPERSE_OFF_MARGIN
                )
                gone_vis = (
                    (px < -m) | (px > self.r_width - 1 + m)
                    | (py < -m) | (py > self.r_height - 1 + m)
                )
                dead = dead | (dispersing & gone_vis)
            if dead.any():
                self._compact(~dead)

        # the big fish first: it lays its wake into self.wake, composited
        # just below
        big = self._big_fish_layer(dt, body_out)
        self._composite(body_out, self.wake, big)

    def _composite(self, body, wake, big):
        """The final mix into `self.matrix`: the canvas plus the BODIES, and
        the WATER under them (the wake, and the big fish behind the shoal)
        met by `wake_blend` — see the WAKE COLOUR block at the top of this
        module. Every path that writes the matrix comes through here (the
        draw, the held-transition `_fade_only`, the outgoing
        `_draw_collapse`), so none of them can mix the layers differently.
        `add` is the pre-2026-10-26 mix, operation for operation."""
        fish = np.asarray(self.matrix, dtype=np.float32) + body
        if self.wake_blend == "add":
            out = fish
            if wake is not None:
                out = out + wake
            if big is not None:
                out = out + big
        else:
            water = None
            for layer in (wake, big):
                if layer is not None:
                    water = layer if water is None else water + layer
            if water is None:
                out = fish
            elif self.wake_blend == "lighten":
                out = np.maximum(fish, _hue_clip(water))
            else:
                # under: a body hides the water behind it in proportion to
                # how lit the body is
                fish = np.clip(fish, 0, 255)
                alpha = _channel_peak(fish) / 255.0
                out = fish + _hue_clip(water) * (1.0 - alpha)
        self.matrix = Image.fromarray(
            np.clip(out, 0, 255).astype(np.uint8), "RGB"
        )

    def _clip_body_layer(self, frame):
        """The body layer's 255 ceiling. Ordinary swimming clips each channel
        on its own; a scatter's gained bodies — and a WORD SHAPE's boosted
        trail deposit — are scaled down as a whole wherever the brightest
        channel passes 255, keeping the colour.

        THE WORD SHAPE'S CASE RIDES A FLAG (`_ws_gain_clip`) RATHER THAN AN
        ARGUMENT, deliberately: two check scripts already substitute or wrap
        this method by its one-positional-argument signature
        (`check_fish_big_fish_avoid.py`'s `_Bodies` spy and
        `check_fish_disperse.py`'s per-channel control), and a new keyword
        broke both. Keeping the signature keeps those proofs working."""
        if self._scatter is None and not self._ws_gain_clip:
            return np.minimum(frame, 255.0)
        peak = frame.max(axis=2, keepdims=True)
        return np.where(
            peak > 255.0,
            frame * (np.float32(255.0) / np.maximum(peak, np.float32(1.0))),
            frame,
        )

    def _apply_lull_dark(self):
        """HIS LULL CLOCK's last two thirds: ripples only, then DARK.

        An exponential half-life can never reach zero and his ask is DARK,
        so the wake (and the body trail under it) is ramped out across
        [LULL_DARK_FROM, LULL_DARK_AT] and held at nothing until the drop.
        See _lull_step.
        """
        if self._phase != "lull" or self._lull_state is None:
            return
        dark = np.float32(self._lull_state.get("dark", 1.0))
        if dark >= 1.0:
            return
        if self.wake is not None:
            self.wake *= dark
        if self.trail is not None:
            self.trail *= dark

    def _fade_only(self, dt):
        """Decay the trail AND the wake, and composite — the held-transition
        path. The wake is a live buffer, so leaving it out here would park a
        frozen smear on the panel for the whole hold."""
        half_life = self._trail_half_life()
        self.trail *= np.float32(0.5 ** (dt / half_life))
        self._rest_level = 0.0      # nothing swims here, so nothing rests
        self._darting = self._rest_free = None
        # An empty panel is exactly when the lull's last two thirds run, so
        # the window still has to ease home and the clock still has to run.
        self._step_camera(dt, self.cruise_px)
        self._step_wake(dt)
        self._apply_lull_dark()
        big = self._big_fish_layer(dt, self.trail)
        self._composite(self.trail, self.wake, big)
