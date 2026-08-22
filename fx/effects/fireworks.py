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

# Every per-particle SoA array, in one place so compaction and the particle
# handoff native snapshot can never drift out of sync with each other.
_SOA_NAMES = (
    "p_x", "p_y", "p_vx", "p_vy", "p_age", "p_life",
    "p_grad", "p_bright", "p_shown", "p_rev", "p_rocket", "p_nocap",
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
        # orbits: every particle explodes as its own firework, keeping
        # its color for the whole burst
        m = len(xs)
        if m <= 0:
            return
        per = int(np.clip(self.max_blobs // max(m, 1), 4, self.burst_size))
        order = np.argsort(snap["bright"])[::-1]
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
        # progress-driven once it moves (hand-scrubbable in the LedFX UI);
        # the wall-clock fallback only runs while progress sits at 0 so a
        # lost ramp still flies the rockets in
        p = float(np.clip(self.phase_progress, 0.0, 1.0))
        f = p if p > 0.0 else min(self._phase_t / LULL_FLIGHT_S, 1.0)
        ease = 1.0 - (1.0 - f) ** 2  # launch fast, drift into the target
        self.p_x[idx] = path["sx"][:m] + (path["ex"][:m] - path["sx"][:m]) * ease
        self.p_y[idx] = path["sy"][:m] + (path["ey"][:m] - path["sy"][:m]) * ease
        self.p_bright[idx] = 1.0 - LULL_ROCKET_FADE * f

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
                    self._launch_rockets()
                elif pend == "drop":
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
                self.p_vx[:n] *= decel
                self.p_vy[:n] *= decel
                self.p_age[:n] += dt
                alive = (self.p_age[:n] < self.p_life[:n]) & (
                    np.hypot(self.p_x[:n], self.p_y[:n]) < self.r_max
                )
                x0, y0 = self._compact(alive, x0, y0)
                n = self.n

            # ── spawn ───────────────────────────────────────────────────
            # paused during a lull: the dark panel belongs to the rockets
            if not holding and self._phase != "lull":
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

        out = np.asarray(self.matrix, dtype=np.float32) + self.trail
        self.matrix = Image.fromarray(
            np.clip(out, 0, 255).astype(np.uint8), "RGB"
        )
