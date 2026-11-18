import logging
import math

import numpy as np
import voluptuous as vol
from PIL import Image

import fx.effects.particle_handoff as particle_handoff
import fx.effects.pre_drop as pre_drop
from fx.effects import drop_colour_resample, lull_dark, lull_handoff, \
    phase_grammar, strip_phase, word_shape_keys, word_shapes
from fx.effects.audio import AudioReactiveEffect
from fx.effects.twod import Twod
from fx.utils import nonlinear_log
from fx.virtuals import virtual_id_validator

_LOGGER = logging.getLogger(__name__)

# div zero protection
epsilon = 1e-6

# fallback source when none is configured or the configured one is missing
DEFAULT_SOURCE_VIRTUAL = "radial-dummy"

# narrowest band the implode warp compresses the pattern into (norm radius)
IMPLODE_MIN_W = 0.10

# Admiral order, 2026-10-06 ("reduce the maximum speed of rotation of Star
# by 20 percent"): ONE scale applied to every source that contributes to
# Star's rotation speed, so the *ceiling* — not just a default — drops by
# a uniform 20% everywhere it can be reached. Before this change the
# reactive ceiling (spin config at its own max 1.0, full audio impulse)
# was 6 rev/s (see radial-effect skill / AGENTS.md: rev/s = 6 × impulse ×
# spin²); after, 4.8 rev/s. A binding/config already set to spin's own
# max (1.0) reaches the new, lower ceiling automatically — the scale is
# applied to the OUTPUT, never to spin's own [-1, 1] input range, so
# nothing about how a binding reaches "max" needs to change.
#
# HALVED AGAIN 2026-11-18 (Admiral order, data/star-curve-study/report.md:
# "cut the max angle/frame the star can rotate, but let's scale it all down
# by 50%. So slow the star rotation by 50% at all speeds, including the
# burst speeds, not just the static speed", then "D2 and all recs"):
# 0.8 -> 0.4, so the reactive ceiling is 2.4 rev/s and his usual fire
# (spin 0.70) means 0.44 rev/s instead of 0.88. THIS IS WHAT HALVES THE
# BURSTS TOO: a bass hit is not a separate quantity, it is this same law at
# a high impulse (data/star-spin-smooth/report.md F3), so one scale covers
# "all speeds" — the static speed, the bursts, and the charge spin-up
# (CHARGE_SPIN_REV_S below) together. The per-frame CAP is halved with it,
# below, because the cap is what clips the loudest fires and would
# otherwise hold them at the old angle. Three mirrors of the derived
# base_rotation ceiling (2.0 × this scale) must move in step:
# config/effect_params.json's declared `max` and spectra/models/scene.py's
# RADIAL_BASE_ROTATION_MAX. Nothing else needed an edit — the spin values a
# flare patches (0.25 / 0.55) and the fire binding (0.4–1.0) are INPUTS to
# the squared law, so they produce half of what they used to on their own.
ROTATION_SPEED_SCALE = 0.4

# charge/lull/drop choreography (SpotFX drives `phase` + ramps
# `phase_progress`; see _phase_step)
# extra rev/s at full charge — scaled by ROTATION_SPEED_SCALE (was 0.9)
CHARGE_SPIN_REV_S = 0.9 * ROTATION_SPEED_SCALE

# ── THE STAR IMPROVE PLAN (2026-11-12, data/star-improve-plan/plan.md; the
# Admiral: "I want it to be able to spin from the beginning. It should also
# cap the max speed it can spin to 70% of what it is now, but it shouldn't
# slow down at lower speeds. Also, the amount of star should dynamically
# change with the music ... constantly be flowing and bouncing between the
# top and bottom values", and after the star grid: "let's do -.2 to +.4 as
# the standard range they sway between. I want it to go through 0").
#
# THE CAP: a hard clamp on the TOTAL per-frame advance of the pattern — the
# audio spin, the base floor and the charge spin-up together. Identity
# below it: a frame that advances less is untouched. First shipped as a
# rate (ROTATION_CAP_REV_S = 70% of the old 4.8 rev/s ceiling = 3.36 rev/s);
# re-expressed per RENDERED FRAME by the spin smooth plan below, because
# what the eye cannot follow is a jump per frame, not a rate.
#
# ── THE SPIN SMOOTH PLAN (2026-11-12, data/star-spin-smooth/plan.md; the
# Admiral, after the star improve plan went live: "it is too jerky in it's
# spin especially on big bass hits. the burst speed is too fast and fades
# too fast. I think sometimes it moves so fast it's hard to tell it moved.
# We need to cap the burst speed ... it shouldn't be jerky, but it should
# be dynamic"; after the analysis page: "the burst fade should be snappier
# at higher energies and lazier at low energies. do 18 degrees per frame
# for now").
#
# The crystal renders at 30 fps (its WLED device's refresh_rate; a virtual
# renders at its slowest device) while the audio callback runs at 60 Hz,
# so a rendered frame carries two callbacks' turn and the old 3.36 rev/s
# cap was 40 deg per frame — past the 30 deg (180/edges) at which a 6-point
# star's turn reads backwards (temporal aliasing). The cap is therefore a
# per-frame angle: 18 deg per rendered frame = 1.5 rev/s at 30 fps, under
# the aliasing limit of every edge count STAR rolls (3..6 edges -> 60..30
# deg). "For now": one constant, retune here.
#
# HALVED 2026-11-18 with ROTATION_SPEED_SCALE above (the same order: "cut
# the max angle/frame the star can rotate, but let's scale it all down by
# 50%"): 18 -> 9 deg per rendered frame = 0.75 rev/s at 30 fps. Both halves
# of that order are needed and neither is redundant — the scale halves every
# frame BELOW the cap, and this halves the ceiling the loudest fires sit on.
# At a 0.9-intensity fire (spin 0.94) the old steady speed was already on the
# 18 deg clamp for half its frames (data/star-spin-smooth/plan.md, "Final
# law, measured"), so leaving the cap at 18 would have left exactly those
# frames unslowed. Still far under the aliasing limit (9 < 30 deg for a
# 6-point star).
ROTATION_CAP_DEG_FRAME = 9.0
ROTATION_CAP_REV_FRAME = ROTATION_CAP_DEG_FRAME / 360.0
# THE RELEASE: a one-pole low-pass on the per-frame ADVANCE (not on the
# speed), so a bass hit's burst, which the lows filter (ExpFilter decay
# 0.2 per 60 Hz frame) shapes into ~6 rendered frames and the squared spin
# gain sharpens further, is spread over `tau` seconds instead. Unity DC
# gain: the total turn and the mean speed are preserved (a steady loud
# passage turns exactly as far as today), only the burst's rise and decay
# stretch. The release time follows the told section `energy` (the same
# pushed value the star wave paces itself by): `spin_release_low_s` at
# energy 0 (lazier), `spin_release_high_s` at energy 1 (snappier), linear
# between — only the filter coefficient changes, the state integrates, so
# a change of energy never steps the motion. Effect default 0 = no filter,
# today's motion to the frame; STAR's Matrix entry carries 0.45 / 0.2
# (scripts/star_spin_smooth_scene_data.py). Analysis: data/star-spin-
# smooth/report.md (rms jerk -85..90%, mean speed within 3%).
DEFAULT_SPIN_RELEASE_S = 0.0
STAR_SPIN_RELEASE_LOW_S = 0.45
STAR_SPIN_RELEASE_HIGH_S = 0.2
# THE EASE-IN: from activation the advance is scaled by a smoothstep over
# this many seconds, so the star is already turning on its first frames and
# reaches the song's own speed over ~1 s instead of starting at whatever
# the audio callback happens to give. The effect's own default is 0 — the
# old behaviour, byte-identical for every Radial scene that does not ask —
# and STAR's Matrix entry carries STAR_SPIN_EASE_IN_S (scripts/
# star_improve_scene_data.py). (The quiet floor stays `base_rotation`,
# default 0 — his Q10: "it can slow to a stop during quiet music".)
DEFAULT_SPIN_EASE_IN_S = 0.0
STAR_SPIN_EASE_IN_S = 1.0
# THE STAR WAVE: `star` sways on a continuous cosine between two bounds, its
# period following the told section energy (slow when calm, quicker when
# loud); the phase integrates, so a period change never jumps the value.
# -0.2 .. +0.4 is his standard range: the wave passes through 0 (the flat
# polygon) every cycle, the points tucking in through flat and coming out
# at the other angle — continuous, because the shaping is
# radius x (1 + star cos(edges phi)) and that is smooth through star = 0.
# Off by default (byte-identical for every other Radial scene); STAR's
# Matrix entry switches it on.
DEFAULT_STAR_WAVE_LO = -0.2
DEFAULT_STAR_WAVE_HI = 0.4
DEFAULT_STAR_WAVE_PERIOD_SLOW_S = 7.0
DEFAULT_STAR_WAVE_PERIOD_FAST_S = 3.0
# ── THE STAR CURVE (2026-11-18, data/star-curve-study/report.md; the Admiral:
# "Additionally, slow the 'star setting' drift by 75%, but keep the burst
# speeds. However, it seems like it currently linearly bounces between the
# limits. Instead, have it follow a curve so that it spends more time flat,
# and at the ends", and after the five-curve page: "D2 and all recs").
#
# IT NEVER WAS A LINEAR BOUNCE. The shipped sway is a raised cosine, which
# already eases to a stop at both LIMITS and runs fastest straight through
# flat: 11% of a cycle within 0.05 of star = 0 against 37% near a limit. The
# dwell he is missing is the one at FLAT, where the shape change is most
# visible. So `star_wave_curve` picks the phase -> value map, and `plateau`
# is the one he chose: four holds per cycle — at lo, at flat, at hi, at flat
# again — with cosine glides between them. Measured: 45% at flat and 31% at
# the ends, against today's 11% / 37%.
#
# FLAT IS NOT THE MIDDLE OF THE RANGE. The shaping is
# radius x (1 + star cos(edges phi)), so star = 0 is the plain polygon, and
# with his -0.2 .. +0.4 bounds that sits at ONE THIRD of the sway, not one
# half. Every hold is therefore placed in VALUE space (`x0` in
# `_star_wave_u`), never at the midpoint of the bounds — a curve built on the
# midpoint would hold at +0.1, a half-pointed shape, which is not the ask.
#
# EVERY GLIDE SHARES ONE PEAK RATE: a glide's time is proportional to the
# value span it covers, so the sway never lurches on the short leg. Holding
# half the cycle still leaves the glide at HALF today's peak rate, because
# the cycle is four times longer (0.135 against 0.269 star/s).
#
# THE DRIFT RATE, x0.25 with the bursts kept ("but keep the burst speeds"):
# the only pace the drift takes from the music is its energy-paced period, so
# that IS its burst speed and it stays — the calm end alone slows, 7 -> 28 s,
# while the loud end holds at 3 s. Both are on STAR's own entry; the effect
# defaults below stay at today's values, so no other Radial scene moves.
STAR_WAVE_CURVES = ("cosine", "linear", "smooth", "plateau", "steps")
DEFAULT_STAR_WAVE_CURVE = "cosine"       # today, for every other Radial scene
STAR_WAVE_CURVE = "plateau"              # STAR's own entry
# the plateau's holds, as shares of ONE CYCLE — two flat holds and two limit
# holds, so his "50% held, split 1.8 : 1 toward flat" is 2 x 0.161 + 2 x 0.089
DEFAULT_STAR_WAVE_DWELL_FLAT = 0.161
DEFAULT_STAR_WAVE_DWELL_END = 0.089
# `steps`: the share of each rung spent held before it snaps to the next
STAR_WAVE_STEP_HOLD = 0.70
# the seeding inverse's table size (see `_star_wave_phase_for`)
STAR_WAVE_SEED_SAMPLES = 256
# STAR's own periods, x4 on the calm end, the loud end kept
STAR_WAVE_PERIOD_SLOW_S = 28.0
STAR_WAVE_PERIOD_FAST_S = 3.0

# ── WORD SHAPES (the Word Shapes plan row W1.6, 2026-11-15; the Admiral:
# "STAR: change the radial shape so it matches the shape if possible. This
# one might be excluded or need some thought", and his Q7 A: "include — the
# outline morphs into the shape, the spin eases to a stop so the shape
# stands upright, resumes on release").
#
# A sung word with a shape writes fx/effects/word_shape_keys.py's six told
# keys in ONE jump; Star edge-detects the SEQ and runs the whole form, hold
# and release on its own clock (`_shape_step`). Untold — no keys, a cleared
# write, an older SpotFX, a LedFX UI scrub — every line below is skipped and
# the effect renders byte for byte what it renders today.
#
# THE THIRD DIVISOR. Star's picture is the source strip sampled at a SHAPED
# RADIUS: `u = r / (max_radius x div(angle))`, so the `u = 1` contour IS the
# visible outline and `div` is the one thing that decides its form. The
# vendored effect has two divisors — the polygon/star lobes (`edges` >= 3)
# and the degenerate 1/2-edge cases — and already blends between two of them
# on an `edges` change (`shape_morph_s`, 0.6 s), harmonically, because the
# shaped radius `r / div` is what blends linearly. The word shape is simply a
# THIRD divisor in that same blend:
#
#     div_shape(psi) = SIZE x polar(theta_n) / (max_radius x k(psi))
#
# where `psi` is the SCREEN angle, `theta_n`/`k` carry it into the effect's
# normalized space (`nx = dx / ax`, `ny = dy / ay`, the shape placed on
# Star's own centre) and `polar` is the library's radius per angle. Two
# consequences, both deliberate:
#   * the divisor is a function of the SCREEN angle, not Star's rotating
#     frame, so THE POLYGON TURNS AND THE SHAPE DOES NOT — which is what
#     makes the heart stand upright at the hold however fast Star was
#     spinning when the word arrived (word_shapes' `Shape.upright`);
#   * `SIZE x polar` is in NORMALIZED units (1.0 = the panel's half-height),
#     so the shape comes out ~14% wider than tall in his room exactly as
#     every circle here does — the panel's own anisotropy, never corrected
#     in cells (`.claude/skills/word-shapes`).
#
# THE SHAPE'S EDGE. The divisor alone is not the shape: `u` keeps rising
# past 1 and the strip REPEATS (`twist_index % 1.0`), so the whole panel
# stays lit and the plan's clarity bar ("at the hold, >= 95% of the lit cells
# lie inside the shape") cannot be met by any divisor. The shape therefore
# also feathers the picture out just past its own outline — `alpha = 1 - m x
# clip((u - 1) / WORD_SHAPE_EDGE_U, 0, 1)`, scaled by the SAME envelope, so
# at the hold the panel holds one solid shape of flowing bands and nothing
# else, and untold (m = 0) the multiply is skipped entirely. Nothing INSIDE
# the shape is ever touched, which is what makes "the shape's area cells are
# lit" the strip's business and not the shape's.
DEFAULT_WORD_SHAPE_SIZE = 0.62
# the feather just outside the outline, in shaped-radius units — about one
# cell pitch on his crystal at the default size (measured in
# scripts/check_star_word_shape.py), so a lit cell is never further than the
# library's own "outline cells" band from the outline.
WORD_SHAPE_EDGE_U = 0.09
LULL_IMPLODE_S = 1.2     # implode fallback when no lull ramp arrives
DROP_BLOOM_S = 0.5       # bloom fallback when no drop ramp arrives

