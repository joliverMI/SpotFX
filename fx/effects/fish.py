import logging

import numpy as np
import voluptuous as vol
from PIL import Image

import fx.effects.particle_handoff as particle_handoff
from fx.color import validate_gradient
from fx.effects.audio import AudioReactiveEffect
from fx.effects.gradient import GradientEffect
from fx.effects.twod import Twod

_LOGGER = logging.getLogger(__name__)

# ── buffer capacity ─────────────────────────────────────────────────────────
# Ordinary swimming is ALWAYS bounded by the `particle_count` parameter. The
# density cap is bypassed at exactly two scripted moments — the charge's
# school (`school_count`) and the lull's rush (`rush_count`) — via the
# `p_nocap` tag, the same shape blackhole's blob rush / fireworks' payoff
# already use. CAP is sized so those two moments plus a full drop explosion
# can never starve the ordinary render (see MAX_* below and
# tests/test_fish.py::test_buffer_headroom).
MAX_PARTICLE_COUNT = 16   # `particle_count` schema max
MAX_SCHOOL = 24           # `school_count` schema max ("up to 12" default)
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

LEAVE_FADE_S = 1.2   # fade-out horizon for departing fish
HANDOFF_ENTER_S = 0.65
HANDOFF_LEAVE_S = 0.55
SLOT_EASE_S = 0.6    # home-anchor re-spacing ease time constant
SPIKE_COOL_S = 0.12  # min gap between beat turn-kicks

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
SPEED_TAU = 0.28        # speed ease time constant (real acceleration)
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
SCHOOL_SEP_BODIES = 3.0  # target spacing, in BODY LENGTHS — derived from the
                         # fish's own size for the same reason
                         # AVOID_SEP_BODIES is, never a second knob
# Low-discrepancy spawn offsets: any PREFIX of these sequences is already
# evenly spread, which matters because a school fills progressively (see
# _charge_step) — an in-order even spread would fill one side of the panel
# first and only look even once the last fish arrived.
SCHOOL_PHI_LAT = 0.6180339887   # golden ratio, lateral
SCHOOL_PHI_DEPTH = 0.7548776662  # plastic number, depth
CENTER_W = 10.0         # the lull's lone fish holding centre

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

# COLOUR — the rule, stated (his ask: "a different color from the fish if
# there is a gradient to work with, or if it's a solid/uniform color, at
# least substantially less bright than the fish").
#
# THE DECISION RULE, read off the RESOLVED gradient curve and not the config
# string: sample the built curve end to end; if every channel's spread
# across those samples is within WAKE_SOLID_TOL, the palette is SOLID.
#   * SOLID  → the wake wears the fish's own colour at WAKE_SOLID_DIM of its
#              amplitude. Distinctness is a BRIGHTNESS ratio.
#   * GRADIENT → the wake samples the gradient WAKE_GRAD_OFFSET further along
#              than the fish that made it — deterministic, and a half turn is
#              the furthest apart two points on a wrapped gradient can be.
#              Distinctness is a COLOUR distance.
WAKE_SOLID_TOL = 8.0 / 255.0
WAKE_SOLID_DIM = 0.35
WAKE_GRAD_OFFSET = 0.5

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
LULL_CENTER_PROGRESS = 0.5
LULL_CENTER_PULL = 9.0   # 1/s positional pull toward centre at p >= 0.5
LULL_DISPERSE_AT = 0.42  # every non-lone fish has left by this progress
LULL_RUSH_AT = 0.60      # the rush enters here
LULL_FALL_S = 3.0        # wall-clock fallback when no lull ramp arrives
DROP_FLY_S = 0.4
DROP_SETTLE_S = 4.2      # drop boost decay / phase auto-reset horizon
DROP_BOOST = 2.5         # extra swim speed at the drop instant
DROP_EJECTA_SPEED = (1.6, 2.9)  # ejecta speed, multiples of cruise

# Every per-fish SoA array, in one place so compaction and the particle
# handoff native snapshot can never drift out of sync with each other.
_SOA_NAMES = (
    "p_mode", "p_nocap", "p_lone", "p_disp", "p_slot", "p_slot_frac",
    "p_x", "p_y", "p_x0", "p_y0", "p_hd", "p_spd", "p_acc",
    "p_flap", "p_jog", "p_ro", "p_lun", "p_lun_t", "p_var",
    "p_enter", "p_erate", "p_leave", "p_lfade",
    "p_nf1", "p_nf2", "p_np1", "p_np2", "p_wf", "p_wp", "p_gf", "p_gp",
    "p_grad", "p_grad_from", "p_scatter", "p_bright",
)


