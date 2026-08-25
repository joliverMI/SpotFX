import logging
import math

import numpy as np
import voluptuous as vol
from PIL import Image

import fx.effects.particle_handoff as particle_handoff
from fx.color import parse_color, validate_color, validate_gradient
from fx.effects.audio import AudioReactiveEffect
from fx.effects.gradient import GradientEffect
from fx.effects.twod import Twod

_LOGGER = logging.getLogger(__name__)

CAP = 1024          # particle capacity; overflow spawns are dropped
SUBSTEPS = 3        # path sub-samples per frame (gap-free smear)
R_FLOOR = 0.06      # radius floor for angular-velocity calc
OMEGA_MAX = 6 * np.pi
DT_MAX = 0.1
FADE_IN_S = 0.15
HORIZON_BLEND_S = 0.6   # seconds to morph a captured blob to the horizon color
HORIZON_FADE_S = 0.8    # fade-out after horizon_hold expires
KERNEL_R = 6        # max blob radius the offset table supports
BAND_ANCHORS = np.array([0.0, 1 / 3, 2 / 3], dtype=np.float32)
BAND_JITTER = 0.06
# charge/lull/drop choreography (SpotFX drives `phase` + ramps
# `phase_progress`; see _phase_step)
DROP_RESET_S = 0.5       # post-burst ease of the horizon back to baseline
PHASE_BURST_N = 48       # blobs in the drop explosion (his ask: at least 2x
                         # the original 24)
# His ask, verbatim: "the timing is good on black hole, but the speed of
# the explosion after the implosion needs to be 2 times faster." Scoped to
# exactly the post-pinch outward burst (_phase_burst's blobs, tagged
# p_is_burst) — NOT the whole drop (the horizon's post-burst ease-back is
# still DROP_RESET_S, untouched). The burst's own LANDING point on the
# trigger's timestamp is a separate question from this multiplier — it
# used to be pinned by this same comment (progress-gated, `p >= 0.995`);
# that anchor was superseded 2026-08-20 (drop anchors its START to the
# mark now, not its end — see _phase_step's own docstring) and this
# multiplier is unaffected either way: it only scales what happens AFTER
# the burst fires, never when. Applied as a matched pair in _phase_burst
# (halves the p_out outward-flight duration) and draw()'s out_mask branch
# (doubles velocity only for p_is_burst particles): halving time while
# doubling speed covers the SAME outward distance in half the time — the
# explosion reaches the same size it always did, just twice as fast,
# rather than reaching twice as far in the same time (a bigger burst, not
# a faster one — not what was asked). _erupt_burst's cross-effect handoff
# eruptions reuse the same out_mask/p_out mechanism but are never tagged
# p_is_burst, so they are untouched by this multiplier.
PHASE_BURST_SPEED_MULT = 2.0
CHARGE_HALO_LEAD = 1.4   # halo (capture ring) growth vs the black disc

# reverse RELEASE fall-back (his ask, 2026-08-24: "when it reverses back to
# normal, currently the blobs immediately change direction. I want them to
# accelerate back to the black hole, but not immediately change direction...
# The current setting is too jerky").
#
# `reverse` is a SPAWN-SIDE flag: it decides where a blob is BORN (horizon
# ring vs the hex boundary) and which sign draw()'s `new_r = r ± v·dt` uses
# for EVERY live blob. Nothing ever reversed the velocity of a particle
# already in flight — so the momentary flare's release flipped the whole
# outbound population's direction in a single frame. It is the direction
# sign that snapped, not the speed (both directions read the same
# per-radius speed curve).
#
# The fix is a real turnaround: on the True→False edge every outbound blob
# keeps its outward velocity and decelerates under an inward acceleration
# until its velocity has passed continuously through zero and MATCHES the
# infall curve's own speed at its current radius, at which point it merges
# into ordinary infall physics with no step at the seam (the trap p_out's
# own expiry falls into — that one stalls to zero and hands the particle to
# full-speed infall on the next frame, an instant jump the other way).
#
# "The acceleration value we have" is the speed curve itself (base_speed /
# accel / edge_speed, audio boost included): the deceleration is
# 2·v(r)/REVERSE_FALLBACK_TURN_S, where v(r) is the SAME per-particle
# infall speed draw() already computes this frame. Expressing it relative
# to that speed rather than as a fixed r/s² makes the turn take
# REVERSE_FALLBACK_TURN_S regardless of base_speed, radius, or the live
# audio boost (the boost scales v and the deceleration alike, so it
# cancels) — one number to tune, and it means the same thing on every
# config. Blobs past the rim (where the curve floors at
# base_speed·edge_speed) still turn: v never reaches 0, so neither does
# the deceleration.
REVERSE_FALLBACK_TURN_S = 0.5
# A horizon captive is PINNED to the ring only while it is actually within
# this of it (normalized r). See draw()'s capture branch: this is what lets
# a captive the outflow carried off the ring fall back under ordinary
# physics instead of being teleported onto the ring the frame `reverse`
# flips back — WITHOUT releasing its capture, which is the part PR #179
# got wrong (reverted in #181, no reason recorded; see
# _arm_reverse_fallback's own docstring).
REVERSE_FALLBACK_RING_TOL = 0.02

# BLOB RUSH (his ask, 2026-08-24): "a new effect that runs as a shape flare
# ... it just generates 12 blobs all at once spread out fairly evenly.
# Override any max blob counts for this generation if that's easy". The
# count is SpotFX's (scene_response.BLOB_RUSH_BLOBS) and arrives on the
# `blob_rush` config key — an instant "spawn this many NOW" write,
# edge-detected in config_updated and self-reset after firing, exactly like
# fireworks' `burst_rockets` (fx/VENDOR.md #15) and the phase keys. "Fairly
# evenly" is fireworks' own equidistant-rocket shape (#16): even 2*pi/k
# spacing, the whole ring randomly rotated per rush, each blob nudged by at
# most BLOB_RUSH_WIGGLE_FRAC of one step — so no two ever swap order and
# the ring still reads as a ring. The cap override is the p_is_burst
# no-cap tag the drop payoff already uses (see _spawn): rush blobs don't
# occupy max_blobs, so a rush can never silence the ambient/beat spawn
# underneath it — his "or remove the ones in the event horizon" alternative
# is deliberately NOT taken, nothing already on screen is disturbed.
BLOB_RUSH_WIGGLE_FRAC = 1.0 / 6.0   # fireworks' own wiggle (deviation #16)

# infall-mode (`reverse=False`) spawn boundary, in the same normalized-r
# units as radius_scale (r=1 sits at the panel's own rectangular edge).
#
# History: fixed (0.90, 1.05) — right at/past the rim — spawned almost
# entirely in dead corner gap on a hex-lattice matrix virtual (invisible
# until a blob had fallen most of the way to the horizon). Pulling that in
# to SPAWN_ANNULUS_MIN/MAX = (0.70, 0.85) maximized real-pixel hit rate
# (scripts/check_blackhole_hex_spawn.py), but overshot: his live report,
# 2026-08-18, was that blobs now spawn "several pixels" inside the visible
# edge instead of arriving from it. Those two fixes were optimizing
# different things — hit rate pulls inward, "arrives from the boundary"
# does not — and hit rate was never the actual ask.
#
# The boundary itself is NOT a circle, so a single scalar can't hit it
# everywhere. crystal-mapper's real-light silhouette is a hexagon inscribed
# in its addressable rectangle (.claude/skills/crystal-hex-grid/SKILL.md) —
# its distance from center genuinely depends on direction: ~0.87
# normalized-r at a flat edge's own midpoint-normal, ~1.13 at a corner
# vertex, a ~30% swing. Picking one number near the tight end (the
# silhouette's own inradius-like minimum, ~0.87) leaves spawns deep inside
# the silhouette at every other angle — numerically almost the same range
# the too-far-in 0.70-0.85 annulus already covered, so it would barely move
# the ring. Picking one number near the loose end (~1.13, the corners)
# overshoots the flat-edge directions by ~30% into dead gap the rest of the
# way around. A circle tangent to a convex hexagon's edges at their
# midpoints (radius = the hexagon's inradius) sits INSIDE the hexagon
# everywhere else, by definition — it can't poke outside toward the
# corners, that direction is exactly where a fixed-radius circle falls
# furthest short of a convex boundary. There is no scalar that is "tangent
# to the edge" in more than the 6 directions where it happens to coincide;
# the fix has to follow the boundary's own shape.
#
# HEX_SPAWN_VERTS are that boundary's true vertices, measured off the real
# device profile (storage/device_profiles/crystal-mapper.json — the same
# row/column real-cell extents scripts/check_blackhole_hex_spawn.py already
# reads), in the same normalized (gx, gy) space Blackhole2d projects into
# (gx=(x-cx)/sx, gy=(y-cy)/sy — see do_once). `_hex_spawn_edge_radius(theta)`
# evaluates the polygon's own support function — for each direction, the
# closest of the 6 edge-lines that direction can reach — to get the exact
# per-direction boundary distance as a closed form, not a lookup table, so
# it costs nothing extra per spawn. Verified against the boundary measured
# directly off the device profile (max real-cell radius per 5-degree
# angular bin) to within +/-0.06 normalized-r — lattice/quantization noise,
# not formula error (scripts/check_blackhole_hex_spawn.py).
#
# SPAWN_EDGE_MARGIN_MIN/MAX then push OUT from that true per-direction
# boundary by a further 0.02-0.12 — "just outside... or right in line with
# the edge" (his words), a band relative to the local edge rather than an
# absolute annulus. This is a WORSE real-pixel hit rate than the
# maximize-hit-rate 0.70-0.85 annulus by design, reported alongside this
# comment's own PR rather than silently regressed: a spawn a hair past the
# true boundary starts dark and lights up the instant it falls back across
# its own local edge, which is the arriving-from-outside look he asked for,
# not a defect to tune back in.
HEX_SPAWN_VERTS = (
    (-0.5211, -1.0000),
    (0.4366, -1.0000),
    (1.0000, 0.0000),
    (0.4366, 1.0000),
    (-0.5211, 1.0000),
    (-1.0000, 0.0000),
)
SPAWN_EDGE_MARGIN_MIN = 0.02
SPAWN_EDGE_MARGIN_MAX = 0.12