# ── THE STAR PLAN (2026-10-13, data/star-plan/report.md; the Admiral: "Use
# lull b, drop d 3"). Read the "STAR'S OWN LULL AND DROP" block above
# `_lull_bands` before touching any of these.
#
# LULL B — the bands fall in as particles. `lull_mode` "bands" (the
# default) / "implode" (today's warp, kept selectable).
LULL_MODES = ("bands", "implode")
DEFAULT_LULL_MODE = "bands"
DEFAULT_LULL_CORE_U = 0.14   # a falling piece is swallowed by the core here
DEFAULT_LULL_PIECE_TAU_S = 0.7   # a piece's radius decays on this (s)
LULL_CUT_END = 0.95          # the rim cut reaches the core at this share of
#                              the approach — the last pieces still fall in
LULL_END_FADE = 0.06         # ... and everything left eases to black over the
#                              last this-share, black ON the dark point
LULL_CUT_SOFT = 0.04         # the cut's feather, in shaped-radius units
LULL_PIECE_CAP = 220         # pieces falling at once (the program cap)
LULL_SHED_PIECES = 180       # roughly how many pieces a whole lull sheds
LULL_SWIRL_REV_S = 0.25      # a piece's own small swirl (± this, rev/s)
LULL_DRIFT_U_S = 0.04        # ... plus a steady inward drift (u / s)
LULL_HELD_CAP = 260          # swallowed pieces kept for the drop
LULL_HOLD_MAX = 8.0          # how far Star lifts the strip's own lull fade
# the visible region a piece may be shed from: the panel's inscribed
# ellipse, a little grown (the crystal's real light is a hexagon inside the
# rectangle — crystal-hex-grid skill; a piece shed from a dead corner would
# fly in out of nothing)
SHED_REGION = 1.15
LIT_MIN = 20.0               # a cell counts as lit above this (0..255)
#
# DROP D3 — the bands snap back. The pieces the lull swallowed are thrown
# back out of the core along their own angles and snap onto their bands as
# the bloom reveals them; the bands wear a hue-kept colour gain.
SNAP_T0_S = 0.55             # a piece's flight out ...
SNAP_PER_U_S = 0.3           # ... plus this per shaped-radius unit
SNAP_OVERSHOOT = 0.16        # the snap's overshoot past its band
SNAP_FADE_S = 0.5            # a landed piece melts into its band over this
SNAP_SWIRL_REV_S = 0.06      # their small swirl on the way out
DEFAULT_DROP_SNAP_GAIN = 1.6     # the bands' colour gain at the mark ...
DEFAULT_DROP_SNAP_DECAY_S = 1.0  # ... decaying to 1 over this
#
# THE SHAPE MORPH: an `edges` change (STAR's dice re-roll) glides from the
# old polygon to the new one instead of cutting in one frame.
DEFAULT_SHAPE_MORPH_S = 0.6
#
# THE BANDS RELEASE (a transition program OUT of Star): how many pieces
# Star's lit cells hand over by default (ProgramSettings.bands_pieces wins
# when a program asks).
RELEASE_PIECES = 180
RELEASE_LIT_MIN = 0.12       # a cell's brightest channel / 255 to be a piece
#
# INTO STAR (a transition program INTO Star — transition_cloud.RingFormer):
# the pieces land on Star's bands while a soft front grows the star out of
# the core; this is how long that front takes to reach the rim (a Star
# param, so it is tuned per scene on the Star entry).
DEFAULT_RING_REVEAL_FRONT_S = 0.65
BAND_MIN_SHARE = 0.35        # a strip peak at least this share of the
#                              brightest is a band a piece may land on
BAND_FALLBACK = np.linspace(0.12, 0.92, 8, dtype=np.float32)

# THE PRE-DROP (fx/effects/pre_drop.py is the binding statement; predrop
# plan step 8, his approval: "the star predrop should grow from the center
# as it spins, so it doesn't just pop in"): the dark point and the breath
# are measured to the pre-drop, so the star has fallen into its core and
# the panel is black before it; on the pre-drop a thin, dim OUTLINE in
# Star's own shape grows out of the centre (eased out, so it reaches its
# full size gently, on the drop) while it spins up, coloured round the set
# by angle from the live palette, so the colour change fading across the
# pre-drop shows in it. The drop is Star's own. Its thrown-back pieces wear
# the set as it is at the drop, not as it was when they fell in (the plan's
# 2.2: "Star re-samples its palette as the colour fades") — WIDENED
# 2026-10-28 (the Admiral: "yes, the star should change color") past the
# pre-drop fade: a drop with no pre-drop changes the set instantly, right
# before this phase arm lands, and SpotFX tells Star so
# (fx/effects/drop_colour_resample.py), so the thrown-back pieces
# re-sample then too (`_begin_snap`'s own comment is the binding statement
# for the rule).
PRE_DROP_LOOK = "outline"
PRE_DROP_OUTLINE_R = 0.42       # its full size: shaped px, x the panel height
PRE_DROP_OUTLINE_W = 1.6        # half-width: full within 0.6 px, gone by 1.6
PRE_DROP_OUTLINE_GAIN0 = 0.30   # its brightness as it appears ...
PRE_DROP_OUTLINE_GAIN1 = 0.40   # ... and on the drop (thin and dim)
PRE_DROP_SPIN_FROM = 0.35       # its own spin, rev/s, on the pre-drop ...
PRE_DROP_SPIN_TO = 1.8          # ... rising to this on the drop

_LUM = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
_SPLAT_R = 2
_sp = np.arange(-_SPLAT_R, _SPLAT_R + 1)
_SDX, _SDY = (a.ravel() for a in np.meshgrid(_sp, _sp))


def _smooth(s):
    s = np.clip(s, 0.0, 1.0)
    return s * s * (3.0 - 2.0 * s)


def _inv_smooth(y):
    """The smoothstep's own inverse: the x in [0, 1] with
    `x^2 (3 - 2x) == y`. WORD SHAPES uses it to place a shape's clock so the
    envelope RESUMES at a fraction the picture already shows — a second word
    landing inside the first's release re-forms from where it is, and a
    clearing write lets go from where it is, neither ever snapping (the
    plan's acceptance 7)."""
    y = float(np.clip(y, 0.0, 1.0))
    return 0.5 - math.sin(math.asin(1.0 - 2.0 * y) / 3.0)


def _smoother(t):
    """The quintic smootherstep — zero slope AND zero curvature at both ends,
    which is what makes `smooth` hover at the limits longer than a cosine."""
    t = np.clip(t, 0.0, 1.0)
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _star_wave_segments(dwell_flat, dwell_end, x0):
    """THE PLATEAU's eight segments, `(duration, u_from, u_to)` in phase
    order: hold at the low end, glide to flat, hold at flat, glide to the high
    end, hold there, glide back to flat, hold at flat, glide back to the low
    end. Durations are shares of ONE CYCLE and always sum to 1.

    A glide's time is proportional to the value span it covers, so every glide
    shares one peak rate and the sway never lurches on the short leg. `x0` is
    where FLAT sits in the sway, in value space (see the STAR CURVE comment):
    when it is outside the bounds — `lo >= 0` or `hi <= 0`, so the sway never
    passes through the plain polygon at all — the two flat holds collapse and
    their time goes to the limits, which keeps the param safe on any bounds
    instead of silently holding at a shape that is not flat."""
    hf = min(max(float(dwell_flat), 0.0), 0.45)
    he = min(max(float(dwell_end), 0.0), 0.45)
    x0 = min(max(float(x0), 0.0), 1.0)
    if x0 <= 0.0 or x0 >= 1.0:
        he = min(he + hf, 0.49)
        hf = 0.0
    held = 2.0 * (he + hf)
    if held > 0.98:                      # always leave the glides some time
        shrink = 0.98 / held
        he *= shrink
        hf *= shrink
    glide = 1.0 - 2.0 * he - 2.0 * hf
    g_up = glide * x0 / 2.0
    g_dn = glide * (1.0 - x0) / 2.0
    return (
        (he, 0.0, 0.0), (g_up, 0.0, x0), (hf, x0, x0), (g_dn, x0, 1.0),
        (he, 1.0, 1.0), (g_dn, 1.0, x0), (hf, x0, x0), (g_up, x0, 0.0),
    )


def _star_wave_u(p, curve, x0, dwell_flat, dwell_end):
    """The sway's normalised position (0 = `star_wave_lo`, 1 = `_hi`) at phase
    `p`, for each `star_wave_curve`. Continuous and bounded to [0, 1] for
    every curve; `steps` is deliberately the one with a visible snap."""
    p = float(p) % 1.0
    if curve == "cosine":                # the original: eased at the limits
        return 0.5 - 0.5 * np.cos(2.0 * np.pi * p)
    if curve == "linear":                # a constant-rate bounce
        return 2.0 * p if p < 0.5 else 2.0 - 2.0 * p
    if curve == "smooth":                # longer hover at the limits only
        return float(_smoother(2.0 * p if p < 0.5 else 2.0 - 2.0 * p))
    if curve == "steps":                 # a ladder of held shapes
        rungs = (0.0, x0 / 2.0, x0, (1.0 + x0) / 2.0, 1.0,
                 (1.0 + x0) / 2.0, x0, x0 / 2.0)
        n = len(rungs)
        k = int(p * n) % n
        f = p * n - k
        if f <= STAR_WAVE_STEP_HOLD:
            return rungs[k]
        s = (f - STAR_WAVE_STEP_HOLD) / (1.0 - STAR_WAVE_STEP_HOLD)
        a, b = rungs[k], rungs[(k + 1) % n]
        return a + (b - a) * float(_smoother(s))
    segments = _star_wave_segments(dwell_flat, dwell_end, x0)
    t = p
    last = len(segments) - 1
    for i, (d, a, b) in enumerate(segments):
        if t <= d or i == last:
            if d <= 0.0:
                return b
            s = min(max(t / d, 0.0), 1.0)
            return a + (b - a) * (0.5 - 0.5 * np.cos(np.pi * s))
        t -= d
    return 0.0


def _star_wave_rise_end(curve, x0, dwell_flat, dwell_end):
    """The phase at which the sway FIRST reaches its high end — the span the
    seeding inverse is built over.

    For the plateau it is computed from the segments rather than assumed:
    `hold_end + glide_up + hold_flat + glide_dn`. That happens to come to
    exactly half a cycle for ANY paired dwell — the two glides share
    `glide/2` however `x0` splits them, and the two holds either side are the
    same pair as on the way down — but computing it keeps the inverse correct
    if the holds are ever made unequal, which the proof depends on."""
    if curve == "plateau":
        segments = _star_wave_segments(dwell_flat, dwell_end, x0)
        return sum(d for d, _a, _b in segments[:4])
    return 0.5


def _star_wave_phase_for(value, lo, hi, curve, x0, dwell_flat, dwell_end):
    """The phase at which the sway shows `value`, taken on its RISING span so
    the scene's first frame is the shape the fire landed and the sway heads up
    from there.

    `cosine` keeps the closed form it has always used, so the DEFAULT curve is
    exactly — not approximately — what shipped before. Every other curve is
    inverted from a table of its rise: non-decreasing by construction, so
    `searchsorted(side="left")` lands on the START of a hold when the landed
    value sits on one, and the star then waits out that whole dwell before it
    moves (with his plateau a fire landing the binding's `star = 0.0` enters
    flat and holds). Measured round trip, landed value -> phase -> value:
    1.5e-5 star units across all five curves, and the table agrees with the
    closed form to 6.4e-6 of a cycle — 0.2 ms of the 28 s period
    (data/star-curve-study/seed_inverse_check.py)."""
    x = (value - lo) / (hi - lo) if hi > lo else 0.0
    x = min(max(float(x), 0.0), 1.0)
    if curve == "cosine":
        return float(np.arccos(1.0 - 2.0 * x)) / (2.0 * np.pi)
    p_up = float(_star_wave_rise_end(curve, x0, dwell_flat, dwell_end))
    if p_up <= 0.0:
        return 0.0
    n = STAR_WAVE_SEED_SAMPLES
    tp = np.linspace(0.0, p_up, n)
    tu = np.maximum.accumulate(np.array(
        [_star_wave_u(float(q), curve, x0, dwell_flat, dwell_end) for q in tp],
        dtype=np.float64))
    i = int(np.searchsorted(tu, x, side="left"))
    if i <= 0:
        return 0.0
    if i >= n:
        return float(tp[-1])
    u0, u1 = float(tu[i - 1]), float(tu[i])
    if u1 - u0 <= 1e-12:                 # inside a hold: take its start
        return float(tp[i - 1])
    f = (x - u0) / (u1 - u0)
    return float(tp[i - 1] + f * (tp[i] - tp[i - 1]))


def splat_brighter(layer, x, y, rgb, size=1.1):
    """Soft dots composed BRIGHTER-WINS into `layer` (H, W, 3) float: where
    a dot is brighter (perceived luminance) than the cell, the cell takes the
    dot's colour outright. Never a per-channel max — two set colours of
    different hues maxed together pale toward white (the plan's named risk);
    this way every lit cell still wears exactly one set colour."""
    x = np.asarray(x, dtype=np.float32)
    if x.size == 0:
        return
    y = np.asarray(y, dtype=np.float32)
    h, w = layer.shape[:2]
    ix = np.floor(x).astype(np.int32)
    iy = np.floor(y).astype(np.int32)
    cx = ix[:, None] + _SDX[None, :]
    cy = iy[:, None] + _SDY[None, :]
    d2 = (cx + 0.5 - x[:, None]) ** 2 + (cy + 0.5 - y[:, None]) ** 2
    wgt = np.exp(-d2 / (2.0 * size * size)).astype(np.float32)
    ok = (cx >= 0) & (cx < w) & (cy >= 0) & (cy < h) & (wgt > 0.05)
    if not ok.any():
        return
    flat = (cy * w + cx)[ok]
    vals = (wgt[..., None] * np.asarray(rgb, np.float32)[:, None, :])[ok]
    lum = vals @ _LUM
    order = np.lexsort((lum, flat))
    flat, vals, lum = flat[order], vals[order], lum[order]
    last = np.ones(flat.size, dtype=bool)
    last[:-1] = flat[1:] != flat[:-1]
    flat, vals, lum = flat[last], vals[last], lum[last]
    out = layer.reshape(-1, 3)
    win = lum > out[flat] @ _LUM
    out[flat[win]] = vals[win]