def _wrap_pi(a):
    """Wrap an angle (or array) into (-pi, pi]."""
    return (a + np.pi) % (2 * np.pi) - np.pi


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

    Mutual avoidance (`avoid_strength`, added 2026-08-28) is STEERING ONLY:
    it contributes one more term to the desired-heading vector sum below and
    is then bounded by the same turn-rate clamp as every other term, so the
    two fish laws hold structurally — no fish ever reverses on the spot, and
    every about-face stays a clear arc. It never writes a position.
    """

    NAME = "Fish"
    CATEGORY = "Matrix"
    HIDDEN_KEYS = Twod.HIDDEN_KEYS + ["gradient_roll", "color_blend"]
    ADVANCED_KEYS = Twod.ADVANCED_KEYS + [
        "impulse_decay",
        "color_shift",
        "phase",
        "phase_progress",
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
                default=0.4,
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
                default=0.9,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=4.0)),
            vol.Optional(
                "ripple_width",
                description="Wake thickness: the size of each deposit, relative to the fish",
                default=1.3,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=4.0)),
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
                default=12,
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
                description="Fish in the lull's rush (ignores the population cap)",
                default=20,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_RUSH)),
            vol.Optional(
                "rush_time",
                description="Seconds the lull's rush takes to sweep past",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=3.0)),
            vol.Optional(
                "rush_chaos",
                description="How disorderly the rush is: 0 = a clean shoal, 1 = scattered",
                default=0.5,
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
        }
    )

    def __init__(self, ledfx, config):
        super().__init__(ledfx, config)
        # SoA + accumulators live here (NOT do_once) so they survive config
        # patches — do_once re-runs on every config change.
        self.p_mode = np.zeros(CAP, dtype=np.int8)   # 0 swim 1 enter 2 leave 3 rush
        self.p_nocap = np.zeros(CAP, dtype=np.int8)  # spawned past the cap
        self.p_lone = np.zeros(CAP, dtype=np.int8)   # the lull's lone fish
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
        self.p_lfade = np.full(CAP, LEAVE_FADE_S, dtype=np.float32)
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
        self.ripple_amount = self._config["ripple_amount"]
        self.ripple_spread = self._config["ripple_spread"]
        self.ripple_life = self._config["ripple_life"]
        self.ripple_width = self._config["ripple_width"]
        self.avoid_strength = self._config["avoid_strength"]
        self.roam_scale = self._config["roam_scale"]
        self.camera_follow = self._config["camera_follow"]
        self.school_count = self._config["school_count"]
        self.school_variation = self._config["school_variation"]
        self.turn_min_time = self._config["turn_min_time"]
        self.rush_count = self._config["rush_count"]
        self.rush_time = self._config["rush_time"]
        self.rush_chaos = self._config["rush_chaos"]

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
            self._center_pull = 0.0
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
        """Pond radius in NORMALIZED units. roam_scale=1 is the panel's own
        inscribed ellipse, which on the crystal hex sits comfortably inside
        the lit silhouette (the rectangle's corners are pure gap — see
        .claude/skills/crystal-hex-grid/SKILL.md)."""
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
        self.p_lone[s] = 0
        self.p_disp[s] = np.nan
        self.p_enter[s] = 0.0 if mode == 1 else 1.0
        self.p_erate[s] = 1.0
        self.p_leave[s] = 0.0
        self.p_lfade[s] = LEAVE_FADE_S
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

    def _manage_population(self):
        """Keep the ORDINARY (non-nocap) swimming population equal to
        `particle_count`, then (re)assign evenly spaced home anchors.
        Fish tagged `p_nocap` are the charge school / lull rush and are
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

    def _depart(self, idx, fade=None):
        """Send fish away: they keep their heading and swim off-panel."""
        if len(idx) == 0:
            return
        self.p_mode[idx] = 2
        self.p_leave[idx] = 0.0
        self.p_nocap[idx] = 0
        self.p_lone[idx] = 0
        if fade is not None:
            self.p_lfade[idx] = fade

    # ── particle handoff ────────────────────────────────────────────────
    def _handoff_snapshot(self):
        if getattr(self, "r_width", None) is None or self.trail is None:
            return None
        n = self.n
        px = self.cx + self.p_x[:n] * self.sx - self.cam_px
        py = self.cy + self.p_y[:n] * self.sy - self.cam_py
        px = np.where(np.isfinite(px), px, self.cx)
        py = np.where(np.isfinite(py), py, self.cy)
        return {
            "src": "fish",
            "t": particle_handoff.now(),
            "dims": (self.r_width, self.r_height),
            "px": px.astype(np.float32),
            "py": py.astype(np.float32),
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

    def _spawn_rush(self, count):
        """The lull's rush: fish pour in FROM THE DIRECTION the lone fish is
        heading and zoom past it, with chaos. Tagged `p_nocap` — the ONE
        lull-scoped bypass of the population cap."""
        lone = np.flatnonzero(self.p_lone[: self.n] == 1)
        if lone.size:
            hd = float(self.p_hd[lone[0]])
            ox = float(self.p_x[lone[0]])
            oy = float(self.p_y[lone[0]])
        else:
            hd = self._mean_heading()
            ox, oy = self.cam_nx, self.cam_ny
        base = self.n
        s = self._spawn(count, mode=3, nocap=True)
        k = self.n - base
        if k <= 0:
            return
        rng = self._rng
        chaos = float(self.rush_chaos)
        # enter ahead of the lone fish, spread across its path, travelling
        # back past it
        lateral = rng.uniform(-1.0, 1.0, k) * self.roam_bound * (
            0.5 + 0.9 * chaos
        )
        ahead = self.entry_radius + rng.uniform(0.0, 0.3 + 0.9 * chaos, k)
        self.p_x[s] = ox + np.cos(hd) * ahead - np.sin(hd) * lateral
        self.p_y[s] = oy + np.sin(hd) * ahead + np.cos(hd) * lateral
        self.p_x0[s] = self.p_x[s]
        self.p_y0[s] = self.p_y[s]
        self.p_hd[s] = (
            hd + np.pi + rng.uniform(-1.0, 1.0, k) * chaos * (np.pi / 3.0)
        )
        self.p_spd[s] = self.cruise_px * (
            2.2 + rng.uniform(-1.0, 1.0, k) * chaos * 1.1
        )
        self.p_enter[s] = 1.0
        self.p_lfade[s] = HANDOFF_LEAVE_S

    def _enter_phase(self, phase):
        self._phase = phase
        self._phase_t = 0.0
        self._phase_done_t = None
        self._center_pull = 0.0
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
        """Pick the fish nearest the centre as the lone one; every other
        swimmer is scheduled to disperse across the first part of the lull."""
        n = self.n
        self.p_lone[:n] = 0
        self.p_disp[:n] = np.nan
        self._lull_state = {"rushed": False, "rush_t": None}
        live = np.flatnonzero(self.p_mode[:n] < 2)
        if live.size == 0:
            return
        d = np.hypot(
            (self.p_x[live] - self.cam_nx) * self.sx,
            (self.p_y[live] - self.cam_ny) * self.sy,
        )
        order = live[np.argsort(d)]
        self.p_lone[order[0]] = 1
        # the lone fish is the one that STAYS, so it rejoins the ordinary
        # population here — a charge-school fish that happens to be nearest
        # centre must not carry its cap exemption out of the lull.
        self.p_nocap[order[0]] = 0
        rest = order[1:][::-1]          # furthest leaves first
        if rest.size:
            self.p_disp[rest] = (
                np.arange(1, rest.size + 1, dtype=np.float32) / rest.size
            )

    def _phase_step(self, dt):
        """Advance the charge/lull/drop state machine. Runs every draw,
        before population management; sets the per-frame overrides
        (_speed_scale, _center_pull, particle_count, school state)."""
        pend = self._phase_pending
        if pend is not None:
            self._phase_pending = None
            if pend != self._phase:
                self._enter_phase(pend)
        self._speed_scale = 1.0
        self._center_pull = 0.0
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
            self._drop_state = {"burst_done": True}
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
        in unison — near-identical motion with minor variation."""
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
        """His words: fish disperse until the centre one is all alone,
        swimming but staying in the centre of view by half way through the
        lull; then a rush comes in from the direction it is heading, zooms
        past, and leaves the parameter's own count behind."""
        st = self._lull_state
        if st is None:
            self._start_lull()
            st = self._lull_state
        # progress-driven once the ramp moves (hand-scrubbable in the LedFX
        # UI); the wall-clock fallback only runs while progress sits at 0
        f = p if p > 0.0 else min(self._phase_t / LULL_FALL_S, 1.0)
        # dispersal: everyone but the lone fish is gone by LULL_DISPERSE_AT
        n = self.n
        frac = min(f / max(LULL_DISPERSE_AT, 1e-3), 1.0)
        due = np.flatnonzero(
            np.isfinite(self.p_disp[:n])
            & (self.p_disp[:n] <= frac)
            & (self.p_mode[:n] < 2)
        )
        if due.size:
            self._depart(due)
            self.p_disp[due] = np.nan
        # the lone fish holds centre: full pull by LULL_CENTER_PROGRESS
        self._center_pull = LULL_CENTER_PULL * min(
            f / max(LULL_CENTER_PROGRESS, 1e-3), 1.0
        )
        # the rush
        if not st["rushed"] and f >= LULL_RUSH_AT:
            st["rushed"] = True
            st["rush_t"] = 0.0
            if self.rush_count > 0:
                self._spawn_rush(int(self.rush_count))
        if st.get("rush_t") is not None:
            st["rush_t"] += dt
            if st["rush_t"] >= max(self.rush_time, 0.05):
                st["rush_t"] = None
                self._settle_rush()
        # Hold the population manager to whatever is actually still
        # swimming, so the PACED dispersal above is the only thing that
        # removes a fish and nothing is ever re-spawned mid-lull.
        n = self.n
        self.particle_count = max(1, int(np.count_nonzero(
            (self.p_mode[:n] < 2) & (self.p_nocap[:n] == 0)
        )))

    def _settle_rush(self):
        """The rush is over: keep exactly as many fish as the parameter
        asks for (the lone fish counts toward it) and send the rest on
        their way. This is what puts the population back under its own cap
        — the nocap tag never outlives the moment it was granted for."""
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
            self.p_lfade[stay] = LEAVE_FADE_S
            leave = np.setdiff1d(rushing, stay)
        else:
            leave = rushing
        self._depart(leave, fade=HANDOFF_LEAVE_S)

    def _release_nocap(self):
        """Send every cap-exempt fish away — used when a phase is abandoned
        so ordinary swimming can never inherit a school or a rush."""
        n = self.n
        extra = np.flatnonzero((self.p_nocap[:n] == 1) & (self.p_mode[:n] < 2))
        self._depart(extra, fade=HANDOFF_LEAVE_S)
        self.p_lone[:n] = 0
        self.p_disp[:n] = np.nan

    def _drop_step(self):
        drop = self._drop_state
        if drop is None:
            drop = self._drop_state = {"burst_done": False}
        if not drop["burst_done"]:
            drop["burst_done"] = True
            self._release_nocap()
            self.particle_count = int(self._config["particle_count"])
            n = self.n
            tracked = int(np.count_nonzero(
                (self.p_mode[:n] < 2) & (self.p_nocap[:n] == 0)
            ))
            missing = self.particle_count - tracked
            if missing > 0:
                self._spawn_center_burst(
                    self.cam_nx, self.cam_ny, missing
                )
            # the explosion: 2x more fish that DON'T stay — they bolt
            # straight off the panel during the boost window
            self._spawn_drop_ejecta(DROP_EJECTA_X * self.particle_count)
        self._speed_scale = 1.0 + DROP_BOOST * max(
            1.0 - self._phase_t / DROP_SETTLE_S, 0.0
        )
        if self._phase_t >= DROP_SETTLE_S:
            self._phase = "none"
            self._drop_state = None
            self._speed_scale = 1.0
            # sanctioned in-render config path (under the effect lock);
            # self-reset so an identical later drop write edges again
            self._apply_config(
                {"phase": "none", "phase_progress": 0.0},
                validate=False,
                fire_event=False,
            )

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
        # ONLY the charge and the lull move the window.
        active = self._phase in ("charge", "lull")
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
        the WAKE_SOLID_* block at the top of this module for the rule.
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
        return False, WAKE_GRAD_OFFSET, 1.0

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

        half_life = max(float(self.ripple_life) * WAKE_HALF_LIFE_X, 0.02)
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

        half_life = 0.02 + self.trail_decay * 0.5
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
            )
            np.maximum(self.trail, np.minimum(frame, 255.0), out=self.trail)
            self.p_x0[:k] = x
            self.p_y0[:k] = y

        out = np.asarray(self.matrix, dtype=np.float32) + self.trail
        self.matrix = Image.fromarray(
            np.clip(out, 0, 255).astype(np.uint8), "RGB"
        )

    def _draw_bodies(self, frame, idx, x, y, hd, bright, half_w, flap_amp,
                     grad):
        """Lay each fish's spine out in SCREEN space and splat it.

        The oval's long axis IS the heading, so a fish always points where
        it is going; the lateral throw is a wave travelling from head to
        tail, which is what reads as a flap."""
        k = len(idx)
        if k == 0:
            return
        px = self.cx + x * self.sx - self.cam_px
        py = self.cy + y * self.sy - self.cam_py
        length = half_w * 2.0 * self.body_aspect
        cos_h = np.cos(hd)
        sin_h = np.sin(hd)
        # along-body offsets: +half at the nose, -half at the tail
        along = (0.5 - SPINE_U)[None, :] * length[:, None]
        lat = (
            flap_amp[:, None]
            * np.sin(
                self.p_flap[idx][:, None] - SPINE_U[None, :] * SPINE_WAVE
                * 2 * np.pi
            )
            * SPINE_THROW[None, :]
        )
        sx_ = px[:, None] + along * cos_h[:, None] - lat * sin_h[:, None]
        sy_ = py[:, None] + along * sin_h[:, None] + lat * cos_h[:, None]
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
        pts_x = []
        pts_y = []
        pts_rgb = []
        pts_size = []
        for f in range(SUBSTEPS):
            back = (SUBSTEPS - 1 - f) / SUBSTEPS
            pts_x.append((sx_ - dx[:, None] * back).ravel())
            pts_y.append((sy_ - dy[:, None] * back).ravel())
            pts_size.append(sizes.ravel())
            pts_rgb.append(
                np.repeat(
                    rgb * (bright[:, None] / SUBSTEPS), SPINE_U.size, axis=0
                )
            )
        self._splat_many(
            frame,
            np.concatenate(pts_x),
            np.concatenate(pts_y),
            np.concatenate(pts_rgb),
            np.concatenate(pts_size),
        )

    # ── main ────────────────────────────────────────────────────────────
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

        rscale = self.reactivity_scale
        impulse = min(self.impulse, 1.0)
        direction = -1.0 if self.reverse else 1.0
        jiggle = self.jiggle

        spike = np.clip((self.impulse - self.slow) * 3.0, 0.0, 1.0)
        beat_now = self._beat_pending

        self._phase_step(dt)
        self._manage_population()
        n = self.n
        if n == 0:
            self._fade_only(dt)
            return

        if beat_now and self._phase != "charge":
            spike = max(spike, 0.4 + 0.5 * impulse)
            self._beat_pending = False

        self.roll_total = (self.roll_total + self.gradient_spin * dt) % 1.0

        mode = self.p_mode[:n]
        swimming = mode < 2
        rushing = mode == 3
        steered = swimming | rushing
        m = int(np.count_nonzero(swimming))

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
        want = (
            cruise
            * (1.0 + jump_eff * impulse * gain)
            * (1.0 + self.p_lun[:n])
            * (1.0 + 0.25 * jiggle * n_r)
            * (1.0 + self.p_ro[:n])
            * self._speed_scale
            * np.where(mode == 1, ENTER_SPEED_X, 1.0)
        )
        # leaving/rushing fish hold whatever they left with
        prev = self.p_spd[:n].copy()
        ease = min(1.0, dt / max(SPEED_TAU, 1e-3))
        self.p_spd[:n] = np.where(
            steered, prev + (want - prev) * ease, prev
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
        desired_x += np.cos(to_home) * w_home
        desired_y += np.sin(to_home) * w_home

        # the pond edge — how much water is left straight ahead, in px
        # (ray/ellipse intersection in normalized space, read back as a
        # distance the fish would actually swim)
        bound = self.roam_bound
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
            (need * BOUND_SOFT - ahead_px) / max(need * (BOUND_SOFT - 1.0), 1e-3),
            0.0, 1.0,
        ) * BOUND_W
        w_bound = np.where(swimming, w_bound, 0.0)
        inward = np.arctan2(-rel_y * self.sy, -rel_x * self.sx)
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
        # identically" and the lull's rush is deliberately chaotic — both are
        # authored choreography, not crowds to fix — so avoidance is never
        # allowed to argue with either.
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
                add_x = np.zeros(n, dtype=np.float32)
                add_y = np.zeros(n, dtype=np.float32)
                add_x[idx] = np.cos(swerve) * w_avoid
                add_y[idx] = np.sin(swerve) * w_avoid
                desired_x += add_x
                desired_y += add_y

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

        # the lull's lone fish keeps to the centre of view
        lone = self.p_lone[:n] == 1
        if self._center_pull > 0.0 and lone.any():
            w_center = np.where(lone & swimming, CENTER_W, 0.0)
            desired_x += np.cos(inward) * w_center
            desired_y += np.sin(inward) * w_center

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
        omega = (
            d_hd * TURN_GAIN
            + np.where(steered, swirl + self.p_jog[:n], 0.0)
        )
        # THE turn-circle guarantee: no steering term, kick or phase can
        # turn a fish faster than its own radius allows, so an about-face
        # is always an arc and never a flip.
        omega = np.clip(omega, -omega_max, omega_max)
        omega = np.where(steered, omega, 0.0)
        self.p_hd[:n] = _wrap_pi(hd + omega * dt)
        hd = self.p_hd[:n]

        # ── integrate ───────────────────────────────────────────────────
        vx_px = np.cos(hd) * self.p_spd[:n]
        vy_px = np.sin(hd) * self.p_spd[:n]
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

        if self._center_pull > 0.0 and lone.any():
            # his words: the lone fish stays "in the centre of VIEW" — so
            # the pull is toward the window's centre, which is the same
            # world point it always was whenever the window is at rest.
            pull = np.float32(min(self._center_pull * dt, 1.0))
            self.p_x[:n] = np.where(
                lone, cnx + (self.p_x[:n] - cnx) * (1.0 - pull), self.p_x[:n]
            )
            self.p_y[:n] = np.where(
                lone, cny + (self.p_y[:n] - cny) * (1.0 - pull), self.p_y[:n]
            )

        entering = mode == 1
        if entering.any():
            self.p_enter[:n] = np.where(
                entering,
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
        flap_freq = self.flap_rate * (0.4 + 0.6 * speed_norm)
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
        fade_in = np.where(
            entering, np.clip(self.p_enter[:n] * 3.3, 0.0, 1.0), 1.0
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
            # the deposit is laid at the tail, sized by the motion that made
            # it: the body's own length and the tail's lateral throw
            tail_px = (
                self.cx + self.p_x[:n][laying] * self.sx
                - np.cos(hd[laying]) * body_len * 0.5
            )
            tail_py = (
                self.cy + self.p_y[:n][laying] * self.sy
                - np.sin(hd[laying]) * body_len * 0.5
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
            self._deposit_wake(
                tail_px, tail_py, amp, sizes, self.p_grad[:n][laying]
            )
        self._step_wake(dt)

        # ── render ──────────────────────────────────────────────────────
        half_life = 0.02 + self.trail_decay * 0.5
        self.trail *= np.float32(0.5 ** (dt / half_life))

        frame = np.zeros_like(self.trail)
        visible = np.flatnonzero(bright > 0.0)
        if visible.size:
            self._draw_bodies(
                frame, visible,
                self.p_x[:n][visible], self.p_y[:n][visible],
                hd[visible], bright[visible], half_w[visible],
                flap_amp[visible], self.p_grad[:n][visible],
            )
        np.maximum(self.trail, np.minimum(frame, 255.0), out=self.trail)

        self.p_x0[:n] = self.p_x[:n]
        self.p_y0[:n] = self.p_y[:n]

        # retire departed fish once fully off-panel or faded
        gone = leaving | rushing
        if gone.any():
            px = self.cx + self.p_x[:n] * self.sx - self.cam_px
            py = self.cy + self.p_y[:n] * self.sy - self.cam_py
            off = (
                (np.abs(px - self.cx) > (self.r_width + 12))
                | (np.abs(py - self.cy) > (self.r_height + 12))
            )
            dead = (leaving & ((self.p_leave[:n] >= self.p_lfade[:n]) | off))
            dead = dead | (rushing & off)
            if dead.any():
                self._compact(~dead)

        out = np.asarray(self.matrix, dtype=np.float32) + self.trail
        if self.wake is not None:
            out = out + self.wake
        self.matrix = Image.fromarray(
            np.clip(out, 0, 255).astype(np.uint8), "RGB"
        )

    def _fade_only(self, dt):
        """Decay the trail AND the wake, and composite — the held-transition
        path. The wake is a live buffer, so leaving it out here would park a
        frozen smear on the panel for the whole hold."""
        half_life = 0.02 + self.trail_decay * 0.5
        self.trail *= np.float32(0.5 ** (dt / half_life))
        self._step_wake(dt)
        out = np.asarray(self.matrix, dtype=np.float32) + self.trail
        if self.wake is not None:
            out = out + self.wake
        self.matrix = Image.fromarray(
            np.clip(out, 0, 255).astype(np.uint8), "RGB"
        )