def _hex_spawn_faces():
    """Precompute each HEX_SPAWN_VERTS edge as an outward unit normal (nx,
    ny) plus its perpendicular distance `d` from the origin (center) —
    the support-function form used by `_hex_spawn_edge_radius`."""
    faces = []
    count = len(HEX_SPAWN_VERTS)
    for i in range(count):
        x1, y1 = HEX_SPAWN_VERTS[i]
        x2, y2 = HEX_SPAWN_VERTS[(i + 1) % count]
        nx, ny = y2 - y1, -(x2 - x1)
        norm = math.hypot(nx, ny)
        nx, ny = nx / norm, ny / norm
        d = nx * x1 + ny * y1
        if d < 0:
            nx, ny, d = -nx, -ny, -d
        faces.append((nx, ny, d))
    return faces


_HEX_FACES = _hex_spawn_faces()
_HEX_FACE_NX = np.array([f[0] for f in _HEX_FACES], dtype=np.float32)
_HEX_FACE_NY = np.array([f[1] for f in _HEX_FACES], dtype=np.float32)
_HEX_FACE_D = np.array([f[2] for f in _HEX_FACES], dtype=np.float32)


def _hex_spawn_edge_radius(theta):
    """Distance from center to the measured crystal-mapper hex silhouette
    along each angle in `theta` (radians, any shape) — the convex-polygon
    support function: the boundary in a given direction is the nearest of
    the 6 edge-lines actually facing that direction."""
    ux = np.cos(theta)
    uy = np.sin(theta)
    denom = (
        _HEX_FACE_NX[:, None] * ux[None, :]
        + _HEX_FACE_NY[:, None] * uy[None, :]
    )
    safe_denom = np.where(denom > 1e-6, denom, 1.0)
    r = np.where(denom > 1e-6, _HEX_FACE_D[:, None] / safe_denom, np.inf)
    return r.min(axis=0).astype(np.float32)


