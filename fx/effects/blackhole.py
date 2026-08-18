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
DROP_FALLBACK_S = 0.45   # drop completes on this timer if no progress ramp
DROP_RESET_S = 0.5       # post-burst ease of the horizon back to baseline
PHASE_BURST_N = 24       # blobs in the drop explosion
CHARGE_HALO_LEAD = 1.4   # halo (capture ring) growth vs the black disc

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
    HIDDEN_KEYS = Twod.HIDDEN_KEYS + ["gradient_roll", "color_blend"]
    ADVANCED_KEYS = Twod.ADVANCED_KEYS + [
        "accel",
        "edge_speed",
        "kill_radius",
        "impulse_decay",
        "phase",
        "phase_progress",
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
        else:
            # non-creation pass: a changed phase key arms the edge
            self._phase_pending = new_phase if new_phase != self._phase else None

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
                        "p_age", "p_band", "p_cap", "p_out",
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
        self.n = k
        # adopted particles wind up to full speed over handoff_ease seconds
        self._adopt_age = 0.0 if self.handoff_ease > 0.0 else None

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

    def _phase_burst(self):
        """Drop payoff: a guaranteed burst of full-bright blobs from the
        center (bypasses max_blobs — the explosion must always land)."""
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
        if self.color_mode == "wheel":
            self.p_grad[s] = (
                self.p_theta[s] / (2 * np.pi) - self.spin_total
            ) % 1.0
        else:
            self.p_grad[s] = rng.random(got, dtype=np.float32)
        self.p_bright[s] = 1.0
        self.p_out[s] = rng.uniform(0.4, 1.1, got).astype(np.float32)
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
            return
        if self._phase == "drop":
            drop = self._drop
            if drop is None:
                drop = self._drop = {"burst_t": None}
            if drop["burst_t"] is None:
                # pinch: progress-driven, with a wall-clock fallback so the
                # payoff can never be lost to a dropped ramp
                p = max(
                    self.phase_progress,
                    min(self._phase_t / DROP_FALLBACK_S, 1.0),
                )
                if p >= 0.995:
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
        charge) and during the drop pinch — the payoff burst starts clean."""
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
        # drop
        drop = self._drop
        if drop is not None and drop["burst_t"] is not None:
            # post-burst: ease back up to the configured baseline
            return base * min(drop["burst_t"] / DROP_RESET_S, 1.0)
        p = max(
            self.phase_progress,
            min(getattr(self, "_phase_t", 0.0) / DROP_FALLBACK_S, 1.0),
        )
        return top * (1.0 - p) ** 2

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
            drop = self._drop
            if drop is not None and drop.get("burst_t") is not None:
                # post-burst: fade out as the horizon eases back
                w = 0.10
                b = 0.6 * max(1.0 - drop["burst_t"] / DROP_RESET_S, 0.0)
            else:
                # pinch: full-charge thickness, full bright, collapsing
                w = 0.22
                b = 1.0
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

    def _spawn(self, count, beat_count):
        # max_blobs is the user-facing density cap; CAP is the hard buffer cap.
        # int(): morph smoothing can hand us float counts, which numpy's rng
        # size argument rejects.
        count = int(min(count, self.max_blobs - self.n, CAP - self.n))
        if count <= 0:
            return
        s = slice(self.n, self.n + count)
        rng = self._rng
        # theta drawn first (both branches want it) — infall mode needs it
        # to look up the boundary at each particle's own spawn direction.
        theta = rng.uniform(0.0, 2 * np.pi, count).astype(np.float32)
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

            out_mask = None
            if self._out_active:
                out_mask = self.p_out[:n] > 0.0
                if out_mask.any():
                    # eruption-burst blobs fly outward; when their time
                    # expires they stall and rejoin the normal infall
                    new_r = np.where(out_mask, r + v * dt, new_r)
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
                new_r = np.where(captured, rh, new_r)
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
                omega = np.where(captured, omega_h, omega)
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