def hue_gain(frame, g):
    """`frame` scaled by `g`, hue-kept: a pixel scales whole and stops at
    full, so a colour gain never pushes one channel to 255 while the others
    catch up (which is what whitens an over-full colour)."""
    if g <= 1.0:
        return frame
    mx = frame.max(axis=-1, keepdims=True)
    k = np.where(mx > 0.0, np.minimum(g, 255.0 / np.maximum(mx, 1.0)), 1.0)
    return frame * k


class Radial2d(Twod):
    NAME = "Radial"
    CATEGORY = "Matrix"
    # add keys you want hidden or in advanced here
    HIDDEN_KEYS = Twod.HIDDEN_KEYS + [
        "test",
        "background_color",
        "background_brightness",
        "background_mode",
    ]
    # phase/phase_progress are SpotFX-driven choreography; advanced (not
    # hidden) so the arc can be hand-scrubbed in the LedFX UI for tuning.
    ADVANCED_KEYS = Twod.ADVANCED_KEYS + [
        "phase", "phase_progress", *lull_dark.KEYS, *phase_grammar.BREATH_KEYS,
        lull_handoff.DROP_KEY, phase_grammar.SHOCK_ON_KEY, *pre_drop.KEYS,
        drop_colour_resample.KEY, *word_shape_keys.KEYS,
    ]
    # Star takes the BREATH-HOLD itself (in its own draw, like Pulse) and
    # never the shared Shockwave overlay — its drop is D3, the bands
    # snapping back (fx.device_model.BREATH_HOLD_EFFECTS / DROP_SHOCK_TOLD_
    # EFFECTS name it; DROP_SHOCK stays False).
    BREATH_HOLD = True

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "source_virtual",
                description="The virtual from which to source the 1d pixels",
                default=DEFAULT_SOURCE_VIRTUAL,
            ): virtual_id_validator,
            vol.Optional(
                "edges",
                description="Edges count of mapping",
                default=0,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=8)),
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
                "twist",
                description="twist that thing",
                default=0,
            ): vol.All(vol.Coerce(float), vol.Range(min=-4, max=4)),
            vol.Optional(
                "polygon",
                description="Use polygonal or radial lobes",
                default=True,
            ): bool,
            vol.Optional(
                "rotation",
                description="static rotation",
                default=0,
            ): vol.All(vol.Coerce(float), vol.Range(min=-0.5, max=0.5)),
            vol.Optional(
                "spin",
                description="Spin the radial effect to the audio impulse",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=-1.0, max=1.0)),
            vol.Optional(
                "base_rotation",
                description=(
                    "Quiet base rotation FLOOR, in revolutions per second "
                    "(linear and absolute — unlike Spin, which is a squared "
                    "gain on live audio). The pattern never turns slower "
                    "than this; whenever the audio's own drive is faster, "
                    "the reactive spin takes over unchanged. 0 disables it "
                    "(the vendored behaviour). Max reduced 2026-10-06 (see "
                    "ROTATION_SPEED_SCALE above) from 2.0 to 1.6 rev/s, and "
                    "halved again 2026-11-18 to 0.8 rev/s with that same "
                    "scale — config/effect_params.json's own declared max "
                    "and spectra/models/scene.py's RADIAL_BASE_ROTATION_MAX "
                    "must stay in sync with this literal."
                ),
                default=0.0,
            ): vol.All(
                vol.Coerce(float), vol.Range(min=0.0, max=2.0 * ROTATION_SPEED_SCALE)
            ),
            vol.Optional(
                "frequency_range",
                description="Frequency range for the spin impulse",
                default="Lows (beat+bass)",
            ): vol.In(list(AudioReactiveEffect.POWER_FUNCS_MAPPING.keys())),
            vol.Optional(
                "star",
                description="pull polygon points to star shape",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=-1.0, max=1.0)),
            vol.Optional(
                "energy",
                description="Section intensity, 0 calm to 1 intense (pushed by SpotFX)",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "spin_ease_in_s",
                description=(
                    "Seconds the rotation eases up to the song's own speed "
                    "from the scene's first frame (0 = none)"
                ),
                default=DEFAULT_SPIN_EASE_IN_S,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=5.0)),
            vol.Optional(
                "spin_release_low_s",
                description=(
                    "Seconds a bass hit's spin burst is spread over when the "
                    "music is calm (energy 0); 0 = none, the burst as the "
                    "audio gives it"
                ),
                default=DEFAULT_SPIN_RELEASE_S,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=3.0)),
            vol.Optional(
                "spin_release_high_s",
                description=(
                    "Seconds a bass hit's spin burst is spread over when the "
                    "music is intense (energy 1); straight line between"
                ),
                default=DEFAULT_SPIN_RELEASE_S,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=3.0)),
            vol.Optional(
                "star_wave",
                description=(
                    "Sway Star between Star Wave Low and High on a slow wave "
                    "whose pace follows the song's energy"
                ),
                default=False,
            ): bool,
            vol.Optional(
                "star_wave_lo",
                description="Star wave: the low end of the sway",
                default=DEFAULT_STAR_WAVE_LO,
            ): vol.All(vol.Coerce(float), vol.Range(min=-1.0, max=1.0)),
            vol.Optional(
                "star_wave_hi",
                description="Star wave: the high end of the sway",
                default=DEFAULT_STAR_WAVE_HI,
            ): vol.All(vol.Coerce(float), vol.Range(min=-1.0, max=1.0)),
            vol.Optional(
                "star_wave_period_slow_s",
                description="Star wave: seconds per full sway when the music is calm",
                default=DEFAULT_STAR_WAVE_PERIOD_SLOW_S,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=30.0)),
            vol.Optional(
                "star_wave_period_fast_s",
                description="Star wave: seconds per full sway when the music is intense",
                default=DEFAULT_STAR_WAVE_PERIOD_FAST_S,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=30.0)),
            vol.Optional(
                "star_wave_curve",
                description=(
                    "Star wave: the shape of the sway. Cosine eases at the "
                    "two limits only (the original); Plateau holds at the "
                    "low end, at flat, at the high end and at flat again; "
                    "Soft Ends hovers longer at the limits; Steps holds a "
                    "ladder of shapes and snaps between them; Linear is a "
                    "constant-rate bounce"
                ),
                default=DEFAULT_STAR_WAVE_CURVE,
            ): vol.In(list(STAR_WAVE_CURVES)),
            vol.Optional(
                "star_wave_dwell_flat",
                description=(
                    "Star wave, Plateau only: the share of one cycle held "
                    "FLAT at each of the two passes through star = 0"
                ),
                default=DEFAULT_STAR_WAVE_DWELL_FLAT,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=0.45)),
            vol.Optional(
                "star_wave_dwell_end",
                description=(
                    "Star wave, Plateau only: the share of one cycle held at "
                    "each of the two limits"
                ),
                default=DEFAULT_STAR_WAVE_DWELL_END,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=0.45)),
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
                "lull_mode",
                description=(
                    "How the lull empties the star: bands = the outermost "
                    "band breaks into pieces that spiral into the core, then "
                    "the next, until the last is gone at the dark point "
                    "(the pieces are kept for the drop, which throws them "
                    "back out); implode = the pattern squeezes into a "
                    "narrow band at the core (the original lull)"
                ),
                default=DEFAULT_LULL_MODE,
            ): vol.In(list(LULL_MODES)),
            vol.Optional(
                "lull_core_u",
                description="Lull (bands): how close to the centre a "
                            "falling piece gets before the core swallows it "
                            "(shaped-radius units, 1 = the panel's corner)",
                default=DEFAULT_LULL_CORE_U,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=0.4)),
            vol.Optional(
                "lull_piece_tau",
                description="Lull (bands): how fast a piece falls — its "
                            "radius decays on this many seconds",
                default=DEFAULT_LULL_PIECE_TAU_S,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.3, max=2.0)),
            vol.Optional(
                "drop_snap_gain",
                description="Drop (the bands snap back): the bands' "
                            "hue-kept colour gain at the mark (more colour, "
                            "never white); 1 = none",
                default=DEFAULT_DROP_SNAP_GAIN,
            ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=2.5)),
            vol.Optional(
                "drop_snap_decay_s",
                description="Drop (the bands snap back): seconds the "
                            "colour gain takes to settle back to 1",
                default=DEFAULT_DROP_SNAP_DECAY_S,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=3.0)),
            vol.Optional(
                "ring_reveal_front_s",
                description="Into Star (a transition program): seconds the "
                            "soft front takes to grow the star out of the "
                            "core while the arriving pieces land on its "
                            "bands (clamped to the time the program has)",
                default=DEFAULT_RING_REVEAL_FRONT_S,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=2.0)),
            vol.Optional(
                "shape_morph_s",
                description="Seconds a change of Edges glides from the old "
                            "shape to the new one (0 = the old instant cut)",
                default=DEFAULT_SHAPE_MORPH_S,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            **lull_dark.schema_fields(),
            **phase_grammar.breath_schema_fields(),
            **lull_handoff.drop_schema_fields(),
            **phase_grammar.shock_on_schema_fields(),
            # THE PRE-DROP's told keys (ride only the lull arm; zeros on a
            # lull that plays none) — fx/effects/pre_drop.py
            **pre_drop.schema_fields(),
            # THE DROP COLOUR RE-SAMPLE's told key (rides only the drop
            # arm) — fx/effects/drop_colour_resample.py
            **drop_colour_resample.schema_field(),
            vol.Optional(
                "word_shape_size",
                description="Word Shapes: the shape's half-height as a "
                            "fraction of the panel's (the heart, star or "
                            "diamond a sung word draws)",
                default=DEFAULT_WORD_SHAPE_SIZE,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=1.0)),
            # THE WORD SHAPE's six told keys (ride only the Words band's own
            # write) — fx/effects/word_shape_keys.py
            **word_shape_keys.schema_fields(),
        }
    )

    def __init__(self, ledfx, config):
        self.bar = 0
        self.virtual = None
        self.spin_total = 0.0
        # revolutions the AUDIO callback has added since the last rendered
        # frame — read (and zeroed) only by _base_rotation_step
        self._reactive_advance = 0.0
        # revolutions EVERY writer (audio, charge spin-up, the base-rotation
        # correction) has added to spin_total since the last GOVERNED frame —
        # read (and zeroed) only by _govern_rotation. Unlike spin_total
        # itself this is never reduced mod 1, so it is always the exact
        # advance even when it exceeds half a revolution.
        self._frame_adv = 0.0
        self.max_radius = None
        # particle ⇄ radial handoff state (here, NOT do_once, so it survives
        # config-patch grid rebuilds)
        self._handoff_pending = True
        self._reveal = None    # incoming bloom: {"mode": "transition"|"timed", ...}
        self._mask_out = None  # outgoing collapse: {"frac0": float}
        # THE STAR PLAN state (`_lull_bands` / `_drop_snap` / the morph)
        self._rng = np.random.default_rng()
        self._bands = None     # lull B: the rim cut and its falling pieces
        self._held = None      # pieces the core swallowed, kept for the drop
        self._snap = None      # drop D3: the pieces flying back out
        self._silent_drop = False   # the orphan watchdog's quiet release
        self._morph = None     # {"from": edges, "t": s} while edges glides
        self._palette = None   # the set's colours, read off the strip (64x3)
        self._omega = 0.0      # live rotation rate, rad/s (the release)
        self._spin_prev = None
        self._last_u = None    # last frame's shaped radius / angle fields
        self._last_angle = None
        # THE PRE-DROP: its clock (None on every frame of a lull not told
        # one), the outline's own spin (revolutions) and whether this lull's
        # pre-drop played (so the drop's pieces wear the set as it is then)
        self._pd_clk = None
        self._pd_spin = 0.0
        self._pd_seen = False
        # THE STAR IMPROVE PLAN: seconds since activation (the ease-in's
        # clock), the pattern's angle at the end of the last rendered frame
        # (what the cap and the ease measure this frame's advance against)
        # and the star wave's phase (None = off / not started)
        self._active_s = 0.0
        self._spin_frame_prev = None
        self._wave_phase = None
        # THE SPIN SMOOTH PLAN: the release filter's state — the smoothed
        # per-frame advance (revolutions); None = not seeded / release off
        self._spin_lp = None
        # WORD SHAPES: the standing shape ({"t": s, "told": WordShapeTold,
        # "shape": Shape, "released": bool}; None = none), this frame's form
        # fraction, an Edge Morph that arrived DURING a shape and is waiting
        # for its release, and the two caches the shaped field is built from
        # (both keyed, both off the frame path). `_shape_seq` is deliberately
        # NOT created here: config_updated's own `hasattr` baseline is what
        # keeps a fresh instance built from a persisted stale SEQ from firing.
        self._shape = None
        self._shape_m = 0.0
        self._shape_edges_defer = None
        self._ws_norm = None
        self._ws_field = None
        super().__init__(ledfx, config)

    def config_updated(self, config):
        super().config_updated(config)
        self.source_virtual = None
        # THE SHAPE MORPH: a CHANGE of edges on a live instance (STAR's dice
        # re-roll lands as a jump) glides from the old shape to the new one.
        # Creation (no `edges` yet) and an unchanged value never start one.
        new_edges = self._config.get("edges")
        old_edges = getattr(self, "edges", None)
        morph_s = float(self._config.get("shape_morph_s",
                                         DEFAULT_SHAPE_MORPH_S) or 0.0)
        if old_edges is not None and self._shape is not None:
            # WORD SHAPES: an Edge Morph arriving DURING a shape is DEFERRED
            # to the release (the plan's W1.6 spec 3). The polygon carries
            # almost no weight at the hold, so applying it now would be a
            # step nobody sees and then a second morph on the way out; held
            # here, the release morphs back into the NEW edge count instead.
            # `self.edges` therefore stays the SHOWING count while a shape
            # stands, and the deferral is re-read from the config on every
            # write — so a change and a change BACK leaves nothing pending,
            # rather than landing the first one at the release.
            if morph_s <= 0.0:
                self._morph = None
            self._shape_edges_defer = (
                int(new_edges) if new_edges is not None
                and new_edges != old_edges else None)
        elif (old_edges is not None and new_edges != old_edges
                and morph_s > 0.0):
            self._morph = {"from": int(old_edges), "t": 0.0}
            self.edges = new_edges
        else:
            if morph_s <= 0.0:
                self._morph = None
            self.edges = new_edges
        self.x_offset = self._config.get("x_offset")
        self.y_offset = self._config.get("y_offset")
        self.twist = self._config.get("twist")
        self.polygon = self._config.get("polygon")
        self.rotation = self._config.get("rotation")
        # bring impulse spin injection into a reasonable range of control
        # — scaled by ROTATION_SPEED_SCALE so the reactive ceiling (spin at
        # its own max 1.0, full audio impulse) drops by the same 20% as
        # every other rotation-speed source, without narrowing spin's own
        # [-1, 1] input range.
        self.spin = (
            nonlinear_log(self._config.get("spin"), 2) / 10.0 * ROTATION_SPEED_SCALE
        )
        # LINEAR rev/s, deliberately NOT put through nonlinear_log: this is an
        # absolute floor a human sets in a plain unit, not a gain to shape.
        self.base_rotation = float(self._config.get("base_rotation", 0.0) or 0.0)
        self.power_func = AudioReactiveEffect.POWER_FUNCS_MAPPING[
            self._config["frequency_range"]
        ]
        self.star = self._config.get("star")
        # THE STAR IMPROVE PLAN: the ease-in length and the wave's bounds /
        # periods; the wave itself runs in draw() (`_star_wave_step`) and
        # overrides `self.star` per frame while on — the stored `star`
        # value is never rewritten.
        self.spin_ease_in_s = float(
            self._config.get("spin_ease_in_s", DEFAULT_SPIN_EASE_IN_S) or 0.0)
        # THE SPIN SMOOTH PLAN: the release's two ends (seconds at energy 0
        # and at energy 1); the per-frame value is read in _spin_release_s
        self.spin_release_low_s = float(
            self._config.get("spin_release_low_s", DEFAULT_SPIN_RELEASE_S) or 0.0)
        self.spin_release_high_s = float(
            self._config.get("spin_release_high_s", DEFAULT_SPIN_RELEASE_S) or 0.0)
        if not self._config.get("star_wave", False):
            self._wave_phase = None

        # WORD SHAPES: edge-detect the told SEQ, never the shape id, so two
        # words of the SAME shape back to back both start a shape (the
        # `burst_rockets` / `surge` pattern). CREATION BASELINE: a fresh
        # instance built from a persisted config that still carries a stale
        # SEQ must NOT fire (fireworks' own "phase-key creation-baseline
        # rule"), so the first pass only records what it found.
        told = word_shape_keys.told(self._config)
        if not hasattr(self, "_shape_seq"):
            self._shape_seq = told.seq if told is not None else 0
        elif told is not None and told.seq != self._shape_seq:
            self._shape_seq = told.seq
            self._shape_begin(told)
        elif told is None and self._shape is not None:
            # a CLEARING write mid-shape: let go from where the shape is
            # now, never a snap (the plan's acceptance 7)
            self._shape_let_go()
            self._shape_seq = 0

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
            self._phase_done_t = None
        else:
            # non-creation pass: a changed phase key arms the edge
            self._phase_pending = new_phase if new_phase != self._phase else None

    def audio_data_updated(self, data):
        self.impulse = getattr(data, self.power_func)()
        delta = self.impulse * self.spin
        self._reactive_advance += delta
        self._frame_adv += delta
        self.spin_total += delta
        self.spin_total %= 1.0  # keep it in [0, 1)

    def do_once(self):
        super().do_once()

        # Compute center based on normalized offsets
        self.cx = self.r_width * self.x_offset
        self.cy = self.r_height * self.y_offset

        # Create fixed coordinate grid
        y, x = np.indices((self.r_height, self.r_width))
        self.dx = x - self.cx
        self.dy = y - self.cy

        # Precompute base radius from center
        self.radius_base = np.sqrt(self.dx**2 + self.dy**2)

        # Compute maximum radius (used for normalization)
        # Add a small epsilon to avoid division by zero or crossing zero artifacts
        radius_stretch = 1.0 + epsilon
        self.max_radius = np.max(self.radius_base) * radius_stretch

        # WORD SHAPES: both caches are built from dx/dy/max_radius, which
        # this method has just rebuilt (a config-patch grid rebuild runs it
        # again), so they go with them.
        self._ws_norm = None
        self._ws_field = None

    def _ensure_source(self):
        if not self.source_virtual:
            # Try to fetch source_virtual (e.g. on startup race)
            virtuals = self._ledfx.virtuals._virtuals
            self.source_virtual = virtuals.get(
                self._config["source_virtual"]
            )
            if self.source_virtual is None:
                # Configured source missing or "unknown" (stale saved
                # configs) — fall back so we never render black forever.
                self.source_virtual = virtuals.get(DEFAULT_SOURCE_VIRTUAL)

    def _source_scroll_sign(self):
        """+1 if the source strip's content drifts toward higher index
        (radial rings expand outward), -1 if inward. Only Melt is
        direction-aware; everything else assumes outward."""
        try:
            self._ensure_source()
            eff = getattr(self.source_virtual, "active_effect", None)
            if eff is not None and getattr(eff, "NAME", "") == "Melt":
                return -1.0 if eff._config.get("flip") else 1.0
        except Exception:
            pass
        return 1.0

    def _handoff_snapshot(self):
        """Neutral handoff snapshot (see particle_handoff module): radial has
        no particles to hand over, but exports its center, flow direction and
        apparent-rotation sign so a particle successor can erupt from the
        center continuing the spin. None before the first render."""
        if self.max_radius is None:
            return None
        tw = self._config.get("twist") or 0.0
        spin = 0.0
        if tw:
            spin = float(
                np.sign(tw)
                * self._source_scroll_sign()
                * particle_handoff.RADIAL_SPIN_PARITY
            )
        empty = np.empty(0, dtype=np.float32)
        return {
            "src": "radial",
            "t": particle_handoff.now(),
            "dims": (self.r_width, self.r_height),
            "px": empty,
            "py": empty.copy(),
            "grad": empty.copy(),
            "bright": empty.copy(),
            "gradient": None,
            "spin_sign": spin,
            "blob_size": None,
            "flow": "out",
            "center_px": (float(self.cx), float(self.cy)),
            "trail": None,
        }

    # ── the set's colours (the palette Star's pieces wear) ───────────────
    # Star draws nothing of its own: its colours are the strip's (the
    # `radial-dummy` virtual running the scene's Strips effect — Melt on
    # STAR). The set's own gradient lives on that strip effect, so it is read
    # from there once a frame and cached: a piece is drawn in the SET colour
    # nearest its cell (transition_cloud.nearest_set_grad — the Flame Lick's
    # rule), and a transition program reads the cached palette through
    # `get_gradient_color_vectorized1d` even after the strip has switched to
    # the next scene's effect.

    def _refresh_palette(self, pixels_in=None):
        from fx.effects import transition_program as tp
        pal = None
        eff = getattr(self.source_virtual, "active_effect", None) \
            if self.source_virtual is not None else None
        fn = getattr(eff, "get_gradient_color_vectorized1d", None)
        if fn is not None:
            try:
                p = np.asarray(fn(tp.PALETTE_GRID), dtype=np.float32)
                if p.shape == (tp.PALETTE_GRID.size, 3) and np.isfinite(p).all():
                    pal = p
            except Exception:                              # noqa: BLE001
                pal = None
        if pal is None and pixels_in is not None:
            # a strip effect with no gradient: its own frame is the palette
            try:
                strip = np.asarray(pixels_in, dtype=np.float32)
                if strip.ndim == 2 and strip.shape[0] > 1 and strip.max() > 0:
                    idx = np.clip((tp.PALETTE_GRID * (strip.shape[0] - 1))
                                  .astype(np.int32), 0, strip.shape[0] - 1)
                    pal = strip[idx, :3].copy()
            except Exception:                              # noqa: BLE001
                pal = None
        if pal is not None:
            self._palette = pal

    def get_gradient_color_vectorized1d(self, points):
        """The colour set at `points` (n,) 0..1, as the cached strip palette
        holds it — what a transition program samples for the pieces Star
        releases (transition_program._sample_rgb). Raises when no palette
        has been seen yet (the program then falls back)."""
        from fx.effects import transition_program as tp
        rgb = tp.palette_rgb(self._palette, np.asarray(points, np.float32))
        if rgb is None:
            raise RuntimeError("radial: no colour set seen yet")
        return rgb

    def _set_colours(self, cell_rgb):
        """For each cell colour (n, 3): its nearest SET colour at full and
        that colour's gradient position (never a pale mix — the set's own)."""
        from fx.effects import transition_cloud
        cell_rgb = np.asarray(cell_rgb, dtype=np.float32)
        if self._palette is None:
            full = cell_rgb * (255.0 / np.maximum(
                cell_rgb.max(axis=1, keepdims=True), 1.0))
            return np.zeros(len(cell_rgb), np.float32), full.astype(np.float32)
        grad, full = transition_cloud.nearest_set_grad(self._palette, cell_rgb)
        return grad.astype(np.float32), full.astype(np.float32)

    # ── THE BANDS RELEASE (a transition program OUT of Star) ─────────────
    def _program_snapshot(self, settings=None):
        """What a TRANSITION PROGRAM captures when Star is the outgoing form
        (transition_program.TransitionProgram.capture asks for this before
        the ordinary `_handoff_snapshot`): the neutral snapshot plus Star's
        bands RELEASED as pieces — sampled from the last frame's lit cells,
        brightness-weighted, each in the set colour nearest its cell and
        moving with the ring it sat on (v = ω × r about the centre, from the
        live rotation rate), so the cloud leaves still turning.

        Deliberately NOT in `_handoff_snapshot`: that one also feeds the
        ordinary crossfade's adoptions (every particle effect's `src ==
        "radial"` branch reads it), whose behaviour this change leaves
        exactly as it was. No lit cells -> no pieces -> no program (the
        switch rides its ordinary path)."""
        snap = self._handoff_snapshot()
        if snap is None:
            return None
        cap = int(getattr(settings, "bands_pieces", RELEASE_PIECES)
                  or RELEASE_PIECES)
        try:
            m = np.asarray(self.matrix, dtype=np.float32)
        except Exception:                                  # noqa: BLE001
            return snap
        if m.ndim != 3 or m.shape[:2] != (self.r_height, self.r_width):
            return snap
        b = m.max(axis=2) / 255.0
        ys, xs = np.nonzero(b > RELEASE_LIT_MIN)
        if xs.size == 0:
            return snap
        if xs.size > cap:
            wgt = b[ys, xs].astype(np.float64)
            wgt = wgt / wgt.sum()
            pick = self._rng.choice(xs.size, cap, replace=False, p=wgt)
            ys, xs = ys[pick], xs[pick]
        px = xs.astype(np.float32) + 0.5
        py = ys.astype(np.float32) + 0.5
        w = float(self._omega)
        vx = (-w * (py - float(self.cy))).astype(np.float32)
        vy = (w * (px - float(self.cx))).astype(np.float32)
        grad, full = self._set_colours(m[ys, xs])
        snap.update({
            "px": px, "py": py, "vx": vx, "vy": vy,
            "grad": grad,
            "bright": np.clip(b[ys, xs], 0.0, 1.0).astype(np.float32),
            "rgb": full,
            "om": np.full(px.size, w, dtype=np.float32),
            "gesture": "bands",
        })
        return snap

    def deactivate(self):
        # Leave state behind for a particle successor (effect switch)
        # before the base clears _virtual.
        virtual = self._virtual
        try:
            if virtual is not None:
                particle_handoff.store(virtual.id, self._handoff_snapshot())
        except Exception:
            pass
        # the strip Star read goes back to doing its own lull
        strip_phase.unmark_radial_source(self.source_virtual)
        # WORD SHAPES: a shape never survives the scene it was sung into —
        # the next activation starts from the polygon, and a deferred Edge
        # Morph that never got its release lands now.
        self._shape = None
        self._shape_m = 0.0
        self._shape_apply_deferred_edges()
        super().deactivate()

    def _adopt_handoff(self):
        """First-draw adoption from a particle predecessor: continue its
        rotation (patch our twist sign) and arm the center-out bloom.

        Never while a TRANSITION PROGRAM brings Star in (transition_cloud.
        RingFormer): the program owns the arrival — the old crossfade
        choreography (this bloom, and the particle side's gather into the
        centre, which only a crossfade sibling ever runs) is retired for
        every program pair."""
        if getattr(self, "_transition_program", None) is not None:
            return
        snap = None
        virtual = self._virtual
        sibling = (
            getattr(virtual, "_transition_effect", None) if virtual else None
        )
        live = False
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
        # src gate keeps radial→radial recreations (and anything else)
        # from replaying the bloom
        if not snap or snap.get("src") not in (
            "orbits",
            "fish",
            "blackhole",
            "fireworks",
            "squiggles",
            "dancer",
            "eye",
            "sauron",
        ):
            return
        if tuple(snap["dims"]) != (self.r_width, self.r_height):
            return
        # apparent rotation = sign(twist) × source scroll; pick the twist
        # sign that continues the particles' spin (magnitude stays ours)
        spin_sign = float(snap.get("spin_sign") or 0.0)
        tw = self._config.get("twist") or 0.0
        if spin_sign and tw:
            want = np.sign(
                spin_sign
                * self._source_scroll_sign()
                * particle_handoff.RADIAL_SPIN_PARITY
            )
            if np.sign(tw) != want:
                # sanctioned in-render config path (we hold the effect lock);
                # one-time — never patch config per frame here
                self._apply_config(
                    {"twist": abs(tw) * want},
                    validate=False,
                    fire_event=False,
                )
        if live and particle_handoff.transition_progress(virtual) is not None:
            # two-phase choreography driven by the crossfade counters
            self._reveal = {"mode": "transition"}
        else:
            # no-transition path: short standalone bloom
            self._reveal = {"mode": "timed", "t": 0.0}

    # ── charge/lull/drop choreography ───────────────────────────────────
    # SpotFX writes `phase` (instant) and ramps `phase_progress` 0→1 over
    # the event's ramp. charge: the rotation accelerates in the direction
    # already set; lull: the pattern implodes to a held center point (same
    # warp as the transition implode, standalone timing); drop: it blooms
    # back out of the center, then `phase` self-resets to "none".

    def _phase_step(self, dt):
        pend = self._phase_pending
        if pend is not None:
            self._phase_pending = None
            if pend != self._phase:
                prev = self._phase
                self._phase = pend
                self._phase_t = 0.0
                self._phase_done_t = None
                self._phase_edge(prev, pend)
        if self._phase == "none":
            return
        self._phase_t += dt
        # orphan watchdog: a charge/lull whose payoff never arrives
        # releases itself — the pattern quietly blooms back out
        due, self._phase_done_t = particle_handoff.phase_release_due(
            self._phase, self.phase_progress, self._phase_t,
            self._phase_done_t,
        )
        if due:
            _LOGGER.info(
                "radial: %s watchdog release after %.1fs",
                self._phase, self._phase_t,
            )
            # a quiet release, never a payoff: nothing is thrown back out
            self._silent_drop = True
            self._held = None
            self._bands = None
            self._snap = None
            self._phase = "drop"
            self._phase_t = 0.0
            self.phase_progress = 0.0
            return
        p = float(np.clip(self.phase_progress, 0.0, 1.0))
        if self._phase == "charge":
            # apparent-direction sign: the audio spin's sign if it has one,
            # else the twist's (rotation-by-twist), else clockwise
            sign = (
                float(np.sign(self._config.get("spin") or 0.0))
                or float(np.sign(self._config.get("twist") or 0.0))
                or 1.0
            )
            # ease-in: spin-up maxes AT the ramp end
            delta = sign * CHARGE_SPIN_REV_S * p * p * dt
            self._frame_adv += delta
            self.spin_total = (self.spin_total + delta) % 1.0
        elif self._phase == "drop":
            done = max(p, min(self._phase_t / DROP_BLOOM_S, 1.0))
            if done >= 1.0:
                self._phase = "none"
                # sanctioned in-render config path (under the effect lock);
                # self-reset so an identical later drop write edges again
                self._apply_config(
                    {"phase": "none", "phase_progress": 0.0},
                    validate=False,
                    fire_event=False,
                )

    def _base_rotation_step(self, dt):
        """DEVIATION (fx/VENDOR.md #22): a quiet BASE ROTATION floor.

        Semantics are a FLOOR, not a sum:

            effective rev/s = max(base_rotation, reactive rev/s)

        so in silence the pattern turns steadily at ``base_rotation``, and
        the instant the audio's own drive is faster the reactive spin owns
        the motion COMPLETELY UNCHANGED — which is what preserves the
        existing reactivity exactly at every peak. (A summed design would
        speed every peak up slightly; it is a one-line change here if that
        is ever preferred.)

        WHERE it advances is load-bearing: the vendored effect's only motion
        source is ``audio_data_updated``, and audio callbacks stop entirely
        when the capture pipeline stalls or the effect is left unsubscribed
        — a base term living there would stall with them, which is exactly
        the "quiet" case this exists for. So it rides the RENDER clock
        (``self.passed``) in ``draw`` instead, and holds with zero audio
        frames.

        DIRECTION follows the current one and never fights it: the sign
        ladder is the same one the charge phase already uses — the audio
        spin's sign (which is what the spin_sign/Flip machinery writes),
        else the twist's, else clockwise.
        """
        # drain unconditionally: the accumulator must never carry a stale
        # frame's advance across a base_rotation=0 stretch
        reactive = self._reactive_advance
        self._reactive_advance = 0.0
        if self.base_rotation <= 0.0 or dt <= 0.0:
            return
        sign = (
            float(np.sign(self._config.get("spin") or 0.0))
            or float(np.sign(self._config.get("twist") or 0.0))
            or 1.0
        )
        want = self.base_rotation * dt          # revolutions owed this frame
        got = reactive * sign                   # revolutions the audio made,
        #                                         measured along `sign`
        if want > got:
            delta = sign * (want - got)
            self._frame_adv += delta
            self.spin_total = (self.spin_total + delta) % 1.0

    def _phase_warp(self):
        """Standalone lull implode / drop bloom warp, when no crossfade
        choreography owns the screen. Returns (warp, bg_alpha) or None.
        A lull in "bands" mode has no warp: its picture is cut from the rim
        inward instead (`_lull_bands`)."""
        if self._phase == "lull" and self._lull_mode() == "bands":
            return None
        if self._phase == "lull":
            # progress-driven once it moves (hand-scrubbable in the LedFX
            # UI); the wall-clock fallback only runs while progress sits at 0
            # so a lost ramp still implodes
            p = float(np.clip(self.phase_progress, 0.0, 1.0))
            s = p if p > 0.0 else min(self._phase_t / LULL_IMPLODE_S, 1.0)
            e = s * s * (3.0 - 2.0 * s)
            return (0.0, 1.0 - e * (1.0 - IMPLODE_MIN_W)), 1.0 - e
        if self._phase == "drop":
            s = max(
                float(np.clip(self.phase_progress, 0.0, 1.0)),
                min(self._phase_t / DROP_BLOOM_S, 1.0),
            )
            e = s * s * (3.0 - 2.0 * s)
            return (0.0, max(e, 1e-3)), e
        return None

    # ── STAR'S OWN LULL AND DROP (the star plan, the Admiral 2026-10-13:
    # "Use lull b, drop d 3") ────────────────────────────────────────────
    #
    # LULL B — THE BANDS FALL IN AS PARTICLES. A rim CUT sweeps from the
    # outermost band inward (in Star's own shaped radius, so it is the
    # shape's outline shrinking): every lit cell the cut passes breaks off
    # as a piece (about LULL_SHED_PIECES over the whole lull, brightness
    # weighted), which keeps the ring's rotation (a piece lives in Star's
    # ROTATING frame, so it turns with the star) and spirals into the core —
    # its radius decays on `lull_piece_tau` with a small swirl — until the
    # core swallows it. Band by band the star empties; the cut reaches the
    # centre at LULL_CUT_END of the approach and the last pieces are in by
    # the DARK POINT (lull_dark's shared rule — Star reads it itself, so a
    # long lull keeps shedding until 3 s before its drop), where the panel is
    # black. Pieces wear the SET colour nearest their cell at full and are
    # composed brighter-wins, never by a channel max (`splat_brighter`) — so
    # pieces of two hues at the core never pale toward white. Every piece
    # the core swallows is KEPT (`_held`) for the drop.
    #
    # DROP D3 — THE BANDS SNAP BACK. On the drop's edge the kept pieces are
    # thrown back out of the core along their own angles and snap onto the
    # band each came from (a small overshoot, SNAP_OVERSHOOT) as the bloom
    # reveals the pattern, then melt into it; the bands wear a hue-kept
    # colour gain (`drop_snap_gain`, x1.6 at the mark, settling over
    # `drop_snap_decay_s`) — more colour, never white. It is Star's drop and
    # replaces the shared Shockwave overlay on this effect (Star is not a
    # DROP_SHOCK member), but it OBEYS THE SAME THREE SWITCHES: SpotFX tells
    # Star the verdict (`drop_shock_on` — the room's switch, the scene's,
    # and the top-bar Energy floor); told False, the drop is the plain bloom
    # (no pieces thrown, no colour gain). The told drop intensity scales the
    # gain and how long it lasts (lull_handoff.drop_scale; untold = 1). A
    # drop with nothing kept (a charge straight into a drop, an "implode"
    # lull) is the plain bloom too, and so is the orphan watchdog's quiet
    # release. A new charge or lull discards anything still in flight.
    #
    # THE BREATH-HOLD: Star takes the lull's short true black before the
    # mark itself (phase_grammar.breath_gain, once a frame — the base
    # Twod's shared painter only runs for Shockwave members). The panel is
    # already black there in both modes: since 2026-10-14 the strip Star
    # reads skips its own lull (strip_phase, THE STRIP STAR READS), so Star
    # takes the panel dark ON the dark point itself — "bands" by its cut,
    # "implode" by `_implode_fade`.

    def _lull_mode(self):
        mode = self._config.get("lull_mode", DEFAULT_LULL_MODE)
        return mode if mode in LULL_MODES else DEFAULT_LULL_MODE

    def _phase_edge(self, prev, new):
        if new in ("charge", "lull"):
            self._snap = None
            self._silent_drop = False
            self._held = None
            self._pd_seen = False
        if new == "lull":
            self._bands = None
        if new == "drop":
            self._begin_snap()
            self._pd_seen = False
        if prev == "lull" and new != "lull":
            self._bands = None

    # the shape a piece rides: a piece at shaped radius u and angle phi
    # (Star's rotating frame) sits at u * max_radius * _shape_div(phi) px

    def _shape_div_for(self, phi, edges):
        phi = np.asarray(phi, dtype=np.float32)
        if edges == 1:
            return 1.0 / np.maximum(np.abs(np.cos(phi)), epsilon)
        if edges == 2:
            return 1.0 / np.sqrt(np.cos(phi) ** 2 + 0.25 * np.sin(phi) ** 2)
        if edges is not None and edges >= 3:
            if not self.polygon:
                return 1.0 / np.maximum(np.abs(np.cos((edges * phi) / 2)), 0.05)
            a = np.pi * 2 / edges
            half_a = a / 2
            am = (phi + half_a) % a - half_a
            pr = np.cos(np.pi / edges) / np.clip(np.cos(am), epsilon, None)
            if self.star != 0:
                pr = pr * (1 + self.star * np.cos(edges * phi))
            return np.maximum(pr, 1e-3)
        return np.ones_like(phi)

    def _shape_div(self, phi, theta=None):
        f = self._shape_div_for(phi, self.edges)
        m = self._morph_mix()
        if m is not None:
            fb = self._shape_div_for(phi, self._morph["from"])
            # the shaped radius blends linearly (r/f), so the divisor blends
            # harmonically
            f = 1.0 / ((1.0 - m) / fb + m / f)
        # WORD SHAPES: the third divisor, in the SAME harmonic blend. `phi`
        # is Star's ROTATING frame and the shape stands in the screen's, so
        # this needs the frame's own angle — a caller with none (there is
        # none left in the module) keeps the polygon, which is what Star
        # looked like before this row.
        ms = float(self._shape_m)
        if ms > 0.0 and theta is not None:
            ds = self._word_shape_div(np.asarray(phi, np.float32)
                                      + float(theta))
            if ds is not None:
                f = 1.0 / ((1.0 - ms) / np.maximum(f, 1e-6)
                           + ms / np.maximum(ds, 1e-6))
        return f

    def _piece_xy(self, u, phi, theta):
        r = (np.asarray(u, np.float32) * self.max_radius
             * self._shape_div(phi, theta))
        ang = np.asarray(phi, np.float32) + theta
        return (self.cx + r * np.cos(ang)).astype(np.float32), \
            (self.cy + r * np.sin(ang)).astype(np.float32)

    def _morph_mix(self):
        if self._morph is None:
            return None
        s = float(self._config.get("shape_morph_s", DEFAULT_SHAPE_MORPH_S) or 0.0)
        if s <= 0.0:
            return None
        return float(_smooth(self._morph["t"] / s))

    # ── WORD SHAPES (the block comment above DEFAULT_WORD_SHAPE_SIZE) ────

    def _shape_active(self):
        """Whether a told shape is standing (anywhere in its form, hold or
        release). `_shape_m` is this frame's form fraction."""
        return self._shape is not None

    def _word_shape_size(self):
        return float(self._config.get("word_shape_size",
                                      DEFAULT_WORD_SHAPE_SIZE)
                     or DEFAULT_WORD_SHAPE_SIZE)

    def _shape_begin(self, told):
        """A told SEQ edge: start the form. A shape arriving while another
        is still standing (two words back to back, the second inside the
        first's release) starts from WHERE THE PICTURE IS, not from zero —
        the clock is placed so the envelope resumes at the current form
        fraction, which is the plan's acceptance 7 (no snap).

        `prime()` builds the library's lazy views HERE, on the config
        write's own thread, so the first rendered frame never pays for
        them."""
        try:
            shape = word_shapes.get(told.shape).prime()
        except Exception:                                   # noqa: BLE001
            # an id this build cannot build is "not told" (word_shape_keys'
            # own rule); told() already filters it, this is the belt
            _LOGGER.warning("radial: unknown word shape %r", told.shape)
            self._shape = None
            self._shape_m = 0.0
            return
        m = float(self._shape_m) if self._shape is not None else 0.0
        t0 = told.form_s * _inv_smooth(m) if told.form_s > 0.0 else 0.0
        self._shape = {"t": float(t0), "told": told, "shape": shape,
                       "released": False}
        self._shape_m = m

    def _shape_let_go(self):
        """A clearing write (`told() is None`) while a shape stands: convert
        what is left into a pure RELEASE from the current fraction, on the
        time the shape was told. Nothing snaps and nothing is re-formed."""
        sh = self._shape
        if sh is None:
            return
        told = sh["told"]
        rel = float(told.release_s)
        m = float(self._shape_m)
        if rel <= 0.0 or m <= 0.0:
            self._shape = None
            self._shape_m = 0.0
            self._shape_apply_deferred_edges()
            return
        self._shape = {
            "t": rel * _inv_smooth(1.0 - m),
            "told": told._replace(form_s=0.0, hold_s=0.0),
            "shape": sh["shape"], "released": True}
        self._shape_apply_deferred_edges()

    def _shape_apply_deferred_edges(self):
        """The Edge Morph held back while the shape stood (config_updated):
        start it now, as the ordinary `shape_morph_s` glide, so the release
        morphs back into the NEW edge count."""
        want = self._shape_edges_defer
        self._shape_edges_defer = None
        if want is None or want == self.edges:
            return
        morph_s = float(self._config.get("shape_morph_s",
                                         DEFAULT_SHAPE_MORPH_S) or 0.0)
        if morph_s > 0.0:
            self._morph = {"from": int(self.edges), "t": 0.0}
        else:
            self._morph = None
        self.edges = want

    def _shape_step(self, dt):
        """One frame of the standing shape's own clock: advance it, read the
        form fraction off the ONE envelope every effect shares
        (`word_shape_keys.envelope`), hand a deferred Edge Morph to the
        release as it starts, and reset when the release is over. The effect
        never writes a told key back."""
        sh = self._shape
        if sh is None:
            self._shape_m = 0.0
            return
        told = sh["told"]
        sh["t"] += dt
        if sh["t"] > told.total_s:
            self._shape = None
            self._shape_m = 0.0
            self._shape_apply_deferred_edges()
            return
        if not sh["released"] and sh["t"] > told.form_s + told.hold_s:
            sh["released"] = True
            self._shape_apply_deferred_edges()
        self._shape_m = float(word_shape_keys.envelope(
            sh["t"], told.form_s, told.hold_s, told.release_s))

    def _ws_normalized(self):
        """Every cell in the effect's NORMALIZED space, cached: the radius
        and the angle the shape's own `polar` is read at. `nx = dx / ax`,
        `ny = dy / ay` with ax/ay the panel's half-width/half-height in
        columns/rows — the `sx`/`sy` convention every Twod effect and the
        shape library share — placed on STAR'S OWN centre (`cx`, `cy`),
        which is where the polygon it morphs out of is centred."""
        if self._ws_norm is None:
            ax = max((self.r_width - 1) * 0.5, 1.0)
            ay = max((self.r_height - 1) * 0.5, 1.0)
            nx = (self.dx / ax).astype(np.float32)
            ny = (self.dy / ay).astype(np.float32)
            self._ws_norm = (np.hypot(nx, ny).astype(np.float32),
                             np.arctan2(ny, nx).astype(np.float32))
        return self._ws_norm

    def _word_shape_shaped(self, shape, size):
        """The shape's own SHAPED RADIUS field — `max_radius x u` where
        `u = |n| / (SIZE x polar(theta_n))`, so `u = 1` is exactly the
        library's outline. Cached per (shape, size): both are constant for
        a whole word, so a holding shape costs one divide a frame."""
        key = (shape.id, round(float(size), 6), int(self.r_width),
               int(self.r_height))
        if self._ws_field is None or self._ws_field[0] != key:
            rn, th = self._ws_normalized()
            rr = np.asarray(shape.polar(th), dtype=np.float32) * float(size)
            field = (rn / np.maximum(rr, 1e-4)
                     * float(self.max_radius)).astype(np.float32)
            self._ws_field = (key, field)
        return self._ws_field[1]

    def _word_shape_div(self, psi):
        """The shape's divisor at SCREEN angle(s) `psi` — the same law the
        field above carries, for the one place that works in angles rather
        than cells (a lull piece, a transition program: `_shape_div`).
        None when no shape stands."""
        sh = self._shape
        if sh is None:
            return None
        size = self._word_shape_size()
        ax = max((self.r_width - 1) * 0.5, 1.0)
        ay = max((self.r_height - 1) * 0.5, 1.0)
        psi = np.asarray(psi, dtype=np.float32)
        nx = np.cos(psi) / ax
        ny = np.sin(psi) / ay
        k = np.hypot(nx, ny)
        theta_n = np.arctan2(ny, nx)
        rr = np.asarray(sh["shape"].polar(theta_n), dtype=np.float32) * size
        return (rr / np.maximum(k * float(self.max_radius), 1e-6)
                ).astype(np.float32)

    def _shed_region(self):
        w2 = max(self.r_width / 2.0, 1.0)
        h2 = max(self.r_height / 2.0, 1.0)
        return ((self.dx / w2) ** 2 + (self.dy / h2) ** 2) <= SHED_REGION

    def _lull_bands(self, rgb, u, angle, dt):
        """LULL B, one frame (block comment above): cut the picture `rgb`
        (float, H x W x 3) from the rim inward, shed the cells the cut passed
        as pieces, let the falling pieces spiral in, keep what the core
        swallows. Returns the pieces' layer to compose (or None)."""
        cfg = self._config
        p = float(np.clip(self.phase_progress, 0.0, 1.0))
        tim = lull_dark.lull_timing(cfg, p, self._phase_t, legacy_dark_at=1.0)
        core = float(cfg.get("lull_core_u", DEFAULT_LULL_CORE_U))
        tau = float(cfg.get("lull_piece_tau", DEFAULT_LULL_PIECE_TAU_S))
        st = self._bands
        lum = rgb.max(axis=2)
        if st is None:
            region = self._shed_region()
            lit = region & (lum > LIT_MIN)
            ref = lum[lit]
            top = float(u[region].max()) if region.any() else 1.0
            st = self._bands = {
                "top": max(top, core),
                "cut": max(top, core) + LULL_CUT_SOFT,
                "prob": float(np.clip(LULL_SHED_PIECES / max(int(lit.sum()), 1),
                                      0.02, 1.0)),
                "region": region,
                "peak0": float(np.percentile(ref, 95)) if ref.size else 0.0,
                "u": np.zeros(0, np.float32), "u0": np.zeros(0, np.float32),
                "phi": np.zeros(0, np.float32), "sw": np.zeros(0, np.float32),
                "rgb": np.zeros((0, 3), np.float32),
                "b": np.zeros(0, np.float32),
                "g": np.zeros(0, np.float32),
            }
            if self._held is None:
                self._held = {"u0": np.zeros(0, np.float32),
                              "phi": np.zeros(0, np.float32),
                              "rgb": np.zeros((0, 3), np.float32),
                              "g": np.zeros(0, np.float32)}
        # STAR HOLDS ITS OWN PICTURE (the plan's Q6): since 2026-10-14 the
        # strip Star reads skips its own lull while Star reads it (strip_
        # phase, THE STRIP STAR READS), so its brightness only eases back
        # from the charge; should a strip under Star dim anyway (a strip no
        # longer marked, an older layer), Star brings the bands it still
        # shows back up to their brightness at the lull's start (hue-kept,
        # capped) so the bands fall in on Star's clock, black ON the dark
        # point.
        if st["peak0"] > 0.0:
            live = lum[st["region"] & (lum > 2.0)]
            if live.size:
                peak = float(np.percentile(live, 95))
                g = min(max(st["peak0"] / max(peak, 1.0), 1.0), LULL_HOLD_MAX)
                if g > 1.0:
                    rgb[...] = hue_gain(rgb, g)
                    lum = rgb.max(axis=2)
        if tim.dark:
            cut = 0.0
        else:
            # the lit AREA shrinks evenly in time (area ~ cut^2), eased at
            # both ends, so the bands keep falling in until the last one goes
            # just before the dark point
            cut = st["top"] * float(np.sqrt(max(
                0.0, 1.0 - float(_smooth(tim.approach / LULL_CUT_END)))))
        prev = st["cut"]
        cut = min(cut, prev)
        st["cut"] = cut
        # shed: the lit cells the cut passed this frame become pieces
        if not tim.dark and prev > cut:
            passed = (st["region"] & (lum > LIT_MIN)
                      & (u > cut - 0.5 * LULL_CUT_SOFT)
                      & (u <= prev - 0.5 * LULL_CUT_SOFT))
            ys, xs = np.nonzero(passed)
            if xs.size:
                keep = self._rng.random(xs.size) < st["prob"]
                room = LULL_PIECE_CAP - st["u"].size
                ys, xs = ys[keep][:max(room, 0)], xs[keep][:max(room, 0)]
            if xs.size:
                cols = rgb[ys, xs]
                grad, full = self._set_colours(cols)
                if self._palette is None:
                    grad = np.full(xs.size, np.nan, np.float32)
                st["g"] = np.concatenate([st["g"], grad.astype(np.float32)])
                uu = u[ys, xs].astype(np.float32)
                st["u"] = np.concatenate([st["u"], uu])
                st["u0"] = np.concatenate([st["u0"], uu])
                st["phi"] = np.concatenate(
                    [st["phi"], angle[ys, xs].astype(np.float32)])
                st["sw"] = np.concatenate(
                    [st["sw"], self._rng.uniform(-1.0, 1.0, xs.size)
                     .astype(np.float32)])
                st["rgb"] = np.concatenate([st["rgb"], full])
                st["b"] = np.concatenate(
                    [st["b"], np.clip(cols.max(axis=1) / 255.0 * 1.4, 0.45, 1.0)
                     .astype(np.float32)])
        # the picture: lit inside the cut only (black once it is gone); the
        # last of it eases out so the panel is black exactly ON the dark point
        end = 0.0 if tim.dark else float(
            _smooth((1.0 - tim.approach) / LULL_END_FADE))
        k = _smooth((cut - u) / LULL_CUT_SOFT).astype(np.float32) * end
        rgb *= k[..., None]
        # fall: pieces spiral into the core, faster when the dark point is
        # near so every one is in by then
        if st["u"].size:
            t_left = None
            if lull_dark.told(cfg):
                t_left = float(cfg.get(lull_dark.DARK_KEY, 0.0) or 0.0) \
                    - self._phase_t
            tau_eff = tau if t_left is None else float(
                np.clip(t_left / 1.5, 0.05, tau))
            st["u"] = np.maximum(
                st["u"] * np.float32(np.exp(-dt / tau_eff))
                - np.float32(LULL_DRIFT_U_S * dt), 0.0)
            st["phi"] = st["phi"] + st["sw"] * np.float32(
                LULL_SWIRL_REV_S * 2 * np.pi * dt)
            gone = st["u"] <= 0.5 * core
            if tim.dark:
                gone[:] = True
            if gone.any():
                h = self._held
                room = LULL_HELD_CAP - h["u0"].size
                g = np.flatnonzero(gone)[:max(room, 0)]
                h["u0"] = np.concatenate([h["u0"], st["u0"][g]])
                h["phi"] = np.concatenate([h["phi"], st["phi"][g]])
                h["rgb"] = np.concatenate([h["rgb"], st["rgb"][g]])
                h["g"] = np.concatenate([h["g"], st["g"][g]])
                live = ~gone
                for key in ("u", "u0", "phi", "sw", "rgb", "b", "g"):
                    st[key] = st[key][live]
        if st["u"].size == 0:
            return None
        # a piece melts into the core as it nears it
        fade = _smooth((st["u"] - 0.5 * core) / (0.5 * core))
        bright = st["b"] * fade * end
        on = bright > 0.01
        if not on.any():
            return None
        theta = ((self.spin_total + self.rotation) % 1.0) * 2 * np.pi
        x, y = self._piece_xy(st["u"][on], st["phi"][on], theta)
        layer = np.zeros_like(rgb)
        splat_brighter(layer, x, y, st["rgb"][on] * bright[on, None])
        return layer

    def _begin_snap(self):
        """DROP D3's start (block comment above): the kept pieces leave the
        core along their own angles. Nothing kept, a quiet watchdog release,
        or SpotFX's verdict saying the drop may not paint: the plain bloom."""
        held, self._held = self._held, None
        st = self._bands
        self._bands = None
        if self._silent_drop or not phase_grammar.shock_on(self._config):
            self._snap = None
            return
        u0 = np.zeros(0, np.float32)
        phi = np.zeros(0, np.float32)
        rgb = np.zeros((0, 3), np.float32)
        gpos = np.zeros(0, np.float32)
        if held is not None:
            u0, phi, rgb = held["u0"], held["phi"], held["rgb"]
            gpos = held.get("g", np.full(u0.size, np.nan, np.float32))
        if st is not None and st["u"].size:
            # a drop landing before the last pieces were in throws them too
            u0 = np.concatenate([u0, st["u0"]])
            phi = np.concatenate([phi, st["phi"]])
            rgb = np.concatenate([rgb, st["rgb"]])
            gpos = np.concatenate([gpos, st.get(
                "g", np.full(st["u0"].size, np.nan, np.float32))])
        if u0.size == 0:
            self._snap = None
            return
        scale = lull_handoff.drop_scale(
            lull_handoff.drop_intensity(self._config))
        scale = 1.0 if scale is None else float(scale)
        g = float(self._config.get("drop_snap_gain", DEFAULT_DROP_SNAP_GAIN))
        self._snap = {
            "t": 0.0,
            "u0": u0.astype(np.float32),
            "phi": phi.astype(np.float32),
            "rgb": rgb.astype(np.float32),
            "sw": self._rng.uniform(-1.0, 1.0, u0.size).astype(np.float32),
            "T": (SNAP_T0_S + SNAP_PER_U_S * u0).astype(np.float32),
            "gain": 1.0 + (g - 1.0) * scale,
            "decay": max(0.05, float(self._config.get(
                "drop_snap_decay_s", DEFAULT_DROP_SNAP_DECAY_S)) * scale),
        }
        if self._pd_seen or drop_colour_resample.landed(self._config):
            # THE PRE-DROP played (colour faded across it), OR SpotFX told
            # this drop a colour change landed on it with no pre-drop to
            # fade across (fx/effects/drop_colour_resample.py — widened
            # 2026-10-28, the Admiral: "yes, the star should change
            # color"): the pieces wear the set as it is now, re-read every
            # frame of the snap. `_phase_edge` clears `_pd_seen` on this
            # same edge; the told key needs no clearing — SpotFX re-asserts
            # it fresh (even False) on every drop arm, never left standing
            # from the last one.
            self._snap["g"] = gpos.astype(np.float32)

    def _drop_snap(self, rgb, dt):
        """DROP D3, one frame: the colour gain on the bands (hue-kept, in
        place on `rgb`) and the layer of pieces flying back out. Returns the
        layer (or None)."""
        sn = self._snap
        sn["t"] += dt
        t = sn["t"]
        g = 1.0 + (sn["gain"] - 1.0) * (1.0 - float(_smooth(t / sn["decay"])))
        if g > 1.0:
            rgb[...] = hue_gain(rgb, g)
        s = np.clip(t / np.maximum(sn["T"], 1e-3), 0.0, 1.0)
        sn["phi"] = sn["phi"] + sn["sw"] * np.float32(
            SNAP_SWIRL_REV_S * 2 * np.pi * dt)
        u = sn["u0"] * _smooth(s) * (1.0 + SNAP_OVERSHOOT * np.sin(np.pi * s))
        b = np.clip(1.0 - (t - sn["T"]) / SNAP_FADE_S, 0.0, 1.0)
        if t > float(sn["T"].max()) + SNAP_FADE_S and t > sn["decay"]:
            self._snap = None
        on = b > 0.01
        if not on.any():
            return None
        theta = ((self.spin_total + self.rotation) % 1.0) * 2 * np.pi
        x, y = self._piece_xy(u[on], sn["phi"][on], theta)
        layer = np.zeros_like(rgb)
        cols = sn["rgb"]
        if "g" in sn:
            now = self._palette_full(sn["g"])
            if now is not None:
                cols = np.where(np.isfinite(sn["g"])[:, None], now, cols)
        splat_brighter(layer, x, y, cols[on] * b[on, None])
        return layer

    def _spin_release_s(self):
        """THE SPIN SMOOTH PLAN's release time this frame, seconds:
        `spin_release_low_s` at told `energy` 0 (lazier) to
        `spin_release_high_s` at 1 (snappier), linear between. 0 = off."""
        lo = self.spin_release_low_s
        hi = self.spin_release_high_s
        if lo <= 0.0 and hi <= 0.0:
            return 0.0
        energy = min(max(float(self._config.get("energy", 0.5) or 0.0), 0.0), 1.0)
        return max(lo + (hi - lo) * energy, 0.0)

    def _govern_rotation(self, dt):
        """THE STAR IMPROVE PLAN's ease-in and cap and THE SPIN SMOOTH PLAN's
        release, on the TOTAL advance of the pattern this frame — whatever
        the audio callback, the base floor and the charge spin-up added to
        `_frame_adv` since the last rendered frame (an exact, never-wrapped
        sum — unlike `spin_total` itself, kept in [0, 1), this can be
        larger than half a revolution and still read correctly):

            adv  = _frame_adv                                 (exact, drained)
            adv *= smoothstep(active_s / spin_ease_in_s)      (the ease-in)
            lp  += (adv - lp) (1 - exp(-dt / tau))            (the release)
            adv  = clamp(lp, -cap, +cap)                      (the cap)

        so the first frames after activation turn gently up to the song's
        own speed, a bass hit's burst is spread over `tau` =
        _spin_release_s() seconds with its total turn preserved (unity DC
        gain — the filter is on the advance, so a steady passage turns
        exactly as far as without it), and no frame ever turns more than
        ROTATION_CAP_DEG_FRAME (9 deg per rendered frame since 2026-11-18,
        18 before it — under the 180/edges deg at which an N-point star's
        turn reads backwards).
        Below the cap a frame is untouched; with spin_ease_in_s 0 the ease
        is gone; with both release params 0 the filter is bypassed and the
        motion is today's to the frame. The first rendered frame (nothing
        to measure against — a hand-off may have just set the angle) is
        never governed, and seeds the release state on the next. The
        pre-drop outline keeps its own spin (`_pd_spin`); it is not
        rotation of the pattern."""
        adv = self._frame_adv
        self._frame_adv = 0.0
        prev = self._spin_frame_prev
        if prev is not None and dt > 0.0:
            ease = self.spin_ease_in_s
            if ease > 0.0 and self._active_s < ease:
                x = self._active_s / ease
                adv *= x * x * (3.0 - 2.0 * x)
            tau = self._spin_release_s()
            if tau > 0.0:
                if self._spin_lp is None:
                    self._spin_lp = adv
                else:
                    self._spin_lp += (adv - self._spin_lp) * (1.0 - np.exp(-dt / tau))
                adv = self._spin_lp
            else:
                self._spin_lp = None
            # WORD SHAPES: THE SHAPE EASES THE TURN TO A STOP. The whole
            # governed advance is scaled by `1 - m`, so the reactive spin,
            # the base floor and anything else that moved the pattern this
            # frame all fade out together over the form, are EXACTLY zero
            # through the hold (the shape stands upright and still) and come
            # back from the music over the release. Applied AFTER the release
            # filter on purpose: the filter's state keeps integrating the
            # music's own advance while the shape stands, so the resume is
            # the song's current speed rather than a lag, and `m = 1` is a
            # true zero rather than a decaying tail.
            # A PHASE TAKES THE GOVERNOR BACK (the plan's W1.6 spec 5): a
            # charge's spin-up, a lull or a drop landing mid-shape owns the
            # motion unscaled — a shape is never TOLD during a phase (P3 A),
            # so this is only the arrive-mid-shape case.
            ms = float(self._shape_m)
            if ms > 0.0 and self._phase == "none":
                adv *= 1.0 - ms
            cap = ROTATION_CAP_REV_FRAME
            if adv > cap:
                adv = cap
            elif adv < -cap:
                adv = -cap
            self.spin_total = (prev + adv) % 1.0
        self._active_s += dt
        self._spin_frame_prev = self.spin_total

    def _star_wave_step(self, dt):
        """THE STAR WAVE (`star_wave`): `star` sways between `star_wave_lo`
        and `star_wave_hi` on the curve `star_wave_curve` names; a full sway
        takes `star_wave_period_slow_s` at energy 0 and `_fast_s` at energy 1
        (the told section energy, linear between). The phase integrates,
        so a change of energy changes the pace and never the value. On the
        scene's FIRST activation the wave starts AT the value the fire
        landed (`star`, clamped into the bounds), heading up, so the first
        frame is the picked shape and nothing steps; a later re-fire while
        STAR is already showing (the same effect instance, `_wave_phase`
        already running) carries on from its current point in the sway
        instead — jumping to the newly landed value would be a visible
        step. Crossing 0 is smooth: the shaping is radius x
        (1 + star cos(edges phi)), continuous through star = 0 — the points
        tuck in through the flat polygon and come out at the other angle.

        THE CURVE (2026-11-18, see the STAR CURVE comment at the top): the
        phase -> value map is `_star_wave_u`, and FLAT is held at the value 0,
        not at the midpoint of the bounds. `cosine` is the default and is the
        shape that shipped before, so no other Radial scene moves."""
        cfg = self._config
        if not cfg.get("star_wave", False):
            self._wave_phase = None
            return
        lo = float(cfg.get("star_wave_lo", DEFAULT_STAR_WAVE_LO))
        hi = float(cfg.get("star_wave_hi", DEFAULT_STAR_WAVE_HI))
        if hi < lo:
            lo, hi = hi, lo
        curve = cfg.get("star_wave_curve", DEFAULT_STAR_WAVE_CURVE)
        if curve not in STAR_WAVE_CURVES:
            curve = DEFAULT_STAR_WAVE_CURVE
        dwell_flat = float(cfg.get("star_wave_dwell_flat",
                                   DEFAULT_STAR_WAVE_DWELL_FLAT))
        dwell_end = float(cfg.get("star_wave_dwell_end",
                                  DEFAULT_STAR_WAVE_DWELL_END))
        # where FLAT sits in the sway, in value space — one third of his
        # -0.2 .. +0.4, never one half
        x0 = (0.0 - lo) / (hi - lo) if hi > lo else 0.0
        x0 = min(max(x0, 0.0), 1.0)
        if self._wave_phase is None:
            base = float(cfg.get("star") or 0.0)
            base = min(max(base, lo), hi)
            self._wave_phase = _star_wave_phase_for(
                base, lo, hi, curve, x0, dwell_flat, dwell_end)
        slow = float(cfg.get("star_wave_period_slow_s",
                             DEFAULT_STAR_WAVE_PERIOD_SLOW_S) or 0.5)
        fast = float(cfg.get("star_wave_period_fast_s",
                             DEFAULT_STAR_WAVE_PERIOD_FAST_S) or 0.5)
        energy = min(max(float(cfg.get("energy", 0.5) or 0.0), 0.0), 1.0)
        period = max(slow + (fast - slow) * energy, 0.05)
        # WORD SHAPES: the wave is HELD at its value for the whole shape
        # (the plan's W1.6 spec 3) — the PHASE is what freezes, and the
        # value is still recomputed from it, so a config write landing
        # mid-shape (which re-reads the stored `star`) cannot step the
        # picture either. It carries on from the same point on the release.
        if not self._shape_active():
            self._wave_phase = (self._wave_phase + dt / period) % 1.0
        self.star = lo + (hi - lo) * _star_wave_u(
            self._wave_phase, curve, x0, dwell_flat, dwell_end)

    def _track_rotation(self, dt):
        """The live rotation rate (rad/s, smoothed) — what the bands release
        hands its pieces as tangential velocity."""
        cur = float(self.spin_total + self.rotation)
        if self._spin_prev is not None and dt > 0.0:
            d = (cur - self._spin_prev + 0.5) % 1.0 - 0.5
            w = 2.0 * np.pi * d / dt
            self._omega = 0.8 * self._omega + 0.2 * w
        self._spin_prev = cur

    def draw(self):
        self._ensure_source()
        # THE STRIP STAR READS leaves the lull to Star (strip_phase's module
        # docstring): say, every frame, which strip that is
        strip_phase.mark_radial_source(self.source_virtual)
        self._refresh_bg_render_state()

        if self._handoff_pending:
            self._handoff_pending = False
            self._adopt_handoff()

        dt = float(self.passed) if np.isfinite(self.passed) else 1.0 / 60.0
        dt = min(max(dt, 0.0), 0.1)
        self._phase_step(dt)
        self._pre_drop_step(dt)
        # WORD SHAPES: before the rotation, which the form eases to a stop,
        # and before the star wave, which it holds
        self._shape_step(dt)
        self._base_rotation_step(dt)
        self._govern_rotation(dt)
        self._star_wave_step(dt)
        self._track_rotation(dt)
        if self._morph is not None:
            self._morph["t"] += dt
            ms = float(self._config.get("shape_morph_s",
                                        DEFAULT_SHAPE_MORPH_S) or 0.0)
            if ms <= 0.0 or self._morph["t"] >= ms:
                self._morph = None

        virtual = self._virtual
        feather = particle_handoff.REVEAL_FEATHER
        gather = particle_handoff.GATHER_FRAC

        # ── outgoing "suck in": we are the crossfade sibling and a particle
        # effect is coming in — collapse the pattern into the center
        if self._mask_out is None:
            inc = particle_handoff.incoming_sibling(virtual, self)
            if inc is not None and getattr(inc, "NAME", None) in (
                "Orbits",
                "Blackhole",
                "Fireworks",
                "Squiggles",
                "Dancer",
            ):
                # incoming infall blackhole with an event horizon: implode
                # down to the horizon RING (the pattern compresses into that
                # disc and hands over), not all the way to a point
                floor = 0.0
                if getattr(inc, "NAME", None) == "Blackhole":
                    try:
                        if (
                            inc.horizon_scale > 0
                            and not inc._config.get("reverse")
                        ):
                            sx = getattr(inc, "sx", None)
                            sy = getattr(inc, "sy", None)
                            if sx is not None and sy is not None:
                                rh_px = (
                                    inc.horizon_scale * (sx + sy) / 2.0
                                )
                                floor = min(
                                    rh_px / self.max_radius, 0.9
                                )
                    except Exception:
                        floor = 0.0
                self._mask_out = {
                    "frac0": particle_handoff.transition_progress(virtual)
                    or 0.0,
                    "floor": floor,
                }
                self._reveal = None

        # warp = (origin, scale): the pattern is sampled at
        # u = origin + (norm_radius - origin) / scale. Bloom: origin 0,
        # scale grows 0→1 — the pattern stretches out of the center.
        # Implode: origin = the incoming horizon ring (0 = a point) and
        # scale shrinks 1→IMPLODE_MIN_W — everything INSIDE the ring
        # expands out to it while everything OUTSIDE collapses onto it,
        # the whole pattern converging into a narrow band at the ring.
        # bg_alpha fades the background color in/out as its own transition.
        warp = None
        bg_alpha = 0.0
        pat_alpha = 1.0
        bloom_start = particle_handoff.BLOOM_START
        if self._mask_out is not None:
            frac = particle_handoff.transition_progress(virtual)
            if (
                frac is None
                or getattr(virtual, "_transition_effect", None) is not self
            ):
                self._mask_out = None
            else:
                f0 = self._mask_out["frac0"]
                floor = self._mask_out.get("floor", 0.0)
                # implode lands exactly when the successor erupts — no dead
                # air between touchdown and the burst
                s = np.clip(
                    (frac - f0) / max(bloom_start - f0, 1e-3), 0.0, 1.0
                )
                e = s * s * (3.0 - 2.0 * s)
                if s >= 1.0:
                    if floor <= 0.0:
                        # fully imploded — the erupting particles own the rest
                        return
                    # compressed into the horizon band: dissolve as the
                    # blackhole's burst takes over (a static hold reads as
                    # a hang)
                    diss = np.clip(
                        (frac - bloom_start) / 0.25, 0.0, 1.0
                    )
                    if diss >= 1.0:
                        return
                    warp = (floor, IMPLODE_MIN_W)
                    bg_alpha = 0.0
                    pat_alpha = 1.0 - float(diss)
                else:
                    warp = (floor, 1.0 - e * (1.0 - IMPLODE_MIN_W))
                    bg_alpha = 1.0 - e       # background fades away with it
        elif self._reveal is not None:
            if self._reveal["mode"] == "transition":
                if getattr(virtual, "_transition_effect", None) is self:
                    # interrupted mid-bloom: we're the outgoing side now
                    self._reveal = None
                else:
                    frac = particle_handoff.transition_progress(virtual)
                    if frac is None:
                        # crossfade over. The counter almost never reads a
                        # full 1.0 before the sibling clears, so a bloom
                        # that visibly started is simply DONE — replaying
                        # it on the timer would explode twice. Only fall
                        # back to the timer if it never started (sibling
                        # died during phase 1).
                        if self._reveal.get("p", 0.0) > 0.0:
                            self._reveal = None
                        else:
                            self._reveal = {"mode": "timed", "t": 0.0}
                    elif frac < bloom_start:
                        # the collapsing particles own the early phase
                        return
                    else:
                        p2 = (frac - bloom_start) / (1.0 - bloom_start)
                        e = p2 * p2 * (3.0 - 2.0 * p2)
                        self._reveal["p"] = e
                        warp = (0.0, max(e, 1e-3))  # pattern stretches out
                        bg_alpha = e                # background fades in
                        if frac >= 1.0:
                            self._reveal = None
            if self._reveal is not None and self._reveal["mode"] == "timed":
                self._reveal["t"] += self.passed
                p = min(
                    self._reveal["t"] / particle_handoff.REVEAL_FALLBACK_S,
                    1.0,
                )
                e = p * p * (3.0 - 2.0 * p)
                warp = (0.0, max(e, 1e-3))
                bg_alpha = e
                if p >= 1.0:
                    self._reveal = None

        # charge/lull/drop: the standalone lull implode / drop bloom, only
        # when no crossfade choreography is already warping the pattern
        if warp is None:
            phase_warp = self._phase_warp()
            if phase_warp is not None:
                warp, bg_alpha = phase_warp

        if self.source_virtual and hasattr(
            self.source_virtual, "assembled_frame"
        ):
            pixels_in = self.source_virtual.assembled_frame

            # Use precomputed geometry
            dx = self.dx
            dy = self.dy
            radius = self.radius_base.copy()

            # Compute rotation + spin as one angle in radians
            rotate_and_spin = (self.spin_total + self.rotation) % 1.0
            theta = rotate_and_spin * 2 * np.pi

            # Angle and rotation
            angle = np.arctan2(dy, dx)
            angle -= theta
            angle_norm = (angle + np.pi) / (2 * np.pi)  # [0, 1)

            # Radius modulation based on edges (THE SHAPE MORPH: while an
            # edges change glides, the old shape's shaped radius blends into
            # the new one's)
            shaped = self._shaped_radius(radius, angle, theta, self.edges)
            m = self._morph_mix()
            if m is not None:
                old = self._shaped_radius(
                    self.radius_base.copy(), angle, theta, self._morph["from"])
                shaped = old * (1.0 - m) + shaped * m
            # WORD SHAPES: the third divisor, blended in by the SAME rule —
            # a shaped radius blends linearly, which is the harmonic blend of
            # the divisors (`1/div = (1-ms)/div_poly + ms/div_shape`). The
            # shape's field is a function of the SCREEN position only, so the
            # polygon keeps turning under it and the shape stands upright.
            ms = float(self._shape_m)
            if ms > 0.0 and self._shape is not None:
                want = self._word_shape_shaped(self._shape["shape"],
                                               self._word_shape_size())
                shaped = shaped * (1.0 - ms) + want * ms
            radius = shaped

            # Normalize and apply twist
            norm_radius = radius / self.max_radius
            # this frame's shaped radius / angle fields: what a transition
            # program INTO Star reveals by (transition_cloud.RingFormer)
            self._last_u = norm_radius
            self._last_angle = angle
            if warp is not None:
                # explosion / implosion warp: sample the pattern at
                # u = origin + (norm - origin)/scale. Origin 0 = zoom from
                # the center (bloom); origin = horizon ring = two-sided
                # convergence onto the ring (implode).
                origin, wscale = warp
                u = origin + (norm_radius - origin) / max(wscale, 1e-3)
                twist_index = (u + self.twist * angle_norm) % 1.0
            else:
                twist_index = (norm_radius + self.twist * angle_norm) % 1.0

            # Map to strip
            strip = pixels_in.clip(0, 255).astype(np.uint8)
            N = len(strip)
            indices = np.clip((twist_index * N).astype(np.int32), 0, N - 1)

            # Fill image
            rgb_array = strip[indices]
            if warp is not None:
                # the pattern only exists for u in [0, 1] (feathered both
                # ends); elsewhere show the background color, itself fading
                # with bg_alpha — the bg is a plain fade, not part of the
                # explosion
                edge = (
                    np.clip((1.0 + feather - u) / feather, 0.0, 1.0)
                    * np.clip((u + feather) / feather, 0.0, 1.0)
                ).astype(np.float32)[..., None]
                bg = np.asarray(
                    getattr(self, "_bg_color", np.zeros(3)),
                    dtype=np.float32,
                )
                rgb_array = (
                    rgb_array.astype(np.float32) * (edge * pat_alpha)
                    + bg[None, None, :] * (1.0 - edge) * bg_alpha
                ).astype(np.uint8)
                self.bg_color_use = False
            elif ms > 0.0:
                # WORD SHAPES: THE SHAPE'S EDGE (the block comment above
                # DEFAULT_WORD_SHAPE_SIZE). `u` keeps rising past the outline
                # and the strip REPEATS (`twist_index % 1.0`), so without
                # this the panel stays lit all over and the shape is an
                # iso-contour rather than a shape. A soft CUT sweeps inward
                # from past the panel's own farthest `u` to exactly `u = 1`,
                # linearly in the envelope, with a feather of one cell pitch:
                # at m = 0 the cut sits at that farthest value and nothing is
                # touched (byte-identical, and this branch is skipped anyway);
                # at the hold the panel holds one solid shape of flowing
                # bands and nothing else. Swept rather than DIMMED on purpose
                # — fading the whole outside by `1 - m` takes every cell out
                # there across the lit threshold in the same frame, which
                # measured as a 115% single-frame change in lit cells
                # (scripts/check_star_word_shape.py); a cut that passes them
                # a few at a time is what makes the form and the release
                # smooth. Nothing INSIDE the outline is ever touched, which is
                # what leaves "is the shape lit" the strip's business.
                # Skipped while a WARP owns the picture (a transition
                # hand-off, the implode lull, the drop bloom): the warp's own
                # feather is already the edge of the pattern there, and a
                # phase keeps precedence.
                #
                # THE CUT IS PACED BY CELLS, NOT BY RADIUS — the RingFormer's
                # own lesson, re-learnt here (transition_cloud's "INTO STAR":
                # "Star's cells crowd into a narrow band of shaped radius, so
                # a front at a steady radial speed lit the whole middle in
                # ~0.1 s"). Swept linearly in `u`, the form held still for
                # half its length and then took two thirds of the panel out
                # in six frames (22% of the lit cells in one frame, measured
                # with the strip frozen). So the cut sits at the QUANTILE of
                # this frame's own `u` field that leaves an even share of the
                # cells uncovered per unit of the envelope: all of them at
                # m = 0 (`u_cut` = the field's own maximum, a true no-op),
                # exactly the shape's at m = 1.
                # ... and the share it leaves falls GEOMETRICALLY, not
                # linearly: what reads as a jump is the RELATIVE change in
                # what is lit, so an even share of what is LEFT has to go
                # each frame. `q = share ** m` is that law in one term — all
                # the cells at m = 0, the shape's own share at m = 1, and a
                # constant relative rate in between (a linear share spent
                # 15% of the lit cells in one frame at the envelope's
                # steepest; this spends about 8%, the plan's own bar).
                share = max(float((norm_radius <= 1.0).mean()), 1e-4)
                q = float(share ** ms)
                u_cut = float(np.quantile(norm_radius, min(max(q, 0.0), 1.0)))
                fade = (1.0 - np.clip(
                    (norm_radius - u_cut) / WORD_SHAPE_EDGE_U, 0.0, 1.0)
                ).astype(np.float32)[..., None]
                rgb_array = (rgb_array.astype(np.float32) * fade
                             ).astype(np.uint8)
            rgb_array = self._star_phase_frame(
                rgb_array, norm_radius, angle, dt, pixels_in)
            image = Image.fromarray(rgb_array, mode="RGB")
            self.matrix.paste(image)

    def _shaped_radius(self, radius, angle, theta, edges):
        """The vendored radius modulation for `edges` (unchanged), factored
        out so the shape morph can compute two shapes in one frame."""
        if edges == 1:
            ux = np.cos(theta)
            uy = np.sin(theta)
            return np.abs(self.dx * ux + self.dy * uy)
        if edges == 2:
            cos_angle = np.cos(angle)
            sin_angle = np.sin(angle)
            modulation = np.sqrt(cos_angle**2 + 0.25 * sin_angle**2)
            radius *= modulation
        elif edges >= 3:
            if not self.polygon:
                modulation = np.cos((edges * angle) / 2)
                radius *= np.abs(modulation)
            else:
                a = np.pi * 2 / edges
                half_a = a / 2
                angle_mod = (angle + half_a) % a - half_a
                polygon_radius = np.cos(np.pi / edges) / np.clip(
                    np.cos(angle_mod), epsilon, None
                )

                # Optional starburst shaping
                if self.star != 0:
                    ripple = 1 + self.star * np.cos(edges * angle)
                    polygon_radius *= ripple
                radius /= polygon_radius
        return radius

    def _star_phase_frame(self, rgb_array, u, angle, dt, pixels_in):
        """Star's own lull and drop on the frame just mapped (block comment
        above `_lull_mode`): lull B's cut and falling pieces, D3's pieces and
        colour gain, and the breath-hold. Outside all three the frame is
        returned untouched (byte for byte)."""
        self._refresh_palette(pixels_in)
        bands = self._phase == "lull" and self._lull_mode() == "bands"
        breath = 1.0
        implode_fade = 1.0
        if self._phase == "lull":
            breath = phase_grammar.breath_gain(self._config, self._phase_t)
            if not bands:
                implode_fade = self._implode_fade()
        outline = self._pre_drop_outline()
        if not bands and self._snap is None and breath >= 1.0 \
                and implode_fade >= 1.0 and outline is None:
            return rgb_array
        rgb = rgb_array.astype(np.float32)
        layers = []
        if bands:
            layer = self._lull_bands(rgb, u, angle, dt)
            if layer is not None:
                layers.append(layer)
        if self._snap is not None:
            layer = self._drop_snap(rgb, dt)
            if layer is not None:
                layers.append(layer)
        for layer in layers:
            lit = (layer @ _LUM) > (rgb @ _LUM)
            rgb[lit] = layer[lit]
        if breath < 1.0:
            rgb *= np.float32(breath)
        if implode_fade < 1.0:
            rgb *= np.float32(implode_fade)
        if outline is not None:
            lit = (outline @ _LUM) > (rgb @ _LUM)
            rgb[lit] = outline[lit]
        return np.clip(rgb, 0, 255).astype(np.uint8)

    def _implode_fade(self):
        """The "implode" lull's own fade to black ON the shared dark point
        (the strip that used to fade under it skips its lull while Star
        reads it — strip_phase, THE STRIP STAR READS): the same eased curve
        the strip layer faded by. Only when SpotFX has TOLD Star the lull's
        dark point (it always does — Star is a LULL_DARK member); an untold
        lull (a hand scrub, the vendored warp alone) is the warp as it was."""
        if not lull_dark.told(self._config):
            return 1.0
        p = float(np.clip(self.phase_progress, 0.0, 1.0))
        tim = lull_dark.lull_timing(self._config, p, self._phase_t,
                                    legacy_dark_at=1.0)
        if tim.dark:
            return 0.0
        return 1.0 - float(_smooth(tim.approach))

    # ── THE PRE-DROP (PRE_DROP_* above) ──────────────────────────────────

    def _pre_drop_step(self, dt):
        """THE PRE-DROP's clock: read only on a lull TOLD a pre-drop —
        every other frame clears it before anything else reads it, so a
        lull without one is today's, byte for byte. On the pre-drop it turns
        the outline's own spin (rising PRE_DROP_SPIN_FROM -> _TO over the
        gap) and marks the lull's pre-drop as played."""
        if self._phase != "lull" or not pre_drop.told(self._config):
            self._pd_clk = None
            return
        clk = self._pd_clk = pre_drop.phase_clock(
            self._config, self._phase, self.phase_progress, self._phase_t,
            prev=self._pd_clk)
        if clk.segment != "pre_drop":
            return
        if clk.edge:
            self._pd_spin = 0.0
        self._pd_seen = True
        rev_s = PRE_DROP_SPIN_FROM + (
            PRE_DROP_SPIN_TO - PRE_DROP_SPIN_FROM) * clk.frac
        self._pd_spin = (self._pd_spin + rev_s * dt) % 1.0

    def _pre_drop_outline(self):
        """The outline (H x W x 3 float, or None): Star's own shape at a
        shaped radius growing from 0 at the pre-drop to PRE_DROP_OUTLINE_R x
        the panel height on the drop (eased out), turned by Star's rotation
        plus its own spin-up, PRE_DROP_OUTLINE_W thin, dim, in the set's
        colours by angle as the cached palette holds them this frame."""
        clk = self._pd_clk
        if clk is None or clk.segment != "pre_drop" or self.max_radius is None:
            return None
        grow = 1.0 - (1.0 - clk.frac) ** 2
        r = PRE_DROP_OUTLINE_R * float(self.r_height) * grow
        theta = ((self.spin_total + self.rotation + self._pd_spin)
                 % 1.0) * 2 * np.pi
        ang = np.arctan2(self.dy, self.dx) - theta
        shaped = self._shaped_radius(self.radius_base.copy(), ang, theta,
                                     self.edges)
        g = np.clip(PRE_DROP_OUTLINE_W - np.abs(shaped - r), 0.0, 1.0)
        if not g.any():
            return None
        g = g * (PRE_DROP_OUTLINE_GAIN0
                 + (PRE_DROP_OUTLINE_GAIN1 - PRE_DROP_OUTLINE_GAIN0) * clk.frac)
        pos = ((ang / (2.0 * np.pi)) % 1.0).astype(np.float32)
        try:
            col = self.get_gradient_color_vectorized1d(pos.ravel())
        except RuntimeError:                               # no set seen yet
            return None
        col = np.asarray(col, np.float32).reshape(shaped.shape + (3,))
        return (col * g[..., None]).astype(np.float32)

    def _palette_full(self, g):
        """The set's colour at full at palette positions `g` from the
        palette as it is now — exactly what `_set_colours` gave a piece at
        `g` (transition_cloud.nearest_set_grad's own arithmetic), so an
        unchanged set gives the same colour back. None with no palette."""
        from fx.effects import transition_program as tp
        pal = self._palette
        if pal is None:
            return None
        n = tp.PALETTE_GRID.size
        g = np.nan_to_num(np.asarray(g, np.float32), nan=0.0)
        j = np.clip(np.rint(g * (n - 1)).astype(np.int32), 0, n - 1)
        c = pal[j]
        return (c * (255.0 / np.maximum(c.max(axis=1, keepdims=True), 1.0))
                ).astype(np.float32)

    # ── INTO STAR (a transition program's FORM — transition_cloud.
    # RingFormer): the geometry and the bands the arriving pieces land on ──

    def _program_bands(self):
        """The bands a piece may land on: the strip's bright peaks as strip
        positions (n,) 0..1, read off the strip Star draws (`radial-dummy`'s
        assembled frame), with each band's SET colour at full (n, 3). A
        strip with no clear peaks falls back to evenly spaced rings."""
        self._ensure_source()
        strip = None
        src = self.source_virtual
        if src is not None and hasattr(src, "assembled_frame"):
            try:
                strip = np.asarray(src.assembled_frame, dtype=np.float32)
            except Exception:                              # noqa: BLE001
                strip = None
        pos = None
        cols = None
        if strip is not None and strip.ndim == 2 and strip.shape[0] >= 8:
            lum = strip[:, :3].max(axis=1)
            k = np.array([1.0, 2.0, 3.0, 2.0, 1.0], np.float32)
            sm = np.convolve(lum, k / k.sum(), mode="same")
            top = float(sm.max())
            if top > LIT_MIN:
                peak = ((sm[1:-1] >= sm[:-2]) & (sm[1:-1] > sm[2:])
                        & (sm[1:-1] >= BAND_MIN_SHARE * top))
                idx = np.flatnonzero(peak) + 1
                if idx.size >= 2:
                    pos = (idx.astype(np.float32) + 0.5) / strip.shape[0]
                    cols = strip[idx, :3]
        if pos is None:
            pos = BAND_FALLBACK.copy()
            if self._palette is not None:
                from fx.effects import transition_program as tp
                cols = tp.palette_rgb(self._palette, pos)
            else:
                cols = np.full((pos.size, 3), 200.0, np.float32)
        _grad, full = self._set_colours(cols)
        return pos.astype(np.float32), full

    def _program_theta(self):
        """Star's rotation angle this frame (rad)."""
        return float(((self.spin_total + self.rotation) % 1.0) * 2 * np.pi)

    def _program_polar(self, x, y):
        """Pixel positions -> (u, phi): Star's shaped radius and the angle
        in its ROTATING frame (a piece at fixed (u, phi) turns with the
        star) — the inverse of `_piece_xy`."""
        x = np.asarray(x, np.float32)
        y = np.asarray(y, np.float32)
        theta = self._program_theta()
        ang = np.arctan2(y - float(self.cy), x - float(self.cx))
        phi = (ang - theta).astype(np.float32)
        r = np.hypot(x - float(self.cx), y - float(self.cy))
        u = r / (float(self.max_radius) * self._shape_div(phi, theta))
        return u.astype(np.float32), phi

    def _program_band_u(self, band_pos, phi):
        """The shaped radius at which strip position(s) `band_pos` show at
        rotating-frame angle(s) `phi` (the draw samples the strip at
        u + twist x angle_norm)."""
        phi = np.asarray(phi, np.float32)
        # the draw's own angle_norm (atan2 - theta, unwrapped), so a twisted
        # star's band lands where the draw shows it
        an = (phi + np.pi) / (2 * np.pi)
        tw = float(self.twist or 0.0)
        return (np.asarray(band_pos, np.float32) - tw * an) % 1.0