class Blackhole2d(Twod, GradientEffect):
    NAME = "Blackhole"
    CATEGORY = "Matrix"
    # color_spin supersedes gradient_roll for this effect; color_blend stays
    # hidden — colors update in place, recreation would kill the particles.
    # phase/phase_progress are SpotFX-driven choreography; advanced (not
    # hidden) so the arc can be hand-scrubbed in the LedFX UI for tuning.
    # blob_rush is the same kind of key (SpotFX's blob_rush flare drives
    # it; self-resets after firing).
    HIDDEN_KEYS = Twod.HIDDEN_KEYS + ["gradient_roll", "color_blend"]
    ADVANCED_KEYS = Twod.ADVANCED_KEYS + [
        "accel",
        "edge_speed",
        "kill_radius",
        "impulse_decay",
        "phase",
        "phase_progress",
        "blob_rush",
        "horizon_follow_blobs",
    ]

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "gradient",
                description="Blob color gradient",
                default="linear-gradient(90deg, #ff0000 0.00%,#ff7800 14.00%,#ffc800 28.00%,#00ff00 42.00%,#00c78c 56.00%,#0000ff 70.00%,#800080 84.00%,#ff00b2 98.00%)",
            ): validate_gradient,
            vol.Optional(
                "swirl",
                description="Swirl amount; sign sets direction, 0 = straight infall",
                default=3.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=-6.0, max=6.0)),
            vol.Optional(
                "reverse",
                description="Blobs flow from center out to the perimeter",
                default=True,
            ): bool,
            vol.Optional(
                "radius_scale",
                description="Spawn radius as a fraction of the panel edge",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=2.0)),
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
                "blob_size",
                description="Blob radius in pixels",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=6.0)),
            vol.Optional(
                "spawn_rate",
                description="Base blobs spawned per second; 0 = beat bursts only (dark without beats)",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=60.0)),
            vol.Optional(
                "beat_burst",
                description="Extra blobs spawned on each beat",
                default=1,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=12)),
            vol.Optional(
                "base_speed",
                description="Infall speed near the center, in radii per second",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=2.0)),
            vol.Optional(
                "accel",
                description="Speed curve exponent: higher = slower at the edge, harder fall",
                default=2.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=5.0)),
            vol.Optional(
                "edge_speed",
                description="Speed at the rim as a fraction of the center speed",
                default=0.25,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=1.0)),
            vol.Optional(
                "max_blobs",
                description="Density cap: spawning pauses at this many live blobs",
                default=50,
            ): vol.All(vol.Coerce(int), vol.Range(min=20, max=1024)),
            vol.Optional(
                "kill_radius",
                description="Radius at which blobs are consumed (spawn radius in reverse)",
                default=0.04,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=0.2)),
            vol.Optional(
                "trail_decay",
                description="Comet-trail length: 0 = crisp dots, 1 = long smear",
                default=0.4,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "color_mode",
                description="wheel: gradient wraps the circle and spins with gradient_spin; band: audio bands pick position; random: uniform (spin invisible)",
                default="wheel",
            ): vol.In(["wheel", "band", "random"]),
            vol.Optional(
                "gradient_spin",
                description="Rotate the gradient mapping over time (rev/s); direction follows the swirl",
                default=0.1,
            ): vol.All(vol.Coerce(float), vol.Range(min=-1.0, max=1.0)),
            vol.Optional(
                "spawn_audio",
                description="How much the selected band boosts the spawn rate",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(
                "speed_audio",
                description="How much the selected band boosts the fall speed",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=5.0)),
            vol.Optional(
                "horizon_scale",
                description="Event-horizon radius baseline; blobs orbit here instead of falling in. 0 disables",
                default=0.25,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=0.8)),
            vol.Optional(
                "horizon_audio",
                description="How much sound grows (+) or shrinks (-) the event horizon",
                default=0.3,
            ): vol.All(vol.Coerce(float), vol.Range(min=-1.0, max=1.0)),
            vol.Optional(
                "horizon_follow_blobs",
                description="Event horizon glow and charge/drop halo take the current blob gradient color; when off, horizon_color is used instead",
                default=True,
            ): bool,
            vol.Optional(
                "horizon_color",
                description="Color blobs take on while orbiting the event horizon (only used when horizon_follow_blobs is off)",
                default="#ffffff",
            ): validate_color,
            vol.Optional(
                "horizon_hold",
                description="Seconds a blob orbits the horizon before fading out",
                default=2.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=10.0)),
            vol.Optional(
                "frequency_range",
                description="Audio band driving spawn/speed reactivity",
                default="Lows (beat+bass)",
            ): vol.In(list(AudioReactiveEffect.POWER_FUNCS_MAPPING.keys())),
            vol.Optional(
                "impulse_decay",
                description="Decay filter applied to the audio impulse",
                default=0.06,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=0.3)),
            vol.Optional(
                "handoff_ease",
                description="Seconds adopted particles take to wind up to full speed after an effect switch",
                default=1.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=5.0)),
            vol.Optional(
                "color_blend",
                description="Restart effect on color change, for transitions",
                default=False,
            ): bool,
            vol.Optional(
                "blob_rush",
                description="Blobs to spawn right now, evenly spread (driven by SpotFX flares; self-resets)",
                default=0,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=64)),
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
        # Particle SoA + accumulators live here (NOT do_once) so they survive
        # config patches — do_once re-runs on every config change and mid-ramp
        # resets would kill all particles.
        self.p_r = np.zeros(CAP, dtype=np.float32)
        self.p_theta = np.zeros(CAP, dtype=np.float32)
        self.p_grad = np.zeros(CAP, dtype=np.float32)
        self.p_bright = np.zeros(CAP, dtype=np.float32)
        self.p_age = np.zeros(CAP, dtype=np.float32)
        self.p_band = np.zeros(CAP, dtype=np.int8)
        # capture age on the event horizon; -1 = free-falling
        self.p_cap = np.full(CAP, -1.0, dtype=np.float32)
        # seconds of outward flight left (radial-handoff eruption burst)
        self.p_out = np.zeros(CAP, dtype=np.float32)
        # True for a drop-payoff burst particle (_phase_burst) — excluded
        # from the ambient spawn's max_blobs check (see _spawn) so doubling
        # PHASE_BURST_N can't starve the ambient/beat spawn that's supposed
        # to keep coming through the drop.
        self.p_is_burst = np.zeros(CAP, dtype=bool)
        self.n = 0
        self.spawn_acc = 0.0
        self.spin_total = 0.0
        self._beat_pending = False
        self.impulse = 0.0
        self.band_powers = np.zeros(3, dtype=np.float32)
        self._rng = np.random.default_rng()
        self.trail = None
        # adopt a predecessor's on-screen particles on the first draw
        self._handoff_pending = True
        # seconds since a cross-effect adoption; None = no wind-up active
        self._adopt_age = None
        # predecessor blob size we ease FROM during the wind-up
        self._adopt_size_from = None
        # outgoing-to-radial collapse state; None = normal physics
        self._collapse = None
        # held center eruption while a radial predecessor collapses
        self._erupt_hold = None
        # held pacman adoption while its maze fades out (phase 1)
        self._pacman_hold = None
        # scalar gate so p_out is only scanned while a burst is in flight
        self._out_active = False
        # reverse-release fall-back (see REVERSE_FALLBACK_TURN_S): p_turn
        # marks a blob mid-turnaround, p_vr is its SIGNED radial velocity
        # while it is (+ = outward). A separate flag is load-bearing: the
        # velocity passes through exactly 0.0 at the stall, so 0.0 cannot
        # double as the "not turning" sentinel without reintroducing the
        # instant-stall discontinuity this mechanism exists to remove.
        self.p_turn = np.zeros(CAP, dtype=bool)
        self.p_vr = np.zeros(CAP, dtype=np.float32)
        # scalar gate so p_turn is only scanned while a turn is in flight
        self._turn_active = False

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
        self.swirl = self._config["swirl"]
        prev_reverse = getattr(self, "reverse", None)
        self.reverse = self._config["reverse"]
        self.radius_scale = self._config["radius_scale"]
        self.x_offset = self._config["x_offset"]
        self.y_offset = self._config["y_offset"]
        self.blob_size = self._config["blob_size"]
        self.spawn_rate = self._config["spawn_rate"]
        self.beat_burst = int(self._config["beat_burst"])
        self.base_speed = self._config["base_speed"]
        self.accel = self._config["accel"]
        self.edge_speed = self._config["edge_speed"]
        self.max_blobs = int(self._config["max_blobs"])
        self.kill_radius = self._config["kill_radius"]
        self.trail_decay = self._config["trail_decay"]
        self.color_mode = self._config["color_mode"]
        self.gradient_spin = self._config["gradient_spin"]
        self.spawn_audio = self._config["spawn_audio"]
        self.speed_audio = self._config["speed_audio"]
        self.horizon_scale = self._config["horizon_scale"]
        self.horizon_audio = self._config["horizon_audio"]
        self.horizon_hold = self._config["horizon_hold"]
        self.handoff_ease = self._config["handoff_ease"]
        self.horizon_follow_blobs = self._config["horizon_follow_blobs"]
        self._horizon_rgb_explicit = np.array(
            parse_color(self._config["horizon_color"]), dtype=np.float32
        )
        # overwritten per-frame in draw() when horizon_follow_blobs is on;
        # this is the value used until the first draw() call
        self.horizon_rgb = self._horizon_rgb_explicit

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
            self._phase_saved = {}
            self._drop = None
            self._phase_done_t = None
            # same creation baseline for the reverse edge: a stale
            # persisted `reverse` must never turn a fresh instance's
            # (empty) population around on its first frame
            self._reverse_edge = None
        else:
            # non-creation pass: a changed phase key arms the edge
            self._phase_pending = new_phase if new_phase != self._phase else None
            # ... and so does a changed `reverse`, in either direction.
            # EDGE-detected, never per-write: config_updated runs on every
            # config patch (a gain envelope, a spawn_rate move), and only a
            # genuine flip should touch particle motion. Only armed here —
            # draw() consumes it, because arming needs each particle's LIVE
            # speed, which only the render step computes.
            if prev_reverse is not None and prev_reverse != self.reverse:
                self._reverse_edge = "fallback" if prev_reverse else "eject"

        # BLOB RUSH: edge-detect the count exactly like fireworks'
        # burst_rockets (SpotFX writes a count, draw consumes it and
        # self-resets the key to 0 so an identical later write edges again)
        new_rush = int(self._config.get("blob_rush", 0))
        if not hasattr(self, "_rush_seen"):
            # creation baseline: a stale persisted count must never rush on
            # a fresh instance
            self._rush_seen = new_rush
            self._rush_pending = 0
        elif new_rush != self._rush_seen:
            self._rush_seen = new_rush
            if new_rush > 0:
                self._rush_pending += new_rush

        self.power_func = self.POWER_FUNCS_MAPPING[
            self._config["frequency_range"]
        ]
        decay = self._config["impulse_decay"]
        self.impulse_filter = self.create_filter(
            alpha_decay=decay, alpha_rise=0.99
        )
        self.band_filters = [
            self.create_filter(alpha_decay=decay, alpha_rise=0.99)
            for _ in range(3)
        ]

    def audio_data_updated(self, data):
        impulse = self.impulse_filter.update(
            getattr(data, self.power_func)()
        )
        self.impulse = float(impulse) if np.isfinite(impulse) else 0.0
        raw = (
            data.lows_power(filtered=False),
            data.mids_power(filtered=False),
            data.high_power(filtered=False),
        )
        for index, value in enumerate(raw):
            filtered = self.band_filters[index].update(value)
            self.band_powers[index] = (
                float(filtered) if np.isfinite(filtered) else 0.0
            )
        if data.bpm_beat_now():
            self._beat_pending = True

    def do_once(self):
        super().do_once()
        self.cx = (self.r_width - 1) * self.x_offset
        self.cy = (self.r_height - 1) * self.y_offset
        # Physics is circular in normalized space; this projection stretches
        # it into a panel-filling ellipse.
        self.sx = self.radius_scale * (self.r_width - 1) / 2.0
        self.sy = self.radius_scale * (self.r_height - 1) / 2.0
        # Normalized radius per pixel (same projection as the particles) —
        # used to paint the black-hole interior with the background color.
        y_idx, x_idx = np.indices((self.r_height, self.r_width))
        gx = (x_idx - self.cx) / max(self.sx, 1e-6)
        gy = (y_idx - self.cy) / max(self.sy, 1e-6)
        self.grid_r = np.sqrt(gx**2 + gy**2).astype(np.float32)
        # normalized radius just past the farthest panel corner: outflow
        # blobs stay alive into the corners (instead of popping at the
        # inscribed rim) and wide-field adopted blobs aren't culled on entry
        self.r_max = float(self.grid_r.max()) + 0.08
        if self.trail is None or self.trail.shape[:2] != (
            self.r_height,
            self.r_width,
        ):
            self.trail = np.zeros(
                (self.r_height, self.r_width, 3), dtype=np.float32
            )

    def _compact(self, alive, *extra):
        """Compact live particles to the front of every SoA array. Returns
        the extra arrays (pre-update state) masked the same way."""
        count = int(np.count_nonzero(alive))
        for arr in (
            self.p_r,
            self.p_theta,
            self.p_grad,
            self.p_bright,
            self.p_age,
            self.p_band,
            self.p_cap,
            self.p_out,
            self.p_is_burst,
            self.p_turn,
            self.p_vr,
        ):
            arr[:count] = arr[: self.n][alive]
        self.n = count
        return tuple(arr[alive] for arr in extra)

    def _handoff_snapshot(self):
        """Live particle state in the neutral handoff format (see
        particle_handoff module). None before the first render."""
        if getattr(self, "r_width", None) is None or self.trail is None:
            return None
        n = self.n
        px = self.cx + self.p_r[:n] * np.cos(self.p_theta[:n]) * self.sx
        py = self.cy + self.p_r[:n] * np.sin(self.p_theta[:n]) * self.sy
        return {
            "src": "blackhole",
            "t": particle_handoff.now(),
            "dims": (self.r_width, self.r_height),
            "px": px.astype(np.float32),
            "py": py.astype(np.float32),
            "grad": self.p_grad[:n].copy(),
            "bright": self.p_bright[:n].copy(),
            "gradient": self._config.get("gradient"),
            # screen rotation sign, blob size, flow direction and center so
            # a successor can continue the motion instead of restating its own
            "spin_sign": float(np.sign(self.swirl)),
            "blob_size": float(self.blob_size),
            "flow": "out" if self.reverse else "in",
            "center_px": (float(self.cx), float(self.cy)),
            # horizon-captured blobs: successors let these fade out in
            # place (via the merged trail) instead of flying them around
            "captured": (self.p_cap[:n] >= 0.0),
            "trail": self.trail,
            "native": {
                "n": n,
                "spawn_acc": self.spawn_acc,
                "spin_total": self.spin_total,
                "arrays": {
                    name: getattr(self, name)[:n].copy()
                    for name in (
                        "p_r", "p_theta", "p_grad", "p_bright",
                        "p_age", "p_band", "p_cap", "p_out", "p_is_burst",
                        "p_turn", "p_vr",
                    )
                },
            },
        }

    def deactivate(self):
        # Leave live state behind for a successor instance (effect switch or
        # same-type recreation) before the base clears _virtual.
        virtual = self._virtual
        try:
            if virtual is not None:
                particle_handoff.store(virtual.id, self._handoff_snapshot())
        except Exception:
            pass
        super().deactivate()

    def _adopt_handoff(self, snap=None, allow_hold=True):
        """First-draw adoption of the predecessor's on-screen particles:
        read the live crossfade sibling if present, else the registry.
        A pre-fetched `snap` (the pacman-hold release path) skips the fetch."""
        virtual = self._virtual
        live = snap is not None
        if snap is None:
            sibling = getattr(virtual, "_transition_effect", None) if virtual else None
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
            # merge so trail history survives the switch
            np.maximum(self.trail, snap["trail"], out=self.trail)
        if snap["src"] == "blackhole":
            native = snap["native"]
            k = min(native["n"], CAP)
            for name, arr in native["arrays"].items():
                getattr(self, name)[:k] = arr[:k]
            self.n = k
            self.spawn_acc = float(native.get("spawn_acc", 0.0))
            self.spin_total = float(native.get("spin_total", 0.0))
            return
        # cross-type: carry the predecessor's gradient so colors are
        # continuous at the switch instant — SpotFX repaints on its next
        # color action and stays the source of truth. Same deal for the
        # rotation sign: the swirl continues the spin the orbits field
        # already had (magnitude stays ours).
        patch = {}
        g = snap.get("gradient")
        if g and g != self._config.get("gradient"):
            patch["gradient"] = g
        spin_sign = float(snap.get("spin_sign") or 0.0)
        if spin_sign and self.swirl and np.sign(self.swirl) != spin_sign:
            patch["swirl"] = abs(self._config["swirl"]) * spin_sign
        if patch:
            # sanctioned in-render config path (we're under the effect lock)
            self._apply_config(patch, validate=False, fire_event=False)
        # blob size eases from the predecessor's to ours over the wind-up
        size_from = snap.get("blob_size")
        if size_from and size_from != self.blob_size:
            self._adopt_size_from = float(size_from)
        if snap["src"] == "radial":
            # "suck in then erupt": the collapsing radial owns phase 1, so
            # hold our eruption until it has pinched out — no wind-up here,
            # the burst should fly at full speed
            c_px = snap.get("center_px") or (self.cx, self.cy)
            ncx = (float(c_px[0]) - self.cx) / max(self.sx, 1e-6)
            ncy = (float(c_px[1]) - self.cy) / max(self.sy, 1e-6)
            if live and particle_handoff.transition_progress(virtual) is not None:
                self._erupt_hold = {
                    "ncx": ncx,
                    "ncy": ncy,
                    "t0": particle_handoff.now(),
                }
            else:
                self._erupt_burst(ncx, ncy)
            return
        # re-normalize pixel positions into our polar space and let the
        # imported particles join the normal infall/eruption flow. Adopt
        # EVERY inherited blob (max_blobs only gates fresh spawns) — nothing
        # on screen should vanish at the switch.
        k = min(len(snap["px"]), CAP)
        if k <= 0:
            return
        gx = (snap["px"][:k] - self.cx) / max(self.sx, 1e-6)
        gy = (snap["py"][:k] - self.cy) / max(self.sy, 1e-6)
        r = np.sqrt(gx**2 + gy**2).astype(np.float32)
        # keep imported blobs inside the alive bounds of every mode; blobs
        # past the unit rim (orbits' field is wider) stay where they are
        # instead of teleporting inward
        self.p_r[:k] = np.clip(r, self.kill_radius + 0.02, self.r_max - 0.02)
        self.p_theta[:k] = np.arctan2(gy, gx).astype(np.float32)
        self.p_grad[:k] = snap["grad"][:k]
        self.p_bright[:k] = np.clip(snap["bright"][:k], 0.3, 1.0)
        self.p_age[:k] = FADE_IN_S  # no fade-in flash
        self.p_band[:k] = 0
        self.p_cap[:k] = -1.0
        self.p_is_burst[:k] = False  # adopted blobs are ordinary population
        self.p_turn[:k] = False      # ... and never mid-turnaround
        self.p_vr[:k] = 0.0
        self.n = k
        # adopted particles wind up to full speed over handoff_ease seconds
        self._adopt_age = 0.0 if self.handoff_ease > 0.0 else None

    def _arm_reverse_fallback(self, n, v_out):
        """Consume a reverse True->False edge: every live blob was flowing
        OUTWARD an instant ago (that is what `reverse` means for motion),
        so each one enters the turnaround carrying exactly the outward
        speed it had — the seam is continuous by construction, there is no
        moment where anything is handed a velocity it did not already
        have.

        CAPTIVES ARE NOT RELEASED HERE — deliberately, and this is the
        hazard PR #179 walked into (reverted same day by #181 with no
        recorded reason). The defect #179 correctly diagnosed is real: a
        horizon captive keeps `cap >= 0` while reversed (the capture
        branch is skipped entirely in reverse), so on the flip back
        `np.where(captured, rh, new_r)` used to teleport it from wherever
        the outflow had carried it straight back onto the ring in ONE
        frame. #179 fixed that by clearing EVERY captive on EVERY frame
        while reversed, which does more than remove the teleport:

          * it evicts blobs still sitting ON the ring, which the flare had
            not moved at all — their horizon colour blend and their hold
            clock both restart, so every flare strips and repopulates the
            ring;
          * an evicted captive is `cap = -1`, and a free-falling blob is
            IMMORTAL in infall mode (the alive test retires captives by
            their hold clock, never free-fallers) — so each flare also
            converts the whole aged ring population back into blobs that
            can never retire, and they re-capture with a FRESH full hold.
            Repeated over a song, the ring stops turning over.

        This mechanism releases nothing. `cap` is untouched: the fix is in
        the capture branch, which now pins a captive to the ring only
        while it is actually AT the ring (within REVERSE_FALLBACK_RING_TOL
        of it). A captive the outflow carried off the ring keeps its
        capture, its colour blend and its hold clock, turns around like
        every other blob, and is re-pinned when it arrives back — no
        teleport, no colour pop, no eviction, and the population turnover
        this effect has always had is unchanged.
        """
        if n <= 0:
            return
        # an eruption/drop-burst blob is flying at its own boosted speed
        # (draw()'s out_mask branch) — fold that ACTUAL speed into the
        # turn, not the ambient one, or its velocity would step at the
        # edge. p_out is then cleared: one mechanism owns the motion.
        out_speed = np.where(
            self.p_out[:n] > 0.0,
            np.where(self.p_is_burst[:n], PHASE_BURST_SPEED_MULT, 1.0),
            1.0,
        )
        self.p_vr[:n] = (v_out * out_speed).astype(np.float32)
        self.p_turn[:n] = True
        self.p_out[:n] = 0.0
        self._turn_active = True

    def _erupt_burst(self, ncx, ncy):
        """Center eruption after a radial handoff: a burst of full-bright
        blobs appears at the predecessor's center. In reverse mode they ride
        the native outward flow; in infall mode p_out gives them a short
        outward flight, after which they stall and fall back in."""
        base = self.n
        burst = min(particle_handoff.BURST_N, self.max_blobs, CAP - base)
        if burst <= 0:
            return
        self._spawn(burst, burst)
        got = self.n - base
        if got <= 0:
            return
        s = slice(base, self.n)
        rng = self._rng
        jr = rng.uniform(0.0, 0.05, got)
        jth = rng.uniform(0.0, 2 * np.pi, got)
        px = ncx + jr * np.cos(jth)
        py = ncy + jr * np.sin(jth)
        inner = (
            self._horizon_radius()
            if (self.horizon_scale > 0 and not self.reverse)
            else self.kill_radius
        )
        self.p_r[s] = np.maximum(
            np.sqrt(px**2 + py**2), inner + 0.02
        ).astype(np.float32)
        self.p_theta[s] = np.arctan2(py, px).astype(np.float32)
        if not self.reverse:
            self.p_out[s] = rng.uniform(0.35, 0.9, got).astype(np.float32)
            self._out_active = True

    # ── charge/lull/drop choreography ───────────────────────────────────
    # SpotFX writes `phase` (instant) and ramps `phase_progress` 0→1 over
    # the event's ramp. charge: forced infall while the horizon swallows the
    # panel; lull: held full-screen black; drop: the horizon pinches to a
    # point, a center burst erupts, then the horizon eases back to baseline
    # and `phase` self-resets to "none" (so an identical later write edges).

    def _enter_phase(self, phase):
        self._phase = phase
        self._phase_t = 0.0
        self._phase_done_t = None
        if phase == "charge":
            self._drop = None
            # charge always falls inward; remember the configured direction
            # and restore it when the drop pays off
            if self.reverse:
                self._phase_saved.setdefault("reverse", True)
                self._apply_config(
                    {"reverse": False}, validate=False, fire_event=False
                )
        elif phase == "drop":
            self._drop = {"burst_t": None}
        elif phase == "none":
            self._drop = None
            self._restore_phase_overrides()

    def _restore_phase_overrides(self):
        saved = self._phase_saved
        if saved:
            self._phase_saved = {}
            # sanctioned in-render config path (we're under the effect lock)
            self._apply_config(dict(saved), validate=False, fire_event=False)

    def _blob_rush(self, count):
        """BLOB RUSH: `count` blobs at once, spread fairly evenly around
        the circle (his ask, 2026-08-24 — see BLOB_RUSH_WIGGLE_FRAC).
        Bypasses max_blobs via _spawn's no-cap tag, so the rush never eats
        the ambient population's budget and nothing already on screen is
        touched. Placement follows the mode the effect is actually in: in
        infall they arrive from the true per-direction hex boundary (the
        same _hex_spawn_edge_radius spawn an ordinary blob uses, so a rush
        reads as a wave arriving from the edge), in reverse they leave from
        the horizon ring."""
        count = int(min(count, CAP - self.n))
        if count <= 0:
            return 0
        rng = self._rng
        step = 2.0 * np.pi / count
        theta = (
            rng.uniform(0.0, 2.0 * np.pi)
            + np.arange(count) * step
            + rng.uniform(-BLOB_RUSH_WIGGLE_FRAC, BLOB_RUSH_WIGGLE_FRAC,
                          count) * step
        ) % (2.0 * np.pi)
        before = self.n
        self._spawn(count, 0, theta=theta, ignore_cap=True)
        return self.n - before

    def _phase_burst(self):
        """Drop payoff: a guaranteed burst of full-bright blobs from the
        center (bypasses max_blobs — the explosion must always land).
        Tagged p_is_burst so the ambient spawn's own max_blobs check (see
        _spawn) doesn't count these against the population budget the
        music-driven blobs need to keep coming through right after —
        otherwise doubling PHASE_BURST_N would starve the very spawns that
        are supposed to fill the post-explosion gap."""
        got = int(min(PHASE_BURST_N, CAP - self.n))
        if got <= 0:
            return
        s = slice(self.n, self.n + got)
        rng = self._rng
        self.p_r[s] = rng.uniform(0.02, 0.10, got).astype(np.float32)
        self.p_theta[s] = rng.uniform(0.0, 2 * np.pi, got).astype(np.float32)
        self.p_age[s] = FADE_IN_S  # no fade-in flash on the payoff
        self.p_cap[s] = -1.0
        self.p_band[s] = 0
        self.p_is_burst[s] = True
        self.p_turn[s] = False
        self.p_vr[s] = 0.0
        if self.color_mode == "wheel":
            self.p_grad[s] = (
                self.p_theta[s] / (2 * np.pi) - self.spin_total
            ) % 1.0
        else:
            self.p_grad[s] = rng.random(got, dtype=np.float32)
        self.p_bright[s] = 1.0
        # Halved to pair with draw()'s PHASE_BURST_SPEED_MULT-scaled
        # velocity for these same (p_is_burst) particles — same outward
        # reach, half the time (see the constant's own docstring).
        self.p_out[s] = (
            rng.uniform(0.4, 1.1, got) / PHASE_BURST_SPEED_MULT
        ).astype(np.float32)
        self.n += got
        self._out_active = True

    def _phase_step(self, dt):
        """Advance the charge/lull/drop state machine. Runs every draw,
        before the horizon radius is sampled."""
        pend = self._phase_pending
        if pend is not None:
            self._phase_pending = None
            if pend != self._phase:
                self._enter_phase(pend)
        if self._phase == "none":
            return
        self._phase_t += dt
        # orphan watchdog: a charge/lull whose payoff never arrives
        # releases itself as a silent drop (pinch + reset, no burst)
        due, self._phase_done_t = particle_handoff.phase_release_due(
            self._phase, self.phase_progress, self._phase_t,
            self._phase_done_t,
        )
        if due:
            _LOGGER.info(
                "blackhole: %s watchdog release after %.1fs",
                self._phase, self._phase_t,
            )
            self._phase = "drop"
            self._phase_t = 0.0
            self.phase_progress = 0.0
            self._drop = {"burst_t": None, "silent": True}
            # No `return` here, unlike the other early-outs in this method:
            # falling through into the "drop" branch below is what resolves
            # burst_t out of its None sentinel on THIS SAME call, before
            # draw() goes on to call _horizon_radius()/_phase_halo() this
            # frame. A prior version returned here, leaving burst_t=None
            # observable for one frame — draw() always reads it before the
            # next _phase_step() call has a chance to self-heal, so it
            # crashed instead (TypeError: None / float).
        if self._phase == "drop":
            drop = self._drop
            if drop is None:
                drop = self._drop = {"burst_t": None}
            if drop["burst_t"] is None:
                # DROP ANCHORS ITS START TO THE MARK (his ruling,
                # 2026-08-20, data/drops-still-fire-early-star-does-not-
                # explode/ — Black Hole was tried as the "known-good" drop
                # reference and then withdrawn when he found it early too):
                # the burst fires on the very first _phase_step after
                # entering "drop", unconditionally — the SAME shape
                # orbits.py's own drop branch already used (its
                # `burst_done` flag). This REPLACES the old progress-gated
                # pinch-then-burst (`p >= 0.995`, DROP_FALLBACK_S) that
                # anchored the payoff to the RAMP'S END instead — that
                # anchor was his own prior ask, and is now superseded, not
                # merely unused: don't reintroduce it.
                drop["burst_t"] = 0.0
                self.p_cap[: self.n] = -1.0
                self._restore_phase_overrides()
                if not drop.get("silent"):
                    self._phase_burst()
            else:
                drop["burst_t"] += dt
                if drop["burst_t"] >= DROP_RESET_S:
                    self._phase = "none"
                    self._drop = None
                    self._apply_config(
                        {"phase": "none", "phase_progress": 0.0},
                        validate=False,
                        fire_event=False,
                    )

    def _phase_spawn_paused(self, rh):
        """Ambient spawning pauses while the panel is swallowed (lull, late
        charge). The drop clause is a defensive no-op in the current
        design (burst_t lands in the same _phase_step call that enters
        "drop" — see that method — so there is no live pre-burst window
        left to pause spawning during); kept so a future change to when
        the burst fires doesn't silently let ambient spawn clutter the
        payoff's very first frame again."""
        if self._phase == "lull":
            return True
        if self._phase == "charge" and rh >= 1.0:
            return True
        if self._phase == "drop":
            drop = self._drop
            return drop is None or drop["burst_t"] is None
        return False

    def _horizon_radius(self):
        """Current event-horizon radius: baseline scaled by the audio impulse
        (grows with sound when horizon_audio is positive). The charge/lull/
        drop phases override it: growth to full-panel, hold, pinch + reset."""
        base = float(
            np.clip(
                self.horizon_scale * (1.0 + self.horizon_audio * self.impulse),
                0.02,
                0.9,
            )
        )
        phase = getattr(self, "_phase", "none")
        if phase == "none":
            return base
        top = float(getattr(self, "r_max", 1.5))
        if phase == "charge":
            p = float(np.clip(self.phase_progress, 0.0, 1.0))
            # quadratic swallow, with the halo (this capture ring) leading
            # the black disc (_disc_radius) by CHARGE_HALO_LEAD — the glow
            # sweeps the panel ahead of the dark
            return base + (top - base) * min(
                CHARGE_HALO_LEAD * p * p, 1.0
            )
        if phase == "lull":
            return top
        # drop: the burst fires (and the horizon starts easing back from
        # zero) on the very first frame of the phase — see _phase_step's
        # own docstring on why there is no pre-burst pinch state left to
        # compute here.
        #
        # burst_t is only ever None as a same-call sentinel inside
        # _phase_step's own drop branch, which always resolves it to 0.0
        # (a real float) before returning — every path that sets
        # self._drop to {"burst_t": None, ...} falls through into that
        # resolution in the SAME _phase_step() call, and draw() only ever
        # calls this method after _phase_step() has run for the frame. So
        # by the time we get here, burst_t is never actually None; the
        # `or 0.0` below is a guard against that invariant regressing
        # again (a 2026-08-20 bug had one such path `return` before
        # reaching the resolution, leaving None observable for a frame —
        # TypeError: None / float, crashing the render thread). If it ever
        # does fire, 0.0 is the CORRECT value, not a fudge: it's exactly
        # what burst_t is resolved to an instant later in the same
        # scenario, i.e. "the drop just started, ease-back hasn't begun" —
        # never the old pre-#160 meaning ("still pinching down from the
        # full panel"), which this redesign retired along with the
        # progress-gated burst it went with.
        drop = self._drop
        burst_t = drop["burst_t"] if drop is not None else 0.0
        if burst_t is None:
            burst_t = 0.0
        return base * min(burst_t / DROP_RESET_S, 1.0)

    def _phase_halo(self, out, rh):
        """Explicit halo ring painted at the horizon radius. The blob-built
        halo only exists when music is feeding captures, so this guarantees
        the charge build (and the drop pinch) reads even in silence: the
        ring grows brighter and thicker as the charge progresses, collapses
        at full brightness with the drop, and fades out as the horizon eases
        back after the burst."""
        phase = self._phase
        if phase == "charge":
            p = float(np.clip(self.phase_progress, 0.0, 1.0))
            w = 0.05 + 0.17 * p    # half-thickness (normalized radius)
            b = 0.30 + 0.70 * p    # brightness scale
        elif phase == "drop":
            # post-burst fade only — the burst fires on the phase's first
            # frame (see _phase_step), so there is no pre-burst pinch state
            # left for the halo to render here. burst_t is never actually
            # None by the time draw() gets here — see _horizon_radius's own
            # comment for the invariant and why 0.0 is the right fallback,
            # not a fudge, on the off chance it ever is.
            drop = self._drop
            burst_t = drop["burst_t"] if drop is not None else 0.0
            if burst_t is None:
                burst_t = 0.0
            w = 0.10
            b = 0.6 * max(1.0 - burst_t / DROP_RESET_S, 0.0)
        else:
            return
        if b <= 0.0:
            return
        d = np.abs(self.grid_r - rh)
        glow = np.clip(1.0 - d / w, 0.0, 1.0) ** 1.5
        out += glow[..., None] * (self.horizon_rgb[None, None, :] * b)

    def _disc_radius(self, rh):
        """Painted black-disc radius. Equals the horizon everywhere except
        during a charge, where the halo (capture ring, `rh`) grows
        quadratically with a head start and the disc follows on the plain
        quadratic — the glowing ring visibly outruns the black."""
        if getattr(self, "_phase", "none") != "charge":
            return rh
        base = float(
            np.clip(
                self.horizon_scale * (1.0 + self.horizon_audio * self.impulse),
                0.02,
                0.9,
            )
        )
        top = float(getattr(self, "r_max", 1.5))
        p = float(np.clip(self.phase_progress, 0.0, 1.0))
        return base + (top - base) * p * p

    def _spawn(self, count, beat_count, *, theta=None, ignore_cap=False):
        """max_blobs is the user-facing density cap; CAP is the hard buffer
        cap. The cap counts only ambient (non-burst) population — a drop's
        _phase_burst blobs are excluded (see its own docstring) so a large
        surviving burst can never pause the music-driven ambient/beat
        spawn this function drives; CAP - self.n still bounds the total
        buffer regardless of tag.

        `ignore_cap` spawns straight past max_blobs and tags the result
        p_is_burst — the same no-cap treatment, for the blob rush (his
        "Override any max blob counts for this generation"). `theta`
        (optional) places the new blobs at chosen angles instead of
        uniformly random ones — the rush's even spread; colours are still
        baked from the angle actually used, so a wheel gradient stays
        consistent with where each blob sits.

        int(): morph smoothing can hand us float counts, which numpy's rng
        size argument rejects."""
        ambient_n = self.n - int(np.count_nonzero(self.p_is_burst[: self.n]))
        room = (CAP - self.n) if ignore_cap else min(
            self.max_blobs - ambient_n, CAP - self.n)
        count = int(min(count, room))
        if count <= 0:
            return
        s = slice(self.n, self.n + count)
        rng = self._rng
        self.p_is_burst[s] = ignore_cap
        # theta drawn first (both branches want it) — infall mode needs it
        # to look up the boundary at each particle's own spawn direction.
        theta = (
            rng.uniform(0.0, 2 * np.pi, count).astype(np.float32)
            if theta is None
            else np.asarray(theta, dtype=np.float32)[:count]
        )
        if self.reverse:
            # With an event horizon, eruptions come from the horizon ring.
            inner = (
                self._horizon_radius()
                if self.horizon_scale > 0
                else self.kill_radius
            )
            self.p_r[s] = rng.uniform(inner, inner + 0.06, count)
        else:
            # Just past the true per-direction hex boundary (see
            # HEX_SPAWN_VERTS above) — evaluated per particle since the
            # boundary itself depends on theta, not a single annulus.
            edge_r = _hex_spawn_edge_radius(theta)
            self.p_r[s] = edge_r + rng.uniform(
                SPAWN_EDGE_MARGIN_MIN, SPAWN_EDGE_MARGIN_MAX, count
            ).astype(np.float32)
        self.p_theta[s] = theta
        self.p_age[s] = 0.0
        self.p_cap[s] = -1.0
        self.p_out[s] = 0.0
        self.p_turn[s] = False
        self.p_vr[s] = 0.0

        # spin_total is baked in at spawn: colors travel WITH the blobs, so
        # a spinning gradient shows as rotating color arms, not in-place
        # hue cycling.
        if self.color_mode == "band":
            weights = self.band_powers + 0.05
            weights = weights / weights.sum()
            bands = rng.choice(3, size=count, p=weights)
            self.p_band[s] = bands
            self.p_grad[s] = (
                BAND_ANCHORS[bands]
                + rng.uniform(-BAND_JITTER, BAND_JITTER, count).astype(
                    np.float32
                )
                + self.spin_total
            ) % 1.0
            self.p_bright[s] = 0.6 + 0.4 * self.band_powers[bands]
        elif self.color_mode == "wheel":
            # Gradient wrapped around the circle: blobs sample by spawn
            # angle, so gradient_spin visibly rotates the color wheel.
            self.p_band[s] = 0
            # minus spin_total so the wheel pattern rotates in the same
            # screen direction as the swirl
            self.p_grad[s] = (
                self.p_theta[s] / (2 * np.pi)
                + rng.uniform(-0.04, 0.04, count).astype(np.float32)
                - self.spin_total
            ) % 1.0
            self.p_bright[s] = rng.uniform(0.7, 1.0, count)
        else:  # random — pure uniform; gradient_spin has no visible effect
            self.p_band[s] = 0
            self.p_grad[s] = rng.random(count, dtype=np.float32)
            self.p_bright[s] = rng.uniform(0.6, 1.0, count)

        if beat_count > 0:
            self.p_bright[self.n + count - beat_count : self.n + count] = 1.0
        self.n += count

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
        if not np.isfinite(self.spin_total):
            self.spin_total = 0.0

        self._phase_step(dt)
        horizon_on = self.horizon_scale > 0.0 or self._phase != "none"
        rh = self._horizon_radius() if horizon_on else 0.0
        swirl_sign = np.sign(self.swirl) if self.swirl != 0 else 1.0
        # Consumed unconditionally, even with no live particles: an edge
        # left armed would fire against an unrelated population later.
        rev_edge = self._reverse_edge
        self._reverse_edge = None

        # post-adoption wind-up: motion eases from frozen to full speed so a
        # handoff reads as a morph, not an instant physics jump
        wind = 1.0
        if self._adopt_age is not None:
            self._adopt_age += dt
            if self._adopt_age >= self.handoff_ease:
                self._adopt_age = None
            else:
                # ease-OUT: adopted particles start moving immediately and
                # settle to full speed (a smoothstep start reads as a hang)
                w = self._adopt_age / self.handoff_ease
                wind = w * (2.0 - w)

        virtual = self._virtual
        # collapse latch: we are the outgoing crossfade sibling and radial
        # is incoming — particles break orbit and spiral into its center
        if self._collapse is None:
            inc = particle_handoff.incoming_sibling(virtual, self)
            if inc is not None and getattr(inc, "NAME", None) == "Radial":
                n0 = self.n
                t_px = self.r_width * float(inc._config.get("x_offset", 0.5))
                t_py = self.r_height * float(inc._config.get("y_offset", 0.5))
                tx = (t_px - self.cx) / max(self.sx, 1e-6)
                ty = (t_py - self.cy) / max(self.sy, 1e-6)
                px = self.p_r[:n0] * np.cos(self.p_theta[:n0])
                py = self.p_r[:n0] * np.sin(self.p_theta[:n0])
                self._collapse = {
                    "rho0": np.hypot(px - tx, py - ty).astype(np.float32),
                    "phi0": np.arctan2(py - ty, px - tx).astype(np.float32),
                    "bright0": self.p_bright[:n0].copy(),
                    "tx": tx,
                    "ty": ty,
                    "frac0": particle_handoff.transition_progress(virtual)
                    or 0.0,
                    "t0": particle_handoff.now(),
                    "spin": float(np.sign(self.swirl)) or 1.0,
                }
                # release horizon captives: the render tail then treats
                # every blob as free-falling during the gather
                self.p_cap[:n0] = -1.0
        elif getattr(virtual, "_transition_effect", None) is not self:
            self._collapse = None
        col = self._collapse

        # held eruption: a collapsing radial predecessor owns phase 1
        holding = False
        if self._erupt_hold is not None:
            hold = self._erupt_hold
            frac = particle_handoff.transition_progress(virtual)
            if getattr(virtual, "_transition_effect", None) is self:
                # switched away mid-hold — no burst
                self._erupt_hold = None
            elif (
                frac is None
                or frac >= particle_handoff.BLOOM_START
                or particle_handoff.now() - hold["t0"]
                > particle_handoff.ERUPT_HOLD_MAX_S
            ):
                self._erupt_hold = None
                self._erupt_burst(hold["ncx"], hold["ncy"])
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

        n = self.n
        # ── update ──────────────────────────────────────────────────────
        if n and col is not None:
            # analytic gather: physics is replaced by a guaranteed-arrival
            # spiral into the radial's center, pinching bright
            frac = particle_handoff.transition_progress(virtual)
            if frac is not None:
                s_ = float(
                    np.clip(
                        (frac - col["frac0"])
                        / max(
                            particle_handoff.GATHER_FRAC - col["frac0"],
                            1e-3,
                        ),
                        0.0,
                        1.0,
                    )
                )
                p2 = float(
                    np.clip(
                        (frac - particle_handoff.GATHER_FRAC)
                        / (1.0 - particle_handoff.GATHER_FRAC),
                        0.0,
                        1.0,
                    )
                )
            else:
                t = particle_handoff.now() - col["t0"]
                s_ = min(t / particle_handoff.COLLAPSE_FALLBACK_S, 1.0)
                p2 = min(
                    max(
                        (t - particle_handoff.COLLAPSE_FALLBACK_S) / 0.5,
                        0.0,
                    ),
                    1.0,
                )
            e = s_ * s_ * (3.0 - 2.0 * s_)
            k = min(len(col["rho0"]), n)
            # small residual radius: the pinch stays a visibly swirling
            # knot instead of a frozen point while it fades out
            rho = col["rho0"][:k] * (1.0 - s_) ** 2 + 0.05 * e
            # the pinch keeps rotating through phase 2 (a frozen bright
            # point while fading reads as a hang)
            phi = (
                col["phi0"][:k]
                + col["spin"]
                * 2.0
                * np.pi
                * (particle_handoff.SWIRL_TURNS * e + 0.35 * p2)
            )
            x = col["tx"] + rho * np.cos(phi)
            y = col["ty"] + rho * np.sin(phi)
            r0 = self.p_r[:n].copy()
            th0 = self.p_theta[:n].copy()
            new_th = np.arctan2(y, x).astype(np.float32)
            self.p_r[:k] = np.hypot(x, y).astype(np.float32)
            # shortest-way theta so the substep smear can't cross the ±π
            # branch cut and paint across the whole circle
            self.p_theta[:k] = th0[:k] + (
                ((new_th - th0[:k] + np.pi) % (2.0 * np.pi)) - np.pi
            )
            self.p_age[:n] += dt
            self.p_bright[:k] = np.minimum(
                col["bright0"][:k] * (1.0 + 0.6 * e), 1.0
            ) * (1.0 - p2)
        elif n:
            r = self.p_r[:n]
            cap = self.p_cap[:n]
            r0 = r.copy()
            th0 = self.p_theta[:n].copy()
            # edge_speed sets the rim/center speed ratio: a low floor makes
            # blobs linger at the rim and pile up (density!), so it defaults
            # to a healthy 0.25 and is directly tunable.
            v = self.base_speed * (
                self.edge_speed
                + (1.0 - self.edge_speed)
                * np.clip(1.0 - r, 0.0, 1.0) ** self.accel
            )
            v = v * (1.0 + self.speed_audio * self.impulse * 2.0) * wind
            omega = np.clip(
                self.swirl * v / np.maximum(r, R_FLOOR),
                -OMEGA_MAX,
                OMEGA_MAX,
            )
            new_r = r + (v if self.reverse else -v) * dt

            # ── reverse release: turn around, never flip ────────────────
            if rev_edge == "fallback":
                self._arm_reverse_fallback(n, v)
            elif rev_edge == "eject":
                # the flare's own outward kick is INSTANT by design (his
                # words: "I like how on reverse, the event horizon
                # immediately ejects blobs") — a turn in flight is
                # abandoned to it, not eased into.
                self.p_turn[:n] = False
                self._turn_active = False
            if self._turn_active:
                turn = self.p_turn[:n]
                if turn.any():
                    # Decelerate under the speed curve's own scale (see
                    # REVERSE_FALLBACK_TURN_S) and merge the instant the
                    # velocity reaches the infall speed for this radius:
                    # the very value the plain `-v` branch will apply on
                    # the next frame, so the handoff has no step in it.
                    vr = self.p_vr[:n] - (
                        2.0 * v / REVERSE_FALLBACK_TURN_S
                    ) * dt
                    merged = vr <= -v
                    vr = np.where(merged, -v, vr).astype(np.float32)
                    self.p_vr[:n] = np.where(turn, vr, self.p_vr[:n])
                    new_r = np.where(turn, r + vr * dt, new_r)
                    turn = turn & ~merged
                    self.p_turn[:n] = turn
                    self._turn_active = bool(turn.any())
                else:
                    self._turn_active = False

            out_mask = None
            if self._out_active:
                out_mask = self.p_out[:n] > 0.0
                if out_mask.any():
                    # eruption-burst blobs fly outward; when their time
                    # expires they stall and rejoin the normal infall.
                    # Drop-payoff bursts (_phase_burst, tagged p_is_burst)
                    # fly PHASE_BURST_SPEED_MULT times faster — paired with
                    # _phase_burst's halved p_out so the reach is unchanged,
                    # just twice as fast. _erupt_burst's cross-effect
                    # handoff eruptions share out_mask/p_out but are never
                    # tagged p_is_burst, so they keep their original speed.
                    out_speed = np.where(
                        self.p_is_burst[:n], PHASE_BURST_SPEED_MULT, 1.0
                    )
                    new_r = np.where(
                        out_mask, r + v * out_speed * dt, new_r
                    )
                    self.p_out[:n] = np.maximum(self.p_out[:n] - dt, 0.0)
                else:
                    self._out_active = False
                    out_mask = None

            if horizon_on and not self.reverse:
                # Falling blobs are captured into orbit at the horizon
                free = (cap < 0) & (new_r <= rh)
                if out_mask is not None:
                    free &= ~out_mask
                cap[free] = 0.0
                captured = cap >= 0
                # Pinned to the ring only while actually AT the ring. A
                # captive the reverse flare's outflow carried off it keeps
                # its capture (colour blend, hold clock, retirement all
                # continue) but falls/turns back under ordinary physics
                # instead of being teleported onto the ring — see
                # _arm_reverse_fallback's docstring for why releasing it
                # instead (PR #179) costs more than it fixes. In ordinary
                # infall this is inert: a pinned orbiter sits exactly at
                # rh, so it is always within tolerance.
                pinned = captured & (
                    new_r <= rh + REVERSE_FALLBACK_RING_TOL)
                # a blob that finished its fall back into the horizon is
                # done turning — the ring owns its radius from here
                if self._turn_active:
                    self.p_turn[:n] &= ~pinned
                    self._turn_active = bool(self.p_turn[:n].any())
                new_r = np.where(pinned, rh, new_r)
                v_h = (
                    self.base_speed
                    * (
                        self.edge_speed
                        + (1.0 - self.edge_speed)
                        * max(0.0, 1.0 - rh) ** self.accel
                    )
                    * (1.0 + self.speed_audio * self.impulse * 2.0)
                    * wind
                )
                omega_h = np.clip(
                    (self.swirl if self.swirl != 0 else 1.0)
                    * v_h
                    / max(rh, R_FLOOR),
                    -OMEGA_MAX,
                    OMEGA_MAX,
                )
                # an off-ring captive swirls by its OWN radius (the plain
                # omega above); only a pinned orbiter takes the ring's.
                # Its hold clock keeps running either way — the capture is
                # never interrupted, only its radius stops being forced.
                omega = np.where(pinned, omega_h, omega)
                cap[captured] += dt

            self.p_r[:n] = new_r
            self.p_theta[:n] = th0 + omega * dt
            self.p_age[:n] += dt

            if self.reverse:
                # live until past the farthest panel corner, not the
                # inscribed rim — outflow visibly exits through the corners
                alive = self.p_r[:n] < self.r_max
            elif horizon_on:
                # orbiters retire after horizon_hold (+ fade); free-fallers
                # can't cross the horizon so they never hit kill_radius
                alive = self.p_cap[:n] < (
                    self.horizon_hold + HORIZON_FADE_S
                )
            else:
                alive = self.p_r[:n] > self.kill_radius
            r0, th0 = self._compact(alive, r0, th0)
            n = self.n

        # ── spawn ───────────────────────────────────────────────────────
        # paused while collapsing into a radial (frozen population reads as
        # a deliberate gather), while holding for a collapsing radial, and
        # while a charge/lull/drop phase owns the screen
        if col is None and not holding and not self._phase_spawn_paused(rh):
            rate = self.spawn_rate * (
                1.0 + self.spawn_audio * self.impulse * 3.0
            )
            self.spawn_acc += rate * dt
            n_new = int(self.spawn_acc)
            self.spawn_acc -= n_new
            beat_count = 0
            if self._beat_pending:
                beat_count = self.beat_burst
                n_new += beat_count
                self._beat_pending = False
            # Gradient spin follows the swirl direction, so the color
            # pattern rotates the same way the blobs do.
            self.spin_total = (
                self.spin_total + self.gradient_spin * swirl_sign * dt
            ) % 1.0
            prev_n = self.n
            self._spawn(n_new, beat_count)
            if self.n > prev_n:
                # Fresh spawns render as stationary points this frame
                fresh = slice(prev_n, self.n)
                r0 = np.concatenate([r0, self.p_r[fresh]]) if prev_n else self.p_r[fresh].copy()
                th0 = np.concatenate([th0, self.p_theta[fresh]]) if prev_n else self.p_theta[fresh].copy()

        # ── blob rush ───────────────────────────────────────────────────
        # A flare-driven "12 blobs, now, evenly spread" write. Deliberately
        # NOT gated by _phase_spawn_paused: like the firework_burst flare
        # (fx/VENDOR.md #15) an explicitly-fired burst still lands during a
        # swallow, the same way the drop payoff itself does. It IS gated by
        # the collapse/hold latches, where physics is replaced wholesale and
        # a fresh spawn would be stranded. Self-reset re-arms the edge; a
        # stale persisted count on a fresh instance (nonzero _rush_seen with
        # nothing pending — the creation baseline armed no spawn) is reset
        # the same way, so the key reads 0 whenever idle.
        if col is None and not holding and (
            self._rush_pending or self._rush_seen
        ):
            pending = self._rush_pending
            self._rush_pending = 0
            if pending:
                prev_n = self.n
                self._blob_rush(pending)
                if self.n > prev_n:
                    fresh = slice(prev_n, self.n)
                    r0 = np.concatenate([r0, self.p_r[fresh]]) if prev_n else self.p_r[fresh].copy()
                    th0 = np.concatenate([th0, self.p_theta[fresh]]) if prev_n else self.p_theta[fresh].copy()
            self._apply_config(
                {"blob_rush": 0}, validate=False, fire_event=False
            )
        n = self.n

        if self.horizon_follow_blobs:
            # same gradient position this frame's fresh spawns are baked
            # with (spin included) — the horizon glow tracks the live blob
            # color instead of a fixed horizon_color
            self.horizon_rgb = self.get_gradient_color_vectorized1d(
                np.array([self.spin_total % 1.0], dtype=np.float32)
            )[0]
        else:
            self.horizon_rgb = self._horizon_rgb_explicit

        # ── render ──────────────────────────────────────────────────────
        half_life = 0.02 + self.trail_decay * 0.5
        self.trail *= np.float32(0.5 ** (dt / half_life))

        if n:
            # Colors are baked at spawn (spin included), so they travel with
            # the blobs and a spinning gradient reads as rotating arms.
            rgb = self.get_gradient_color_vectorized1d(
                self.p_grad[:n]
            ).astype(np.float32)
            fade = np.minimum(self.p_age[:n] / FADE_IN_S, 1.0)
            if horizon_on and not self.reverse:
                # Orbiting blobs morph to the horizon color, then fade out
                # after horizon_hold.
                cap = self.p_cap[:n]
                captured = cap >= 0
                blend = np.where(
                    captured, np.clip(cap / HORIZON_BLEND_S, 0.0, 1.0), 0.0
                )
                rgb = (
                    rgb * (1.0 - blend[:, None])
                    + self.horizon_rgb[None, :] * blend[:, None]
                )
                fade = fade * np.where(
                    captured,
                    np.clip(
                        1.0 - (cap - self.horizon_hold) / HORIZON_FADE_S,
                        0.0,
                        1.0,
                    ),
                    1.0,
                )
            rgb *= (self.p_bright[:n] * fade)[:, None]

            # Sub-sample each particle's path this frame: stationary blobs
            # stack to full brightness, fast ones smear their energy along
            # the path (natural motion-blur stretch).
            fractions = (
                np.arange(1, SUBSTEPS + 1, dtype=np.float32) / SUBSTEPS
            )
            ri = r0[:, None] + (self.p_r[:n] - r0)[:, None] * fractions
            thi = th0[:, None] + (self.p_theta[:n] - th0)[:, None] * fractions
            x = self.cx + ri * np.cos(thi) * self.sx
            y = self.cy + ri * np.sin(thi) * self.sy

            # blob size eases from an adopted predecessor's size to ours
            # along the same wind-up curve as the motion
            blob = self.blob_size
            if self._adopt_size_from is not None:
                if self._adopt_age is None:
                    self._adopt_size_from = None
                else:
                    blob = min(
                        self._adopt_size_from
                        + (self.blob_size - self._adopt_size_from) * wind,
                        float(KERNEL_R),
                    )
            keep = self.k_dist <= blob
            k_dx = self.k_dx[keep]
            k_dy = self.k_dy[keep]
            k_weight = (
                1.0 - self.k_dist[keep] / (blob + 0.5)
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
            # Per-channel bincount scatter — ~6x faster than np.add.at here.
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
            # Bright current blobs over a fading history, bounded.
            np.maximum(self.trail, np.minimum(frame, 255.0), out=self.trail)

            self.p_theta[:n] %= 2 * np.pi

        out = np.asarray(self.matrix, dtype=np.float32) + self.trail
        # explicit charge/drop halo ring, painted under the disc so the
        # black swallows its inner tail with a crisp edge
        if col is None and self._phase != "none":
            self._phase_halo(out, rh)
        # (disc suppressed while collapsing — it would black out exactly
        # where the particles are converging)
        if horizon_on and col is None:
            # The inside of the black hole shows the background color —
            # a flat disc just inside the horizon ring (covers trails too).
            # During a charge the disc lags the halo, which sweeps ahead.
            inside = self.grid_r < (self._disc_radius(rh) - 0.01)
            out[inside] = getattr(self, "_bg_color", np.zeros(3))
        self.matrix = Image.fromarray(
            np.clip(out, 0, 255).astype(np.uint8), "RGB"
        )
